/**
 * Mirrors `backend/tests/test_geometry.py`. The two suites cover the same cases
 * on purpose: a divergence between the on-device and server implementations is
 * exactly what this pair of files exists to catch.
 */

import { describe, expect, it } from "vitest";

import { angleDeg, midpoint, norm, symmetryScore } from "./angles";

describe("angleDeg", () => {
  it("measures a right angle", () => {
    expect(
      angleDeg({ x: 0, y: 1, z: 0 }, { x: 0, y: 0, z: 0 }, { x: 1, y: 0, z: 0 }),
    ).toBeCloseTo(90);
  });

  it("measures a straight arm", () => {
    expect(
      angleDeg({ x: 0, y: 1, z: 0 }, { x: 0, y: 0, z: 0 }, { x: 0, y: -1, z: 0 }),
    ).toBeCloseTo(180);
  });

  it("measures a fully folded arm", () => {
    expect(
      angleDeg({ x: 0, y: 1, z: 0 }, { x: 0, y: 0, z: 0 }, { x: 0, y: 1, z: 0 }),
    ).toBeCloseTo(0);
  });

  it("uses the third dimension", () => {
    // A 2D projection would read this as 180 degrees. It is 90.
    expect(
      angleDeg({ x: 0, y: 1, z: 0 }, { x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: 1 }),
    ).toBeCloseTo(90);
  });

  it("reads a degenerate segment as extended, never as flexed", () => {
    const vertex = { x: 0, y: 0, z: 0 };
    expect(angleDeg(vertex, vertex, { x: 1, y: 0, z: 0 })).toBe(180);
  });

  it("does not return NaN on collinear float drift", () => {
    const result = angleDeg(
      { x: 1e-8, y: 0, z: 0 },
      { x: 0, y: 0, z: 0 },
      { x: 3e-8, y: 0, z: 0 },
    );
    expect(Number.isNaN(result)).toBe(false);
  });
});

describe("helpers", () => {
  it("computes a norm", () => {
    expect(norm({ x: 3, y: 4, z: 0 })).toBeCloseTo(5);
  });

  it("computes a midpoint", () => {
    expect(midpoint({ x: 0, y: 0, z: 0 }, { x: 2, y: 4, z: 6 })).toEqual({
      x: 1,
      y: 2,
      z: 3,
    });
  });
});

describe("symmetryScore", () => {
  it("scores identical sides at 1", () => {
    expect(symmetryScore(120, 120)).toBeCloseTo(1);
  });

  it("degrades continuously rather than crossing a threshold", () => {
    const small = symmetryScore(120, 125);
    const large = symmetryScore(120, 135);
    expect(small).toBeLessThan(1);
    expect(large).toBeLessThan(small);
    expect(large).toBeGreaterThan(0);
  });

  it("floors at zero beyond tolerance", () => {
    expect(symmetryScore(90, 180)).toBe(0);
  });

  it("is symmetric in its arguments", () => {
    expect(symmetryScore(100, 115)).toBeCloseTo(symmetryScore(115, 100));
  });

  it("rejects a non-positive tolerance", () => {
    expect(() => symmetryScore(100, 100, 0)).toThrow(RangeError);
  });
});
