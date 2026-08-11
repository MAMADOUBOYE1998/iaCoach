"""Data contracts for iaCoach.

This module is the single source of truth for every structure that crosses a
boundary: browser -> API, API -> LLM, LLM -> API, API -> database.

The TypeScript mirror in ``web/src/types/contracts.ts`` is generated-adjacent
(hand-written, checked against the JSON Schema exported by
``scripts/export_schemas.py``). Never edit ``contracts/schema/`` by hand.

Conventions:
- Field names are English; user-facing strings produced by the coach are French.
- Every athlete-scoped row carries ``athlete_id`` so a future multi-user move is
  a migration, not a rewrite.
- Form scores are continuous in [0, 1]. Never booleans.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Unit = Annotated[float, Field(ge=0.0, le=1.0)]
"""A normalised score in [0, 1]. 1.0 = ideal, 0.0 = worst observed."""


class Exercise(StrEnum):
    """Exercises the movement classifier can emit.

    v1 ships pull-up end to end; the rest are declared so the classifier and the
    database schema are stable before the rules exist.
    """

    PULL_UP = "pull_up"
    CHIN_UP = "chin_up"
    DIP = "dip"
    PUSH_UP = "push_up"
    SQUAT = "squat"
    MUSCLE_UP = "muscle_up"
    L_SIT = "l_sit"
    UNKNOWN = "unknown"


class RepPhase(StrEnum):
    """Finite-state-machine states for a single repetition."""

    IDLE = "idle"
    ECCENTRIC = "eccentric"
    BOTTOM = "bottom"
    CONCENTRIC = "concentric"
    TOP = "top"


class Side(StrEnum):
    LEFT = "left"
    RIGHT = "right"


# --------------------------------------------------------------------------- #
# Athlete
# --------------------------------------------------------------------------- #


class Anthropometry(BaseModel):
    """Measured once at calibration. Used to normalise angles across body types."""

    model_config = ConfigDict(extra="forbid")

    height_m: float = Field(gt=0.5, lt=2.5)
    mass_kg: float | None = Field(default=None, gt=20.0, lt=250.0)
    arm_span_m: float | None = Field(default=None, gt=0.5, lt=2.6)


class ExerciseCalibration(BaseModel):
    """Per-athlete, per-exercise reference range of motion.

    All downstream thresholds are expressed as a fraction of this range, never as
    hard-coded angles. ``rom_min_deg``/``rom_max_deg`` are the joint angle
    extremes the athlete actually reached during a supervised calibration set.
    """

    model_config = ConfigDict(extra="forbid")

    exercise: Exercise
    joint: str = Field(description="Joint driving the FSM, e.g. 'elbow'.")
    rom_min_deg: float
    rom_max_deg: float
    captured_at: datetime
    confidence: Unit = Field(
        description="Fraction of calibration frames above the visibility threshold."
    )

    def normalised(self, angle_deg: float) -> float:
        """Map a raw joint angle onto [0, 1] within this athlete's own range."""
        span = self.rom_max_deg - self.rom_min_deg
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (angle_deg - self.rom_min_deg) / span))


class AthleteProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    athlete_id: str
    level: Literal["debutant", "intermediaire", "avance"]
    goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(
        default_factory=list,
        description="Injuries, equipment limits, schedule constraints. Free text.",
    )
    anthropometry: Anthropometry | None = None
    calibrations: list[ExerciseCalibration] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Rep-level telemetry
# --------------------------------------------------------------------------- #


class FrameSample(BaseModel):
    """One frame, reduced to the signals the rep counter consumes.

    This is the seam between pose estimation and analysis. The counter never
    sees raw landmarks: it sees derived quantities, which is what makes the same
    logic runnable on-device (from MediaPipe) and server-side (from a heavier
    model) without either knowing which produced it.

    All angles are computed from ``worldLandmarks`` — metric 3D — never from the
    normalised 2D set.
    """

    model_config = ConfigDict(extra="forbid")

    t_ms: float = Field(description="Monotonic offset from set start, milliseconds.")
    elbow_left_deg: float
    elbow_right_deg: float
    trunk_deg: float = Field(description="Trunk deviation from vertical, in degrees. 0 = upright.")
    hip_speed: float = Field(
        ge=0.0,
        description="Hip speed orthogonal to the movement axis, m/s. This is the "
        "kipping signal: a strict pull-up moves the hips very little sideways.",
    )
    confidence: Unit = Field(
        description="Fraction of the driving landmarks above the visibility "
        "threshold on this frame."
    )

    @property
    def elbow_mean_deg(self) -> float:
        return (self.elbow_left_deg + self.elbow_right_deg) / 2.0


class Tempo(BaseModel):
    """Phase durations in seconds. Mirrors the usual eccentric/pause/concentric
    notation used in strength programming."""

    model_config = ConfigDict(extra="forbid")

    eccentric_s: float = Field(ge=0.0)
    bottom_pause_s: float = Field(ge=0.0)
    concentric_s: float = Field(ge=0.0)
    top_pause_s: float = Field(ge=0.0)

    @property
    def total_s(self) -> float:
        return self.eccentric_s + self.bottom_pause_s + self.concentric_s + self.top_pause_s


class FormScores(BaseModel):
    """Continuous quality scores for one repetition.

    Each field is a magnitude of deviation normalised to [0, 1], where 1.0 means
    "no deviation detected". A rule never returns a boolean: the coaching layer
    needs to say "tu ne descends pas assez bas" with a degree, not "rep invalide".
    """

    model_config = ConfigDict(extra="forbid")

    rom: Unit = Field(description="Fraction of the athlete's calibrated range reached.")
    symmetry: Unit = Field(description="1.0 = identical left/right joint angles through the rep.")
    kipping: Unit = Field(
        description="1.0 = no parasitic hip momentum. Derived from pelvis "
        "acceleration orthogonal to the movement axis."
    )
    tempo_control: Unit = Field(
        description="1.0 = smooth, controlled velocity profile; low = jerky."
    )
    alignment: Unit = Field(description="1.0 = trunk/shoulder alignment held through the rep.")

    @property
    def overall(self) -> float:
        """Unweighted mean. Weighting is exercise-specific and lives in the rules,
        not here — this is a convenience for display only."""
        values = (
            self.rom,
            self.symmetry,
            self.kipping,
            self.tempo_control,
            self.alignment,
        )
        return sum(values) / len(values)


class RepEvent(BaseModel):
    """The central contract. Every counted repetition produces one of these.

    Nothing in the system increments a bare counter: fatigue tracking, progression,
    periodisation and the LLM coach are all built on the stream of RepEvents.
    """

    model_config = ConfigDict(extra="forbid")

    rep_index: int = Field(ge=0, description="0-based index within the set.")
    exercise: Exercise
    started_at_ms: float = Field(
        description="Monotonic clock offset from session start, in milliseconds."
    )
    duration_ms: float = Field(gt=0.0)
    tempo: Tempo
    scores: FormScores
    peak_angle_deg: float
    min_angle_deg: float
    confidence: Unit = Field(
        description="Fraction of frames in this rep whose driving landmarks were "
        "above the visibility threshold. Below ~0.7, corrections are suppressed."
    )
    counted: bool = Field(
        description="Whether this rep counts toward the valid total. A rep can be "
        "recorded with poor scores and still count; `counted=False` is reserved "
        "for reps that failed the hard ROM floor."
    )
    flags: list[str] = Field(
        default_factory=list,
        description="Machine-readable issue codes, e.g. 'rom_short', 'kipping', "
        "'left_lag'. Rendered to French by the UI, not stored in French.",
    )


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #


class SetSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise: Exercise
    reps: list[RepEvent]

    @property
    def valid_reps(self) -> int:
        return sum(1 for r in self.reps if r.counted)


class SessionSummary(BaseModel):
    """Aggregated, image-free payload. This — and only this — is what may be sent
    to the Anthropic API."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    athlete_id: str
    started_at: datetime
    duration_s: float = Field(ge=0.0)
    sets: list[SetSummary]
    perceived_effort: int | None = Field(
        default=None, ge=1, le=10, description="RPE, self-reported."
    )
    notes: str | None = Field(default=None, max_length=1000)


class HistoryPoint(BaseModel):
    """One past session, compressed to what the coach actually needs."""

    model_config = ConfigDict(extra="forbid")

    date: datetime
    exercise: Exercise
    total_reps: int = Field(ge=0)
    valid_reps: int = Field(ge=0)
    mean_rom: Unit
    mean_form: Unit


class ProgressPoint(BaseModel):
    """One point on a progression curve. Aggregated in SQL, not in Python: the
    database is where "volume per week" belongs."""

    model_config = ConfigDict(extra="forbid")

    date: datetime
    exercise: Exercise
    total_reps: int = Field(ge=0)
    valid_reps: int = Field(ge=0)
    mean_rom: Unit
    mean_form: Unit
    best_rom: Unit = Field(description="Best single-rep ROM of the session. The PR line.")


# --------------------------------------------------------------------------- #
# Exercise catalogue
# --------------------------------------------------------------------------- #


class ExerciseEntry(BaseModel):
    """One entry of the structured exercise database.

    French field names because these strings are handed to the coach and shown to
    the athlete verbatim; translating them at the boundary would only add a lossy
    step. ``tags`` stays machine-readable — it is what retrieval matches on.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    nom: str
    muscles: list[str]
    prerequis: list[str] = Field(default_factory=list)
    progressions: list[str] = Field(
        default_factory=list, description="Harder variants, by entry id."
    )
    regressions: list[str] = Field(
        default_factory=list, description="Easier variants, by entry id."
    )
    criteres_qualite: list[str]
    tags: list[str] = Field(
        description="Machine-readable needs this exercise addresses, e.g. "
        "'rom_short', 'kipping', 'scapular_control'. Retrieval matches on these."
    )


# --------------------------------------------------------------------------- #
# Coaching: request to the LLM, response from the LLM
# --------------------------------------------------------------------------- #


class CoachRequest(BaseModel):
    """Assembled server-side and rendered into the user turn. No raw landmarks,
    no imagery, ever."""

    model_config = ConfigDict(extra="forbid")

    athlete: AthleteProfile
    session: SessionSummary
    history: list[HistoryPoint] = Field(default_factory=list, max_length=30)
    catalogue: list[ExerciseEntry] = Field(
        default_factory=list,
        max_length=12,
        description="Exercise entries retrieved for this session's detected "
        "weaknesses. Keeps the coach's suggestions anchored to a real catalogue "
        "instead of invented movement names.",
    )


class SuggestedExercise(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nom: str
    raison: str
    series_reps: str


class NextSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    focus: str
    exercices: list[SuggestedExercise]
    duree_estimee_min: int = Field(ge=5, le=180)


class CoachResponse(BaseModel):
    """Schema the model is *constrained* to, via structured outputs — not a format
    requested in prose. Field names are French because they surface directly in
    the UI."""

    model_config = ConfigDict(extra="forbid")

    diagnostic: str
    points_faibles: list[str]
    exercices_suggeres: list[SuggestedExercise]
    seance_suivante: NextSession
    confiance: Literal["eleve", "moyen", "faible"]


__all__ = [
    "Anthropometry",
    "AthleteProfile",
    "CoachRequest",
    "CoachResponse",
    "Exercise",
    "ExerciseCalibration",
    "ExerciseEntry",
    "FormScores",
    "FrameSample",
    "HistoryPoint",
    "NextSession",
    "ProgressPoint",
    "RepEvent",
    "RepPhase",
    "SessionSummary",
    "SetSummary",
    "Side",
    "SuggestedExercise",
    "Tempo",
    "Unit",
]
