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
from .counting import RepCounter

__all__ = [
    "ClipResult",
    "calibration_from",
    "score_samples",
    "summarise",
    "summarise_out_of_domain",
]

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

    # Diagnostics. Without these, a wrong count has two indistinguishable
    # causes: the state machine never saw the repetition, or it saw it and
    # declined to count it. Those need opposite fixes, and reporting only the
    # final number hides which one you have.
    attempted: int = 0
    """Excursions the state machine saw at all, however shallow."""
    events: int = 0
    """Of those, the ones deep enough to emit an event (peak >= `rep_floor`)."""
    calibration_deg: tuple[float, float] | None = None
    """The range the counter was given. An outlier frame inflates it, and every
    threshold is a fraction of it, so a wrong range starves every rep at once."""
    usable_frames: int = 0
    """Frames above the confidence floor — the only ones calibration may use."""

    # `attempted` / `events` / `predicted` nest, and the step that collapses says
    # which stage is at fault. An earlier version of this reported the per-rep
    # `peak_angle_deg` instead, which is `max(angle)` — the most *extended* point
    # of the rep. Since a rep closes on the return to extension, that number is
    # tautological and answered nothing.
    angle_percentiles: dict[str, float] = field(default_factory=dict)
    """Raw mean elbow angle, usable frames only. Says *which* tail carries the
    range: a brief real flexion and a spurious hyperextension both widen the
    min/max span, and they need opposite fixes."""
    flexion_percentiles: dict[str, float] = field(default_factory=dict)
    """The filtered, normalised signal the state machine actually consumes,
    against which `bottom_exit` (0.20), `rep_floor` (0.50) and `count_floor`
    (0.75) are read directly."""
    rep_rom: list[float] = field(default_factory=list)
    """Peak flexion per emitted rep, in the same units as those thresholds."""
    rep_min_angle_deg: list[float] = field(default_factory=list)
    """Deepest angle actually reached per emitted rep."""

    @property
    def error(self) -> int | None:
        return None if self.predicted is None else abs(self.predicted - self.truth)


def _quantile(sorted_values: list[float], q: float) -> float:
    rank = (len(sorted_values) - 1) * q
    low, high = int(rank), min(int(rank) + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (rank - low)


PERCENTILES = (1, 2, 5, 25, 50, 75, 95, 98, 99)


def _percentiles(values: list[float], digits: int = 1) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)
    return {f"p{p}": round(_quantile(ordered, p / 100.0), digits) for p in PERCENTILES}


def calibration_from(
    samples: list[FrameSample],
    exercise: Exercise = Exercise.PULL_UP,
    captured_at: datetime | None = None,
    trim_percent: float = 0.0,
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
    angles = sorted((s.elbow_left_deg + s.elbow_right_deg) / 2.0 for s in usable)

    # min/max is one bad frame away from a wrong range, and every threshold is a
    # fraction of that range — so a single spurious extreme starves every rep at
    # once, and the symptom is "counts nothing", which looks like a broken state
    # machine rather than a broken calibration. `trim_percent` discards that tail.
    if trim_percent > 0.0:
        q = trim_percent / 100.0
        low, high = _quantile(angles, q), _quantile(angles, 1.0 - q)
    else:
        low, high = angles[0], angles[-1]

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


def score_samples(
    samples: list[FrameSample],
    *,
    path: str,
    truth: int,
    exercise: Exercise = Exercise.PULL_UP,
    frames: int = 0,
    seconds: float = 0.0,
    trim_percent: float = 0.0,
) -> ClipResult:
    """Calibrate from a clip's samples, then count.

    Lives here rather than beside the video reader so it is covered by the test
    suite. It was in the reader once, and the one line that constructs the
    counter went untested because no synthetic clip ever calibrated far enough
    to reach it — the wrong argument list only surfaced on the first real video.
    """
    result = ClipResult(
        path=path,
        truth=truth,
        predicted=None,
        frames=frames,
        detected_frames=len(samples),
        seconds=seconds,
    )

    usable = [s for s in samples if s.confidence >= MIN_CONFIDENCE]
    result.usable_frames = len(usable)
    result.angle_percentiles = _percentiles([s.elbow_mean_deg for s in usable])

    calibration = calibration_from(samples, exercise, trim_percent=trim_percent)
    if calibration is None:
        # Reported, not silently counted as zero: "could not calibrate" and
        # "counted no reps" are different failures needing different fixes.
        result.note = "calibration impossible (amplitude ou suivi insuffisants)"
        return result

    # A throwaway counter, driven through the production `flexion_of`, gives the
    # exact signal the real one will see without reimplementing the filter and
    # the normalisation here — a copy of those would drift and then lie.
    probe = RepCounter(exercise, calibration)
    result.flexion_percentiles = _percentiles(
        [probe.flexion_of(sample, sample.t_ms) for sample in samples], digits=3
    )

    counter = RepCounter(exercise, calibration)
    events = [event for sample in samples if (event := counter.push(sample)) is not None]
    result.predicted = sum(1 for event in events if event.counted)
    result.events = len(events)
    result.attempted = counter.attempted_reps
    result.calibration_deg = (
        round(calibration.rom_min_deg, 1),
        round(calibration.rom_max_deg, 1),
    )
    result.rep_rom = [round(event.scores.rom, 3) for event in events]
    result.rep_min_angle_deg = [round(event.min_angle_deg, 1) for event in events]
    for event in events:
        for flag in event.flags:
            result.flags[flag] = result.flags.get(flag, 0) + 1
    return result


def summarise_out_of_domain(results: list[ClipResult]) -> dict[str, Any]:
    """Specificity: how often the counter invents reps on footage that is not
    the exercise at all.

    Accuracy answers "does it count correctly when the athlete is doing
    pull-ups". This answers the question underneath it — "does it stay silent
    when they are not" — and that one decides whether a session log can be
    trusted at all. A counter that ticks while someone skips rope will also tick
    while they hang, adjust their grip, or walk past the camera.

    Refusing to calibrate counts as a **correct** outcome here, not a failure:
    on footage that is not the exercise, refusing is the right answer.

    `truth` in the manifest is ignored — it describes a different movement.
    """
    scored = [r for r in results if r.predicted is not None]
    false_positives = [r for r in scored if (r.predicted or 0) > 0]
    counts = sorted((r.predicted or 0) for r in false_positives)
    return {
        "clips": len(results),
        "refused_to_calibrate": len(results) - len(scored),
        "scored": len(scored),
        "false_positive_clips": len(false_positives),
        "false_positive_rate": (len(false_positives) / len(results)) if results else 0.0,
        "reps_invented_total": sum(counts),
        "worst_clip_reps": counts[-1] if counts else 0,
    }


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
