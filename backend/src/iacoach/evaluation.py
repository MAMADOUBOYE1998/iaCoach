"""Counting accuracy: calibration from a clip, and the summary metrics.

Kept here rather than next to the video runner so it is covered by the normal
test suite. `vision/eval/evaluate.py` supplies the frames; this decides what a
result means.

Metric names follow the repetition-counting literature (MAE, OBO, MAPE) on
purpose: a number nobody can compare with a published one is a number that
settles no argument.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .contracts import Exercise, ExerciseCalibration, FrameSample
from .counting import RepCounter

__all__ = [
    "ClipResult",
    "calibration_from",
    "classification_verdict",
    "periodicity_count",
    "score_samples",
    "segment_stability",
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
    periodicity_reps: float | None = None
    """Count from the rhythm alone, ignoring depth. A baseline: the gap to
    `predicted` is what amplitude gating costs on this clip."""
    periodicity_r: float | None = None
    """Autocorrelation at the chosen period. Low means the baseline is guessing."""
    exercise: str = ""
    """The exercise the manifest claims. Needed to ask whether the classifier
    would have let this clip reach the counter at all."""
    in_domain: bool = False
    """This clip really *is* the exercise, inside a set that mostly is not.

    Defaults to False so a manifest that says nothing is treated as fully
    out-of-domain — the reading that cannot flatter the gate."""
    classified_as: str = ""
    """What the classifier called it, over the whole clip."""
    classified_share: float = 0.0
    unknown_share: float = 0.0
    """Fraction of windows the classifier refused to name. High is *good* on
    footage that is not the exercise."""
    segment_cv: dict[str, float] = field(default_factory=dict)
    """Length variability of the rigid arm segments. The one tracking-quality
    signal here that does not come from MediaPipe's own optimism."""

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


SEGMENTS = ("upper_arm_left", "forearm_left", "upper_arm_right", "forearm_right")


def segment_stability(lengths: list[dict[str, float]]) -> dict[str, float]:
    """Coefficient of variation of each rigid segment's measured length.

    Our per-frame ``confidence`` is the fraction of driving landmarks whose
    MediaPipe ``visibility`` clears 0.6 — that is a claim the landmark was
    *found*, not that it was found in the right place. Nothing in the pipeline
    currently measures the second thing, and invariant "no landmark below the
    confidence threshold is used for a correction" rests on it.

    A forearm is rigid. Its metric length in ``worldLandmarks`` should barely
    move. When it swings by 20 % frame to frame, the 3D estimate is unreliable
    however confident ``visibility`` sounds — and unlike visibility, this is
    checkable without ground truth.

    Returns the CV per segment, plus ``worst``. Empty input yields ``{}`` rather
    than a zero that would read as perfect stability.
    """
    if not lengths:
        return {}
    out: dict[str, float] = {}
    for name in SEGMENTS:
        values = [row[name] for row in lengths if row.get(name, 0.0) > 0.0]
        if len(values) < 2:
            continue
        mean = sum(values) / len(values)
        if mean <= 0.0:
            continue
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        out[name] = round(math.sqrt(variance) / mean, 4)
    if out:
        out["worst"] = max(out.values())
    return out


MIN_PERIODICITY_R = 0.20
MIN_PERIODICITY_FRAMES = 60


def periodicity_count(samples: list[FrameSample]) -> tuple[float, float] | None:
    """Repetitions counted from the *rhythm* of the elbow angle, ignoring depth.

    A **baseline, not a counter.** `RepCounter` gates on amplitude: every
    threshold is a fraction of a calibrated range, so a movement whose range is
    misjudged is invisible however plainly periodic it is. This measures what is
    left on the table by asking only "how often does the signal repeat".

    Two things it cannot do, and they are why it does not replace anything:

    - **No specificity whatsoever.** Skipping rope, rowing and stirring a pot
      are periodic. `RepCounter` refuses 61 of the 100 out-of-domain QUVA clips;
      this would count all 100. It is only safe downstream of an exercise
      classifier.
    - **No per-rep quality.** A count is not a `RepEvent`: no ROM, no symmetry,
      no tempo. The coaching contract needs all three.

    Returns ``(count, correlation)``, or ``None`` when nothing repeats clearly
    enough — refusing rather than inventing a number from noise.

    Assumes near-uniform frame spacing (lags are in frames). True of video and
    of a steady capture; a clip with large gaps would need resampling first.
    """
    if len(samples) < MIN_PERIODICITY_FRAMES:
        return None
    values = [s.elbow_mean_deg for s in samples]
    n = len(values)
    mean = sum(values) / n
    centred = [v - mean for v in values]
    energy = sum(v * v for v in centred)
    if energy <= 0.0:
        return None

    limit = n // 3
    correlation = {
        lag: sum(centred[i] * centred[i + lag] for i in range(n - lag)) / energy
        for lag in range(3, limit + 2)
    }
    # Local maxima only. Autocorrelation is near 1.0 at short lags for any smooth
    # signal, so a plain maximum returns the smoothness scale, not the period.
    peaks = [
        lag
        for lag in range(4, limit)
        if correlation[lag] > correlation[lag - 1] and correlation[lag] > correlation[lag + 1]
    ]
    if not peaks:
        return None
    best = max(peaks, key=lambda lag: correlation[lag])

    # Octave correction, standard in pitch detection: a periodic signal peaks at
    # its period *and* at every multiple, and the multiple can win. When a
    # sub-multiple holds up nearly as well, it is the fundamental.
    for divisor in (2, 3):
        target = best / divisor
        nearby = [lag for lag in peaks if abs(lag - target) <= max(2.0, target * 0.15)]
        if nearby:
            candidate = max(nearby, key=lambda lag: correlation[lag])
            if correlation[candidate] >= 0.8 * correlation[best]:
                best = candidate
                break

    if correlation[best] < MIN_PERIODICITY_R:
        return None
    return (n - 1) / best, round(correlation[best], 3)


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
    labels: list[Exercise] | None = None,
    in_domain: bool = False,
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
        exercise=exercise.value,
        in_domain=in_domain,
    )
    if labels:
        verdict = classification_verdict(labels)
        result.classified_as = verdict["label"]
        result.classified_share = round(verdict["share"], 3)
        result.unknown_share = round(verdict["unknown_share"], 3)

    usable = [s for s in samples if s.confidence >= MIN_CONFIDENCE]
    result.usable_frames = len(usable)
    if (periodicity := periodicity_count(samples)) is not None:
        result.periodicity_reps, result.periodicity_r = round(periodicity[0], 1), periodicity[1]
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


def classification_verdict(labels: list[Exercise]) -> dict[str, Any]:
    """Per-window labels reduced to one verdict for the clip.

    The dominant *named* label wins, but ``unknown_share`` is reported beside
    it and not folded in: a clip the classifier refused 90 % of the time and
    hesitantly called a dip once is not a dip, and a summary that only kept the
    label would say it was.
    """
    if not labels:
        return {"label": "", "share": 0.0, "unknown_share": 0.0}
    counts = Counter(labels)
    unknown_share = counts[Exercise.UNKNOWN] / len(labels)
    named = [(e, c) for e, c in counts.items() if e is not Exercise.UNKNOWN]
    if not named:
        return {"label": Exercise.UNKNOWN.value, "share": 0.0, "unknown_share": 1.0}
    label, count = max(named, key=lambda pair: pair[1])
    return {
        "label": label.value,
        "share": count / len(labels),
        "unknown_share": unknown_share,
    }


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

    Clips flagged `in_domain` are held apart. A general-purpose repetition
    dataset can contain the exercise: QUVA has three pull-up clips among its
    hundred. Counting a correct label on those as a "false positive after the
    gate" would punish the classifier for being right, and — worse — would let a
    gate that refuses *everything*, positives included, post the best score on
    this page. `gate_recall` is reported next to the specificity for that
    reason: specificity alone is trivially winnable and means nothing on its own.
    """
    in_domain = [r for r in results if r.in_domain]
    out_domain = [r for r in results if not r.in_domain]
    scored = [r for r in out_domain if r.predicted is not None]
    false_positives = [r for r in scored if (r.predicted or 0) > 0]
    counts = sorted((r.predicted or 0) for r in false_positives)

    # What the classifier would change if it gated the counter: a clip it does
    # not call the manifest's exercise never reaches `RepCounter`, so its
    # invented reps never exist. Clips with no classification at all are counted
    # as surviving — an unmeasured gate must not be credited with a save.
    classified = [r for r in out_domain if r.classified_as]
    survivors = [r for r in false_positives if r.classified_as == r.exercise]
    recognised = [r for r in in_domain if r.classified_as == r.exercise]
    return {
        "classified_clips": len(classified),
        "false_positive_clips_after_gate": len(survivors) if classified else None,
        "reps_invented_after_gate": sum(r.predicted or 0 for r in survivors)
        if classified
        else None,
        "in_domain_clips": len(in_domain),
        "gate_recall": (len(recognised) / len(in_domain)) if in_domain else None,
        "clips": len(out_domain),
        "refused_to_calibrate": len(out_domain) - len(scored),
        "scored": len(scored),
        "false_positive_clips": len(false_positives),
        "false_positive_rate": (len(false_positives) / len(out_domain)) if out_domain else 0.0,
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
