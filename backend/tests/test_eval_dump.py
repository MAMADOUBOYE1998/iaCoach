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

from iacoach.classify import Classification, WindowFeatures
from iacoach.contracts import Exercise, FrameSample
from iacoach.frame import LANDMARK, Landmark
from vision.eval.evaluate import _orientation, dump_angles, dump_windows


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


def _window(**overrides: float) -> WindowFeatures:
    values: dict[str, float] = {
        "wrist_above_shoulder": 0.95,
        "trunk_verticality": 1.0,
        "elbow_rom_deg": 6.0,
        "knee_rom_deg": 80.0,
        "hip_rom_deg": 78.0,
        "knee_deg": 150.0,
        "hip_deg": 137.0,
        "frames": 60,
        "confidence": 1.0,
    }
    values.update(overrides)
    return WindowFeatures(**values)  # type: ignore[arg-type]


class TestDumpWindows:
    """The classification window, written down so a wrong label can be argued.

    Clip `084` is labelled `squat` on 99.8 % of its windows while the athlete
    does pull-ups. Two incompatible explanations fit — MediaPipe is not placing
    the hands overhead on a hanging athlete, or the clip is not framed the way
    the rule assumes — and the label alone distinguishes neither. Only the
    features do, and until this existed they were computed and discarded.
    """

    def test_writes_the_feature_that_decides_the_squat_rule(self, tmp_path: Path) -> None:
        destination = tmp_path / "clip_windows.csv"
        verdict = Classification(
            Exercise.SQUAT, 0.8, {Exercise.SQUAT: 0.8, Exercise.PULL_UP: 0.0}, "", _window()
        )

        dump_windows([verdict], destination)

        header, rows = _read(destination)
        assert "wrist_above_shoulder" in header
        assert rows[0]["wrist_above_shoulder"] == "0.9500"
        assert rows[0]["exercise"] == "squat"
        assert rows[0]["score_pull_up"] == "0.0000"

    def test_a_window_without_features_leaves_blanks(self, tmp_path: Path) -> None:
        """Blank, never 0.0 — a zero here would read as a measured value.

        `wrist_above_shoulder = 0` is a real posture (hands at shoulder height),
        so filling it in for a window that has no features would fabricate the
        exact evidence this file exists to supply.
        """
        destination = tmp_path / "clip_windows.csv"
        refused = Classification(Exercise.UNKNOWN, 0.0, {}, "fenêtre trop courte", None)

        dump_windows([refused], destination)

        _, rows = _read(destination)
        assert rows[0]["wrist_above_shoulder"] == ""
        assert rows[0]["reason"] == "fenêtre trop courte"

    def test_a_clip_with_no_windows_still_writes_a_header(self, tmp_path: Path) -> None:
        destination = tmp_path / "empty_windows.csv"

        dump_windows([], destination)

        header, rows = _read(destination)
        assert rows == []
        assert header[0] == "exercise"


def _body(*, inverted: bool = False, arms_up: bool = True) -> list[Landmark]:
    """A minimal upright skeleton, optionally flipped. y points down."""
    sign = -1.0 if inverted else 1.0
    y = {
        "SHOULDER": -0.5 * sign,
        "HIP": 0.0,
        "KNEE": 0.45 * sign,
        "WRIST": (-1.2 if arms_up else -0.1) * sign,
    }
    points = [Landmark(0.0, 0.0, 0.0, 1.0) for _ in range(33)]
    for joint, value in y.items():
        for side in ("LEFT", "RIGHT"):
            points[LANDMARK[f"{side}_{joint}"]] = Landmark(0.1, value, 0.0, 1.0)
    return points


class TestOrientation:
    """The one thing the analysis stage structurally cannot see.

    Every angle it computes is rotation-invariant, and `trunk_verticality`
    takes an absolute value, so an athlete tracked upside down reads as
    perfectly upright. On clip `084` the classifier scores `squat` at 1.000 on
    all 1156 windows with the hands below the shoulders, and no quantity
    anywhere in the pipeline could say whether the body was inverted.
    """

    def test_an_upright_body_has_its_shoulders_above_its_hips(self) -> None:
        found = _orientation(_body())

        assert found["shoulder_above_hip"] > 0
        assert found["knee_below_hip"] > 0
        assert found["wrist_above_shoulder_y"] > 0

    def test_an_inverted_body_flips_every_sign(self) -> None:
        """The discriminator. `shoulder_above_hip` is negative for no posture
        a human body can take — only for a skeleton read upside down."""
        found = _orientation(_body(inverted=True))

        assert found["shoulder_above_hip"] < 0
        assert found["knee_below_hip"] < 0

    def test_arms_down_does_not_invert_the_torso(self) -> None:
        """Separates the two candidate causes on `084`.

        Hands below shoulders *with* shoulders still above hips means the
        skeleton is upright and the arms really are down — a different person,
        or a different moment. Hands below shoulders *with* the torso flipped
        means the whole body is upside down. Opposite fixes.
        """
        found = _orientation(_body(arms_up=False))

        assert found["wrist_above_shoulder_y"] < 0
        assert found["shoulder_above_hip"] > 0

    def test_a_degenerate_torso_yields_nothing(self) -> None:
        """Zero, not a division by it — and no fabricated orientation."""
        flat = [Landmark(0.0, 0.0, 0.0, 1.0) for _ in range(33)]

        assert _orientation(flat) == {}
