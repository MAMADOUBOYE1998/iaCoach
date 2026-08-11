"""Exercise catalogue and retrieval tests."""

from __future__ import annotations

from datetime import UTC, datetime

from factories import make_rep
from iacoach.catalogue import (
    FLAG_TO_NEEDS,
    by_id,
    load_catalogue,
    needs_for,
    retrieve,
)
from iacoach.contracts import Exercise, SessionSummary, SetSummary


def session_with(*flag_sets: list[str], exercise: Exercise = Exercise.PULL_UP) -> SessionSummary:
    return SessionSummary(
        session_id="s1",
        athlete_id="a1",
        started_at=datetime(2026, 8, 1, tzinfo=UTC),
        duration_s=600.0,
        sets=[
            SetSummary(
                exercise=exercise,
                reps=[make_rep(i, flags=flags) for i, flags in enumerate(flag_sets)],
            )
        ],
    )


class TestCatalogueIntegrity:
    def test_entries_load(self) -> None:
        assert len(load_catalogue()) >= 12

    def test_ids_are_unique(self) -> None:
        ids = [entry.id for entry in load_catalogue()]
        assert len(ids) == len(set(ids))

    def test_every_entry_has_quality_criteria_and_tags(self) -> None:
        """An entry without criteria is useless to the coach, and one without
        tags can never be retrieved."""
        for entry in load_catalogue():
            assert entry.criteres_qualite, entry.id
            assert entry.tags, entry.id

    def test_progressions_and_regressions_reference_real_entries(self) -> None:
        """A dangling id would surface as a suggestion the athlete cannot look up."""
        known = {entry.id for entry in load_catalogue()}
        for entry in load_catalogue():
            for ref in [*entry.progressions, *entry.regressions, *entry.prerequis]:
                assert ref in known, f"{entry.id} references unknown {ref}"

    def test_lookup_by_id(self) -> None:
        entry = by_id("traction_stricte")
        assert entry is not None
        assert entry.nom == "Traction stricte"
        assert by_id("does_not_exist") is None


class TestNeeds:
    def test_derives_needs_from_flags(self) -> None:
        needs = needs_for(session_with(["kipping"]))
        assert "anti_kipping" in needs
        assert "gainage" in needs

    def test_orders_by_frequency(self) -> None:
        """The dominant fault leads, so the retrieved catalogue is about the
        athlete's main problem rather than an alphabetical accident."""
        session = session_with(["kipping"], ["kipping"], ["kipping"], ["asymmetry"])
        needs = needs_for(session)
        assert needs.index("anti_kipping") < needs.index("symetrie")

    def test_low_confidence_contributes_nothing(self) -> None:
        """No exercise fixes a tracking dropout — the fix is camera placement, and
        suggesting accessory work for it would be noise."""
        assert FLAG_TO_NEEDS["low_confidence"] == ()
        needs = needs_for(session_with(["low_confidence"]))
        assert needs == ["traction"]  # only the exercise family remains

    def test_exercise_family_is_always_a_need(self) -> None:
        assert "traction" in needs_for(session_with([]))


class TestRetrieval:
    def test_kipping_retrieves_bracing_work(self) -> None:
        ids = [e.id for e in retrieve(session_with(["kipping"], ["kipping"]))]
        assert "hollow_body" in ids

    def test_asymmetry_retrieves_unilateral_work(self) -> None:
        ids = [e.id for e in retrieve(session_with(["asymmetry"], ["asymmetry"]))]
        assert any(i in ids for i in ("traction_archer", "rowing_unilateral"))

    def test_short_range_retrieves_bottom_end_strength(self) -> None:
        ids = [e.id for e in retrieve(session_with(["rom_short"], ["rom_short"]))]
        assert any(i in ids for i in ("traction_negative", "tirage_scapulaire"))

    def test_is_deterministic(self) -> None:
        """This feeds a prompt; a set-iteration-order wobble would change the
        bytes on every call for no reason."""
        session = session_with(["kipping"], ["asymmetry"], ["rom_short"])
        assert [e.id for e in retrieve(session)] == [e.id for e in retrieve(session)]

    def test_respects_the_limit(self) -> None:
        session = session_with(["kipping"], ["asymmetry"], ["rom_short"], ["jerky"])
        assert len(retrieve(session, limit=3)) == 3

    def test_clean_session_still_gets_suggestions(self) -> None:
        """A clean session deserves a progression; returning nothing would push
        the model to invent one."""
        assert retrieve(session_with([], [], [])) != []
