"""Deterministic bounding of the coach's proposal.

The model proposes; this decides. Every correction is recorded as a
``GuardrailAdjustment`` and shown to the athlete — a cap applied silently is
indistinguishable from a bug, and it removes the one signal that would let anyone
notice the model is systematically over-prescribing.

Nothing here rewrites the model's prose. The diagnostic and the reasoning are its
job; volume and scope are not.
"""

from __future__ import annotations

import re

from iacoach.contracts import (
    CoachResponse,
    ExerciseEntry,
    GuardrailAdjustment,
    NextSession,
    PlanConstraints,
    SuggestedExercise,
)

# A time unit right after the rep count means this is a hold, not reps: "3x30s"
# is three 30-second holds. Reading it as 90 reps would enforce the volume bound
# against a number nobody wrote.
#
# `(?!\d)` is load-bearing, not defensive: without it the engine backtracks and
# matches "3x3" out of "3x30s", because the character after that shorter match is
# a digit rather than a time unit. The guard has to reject a partial number
# before it can meaningfully reject a duration.
_NOT_A_DURATION = r"""(?!\d)(?!\s*(?:s\b|sec|min|["']))"""

SETS_REPS = re.compile(rf"(\d+)\s*[x×*]\s*(\d+){_NOT_A_DURATION}")
"""Matches '4x8', '4 × 8', '3*10'. Deliberately narrow: a pattern that tries to
understand every notation would silently mis-parse the ones it half-understands,
and an unparsed prescription is safer than a wrongly parsed one."""

SETS_REPS_RANGE = re.compile(rf"(\d+)\s*[x×*]\s*(\d+)\s*[-–]\s*(\d+){_NOT_A_DURATION}")
"""Matches '3x8-10'. Handled separately so the *upper* bound is used."""


def parse_volume(series_reps: str) -> int | None:
    """Total reps in a prescription like ``4x8``.

    Returns ``None`` when the notation is not recognised — a hold like "3x30s"
    has no rep count at all.

    A range like ``3x8-10`` resolves to its **upper** bound. This number feeds a
    safety ceiling, so the conservative read is the larger one: assuming the
    athlete does 24 when they may do 30 would let a session exceed the cap.
    """
    ranged = SETS_REPS_RANGE.search(series_reps)
    if ranged is not None:
        return int(ranged.group(1)) * int(ranged.group(3))

    match = SETS_REPS.search(series_reps)
    if match is None:
        return None
    return int(match.group(1)) * int(match.group(2))


def total_volume(exercises: list[SuggestedExercise]) -> tuple[int, int]:
    """Summed reps and the number of entries that could not be parsed."""
    total = 0
    unparsed = 0
    for exercise in exercises:
        volume = parse_volume(exercise.series_reps)
        if volume is None:
            unparsed += 1
        else:
            total += volume
    return total, unparsed


def _scale(series_reps: str, factor: float) -> str:
    """Scale a prescription down by reducing sets, not reps.

    Cutting reps per set changes the stimulus — a set of 8 and a set of 5 train
    different things. Cutting sets keeps each set intact and just does fewer of
    them, which is what a coach would actually do to shed volume.
    """
    match = SETS_REPS.search(series_reps)
    if match is None:
        return series_reps
    sets = int(match.group(1))
    reps = int(match.group(2))
    scaled = max(1, int(sets * factor))
    if scaled == sets:
        return series_reps
    return series_reps[: match.start()] + f"{scaled}x{reps}" + series_reps[match.end() :]


def apply(
    response: CoachResponse,
    constraints: PlanConstraints,
    catalogue: list[ExerciseEntry],
) -> tuple[CoachResponse, list[GuardrailAdjustment]]:
    """Hold the proposal to the constraints. Returns the bounded response and
    every adjustment applied."""
    adjustments: list[GuardrailAdjustment] = []
    next_session = response.seance_suivante

    exercises = list(next_session.exercices)

    # -- scope ------------------------------------------------------------- #
    if len(exercises) > constraints.max_exercises:
        adjustments.append(
            GuardrailAdjustment(
                champ="seance_suivante.exercices",
                raison=f"Maximum {constraints.max_exercises} exercices par séance.",
                propose=f"{len(exercises)} exercices",
                applique=f"{constraints.max_exercises} exercices",
            )
        )
        # Keep the first ones: the model is asked to order by importance, so
        # truncating the tail drops what it judged least essential.
        exercises = exercises[: constraints.max_exercises]

    # -- volume ------------------------------------------------------------ #
    volume, unparsed = total_volume(exercises)
    if volume > constraints.max_total_reps and constraints.max_total_reps > 0:
        factor = constraints.max_total_reps / volume
        exercises = [
            SuggestedExercise(
                nom=exercise.nom,
                raison=exercise.raison,
                series_reps=_scale(exercise.series_reps, factor),
            )
            for exercise in exercises
        ]
        applied, _ = total_volume(exercises)
        adjustments.append(
            GuardrailAdjustment(
                champ="seance_suivante.volume",
                raison=" ".join(constraints.rationale)
                or f"Plafond de {constraints.max_total_reps} reps.",
                propose=f"{volume} reps",
                applique=f"{applied} reps",
            )
        )

    if unparsed:
        # Not an error: holds and ranges are legitimate prescriptions. But the
        # athlete should know part of the volume was never checked.
        adjustments.append(
            GuardrailAdjustment(
                champ="seance_suivante.volume",
                raison="Notation non reconnue : ce volume n'a pas pu être vérifié.",
                propose=f"{unparsed} exercice(s) non chiffrable(s)",
                applique="laissé tel quel",
            )
        )

    # -- duration ---------------------------------------------------------- #
    duration = next_session.duree_estimee_min
    if duration > constraints.max_session_minutes:
        adjustments.append(
            GuardrailAdjustment(
                champ="seance_suivante.duree_estimee_min",
                raison=f"Séance plafonnée à {constraints.max_session_minutes} min.",
                propose=f"{duration} min",
                applique=f"{constraints.max_session_minutes} min",
            )
        )
        duration = constraints.max_session_minutes

    # -- catalogue anchoring ----------------------------------------------- #
    known = {entry.nom.casefold() for entry in catalogue}
    if known:
        off_catalogue = [
            exercise.nom for exercise in exercises if exercise.nom.casefold() not in known
        ]
        if off_catalogue:
            # Flagged, not removed. The prompt allows proposing something outside
            # the catalogue as long as it is declared; dropping it would discard a
            # legitimate suggestion, while hiding it would defeat the anchoring.
            adjustments.append(
                GuardrailAdjustment(
                    champ="seance_suivante.exercices",
                    raison="Hors du catalogue du projet — à vérifier avant de l'intégrer.",
                    propose=", ".join(off_catalogue),
                    applique="conservé, signalé",
                )
            )

    bounded = response.model_copy(
        update={
            "seance_suivante": NextSession(
                focus=next_session.focus,
                exercices=exercises,
                duree_estimee_min=duration,
            )
        }
    )
    return bounded, adjustments


__all__ = ["SETS_REPS", "apply", "parse_volume", "total_volume"]
