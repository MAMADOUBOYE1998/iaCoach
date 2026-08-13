/**
 * Counter diagnostics — the TypeScript half.
 *
 * `backend/tests/test_evaluation.py::TestDiagnostics` is the other half and
 * builds the same signal with the same numbers. `attemptedReps` is not part of
 * the `RepEvent` stream, so the fixture conformance check cannot see it: if the
 * two implementations are to stay mirrors, this is where that is enforced.
 */

import { describe, expect, it } from "vitest";

import type { ExerciseCalibration } from "../types/contracts";
import { RepCounter, type FrameSample } from "./counting";

const CALIBRATION: ExerciseCalibration = {
  exercise: "pull_up",
  joint: "elbow",
  rom_min_deg: 45,
  rom_max_deg: 175,
  captured_at: "2026-01-01T00:00:00Z",
  confidence: 1,
};

/** `count` cycles from `highDeg` (extended) down to `lowDeg` and back. */
function cyclesBetween(
  count: number,
  highDeg: number,
  lowDeg: number,
  startMs = 0,
  fps = 30,
  secondsPerRep = 2,
): FrameSample[] {
  const mid = (highDeg + lowDeg) / 2;
  const half = (highDeg - lowDeg) / 2;
  const frames: FrameSample[] = [];
  for (let i = 0; i < Math.trunc(count * secondsPerRep * fps); i += 1) {
    const phase = (2 * Math.PI * i) / (secondsPerRep * fps);
    const angle = mid + half * Math.cos(phase);
    frames.push({
      t_ms: startMs + (i * 1000) / fps,
      elbow_left_deg: angle,
      elbow_right_deg: angle,
      trunk_deg: 3,
      hip_speed: 0.05,
      confidence: 0.95,
    });
  }
  return frames;
}

describe("RepCounter diagnostics", () => {
  it("sees shallow excursions that emit no event", () => {
    const deep = cyclesBetween(2, 175, 45);
    const shallow = cyclesBetween(6, 175, 130, deep[deep.length - 1]!.t_ms + 33.4);

    const counter = new RepCounter("pull_up", CALIBRATION);
    let events = 0;
    for (const sample of [...deep, ...shallow]) {
      if (counter.push(sample) !== null) events += 1;
    }

    // The state machine saw all eight; six were too shallow to become reps.
    // Same three numbers as the Python test, on the same signal.
    expect(counter.attemptedReps).toBe(8);
    expect(events).toBe(2);
    expect(counter.completedReps).toBe(2);
  });
});
