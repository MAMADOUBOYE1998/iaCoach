"""Persistence tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from factories import make_rep, make_scores
from iacoach import storage
from iacoach.contracts import (
    AthleteProfile,
    CoachResponse,
    Exercise,
    NextSession,
    SessionSummary,
    SetSummary,
)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = storage.connect(tmp_path / "test.db")
    storage.init_schema(connection)
    yield connection
    connection.close()


def make_session(
    session_id: str = "s1",
    *,
    athlete_id: str = "a1",
    started_at: datetime | None = None,
    reps: list | None = None,
) -> SessionSummary:
    return SessionSummary(
        session_id=session_id,
        athlete_id=athlete_id,
        started_at=started_at or datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        duration_s=900.0,
        sets=[
            SetSummary(
                exercise=Exercise.PULL_UP,
                reps=reps if reps is not None else [make_rep(0), make_rep(1)],
            )
        ],
        perceived_effort=7,
    )


class TestAthlete:
    def test_round_trips(self, conn: sqlite3.Connection) -> None:
        profile = AthleteProfile(
            athlete_id="a1", level="avance", goals=["muscle-up"], constraints=["épaule droite"]
        )
        storage.upsert_athlete(conn, profile)
        assert storage.load_athlete(conn, "a1") == profile

    def test_upsert_replaces_rather_than_duplicating(self, conn: sqlite3.Connection) -> None:
        storage.upsert_athlete(conn, AthleteProfile(athlete_id="a1", level="debutant"))
        storage.upsert_athlete(conn, AthleteProfile(athlete_id="a1", level="avance"))
        loaded = storage.load_athlete(conn, "a1")
        assert loaded is not None
        assert loaded.level == "avance"
        assert conn.execute("SELECT COUNT(*) FROM athletes").fetchone()[0] == 1

    def test_unknown_athlete_is_none(self, conn: sqlite3.Connection) -> None:
        assert storage.load_athlete(conn, "nobody") is None


class TestSession:
    def test_round_trips(self, conn: sqlite3.Connection) -> None:
        session = make_session()
        storage.save_session(conn, session)
        assert storage.load_session(conn, "s1") == session

    def test_resync_replaces_instead_of_duplicating(self, conn: sqlite3.Connection) -> None:
        """The PWA queues sessions offline and retries sends it is unsure about,
        so at-least-once delivery is the normal case."""
        storage.save_session(conn, make_session())
        storage.save_session(conn, make_session())
        assert conn.execute("SELECT COUNT(*) FROM reps").fetchone()[0] == 2

    def test_resync_with_fewer_reps_drops_the_stale_ones(self, conn: sqlite3.Connection) -> None:
        storage.save_session(conn, make_session(reps=[make_rep(0), make_rep(1), make_rep(2)]))
        storage.save_session(conn, make_session(reps=[make_rep(0)]))
        loaded = storage.load_session(conn, "s1")
        assert loaded is not None
        assert len(loaded.sets[0].reps) == 1

    def test_multiple_sets_keep_their_boundaries(self, conn: sqlite3.Connection) -> None:
        session = SessionSummary(
            session_id="s2",
            athlete_id="a1",
            started_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
            duration_s=600.0,
            sets=[
                SetSummary(exercise=Exercise.PULL_UP, reps=[make_rep(0), make_rep(1)]),
                SetSummary(exercise=Exercise.PULL_UP, reps=[make_rep(0)]),
            ],
        )
        storage.save_session(conn, session)
        loaded = storage.load_session(conn, "s2")
        assert loaded is not None
        assert [len(s.reps) for s in loaded.sets] == [2, 1]

    def test_flags_and_counted_survive_the_round_trip(self, conn: sqlite3.Connection) -> None:
        rep = make_rep(0, counted=False, flags=["rom_short", "kipping"])
        storage.save_session(conn, make_session(reps=[rep]))
        loaded = storage.load_session(conn, "s1")
        assert loaded is not None
        assert loaded.sets[0].reps[0].flags == ["rom_short", "kipping"]
        assert loaded.sets[0].reps[0].counted is False

    def test_unknown_session_is_none(self, conn: sqlite3.Connection) -> None:
        assert storage.load_session(conn, "nope") is None

    def test_lists_newest_first(self, conn: sqlite3.Connection) -> None:
        base = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
        for i in range(3):
            storage.save_session(conn, make_session(f"s{i}", started_at=base + timedelta(days=i)))
        assert storage.list_sessions(conn, "a1") == ["s2", "s1", "s0"]


class TestAggregates:
    def test_history_is_computed_in_sql(self, conn: sqlite3.Connection) -> None:
        reps = [make_rep(0), make_rep(1, counted=False), make_rep(2)]
        storage.save_session(conn, make_session(reps=reps))
        history = storage.recent_history(conn, "a1")
        assert len(history) == 1
        assert history[0].total_reps == 3
        assert history[0].valid_reps == 2

    def test_history_scoped_to_the_athlete(self, conn: sqlite3.Connection) -> None:
        storage.save_session(conn, make_session("s1", athlete_id="a1"))
        storage.save_session(conn, make_session("s2", athlete_id="a2"))
        assert len(storage.recent_history(conn, "a1")) == 1

    def test_progress_is_chronological(self, conn: sqlite3.Connection) -> None:
        """Oldest first — the order a chart wants, and the opposite of the
        newest-first order the coach history uses."""
        base = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
        for i in range(3):
            storage.save_session(conn, make_session(f"s{i}", started_at=base + timedelta(days=i)))
        points = storage.progress_series(conn, "a1")
        assert [p.date for p in points] == sorted(p.date for p in points)

    def test_progress_tracks_the_best_rep_separately_from_the_mean(
        self, conn: sqlite3.Connection
    ) -> None:
        """The PR line and the average line tell different stories; a session can
        raise one without moving the other."""
        reps = [
            make_rep(0, scores=make_scores(rom=0.60)),
            make_rep(1, scores=make_scores(rom=0.98)),
        ]
        storage.save_session(conn, make_session(reps=reps))
        point = storage.progress_series(conn, "a1")[0]
        assert point.best_rom == pytest.approx(0.98)
        assert point.mean_rom == pytest.approx(0.79)

    def test_progress_filters_by_exercise(self, conn: sqlite3.Connection) -> None:
        storage.save_session(conn, make_session())
        assert storage.progress_series(conn, "a1", exercise=Exercise.PULL_UP)
        assert storage.progress_series(conn, "a1", exercise=Exercise.DIP) == []

    def test_empty_history_is_empty_not_an_error(self, conn: sqlite3.Connection) -> None:
        assert storage.recent_history(conn, "nobody") == []
        assert storage.progress_series(conn, "nobody") == []


class TestDebriefCache:
    def make_response(self, diagnostic: str = "ok") -> CoachResponse:
        return CoachResponse(
            diagnostic=diagnostic,
            points_faibles=["amplitude"],
            exercices_suggeres=[],
            seance_suivante=NextSession(focus="tractions", exercices=[], duree_estimee_min=40),
            confiance="moyen",
        )

    def test_round_trips(self, conn: sqlite3.Connection) -> None:
        storage.save_session(conn, make_session())
        response = self.make_response()
        storage.save_debrief(conn, "s1", response, model="claude-sonnet-5")
        assert storage.load_debrief(conn, "s1") == response

    def test_refresh_overwrites(self, conn: sqlite3.Connection) -> None:
        storage.save_session(conn, make_session())
        storage.save_debrief(conn, "s1", self.make_response("first"), model="m")
        storage.save_debrief(conn, "s1", self.make_response("second"), model="m")
        cached = storage.load_debrief(conn, "s1")
        assert cached is not None
        assert cached.diagnostic == "second"

    def test_deleting_a_session_cascades(self, conn: sqlite3.Connection) -> None:
        """Foreign keys are off by default in SQLite; this asserts the pragma is
        actually applied, not just declared in the schema."""
        storage.save_session(conn, make_session())
        storage.save_debrief(conn, "s1", self.make_response(), model="m")
        with conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", ("s1",))
        assert storage.load_debrief(conn, "s1") is None
        assert conn.execute("SELECT COUNT(*) FROM reps").fetchone()[0] == 0
