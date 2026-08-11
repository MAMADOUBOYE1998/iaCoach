"""Shared object factories for the test suite.

Kept out of the test modules so importing them never depends on the ``tests``
directory happening to be importable as a package — which varies with the
invocation directory.
"""

from __future__ import annotations

from iacoach.contracts import Exercise, FormScores, RepEvent, Tempo


def make_scores(**overrides: float) -> FormScores:
    base = {
        "rom": 0.9,
        "symmetry": 0.95,
        "kipping": 1.0,
        "tempo_control": 0.8,
        "alignment": 0.85,
    }
    base.update(overrides)
    return FormScores(**base)


def make_rep(index: int = 0, **overrides: object) -> RepEvent:
    base: dict[str, object] = {
        "rep_index": index,
        "exercise": Exercise.PULL_UP,
        "started_at_ms": 1000.0 * index,
        "duration_ms": 2400.0,
        "tempo": Tempo(eccentric_s=1.2, bottom_pause_s=0.2, concentric_s=0.9, top_pause_s=0.1),
        "scores": make_scores(),
        "peak_angle_deg": 168.0,
        "min_angle_deg": 42.0,
        "confidence": 0.93,
        "counted": True,
    }
    base.update(overrides)
    return RepEvent(**base)  # type: ignore[arg-type]
