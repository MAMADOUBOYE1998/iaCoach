"""Structured exercise database and retrieval.

The coach gets a *retrieved subset* of a real catalogue rather than free rein to
invent movement names. That is the whole point of the light RAG here: the model
is good at reading measurements and bad at knowing whether "scapular pull-up
negative hold" is a thing this athlete's programme uses.

Retrieval is deterministic and rule-based, not embedding-based. The mapping from
a detected fault to the exercises that address it is domain knowledge that should
be readable and reviewable, not buried in a vector index — and with 16 entries a
vector store would be pure ceremony.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from iacoach.contracts import Exercise, ExerciseEntry, SessionSummary

CATALOGUE_PATH = Path(__file__).parent / "data" / "exercises.json"

DEFAULT_LIMIT = 8

FLAG_TO_NEEDS: dict[str, tuple[str, ...]] = {
    "rom_short": ("amplitude", "force_bas", "scapulaire"),
    "kipping": ("anti_kipping", "gainage", "strict"),
    "asymmetry": ("symetrie", "unilateral"),
    "jerky": ("tempo", "controle"),
    "trunk_swing": ("gainage", "anti_kipping"),
    # Deliberately empty: no exercise fixes a tracking dropout. The fix is camera
    # placement, and suggesting accessory work for it would be noise.
    "low_confidence": (),
}

EXERCISE_TO_NEEDS: dict[Exercise, tuple[str, ...]] = {
    Exercise.PULL_UP: ("traction",),
    Exercise.CHIN_UP: ("traction",),
    Exercise.MUSCLE_UP: ("traction",),
    Exercise.DIP: ("poussee",),
    Exercise.PUSH_UP: ("poussee",),
    Exercise.L_SIT: ("gainage",),
}


@lru_cache(maxsize=1)
def load_catalogue() -> tuple[ExerciseEntry, ...]:
    raw = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
    return tuple(ExerciseEntry.model_validate(entry) for entry in raw)


def by_id(entry_id: str) -> ExerciseEntry | None:
    return next((e for e in load_catalogue() if e.id == entry_id), None)


def needs_for(session: SessionSummary) -> list[str]:
    """Machine-readable needs derived from what was actually measured.

    Ordered by how often the underlying fault occurred, so the retrieved
    catalogue leads with the athlete's dominant problem rather than an
    alphabetical accident.
    """
    counts: dict[str, int] = {}

    for set_summary in session.sets:
        for need in EXERCISE_TO_NEEDS.get(set_summary.exercise, ()):
            counts[need] = counts.get(need, 0) + 1
        for rep in set_summary.reps:
            for flag in rep.flags:
                for need in FLAG_TO_NEEDS.get(flag, ()):
                    counts[need] = counts.get(need, 0) + 1

    # Descending frequency, then alphabetical: determinism matters because this
    # feeds a prompt whose prefix we want to stay cacheable.
    return [need for need, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def retrieve(session: SessionSummary, *, limit: int = DEFAULT_LIMIT) -> list[ExerciseEntry]:
    """Catalogue entries relevant to this session's measured weaknesses.

    Falls back to the exercise's own family when no fault was detected — a clean
    session still deserves a progression suggestion, and returning nothing would
    push the model to invent one.
    """
    needs = needs_for(session)
    if not needs:
        return []

    weights = {need: len(needs) - i for i, need in enumerate(needs)}
    scored: list[tuple[int, str, ExerciseEntry]] = []
    for entry in load_catalogue():
        score = sum(weights.get(tag, 0) for tag in entry.tags)
        if score > 0:
            scored.append((score, entry.id, entry))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [entry for _, _, entry in scored[:limit]]


__all__ = [
    "CATALOGUE_PATH",
    "DEFAULT_LIMIT",
    "EXERCISE_TO_NEEDS",
    "FLAG_TO_NEEDS",
    "by_id",
    "load_catalogue",
    "needs_for",
    "retrieve",
]
