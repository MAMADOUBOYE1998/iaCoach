"""Choosing which detected body is the athlete, and keeping that choice.

MediaPipe returns poses, not identities. With ``num_poses=1`` it returns
whichever one it liked on this frame, and nothing downstream can tell that a
different person answered. Clip `084` is the measured case: 1175 frames of a
coherent, confidently tracked, upright body whose hands never once rise above
its shoulders, on footage annotated as pull-ups. Every biomechanical threshold
in this project was innocent; the wrong body was being measured.

**Tracking runs on the normalised landmarks, never on ``worldLandmarks``.**
World landmarks are re-centred on each subject's own hip midpoint, so every
person in the frame sits at the origin — two people are positionally identical
there, and the one signal that separates them is gone. The normalised set keeps
image position, which is exactly what continuity needs. It is the one place in
this codebase where the 2D set is the correct input, and it is correct precisely
because it is framing-dependent.

What this fixes and what it does not
------------------------------------
Continuity fixes **switching**: once a body is chosen, the tracker follows it
rather than re-deciding every frame. It does **not** fix **acquisition**. If the
first frame hands us the wrong person, continuity locks that error in and makes
it steadier. That is a real cost, not a hypothetical one, and it is why
`SubjectTracker` counts what it saw: a clip where only one pose was ever
detected cannot have been a selection mistake, and one where three were
competing can. Those need opposite fixes, and the count is the only way to tell.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .frame import LANDMARK, Landmark

__all__ = [
    "DEFAULT_TRACKER_CONFIG",
    "Subject",
    "SubjectTracker",
    "TrackerConfig",
]

_HIPS = (LANDMARK["LEFT_HIP"], LANDMARK["RIGHT_HIP"])
_SHOULDERS = (LANDMARK["LEFT_SHOULDER"], LANDMARK["RIGHT_SHOULDER"])


@dataclass(frozen=True)
class TrackerConfig:
    max_centre_jump: float = 0.25
    """How far the torso centre may move between frames, in image widths.

    A real athlete filmed at 30 fps moves a few percent of the frame per frame,
    even kipping. A quarter of the frame is a different body, or the same body
    after a cut. Loose enough to survive a dropped frame or two, tight enough
    that a bystander walking past cannot claim the track."""

    max_scale_ratio: float = 1.6
    """Torso size ratio between the candidate and the track.

    Distance from the camera changes apparent size slowly; identity changes it
    at once. This catches the case the centre distance misses — a second person
    standing close behind the athlete, whose torso centre is nearby but who is
    visibly smaller."""

    reacquire_after: int = 15
    """Frames with no acceptable candidate before the track is abandoned.

    Half a second at 30 fps. Below this the athlete is assumed occluded and the
    frames are simply dropped, which is right: a missing measurement is honest
    and a substituted one is not. Above it the athlete has genuinely left, and
    holding the old position would reject them forever when they return."""

    min_visibility: float = 0.5
    """A landmark below this is not used to place or size a candidate."""


DEFAULT_TRACKER_CONFIG = TrackerConfig()


@dataclass(frozen=True)
class Subject:
    """Which pose was chosen on one frame, and why."""

    index: int
    reason: str
    candidates: int


@dataclass
class SubjectTracker:
    """Follows one body across frames. Feed it every frame's detected poses.

    `select` returns the chosen pose's index, or ``None`` when no candidate is
    close enough to the track. ``None`` means *drop this frame* — never
    substitute a neighbouring pose, for the same reason a missing landmark is
    never replaced by a neutral one.
    """

    config: TrackerConfig = DEFAULT_TRACKER_CONFIG

    acquisitions: int = 0
    """Times a track was started from nothing. More than one means the athlete
    was lost and re-acquired, and the second body may not be the first."""
    dropped_frames: int = 0
    """Frames where a pose existed but none of them matched the track."""
    max_candidates: int = 0
    """Most poses seen at once. **1 means selection was never in play** — a
    wrong subject on such a clip is a detection failure, not a choice."""
    frames_with_choice: int = 0
    """Frames where more than one pose was offered. The clips where a selection
    policy can have changed anything at all."""

    _centre: tuple[float, float] | None = field(default=None, repr=False)
    _scale: float | None = field(default=None, repr=False)
    _missing: int = field(default=0, repr=False)

    def select(self, poses: list[list[Landmark]]) -> Subject | None:
        if not poses:
            return None
        self.max_candidates = max(self.max_candidates, len(poses))
        if len(poses) > 1:
            self.frames_with_choice += 1

        measured = [self._measure(pose) for pose in poses]
        usable = [(i, m) for i, m in enumerate(measured) if m is not None]
        if not usable:
            return None

        if self._centre is None:
            return self._acquire(usable, len(poses))

        best = self._nearest(usable)
        if best is None:
            self._missing += 1
            self.dropped_frames += 1
            if self._missing >= self.config.reacquire_after:
                self._centre, self._scale, self._missing = None, None, 0
            return None

        index, (centre, scale) = best
        self._centre, self._scale, self._missing = centre, scale, 0
        return Subject(index, "suivi", len(poses))

    def _acquire(
        self, usable: list[tuple[int, tuple[tuple[float, float], float]]], candidates: int
    ) -> Subject:
        """Largest torso wins.

        A guess, and named as one. The athlete filming themselves is normally
        the nearest body and therefore the biggest, but a bystander walking
        between the camera and the bar is bigger still. Nothing available on a
        single frame does better without assuming the exercise, and assuming the
        exercise is what the classifier gate is for — deciding it here would
        make the gate's own measurement circular.
        """
        index, (centre, scale) = max(usable, key=lambda item: item[1][1])
        self._centre, self._scale, self._missing = centre, scale, 0
        self.acquisitions += 1
        return Subject(index, "acquisition", candidates)

    def _nearest(
        self, usable: list[tuple[int, tuple[tuple[float, float], float]]]
    ) -> tuple[int, tuple[tuple[float, float], float]] | None:
        assert self._centre is not None and self._scale is not None
        accepted: list[tuple[float, int, tuple[tuple[float, float], float]]] = []
        for index, (centre, scale) in usable:
            distance = math.dist(centre, self._centre)
            if distance > self.config.max_centre_jump:
                continue
            ratio = max(scale, self._scale) / max(min(scale, self._scale), 1e-9)
            if ratio > self.config.max_scale_ratio:
                continue
            accepted.append((distance, index, (centre, scale)))
        if not accepted:
            return None
        _, index, measurement = min(accepted, key=lambda item: item[0])
        return index, measurement

    def _measure(self, pose: list[Landmark]) -> tuple[tuple[float, float], float] | None:
        """Torso centre and torso size, from the normalised landmarks.

        Torso rather than a full bounding box: limbs swing, the trunk does not,
        so a box would report a size that changes with the movement being
        measured. On a pull-up that is the worst possible choice — the arms move
        most exactly when we most need the size to hold still.
        """
        points: list[Landmark] = []
        for index in (*_HIPS, *_SHOULDERS):
            landmark = pose[index] if index < len(pose) else None
            if landmark is None:
                return None
            if landmark.visibility is not None and landmark.visibility < self.config.min_visibility:
                return None
            points.append(landmark)
        hips, shoulders = points[:2], points[2:]

        hip = ((hips[0].x + hips[1].x) / 2.0, (hips[0].y + hips[1].y) / 2.0)
        shoulder = (
            (shoulders[0].x + shoulders[1].x) / 2.0,
            (shoulders[0].y + shoulders[1].y) / 2.0,
        )
        scale = math.dist(hip, shoulder)
        if scale <= 0.0:
            return None
        centre = ((hip[0] + shoulder[0]) / 2.0, (hip[1] + shoulder[1]) / 2.0)
        return centre, scale
