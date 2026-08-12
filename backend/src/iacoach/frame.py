"""Turns pose landmarks into ``FrameSample``.

Mirror of ``web/src/analysis/frame.ts``. The TypeScript side runs it live on the
phone; this side runs it over recorded video, which is the only way to measure
counting accuracy against ground truth. Two implementations, one behaviour —
enforced by the landmark fixtures under ``fixtures/landmarks/``, replayed by
both languages in CI.

Every quantity comes from ``worldLandmarks`` — metric 3D, origin at the hip
midpoint. The normalised 2D set depends on framing and camera distance, so a
range of motion measured from it is not comparable between sessions, let alone
between an athlete and a dataset subject.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .contracts import ExerciseCalibration, FrameSample
from .geometry import Point3, angle_deg, midpoint, norm, subtract

__all__ = [
    "DRIVING_LANDMARKS",
    "LANDMARK",
    "CalibrationRecorder",
    "FrameSampler",
    "Landmark",
    "usable_fraction",
]

# MediaPipe BlazePose indices, kept in step with `web/src/pose/landmarker.ts`.
LANDMARK = {
    "LEFT_SHOULDER": 11,
    "RIGHT_SHOULDER": 12,
    "LEFT_ELBOW": 13,
    "RIGHT_ELBOW": 14,
    "LEFT_WRIST": 15,
    "RIGHT_WRIST": 16,
    "LEFT_HIP": 23,
    "RIGHT_HIP": 24,
    "LEFT_KNEE": 25,
    "RIGHT_KNEE": 26,
    "LEFT_ANKLE": 27,
    "RIGHT_ANKLE": 28,
}

VISIBILITY_THRESHOLD = 0.6
"""Below this a landmark is not trusted for any correction. A wrong correction
is worse than none, so the threshold is deliberately conservative."""

DRIVING_LANDMARKS = (
    LANDMARK["LEFT_SHOULDER"],
    LANDMARK["RIGHT_SHOULDER"],
    LANDMARK["LEFT_ELBOW"],
    LANDMARK["RIGHT_ELBOW"],
    LANDMARK["LEFT_WRIST"],
    LANDMARK["RIGHT_WRIST"],
)


@dataclass(frozen=True)
class Landmark:
    """One landmark. ``visibility`` is absent on some MediaPipe builds."""

    x: float
    y: float
    z: float
    visibility: float | None = None


def usable_fraction(landmarks: list[Landmark], indices: tuple[int, ...]) -> float:
    """Fraction of the given landmarks above the visibility threshold.

    A missing ``visibility`` counts as unusable rather than assumed visible: a
    model that stops reporting confidence should degrade to "suppress
    corrections", not to silently asserting them.
    """
    if not indices:
        return 0.0
    usable = 0
    for i in indices:
        if i < len(landmarks) and (landmarks[i].visibility or 0.0) >= VISIBILITY_THRESHOLD:
            usable += 1
    return usable / len(indices)


def _point(landmarks: list[Landmark], index: int) -> Point3 | None:
    if index >= len(landmarks):
        return None
    lm = landmarks[index]
    return Point3(lm.x, lm.y, lm.z)


def _joint_angle(landmarks: list[Landmark], a: int, vertex: int, c: int) -> float | None:
    pa, pv, pc = _point(landmarks, a), _point(landmarks, vertex), _point(landmarks, c)
    if pa is None or pv is None or pc is None:
        return None
    return angle_deg(pa, pv, pc)


class FrameSampler:
    """Stateful across frames, because hip speed is a derivative."""

    def __init__(self) -> None:
        self._previous_hip: Point3 | None = None
        self._previous_t_ms: float | None = None

    def reset(self) -> None:
        self._previous_hip = None
        self._previous_t_ms = None

    def sample(
        self,
        world: list[Landmark],
        normalized: list[Landmark],
        t_ms: float,
    ) -> FrameSample | None:
        """Returns ``None`` when the frame lacks what the counter needs.

        The caller must treat that as "no data" and never substitute a neutral
        pose: a fabricated frame moves the state machine.
        """
        left = _joint_angle(
            world, LANDMARK["LEFT_SHOULDER"], LANDMARK["LEFT_ELBOW"], LANDMARK["LEFT_WRIST"]
        )
        right = _joint_angle(
            world, LANDMARK["RIGHT_SHOULDER"], LANDMARK["RIGHT_ELBOW"], LANDMARK["RIGHT_WRIST"]
        )
        if left is None or right is None:
            return None

        left_hip = _point(world, LANDMARK["LEFT_HIP"])
        right_hip = _point(world, LANDMARK["RIGHT_HIP"])
        left_shoulder = _point(world, LANDMARK["LEFT_SHOULDER"])
        right_shoulder = _point(world, LANDMARK["RIGHT_SHOULDER"])
        if left_hip is None or right_hip is None:
            return None
        if left_shoulder is None or right_shoulder is None:
            return None

        hip = midpoint(left_hip, right_hip)
        shoulder = midpoint(left_shoulder, right_shoulder)

        # Trunk lean: angle between the hip->shoulder vector and vertical. In
        # world landmarks the y axis points down, so "up" is -y.
        trunk_deg = angle_deg(shoulder, hip, Point3(hip.x, hip.y - 1.0, hip.z))

        # Kipping signal: hip travel orthogonal to the movement axis. A pull-up
        # is vertical work, so lateral and fore-aft hip speed is parasitic.
        hip_speed = 0.0
        if self._previous_hip is not None and self._previous_t_ms is not None:
            dt_s = (t_ms - self._previous_t_ms) / 1000.0
            if dt_s > 0:
                delta = subtract(hip, self._previous_hip)
                hip_speed = norm(Point3(delta.x, 0.0, delta.z)) / dt_s
        self._previous_hip = hip
        self._previous_t_ms = t_ms

        return FrameSample(
            t_ms=t_ms,
            elbow_left_deg=left,
            elbow_right_deg=right,
            trunk_deg=trunk_deg,
            hip_speed=hip_speed,
            confidence=usable_fraction(normalized, DRIVING_LANDMARKS),
        )


class CalibrationRecorder:
    """Records the athlete's own range of motion.

    Thresholds are fractions of this range rather than fixed angles, so the
    counter behaves the same for a 1.60 m and a 1.95 m athlete. Frames below the
    visibility threshold are ignored: calibrating on unreliable landmarks bakes
    a wrong range into every score that follows.
    """

    MIN_SPAN_DEG = 40.0
    MIN_FRAMES = 30
    MIN_CONFIDENCE = 0.7

    def __init__(self) -> None:
        self._min_deg = float("inf")
        self._max_deg = float("-inf")
        self._accepted = 0
        self._seen = 0

    def add(self, sample: FrameSample) -> None:
        self._seen += 1
        if sample.confidence < self.MIN_CONFIDENCE:
            return
        angle = (sample.elbow_left_deg + sample.elbow_right_deg) / 2.0
        self._min_deg = min(self._min_deg, angle)
        self._max_deg = max(self._max_deg, angle)
        self._accepted += 1

    @property
    def progress(self) -> tuple[int, int, float]:
        """(accepted, seen, span_deg)."""
        span = 0.0 if self._accepted == 0 else self._max_deg - self._min_deg
        return self._accepted, self._seen, span

    def finish(
        self,
        exercise: str = "pull_up",
        captured_at: datetime | None = None,
    ) -> ExerciseCalibration | None:
        """The calibrated range, or ``None`` when the recording is not good
        enough to trust.

        Refusing is the correct outcome: a bad range corrupts every subsequent
        score silently, and a silent corruption is worse than a visible refusal.
        """
        if self._accepted < self.MIN_FRAMES:
            return None
        if self._max_deg - self._min_deg < self.MIN_SPAN_DEG:
            return None
        return ExerciseCalibration(
            exercise=exercise,
            joint="elbow",
            rom_min_deg=self._min_deg,
            rom_max_deg=self._max_deg,
            captured_at=captured_at or datetime.now(UTC),
            confidence=self._accepted / self._seen,
        )

    def reset(self) -> None:
        self._min_deg = float("inf")
        self._max_deg = float("-inf")
        self._accepted = 0
        self._seen = 0
