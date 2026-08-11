/** One-Euro filter tests. Mirrors `backend/tests/test_filter.py`. */

import { describe, expect, it } from "vitest";

import { OneEuroFilter } from "./filter";

const STEP_MS = 1000 / 30;

function feed(values: number[]): number[] {
  const filter = new OneEuroFilter();
  return values.map((v, i) => filter.filter(v, i * STEP_MS));
}

describe("OneEuroFilter", () => {
  it("passes the first sample through", () => {
    // No warm-up ramp: the first reading is the best estimate available.
    expect(new OneEuroFilter().filter(123.5, 0)).toBeCloseTo(123.5, 10);
  });

  it("converges on a constant signal", () => {
    const out = feed(Array.from({ length: 40 }, () => 90));
    expect(out.at(-1)).toBeCloseTo(90, 6);
  });

  it("attenuates jitter at rest", () => {
    const noisy = Array.from({ length: 60 }, (_, i) => 100 + (i % 2 ? 2 : -2));
    const tail = feed(noisy).slice(30);
    // The input swings 4 degrees peak to peak.
    expect(Math.max(...tail) - Math.min(...tail)).toBeLessThan(2);
  });

  it("tracks a fast ramp with little lag", () => {
    // The reason this filter exists: a moving average would lag here, and the
    // angular-velocity peak it flattens is the fatigue signal.
    const ramp = Array.from({ length: 30 }, (_, i) => 40 + 4 * i);
    const lag = ramp.at(-1)! - feed(ramp).at(-1)!;
    expect(lag).toBeLessThan(8);
  });

  it("lags less than a five-frame moving average", () => {
    const ramp = Array.from({ length: 30 }, (_, i) => 40 + 4 * i);
    const oneEuro = feed(ramp).at(-1)!;
    const movingAverage = ramp.slice(-5).reduce((a, b) => a + b, 0) / 5;
    const last = ramp.at(-1)!;
    expect(Math.abs(last - oneEuro)).toBeLessThan(Math.abs(last - movingAverage));
  });

  it("holds the estimate on a repeated timestamp", () => {
    // Duplicate timestamps happen when a frame is re-submitted; dividing by a
    // zero dt would produce an infinity that poisons every later sample.
    const filter = new OneEuroFilter();
    filter.filter(100, 0);
    const first = filter.filter(120, 33);
    expect(filter.filter(999, 33)).toBeCloseTo(first, 10);
  });

  it("clears state on reset", () => {
    const filter = new OneEuroFilter();
    for (let i = 0; i < 20; i += 1) filter.filter(100, i * 33);
    filter.reset();
    expect(filter.filter(10, 0)).toBeCloseTo(10, 10);
  });
});
