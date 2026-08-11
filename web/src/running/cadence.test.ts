import { describe, expect, it } from "vitest";

import {
  cadenceSpm,
  detectSteps,
  MIN_STEP_INTERVAL_MS,
  regularity,
  removeGravity,
  runningIntervals,
  type MotionSample,
} from "./cadence";

const SAMPLE_HZ = 50;
const GRAVITY = 9.81;

/**
 * A synthetic gait signal: gravity plus a vertical oscillation at the given
 * cadence. `jitterMs` perturbs each step's timing to model an irregular gait.
 */
function gait(
  spm: number,
  seconds: number,
  { amplitude = 3, jitterMs = 0 } = {},
): MotionSample[] {
  const samples: MotionSample[] = [];
  const stepMs = 60_000 / spm;
  const stepTimes: number[] = [];
  for (let t = 0; t < seconds * 1000; t += stepMs) {
    // Deterministic alternating jitter — no RNG, so the test cannot flake.
    stepTimes.push(t + (stepTimes.length % 2 === 0 ? jitterMs : -jitterMs));
  }

  for (let i = 0; i < seconds * SAMPLE_HZ; i += 1) {
    const t = (i * 1000) / SAMPLE_HZ;
    // Each step contributes a bump peaking at its time and falling to zero
    // half a stride either side. The divisor is `stepMs`, not `stepMs / 2`:
    // with the latter the cosine reaches -1 at the window edge and `^8` turns
    // that back into a full-height lobe, planting a phantom foot strike between
    // every real one.
    let bump = 0;
    for (const stepTime of stepTimes) {
      const dt = t - stepTime;
      if (Math.abs(dt) < stepMs / 2) {
        bump += amplitude * Math.cos((Math.PI * dt) / stepMs) ** 8;
      }
    }
    samples.push({ t_ms: t, x: 0, y: GRAVITY + bump, z: 0 });
  }
  return samples;
}

describe("removeGravity", () => {
  it("centres a constant signal on zero", () => {
    const still: MotionSample[] = Array.from({ length: 100 }, (_, i) => ({
      t_ms: (i * 1000) / SAMPLE_HZ,
      x: 0,
      y: GRAVITY,
      z: 0,
    }));
    const signal = removeGravity(still);
    expect(Math.max(...signal.map(Math.abs))).toBeLessThan(1e-9);
  });

  it("preserves the oscillation", () => {
    const signal = removeGravity(gait(170, 4));
    expect(Math.max(...signal)).toBeGreaterThan(1);
  });
});

describe("detectSteps", () => {
  it("finds one step per foot strike", () => {
    const steps = detectSteps(gait(170, 6));
    // ~17 steps in 6 s at 170 spm; the trailing-mean warm-up can cost the first.
    expect(steps.length).toBeGreaterThanOrEqual(15);
    expect(steps.length).toBeLessThanOrEqual(18);
  });

  it("does not double-count a single strike", () => {
    // Without the refractory period, a noisy peak counts two or three times and
    // cadence roughly doubles.
    const steps = detectSteps(gait(170, 6));
    const intervals = runningIntervals(steps);
    expect(Math.min(...intervals)).toBeGreaterThanOrEqual(MIN_STEP_INTERVAL_MS);
  });

  it("finds nothing in a still signal", () => {
    const still: MotionSample[] = Array.from({ length: 200 }, (_, i) => ({
      t_ms: (i * 1000) / SAMPLE_HZ,
      x: 0,
      y: GRAVITY,
      z: 0,
    }));
    expect(detectSteps(still)).toEqual([]);
  });

  it("leaves the first step without an interval", () => {
    // Inventing one would put a phantom value into the regularity computation.
    const steps = detectSteps(gait(170, 4));
    expect(steps[0]!.interval_ms).toBeNull();
  });
});

describe("cadenceSpm", () => {
  it("recovers the cadence it was given", () => {
    expect(cadenceSpm(detectSteps(gait(170, 8)))!).toBeCloseTo(170, 0);
  });

  it("tracks a different cadence", () => {
    expect(cadenceSpm(detectSteps(gait(150, 8)))!).toBeCloseTo(150, 0);
  });

  it("returns null below three steps", () => {
    // Two intervals is not a cadence, it is two numbers.
    expect(cadenceSpm(detectSteps(gait(170, 1)))).toBeNull();
  });
});

describe("regularity", () => {
  it("scores a metronomic gait near 1", () => {
    expect(regularity(detectSteps(gait(170, 8)))!).toBeGreaterThan(0.9);
  });

  it("degrades continuously rather than crossing a threshold", () => {
    // "Irregular" is a degree, not a verdict — same rule as every other score.
    const steady = regularity(detectSteps(gait(170, 8, { jitterMs: 10 })))!;
    const erratic = regularity(detectSteps(gait(170, 8, { jitterMs: 60 })))!;
    expect(erratic).toBeLessThan(steady);
    expect(erratic).toBeGreaterThanOrEqual(0);
  });

  it("stays within [0, 1]", () => {
    const score = regularity(detectSteps(gait(170, 8, { jitterMs: 120 })));
    expect(score).not.toBeNull();
    expect(score!).toBeGreaterThanOrEqual(0);
    expect(score!).toBeLessThanOrEqual(1);
  });

  it("returns null when there are too few steps", () => {
    expect(regularity([])).toBeNull();
  });
});

describe("runningIntervals", () => {
  it("drops intervals outside the running range", () => {
    const intervals = runningIntervals([
      { t_ms: 0, interval_ms: null },
      { t_ms: 350, interval_ms: 350 },
      { t_ms: 5000, interval_ms: 4650 }, // a pause, not a stride
    ]);
    expect(intervals).toEqual([350]);
  });
});
