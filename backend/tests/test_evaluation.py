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
    detection_summary,
    orientation_summary,
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


class TestDetectionSummary:
    """Why the athlete was never a candidate, rather than which body to pick.

    Subject selection turned out to answer the wrong question on `084`: the
    tracker never had more than one candidate, so the athlete was not chosen
    against — they were never offered.
    """

    def test_a_still_box_through_many_reps_is_not_the_athlete(self) -> None:
        """The signal a rep count cannot give.

        A pull-up translates the whole body by roughly half a torso, every
        repetition. A box that barely moves through 34 annotated repetitions
        belongs to somebody else — and every angle-based quantity in the
        pipeline is blind to it, because angles do not care where a body is.
        """
        still = [{"box_centre_y": 0.5 + 0.001 * (i % 3)} for i in range(200)]

        found = detection_summary(still)

        assert found["box_centre_y_excursion"] < 0.01

    def test_a_moving_box_is_reported_as_moving(self) -> None:
        cycling = [{"box_centre_y": 0.4 + 0.2 * (i % 2)} for i in range(200)]

        assert detection_summary(cycling)["box_centre_y_excursion"] > 0.15

    def test_an_impossible_limb_ratio_is_flagged(self) -> None:
        """An upper arm shorter than its forearm belongs to no human.

        Measured on `084`: 0.94 and 0.99 left and right, where every person is
        between 1.05 and 1.35. That is a badly fitted skeleton, not an unusual
        build — and it is the reading of `segment_cv` this project got wrong,
        since a consistently wrong fit is perfectly stable.
        """
        frames = [{"limb_ratio": r} for r in (0.94, 0.99, 1.20, 0.95)]

        found = detection_summary(frames)

        assert found["limb_ratio_implausible"] == pytest.approx(0.75)

    def test_a_plausible_body_is_not_flagged(self) -> None:
        assert detection_summary([{"limb_ratio": 1.2}] * 10)["limb_ratio_implausible"] == 0.0

    def test_the_2d_ratio_is_carried_but_never_graded(self) -> None:
        """The band is a fact about 3D anatomy, so image space cannot be judged by it.

        This was added to localise the fault — plausible in 2D and impossible in
        3D would have blamed the depth estimate — and the test is invalid.
        Projection foreshortens whichever limb points at the camera, so a
        correct skeleton leaves the band in image space routinely. Over QUVA the
        2D ratio is outside the band on *more* frames than the 3D one (median
        76 % against 64 %), which is the artefact, not a finding. The value is
        kept as context; grading it would invite the reading it cannot support.
        """
        frames = [{"limb_ratio": 0.94, "limb_ratio_2d": 1.2}] * 10

        found = detection_summary(frames)

        assert found["limb_ratio_implausible"] == 1.0
        assert found["limb_ratio_2d"] == pytest.approx(1.2)
        assert "limb_ratio_2d_implausible" not in found

    def test_rigid_bones_make_a_varying_ratio_an_error_with_no_alibi(self) -> None:
        """The one detection signal that rests on geometry alone.

        Upper arm and forearm are rigid, so their ratio is a constant of the
        athlete: no pose, distance or camera angle can move it, and MediaPipe's
        per-detection scale cancels. Zero is the only correct answer, for any
        clip, whatever is being filmed. That is what `limb_ratio_implausible`
        cannot claim — it needs `HUMAN_LIMB_RATIO` to be the right band, and a
        band read off anthropometry is arguable in a way a rigid bone is not.
        """
        rigid = [{"limb_ratio": 1.2}] * 40
        wobbling = [{"limb_ratio": 1.2 + 0.3 * (i % 2)} for i in range(40)]

        assert detection_summary(rigid)["limb_ratio_cv"] == 0.0
        assert detection_summary(wobbling)["limb_ratio_cv"] > 0.1

    def test_a_ratio_read_on_a_fifth_of_the_clip_says_so(self) -> None:
        """Coverage travels with the value, or the value lies.

        The ratio is gated on `VISIBILITY_THRESHOLD` — invariant no. 5, the rule
        the correction stage already obeys. Frames where the arm is not visible
        contribute nothing rather than a guess. Without the coverage figure, a
        clip measured on a fifth of its frames reads exactly like one measured
        on all of them, and `limb_ratio_implausible` silently changes meaning.
        """
        measured = [{"limb_ratio": 1.2}] * 20
        gated_out = [{"box_height": 0.5}] * 80

        found = detection_summary(measured + gated_out)

        assert found["limb_ratio_frames"] == pytest.approx(0.2)
        assert found["limb_ratio_implausible"] == 0.0

    def test_a_stable_but_impossible_skeleton_is_caught_by_the_band_alone(self) -> None:
        """The two signals are complementary, and neither subsumes the other.

        A skeleton fitted consistently wrong holds its ratio perfectly steady —
        `limb_ratio_cv` sees nothing. Only the anatomical band catches it. The
        converse is `test_rigid_bones...`: a ratio swinging through the band is
        invisible to the band and obvious to the variation.
        """
        steady_and_wrong = [{"limb_ratio": 0.94}] * 40

        found = detection_summary(steady_and_wrong)

        assert found["limb_ratio_cv"] == 0.0
        assert found["limb_ratio_implausible"] == 1.0

    def test_a_small_body_in_frame_is_reported(self) -> None:
        """MediaPipe has a practical lower size limit; this is where it shows."""
        found = detection_summary([{"box_height": 0.08}] * 10)

        assert found["box_height"] == pytest.approx(0.08)

    def test_no_frames_reports_nothing(self) -> None:
        assert detection_summary([]) == {}


class TestOrientationSummary:
    """Per clip, so this question never needs a per-frame dump again.

    It took four passes to establish that `084` — annotated as pull-ups —
    never once shows the hands above the shoulders, and the last one only
    answered it because a CSV got opened by hand.
    """

    def test_reports_how_often_a_relation_is_negative(self) -> None:
        frames = [{"wrist_above_shoulder_y": v} for v in (-0.8, -0.9, -0.7, 0.4)]

        found = orientation_summary(frames)

        assert found["wrist_above_shoulder_y_negative"] == pytest.approx(0.75)
        assert found["wrist_above_shoulder_y"] < 0

    def test_the_084_signature(self) -> None:
        """Upright torso, hands never up: not an inversion, a wrong subject."""
        frames = [{"shoulder_above_hip": 1.0, "wrist_above_shoulder_y": -0.84}] * 50

        found = orientation_summary(frames)

        assert found["shoulder_above_hip_negative"] == 0.0
        assert found["wrist_above_shoulder_y_negative"] == 1.0

    def test_no_frames_reports_nothing(self) -> None:
        """`{}`, not zeros — zeros here would read as a measured upright body."""
        assert orientation_summary([]) == {}


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
