"""Anthropic Messages API client for the coaching layer.

Design notes:

- The response shape is enforced with **structured outputs**, not requested in
  prose. ``messages.parse()`` constrains the model to the ``CoachResponse``
  JSON Schema and returns a validated Pydantic object, so there is no preamble to
  strip and no defensive parsing to write.
- Only ``CoachRequest`` — aggregated numeric features — ever leaves the machine.
  No landmarks, no imagery.
- The system prompt carries a cache breakpoint: it is stable across every call
  and large enough to be worth caching.
"""

from __future__ import annotations

import logging

import anthropic

from iacoach.config import Settings, load_settings
from iacoach.contracts import CoachRequest, CoachResponse

from .prompt import load_system_prompt, render_user_turn

logger = logging.getLogger(__name__)

MAX_TOKENS = 4096


class CoachUnavailable(RuntimeError):
    """Raised when the coaching layer cannot produce a debrief.

    The caller is expected to degrade gracefully: rep counting and form scoring
    do not depend on this layer.
    """


class Coach:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or load_settings()
        if not self._settings.coaching_enabled:
            raise CoachUnavailable(
                "ANTHROPIC_API_KEY is not set. Counting and form scoring still "
                "work; only the LLM debrief is disabled."
            )
        self._client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key)

    def debrief(self, request: CoachRequest, *, model: str | None = None) -> CoachResponse:
        """Produce a session debrief.

        Raises ``CoachUnavailable`` on any API failure — the caller shows the
        session summary without a debrief rather than failing the whole flow.
        """
        try:
            response = self._client.messages.parse(
                model=model or self._settings.session_model,
                max_tokens=MAX_TOKENS,
                system=[
                    {
                        "type": "text",
                        "text": load_system_prompt(),
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": render_user_turn(request)}],
                output_format=CoachResponse,
            )
        except anthropic.RateLimitError as exc:
            raise CoachUnavailable("Rate limited by the Anthropic API.") from exc
        except anthropic.APIStatusError as exc:
            raise CoachUnavailable(f"Anthropic API error {exc.status_code}.") from exc
        except anthropic.APIConnectionError as exc:
            raise CoachUnavailable("Could not reach the Anthropic API.") from exc

        if response.stop_reason == "refusal":
            raise CoachUnavailable("The model declined to answer this request.")

        parsed = response.parsed_output
        if parsed is None:
            raise CoachUnavailable("The model returned no parsable debrief.")

        logger.info(
            "coach debrief ok: model=%s in=%d out=%d cache_read=%d",
            response.model,
            response.usage.input_tokens,
            response.usage.output_tokens,
            response.usage.cache_read_input_tokens or 0,
        )
        return parsed


__all__ = ["MAX_TOKENS", "Coach", "CoachUnavailable"]
