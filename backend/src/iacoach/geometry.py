"""3D geometry helpers.

Every biomechanical computation in iaCoach runs on ``worldLandmarks`` — metric
3D coordinates in metres, origin at the hip midpoint — never on the normalised
2D landmarks. 2D angles depend on framing and camera distance, so a ROM measured
in 2D is not comparable between sessions.

The TypeScript mirror lives in ``web/src/pose/angles.ts`` and must produce
identical results on the shared fixtures.
"""

from __future__ import annotations

import math
from typing import NamedTuple


class Point3(NamedTuple):
    """A world landmark, in metres."""

    x: float
    y: float
    z: float


def subtract(a: Point3, b: Point3) -> Point3:
    return Point3(a.x - b.x, a.y - b.y, a.z - b.z)


def norm(v: Point3) -> float:
    return math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)


def dot(a: Point3, b: Point3) -> float:
    return a.x * b.x + a.y * b.y + a.z * b.z


def angle_deg(a: Point3, vertex: Point3, c: Point3) -> float:
    """Interior angle at ``vertex`` of the path a -> vertex -> c, in degrees.

    Returns ``180.0`` for a degenerate configuration (a segment of zero length),
    which is the "fully extended" reading and the safe default for a joint whose
    landmarks collapsed: it never fabricates a flexed position that would be read
    as a completed repetition.
    """
    v1 = subtract(a, vertex)
    v2 = subtract(c, vertex)
    n1, n2 = norm(v1), norm(v2)
    if n1 == 0.0 or n2 == 0.0:
        return 180.0
    cosine = dot(v1, v2) / (n1 * n2)
    # Guard against float drift pushing |cos| just past 1.0.
    cosine = max(-1.0, min(1.0, cosine))
    return math.degrees(math.acos(cosine))


def midpoint(a: Point3, b: Point3) -> Point3:
    return Point3((a.x + b.x) / 2.0, (a.y + b.y) / 2.0, (a.z + b.z) / 2.0)


def symmetry_score(left_deg: float, right_deg: float, tolerance_deg: float = 20.0) -> float:
    """Continuous left/right agreement in [0, 1].

    ``tolerance_deg`` is the difference at which the score reaches 0. 20 degrees
    is a placeholder pending the M2 fixture study — it is deliberately generous,
    because a false asymmetry warning is worse than a missed one.
    """
    if tolerance_deg <= 0:
        raise ValueError("tolerance_deg must be positive")
    delta = abs(left_deg - right_deg)
    return max(0.0, 1.0 - delta / tolerance_deg)


__all__ = [
    "Point3",
    "angle_deg",
    "dot",
    "midpoint",
    "norm",
    "subtract",
    "symmetry_score",
]
