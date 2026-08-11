"""FastAPI application.

M0 scope: health, contract schema exposure, and the coaching endpoint. Persistence
(M3) and clip analysis (M4) attach here without changing the contracts.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from iacoach.coach.client import Coach, CoachUnavailable
from iacoach.config import load_settings
from iacoach.contracts import CoachRequest, CoachResponse

logger = logging.getLogger(__name__)

app = FastAPI(
    title="iaCoach API",
    version="0.1.0",
    summary="Coaching and persistence layer. Real-time analysis runs on-device.",
)

# The PWA runs on a separate dev origin; production serves both from one host.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)


@app.get("/health")
def health() -> dict[str, object]:
    settings = load_settings()
    return {
        "status": "ok",
        "coaching_enabled": settings.coaching_enabled,
        "session_model": settings.session_model,
    }


@app.post("/coach/debrief", response_model=CoachResponse)
def coach_debrief(request: CoachRequest) -> CoachResponse:
    """Produce a debrief for a finished session.

    Returns 503 when the coaching layer is unavailable — the client is expected to
    show the session summary without a debrief rather than treat this as fatal.
    """
    try:
        return Coach().debrief(request)
    except CoachUnavailable as exc:
        logger.warning("coach unavailable: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


__all__ = ["app"]
