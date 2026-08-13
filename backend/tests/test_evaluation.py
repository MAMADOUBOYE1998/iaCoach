"""Evaluation metrics.

These guard the property that makes an accuracy number worth anything: a clip
the harness could not score must never be folded in as a success. A harness
that scores its own failures reports progress it did not make.
"""

from __future__ import annotations

import math

import pytest

from iacoach.contracts import Exercise, FrameSample
from iacoach.evaluation import (
    MIN_SPAN_DEG,
    MIN_USABLE_FRAMES,
    ClipResult,
    calibration_from,
    score_samples,
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


def pullup_cycles(
    count: int, *, fps: float = 30.0, seconds_per_rep: float = 2.0
) -> list[FrameSample]:
    """`count` full pull-up cycles, 175 deg hanging to 45 deg at the top."""
    out: list[FrameSample] = []
    total = int(count * seconds_per_rep * fps)
    for i in range(total):
        phase = 2.0 * math.pi * i / (seconds_per_rep * fps)
        angle = 110.0 + 65.0 * math.cos(phase)
        out.append(
            FrameSample(
                t_ms=i * 1000.0 / fps,
                elbow_left_deg=angle,
                elbow_right_deg=angle,
                trunk_deg=3.0,
                hip_speed=0.05,
                confidence=0.95,
            )
        )
    return out


class TestScoreSamples:
    """The path from samples to a count.

    This is what was missing: the line constructing `RepCounter` lived beside
    the video reader, outside the test suite, and its wrong argument list only
    surfaced on the first real clip that got far enough to reach it.
    """

    def test_counts_the_cycles_it_was_given(self) -> None:
        result = score_samples(pullup_cycles(5), path="synthetic.mp4", truth=5)
        assert result.predicted == 5
        assert result.error == 0

    def test_reports_the_calibration_refusal_instead_of_zero(self) -> None:
        flat = samples(60, low=100.0, high=110.0)
        result = score_samples(flat, path="flat.mp4", truth=4)
        assert result.predicted is None
        assert "calibration impossible" in result.note

    def test_carries_the_flags_through(self) -> None:
        result = score_samples(pullup_cycles(3), path="synthetic.mp4", truth=3)
        assert isinstance(result.flags, dict)


class TestTrimmedCalibration:
    """One spurious frame must not redefine the athlete's range.

    Every threshold is a fraction of the calibrated range, so an inflated range
    starves every rep at once — and the symptom is "counts nothing", which reads
    like a broken state machine rather than a broken calibration.
    """

    def test_min_max_is_captured_by_a_single_outlier(self) -> None:
        clean = pullup_cycles(4)
        outlier = FrameSample(
            t_ms=-1.0,
            elbow_left_deg=15.0,
            elbow_right_deg=15.0,
            trunk_deg=0.0,
            hip_speed=0.0,
            confidence=0.95,
        )
        wide = calibration_from([outlier, *clean])
        assert wide is not None
        assert wide.rom_min_deg == pytest.approx(15.0)

    def test_trimming_ignores_it(self) -> None:
        clean = pullup_cycles(4)
        outlier = FrameSample(
            t_ms=-1.0,
            elbow_left_deg=15.0,
            elbow_right_deg=15.0,
            trunk_deg=0.0,
            hip_speed=0.0,
            confidence=0.95,
        )
        trimmed = calibration_from([outlier, *clean], trim_percent=2.0)
        assert trimmed is not None
        assert trimmed.rom_min_deg > 40.0

    def test_trimming_a_clean_clip_barely_moves_the_range(self) -> None:
        clean = pullup_cycles(6)
        plain = calibration_from(clean)
        trimmed = calibration_from(clean, trim_percent=2.0)
        assert plain is not None and trimmed is not None
        assert abs(trimmed.rom_max_deg - plain.rom_max_deg) < 5.0

    def test_diagnostics_separate_unseen_from_uncounted(self) -> None:
        # `events` is what tells the two apart; without it a low count has two
        # opposite explanations and no way to choose.
        result = score_samples(pullup_cycles(5), path="c.mp4", truth=5)
        assert result.events == 5
        assert len(result.peak_angles_deg) == 5
        assert result.calibration_deg is not None
