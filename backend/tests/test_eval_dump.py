"""The per-frame CSV the evaluation harness writes.

This file exists because the dump silently lost a column. `dump_angles` was
widened to take the per-frame segment lengths — the one tracking-quality signal
that does not come from MediaPipe's own optimism — and then never wrote them.
Nothing failed: the signature accepted the data, `segment_stability` still
computed its summary from the same list, and the CSV just came out one concern
short. A parameter a function ignores is invisible until someone reads the
output looking for something that was never there.

So the contract under test is narrow and literal: every column the caller hands
over reaches the file, on the row belonging to the frame it was measured on.
"""

from __future__ import annotations

import csv
from pathlib import Path

from iacoach.contracts import FrameSample
from vision.eval.evaluate import dump_angles


def _sample(t_ms: float, angle: float = 90.0) -> FrameSample:
    return FrameSample(
        t_ms=t_ms,
        elbow_left_deg=angle,
        elbow_right_deg=angle + 1.0,
        trunk_deg=3.0,
        hip_speed=0.1,
        confidence=0.9,
    )


def _lengths(upper: float) -> dict[str, float]:
    return {
        "forearm_left": 0.25,
        "forearm_right": 0.25,
        "upper_arm_left": upper,
        "upper_arm_right": 0.30,
    }


def _read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


class TestDumpAngles:
    def test_writes_the_segment_lengths(self, tmp_path: Path) -> None:
        """The regression itself: the columns must exist and carry the values."""
        destination = tmp_path / "clip.csv"

        dump_angles([_sample(0.0), _sample(33.3)], [_lengths(0.31), _lengths(0.28)], destination)

        header, rows = _read(destination)
        assert "upper_arm_left" in header
        assert [r["upper_arm_left"] for r in rows] == ["0.3100", "0.2800"]

    def test_a_length_lands_on_its_own_frame(self, tmp_path: Path) -> None:
        """Row alignment, not just presence.

        The two lists are built in lockstep in `sample_video`. If that ever
        stops being true the CSV would still look well-formed while pairing
        each angle with someone else's bone length — the kind of wrong that
        survives a glance at the file.
        """
        destination = tmp_path / "clip.csv"
        samples = [_sample(0.0, angle=170.0), _sample(50.0, angle=40.0)]

        dump_angles(samples, [_lengths(0.31), _lengths(0.20)], destination)

        _, rows = _read(destination)
        by_angle = {r["elbow_left_deg"]: r["upper_arm_left"] for r in rows}
        assert by_angle == {"170.00": "0.3100", "40.00": "0.2000"}

    def test_survives_a_clip_with_no_frames(self, tmp_path: Path) -> None:
        """A clip where MediaPipe found nothing still gets a readable file.

        Writing a header-only CSV rather than raising keeps "no pose was found"
        distinguishable from "the dump crashed", which is the whole reason the
        dump exists.
        """
        destination = tmp_path / "empty.csv"

        dump_angles([], [], destination)

        header, rows = _read(destination)
        assert rows == []
        assert header[:1] == ["t_ms"]

    def test_creates_the_destination_directory(self, tmp_path: Path) -> None:
        destination = tmp_path / "nested" / "deeper" / "clip.csv"

        dump_angles([_sample(0.0)], [_lengths(0.31)], destination)

        assert destination.exists()
