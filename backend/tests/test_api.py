"""API tests.

The coaching layer is stubbed: these cover routing, persistence and degradation,
not the model's output. Exercising a real API call in unit tests would be slow,
non-deterministic and billed.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from factories import make_rep
from iacoach import storage
from iacoach.api.app import app, get_conn, get_settings
from iacoach.coach.client import CoachUnavailable
from iacoach.config import Settings
from iacoach.contracts import (
    AthleteProfile,
    CoachResponse,
    Exercise,
    NextSession,
    SessionSummary,
    SetSummary,
)

DEBRIEF = CoachResponse(
    diagnostic="Amplitude en baisse sur la fin de série.",
    points_faibles=["amplitude"],
    exercices_suggeres=[],
    seance_suivante=NextSession(focus="tractions", exercices=[], duree_estimee_min=40),
    confiance="moyen",
)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "api.db"


@pytest.fixture
def settings(db: Path) -> Settings:
    return Settings(
        anthropic_api_key="test-key",
        database_url=f"sqlite:///{db}",
        session_model="claude-sonnet-5",
        planning_model="claude-opus-4-8",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    def override_conn() -> Iterator[sqlite3.Connection]:
        conn = storage.connect(settings.database_path)
        try:
            storage.init_schema(conn)
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_conn] = override_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def make_session(session_id: str = "s1", **overrides: object) -> SessionSummary:
    payload: dict[str, object] = {
        "session_id": session_id,
        "athlete_id": "a1",
        "started_at": datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        "duration_s": 900.0,
        "sets": [SetSummary(exercise=Exercise.PULL_UP, reps=[make_rep(0), make_rep(1)])],
    }
    payload.update(overrides)
    return SessionSummary(**payload)  # type: ignore[arg-type]


class TestHealth:
    def test_reports_coaching_availability(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["coaching_enabled"] is True

    def test_reports_coaching_disabled_without_a_key(self, db: Path) -> None:
        """Offline-first: no key is a normal configuration, not an error state."""
        offline = Settings(
            anthropic_api_key=None,
            database_url=f"sqlite:///{db}",
            session_model="claude-sonnet-5",
            planning_model="claude-opus-4-8",
        )
        app.dependency_overrides[get_settings] = lambda: offline
        try:
            with TestClient(app) as local:
                assert local.get("/health").json()["coaching_enabled"] is False
        finally:
            app.dependency_overrides.clear()


class TestAthletes:
    def test_upsert_and_fetch(self, client: TestClient) -> None:
        profile = AthleteProfile(athlete_id="a1", level="avance", goals=["muscle-up"])
        assert client.post("/athletes", json=profile.model_dump(mode="json")).status_code == 200
        fetched = client.get("/athletes/a1").json()
        assert fetched["level"] == "avance"

    def test_unknown_athlete_is_404(self, client: TestClient) -> None:
        assert client.get("/athletes/nobody").status_code == 404


class TestSessions:
    def test_store_and_fetch(self, client: TestClient) -> None:
        session = make_session()
        assert client.post("/sessions", json=session.model_dump(mode="json")).status_code == 200
        fetched = client.get("/sessions/s1").json()
        assert len(fetched["sets"][0]["reps"]) == 2

    def test_replay_is_idempotent(self, client: TestClient) -> None:
        """The PWA retries sends it is unsure about; a replay must not duplicate."""
        payload = make_session().model_dump(mode="json")
        client.post("/sessions", json=payload)
        client.post("/sessions", json=payload)
        assert len(client.get("/sessions/s1").json()["sets"][0]["reps"]) == 2

    def test_rejects_a_malformed_session(self, client: TestClient) -> None:
        assert client.post("/sessions", json={"session_id": "s1"}).status_code == 422

    def test_unknown_session_is_404(self, client: TestClient) -> None:
        assert client.get("/sessions/nope").status_code == 404

    def test_progress_is_empty_for_a_new_athlete(self, client: TestClient) -> None:
        assert client.get("/athletes/a1/progress").json() == []

    def test_progress_reflects_stored_sessions(self, client: TestClient) -> None:
        client.post("/sessions", json=make_session().model_dump(mode="json"))
        points = client.get("/athletes/a1/progress").json()
        assert len(points) == 1
        assert points[0]["total_reps"] == 2

    def test_progress_filters_by_exercise(self, client: TestClient) -> None:
        client.post("/sessions", json=make_session().model_dump(mode="json"))
        assert client.get("/athletes/a1/progress?exercise=dip").json() == []


class TestDebrief:
    def test_debriefs_a_stored_session(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("iacoach.api.app.Coach", lambda _s: _StubCoach(DEBRIEF))
        client.post("/sessions", json=make_session().model_dump(mode="json"))
        body = client.post("/sessions/s1/debrief").json()
        assert body["diagnostic"] == DEBRIEF.diagnostic

    def test_second_call_is_served_from_cache(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Re-opening a past session must not re-bill the API."""
        stub = _StubCoach(DEBRIEF)
        monkeypatch.setattr("iacoach.api.app.Coach", lambda _s: stub)
        client.post("/sessions", json=make_session().model_dump(mode="json"))
        client.post("/sessions/s1/debrief")
        client.post("/sessions/s1/debrief")
        assert stub.calls == 1

    def test_refresh_bypasses_the_cache(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = _StubCoach(DEBRIEF)
        monkeypatch.setattr("iacoach.api.app.Coach", lambda _s: stub)
        client.post("/sessions", json=make_session().model_dump(mode="json"))
        client.post("/sessions/s1/debrief")
        client.post("/sessions/s1/debrief?refresh=true")
        assert stub.calls == 2

    def test_unavailable_coach_is_503_not_500(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The measurements are the product. A missing debrief degrades the
        experience; it must not look like the session failed to record."""
        monkeypatch.setattr("iacoach.api.app.Coach", lambda _s: _FailingCoach())
        client.post("/sessions", json=make_session().model_dump(mode="json"))
        response = client.post("/sessions/s1/debrief")
        assert response.status_code == 503
        # The session itself is still intact and readable.
        assert client.get("/sessions/s1").status_code == 200

    def test_debriefing_an_unknown_session_is_404(self, client: TestClient) -> None:
        assert client.post("/sessions/nope/debrief").status_code == 404

    def test_payload_carries_history_and_catalogue(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = _StubCoach(DEBRIEF)
        monkeypatch.setattr("iacoach.api.app.Coach", lambda _s: stub)
        client.post(
            "/sessions",
            json=make_session("s0", started_at=datetime(2026, 7, 25, 9, 0, tzinfo=UTC)).model_dump(
                mode="json"
            ),
        )
        client.post("/sessions", json=make_session("s1").model_dump(mode="json"))
        client.post("/sessions/s1/debrief")

        assert stub.last is not None
        assert stub.last.catalogue, "retrieval should anchor suggestions to the catalogue"
        assert len(stub.last.history) == 1, "the session being debriefed is not its own history"

    def test_missing_profile_does_not_block_a_first_debrief(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = _StubCoach(DEBRIEF)
        monkeypatch.setattr("iacoach.api.app.Coach", lambda _s: stub)
        client.post("/sessions", json=make_session().model_dump(mode="json"))
        assert client.post("/sessions/s1/debrief").status_code == 200
        assert stub.last is not None
        assert stub.last.athlete.athlete_id == "a1"


class _StubCoach:
    def __init__(self, response: CoachResponse) -> None:
        self.response = response
        self.calls = 0
        self.last = None

    def debrief(self, request, *, model=None):
        self.calls += 1
        self.last = request
        return self.response


class _FailingCoach:
    def debrief(self, request, *, model=None):
        raise CoachUnavailable("no key configured")
