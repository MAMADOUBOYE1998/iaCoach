"""SQLite persistence.

Plain ``sqlite3`` rather than an ORM: the Pydantic contracts are already the
source of truth for shape, and an ORM would introduce a second, competing model
definition to keep in sync. What is left is a thin mapping layer, and it is
better read than generated.

Reps are stored as columns, not as a JSON blob. "Mean ROM per week" and "best rep
of the session" are aggregate queries, and they belong in SQL — a blob would push
every progression view into a Python loop over the full history.

Every athlete-scoped row carries ``athlete_id``, so moving to multi-user later is
a migration rather than a rewrite. Postgres remains the documented prod option;
nothing here uses SQLite-only syntax beyond the pragmas.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from iacoach.contracts import (
    AthleteProfile,
    CoachResponse,
    Exercise,
    FormScores,
    HistoryPoint,
    ProgressPoint,
    RepEvent,
    SessionSummary,
    SetSummary,
    Tempo,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS athletes (
    athlete_id   TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id       TEXT PRIMARY KEY,
    athlete_id       TEXT NOT NULL,
    started_at       TEXT NOT NULL,
    duration_s       REAL NOT NULL,
    perceived_effort INTEGER,
    notes            TEXT,
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS sessions_by_athlete
    ON sessions (athlete_id, started_at DESC);

CREATE TABLE IF NOT EXISTS reps (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    athlete_id     TEXT NOT NULL,
    set_index      INTEGER NOT NULL,
    rep_index      INTEGER NOT NULL,
    exercise       TEXT NOT NULL,
    started_at_ms  REAL NOT NULL,
    duration_ms    REAL NOT NULL,
    eccentric_s    REAL NOT NULL,
    bottom_pause_s REAL NOT NULL,
    concentric_s   REAL NOT NULL,
    top_pause_s    REAL NOT NULL,
    rom            REAL NOT NULL,
    symmetry       REAL NOT NULL,
    kipping        REAL NOT NULL,
    tempo_control  REAL NOT NULL,
    alignment      REAL NOT NULL,
    peak_angle_deg REAL NOT NULL,
    min_angle_deg  REAL NOT NULL,
    confidence     REAL NOT NULL,
    counted        INTEGER NOT NULL,
    flags_json     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS reps_by_session ON reps (session_id, set_index, rep_index);
CREATE INDEX IF NOT EXISTS reps_by_athlete ON reps (athlete_id, exercise);

CREATE TABLE IF NOT EXISTS debriefs (
    session_id    TEXT PRIMARY KEY REFERENCES sessions (session_id) ON DELETE CASCADE,
    response_json TEXT NOT NULL,
    model         TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
"""


def connect(database: str | Path) -> sqlite3.Connection:
    """Open a connection with the pragmas this schema assumes.

    ``foreign_keys`` is off by default in SQLite, so the cascade deletes declared
    above would silently do nothing without it. WAL keeps a read during a write
    from blocking, which matters as soon as the PWA syncs while a query runs.
    """
    conn = sqlite3.connect(database, detect_types=0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def session_scope(database: str | Path) -> Iterator[sqlite3.Connection]:
    conn = connect(database)
    try:
        init_schema(conn)
        yield conn
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(UTC).isoformat()


# --------------------------------------------------------------------------- #
# Athlete
# --------------------------------------------------------------------------- #


def upsert_athlete(conn: sqlite3.Connection, profile: AthleteProfile) -> None:
    conn.execute(
        """
        INSERT INTO athletes (athlete_id, profile_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT (athlete_id) DO UPDATE SET
            profile_json = excluded.profile_json,
            updated_at   = excluded.updated_at
        """,
        (profile.athlete_id, profile.model_dump_json(), _now()),
    )
    conn.commit()


def load_athlete(conn: sqlite3.Connection, athlete_id: str) -> AthleteProfile | None:
    row = conn.execute(
        "SELECT profile_json FROM athletes WHERE athlete_id = ?", (athlete_id,)
    ).fetchone()
    if row is None:
        return None
    return AthleteProfile.model_validate_json(row["profile_json"])


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #


def save_session(conn: sqlite3.Connection, summary: SessionSummary) -> None:
    """Persist a session and its reps.

    Idempotent on ``session_id``: re-syncing the same session replaces it rather
    than duplicating it. The PWA queues sessions offline and may retry a send it
    is not sure landed, so at-least-once delivery is the normal case, not an edge
    case.
    """
    with conn:  # implicit transaction: reps and session commit together or not at all
        conn.execute(
            """
            INSERT INTO sessions (
                session_id, athlete_id, started_at, duration_s,
                perceived_effort, notes, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (session_id) DO UPDATE SET
                athlete_id       = excluded.athlete_id,
                started_at       = excluded.started_at,
                duration_s       = excluded.duration_s,
                perceived_effort = excluded.perceived_effort,
                notes            = excluded.notes
            """,
            (
                summary.session_id,
                summary.athlete_id,
                summary.started_at.isoformat(),
                summary.duration_s,
                summary.perceived_effort,
                summary.notes,
                _now(),
            ),
        )
        conn.execute("DELETE FROM reps WHERE session_id = ?", (summary.session_id,))
        conn.executemany(
            """
            INSERT INTO reps (
                session_id, athlete_id, set_index, rep_index, exercise,
                started_at_ms, duration_ms,
                eccentric_s, bottom_pause_s, concentric_s, top_pause_s,
                rom, symmetry, kipping, tempo_control, alignment,
                peak_angle_deg, min_angle_deg, confidence, counted, flags_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    summary.session_id,
                    summary.athlete_id,
                    set_index,
                    rep.rep_index,
                    rep.exercise.value,
                    rep.started_at_ms,
                    rep.duration_ms,
                    rep.tempo.eccentric_s,
                    rep.tempo.bottom_pause_s,
                    rep.tempo.concentric_s,
                    rep.tempo.top_pause_s,
                    rep.scores.rom,
                    rep.scores.symmetry,
                    rep.scores.kipping,
                    rep.scores.tempo_control,
                    rep.scores.alignment,
                    rep.peak_angle_deg,
                    rep.min_angle_deg,
                    rep.confidence,
                    int(rep.counted),
                    json.dumps(rep.flags),
                )
                for set_index, set_summary in enumerate(summary.sets)
                for rep in set_summary.reps
            ],
        )


def _rep_from_row(row: sqlite3.Row) -> RepEvent:
    return RepEvent(
        rep_index=row["rep_index"],
        exercise=Exercise(row["exercise"]),
        started_at_ms=row["started_at_ms"],
        duration_ms=row["duration_ms"],
        tempo=Tempo(
            eccentric_s=row["eccentric_s"],
            bottom_pause_s=row["bottom_pause_s"],
            concentric_s=row["concentric_s"],
            top_pause_s=row["top_pause_s"],
        ),
        scores=FormScores(
            rom=row["rom"],
            symmetry=row["symmetry"],
            kipping=row["kipping"],
            tempo_control=row["tempo_control"],
            alignment=row["alignment"],
        ),
        peak_angle_deg=row["peak_angle_deg"],
        min_angle_deg=row["min_angle_deg"],
        confidence=row["confidence"],
        counted=bool(row["counted"]),
        flags=json.loads(row["flags_json"]),
    )


def load_session(conn: sqlite3.Connection, session_id: str) -> SessionSummary | None:
    header = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if header is None:
        return None

    rows = conn.execute(
        "SELECT * FROM reps WHERE session_id = ? ORDER BY set_index, rep_index",
        (session_id,),
    ).fetchall()

    sets: list[SetSummary] = []
    current_index: int | None = None
    for row in rows:
        if row["set_index"] != current_index:
            current_index = row["set_index"]
            sets.append(SetSummary(exercise=Exercise(row["exercise"]), reps=[]))
        sets[-1].reps.append(_rep_from_row(row))

    return SessionSummary(
        session_id=header["session_id"],
        athlete_id=header["athlete_id"],
        started_at=datetime.fromisoformat(header["started_at"]),
        duration_s=header["duration_s"],
        sets=sets,
        perceived_effort=header["perceived_effort"],
        notes=header["notes"],
    )


def list_sessions(conn: sqlite3.Connection, athlete_id: str, *, limit: int = 20) -> list[str]:
    rows = conn.execute(
        "SELECT session_id FROM sessions WHERE athlete_id = ? ORDER BY started_at DESC LIMIT ?",
        (athlete_id, limit),
    ).fetchall()
    return [row["session_id"] for row in rows]


# --------------------------------------------------------------------------- #
# Aggregates
# --------------------------------------------------------------------------- #

_AGGREGATE_SELECT = """
    SELECT
        s.started_at                       AS started_at,
        r.exercise                         AS exercise,
        COUNT(*)                           AS total_reps,
        SUM(r.counted)                     AS valid_reps,
        AVG(r.rom)                         AS mean_rom,
        MAX(r.rom)                         AS best_rom,
        AVG(
            (r.rom + r.symmetry + r.kipping + r.tempo_control + r.alignment) / 5.0
        )                                  AS mean_form
    FROM reps r
    JOIN sessions s ON s.session_id = r.session_id
    WHERE r.athlete_id = ?
"""


def recent_history(
    conn: sqlite3.Connection, athlete_id: str, *, limit: int = 10
) -> list[HistoryPoint]:
    """Compressed history for the coach: one row per session and exercise.

    Aggregated in SQL so the coach payload stays small regardless of how many
    reps the athlete has logged — the model needs the trend, not the raw stream.
    """
    rows = conn.execute(
        _AGGREGATE_SELECT
        + """
        GROUP BY r.session_id, r.exercise
        ORDER BY s.started_at DESC
        LIMIT ?
        """,
        (athlete_id, limit),
    ).fetchall()

    return [
        HistoryPoint(
            date=datetime.fromisoformat(row["started_at"]),
            exercise=Exercise(row["exercise"]),
            total_reps=row["total_reps"],
            valid_reps=row["valid_reps"],
            mean_rom=row["mean_rom"],
            mean_form=row["mean_form"],
        )
        for row in rows
    ]


def progress_series(
    conn: sqlite3.Connection,
    athlete_id: str,
    *,
    exercise: Exercise | None = None,
    limit: int = 90,
) -> list[ProgressPoint]:
    """Chronological progression, oldest first — the order a chart wants."""
    params: list[object] = [athlete_id]
    clause = ""
    if exercise is not None:
        clause = " AND r.exercise = ?"
        params.append(exercise.value)
    params.append(limit)

    rows = conn.execute(
        _AGGREGATE_SELECT
        + clause
        + """
        GROUP BY r.session_id, r.exercise
        ORDER BY s.started_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()

    points = [
        ProgressPoint(
            date=datetime.fromisoformat(row["started_at"]),
            exercise=Exercise(row["exercise"]),
            total_reps=row["total_reps"],
            valid_reps=row["valid_reps"],
            mean_rom=row["mean_rom"],
            mean_form=row["mean_form"],
            best_rom=row["best_rom"],
        )
        for row in rows
    ]
    points.reverse()
    return points


# --------------------------------------------------------------------------- #
# Debriefs
# --------------------------------------------------------------------------- #


def save_debrief(
    conn: sqlite3.Connection, session_id: str, response: CoachResponse, *, model: str
) -> None:
    """Cache the debrief so re-opening a past session does not re-bill the API."""
    with conn:
        conn.execute(
            """
            INSERT INTO debriefs (session_id, response_json, model, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (session_id) DO UPDATE SET
                response_json = excluded.response_json,
                model         = excluded.model,
                created_at    = excluded.created_at
            """,
            (session_id, response.model_dump_json(), model, _now()),
        )


def load_debrief(conn: sqlite3.Connection, session_id: str) -> CoachResponse | None:
    row = conn.execute(
        "SELECT response_json FROM debriefs WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row is None:
        return None
    return CoachResponse.model_validate_json(row["response_json"])


__all__ = [
    "SCHEMA",
    "connect",
    "init_schema",
    "list_sessions",
    "load_athlete",
    "load_debrief",
    "load_session",
    "progress_series",
    "recent_history",
    "save_debrief",
    "save_session",
    "session_scope",
    "upsert_athlete",
]
