"""Exercise classification from a sliding window of pose landmarks.

Mirror of ``web/src/analysis/classify.ts``. Both implementations must agree on
the shared fixtures in ``fixtures/classify/`` — same discipline as the counter,
for the same reason: the phone classifies live, the server classifies recorded
video, and a silent divergence between them would make every stored session
incomparable with the next.

Why this exists, in one measurement: on 100 clips of *other* movements, the
repetition counter invented reps on 31 of them (`docs/BENCHMARKS.md`). It counts
elbow-flexion cycles, and rowing is one. Nothing upstream ever asked whether the
athlete was doing the exercise at all. This is that question.

Design, following the rest of the analysis stage:

- Everything comes from ``worldLandmarks`` — metric 3D, hip-origin. Normalised
  2D coordinates depend on framing, so a posture measured from them is not
  comparable between sessions.
- Every rule returns a **continuous** score in [0, 1], never a boolean. A body
  half-way between a dip and a push-up should read as ambiguous, not be forced
  into one of them.
- Every threshold is expressed in the athlete's **own** limb lengths or in
  degrees of joint range, never in absolute metres. A 1.60 m and a 1.95 m
  athlete have the same geometry, not the same measurements.
- ``UNKNOWN`` is a first-class answer. Refusing to name the movement is correct
  far more often than any single label, and it is the outcome the false-positive
  measurement demands.

**The thresholds below are geometric priors, not measurements.** They encode
what the postures are — hands overhead, trunk upright, which joint carries the
work — and they have been checked for refusal on 100 out-of-domain clips. They
have *not* been fitted to annotated positives, because we have none. Treat them
as `kip_tolerance_ms` is treated: a starting point to recalibrate on real
footage, flagged as such.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .contracts import Exercise
from .frame import LANDMARK, Landmark, usable_fraction
from .geometry import Point3, angle_deg, dot, midpoint, norm, subtract

__all__ = [
    "CLASSIFIER_LANDMARKS",
    "Classification",
    "ClassifierConfig",
    "ExerciseClassifier",
    "WindowFeatures",
    "classify_window",
    "frame_features",
]

CLASSIFIER_LANDMARKS = (
    LANDMARK["LEFT_SHOULDER"],
    LANDMARK["RIGHT_SHOULDER"],
    LANDMARK["LEFT_ELBOW"],
    LANDMARK["RIGHT_ELBOW"],
    LANDMARK["LEFT_WRIST"],
    LANDMARK["RIGHT_WRIST"],
    LANDMARK["LEFT_HIP"],
    LANDMARK["RIGHT_HIP"],
    LANDMARK["LEFT_KNEE"],
    LANDMARK["RIGHT_KNEE"],
)
"""Wider than `DRIVING_LANDMARKS`: telling a squat from a pull-up needs the legs.
Ankles are deliberately excluded — they are the first thing to leave frame when
an athlete films themselves on a bar, and requiring them would refuse the very
footage we most want to classify."""

UNCLASSIFIABLE: dict[Exercise, str] = {
    Exercise.CHIN_UP: (
        "indistinguishable from a pull-up here: the difference is grip "
        "supination, and forearm rotation is not recoverable from the landmarks "
        "this stage uses"
    ),
    Exercise.MUSCLE_UP: (
        "needs a model of the transition over the bar, and we have no annotated "
        "example of one. A muscle-up will read as PULL_UP during its pull phase"
    ),
}
"""Exercises in the contract that this classifier deliberately never emits.

Written down rather than silently absent: an athlete doing chin-ups deserves to
know the label is approximate, and a future reader deserves to know these were
omitted on purpose rather than forgotten."""


@dataclass(frozen=True)
class ClassifierConfig:
    """Geometric priors. See the module docstring on their status."""

    window_s: float = 2.0
    """Long enough to contain a full repetition at a slow tempo — the joint
    ranges below are meaningless over a fraction of a cycle."""

    min_frames: int = 20
    min_confidence: float = 0.7

    min_score: float = 0.45
    """Below this the window is ``UNKNOWN``. Set where refusing is cheap: a
    misrouted rule set corrects the wrong thing, which is worse than not
    correcting."""

    switch_margin: float = 0.15
    switch_windows: int = 3
    """A challenger must beat the incumbent by `switch_margin` on
    `switch_windows` consecutive windows. Same hysteresis reasoning as the rep
    state machine: a label that flickers mid-set is worse than a stale one."""


DEFAULT_CONFIG = ClassifierConfig()


@dataclass(frozen=True)
class FrameFeatures:
    """One frame, reduced to scale-free posture quantities."""

    t_ms: float
    wrist_above_shoulder: float
    """Height of the hands above the shoulders, in arm lengths. Positive means
    overhead. The single most discriminating quantity here: it separates the
    hanging family from everything else without depending on the camera."""
    trunk_verticality: float
    """1.0 when the trunk is aligned with gravity, 0.0 when horizontal."""
    elbow_deg: float
    knee_deg: float
    hip_deg: float
    confidence: float


@dataclass(frozen=True)
class WindowFeatures:
    """A window, reduced to what tells the exercises apart."""

    wrist_above_shoulder: float
    trunk_verticality: float
    elbow_rom_deg: float
    knee_rom_deg: float
    knee_deg: float
    hip_deg: float
    frames: int
    confidence: float


@dataclass(frozen=True)
class Classification:
    exercise: Exercise
    confidence: float
    scores: dict[Exercise, float] = field(default_factory=dict)
    reason: str = ""
    features: WindowFeatures | None = None


def _quantile(sorted_values: list[float], q: float) -> float:
    rank = (len(sorted_values) - 1) * q
    low, high = int(rank), min(int(rank) + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (rank - low)


def _robust_range(values: list[float]) -> float:
    """p90 − p10 rather than max − min.

    The counter learned this the hard way on real footage: on clip `082` the
    calibrated range was set by seven frames out of 791, and every threshold
    being a fraction of it, those seven starved the other 784."""
    if len(values) < 2:
        return 0.0
    ordered = sorted(values)
    return _quantile(ordered, 0.9) - _quantile(ordered, 0.1)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    return _quantile(sorted(values), 0.5)


def _point(landmarks: list[Landmark], index: int) -> Point3 | None:
    if index >= len(landmarks):
        return None
    lm = landmarks[index]
    return Point3(lm.x, lm.y, lm.z)


def _at_least(value: float, threshold: float, soft: float) -> float:
    """1.0 at or above `threshold`, fading to 0.0 `soft` below it."""
    if soft <= 0.0:
        return 1.0 if value >= threshold else 0.0
    return max(0.0, min(1.0, (value - threshold) / soft + 1.0))


def _at_most(value: float, threshold: float, soft: float) -> float:
    return _at_least(-value, -threshold, soft)


def _band(value: float, low: float, high: float, soft: float) -> float:
    return min(_at_least(value, low, soft), _at_most(value, high, soft))


def frame_features(
    world: list[Landmark], normalized: list[Landmark], t_ms: float
) -> FrameFeatures | None:
    """One frame of landmarks, reduced. ``None`` when the frame lacks a joint.

    Never substitutes a neutral value for a missing landmark: a fabricated
    posture would be classified as confidently as a real one.
    """
    required = (
        "LEFT_SHOULDER",
        "RIGHT_SHOULDER",
        "LEFT_ELBOW",
        "RIGHT_ELBOW",
        "LEFT_WRIST",
        "RIGHT_WRIST",
        "LEFT_HIP",
        "RIGHT_HIP",
        "LEFT_KNEE",
        "RIGHT_KNEE",
    )
    points: dict[str, Point3] = {}
    for name in required:
        point = _point(world, LANDMARK[name])
        if point is None:
            return None
        points[name] = point

    left_shoulder, right_shoulder = points["LEFT_SHOULDER"], points["RIGHT_SHOULDER"]
    left_elbow, right_elbow = points["LEFT_ELBOW"], points["RIGHT_ELBOW"]
    left_wrist, right_wrist = points["LEFT_WRIST"], points["RIGHT_WRIST"]
    left_hip, right_hip = points["LEFT_HIP"], points["RIGHT_HIP"]
    left_knee, right_knee = points["LEFT_KNEE"], points["RIGHT_KNEE"]

    shoulder = midpoint(left_shoulder, right_shoulder)
    hip = midpoint(left_hip, right_hip)
    wrist = midpoint(left_wrist, right_wrist)
    knee = midpoint(left_knee, right_knee)

    # Scale reference: the athlete's own arm. Every length below is divided by
    # it, so nothing in this module carries an absolute metre.
    arm = (
        norm(subtract(left_elbow, left_shoulder))
        + norm(subtract(left_wrist, left_elbow))
        + norm(subtract(right_elbow, right_shoulder))
        + norm(subtract(right_wrist, right_elbow))
    ) / 2.0
    if arm <= 0.0:
        return None

    # y points down in world landmarks, so "above" is a smaller y.
    wrist_above_shoulder = (shoulder.y - wrist.y) / arm

    trunk = subtract(shoulder, hip)
    trunk_length = norm(trunk)
    if trunk_length <= 0.0:
        return None
    trunk_verticality = abs(dot(trunk, Point3(0.0, 1.0, 0.0))) / trunk_length

    elbow = (
        angle_deg(left_shoulder, left_elbow, left_wrist)
        + angle_deg(right_shoulder, right_elbow, right_wrist)
    ) / 2.0
    # A missing ankle yields the degenerate 180 deg from `angle_deg` — "leg
    # extended", the reading that makes the classifier refuse a squat rather
    # than assert one. Ankles leave frame constantly; refusing the whole frame
    # over them would throw away most self-filmed footage.
    left_ankle = _point(world, LANDMARK["LEFT_ANKLE"])
    right_ankle = _point(world, LANDMARK["RIGHT_ANKLE"])
    knee_deg = (
        angle_deg(left_hip, left_knee, left_ankle if left_ankle else left_knee)
        + angle_deg(right_hip, right_knee, right_ankle if right_ankle else right_knee)
    ) / 2.0
    hip_deg = angle_deg(shoulder, hip, knee)

    return FrameFeatures(
        t_ms=t_ms,
        wrist_above_shoulder=wrist_above_shoulder,
        trunk_verticality=trunk_verticality,
        elbow_deg=elbow,
        knee_deg=knee_deg,
        hip_deg=hip_deg,
        confidence=usable_fraction(normalized, CLASSIFIER_LANDMARKS),
    )


def window_features(frames: list[FrameFeatures]) -> WindowFeatures:
    """Aggregate a window. Postures use the median, work uses a robust range."""
    return WindowFeatures(
        wrist_above_shoulder=_median([f.wrist_above_shoulder for f in frames]),
        trunk_verticality=_median([f.trunk_verticality for f in frames]),
        elbow_rom_deg=_robust_range([f.elbow_deg for f in frames]),
        knee_rom_deg=_robust_range([f.knee_deg for f in frames]),
        knee_deg=_median([f.knee_deg for f in frames]),
        hip_deg=_median([f.hip_deg for f in frames]),
        frames=len(frames),
        confidence=_median([f.confidence for f in frames]),
    )


def classify_window(
    features: WindowFeatures, config: ClassifierConfig = DEFAULT_CONFIG
) -> Classification:
    """Score every exercise, take the best, or refuse.

    Each rule is a conjunction combined with ``min`` rather than a product: the
    weakest piece of evidence should cap the confidence, and a product would
    penalise an exercise merely for being defined by more criteria than another.
    """
    f = features
    hangs = _at_least(f.wrist_above_shoulder, 0.5, 0.5)
    # A dip supports the whole body on hands at hip height, so the wrists sit
    # roughly an arm's length below the shoulders and the trunk is near-plumb.
    # Both bounds are tight on purpose: at -0.3 the hands are barely below
    # shoulder height, which describes a rowing stroke or a bent-over row just
    # as well, and those cycle the elbow through a full range without the
    # athlete being on bars at all. Rowing is the single largest source of
    # invented reps in the specificity run.
    on_bars = _at_most(f.wrist_above_shoulder, -0.6, 0.3)
    plumb = _at_least(f.trunk_verticality, 0.9, 0.12)
    # Looser than `plumb`, because a kipping pull-up leans and we want it
    # classified as a pull-up and then flagged, not refused. Hands overhead
    # already separates the hanging family from everything else.
    upright = _at_least(f.trunk_verticality, 0.85, 0.2)
    horizontal = _at_most(f.trunk_verticality, 0.35, 0.25)
    arms_work = _at_least(f.elbow_rom_deg, 40.0, 25.0)
    arms_still = _at_most(f.elbow_rom_deg, 25.0, 25.0)
    legs_still = _at_most(f.knee_rom_deg, 30.0, 30.0)
    legs_work = _at_least(f.knee_rom_deg, 50.0, 30.0)

    scores = {
        Exercise.PULL_UP: min(hangs, upright, arms_work, legs_still),
        Exercise.DIP: min(on_bars, plumb, arms_work, legs_still),
        Exercise.PUSH_UP: min(horizontal, arms_work, legs_still),
        Exercise.SQUAT: min(legs_work, arms_still, _at_least(f.trunk_verticality, 0.6, 0.3)),
        Exercise.L_SIT: min(
            _band(f.hip_deg, 70.0, 115.0, 30.0),
            _at_least(f.knee_deg, 150.0, 30.0),
            arms_still,
            _at_most(f.knee_rom_deg, 20.0, 20.0),
        ),
    }

    if f.frames < config.min_frames:
        return Classification(Exercise.UNKNOWN, 0.0, scores, "fenêtre trop courte", f)
    if f.confidence < config.min_confidence:
        # Same rule as everywhere else in the analysis stage: unreliable
        # landmarks produce no assertion, only the fact that they were unreliable.
        return Classification(Exercise.UNKNOWN, 0.0, scores, "suivi insuffisant", f)

    best = max(scores, key=lambda e: scores[e])
    if scores[best] < config.min_score:
        return Classification(Exercise.UNKNOWN, scores[best], scores, "aucun exercice reconnu", f)

    runner_up = max((s for e, s in scores.items() if e is not best), default=0.0)
    if scores[best] - runner_up < 0.10:
        # Two labels fit equally well. Naming one would route the athlete to a
        # rule set on a coin toss.
        return Classification(Exercise.UNKNOWN, scores[best], scores, "ambigu", f)

    return Classification(best, scores[best], scores, "", f)


class ExerciseClassifier:
    """Streaming classifier over a sliding window.

    Stateful for the same reason the counter is: the phone needs an answer while
    the set is happening, not after it.
    """

    def __init__(self, config: ClassifierConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self._frames: deque[FrameFeatures] = deque()
        self._current = Exercise.UNKNOWN
        self._challenger = Exercise.UNKNOWN
        self._challenger_windows = 0

    @property
    def current(self) -> Exercise:
        return self._current

    def reset(self) -> None:
        self._frames.clear()
        self._current = Exercise.UNKNOWN
        self._challenger = Exercise.UNKNOWN
        self._challenger_windows = 0

    def push(
        self, world: list[Landmark], normalized: list[Landmark], t_ms: float
    ) -> Classification | None:
        """Feed one frame. ``None`` until the window holds enough of them."""
        features = frame_features(world, normalized, t_ms)
        if features is None:
            return None
        self._frames.append(features)
        horizon = t_ms - self.config.window_s * 1000.0
        while self._frames and self._frames[0].t_ms < horizon:
            self._frames.popleft()
        if len(self._frames) < self.config.min_frames:
            return None

        proposal = classify_window(window_features(list(self._frames)), self.config)
        return self._settle(proposal)

    def _settle(self, proposal: Classification) -> Classification:
        """Hysteresis on the label itself.

        A single bad window must not rename the exercise mid-set — the label
        routes the rule set, so flipping it changes which corrections the
        athlete is given.
        """
        if proposal.exercise is self._current:
            self._challenger_windows = 0
            return proposal

        if proposal.exercise is not self._challenger:
            self._challenger = proposal.exercise
            self._challenger_windows = 1
        else:
            self._challenger_windows += 1

        incumbent = proposal.scores.get(self._current, 0.0)
        clears_margin = proposal.confidence - incumbent >= self.config.switch_margin
        if self._challenger_windows >= self.config.switch_windows and clears_margin:
            self._current = proposal.exercise
            self._challenger_windows = 0
            return proposal

        return Classification(
            self._current,
            incumbent,
            proposal.scores,
            f"maintenu ({proposal.exercise} en attente)",
            proposal.features,
        )
