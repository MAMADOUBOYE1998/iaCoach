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
Paths are resolved relative to the manifest.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

from iacoach.contracts import Exercise, FrameSample
from iacoach.evaluation import (
    ClipResult,
    score_samples,
    summarise,
    summarise_out_of_domain,
)
from iacoach.frame import FrameSampler, Landmark


def _landmarks(proto: Any) -> list[Landmark]:
    return [Landmark(lm.x, lm.y, lm.z, getattr(lm, "visibility", None)) for lm in proto]


def sample_video(path: Path, model_path: Path) -> tuple[list[FrameSample], int, float]:
    """Every frame of a clip, reduced to `FrameSample`.

    Returns the samples, the number of frames read, and the wall-clock seconds
    spent. Frames where no pose was found produce no sample — never a neutral
    one.
    """
    import cv2  # imported here so the module can be read without the heavy deps
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    options = mp_vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
        running_mode=mp_vision.RunningMode.VIDEO,
        num_poses=1,
    )

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise FileNotFoundError(f"cannot open {path}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0

    sampler = FrameSampler()
    samples: list[FrameSample] = []
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
            result = landmarker.detect_for_video(image, int(t_ms))
            if not result.pose_world_landmarks or not result.pose_landmarks:
                continue
            sample = sampler.sample(
                _landmarks(result.pose_world_landmarks[0]),
                _landmarks(result.pose_landmarks[0]),
                t_ms,
            )
            if sample is not None:
                samples.append(sample)

    capture.release()
    return samples, frames, time.perf_counter() - started


def dump_angles(samples: list[FrameSample], destination: Path) -> None:
    """The per-frame signal, so it can be looked at rather than inferred.

    Percentiles say the distribution is narrow; only the time series says
    whether that is a flat signal, a fast one the sampler undersamples, or a
    clean cycle sitting at the wrong offset.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "t_ms",
                "elbow_left_deg",
                "elbow_right_deg",
                "elbow_mean_deg",
                "confidence",
            ]
        )
        for s in samples:
            writer.writerow(
                [
                    f"{s.t_ms:.1f}",
                    f"{s.elbow_left_deg:.2f}",
                    f"{s.elbow_right_deg:.2f}",
                    f"{s.elbow_mean_deg:.2f}",
                    f"{s.confidence:.3f}",
                ]
            )


def evaluate_clip(
    path: Path,
    truth: int,
    exercise: Exercise,
    model: Path,
    trim_percent: float,
    dump_dir: Path | None = None,
) -> ClipResult:
    """Read a clip, then hand the samples to the tested scoring path."""
    samples, frames, seconds = sample_video(path, model)
    if dump_dir is not None:
        dump_angles(samples, dump_dir / f"{path.stem}.csv")
    return score_samples(
        samples,
        path=str(path),
        truth=truth,
        exercise=exercise,
        frames=frames,
        seconds=seconds,
        trim_percent=trim_percent,
    )


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)

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
    for entry in clips:
        path = (root / entry["path"]).resolve()
        exercise = Exercise(entry.get("exercise", "pull_up"))
        if not path.exists():
            results.append(
                ClipResult(
                    str(path), entry["reps"], None, 0, 0, 0.0, note="fichier absent"
                )
            )
            print(f"absent  {path}", file=sys.stderr)
            continue
        result = evaluate_clip(
            path,
            int(entry["reps"]),
            exercise,
            args.model,
            args.trim_percent,
            args.dump_angles,
        )
        results.append(result)
        truth_column = (
            "hors-domaine" if args.out_of_domain else f"vrai={result.truth:3d}"
        )
        print(
            f"{path.name:40s} {truth_column} "
            f"prédit={'—' if result.predicted is None else result.predicted:>3} "
            f"({result.detected_frames}/{result.frames} frames, "
            f"{result.attempted} excursions / {result.events} cycles, "
            f"{result.seconds:.1f}s) "
            f"{result.note}"
        )

    missing = [r for r in results if r.note == "fichier absent"]
    if missing and len(missing) == len(results):
        # Exiting 0 here would hand back an empty summary that looks like a
        # measurement. It is a setup error, and it has to read as one.
        print(
            f"\nAucun clip trouvé ({len(missing)}/{len(results)}). Les chemins du "
            f"manifeste sont résolus depuis {root}.\n"
            "Utiliser --clips-root pour pointer le dossier des vidéos :\n"
            f"  python -m vision.eval.evaluate {args.manifest} "
            "--clips-root /chemin/vers/les/videos",
            file=sys.stderr,
        )
        return 2
    if missing:
        print(
            f"\n⚠ {len(missing)} clips absents, exclus des métriques.", file=sys.stderr
        )

    summary = (
        summarise_out_of_domain(results) if args.out_of_domain else summarise(results)
    )
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
