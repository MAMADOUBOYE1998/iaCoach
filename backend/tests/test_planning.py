"""Deterministic training-load model tests.

These lock the behaviour that keeps the LLM out of load decisions. A regression
here is not a cosmetic bug: it hands volume progression back to a component that
is not accountable for the consequences.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from factories import make_rep
from iacoach.contracts import Exercise, HistoryPoint, SessionSummary, SetSummary
from iacoach.planning import (
    FORM_DECLINE,
    HIGH_RATIO,
    MAX_GROWTH,
    MIN_SESSIONS_FOR_RATIO,
    compute_load,
    plan_constraints,
    session_confidence_is_low,
)

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def point(days_ago: float, *, valid_reps: int = 10, mean_form: float = 0.85) -> HistoryPoint:
    return HistoryPoint(
        date=NOW - timedelta(days=days_ago),
        exercise=Exercise.PULL_UP,
        total_reps=valid_reps,
        valid_reps=valid_reps,
        mean_rom=0.9,
        mean_form=mean_form,
    )


def session(valid: int = 10, *, confidence: float = 0.95) -> SessionSummary:
    return SessionSummary(
        session_id="s1",
        athlete_id="a1",
        started_at=NOW,
        duration_s=900.0,
        sets=[
            SetSummary(
                exercise=Exercise.PULL_UP,
                reps=[make_rep(i, confidence=confidence) for i in range(valid)],
            )
        ],
    )


class TestComputeLoad:
    def test_empty_history(self) -> None:
        load = compute_load([], now=NOW)
        assert load.acute_reps == 0
        assert load.ratio is None
        assert load.sessions_28d == 0

    def test_acute_window_is_seven_days(self) -> None:
        history = [point(2), point(6), point(9)]
        assert compute_load(history, now=NOW).acute_reps == 20

    def test_chronic_window_is_twenty_eight_days(self) -> None:
        history = [point(5), point(20), point(30)]
        load = compute_load(history, now=NOW)
        assert load.sessions_28d == 2
        assert load.chronic_reps_per_week == pytest.approx(20 / 4)

    def test_ratio_is_withheld_until_there_is_enough_history(self) -> None:
        """A ratio computed from three days of data is a number, not a signal."""
        thin = [point(i) for i in range(MIN_SESSIONS_FOR_RATIO - 1)]
        assert compute_load(thin, now=NOW).ratio is None

        enough = [point(i * 3) for i in range(MIN_SESSIONS_FOR_RATIO)]
        assert compute_load(enough, now=NOW).ratio is not None

    def test_ratio_detects_a_spike(self) -> None:
        # Steady 10 reps per session over four weeks, then a big week.
        history = [point(d) for d in (26, 20, 14, 10)] + [
            point(1, valid_reps=40),
            point(3, valid_reps=40),
        ]
        load = compute_load(history, now=NOW)
        assert load.ratio is not None
        assert load.ratio > HIGH_RATIO

    def test_form_trend_needs_four_points(self) -> None:
        """One bad session is noise; reacting to it would make the plan oscillate."""
        assert compute_load([point(1), point(3), point(5)], now=NOW).form_trend == 0.0

    def test_form_trend_is_negative_when_technique_degrades(self) -> None:
        history = [
            point(20, mean_form=0.90),
            point(16, mean_form=0.90),
            point(4, mean_form=0.70),
            point(2, mean_form=0.70),
        ]
        assert compute_load(history, now=NOW).form_trend == pytest.approx(-0.20)

    def test_ordering_of_the_input_does_not_matter(self) -> None:
        history = [point(2), point(10), point(20)]
        assert compute_load(history, now=NOW) == compute_load(list(reversed(history)), now=NOW)


class TestPlanConstraints:
    def test_no_history_gets_a_conservative_ceiling(self) -> None:
        """A first session is not evidence of capacity."""
        constraints = plan_constraints(session(8), compute_load([], now=NOW))
        assert constraints.allow_volume_increase is False
        assert constraints.rationale

    def test_thin_history_blocks_progression(self) -> None:
        load = compute_load([point(2), point(5)], now=NOW)
        constraints = plan_constraints(session(10), load)
        assert constraints.allow_volume_increase is False
        assert constraints.max_total_reps == 10

    def test_steady_history_allows_a_capped_increase(self) -> None:
        history = [point(d) for d in (24, 18, 12, 6)]
        constraints = plan_constraints(session(10), compute_load(history, now=NOW))
        assert constraints.allow_volume_increase is True
        assert constraints.max_total_reps == round(10 * MAX_GROWTH)

    def test_growth_is_capped_even_when_everything_is_green(self) -> None:
        """The ratio can justify holding; it never authorises exceeding the cap."""
        history = [point(d, valid_reps=100) for d in (24, 18, 12, 6)]
        constraints = plan_constraints(session(10), compute_load(history, now=NOW))
        assert constraints.max_total_reps <= round(10 * MAX_GROWTH)

    def test_a_load_spike_holds_volume(self) -> None:
        history = [point(d) for d in (26, 20, 14, 10)] + [
            point(1, valid_reps=40),
            point(3, valid_reps=40),
        ]
        constraints = plan_constraints(session(20), compute_load(history, now=NOW))
        assert constraints.allow_volume_increase is False
        assert constraints.max_total_reps == 20
        assert any("charge aiguë" in r.lower() for r in constraints.rationale)

    def test_declining_form_holds_volume(self) -> None:
        history = [
            point(24, mean_form=0.92),
            point(18, mean_form=0.92),
            point(8, mean_form=0.70),
            point(4, mean_form=0.70),
        ]
        load = compute_load(history, now=NOW)
        assert load.form_trend < FORM_DECLINE
        constraints = plan_constraints(session(10), load)
        assert constraints.allow_volume_increase is False
        assert any("qualité technique" in r.lower() for r in constraints.rationale)

    def test_low_confidence_blocks_progression(self) -> None:
        """No progression decided on measurements we do not trust."""
        history = [point(d) for d in (24, 18, 12, 6)]
        constraints = plan_constraints(
            session(10), compute_load(history, now=NOW), confidence_is_low=True
        )
        assert constraints.allow_volume_increase is False
        assert any("peu fiables" in r for r in constraints.rationale)

    def test_rationale_is_never_empty(self) -> None:
        """A cap the athlete cannot see is indistinguishable from a bug."""
        history = [point(d) for d in (24, 18, 12, 6)]
        for low in (True, False):
            constraints = plan_constraints(
                session(10), compute_load(history, now=NOW), confidence_is_low=low
            )
            assert constraints.rationale

    def test_ceiling_is_never_zero(self) -> None:
        constraints = plan_constraints(session(0), compute_load([point(1)], now=NOW))
        assert constraints.max_total_reps >= 1


class TestSessionConfidence:
    def test_good_tracking_is_not_low(self) -> None:
        assert session_confidence_is_low(session(5, confidence=0.95)) is False

    def test_poor_tracking_is_low(self) -> None:
        assert session_confidence_is_low(session(5, confidence=0.3)) is True

    def test_an_empty_session_is_treated_as_unreliable(self) -> None:
        """No measurements is not the same as good measurements."""
        empty = SessionSummary(
            session_id="s1",
            athlete_id="a1",
            started_at=NOW,
            duration_s=10.0,
            sets=[],
        )
        assert session_confidence_is_low(empty) is True
