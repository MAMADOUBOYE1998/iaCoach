"""Rep counter behaviour, driven by hand-built sequences.

The fixture-driven conformance suite lives in ``test_conformance.py``; this file
covers the state machine's edges directly, where a fixture would be a clumsy way
to express the case.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from iacoach.contracts import Exercise, ExerciseCalibration, FrameSample, RepPhase
from iacoach.counting import DEFAULT_CONFIG, RepCounter, analyse_sequence

FPS = 30.0
STEP_MS = 1000.0 / FPS
ROM_MIN, ROM_MAX = 40.0, 172.0


def calibration(rom_min: float = ROM_MIN, rom_max: float = ROM_MAX) -> ExerciseCalibration:
    return ExerciseCalibration(
        exercise=Exercise.PULL_UP,
        joint="elbow",
        rom_min_deg=rom_min,
        rom_max_deg=rom_max,
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        confidence=1.0,
    )


def angle_for(flexion: float, rom_min: float = ROM_MIN, rom_max: float = ROM_MAX) -> float:
    return rom_max - flexion * (rom_max - rom_min)


def frames(
    flexions: list[float],
    *,
    hip_speed: float = 0.05,
    trunk_deg: float = 2.0,
    confidence: float = 1.0,
    asymmetry_deg: float = 0.0,
    rom_min: float = ROM_MIN,
    rom_max: float = ROM_MAX,
) -> list[FrameSample]:
    out: list[FrameSample] = []
    for i, f in enumerate(flexions):
        angle = angle_for(f, rom_min, rom_max)
        out.append(
            FrameSample(
                t_ms=i * STEP_MS,
                elbow_left_deg=angle + asymmetry_deg,
                elbow_right_deg=angle - asymmetry_deg,
                trunk_deg=trunk_deg,
                hip_speed=hip_speed,
                confidence=confidence,
            )
        )
    return out


def ramp(start: float, end: float, count: int) -> list[float]:
    if count <= 1:
        return [end]
    return [start + (end - start) * i / (count - 1) for i in range(count)]


def rep_profile(peak: float, *, hold: int = 8) -> list[float]:
    """A settle-in dead hang, a pull to `peak`, a hold, and a return."""
    return [0.0] * hold + ramp(0.0, peak, 20) + [peak] * hold + ramp(peak, 0.0, 20) + [0.0] * hold


class TestStateMachine:
    def test_counts_a_full_rep(self) -> None:
        events = analyse_sequence(Exercise.PULL_UP, calibration(), frames(rep_profile(0.95)))
        assert len(events) == 1
        assert events[0].counted is True
        assert events[0].rep_index == 0

    def test_starts_idle_and_waits_for_a_dead_hang(self) -> None:
        """Starting the app mid-pull must not fabricate a partial first rep."""
        counter = RepCounter(Exercise.PULL_UP, calibration())
        assert counter.phase is RepPhase.IDLE
        # Begin at the top and come down: the first descent is not a repetition.
        sequence = ramp(0.95, 0.0, 20) + [0.0] * 8
        emitted = [counter.push(s) for s in frames(sequence)]
        assert all(e is None for e in emitted)
        assert counter.phase is RepPhase.BOTTOM

    def test_noise_below_the_rep_floor_emits_nothing(self) -> None:
        sequence: list[float] = []
        for _ in range(4):
            sequence += rep_profile(0.30)
        assert analyse_sequence(Exercise.PULL_UP, calibration(), frames(sequence)) == []

    def test_short_rep_is_recorded_but_not_counted(self) -> None:
        """The data survives being imperfect: the coach needs to say 'your last
        three were short', which requires having them."""
        events = analyse_sequence(Exercise.PULL_UP, calibration(), frames(rep_profile(0.62)))
        assert len(events) == 1
        assert events[0].counted is False
        assert "rom_short" in events[0].flags
        assert events[0].scores.rom == pytest.approx(0.62, abs=0.05)

    def test_hysteresis_prevents_double_counting_at_the_top(self) -> None:
        """Dithering across the top threshold must produce one rep, not several."""
        dither = [0.76, 0.74, 0.76, 0.74, 0.76, 0.74] * 4
        sequence = [0.0] * 8 + ramp(0.0, 0.76, 20) + dither + ramp(0.76, 0.0, 20) + [0.0] * 8
        events = analyse_sequence(Exercise.PULL_UP, calibration(), frames(sequence))
        assert len(events) == 1

    def test_rep_indices_increment(self) -> None:
        sequence = rep_profile(0.95) * 3
        events = analyse_sequence(Exercise.PULL_UP, calibration(), frames(sequence))
        assert [e.rep_index for e in events] == [0, 1, 2]

    def test_incomplete_final_rep_is_not_emitted(self) -> None:
        """A set that ends at the top of a rep has not completed that rep."""
        sequence = [0.0] * 8 + ramp(0.0, 0.95, 20) + [0.95] * 10
        assert analyse_sequence(Exercise.PULL_UP, calibration(), frames(sequence)) == []


class TestCalibrationDrivesThresholds:
    def test_same_movement_scores_the_same_across_body_geometries(self) -> None:
        """The point of calibrating: an athlete whose usable range is 60-160 and
        one whose range is 40-172 both score ~0.9 for a rep to 90% of their own
        range. Hard-coded angles would score them differently."""
        tall = analyse_sequence(
            Exercise.PULL_UP,
            calibration(40.0, 172.0),
            frames(rep_profile(0.90), rom_min=40.0, rom_max=172.0),
        )
        short = analyse_sequence(
            Exercise.PULL_UP,
            calibration(60.0, 160.0),
            frames(rep_profile(0.90), rom_min=60.0, rom_max=160.0),
        )
        assert tall[0].scores.rom == pytest.approx(short[0].scores.rom, abs=0.02)


class TestScoring:
    def test_scores_stay_continuous(self) -> None:
        """Every score is a magnitude, never a verdict."""
        events = analyse_sequence(Exercise.PULL_UP, calibration(), frames(rep_profile(0.80)))
        scores = events[0].scores
        for value in (
            scores.rom,
            scores.symmetry,
            scores.kipping,
            scores.tempo_control,
            scores.alignment,
        ):
            assert 0.0 <= value <= 1.0

    def test_asymmetry_degrades_the_symmetry_score(self) -> None:
        even = analyse_sequence(Exercise.PULL_UP, calibration(), frames(rep_profile(0.90)))
        lopsided = analyse_sequence(
            Exercise.PULL_UP, calibration(), frames(rep_profile(0.90), asymmetry_deg=6.0)
        )
        assert lopsided[0].scores.symmetry < even[0].scores.symmetry
        assert "asymmetry" in lopsided[0].flags

    def test_hip_speed_degrades_the_kipping_score(self) -> None:
        strict = analyse_sequence(Exercise.PULL_UP, calibration(), frames(rep_profile(0.90)))
        kipped = analyse_sequence(
            Exercise.PULL_UP, calibration(), frames(rep_profile(0.90), hip_speed=1.4)
        )
        assert kipped[0].scores.kipping < strict[0].scores.kipping
        assert "kipping" in kipped[0].flags

    def test_tempo_phases_are_ordered_sensibly(self) -> None:
        events = analyse_sequence(Exercise.PULL_UP, calibration(), frames(rep_profile(0.95)))
        tempo = events[0].tempo
        assert tempo.concentric_s > 0
        assert tempo.eccentric_s > 0
        assert tempo.top_pause_s > 0
        assert tempo.total_s == pytest.approx(
            tempo.concentric_s + tempo.eccentric_s + tempo.top_pause_s + tempo.bottom_pause_s
        )


class TestConfidenceSuppressesCorrections:
    def test_low_confidence_reports_only_low_confidence(self) -> None:
        """A wrong correction is worse than none. When tracking is poor, every
        form score derived from those frames is unreliable, so the counter must
        not turn them into confident advice."""
        events = analyse_sequence(
            Exercise.PULL_UP,
            calibration(),
            frames(rep_profile(0.62), confidence=0.3, asymmetry_deg=8.0, hip_speed=1.5),
        )
        assert events[0].flags == ["low_confidence"]

    def test_the_rep_still_counts_when_range_was_reached(self) -> None:
        """Poor tracking should not silently cost the athlete reps."""
        events = analyse_sequence(
            Exercise.PULL_UP, calibration(), frames(rep_profile(0.95), confidence=0.3)
        )
        assert events[0].counted is True
        assert events[0].confidence == pytest.approx(0.3, abs=0.01)

    def test_threshold_matches_the_documented_invariant(self) -> None:
        assert DEFAULT_CONFIG.min_coachable_confidence == 0.70
