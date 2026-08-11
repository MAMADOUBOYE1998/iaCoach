"""Repetition counting and form scoring.

Mirrors ``web/src/analysis/counting.ts``. Both implementations must produce
byte-identical ``RepEvent`` streams on the shared fixtures in ``fixtures/`` —
that conformance check is what stops the on-device and server-side analyses from
drifting apart (see docs/ARCHITECTURE.md §2).

Design notes that are load-bearing, not stylistic:

- Every threshold is a fraction of the athlete's *own* calibrated range. There
  are no hard-coded joint angles: a 1.60 m and a 1.95 m athlete do not share a
  pull-up geometry.
- The state machine uses hysteresis on every boundary. A single threshold makes
  a rep flicker in and out at the turning point, which is where the signal is
  slowest and noisiest.
- A repetition that falls short is *recorded* with its scores and
  ``counted=False``. Data is never discarded for being imperfect — the coach
  needs to say "your last three were short", which requires having them.
- When frame confidence is low, corrective flags are suppressed. A wrong
  correction is worse than no correction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from iacoach.contracts import (
    Exercise,
    ExerciseCalibration,
    FormScores,
    FrameSample,
    RepEvent,
    RepPhase,
    Tempo,
)
from iacoach.filter import OneEuroFilter
from iacoach.geometry import symmetry_score


@dataclass(frozen=True)
class CountingConfig:
    """Thresholds, all in normalised-flexion units unless stated.

    ``flexion`` is 0.0 at full extension (dead hang, bottom of a pull-up) and
    1.0 at the athlete's calibrated maximum flexion (chin over bar). Identical
    values live in the TypeScript mirror; changing one without the other breaks
    conformance.
    """

    # --- state machine, with hysteresis on both boundaries ---
    bottom_enter: float = 0.12
    bottom_exit: float = 0.20
    top_enter: float = 0.75
    top_exit: float = 0.65

    # --- what qualifies as a repetition at all ---
    rep_floor: float = 0.50
    """Below this peak flexion the excursion is not a rep — it is a shrug, a
    reposition, or noise. No event is emitted."""

    count_floor: float = 0.75
    """At or above this peak, the rep counts. Between `rep_floor` and this, it is
    recorded with `counted=False` and flagged `rom_short`."""

    # --- scoring tolerances ---
    symmetry_tolerance_deg: float = 20.0
    kip_tolerance_ms: float = 0.80
    """Hip speed orthogonal to the movement axis, m/s, at which the kipping score
    reaches 0. Placeholder pending the M2 fixture study."""
    trunk_tolerance_deg: float = 30.0
    tempo_cv_tolerance: float = 1.50
    """Coefficient of variation of angular speed at which tempo control reaches 0."""

    # --- flag thresholds ---
    flag_symmetry: float = 0.70
    flag_kipping: float = 0.70
    flag_tempo: float = 0.60
    flag_alignment: float = 0.70
    min_coachable_confidence: float = 0.70


DEFAULT_CONFIG = CountingConfig()

DIFFERENTIATION_WINDOW_MS = 100.0
"""Window used to estimate angular speed. Wide enough that landmark jitter does
not dominate the derivative, narrow enough to still resolve a stall inside a
one-second concentric."""


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


@dataclass
class _Window:
    """Frames accumulated for the repetition currently in progress."""

    samples: list[FrameSample] = field(default_factory=list)
    flexion: list[float] = field(default_factory=list)

    def clear(self) -> None:
        self.samples.clear()
        self.flexion.clear()


class RepCounter:
    """Streaming counter: push frames, get a ``RepEvent`` when one completes.

    Streaming rather than batch because the on-device path has to emit feedback
    within the ~100 ms correction window; the fixture runner just drives the same
    object frame by frame.
    """

    def __init__(
        self,
        exercise: Exercise,
        calibration: ExerciseCalibration,
        *,
        config: CountingConfig = DEFAULT_CONFIG,
    ) -> None:
        self.exercise = exercise
        self.calibration = calibration
        self.config = config

        self._filter = OneEuroFilter()
        self._phase = RepPhase.IDLE
        self._rep_index = 0
        self._window = _Window()

        self._bottom_since_ms: float | None = None
        self._pending_bottom_pause_s = 0.0
        self._rep_start_ms: float | None = None
        self._top_enter_ms: float | None = None
        self._top_exit_ms: float | None = None
        self._peak_flexion = 0.0
        self._peak_ms: float | None = None

    @property
    def phase(self) -> RepPhase:
        return self._phase

    @property
    def completed_reps(self) -> int:
        return self._rep_index

    def flexion_of(self, sample: FrameSample, t_ms: float) -> float:
        """Filtered, normalised flexion for one frame: 0 = extended, 1 = flexed."""
        smoothed = self._filter.filter(sample.elbow_mean_deg, t_ms)
        return 1.0 - self.calibration.normalised(smoothed)

    def push(self, sample: FrameSample) -> RepEvent | None:
        """Feed one frame. Returns a ``RepEvent`` on the frame a rep completes."""
        cfg = self.config
        t = sample.t_ms
        f = self.flexion_of(sample, t)

        if self._phase is not RepPhase.IDLE and self._rep_start_ms is not None:
            self._window.samples.append(sample)
            self._window.flexion.append(f)
            if f > self._peak_flexion:
                self._peak_flexion = f
                self._peak_ms = t

        if self._phase is RepPhase.IDLE:
            # Wait for a confirmed dead hang before counting anything: starting
            # mid-movement would fabricate a partial first rep.
            if f <= cfg.bottom_enter:
                self._enter_bottom(t)
            return None

        if self._phase is RepPhase.BOTTOM:
            if f >= cfg.bottom_exit:
                self._start_rep(t, sample, f)
            return None

        if self._phase is RepPhase.CONCENTRIC:
            if f >= cfg.top_enter:
                self._phase = RepPhase.TOP
                self._top_enter_ms = t
            elif f <= cfg.bottom_enter:
                # Came back down without reaching the top: still a repetition
                # attempt if it went far enough, otherwise noise.
                return self._close_rep(t)
            return None

        if self._phase is RepPhase.TOP:
            if f <= cfg.top_exit:
                self._phase = RepPhase.ECCENTRIC
                self._top_exit_ms = t
            return None

        # ECCENTRIC
        if f <= cfg.bottom_enter:
            return self._close_rep(t)
        return None

    # -- state transitions -------------------------------------------------- #

    def _enter_bottom(self, t_ms: float) -> None:
        self._phase = RepPhase.BOTTOM
        self._bottom_since_ms = t_ms

    def _start_rep(self, t_ms: float, sample: FrameSample, flexion: float) -> None:
        self._phase = RepPhase.CONCENTRIC
        self._rep_start_ms = t_ms
        # The dead hang preceding this rep. Attributed to the rep that follows so
        # the event can be emitted the moment the rep ends, rather than deferred
        # until the athlete starts the next one.
        self._pending_bottom_pause_s = (
            0.0 if self._bottom_since_ms is None else (t_ms - self._bottom_since_ms) / 1000.0
        )
        self._top_enter_ms = None
        self._top_exit_ms = None
        self._peak_flexion = flexion
        self._peak_ms = t_ms
        self._window.clear()
        self._window.samples.append(sample)
        self._window.flexion.append(flexion)

    def _close_rep(self, t_ms: float) -> RepEvent | None:
        start = self._rep_start_ms
        peak = self._peak_flexion
        samples = list(self._window.samples)
        flexion = list(self._window.flexion)

        self._enter_bottom(t_ms)
        self._window.clear()
        self._rep_start_ms = None

        if start is None or peak < self.config.rep_floor or len(samples) < 2:
            return None

        event = self._build_event(start, t_ms, peak, samples, flexion)
        self._rep_index += 1
        return event

    # -- scoring ------------------------------------------------------------ #

    def _build_event(
        self,
        start_ms: float,
        end_ms: float,
        peak: float,
        samples: list[FrameSample],
        flexion: list[float],
    ) -> RepEvent:
        cfg = self.config
        peak_ms = self._peak_ms if self._peak_ms is not None else end_ms

        # A rep that never reached the top has no plateau: concentric and
        # eccentric meet at the peak.
        top_enter = self._top_enter_ms if self._top_enter_ms is not None else peak_ms
        top_exit = self._top_exit_ms if self._top_exit_ms is not None else peak_ms

        tempo = Tempo(
            eccentric_s=max(0.0, (end_ms - top_exit) / 1000.0),
            bottom_pause_s=max(0.0, self._pending_bottom_pause_s),
            concentric_s=max(0.0, (top_enter - start_ms) / 1000.0),
            top_pause_s=max(0.0, (top_exit - top_enter) / 1000.0),
        )

        scores = FormScores(
            rom=_clamp01(peak),
            symmetry=_mean(
                [
                    symmetry_score(s.elbow_left_deg, s.elbow_right_deg, cfg.symmetry_tolerance_deg)
                    for s in samples
                ]
            ),
            kipping=_clamp01(1.0 - max(s.hip_speed for s in samples) / cfg.kip_tolerance_ms),
            tempo_control=self._tempo_control(samples, flexion, top_enter),
            alignment=_mean(
                [_clamp01(1.0 - abs(s.trunk_deg) / cfg.trunk_tolerance_deg) for s in samples]
            ),
        )

        confidence = _clamp01(_mean([s.confidence for s in samples]))
        counted = peak >= cfg.count_floor
        angles = [s.elbow_mean_deg for s in samples]

        return RepEvent(
            rep_index=self._rep_index,
            exercise=self.exercise,
            started_at_ms=start_ms,
            duration_ms=max(1e-9, end_ms - start_ms),
            tempo=tempo,
            scores=scores,
            peak_angle_deg=max(angles),
            min_angle_deg=min(angles),
            confidence=confidence,
            counted=counted,
            flags=self._flags(scores, confidence, counted),
        )

    def _tempo_control(
        self, samples: list[FrameSample], flexion: list[float], top_enter_ms: float
    ) -> float:
        """Smoothness of the velocity profile: 1.0 = even pace, 0.0 = jerky.

        Measured as the coefficient of variation of angular speed, which is
        scale-free — a slow controlled rep and a fast controlled rep both score
        well, while a rep that stalls and snaps does not.

        Restricted to the concentric phase on purpose. A deliberate pause at the
        top or bottom is technique, not jerkiness; including those zero-speed
        frames would penalise a controlled rep for being controlled.

        Speed is differentiated over a fixed ``DIFFERENTIATION_WINDOW_MS``, not
        between adjacent frames. Frame-to-frame differencing amplifies landmark
        jitter enough to flag identical reps inconsistently, and it would make
        the score depend on frame rate — the same clip analysed at 30 fps
        on-device and 60 fps server-side has to yield the same number.
        """
        speeds: list[float] = []
        j = 0
        for i in range(1, len(samples)):
            if samples[i].t_ms > top_enter_ms:
                break
            while j + 1 < i and samples[i].t_ms - samples[j + 1].t_ms >= DIFFERENTIATION_WINDOW_MS:
                j += 1
            dt_s = (samples[i].t_ms - samples[j].t_ms) / 1000.0
            if dt_s <= 0.0:
                continue
            speeds.append(abs(flexion[i] - flexion[j]) / dt_s)

        if len(speeds) < 2:
            return 1.0
        mean_speed = _mean(speeds)
        if mean_speed <= 0.0:
            return 1.0
        variance = sum((s - mean_speed) ** 2 for s in speeds) / len(speeds)
        cv = math.sqrt(variance) / mean_speed
        return _clamp01(1.0 - cv / self.config.tempo_cv_tolerance)

    def _flags(self, scores: FormScores, confidence: float, counted: bool) -> list[str]:
        cfg = self.config
        if confidence < cfg.min_coachable_confidence:
            # Tracking was poor. Report that, and nothing else: every form score
            # derived from those frames is unreliable, and a confident-sounding
            # correction built on bad data is the failure mode to avoid.
            return ["low_confidence"]

        flags: list[str] = []
        if not counted:
            flags.append("rom_short")
        if scores.kipping < cfg.flag_kipping:
            flags.append("kipping")
        if scores.symmetry < cfg.flag_symmetry:
            flags.append("asymmetry")
        if scores.tempo_control < cfg.flag_tempo:
            flags.append("jerky")
        if scores.alignment < cfg.flag_alignment:
            flags.append("trunk_swing")
        return flags


def analyse_sequence(
    exercise: Exercise,
    calibration: ExerciseCalibration,
    samples: list[FrameSample],
    *,
    config: CountingConfig = DEFAULT_CONFIG,
) -> list[RepEvent]:
    """Batch helper over the same streaming counter. Used by the fixture runner."""
    counter = RepCounter(exercise, calibration, config=config)
    events: list[RepEvent] = []
    for sample in samples:
        event = counter.push(sample)
        if event is not None:
            events.append(event)
    return events


__all__ = [
    "DEFAULT_CONFIG",
    "DIFFERENTIATION_WINDOW_MS",
    "CountingConfig",
    "RepCounter",
    "analyse_sequence",
]
