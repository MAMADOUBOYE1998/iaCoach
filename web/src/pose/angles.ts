/**
 * 3D geometry, mirroring `backend/src/iacoach/geometry.py`.
 *
 * Both implementations must produce identical results on the shared fixtures —
 * that conformance check is what keeps the on-device and server-side analysis
 * from drifting apart. See docs/ARCHITECTURE.md §2.
 */

export interface Point3 {
  x: number;
  y: number;
  z: number;
}

export function subtract(a: Point3, b: Point3): Point3 {
  return { x: a.x - b.x, y: a.y - b.y, z: a.z - b.z };
}

export function norm(v: Point3): number {
  return Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
}

export function dot(a: Point3, b: Point3): number {
  return a.x * b.x + a.y * b.y + a.z * b.z;
}

export function midpoint(a: Point3, b: Point3): Point3 {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: (a.z + b.z) / 2 };
}

/**
 * Interior angle at `vertex` of the path a -> vertex -> c, in degrees.
 *
 * Returns 180 for a degenerate configuration (zero-length segment): that is the
 * "fully extended" reading and the safe default for collapsed landmarks, because
 * it never fabricates a flexed joint that the rep FSM would read as a completed
 * repetition.
 */
export function angleDeg(a: Point3, vertex: Point3, c: Point3): number {
  const v1 = subtract(a, vertex);
  const v2 = subtract(c, vertex);
  const n1 = norm(v1);
  const n2 = norm(v2);
  if (n1 === 0 || n2 === 0) return 180;
  // Clamp against float drift pushing |cos| just past 1, which would make
  // Math.acos return NaN and poison every downstream score.
  const cosine = Math.min(1, Math.max(-1, dot(v1, v2) / (n1 * n2)));
  return (Math.acos(cosine) * 180) / Math.PI;
}

/**
 * Continuous left/right agreement in [0, 1]. `toleranceDeg` is the difference at
 * which the score reaches 0; the default is deliberately generous because a
 * false asymmetry warning is worse than a missed one.
 */
export function symmetryScore(
  leftDeg: number,
  rightDeg: number,
  toleranceDeg = 20,
): number {
  if (toleranceDeg <= 0) throw new RangeError("toleranceDeg must be positive");
  return Math.max(0, 1 - Math.abs(leftDeg - rightDeg) / toleranceDeg);
}
