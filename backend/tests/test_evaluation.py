"""Evaluation metrics.

These guard the property that makes an accuracy number worth anything: a clip
the harness could not score must never be folded in as a success. A harness
that scores its own failures reports progress it did not make.
"""

from __future__ import annotations

import pytest

from iacoach.contracts import Exercise, FrameSample
from iacoach.evaluation import (
    MIN_SPAN_DEG,
    MIN_USABLE_FRAMES,
    ClipResult,
    calibration_from,
    summarise,
    summarise_out_of_domain,
)


def samples(
    count: int,
    *,
    low: float = 45.0,
    high: float = 175.0,
    confidence: float = 0.95,
) -> list[FrameSample]:
    """`count` frames sweeping the elbow angle between `low` and `high`."""
    out: list[FrameSample] = []
    for i in range(count):
        ratio = i / max(1, count - 1)
        angle = low + (high - low) * ratio
        out.append(
            FrameSample(
                t_ms=i * 33.3,
                elbow_left_deg=angle,
                elbow_right_deg=angle,
                trunk_deg=2.0,
                hip_speed=0.1,
                confidence=confidence,
            )
        )
    return out


def clip(truth: int, predicted: int | None, note: str = "") -> ClipResult:
    return ClipResult(
        path=f"c{truth}.mp4",
        truth=truth,
        predicted=predicted,
        frames=100,
        detected_frames=90,
        seconds=1.0,
        note=note,
    )


class TestCalibrationFrom:
    def test_recovers_the_observed_range(self) -> None:
        calibration = calibration_from(samples(60), Exercise.PULL_UP)
        assert calibration is not None
        assert calibration.rom_min_deg == pytest.approx(45.0)
        assert calibration.rom_max_deg == pytest.approx(175.0)

    def test_refuses_a_clip_with_too_few_usable_frames(self) -> None:
        assert calibration_from(samples(MIN_USABLE_FRAMES - 1)) is None

    def test_refuses_a_clip_that_never_moved(self) -> None:
        # A hang, a still frame, a mis-detected subject: no range, no scores.
        assert calibration_from(samples(60, low=100.0, high=100.0 + MIN_SPAN_DEG - 1)) is None

    def test_ignores_low_confidence_frames(self) -> None:
        # Calibrating on unreliable landmarks bakes a wrong range into every
        # score that follows, silently.
        assert calibration_from(samples(60, confidence=0.4)) is None

    def test_reports_the_fraction_of_frames_it_trusted(self) -> None:
        mixed = samples(40) + samples(10, confidence=0.2)
        calibration = calibration_from(mixed)
        assert calibration is not None
        assert calibration.confidence == pytest.approx(40 / 50)


class TestSummarise:
    def test_counts_unscorable_clips_separately(self) -> None:
        summary = summarise([clip(5, 5), clip(3, None, "calibration impossible")])
        assert summary["scored"] == 1
        assert summary["skipped"] == 1
        # The skipped clip must not be an error of zero.
        assert summary["mae"] == 0.0

    def test_obo_is_within_one_rep(self) -> None:
        summary = summarise([clip(10, 10), clip(10, 11), clip(10, 13)])
        assert summary["obo"] == pytest.approx(2 / 3)
        assert summary["exact"] == pytest.approx(1 / 3)
        assert summary["mae"] == pytest.approx((0 + 1 + 3) / 3)

    def test_mape_is_relative(self) -> None:
        # One rep missed out of 20 is not the same failure as one out of 2.
        summary = summarise([clip(20, 19), clip(2, 1)])
        assert summary["mape"] == pytest.approx((1 / 20 + 1 / 2) / 2)

    def test_no_scored_clip_yields_no_invented_metric(self) -> None:
        summary = summarise([clip(4, None)])
        assert "mae" not in summary
        assert summary == {"clips": 1, "scored": 0, "skipped": 1}

    def test_empty_input(self) -> None:
        assert summarise([]) == {"clips": 0, "scored": 0, "skipped": 0}


class TestOutOfDomain:
    """Specificity on footage that is not the exercise at all."""

    def test_refusing_to_calibrate_counts_as_correct(self) -> None:
        # On a rope-skipping clip, refusing is the right answer, not a miss.
        summary = summarise_out_of_domain([clip(0, None), clip(0, None)])
        assert summary["refused_to_calibrate"] == 2
        assert summary["false_positive_rate"] == 0.0

    def test_a_counted_rep_on_other_footage_is_a_false_positive(self) -> None:
        summary = summarise_out_of_domain([clip(0, 3), clip(0, None), clip(0, 0)])
        assert summary["false_positive_clips"] == 1
        assert summary["false_positive_rate"] == pytest.approx(1 / 3)
        assert summary["reps_invented_total"] == 3
        assert summary["worst_clip_reps"] == 3

    def test_zero_reps_counted_is_not_a_false_positive(self) -> None:
        # Calibrating then counting nothing is the counter working correctly.
        summary = summarise_out_of_domain([clip(0, 0)])
        assert summary["false_positive_clips"] == 0
        assert summary["scored"] == 1

    def test_empty_input(self) -> None:
        assert summarise_out_of_domain([])["false_positive_rate"] == 0.0
