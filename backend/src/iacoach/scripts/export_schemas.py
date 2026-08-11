"""Export the Pydantic contracts to JSON Schema.

The Pydantic models are the source of truth; ``contracts/schema/*.json`` is
generated. The TypeScript mirror in ``web/src/types/contracts.ts`` is checked
against these files, so a contract change that is not propagated fails CI rather
than drifting silently.

Usage:  python -m iacoach.scripts.export_schemas [--check]
"""

from __future__ import annotations

import argparse
import json
import sys

from pydantic import BaseModel

from iacoach.config import SCHEMA_DIR
from iacoach.contracts import (
    AthleteProfile,
    CoachRequest,
    CoachResponse,
    RepEvent,
    SessionSummary,
)

EXPORTED: tuple[type[BaseModel], ...] = (
    RepEvent,
    SessionSummary,
    AthleteProfile,
    CoachRequest,
    CoachResponse,
)


def _render(model: type[BaseModel]) -> str:
    schema = model.model_json_schema()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the committed schemas are stale. Used in CI.",
    )
    args = parser.parse_args(argv)

    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []

    for model in EXPORTED:
        path = SCHEMA_DIR / f"{model.__name__}.json"
        rendered = _render(model)
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != rendered:
                stale.append(path.name)
        else:
            path.write_text(rendered, encoding="utf-8")

    if args.check and stale:
        print(
            "Stale contract schemas: "
            + ", ".join(stale)
            + "\nRun: python -m iacoach.scripts.export_schemas",
            file=sys.stderr,
        )
        return 1

    if not args.check:
        print(f"Wrote {len(EXPORTED)} schemas to {SCHEMA_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
