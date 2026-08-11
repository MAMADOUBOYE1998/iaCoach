"""Fixture conformance — the Python half.

``web/src/analysis/conformance.test.ts`` is the other half and reads the same
files. The two must agree; that is the only thing standing between the on-device
and server-side analyses and a silent divergence.

Each scenario is checked twice:
- against the hand-authored expectation in the sequence file (semantics), and
- against the golden ``RepEvent`` stream (exact behaviour, cross-language).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iacoach.config import REPO_ROOT
from iacoach.contracts import Exercise, ExerciseCalibration, FrameSample
from iacoach.counting import analyse_sequence

SEQUENCES_DIR = REPO_ROOT / "fixtures" / "sequences"
GOLDEN_DIR = REPO_ROOT / "fixtures" / "golden"

SEQUENCE_FILES = sorted(SEQUENCES_DIR.glob("*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_fixtures_are_present() -> None:
    """Guard against the parametrised suite silently collecting nothing."""
    assert len(SEQUENCE_FILES) >= 8


@pytest.mark.parametrize("path", SEQUENCE_FILES, ids=lambda p: p.stem)
class TestFixture:
    def test_matches_the_hand_authored_expectation(self, path: Path) -> None:
        fixture = _load(path)
        events = analyse_sequence(
            Exercise(fixture["exercise"]),
            ExerciseCalibration.model_validate(fixture["calibration"]),
            [FrameSample.model_validate(f) for f in fixture["frames"]],
        )
        expected = fixture["expected"]
        assert len(events) == expected["events"], fixture["description"]
        assert sum(1 for e in events if e.counted) == expected["counted"]
        assert [e.flags for e in events] == expected["flags"]

    def test_matches_the_golden_stream(self, path: Path) -> None:
        fixture = _load(path)
        golden = _load(GOLDEN_DIR / path.name)
        events = analyse_sequence(
            Exercise(fixture["exercise"]),
            ExerciseCalibration.model_validate(fixture["calibration"]),
            [FrameSample.model_validate(f) for f in fixture["frames"]],
        )
        assert [e.model_dump(mode="json") for e in events] == golden
