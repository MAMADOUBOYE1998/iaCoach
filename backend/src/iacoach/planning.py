"""Deterministic training-load model.

This runs **before** the coach is called and produces the bounds the coach's
proposal is held to. It is plain arithmetic over measured history: no model, no
judgement calls that cannot be read off the code.

Why it exists: the LLM is good at reading a session and saying something useful
about technique. It is not a safe place to decide how much load an athlete takes
next week, because nothing in its training makes it accountable for the injury
that follows. So the model proposes and this decides — the invariant is enforced
here, not asked for in a prompt.

The acute:chronic workload ratio is the standard sports-science framing (7-day
load over 28-day average). It is a heuristic with real limits and a contested
literature; it is used here as a *brake*, never as a licence to push. A ratio in
the comfortable band never authorises more than the growth cap below.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from iacoach.contracts import HistoryPoint, PlanConstraints, SessionSummary, TrainingLoad

ACUTE_WINDOW_DAYS = 7
CHRONIC_WINDOW_DAYS = 28

MAX_GROWTH = 1.10
"""Hardest cap on volume growth per session. Even a perfectly recovered athlete
with flawless technique gets at most +10% — the ratio can justify holding, never
exceeding this."""

HIGH_RATIO = 1.30
"""Above this acute:chronic ratio, no increase is authorised."""

MIN_SESSIONS_FOR_RATIO = 4
"""Below this, the 28-day denominator is too thin for the ratio to mean
anything. Reporting one anyway would dress up noise as a signal."""

FORM_DECLINE = -0.03
"""Drop in mean form score that blocks a volume increase. Technique degrading
under load is the earliest signal available here, and it is cheap to respect."""

BASELINE_REPS = 20
"""Volume ceiling for an athlete with no history at all. Deliberately modest: a
first session is not evidence of capacity."""

MAX_SESSION_MINUTES = 75
MAX_EXERCISES = 5


@dataclass(frozen=True)
class Windows:
    """Split of history into the two comparison windows."""

    acute: list[HistoryPoint]
    chronic: list[HistoryPoint]


def split_windows(history: list[HistoryPoint], now: datetime) -> Windows:
    acute_cutoff = now - timedelta(days=ACUTE_WINDOW_DAYS)
    chronic_cutoff = now - timedelta(days=CHRONIC_WINDOW_DAYS)
    return Windows(
        acute=[p for p in history if p.date >= acute_cutoff],
        chronic=[p for p in history if p.date >= chronic_cutoff],
    )


def compute_load(history: list[HistoryPoint], *, now: datetime | None = None) -> TrainingLoad:
    """Load state from measured history. Newest-first or oldest-first both work."""
    now = now or datetime.now(UTC)
    windows = split_windows(history, now)

    acute_reps = sum(p.valid_reps for p in windows.acute)
    chronic_reps = sum(p.valid_reps for p in windows.chronic)
    chronic_per_week = chronic_reps / (CHRONIC_WINDOW_DAYS / 7)

    ratio: float | None = None
    if len(windows.chronic) >= MIN_SESSIONS_FOR_RATIO and chronic_per_week > 0:
        ratio = acute_reps / chronic_per_week

    return TrainingLoad(
        acute_reps=acute_reps,
        chronic_reps_per_week=chronic_per_week,
        ratio=ratio,
        form_trend=_form_trend(windows.chronic),
        sessions_28d=len(windows.chronic),
    )


def _form_trend(points: list[HistoryPoint]) -> float:
    """Recent mean form minus the mean form before it.

    Split down the middle rather than "last session vs the rest": a single bad
    session is noise, and reacting to it would make the plan oscillate.
    """
    if len(points) < 4:
        return 0.0
    ordered = sorted(points, key=lambda p: p.date)
    half = len(ordered) // 2
    older = ordered[:half]
    recent = ordered[half:]
    mean = lambda group: sum(p.mean_form for p in group) / len(group)  # noqa: E731
    return mean(recent) - mean(older)


LOW_CONFIDENCE = 0.70
"""Mirrors the counter's coachable-confidence floor. A session whose tracking was
mostly unreliable is not evidence of capacity, in either direction."""


def session_confidence_is_low(session: SessionSummary) -> bool:
    """Whether this session's measurements are too shaky to plan on.

    Uses the mean over recorded reps rather than any single one: one bad rep in a
    good set is normal, a whole set below the floor is not.
    """
    confidences = [rep.confidence for s in session.sets for rep in s.reps]
    if not confidences:
        return True
    return sum(confidences) / len(confidences) < LOW_CONFIDENCE


def plan_constraints(
    session: SessionSummary,
    load: TrainingLoad,
    *,
    confidence_is_low: bool = False,
) -> PlanConstraints:
    """Bounds for the next session.

    The rationale is part of the output, in French, and shown to the athlete: a
    cap the athlete cannot see is indistinguishable from a bug.
    """
    performed = sum(1 for set_summary in session.sets for rep in set_summary.reps if rep.counted)
    rationale: list[str] = []

    if load.sessions_28d == 0:
        ceiling = max(performed, BASELINE_REPS)
        rationale.append(
            f"Pas d'historique : plafond prudent à {ceiling} reps pour la prochaine séance."
        )
        return PlanConstraints(
            max_total_reps=ceiling,
            max_session_minutes=MAX_SESSION_MINUTES,
            max_exercises=MAX_EXERCISES,
            allow_volume_increase=False,
            rationale=rationale,
        )

    allow_increase = True

    if load.ratio is not None and load.ratio > HIGH_RATIO:
        allow_increase = False
        rationale.append(
            f"Charge aiguë à {load.ratio:.2f}× la charge chronique "
            f"(seuil {HIGH_RATIO:.2f}) : volume maintenu, pas augmenté."
        )
    elif load.ratio is None:
        allow_increase = False
        rationale.append(
            f"Moins de {MIN_SESSIONS_FOR_RATIO} séances sur 28 jours : "
            "historique trop mince pour justifier une progression."
        )

    if load.form_trend < FORM_DECLINE:
        allow_increase = False
        rationale.append(
            f"Qualité technique en baisse ({load.form_trend:+.2f}) : "
            "volume maintenu tant qu'elle ne remonte pas."
        )

    if confidence_is_low:
        allow_increase = False
        rationale.append(
            "Mesures peu fiables sur cette séance : aucune progression décidée sur "
            "des données douteuses."
        )

    ceiling = round(performed * MAX_GROWTH) if allow_increase else performed
    if allow_increase:
        rationale.append(
            f"Progression autorisée, plafonnée à +{round((MAX_GROWTH - 1) * 100)}% "
            f"({performed} → {ceiling} reps)."
        )

    return PlanConstraints(
        max_total_reps=max(ceiling, 1),
        max_session_minutes=MAX_SESSION_MINUTES,
        max_exercises=MAX_EXERCISES,
        allow_volume_increase=allow_increase,
        rationale=rationale,
    )


__all__ = [
    "ACUTE_WINDOW_DAYS",
    "BASELINE_REPS",
    "CHRONIC_WINDOW_DAYS",
    "FORM_DECLINE",
    "HIGH_RATIO",
    "LOW_CONFIDENCE",
    "MAX_EXERCISES",
    "MAX_GROWTH",
    "MAX_SESSION_MINUTES",
    "MIN_SESSIONS_FOR_RATIO",
    "Windows",
    "compute_load",
    "plan_constraints",
    "session_confidence_is_low",
    "split_windows",
]
