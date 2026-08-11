"""FastAPI application.

Everything here is asynchronous work: persistence, aggregation, and the LLM
debrief. Rep counting and form scoring never touch this layer — they run in the
browser, inside the ~100 ms correction window.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from iacoach import storage
from iacoach.catalogue import retrieve
from iacoach.coach.client import Coach, CoachUnavailable
from iacoach.config import Settings, load_settings
from iacoach.contracts import (
    AthleteProfile,
    CoachRequest,
    CoachResponse,
    Exercise,
    ProgressPoint,
    SessionSummary,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="iaCoach API",
    version="0.3.0",
    summary="Coaching and persistence layer. Real-time analysis runs on-device.",
)

# The PWA runs on a separate dev origin; production serves both from one host.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)


def get_settings() -> Settings:
    return load_settings()


def get_conn(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[sqlite3.Connection]:
    """One connection per request.

    SQLite connections are not safe to share across threads, and FastAPI runs
    sync endpoints in a thread pool — a module-level connection would be a
    latent, load-dependent bug.
    """
    conn = storage.connect(settings.database_path)
    try:
        storage.init_schema(conn)
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
Config = Annotated[Settings, Depends(get_settings)]


@app.get("/health")
def health(settings: Config) -> dict[str, object]:
    return {
        "status": "ok",
        "coaching_enabled": settings.coaching_enabled,
        "session_model": settings.session_model,
    }


# --------------------------------------------------------------------------- #
# Athlete
# --------------------------------------------------------------------------- #


@app.post("/athletes", response_model=AthleteProfile)
def put_athlete(profile: AthleteProfile, conn: Conn) -> AthleteProfile:
    storage.upsert_athlete(conn, profile)
    return profile


@app.get("/athletes/{athlete_id}", response_model=AthleteProfile)
def get_athlete(athlete_id: str, conn: Conn) -> AthleteProfile:
    profile = storage.load_athlete(conn, athlete_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Unknown athlete")
    return profile


@app.get("/athletes/{athlete_id}/progress", response_model=list[ProgressPoint])
def get_progress(
    athlete_id: str,
    conn: Conn,
    exercise: Annotated[Exercise | None, Query()] = None,
) -> list[ProgressPoint]:
    return storage.progress_series(conn, athlete_id, exercise=exercise)


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #


@app.post("/sessions", response_model=SessionSummary)
def post_session(summary: SessionSummary, conn: Conn) -> SessionSummary:
    """Store a finished session.

    Idempotent on ``session_id``: the PWA queues sessions while offline and may
    retry a send it is not sure landed, so replaying one must not duplicate it.
    """
    storage.save_session(conn, summary)
    return summary


@app.get("/sessions/{session_id}", response_model=SessionSummary)
def get_session(session_id: str, conn: Conn) -> SessionSummary:
    summary = storage.load_session(conn, session_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Unknown session")
    return summary


# --------------------------------------------------------------------------- #
# Coaching
# --------------------------------------------------------------------------- #


def _build_request(conn: sqlite3.Connection, summary: SessionSummary) -> CoachRequest:
    """Assemble the coach payload from stored state.

    The athlete profile is optional: a first session should still get a debrief
    rather than a 404 for not having filled in a form.
    """
    profile = storage.load_athlete(conn, summary.athlete_id) or AthleteProfile(
        athlete_id=summary.athlete_id, level="intermediaire"
    )
    return CoachRequest(
        athlete=profile,
        # The session just stored is itself the most recent history row; skip it
        # so the model does not read its own input back as a past trend.
        history=[
            point
            for point in storage.recent_history(conn, summary.athlete_id, limit=11)
            if point.date != summary.started_at
        ][:10],
        session=summary,
        catalogue=retrieve(summary),
    )


@app.post("/sessions/{session_id}/debrief", response_model=CoachResponse)
def post_session_debrief(
    session_id: str,
    conn: Conn,
    settings: Config,
    refresh: Annotated[bool, Query(description="Ignore the cached debrief.")] = False,
) -> CoachResponse:
    """Debrief a stored session, caching the result.

    Returns 503 when the coaching layer is unavailable. The client is expected to
    show the session summary without a debrief rather than treat that as fatal —
    the measurements are the product; the debrief is an addition to them.
    """
    summary = storage.load_session(conn, session_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Unknown session")

    if not refresh:
        cached = storage.load_debrief(conn, session_id)
        if cached is not None:
            return cached

    try:
        response = Coach(settings).debrief(_build_request(conn, summary))
    except CoachUnavailable as exc:
        logger.warning("coach unavailable for %s: %s", session_id, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    storage.save_debrief(conn, session_id, response, model=settings.session_model)
    return response


@app.post("/coach/debrief", response_model=CoachResponse)
def coach_debrief(request: CoachRequest, settings: Config) -> CoachResponse:
    """Stateless debrief: caller supplies the whole payload, nothing is stored.

    Kept alongside the session-scoped endpoint for tooling and evaluation runs
    that should not write to the athlete's history.
    """
    try:
        return Coach(settings).debrief(request)
    except CoachUnavailable as exc:
        logger.warning("coach unavailable: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


__all__ = ["app", "get_conn", "get_settings"]
