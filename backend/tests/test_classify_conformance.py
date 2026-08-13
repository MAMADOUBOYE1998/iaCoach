"""Classification conformance — the Python half.

`web/src/analysis/classify.test.ts` is the other half and reads the same files.
The label decides which corrections an athlete is given, so a divergence between
the phone and the server would produce different coaching from the same
movement, with nothing to say why.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from iacoach.classify import Landmark, classify_window, frame_features, window_features
from iacoach.config import REPO_ROOT

CLASSIFY_DIR = REPO_ROOT / "fixtures" / "classify"
FIXTURES = sorted(CLASSIFY_DIR.glob("*.json"))


def test_fixtures_exist() -> None:
    assert FIXTURES, "aucune fixture de classification"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_replays_exactly(path: Path) -> None:
    fixture = json.loads(path.read_text(encoding="utf-8"))

    pad = fixture["pad"]

    features = []
    for frame, expected in zip(fixture["frames"], fixture["expected_frames"], strict=True):
        # Only the read landmarks are stored; the rest is inert padding that
        # nothing indexes, rebuilt here so the frame is complete.
        landmarks = [
            Landmark(pad["x"], pad["y"], pad["z"], pad["visibility"])
            for _ in range(fixture["landmark_count"])
        ]
        for index, lm in frame["landmarks"].items():
            landmarks[int(index)] = Landmark(lm["x"], lm["y"], lm["z"], lm["visibility"])
        found = frame_features(landmarks, landmarks, frame["t_ms"])
        assert found is not None
        assert asdict(found) == pytest.approx(expected, abs=1e-9)
        features.append(found)

    window = window_features(features)
    assert asdict(window) == pytest.approx(fixture["expected_window"], abs=1e-9)

    verdict = classify_window(window)
    assert verdict.exercise.value == fixture["expected"]["exercise"]
    assert verdict.confidence == pytest.approx(fixture["expected"]["confidence"], abs=1e-9)
    assert verdict.reason == fixture["expected"]["reason"]
