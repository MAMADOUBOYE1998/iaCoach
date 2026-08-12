"""Counting accuracy: calibration from a clip, and the summary metrics.

Kept here rather than next to the video runner so it is covered by the normal
test suite. `vision/eval/evaluate.py` supplies the frames; this decides what a
result means.

Metric names follow the repetition-counting literature (MAE, OBO, MAPE) on
purpose: a number nobody can compare with a published one is a number that
settles no argument.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .contracts import Exercise, ExerciseCalibration, FrameSample

__all__ = ["ClipResult", "calibration_from", "summarise"]

MIN_SPAN_DEG = 40.0
"""Below this the clip never showed a real range, so any calibration from it is
noise. Same threshold as the on-device recorder, for the same reason."""

MIN_USABLE_FRAMES = 30
MIN_CONFIDENCE = 0.7


@dataclass
class ClipResult:
    path: str
    truth: int
    predicted: int | None
    frames: int
    detected_frames: int
    seconds: float
    note: str = ""
    flags: dict[str, int] = field(default_factory=dict)

    @property
    def error(self) -> int | None:
        return None if self.predicted is None else abs(self.predicted - self.truth)


def calibration_from(
    samples: list[FrameSample],
    exercise: Exercise = Exercise.PULL_UP,
    captured_at: datetime | None = None,
) -> ExerciseCalibration | None:
    """Range of motion estimated from the clip itself.

    A real departure from how the app works, where the athlete calibrates
    deliberately before a set — and one that **flatters the result**: the
    counter is handed the exact range it is about to be tested on. It is the
    only option on third-party footage, and it is why a dataset score is a
    lower bound on the work left, not a substitute for measuring a real session.

    Returns ``None`` rather than a guess when the clip does not support a
    calibration. "Could not calibrate" and "counted zero reps" are different
    failures needing different fixes, and collapsing them hides both.
    """
    usable = [s for s in samples if s.confidence >= MIN_CONFIDENCE]
    if len(usable) < MIN_USABLE_FRAMES:
        return None
    angles = [(s.elbow_left_deg + s.elbow_right_deg) / 2.0 for s in usable]
    low, high = min(angles), max(angles)
    if high - low < MIN_SPAN_DEG:
        return None
    return ExerciseCalibration(
        exercise=exercise,
        joint="elbow",
        rom_min_deg=low,
        rom_max_deg=high,
        captured_at=captured_at or datetime.now(UTC),
        confidence=len(usable) / len(samples),
    )


def summarise(results: list[ClipResult]) -> dict[str, Any]:
    """Aggregate over clips.

    Clips that could not be scored are counted and reported separately, never
    folded in as zeros: a harness that silently scores its own failures as
    perfect misses is a harness that reports progress it did not make.
    """
    scored = [r for r in results if r.error is not None]
    summary: dict[str, Any] = {
        "clips": len(results),
        "scored": len(scored),
        "skipped": len(results) - len(scored),
    }
    if not scored:
        return summary

    errors = [r.error or 0 for r in scored]
    with_truth = [r for r in scored if r.truth > 0]
    summary.update(
        {
            "mae": sum(errors) / len(errors),
            "obo": sum(1 for e in errors if e <= 1) / len(errors),
            "exact": sum(1 for e in errors if e == 0) / len(errors),
        }
    )
    if with_truth:
        summary["mape"] = sum((r.error or 0) / r.truth for r in with_truth) / len(with_truth)
    return summary
