import { describe, expect, it } from "vitest";

import type { ProgressPoint } from "../types/contracts";
import { polylinePoints, seriesFor } from "./progress";

function point(overrides: Partial<ProgressPoint> = {}): ProgressPoint {
  return {
    date: "2026-08-01T09:00:00Z",
    exercise: "pull_up",
    total_reps: 10,
    valid_reps: 8,
    mean_rom: 0.8,
    mean_form: 0.85,
    best_rom: 0.95,
    ...overrides,
  };
}

describe("polylinePoints", () => {
  it("returns nothing for an empty series", () => {
    expect(polylinePoints([])).toBe("");
  });

  it("draws a single point as a flat line across the chart", () => {
    // One session is a valid state; rendering it as a dot in the corner would
    // read as a broken chart.
    const points = polylinePoints([0.5]);
    const ys = points.split(" ").map((pair) => pair.split(",")[1]);
    expect(ys[0]).toBe(ys[1]);
  });

  it("pins the axis to [0, 1] rather than auto-scaling", () => {
    // Auto-scaling makes a 3% wobble look like a breakthrough — exactly the
    // misreading this project should not encourage.
    const flatHigh = polylinePoints([0.9, 0.92, 0.9]);
    const flatLow = polylinePoints([0.1, 0.12, 0.1]);
    expect(flatHigh).not.toBe(flatLow);

    const highYs = flatHigh.split(" ").map((p) => Number(p.split(",")[1]));
    const lowYs = flatLow.split(" ").map((p) => Number(p.split(",")[1]));
    // Higher value means smaller y in SVG coordinates.
    expect(Math.max(...highYs)).toBeLessThan(Math.min(...lowYs));
  });

  it("clamps out-of-range values instead of drawing outside the chart", () => {
    const points = polylinePoints([-0.5, 1.5]);
    const ys = points.split(" ").map((p) => Number(p.split(",")[1]));
    expect(Math.min(...ys)).toBeGreaterThanOrEqual(0);
    expect(Math.max(...ys)).toBeLessThanOrEqual(120);
  });

  it("spreads points evenly across the width", () => {
    const xs = polylinePoints([0.5, 0.5, 0.5]).split(" ").map((p) => Number(p.split(",")[0]));
    expect(xs[1]! - xs[0]!).toBeCloseTo(xs[2]! - xs[1]!, 6);
  });
});

describe("seriesFor", () => {
  it("plots the best rep and the session mean separately", () => {
    // They tell different stories: a set taken closer to failure drags the mean
    // down while the best rep holds, which is progress, not regression.
    const series = seriesFor([point({ best_rom: 0.95, mean_rom: 0.7 })]);
    expect(series).toHaveLength(2);
    expect(series[0]!.values).toEqual([0.95]);
    expect(series[1]!.values).toEqual([0.7]);
  });

  it("preserves the order of the points", () => {
    const series = seriesFor([point({ best_rom: 0.6 }), point({ best_rom: 0.9 })]);
    expect(series[0]!.values).toEqual([0.6, 0.9]);
  });
});
