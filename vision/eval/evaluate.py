"""Counting accuracy over recorded video.

Runs the real pipeline — MediaPipe pose, `FrameSampler`, `RepCounter` — over a
set of clips whose true rep count is known, and reports the metrics the
repetition-counting literature uses, so numbers here can be compared with
published ones:

  MAE  mean absolute error on the count
  OBO  off-by-one accuracy: fraction of clips predicted within ±1 rep
  MAPE mean absolute percentage error

Why the whole pipeline and not just the counter: an accuracy figure has to
include the pose stage. Counting perfectly from perfect keypoints says nothing
about counting from what a camera actually produces.

**Calibration is estimated per clip**, from the clip itself: the observed range
of the mean elbow angle. That is a real departure from how the app works, where
the athlete calibrates deliberately, and it flatters the result — the counter is
handed the exact range it is about to be tested on. It is the only option on
third-party footage, and it is why a dataset number is a lower bound on the work
still to do, not a substitute for measuring on a real session.

Usage:
    python -m vision.eval.evaluate manifest.json [--out results.json] [--limit N]

Manifest format (JSON):
    {"clips": [{"path": "clips/pullup_01.mp4", "reps": 8, "exercise": "pull_up"}]}
Paths are resolved relative to the manifest, or to `--clips-root` when given.
When a clip is not where the manifest says, the file is looked up by name under
that root before being declared missing — see `_index_by_name`.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

from iacoach.classify import Classification, ExerciseClassifier
from iacoach.contracts import Exercise, FrameSample
from iacoach.evaluation import (
    ClipResult,
    detection_summary,
    orientation_summary,
    score_samples,
    segment_stability,
    summarise,
    summarise_out_of_domain,
)
from iacoach.frame import LANDMARK, FrameSampler, Landmark
from iacoach.tracking import SubjectTracker


def _landmarks(proto: Any) -> list[Landmark]:
    return [Landmark(lm.x, lm.y, lm.z, getattr(lm, "visibility", None)) for lm in proto]


def _segment_lengths(world: list[Landmark]) -> dict[str, float]:
    """Metric length of each rigid arm segment, from `worldLandmarks`.

    The arm bones do not change length. Whatever variation shows up here is the
    3D estimate moving, which is the one tracking-quality signal available that
    MediaPipe does not grade itself.
    """

    def span(a: int, b: int) -> float:
        p, q = world[a], world[b]
        return math.dist((p.x, p.y, p.z), (q.x, q.y, q.z))

    return {
        "upper_arm_left": span(LANDMARK["LEFT_SHOULDER"], LANDMARK["LEFT_ELBOW"]),
        "forearm_left": span(LANDMARK["LEFT_ELBOW"], LANDMARK["LEFT_WRIST"]),
        "upper_arm_right": span(LANDMARK["RIGHT_SHOULDER"], LANDMARK["RIGHT_ELBOW"]),
        "forearm_right": span(LANDMARK["RIGHT_ELBOW"], LANDMARK["RIGHT_WRIST"]),
    }


def _orientation(world: list[Landmark]) -> dict[str, float]:
    """Signed vertical relations, in torso lengths. y points down.

    Every angle the analysis stage computes is rotation-invariant, and
    `trunk_verticality` takes an absolute value — so an athlete tracked
    **upside down** reads as perfectly upright. Nothing in the pipeline can
    currently tell that apart from a correctly tracked one, and on clip `084`
    the classifier scores `squat` at 1.000 on all 1156 windows with the hands
    0.79 arm-lengths *below* the shoulders.

    `shoulder_above_hip` is the discriminator. Standing, hanging, squatting,
    mid-muscle-up — in every posture a human body takes, the shoulders are
    above the hips. If this comes out negative, the skeleton is inverted and
    every angle downstream is being read off an upside-down body. If it stays
    positive while `wrist_above_shoulder_y` is negative, the skeleton is
    upright and the arms really are down: a different person, or a different
    moment, but not a rotation.

    Everything is divided by the **3D** torso length, not by the vertical gap.
    The first version used the gap, which made `shoulder_above_hip` come out
    exactly ±1 on every frame by construction — a sign, carrying no magnitude,
    and blind to a body lying on its side. Against the 3D length it is a signed
    verticality: +1 upright, 0 horizontal, −1 inverted. Which is precisely the
    quantity `trunk_verticality` throws away when it takes an absolute value.
    """

    def mid(left: str, right: str) -> tuple[float, float, float]:
        p, q = world[LANDMARK[left]], world[LANDMARK[right]]
        return ((p.x + q.x) / 2.0, (p.y + q.y) / 2.0, (p.z + q.z) / 2.0)

    hip, shoulder = mid("LEFT_HIP", "RIGHT_HIP"), mid("LEFT_SHOULDER", "RIGHT_SHOULDER")
    torso = math.dist(hip, shoulder)
    if torso <= 0.0:
        return {}
    return {
        "shoulder_above_hip": (hip[1] - shoulder[1]) / torso,
        "knee_below_hip": (mid("LEFT_KNEE", "RIGHT_KNEE")[1] - hip[1]) / torso,
        "wrist_above_shoulder_y": (shoulder[1] - mid("LEFT_WRIST", "RIGHT_WRIST")[1]) / torso,
    }


def _detection(normalized: list[Landmark], world: list[Landmark]) -> dict[str, float]:
    """Where the detected body is in the frame, and whether it is shaped like one.

    Answers the question left open by subject selection: on clip `084` the
    tracker reported only ever one candidate, so the athlete was never *offered*,
    and "which body do we pick" was the wrong question. These say why.

    `box_height` is the detected body's share of the frame. MediaPipe's detector
    has a practical lower size limit; an athlete filmed wide on a bar can fall
    under it while a bystander nearer the camera does not.

    `centre_y_excursion` is the giveaway a rep count cannot give. A pull-up
    translates the whole body by roughly half a torso; a standing spectator's
    box does not move. If the tracked box is still while the annotation says 34
    repetitions happened, the body being measured is not the one doing them.

    `limb_ratio` is upper arm over forearm. Every human is between about 1.15
    and 1.25, children included. Well below that is not a person of unusual
    build — it is a skeleton fitted badly. Worth having because segment *stability*
    does not imply segment *correctness*: a consistently wrong fit is stable too,
    which is a reading of `segment_cv` this project got wrong once already.
    """
    visible = [p for p in normalized if p.visibility is None or p.visibility >= 0.5]
    if len(visible) < 4:
        return {}
    xs, ys = [p.x for p in visible], [p.y for p in visible]

    def span(a: str, b: str) -> float:
        p, q = world[LANDMARK[a]], world[LANDMARK[b]]
        return math.dist((p.x, p.y, p.z), (q.x, q.y, q.z))

    def span_2d(a: str, b: str) -> float:
        p, q = normalized[LANDMARK[a]], normalized[LANDMARK[b]]
        return math.dist((p.x, p.y), (q.x, q.y))

    upper = span("LEFT_SHOULDER", "LEFT_ELBOW") + span("RIGHT_SHOULDER", "RIGHT_ELBOW")
    fore = span("LEFT_ELBOW", "LEFT_WRIST") + span("RIGHT_ELBOW", "RIGHT_WRIST")
    upper_2d = span_2d("LEFT_SHOULDER", "LEFT_ELBOW") + span_2d("RIGHT_SHOULDER", "RIGHT_ELBOW")
    fore_2d = span_2d("LEFT_ELBOW", "LEFT_WRIST") + span_2d("RIGHT_ELBOW", "RIGHT_WRIST")
    out = {
        "box_width": max(xs) - min(xs),
        "box_height": max(ys) - min(ys),
        "box_centre_x": (max(xs) + min(xs)) / 2.0,
        "box_centre_y": (max(ys) + min(ys)) / 2.0,
    }
    if fore > 0.0:
        out["limb_ratio"] = upper / fore
    if fore_2d > 0.0:
        # The same ratio in image space, which localises the defect. Every
        # biomechanical quantity in this project comes from `worldLandmarks` —
        # that is a stated invariant — so a skeleton that is anatomically
        # impossible *there* poisons every angle, even if its 2D projection
        # looks right. If 2D is plausible while 3D is not, the fault is the
        # depth estimate, not the detection.
        #
        # Read over a clip, not per frame: perspective foreshortens a limb
        # pointing at the camera, so single frames are legitimately far from
        # anatomy. A whole clip sitting below 1.0 is not perspective.
        out["limb_ratio_2d"] = upper_2d / fore_2d
    return out


def sample_video(
    path: Path, model_path: Path, max_poses: int = 1, running_mode: str = "video"
) -> tuple[
    list[FrameSample],
    list[dict[str, float]],
    list[Classification],
    int,
    float,
    SubjectTracker | None,
]:
    """Every frame of a clip, reduced to `FrameSample` plus its segment lengths.

    Returns the samples, the per-sample arm-segment lengths, the classifier's
    per-window verdicts, the number of frames read, and the wall-clock seconds
    spent.

    Frames where no pose was found produce no sample — never a neutral one.

    The verdicts are returned whole rather than reduced to labels. A label says
    what the classifier decided; only the features say why, and a wrong label
    with no features attached can only be argued about.

    The classifier runs over the same frames as the counter, deliberately: a
    gate measured on a different frame set than the thing it gates would not
    describe the pipeline anyone will ship.
    """
    import cv2  # imported here so the module can be read without the heavy deps
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    # VIDEO mode reuses the previous frame's region of interest and only runs
    # the full detector when tracking is lost. That is the right trade on a
    # phone, and it means a second body entering the scene may never be looked
    # for at all — which would explain `084` reporting one candidate even with
    # `num_poses=3`. IMAGE mode re-detects every frame, so the two disagree
    # exactly when ROI reuse is what hid the athlete.
    image_mode = running_mode == "image"
    options = mp_vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
        running_mode=mp_vision.RunningMode.IMAGE if image_mode else mp_vision.RunningMode.VIDEO,
        # Default 1, and *measured* rather than assumed. Raising it to 3 so the
        # tracker could choose cost 26 % of throughput (54.9 -> 40.6 fps on the
        # same 48 030 frames) and bought nothing: false positives 29 -> 28,
        # invented reps 109 -> 109, gate recall still 0/3. See BENCHMARKS.
        num_poses=max_poses,
    )

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise FileNotFoundError(f"cannot open {path}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0

    sampler = FrameSampler()
    classifier = ExerciseClassifier()
    # `max_poses == 1` bypasses the tracker entirely rather than running it over
    # a single candidate. The first version did the latter, and it made the A/B
    # unreadable: with nothing to choose between, the tracker still dropped
    # frames whose one body had "teleported", changing the count on 11 of 97
    # clips. Continuity-as-a-quality-filter is a different feature from subject
    # selection, and measuring them through one flag measured neither.
    tracker = SubjectTracker() if max_poses > 1 else None
    samples: list[FrameSample] = []
    lengths: list[dict[str, float]] = []
    verdicts: list[Classification] = []
    frames = 0
    started = time.perf_counter()

    with mp_vision.PoseLandmarker.create_from_options(options) as landmarker:
        while True:
            ok, frame_bgr = capture.read()
            if not ok:
                break
            t_ms = frames * 1000.0 / fps
            frames += 1
            image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB),
            )
            result = (
                landmarker.detect(image)
                if image_mode
                else landmarker.detect_for_video(image, int(t_ms))
            )
            if not result.pose_world_landmarks or not result.pose_landmarks:
                continue
            # Selection runs on the *normalised* set: world landmarks are
            # re-centred on each subject's own hips, so every body sits at the
            # origin and the one signal that separates them is gone.
            normalized = [_landmarks(p) for p in result.pose_landmarks]
            if tracker is None:
                chosen = 0
            else:
                subject = tracker.select(normalized)
                if subject is None:
                    continue
                chosen = subject.index
            world = _landmarks(result.pose_world_landmarks[chosen])
            if (verdict := classifier.push(world, normalized[chosen], t_ms)) is not None:
                verdicts.append(verdict)
            sample = sampler.sample(world, normalized[chosen], t_ms)
            if sample is not None:
                samples.append(sample)
                lengths.append(
                    _segment_lengths(world)
                    | _orientation(world)
                    | _detection(normalized[chosen], world)
                )

    capture.release()
    return samples, lengths, verdicts, frames, time.perf_counter() - started, tracker


def dump_angles(
    samples: list[FrameSample], lengths: list[dict[str, float]], destination: Path
) -> None:
    """The per-frame signal, so it can be looked at rather than inferred.

    Percentiles say the distribution is narrow; only the time series says
    whether that is a flat signal, a fast one the sampler undersamples, or a
    clean cycle sitting at the wrong offset.

    The segment lengths ride along in the same file on purpose. `confidence` is
    built from MediaPipe's `visibility`, which claims a landmark was *found*,
    not that it was found in the right place — so a frame can be fully
    confident and badly placed. A bone changing length is the evidence for
    that, and it is only interpretable next to the angle it was measured from.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    segments = sorted(lengths[0]) if lengths else []
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "t_ms",
                "elbow_left_deg",
                "elbow_right_deg",
                "elbow_mean_deg",
                "confidence",
                *segments,
            ]
        )
        # `lengths` is built alongside `samples` in `sample_video`, one entry
        # per retained frame, so index i means the same frame in both.
        for i, s in enumerate(samples):
            row = lengths[i] if i < len(lengths) else {}
            writer.writerow(
                [
                    f"{s.t_ms:.1f}",
                    f"{s.elbow_left_deg:.2f}",
                    f"{s.elbow_right_deg:.2f}",
                    f"{s.elbow_mean_deg:.2f}",
                    f"{s.confidence:.3f}",
                    *(f"{row[k]:.4f}" if k in row else "" for k in segments),
                ]
            )


WINDOW_FIELDS = (
    "wrist_above_shoulder",
    "trunk_verticality",
    "elbow_rom_deg",
    "knee_rom_deg",
    "hip_rom_deg",
    "knee_deg",
    "hip_deg",
    "frames",
    "confidence",
)


def dump_windows(verdicts: list[Classification], destination: Path) -> None:
    """Every classification window: the verdict, its scores, and its features.

    Written because a wrong label was, until now, unarguable. Clip `084` is
    called `squat` on 99.8 % of its windows while the athlete does pull-ups, and
    settling *why* meant reasoning backwards from the rule to what the features
    must have been — which is guessing with extra steps. The squat rule requires
    the hands not to be overhead, so either MediaPipe is not putting them there
    on a hanging athlete, or the clip is not framed as we assume. Those need
    opposite fixes and the label alone cannot tell them apart.

    One row per window, so the label can be read against the geometry that
    produced it, at the moment it produced it.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    exercises = sorted({e.value for v in verdicts for e in v.scores})
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["exercise", "confidence", "reason", *WINDOW_FIELDS, *(f"score_{e}" for e in exercises)]
        )
        for v in verdicts:
            f = v.features
            writer.writerow(
                [
                    v.exercise.value,
                    f"{v.confidence:.4f}",
                    v.reason,
                    # A refused window has no features when the frames never
                    # formed one; blank, not zero, which would read as measured.
                    *(f"{getattr(f, name):.4f}" if f is not None else "" for name in WINDOW_FIELDS),
                    *(f"{v.scores.get(Exercise(e), 0.0):.4f}" for e in exercises),
                ]
            )


def evaluate_clip(
    path: Path,
    truth: int,
    exercise: Exercise,
    model: Path,
    trim_percent: float,
    dump_dir: Path | None = None,
    in_domain: bool = False,
    max_poses: int = 1,
    running_mode: str = "video",
) -> ClipResult:
    """Read a clip, then hand the samples to the tested scoring path."""
    samples, lengths, verdicts, frames, seconds, tracker = sample_video(
        path, model, max_poses, running_mode
    )
    if dump_dir is not None:
        dump_angles(samples, lengths, dump_dir / f"{path.stem}.csv")
        dump_windows(verdicts, dump_dir / f"{path.stem}_windows.csv")
    result = score_samples(
        samples,
        path=str(path),
        truth=truth,
        exercise=exercise,
        frames=frames,
        seconds=seconds,
        trim_percent=trim_percent,
        labels=[v.exercise for v in verdicts],
        in_domain=in_domain,
    )
    result.segment_cv = segment_stability(lengths)
    result.orientation = orientation_summary(lengths)
    result.detection = detection_summary(lengths)
    result.subject = (
        {}
        if tracker is None
        else {
            "acquisitions": tracker.acquisitions,
            "dropped_frames": tracker.dropped_frames,
            "max_candidates": tracker.max_candidates,
            "frames_with_choice": tracker.frames_with_choice,
        }
    )
    return result


def _index_by_name(root: Path) -> dict[str, list[Path]]:
    """Every file under `root`, grouped by basename.

    Built lazily, on the first clip that is not where the manifest says it is,
    and never otherwise: a manifest whose paths are right walks nothing. The
    obvious alternative — an `rglob` per missing clip — re-walks the dataset
    once per line, which on QUVA is 100 walks of 201 files to answer the same
    question 100 times.

    Grouping by name rather than returning the first hit is deliberate. Two
    files with the same basename under one root mean the manifest is ambiguous,
    and guessing between them would silently score the wrong video against the
    right annotation. That case has to stay visible.
    """
    index: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        if path.is_file():
            index.setdefault(path.name, []).append(path)
    return index


class ClipLocator:
    """Turns a manifest path into a file on disk, or into a reason it is not.

    Separate from `main` so it can be tested without MediaPipe, and because the
    decision it makes — score this file, or refuse — is the one that decides
    whether the harness reports a measurement or an empty summary.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.relocated = 0
        self._index: dict[str, list[Path]] | None = None

    def locate(self, relative: str) -> tuple[Path | None, str]:
        """`(path, note)`. A `None` path means the note is why there isn't one."""
        path = (self.root / relative).resolve()
        if path.exists():
            return path, ""

        # We know the filename and we know the root. Looking under it is what
        # the person reading "absent" is about to do by hand, and the first
        # version of this harness made them do it for a dataset whose videos
        # sat one directory away from where its manifest said.
        if self._index is None:
            self._index = _index_by_name(self.root)
        candidates = self._index.get(Path(relative).name, [])
        if len(candidates) == 1:
            self.relocated += 1
            return candidates[0].resolve(), f"retrouvé sous {self.root}"
        if candidates:
            return None, f"nom ambigu ({len(candidates)} fichiers)"
        return None, "fichier absent"


def build_parser() -> argparse.ArgumentParser:
    """Separate from `main` so the flags can be rendered without running a pass.

    `--help` shipped broken once because nothing in the suite had ever built
    this parser: argparse expands `%` in help strings, and a literal per-cent
    sign in one flag's text kills `--help` for every flag at once.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("web/public/models/pose_landmarker_full.task"),
        help="Same .task the app ships, so the measurement describes the app.",
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--max-poses",
        type=int,
        default=1,
        help=(
            "How many bodies MediaPipe may return per frame. 1 (the default) "
            "bypasses subject selection entirely. Above 1, `SubjectTracker` "
            # `%%`, not `%`: argparse runs help strings through `%`-formatting,
            # so a bare `% o` is read as a format spec and `--help` dies with
            # `TypeError: %o format: an integer is required`. Shipped broken
            # once already, which is what this test-free surface costs.
            "picks one and follows it. Measured on QUVA: 3 costs 26 %% of "
            "throughput and improves no counting metric, so it is off until "
            "footage exists where it helps."
        ),
    )
    parser.add_argument(
        "--running-mode",
        choices=("video", "image"),
        default="video",
        help=(
            "`video` (default) is what the app runs: MediaPipe reuses the "
            "previous frame's region of interest and only re-detects when "
            "tracking is lost. `image` re-detects every frame — slower, and the "
            "way to tell whether ROI reuse is why a second body is never found."
        ),
    )
    parser.add_argument(
        "--clips-root",
        type=Path,
        default=None,
        help=(
            "Directory the manifest's relative paths resolve against. Defaults "
            "to the manifest's own directory, which is wrong as soon as the "
            "manifest lives in the repository and the clips do not."
        ),
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--trim-percent",
        type=float,
        default=0.0,
        help=(
            "Discard this %% from each tail when estimating the clip's range of "
            "motion. 0 uses min/max, which one spurious frame is enough to "
            "inflate — and since every threshold is a fraction of the range, an "
            "inflated one starves every rep at once."
        ),
    )
    parser.add_argument(
        "--dump-angles",
        type=Path,
        default=None,
        help=(
            "Write the per-frame elbow angles of each clip to this directory as "
            "CSV. Percentiles say a distribution is narrow; only the series says "
            "whether that is a flat signal or a real cycle at the wrong offset."
        ),
    )
    parser.add_argument(
        "--out-of-domain",
        action="store_true",
        help=(
            "The clips are NOT the exercise. Reports specificity — how often the "
            "counter invents reps on footage it should stay silent on — instead "
            "of accuracy, whose `truth` would describe a different movement."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.model.exists():
        # The npm route needs node; the curl route needs nothing. Both fetch the
        # same file, and someone evaluating clips has no reason to install a
        # JavaScript toolchain first.
        print(
            f"Modèle de pose absent : {args.model}\n\n"
            "  mkdir -p web/public/models && curl -L -o "
            "web/public/models/pose_landmarker_full.task \\\n"
            "    https://storage.googleapis.com/mediapipe-models/pose_landmarker"
            "/pose_landmarker_full/float16/1/pose_landmarker_full.task\n\n"
            "ou, si node est installé :  cd web && npm run vendor-assets",
            file=sys.stderr,
        )
        return 2

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    root = args.clips_root or args.manifest.parent
    clips = manifest["clips"][: args.limit]

    results: list[ClipResult] = []
    locator = ClipLocator(root)
    for entry in clips:
        exercise = Exercise(entry.get("exercise", "pull_up"))
        path, found_via = locator.locate(entry["path"])
        if path is None:
            declared = (root / entry["path"]).resolve()
            print(f"{found_via:24s} {declared}", file=sys.stderr)
            results.append(
                ClipResult(str(declared), entry["reps"], None, 0, 0, 0.0, note=found_via)
            )
            continue
        if found_via:
            print(f"dévié   {entry['path']} -> {path}", file=sys.stderr)
        result = evaluate_clip(
            path,
            int(entry["reps"]),
            exercise,
            args.model,
            args.trim_percent,
            args.dump_angles,
            bool(entry.get("in_domain", False)),
            args.max_poses,
            args.running_mode,
        )
        if found_via:
            # Carried into the JSON, not just stderr: a run that silently
            # scored files other than the ones the manifest named is a run
            # whose provenance you cannot reconstruct afterwards.
            result.note = f"{result.note} ; {found_via}".strip(" ;").strip()
        results.append(result)
        truth_column = "hors-domaine" if args.out_of_domain else f"vrai={result.truth:3d}"
        print(
            f"{path.name:40s} {truth_column} "
            f"prédit={'—' if result.predicted is None else result.predicted:>3} "
            f"({result.detected_frames}/{result.frames} frames, "
            f"[{result.classified_as or '—'}] "
            f"{result.attempted} excursions / {result.events} cycles, "
            f"{result.seconds:.1f}s) "
            f"{result.note}"
        )

    missing = [r for r in results if r.predicted is None and r.frames == 0]
    if missing and len(missing) == len(results):
        # Exiting 0 here would hand back an empty summary that looks like a
        # measurement. It is a setup error, and it has to read as one.
        seen = sorted({Path(r.path).suffix for r in results if Path(r.path).suffix})
        print(
            f"\nAucun clip trouvé ({len(missing)}/{len(results)}). Les chemins du "
            f"manifeste sont résolus depuis {root}, et une recherche par nom de "
            "fichier sous cette racine n'a rien donné non plus"
            + (f" (extensions cherchées : {', '.join(seen)})." if seen else ".")
            + "\nLa racine est probablement la mauvaise :\n"
            f"  python -m vision.eval.evaluate {args.manifest} "
            "--clips-root /chemin/vers/les/videos",
            file=sys.stderr,
        )
        return 2
    if missing:
        print(f"\n⚠ {len(missing)} clips absents, exclus des métriques.", file=sys.stderr)
    if locator.relocated:
        # Not a warning — the run is valid — but the manifest is now wrong about
        # where its own clips live, and that is worth fixing before the next one.
        print(
            f"⚠ {locator.relocated} clips retrouvés ailleurs que là où le manifeste les "
            "déclare. Les chemins du manifeste sont périmés.",
            file=sys.stderr,
        )

    summary = summarise_out_of_domain(results) if args.out_of_domain else summarise(results)
    print("\n" + json.dumps(summary, indent=2))

    if args.out:
        args.out.write_text(
            json.dumps(
                {"summary": summary, "clips": [r.__dict__ for r in results]},
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"\nÉcrit dans {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
