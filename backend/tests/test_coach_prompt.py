"""Prompt assembly tests.

The privacy guarantee — no imagery, no raw landmarks leaving the device — is
enforced by the *shape of the payload*, so it is tested here rather than trusted.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from factories import make_rep
from iacoach.coach.prompt import load_system_prompt, render_user_turn
from iacoach.contracts import (
    AthleteProfile,
    CoachRequest,
    Exercise,
    SessionSummary,
    SetSummary,
)


def make_request() -> CoachRequest:
    return CoachRequest(
        athlete=AthleteProfile(athlete_id="a1", level="intermediaire", goals=["premier muscle-up"]),
        session=SessionSummary(
            session_id="s1",
            athlete_id="a1",
            started_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
            duration_s=1200.0,
            sets=[SetSummary(exercise=Exercise.PULL_UP, reps=[make_rep(0), make_rep(1)])],
        ),
    )


class TestSystemPrompt:
    def test_prompt_file_is_present_and_versioned(self) -> None:
        prompt = load_system_prompt()
        assert "Version" in prompt
        assert len(prompt) > 500

    def test_prompt_forbids_medical_advice(self) -> None:
        """A regression here is a safety regression, not a style one."""
        prompt = load_system_prompt().lower()
        assert "professionnel de santé" in prompt
        assert "diagnostic médical" in prompt

    def test_prompt_requires_honest_confidence(self) -> None:
        prompt = load_system_prompt().lower()
        assert "confiance" in prompt
        assert "faible" in prompt

    def test_prompt_is_stable_across_calls(self) -> None:
        """Byte-identical across calls, or prompt caching never hits."""
        assert load_system_prompt() is load_system_prompt()


class TestUserTurn:
    def test_payload_is_valid_json(self) -> None:
        rendered = render_user_turn(make_request())
        body = rendered.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
        assert json.loads(body)["athlete"]["athlete_id"] == "a1"

    def test_serialisation_is_deterministic(self) -> None:
        """Unsorted keys would change the prefix bytes on every call and silently
        defeat prompt caching."""
        request = make_request()
        assert render_user_turn(request) == render_user_turn(request)

    def test_no_landmarks_or_imagery_reach_the_payload(self) -> None:
        """The privacy invariant: only derived numeric features leave the device."""
        rendered = render_user_turn(make_request()).lower()
        for leak in ("landmark", "base64", "image", "frame_data", "video"):
            assert leak not in rendered
