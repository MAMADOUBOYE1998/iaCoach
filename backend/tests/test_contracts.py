"""Contract tests.

These lock the invariants that the rest of the system assumes. A change here
should be a deliberate contract change, not a side effect.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from factories import make_rep, make_scores
from iacoach.contracts import (
    AthleteProfile,
    Exercise,
    ExerciseCalibration,
    SessionSummary,
    SetSummary,
    Tempo,
)


class TestFormScores:
    def test_scores_are_bounded(self) -> None:
        """Scores outside [0, 1] are a bug upstream, not something to clamp here."""
        with pytest.raises(ValidationError):
            make_scores(rom=1.4)
        with pytest.raises(ValidationError):
            make_scores(symmetry=-0.1)

    def test_overall_is_the_mean(self) -> None:
        scores = make_scores(rom=1.0, symmetry=1.0, kipping=1.0, tempo_control=0.0, alignment=0.0)
        assert scores.overall == pytest.approx(0.6)

    def test_scores_are_continuous_not_boolean(self) -> None:
        """The whole point of the project: a rule reports a magnitude."""
        partial = make_scores(rom=0.62)
        assert 0.0 < partial.rom < 1.0


class TestRepEvent:
    def test_extra_fields_are_rejected(self) -> None:
        """A typo in a field name must fail loudly, not be silently dropped."""
        with pytest.raises(ValidationError):
            make_rep(romm=0.9)

    def test_zero_duration_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_rep(duration_ms=0.0)

    def test_a_rep_can_be_recorded_but_not_counted(self) -> None:
        """Failing the hard ROM floor records the rep with its scores; it just
        does not add to the valid total. The data is never discarded."""
        rep = make_rep(counted=False, scores=make_scores(rom=0.31), flags=["rom_short"])
        assert rep.counted is False
        assert rep.scores.rom == pytest.approx(0.31)

    def test_flags_are_machine_readable_codes(self) -> None:
        rep = make_rep(flags=["rom_short", "left_lag"])
        assert all(f.islower() and " " not in f for f in rep.flags)


class TestTempo:
    def test_total_sums_the_phases(self) -> None:
        tempo = Tempo(eccentric_s=1.5, bottom_pause_s=0.3, concentric_s=1.0, top_pause_s=0.2)
        assert tempo.total_s == pytest.approx(3.0)

    def test_negative_phase_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Tempo(eccentric_s=-0.1, bottom_pause_s=0.0, concentric_s=1.0, top_pause_s=0.0)


class TestCalibration:
    def test_normalises_within_the_athletes_own_range(self) -> None:
        calib = ExerciseCalibration(
            exercise=Exercise.PULL_UP,
            joint="elbow",
            rom_min_deg=40.0,
            rom_max_deg=170.0,
            captured_at=datetime.now(UTC),
            confidence=0.9,
        )
        assert calib.normalised(40.0) == pytest.approx(0.0)
        assert calib.normalised(170.0) == pytest.approx(1.0)
        assert calib.normalised(105.0) == pytest.approx(0.5)

    def test_out_of_range_angles_are_clamped(self) -> None:
        """An athlete exceeding a stale calibration must not produce rom > 1."""
        calib = ExerciseCalibration(
            exercise=Exercise.PULL_UP,
            joint="elbow",
            rom_min_deg=40.0,
            rom_max_deg=170.0,
            captured_at=datetime.now(UTC),
            confidence=0.9,
        )
        assert calib.normalised(200.0) == pytest.approx(1.0)
        assert calib.normalised(10.0) == pytest.approx(0.0)

    def test_degenerate_range_does_not_divide_by_zero(self) -> None:
        calib = ExerciseCalibration(
            exercise=Exercise.PULL_UP,
            joint="elbow",
            rom_min_deg=90.0,
            rom_max_deg=90.0,
            captured_at=datetime.now(UTC),
            confidence=0.1,
        )
        assert calib.normalised(90.0) == 0.0


class TestSessionSummary:
    def test_valid_reps_counts_only_counted_ones(self) -> None:
        reps = [make_rep(0), make_rep(1, counted=False), make_rep(2)]
        summary = SetSummary(exercise=Exercise.PULL_UP, reps=reps)
        assert summary.valid_reps == 2
        assert len(summary.reps) == 3

    def test_session_round_trips_through_json(self) -> None:
        """This payload is what crosses the wire to the API and the LLM."""
        session = SessionSummary(
            session_id="s1",
            athlete_id="a1",
            started_at=datetime.now(UTC),
            duration_s=900.0,
            sets=[SetSummary(exercise=Exercise.PULL_UP, reps=[make_rep(0)])],
            perceived_effort=7,
        )
        restored = SessionSummary.model_validate_json(session.model_dump_json())
        assert restored == session

    def test_rpe_is_bounded_to_the_usual_scale(self) -> None:
        with pytest.raises(ValidationError):
            SessionSummary(
                session_id="s1",
                athlete_id="a1",
                started_at=datetime.now(UTC),
                duration_s=1.0,
                sets=[],
                perceived_effort=11,
            )


class TestAthleteProfile:
    def test_profile_carries_athlete_id_for_future_multi_user(self) -> None:
        profile = AthleteProfile(athlete_id="a1", level="intermediaire")
        assert profile.athlete_id == "a1"
        assert profile.goals == []

    def test_unknown_level_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AthleteProfile(athlete_id="a1", level="expert")  # type: ignore[arg-type]
