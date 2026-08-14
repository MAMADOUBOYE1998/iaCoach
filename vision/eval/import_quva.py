"""Turns a downloaded dataset directory into an evaluation manifest.

Written for QUVA Repetition, whose archive layout and annotation convention are
not documented anywhere I could reach. So this **inspects first and concludes
second**: it prints what it actually found — extensions, pairing, the shape and
first values of one annotation — before writing anything. If the counting
convention it picked is wrong, the printout is what makes that obvious instead
of producing a plausible manifest full of off-by-one truths.

Usage:
    python -m vision.eval.import_quva /path/to/QUVARepetitionDataset
    python -m vision.eval.import_quva DIR --out fixtures/clips/manifest.json
    python -m vision.eval.import_quva DIR --count-convention boundaries

Counting conventions, for annotations that store cycle boundaries:
    cycles      (default) count = len(bounds) - 1   [b0 b1 b2] -> 2 cycles
    boundaries            count = len(bounds)       if each entry marks one rep

A word of warning about QUVA specifically: it is a **generic** motion dataset —
swimming, stirring, combing, music-making. Very little of it shows a whole body
with visible arms, which is what this pipeline needs. Expect most clips to come
back `skipped`. That is the correct outcome and a useful test in itself: it
shows the harness refusing out-of-domain footage rather than inventing counts
for it. It will **not** yield a pull-up accuracy figure.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
ANNOTATION_SUFFIXES = {".npy", ".json", ".txt", ".csv", ".mat"}


def inspect(root: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    """Print the directory's real shape, and return videos/annotations by stem."""
    files = [p for p in root.rglob("*") if p.is_file()]
    by_suffix = Counter(p.suffix.lower() for p in files)

    print(f"{root}")
    print(f"  {len(files)} fichiers")
    for suffix, count in by_suffix.most_common(12):
        print(f"    {suffix or '(sans extension)':12s} {count}")

    videos = {p.stem: p for p in files if p.suffix.lower() in VIDEO_SUFFIXES}
    annotations = {p.stem: p for p in files if p.suffix.lower() in ANNOTATION_SUFFIXES}

    print(f"\n  vidéos      : {len(videos)}")
    print(f"  annotations : {len(annotations)}")
    paired = sorted(set(videos) & set(annotations))
    print(f"  appariées   : {len(paired)}")

    if not paired:
        for label, group in (("vidéo", videos), ("annotation", annotations)):
            sample = sorted(group)[:5]
            if sample:
                print(f"  exemples de noms de {label} : {sample}")
    return videos, annotations


def read_count(path: Path, convention: str) -> tuple[int | None, str]:
    """Derive a repetition count, and say how it was derived."""
    suffix = path.suffix.lower()

    if suffix == ".npy":
        import numpy as np

        data = np.load(path, allow_pickle=True)
        flat = np.ravel(data)
        detail = f"npy shape={data.shape} dtype={data.dtype} head={flat[:5].tolist()}"
        # A single scalar is already the count; anything longer is boundaries.
        if flat.size == 1:
            return int(flat[0]), f"{detail} → scalaire lu comme le comptage"
        count = len(flat) - 1 if convention == "cycles" else len(flat)
        return count, f"{detail} → {convention}: {count}"

    if suffix == ".json":
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, int):
            return payload, "json scalaire"
        if isinstance(payload, list):
            count = len(payload) - 1 if convention == "cycles" else len(payload)
            return count, f"json liste de {len(payload)} → {convention}: {count}"
        for key in ("count", "reps", "repetitions", "num_reps"):
            if isinstance(payload, dict) and key in payload:
                return int(payload[key]), f"json clé '{key}'"
        return None, f"json non reconnu: {type(payload).__name__}"

    if suffix in {".txt", ".csv"}:
        values = [
            line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        if len(values) == 1 and values[0].isdigit():
            return int(values[0]), "texte scalaire"
        count = len(values) - 1 if convention == "cycles" else len(values)
        return count, f"texte de {len(values)} lignes → {convention}: {count}"

    return None, f"format non géré: {suffix} (à ouvrir à la main)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--count-convention",
        choices=("cycles", "boundaries"),
        default="cycles",
    )
    parser.add_argument("--exercise", default="pull_up")
    parser.add_argument(
        "--in-domain",
        default="pullups",
        help=(
            "Substring marking clips that ARE the exercise. QUVA is a "
            "general-purpose repetition dataset and happens to contain three "
            "pull-up clips; in specificity mode they are positives sitting in a "
            "negative set. Marked here so the summary can hold them apart "
            "instead of scoring a correct label as a false positive. Empty "
            "disables the marking."
        ),
    )
    args = parser.parse_args(argv)

    if not args.directory.is_dir():
        print(f"Introuvable : {args.directory}")
        return 2

    videos, annotations = inspect(args.directory)
    paired = sorted(set(videos) & set(annotations))
    if not paired:
        print("\nAucune paire vidéo/annotation. Colle la sortie ci-dessus.")
        return 1

    out = args.out or (args.directory / "manifest.json")
    clips: list[dict[str, Any]] = []
    unreadable: list[str] = []

    print("\n  quelques dérivations, à vérifier sur une vidéo avant de s'y fier :")
    for index, stem in enumerate(paired):
        count, detail = read_count(annotations[stem], args.count_convention)
        if index < 3:
            print(f"    {stem}: {detail}")
        if count is None:
            unreadable.append(stem)
            continue
        entry: dict[str, Any] = {
            # `Path.relative_to(walk_up=True)` is 3.12; this project targets
            # 3.11, and the manifest needs paths that can climb out of the
            # directory it sits in.
            "path": os.path.relpath(videos[stem].resolve(), out.parent.resolve()),
            "reps": count,
            "exercise": args.exercise,
        }
        if args.in_domain and args.in_domain in stem:
            entry["in_domain"] = True
        clips.append(entry)

    if unreadable:
        print(f"\n  {len(unreadable)} annotations illisibles, par ex. {unreadable[:3]}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"clips": clips}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\n{len(clips)} clips → {out}")
    print(
        "\nVérifie UNE vidéo à la main avant de lancer l'évaluation : si le compte "
        "dérivé est décalé de 1, relance avec --count-convention boundaries."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
