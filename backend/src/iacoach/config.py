"""Runtime configuration. Secrets come from the environment, never from source."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_DIR = REPO_ROOT / "prompts"
SCHEMA_DIR = REPO_ROOT / "contracts" / "schema"

# Debrief of a single session: cheap and frequent.
MODEL_SESSION_DEBRIEF = "claude-sonnet-5"
# Weekly planning: rarer, reasons over more history, worth the stronger model.
MODEL_WEEKLY_PLANNING = "claude-opus-4-8"


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str | None
    database_url: str
    session_model: str
    planning_model: str

    @property
    def coaching_enabled(self) -> bool:
        """Without a key the app still counts reps and scores form; only the LLM
        debrief is unavailable. Offline-first is a requirement, not a fallback."""
        return bool(self.anthropic_api_key)

    @property
    def database_path(self) -> Path:
        """Filesystem path behind ``database_url``.

        Only the ``sqlite:///`` form is understood. A Postgres URL is a valid
        future setting but not a valid *path*, so it fails here rather than
        silently creating a SQLite file named after the connection string.
        """
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError(f"Only sqlite:/// URLs are supported in v1, got {self.database_url!r}")
        return Path(self.database_url[len(prefix) :])


def load_settings() -> Settings:
    return Settings(
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        database_url=os.environ.get("IACOACH_DB_URL", f"sqlite:///{REPO_ROOT / 'iacoach.db'}"),
        session_model=os.environ.get("IACOACH_SESSION_MODEL", MODEL_SESSION_DEBRIEF),
        planning_model=os.environ.get("IACOACH_PLANNING_MODEL", MODEL_WEEKLY_PLANNING),
    )


__all__ = [
    "MODEL_SESSION_DEBRIEF",
    "MODEL_WEEKLY_PLANNING",
    "PROMPTS_DIR",
    "REPO_ROOT",
    "SCHEMA_DIR",
    "Settings",
    "load_settings",
]
