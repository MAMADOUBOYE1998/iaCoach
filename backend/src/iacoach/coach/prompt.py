"""Assembles the coaching prompt.

The system prompt is versioned in ``prompts/coaching.md`` and read from disk, so
changing coaching behaviour is a reviewable diff, not a code edit.
"""

from __future__ import annotations

import json
from functools import lru_cache

from iacoach.config import PROMPTS_DIR
from iacoach.contracts import CoachRequest

SYSTEM_PROMPT_PATH = PROMPTS_DIR / "coaching.md"


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    """Read the versioned coaching prompt.

    Cached because it is stable for the process lifetime — and because the system
    prompt sits at the front of the cacheable prefix, so it must be byte-identical
    across requests for prompt caching to hit.
    """
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


def render_user_turn(request: CoachRequest) -> str:
    """Render the session payload as the user turn.

    JSON with sorted keys: a stable serialisation keeps the prefix bytes stable
    for the parts that repeat (athlete profile, history), which is what prompt
    caching keys on.
    """
    payload = request.model_dump(mode="json")
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return (
        "Voici les données mesurées de la séance qui vient de se terminer, "
        "ainsi que le profil de l'athlète et son historique récent.\n\n"
        f"```json\n{body}\n```\n\n"
        "Analyse ces données et produis le débrief."
    )


__all__ = ["SYSTEM_PROMPT_PATH", "load_system_prompt", "render_user_turn"]
