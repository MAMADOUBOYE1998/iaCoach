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
    classification_verdict,
    periodicity_count,
    score_samples,
    segment_stability,
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


def gated(
    exercise: str, label: str, predicted: int | None, *, in_domain: bool = False
) -> ClipResult:
    result = clip(0, predicted)
    result.exercise, result.classified_as, result.in_domain = exercise, label, in_domain
    return result


class TestTheGateIsNotGradedOnSpecificityAlone:
    """A gate that refuses everything has perfect specificity.

    This is not a hypothetical: the QUVA set contains three genuine pull-up
    clips among its hundred, the classifier labelled none of them `pull_up`,
    and the specificity headline improved *because* of it. A page reporting
    only the false-positive rate would have read that as progress.
    """

    def test_in_domain_clips_leave_the_specificity_denominator(self) -> None:
        results = [
            gated("pull_up", "unknown", None),
            gated("pull_up", "squat", 3, in_domain=True),
        ]

        summary = summarise_out_of_domain(results)

        assert summary["clips"] == 1
        assert summary["in_domain_clips"] == 1
        assert summary["false_positive_clips"] == 0

    def test_a_correct_label_is_never_a_false_positive(self) -> None:
        """Being right about a real pull-up must not cost anything here.

        Before `in_domain` existed it did: the clip was declared out-of-domain,
        so classifying it correctly let it through the gate and its reps were
        booked as invented.

        The out-of-domain clip is not decoration. With only the positive in the
        list there are no out-of-domain clips left to classify, so the after-gate
        fields correctly come back `None` — unmeasured, not zero — and the
        assertion would pass for the wrong reason.
        """
        results = [
            gated("pull_up", "pull_up", 9, in_domain=True),
            gated("pull_up", "unknown", None),
        ]

        summary = summarise_out_of_domain(results)

        assert summary["false_positive_clips_after_gate"] == 0
        assert summary["reps_invented_after_gate"] == 0
        assert summary["gate_recall"] == pytest.approx(1.0)

    def test_refusing_the_positives_shows_up_as_lost_recall(self) -> None:
        """The measurement that makes a silent gate visible."""
        results = [
            gated("pull_up", "squat", 3, in_domain=True),
            gated("pull_up", "unknown", None, in_domain=True),
            gated("pull_up", "unknown", None),
        ]

        summary = summarise_out_of_domain(results)

        assert summary["gate_recall"] == pytest.approx(0.0)
        assert summary["false_positive_clips_after_gate"] == 0

    def test_no_positives_means_no_recall_claim(self) -> None:
        """`None`, not 0.0 and not 1.0 — the set simply cannot answer.

        Every manifest before this change is in that case, and a default that
        looked like a measurement would misreport all of them.
        """
        assert summarise_out_of_domain([gated("pull_up", "unknown", None)])["gate_recall"] is None


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
        assert len(result.rep_rom) == 5
        assert result.calibration_deg is not None


def cycles_between(
    count: int,
    high_deg: float,
    low_deg: float,
    *,
    fps: float = 30.0,
    seconds_per_rep: float = 2.0,
    start_ms: float = 0.0,
) -> list[FrameSample]:
    """`count` cycles from `high_deg` (extended) down to `low_deg` and back."""
    mid, half = (high_deg + low_deg) / 2.0, (high_deg - low_deg) / 2.0
    out: list[FrameSample] = []
    for i in range(int(count * seconds_per_rep * fps)):
        phase = 2.0 * math.pi * i / (seconds_per_rep * fps)
        angle = mid + half * math.cos(phase)
        out.append(
            FrameSample(
                t_ms=start_ms + i * 1000.0 / fps,
                elbow_left_deg=angle,
                elbow_right_deg=angle,
                trunk_deg=3.0,
                hip_speed=0.05,
                confidence=0.95,
            )
        )
    return out


class TestDiagnostics:
    """Why a count is wrong, not just that it is.

    `attempted` >= `events` >= `predicted`, and the step where the number
    collapses names the stage at fault. Reporting only the final count leaves
    "the movement never happened", "it was too shallow to register" and "it was
    registered and refused" indistinguishable — three failures needing three
    different fixes.
    """

    def test_shallow_excursions_are_seen_but_emit_nothing(self) -> None:
        deep = cycles_between(2, 175.0, 45.0)
        shallow = cycles_between(6, 175.0, 130.0, start_ms=deep[-1].t_ms + 33.4)
        result = score_samples(deep + shallow, path="c.mp4", truth=8)

        # The state machine saw all eight; six were too shallow to become reps.
        assert result.attempted == 8
        assert result.events == 2
        assert result.predicted == 2

    def test_angle_distribution_survives_a_calibration_refusal(self) -> None:
        # The refusal is exactly when the distribution matters most: it is the
        # only evidence of whether the clip held a signal the range test missed.
        result = score_samples(samples(60, low=100.0, high=110.0), path="f.mp4", truth=4)
        assert result.predicted is None
        assert result.usable_frames == 60
        assert result.angle_percentiles["p50"] == pytest.approx(105.0, abs=1.0)

    def test_low_confidence_frames_are_excluded_from_the_distribution(self) -> None:
        good = samples(40, confidence=0.95)
        bad = samples(20, low=10.0, high=20.0, confidence=0.2)
        result = score_samples(good + bad, path="c.mp4", truth=1)
        assert result.usable_frames == 40
        assert result.angle_percentiles["p1"] > 20.0

    def test_flexion_percentiles_are_read_against_the_thresholds(self) -> None:
        result = score_samples(pullup_cycles(5), path="c.mp4", truth=5)
        # A clip of full reps must spend part of its time above `count_floor`.
        assert result.flexion_percentiles["p95"] > 0.75
        assert result.flexion_percentiles["p5"] < 0.12


class TestSegmentStability:
    """A tracking-quality signal MediaPipe does not grade itself.

    `confidence` is built from `visibility`, which claims a landmark was
    *found*, not that it was found in the right place. A rigid bone whose
    measured length wanders says the second thing, without ground truth.
    """

    def test_a_rigid_arm_is_stable(self) -> None:
        rows = [
            {
                "upper_arm_left": 0.30,
                "forearm_left": 0.25,
                "upper_arm_right": 0.30,
                "forearm_right": 0.25,
            }
            for _ in range(50)
        ]
        assert segment_stability(rows)["worst"] == pytest.approx(0.0)

    def test_a_wandering_segment_shows_up(self) -> None:
        rows = [
            {
                "upper_arm_left": 0.30,
                "forearm_left": 0.20 if i % 2 else 0.30,
                "upper_arm_right": 0.30,
                "forearm_right": 0.25,
            }
            for i in range(50)
        ]
        stability = segment_stability(rows)
        assert stability["forearm_left"] > 0.15
        assert stability["upper_arm_left"] == pytest.approx(0.0)
        assert stability["worst"] == stability["forearm_left"]

    def test_no_frames_is_not_perfect_stability(self) -> None:
        # A zero here would read as a flawless track on a clip nobody measured.
        assert segment_stability([]) == {}


class TestPeriodicityBaseline:
    """What the rhythm alone contains, as a floor under the amplitude-gated FSM.

    Not a replacement: it has no specificity (skipping rope is periodic too) and
    yields no per-rep quality. It exists so "our counter found 2" can be read
    against "the signal held 34".
    """

    def test_counts_the_rhythm_of_full_reps(self) -> None:
        found = periodicity_count(pullup_cycles(8))
        assert found is not None
        count, correlation = found
        assert abs(count - 8) <= 1
        assert correlation > 0.5

    def test_counts_reps_far_too_shallow_for_the_state_machine(self) -> None:
        # The whole point. These never approach `rep_floor`, so `RepCounter`
        # emits nothing, yet the rhythm is unambiguous.
        shallow = cycles_between(10, 175.0, 168.0)
        result = score_samples(shallow, path="c.mp4", truth=10)
        assert result.predicted is None or result.predicted == 0

        found = periodicity_count(shallow)
        assert found is not None
        assert abs(found[0] - 10) <= 1

    def test_refuses_a_signal_with_no_rhythm(self) -> None:
        flat = samples(200, low=140.0, high=141.0)
        assert periodicity_count(flat) is None

    def test_refuses_a_clip_too_short_to_judge(self) -> None:
        assert periodicity_count(pullup_cycles(1)[:40]) is None


class TestClassificationVerdict:
    """Windows reduced to one label per clip, without losing the refusals."""

    def test_the_dominant_named_label_wins(self) -> None:
        labels = [Exercise.PULL_UP] * 8 + [Exercise.DIP] * 2
        verdict = classification_verdict(labels)
        assert verdict["label"] == "pull_up"
        assert verdict["share"] == pytest.approx(0.8)

    def test_refusals_are_reported_beside_the_label_not_folded_in(self) -> None:
        # 9 refusals and one hesitant dip is not a dip. Keeping only the label
        # would say it was, and the counter would be let through.
        labels = [Exercise.UNKNOWN] * 9 + [Exercise.DIP]
        verdict = classification_verdict(labels)
        assert verdict["label"] == "dip"
        assert verdict["share"] == pytest.approx(0.1)
        assert verdict["unknown_share"] == pytest.approx(0.9)

    def test_all_refusals_yield_unknown(self) -> None:
        verdict = classification_verdict([Exercise.UNKNOWN] * 5)
        assert verdict["label"] == "unknown"
        assert verdict["unknown_share"] == 1.0

    def test_no_windows_invents_nothing(self) -> None:
        assert classification_verdict([])["label"] == ""


class TestGateReporting:
    """What the classifier would remove from the false-positive count."""

    def _fp(self, classified: str) -> ClipResult:
        result = clip(truth=5, predicted=4)
        result.exercise, result.classified_as = "pull_up", classified
        return result

    def test_a_clip_the_classifier_rejects_never_reaches_the_counter(self) -> None:
        summary = summarise_out_of_domain([self._fp("squat"), self._fp("unknown")])
        assert summary["false_positive_clips"] == 2
        assert summary["false_positive_clips_after_gate"] == 0
        assert summary["reps_invented_after_gate"] == 0

    def test_a_clip_it_accepts_still_counts(self) -> None:
        summary = summarise_out_of_domain([self._fp("pull_up"), self._fp("squat")])
        assert summary["false_positive_clips_after_gate"] == 1
        assert summary["reps_invented_after_gate"] == 4

    def test_an_unmeasured_gate_is_not_credited_with_a_save(self) -> None:
        # No classification ran. Reporting 0 survivors would claim a saving the
        # measurement never made.
        plain = clip(truth=5, predicted=4)
        summary = summarise_out_of_domain([plain])
        assert summary["false_positive_clips"] == 1
        assert summary["false_positive_clips_after_gate"] is None
