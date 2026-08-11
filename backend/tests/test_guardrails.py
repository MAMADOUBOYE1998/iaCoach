"""Guardrail tests.

The model proposes; these decide. Every case here is a way the model's answer
could have reached the athlete unbounded.
"""

from __future__ import annotations

import pytest

from iacoach.catalogue import by_id
from iacoach.coach import guardrails
from iacoach.contracts import (
    CoachResponse,
    NextSession,
    PlanConstraints,
    SuggestedExercise,
)


def constraints(
    *, max_total_reps: int = 40, max_exercises: int = 5, max_session_minutes: int = 75
) -> PlanConstraints:
    return PlanConstraints(
        max_total_reps=max_total_reps,
        max_session_minutes=max_session_minutes,
        max_exercises=max_exercises,
        allow_volume_increase=False,
        rationale=["Charge maintenue."],
    )


def response(exercises: list[SuggestedExercise], *, minutes: int = 45) -> CoachResponse:
    return CoachResponse(
        diagnostic="Amplitude en baisse en fin de série.",
        points_faibles=["amplitude"],
        exercices_suggeres=[],
        seance_suivante=NextSession(
            focus="tractions", exercices=exercises, duree_estimee_min=minutes
        ),
        confiance="moyen",
    )


def exercise(nom: str, series_reps: str) -> SuggestedExercise:
    return SuggestedExercise(nom=nom, raison="parce que", series_reps=series_reps)


class TestParseVolume:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("4x8", 32),
            ("4 x 8", 32),
            ("4×8", 32),
            ("3*10", 30),
            ("4x8 avec 90 s de repos", 32),
        ],
    )
    def test_recognised_notations(self, text: str, expected: int) -> None:
        assert guardrails.parse_volume(text) == expected

    @pytest.mark.parametrize("text", ["3x30s", "AMRAP", "3 séries jusqu'à l'échec", ""])
    def test_unrecognised_notations_return_none(self, text: str) -> None:
        """A hold or a range has no single rep count. Inventing one would let a
        bound be enforced against a number nobody wrote."""
        assert guardrails.parse_volume(text) is None

    def test_a_range_resolves_to_its_upper_bound(self) -> None:
        # This number feeds a safety ceiling, so the conservative read is the
        # larger one: assuming 24 when the athlete may do 30 lets a session
        # exceed the cap.
        assert guardrails.parse_volume("3x8-10") == 30

    def test_a_hold_is_not_read_as_reps(self) -> None:
        # '3x30s' is three 30-second holds, not 90 reps.
        assert guardrails.parse_volume("3x30s") is None
        assert guardrails.parse_volume("3x30 secondes") is None

    def test_a_word_starting_with_s_is_not_a_time_unit(self) -> None:
        assert guardrails.parse_volume("4x8 sur barre haute") == 32


class TestScope:
    def test_truncates_an_overlong_session(self) -> None:
        proposal = response([exercise(f"Exercice {i}", "3x8") for i in range(8)])
        bounded, adjustments = guardrails.apply(proposal, constraints(max_exercises=3), [])
        assert len(bounded.seance_suivante.exercices) == 3
        assert any(a.champ == "seance_suivante.exercices" for a in adjustments)

    def test_keeps_the_first_exercises(self) -> None:
        """The model is asked to order by importance, so the tail is what it
        judged least essential."""
        proposal = response([exercise("Prioritaire", "3x8"), exercise("Secondaire", "3x8")])
        bounded, _ = guardrails.apply(proposal, constraints(max_exercises=1), [])
        assert bounded.seance_suivante.exercices[0].nom == "Prioritaire"

    def test_a_session_within_scope_is_untouched(self) -> None:
        proposal = response([exercise("Traction stricte", "3x8")])
        bounded, adjustments = guardrails.apply(proposal, constraints(), [])
        assert bounded.seance_suivante.exercices == proposal.seance_suivante.exercices
        assert adjustments == []


class TestVolume:
    def test_scales_an_over_budget_session_down(self) -> None:
        proposal = response([exercise("Traction stricte", "10x8")])  # 80 reps
        bounded, adjustments = guardrails.apply(proposal, constraints(max_total_reps=40), [])
        volume, _ = guardrails.total_volume(bounded.seance_suivante.exercices)
        assert volume <= 40
        assert any(a.champ == "seance_suivante.volume" for a in adjustments)

    def test_cuts_sets_rather_than_reps(self) -> None:
        """A set of 8 and a set of 5 train different things. Shedding volume by
        doing fewer full sets is what a coach would actually do."""
        proposal = response([exercise("Traction stricte", "10x8")])
        bounded, _ = guardrails.apply(proposal, constraints(max_total_reps=40), [])
        assert bounded.seance_suivante.exercices[0].series_reps.startswith("5x8")

    def test_reports_the_reason_from_the_plan(self) -> None:
        plan = constraints(max_total_reps=10)
        plan = plan.model_copy(update={"rationale": ["Charge aiguë trop élevée."]})
        proposal = response([exercise("Traction stricte", "10x8")])
        _, adjustments = guardrails.apply(proposal, plan, [])
        volume_adjustment = next(a for a in adjustments if a.champ == "seance_suivante.volume")
        assert "Charge aiguë" in volume_adjustment.raison

    def test_flags_volume_it_could_not_verify(self) -> None:
        """Holds and ranges are legitimate prescriptions, but the athlete should
        know part of the volume went unchecked."""
        proposal = response([exercise("Hollow body hold", "3x30s")])
        _, adjustments = guardrails.apply(proposal, constraints(), [])
        assert any("non reconnue" in a.raison for a in adjustments)

    def test_a_session_within_budget_is_untouched(self) -> None:
        proposal = response([exercise("Traction stricte", "4x8")])
        bounded, adjustments = guardrails.apply(proposal, constraints(max_total_reps=40), [])
        assert bounded.seance_suivante.exercices[0].series_reps == "4x8"
        assert adjustments == []


class TestDuration:
    def test_caps_an_overlong_session(self) -> None:
        proposal = response([exercise("Traction stricte", "4x8")], minutes=120)
        bounded, adjustments = guardrails.apply(proposal, constraints(max_session_minutes=75), [])
        assert bounded.seance_suivante.duree_estimee_min == 75
        assert any(a.champ == "seance_suivante.duree_estimee_min" for a in adjustments)

    def test_a_reasonable_duration_is_untouched(self) -> None:
        proposal = response([exercise("Traction stricte", "4x8")], minutes=40)
        bounded, _ = guardrails.apply(proposal, constraints(), [])
        assert bounded.seance_suivante.duree_estimee_min == 40


class TestCatalogueAnchoring:
    def test_flags_an_off_catalogue_suggestion(self) -> None:
        entry = by_id("traction_stricte")
        assert entry is not None
        proposal = response([exercise("Traction cosmique inversée", "4x8")])
        bounded, adjustments = guardrails.apply(proposal, constraints(), [entry])
        # Flagged, not removed: the prompt allows an off-catalogue proposal as
        # long as it is declared, and dropping it would discard a real suggestion.
        assert len(bounded.seance_suivante.exercices) == 1
        assert any("Hors du catalogue" in a.raison for a in adjustments)

    def test_a_catalogue_exercise_is_not_flagged(self) -> None:
        entry = by_id("traction_stricte")
        assert entry is not None
        proposal = response([exercise("Traction stricte", "4x8")])
        _, adjustments = guardrails.apply(proposal, constraints(), [entry])
        assert adjustments == []

    def test_matching_ignores_case(self) -> None:
        entry = by_id("traction_stricte")
        assert entry is not None
        proposal = response([exercise("TRACTION STRICTE", "4x8")])
        _, adjustments = guardrails.apply(proposal, constraints(), [entry])
        assert adjustments == []

    def test_no_catalogue_means_no_anchoring_check(self) -> None:
        proposal = response([exercise("N'importe quoi", "4x8")])
        _, adjustments = guardrails.apply(proposal, constraints(), [])
        assert adjustments == []


class TestProseIsLeftAlone:
    def test_diagnostic_and_confidence_are_never_rewritten(self) -> None:
        """Volume and scope are the deterministic stage's business. The reading of
        the session is the model's."""
        proposal = response([exercise("Traction stricte", "20x10")], minutes=170)
        bounded, _ = guardrails.apply(proposal, constraints(max_total_reps=10), [])
        assert bounded.diagnostic == proposal.diagnostic
        assert bounded.points_faibles == proposal.points_faibles
        assert bounded.confiance == proposal.confiance
        assert bounded.seance_suivante.focus == proposal.seance_suivante.focus
