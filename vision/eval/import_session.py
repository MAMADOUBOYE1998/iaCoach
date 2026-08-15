"""Turns a filmed session into an evaluation manifest, from the file names alone.

The failure mode this exists to prevent is footage you cannot label afterwards.
An evening of filming produces thirty clips that all look alike; deciding a week
later how many repetitions clip 17 contained, and whether the athlete was kipping
on purpose, means re-watching everything and guessing. So the ground truth is
written down **at filming time, in the file name**, where it cannot drift from
the footage.

Naming convention — five fields, separated by ``_``::

    <order>_<exercise>_<variant>_<view>_<reps>.mp4
    03_pullup_strict_face_05.mp4     5 strict pull-ups, filmed head-on
    07_pullup_kip_face_05.mp4        5 deliberately kipping, same framing
    12_rest_deadhang_face_00.mp4     30 s hanging still: zero repetitions
    01_idle_tpose_face_00.mp4        T-pose held still: the reference clip

``reps`` is the count the athlete announced, and ``variant`` is the label that
makes a threshold fittable: `kip_tolerance_ms` cannot be recalibrated from strict
repetitions alone, because nothing in the set sits on the other side of it. The
label has to be decided **before** the set, not read off the video after.

Two manifests come out, because they answer opposite questions and the harness
grades them in opposite modes:

    session.json       clips that ARE the exercise. Run normally: MAE, OBO, MAPE
                       against the announced count. This is sensitivity — never
                       once measured on this project, since QUVA holds three
                       degraded pull-ups and no squat, dip or push-up at all.

    session_rest.json  clips where nothing is being performed: rest, setup, a
                       dead hang, walking back to the bar. Run with
                       `--out-of-domain`. This is specificity on the athlete's
                       own equipment, in the moments the app will actually be
                       left running.

Usage:
    python -m vision.eval.import_session ~/seances/2026-08-15
    python -m vision.eval.import_session DIR --out-dir fixtures/sessions/2026-08-15

The clips stay where they are. Nothing is copied, nothing is uploaded, and the
manifests hold paths into the athlete's own filesystem — keep both out of the
repository, along with the footage.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}

EXERCISES = {
    "pullup": "pull_up",
    "chinup": "chin_up",
    "dip": "dip",
    "pushup": "push_up",
    "squat": "squat",
    "muscleup": "muscle_up",
}
"""Short names for file names, mapped to the `Exercise` enum's values.

Not imported from `iacoach.contracts` on purpose: the point of the short form is
that it is quick to type on a phone keyboard between two sets.
"""

REST = "rest"
IDLE = "idle"
"""`rest` is between-sets footage; `idle` is a deliberately held reference pose.

Both carry zero repetitions and both go into the specificity manifest, but they
answer different questions and the distinction is worth keeping in the name.
`idle` clips are the ones where a bad `limb_ratio` has no excuse left — no
motion, no occlusion, the whole body in frame.
"""


def parse_name(path: Path) -> dict[str, Any] | None:
    """Read the ground truth out of a file name, or return None and say why.

    Refusing is the point. A clip whose name does not parse is a clip whose
    repetition count is unknown, and inventing one — defaulting to zero, or to
    the previous clip's — would put a fabricated truth into a benchmark.
    """
    fields = path.stem.split("_")
    if len(fields) != 5:
        return None
    order, exercise, variant, view, reps = fields
    if not order.isdigit() or not reps.isdigit():
        return None
    if exercise not in EXERCISES and exercise not in (REST, IDLE):
        return None
    return {
        "order": int(order),
        "exercise": exercise,
        "variant": variant,
        "view": view,
        "reps": int(reps),
    }


def build(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[Path]]:
    """Split the directory into performed sets, rest clips, and unparseable names."""
    videos = sorted(p for p in root.rglob("*") if p.suffix.lower() in VIDEO_SUFFIXES)
    sets: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    rejected: list[Path] = []

    for video in videos:
        parsed = parse_name(video)
        if parsed is None:
            rejected.append(video)
            continue
        entry: dict[str, Any] = {
            "path": str(video),
            "reps": parsed["reps"],
            # Carried through for the human reading the results; the harness
            # ignores unknown keys, and losing the variant would make the run
            # unreadable exactly where it matters — which set was the kipping one.
            "variant": parsed["variant"],
            "view": parsed["view"],
        }
        if parsed["exercise"] in (REST, IDLE):
            entry["exercise"] = "pull_up"
            rest.append(entry)
        else:
            entry["exercise"] = EXERCISES[parsed["exercise"]]
            entry["in_domain"] = True
            sets.append(entry)

    sets.sort(key=lambda e: e["path"])
    rest.sort(key=lambda e: e["path"])
    return sets, rest, rejected


def report(sets: list[dict[str, Any]], rest: list[dict[str, Any]], rejected: list[Path]) -> None:
    """Print what was found before anything is written.

    Same reason as `import_quva`: a manifest full of plausible but wrong truths
    is worse than no manifest, and the printout is what makes a naming mistake
    obvious while the athlete is still standing next to the bar.
    """
    print(f"  séries      : {len(sets):3d}  ({sum(e['reps'] for e in sets)} répétitions annoncées)")
    print(f"  repos/idle  : {len(rest):3d}")
    if sets:
        print("\n  par exercice :")
        for exercise, count in Counter(e["exercise"] for e in sets).most_common():
            reps = sum(e["reps"] for e in sets if e["exercise"] == exercise)
            print(f"    {exercise:10s} {count:3d} séries, {reps:3d} répétitions")
        print("\n  par variante :")
        for variant, count in Counter(e["variant"] for e in sets).most_common():
            print(f"    {variant:12s} {count:3d}")
        print("\n  par angle :")
        for view, count in Counter(e["view"] for e in sets).most_common():
            print(f"    {view:12s} {count:3d}")
    if rejected:
        print(f"\n  {len(rejected)} fichier(s) au nom illisible, ignoré(s) :", file=sys.stderr)
        for path in rejected[:10]:
            print(f"    {path.name}", file=sys.stderr)
        print(
            "\n  Attendu : <ordre>_<exercice>_<variante>_<angle>_<reps>.mp4\n"
            "  ex.      03_pullup_strict_face_05.mp4\n"
            f"  exercices : {', '.join(sorted(EXERCISES))}, {REST}, {IDLE}",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Where to write the two manifests. Defaults to the clips' directory.",
    )
    args = parser.parse_args(argv)

    root = args.directory.expanduser().resolve()
    if not root.is_dir():
        print(f"pas un dossier : {root}", file=sys.stderr)
        return 2

    print(f"{root}")
    sets, rest, rejected = build(root)
    report(sets, rest, rejected)

    if not sets and not rest:
        # Exiting 0 with two empty manifests would look like a session that
        # produced nothing, rather than a naming convention nobody followed.
        print("\naucun clip exploitable", file=sys.stderr)
        return 2

    out_dir = (args.out_dir or root).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, clips in (("session.json", sets), ("session_rest.json", rest)):
        if not clips:
            continue
        out = out_dir / name
        out.write_text(json.dumps({"clips": clips}, indent=2, ensure_ascii=False) + "\n")
        written.append(out)

    print("\n" + "\n".join(f"  → {p}" for p in written))
    print("\nEnsuite :")
    if sets:
        print(f"  python -m vision.eval.evaluate {out_dir / 'session.json'} --out sens.json")
    if rest:
        print(
            f"  python -m vision.eval.evaluate {out_dir / 'session_rest.json'} "
            "--out-of-domain --out spec.json"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
