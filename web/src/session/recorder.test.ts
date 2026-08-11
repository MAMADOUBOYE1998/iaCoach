import { describe, expect, it } from "vitest";

import type { Exercise, RepEvent } from "../types/contracts";
import { SessionRecorder, type RecorderClock } from "./recorder";

function rep(index: number, overrides: Partial<RepEvent> = {}): RepEvent {
  return {
    rep_index: index,
    exercise: "pull_up",
    started_at_ms: index * 3000,
    duration_ms: 2400,
    tempo: { eccentric_s: 1.2, bottom_pause_s: 0.2, concentric_s: 0.9, top_pause_s: 0.1 },
    scores: { rom: 0.9, symmetry: 0.95, kipping: 1, tempo_control: 0.8, alignment: 0.85 },
    peak_angle_deg: 168,
    min_angle_deg: 42,
    confidence: 0.93,
    counted: true,
    flags: [],
    ...overrides,
  };
}

class FakeClock implements RecorderClock {
  elapsedMs = 0;

  now(): Date {
    return new Date("2026-08-01T09:00:00Z");
  }

  elapsed(): number {
    return this.elapsedMs;
  }
}

describe("SessionRecorder", () => {
  it("starts empty", () => {
    const recorder = new SessionRecorder("s1", "a1", new FakeClock());
    expect(recorder.isEmpty).toBe(true);
    expect(recorder.finish().sets).toEqual([]);
  });

  it("opens a set implicitly on the first rep", () => {
    const recorder = new SessionRecorder("s1", "a1", new FakeClock());
    recorder.addRep(rep(0));
    expect(recorder.setCount).toBe(1);
  });

  it("counts total and valid reps separately", () => {
    const recorder = new SessionRecorder("s1", "a1", new FakeClock());
    recorder.addRep(rep(0));
    recorder.addRep(rep(1, { counted: false, flags: ["rom_short"] }));
    recorder.addRep(rep(2));
    expect(recorder.totalReps).toBe(3);
    expect(recorder.validReps).toBe(2);
  });

  it("keeps explicit set boundaries", () => {
    // Sets are opened explicitly rather than inferred from a rest gap: guessing
    // from timing merges two quick sets and splits one long one.
    const recorder = new SessionRecorder("s1", "a1", new FakeClock());
    recorder.addRep(rep(0));
    recorder.startSet("pull_up");
    recorder.addRep(rep(0));
    recorder.addRep(rep(1));
    expect(recorder.finish().sets.map((s) => s.reps.length)).toEqual([1, 2]);
  });

  it("opens a new set when the exercise changes mid-set", () => {
    const recorder = new SessionRecorder("s1", "a1", new FakeClock());
    recorder.addRep(rep(0));
    recorder.addRep(rep(0, { exercise: "dip" as Exercise }));
    const sets = recorder.finish().sets;
    expect(sets.map((s) => s.exercise)).toEqual(["pull_up", "dip"]);
  });

  it("drops sets that were opened and abandoned", () => {
    const recorder = new SessionRecorder("s1", "a1", new FakeClock());
    recorder.addRep(rep(0));
    recorder.startSet("pull_up"); // athlete steps away without pulling
    expect(recorder.finish().sets).toHaveLength(1);
  });

  it("measures duration from the monotonic clock", () => {
    const clock = new FakeClock();
    const recorder = new SessionRecorder("s1", "a1", clock);
    clock.elapsedMs = 754_000;
    expect(recorder.finish().duration_s).toBeCloseTo(754, 6);
  });

  it("never reports a negative duration", () => {
    // performance.now() should be monotonic, but a summary with a negative
    // duration would be rejected by the API contract.
    const clock = new FakeClock();
    clock.elapsedMs = 5000;
    const recorder = new SessionRecorder("s1", "a1", clock);
    clock.elapsedMs = 0;
    expect(recorder.finish().duration_s).toBe(0);
  });

  it("omits optional fields rather than sending nulls", () => {
    const summary = new SessionRecorder("s1", "a1", new FakeClock()).finish();
    expect("perceived_effort" in summary).toBe(false);
    expect("notes" in summary).toBe(false);
  });

  it("carries the self-reported effort and notes when given", () => {
    const summary = new SessionRecorder("s1", "a1", new FakeClock()).finish({
      perceivedEffort: 8,
      notes: "épaule droite sensible",
    });
    expect(summary.perceived_effort).toBe(8);
    expect(summary.notes).toBe("épaule droite sensible");
  });

  it("stamps the session and athlete ids", () => {
    const summary = new SessionRecorder("sess-42", "athlete-1", new FakeClock()).finish();
    expect(summary.session_id).toBe("sess-42");
    expect(summary.athlete_id).toBe("athlete-1");
    expect(summary.started_at).toBe("2026-08-01T09:00:00.000Z");
  });
});
