import { describe, expect, it } from "vitest";

import { LANDMARK, type Landmark } from "../pose/landmarker";
import { CalibrationRecorder, FrameSampler } from "./frame";
import type { FrameSample } from "./counting";

/** A minimal 33-slot landmark array with only the joints we exercise filled in. */
function pose(overrides: Record<number, [number, number, number]>): Landmark[] {
  const out: Landmark[] = Array.from({ length: 33 }, () => ({
    x: 0,
    y: 0,
    z: 0,
    visibility: 1,
  }));
  for (const [index, [x, y, z]] of Object.entries(overrides)) {
    out[Number(index)] = { x, y, z, visibility: 1 };
  }
  return out;
}

/** Arms straight down, torso upright. */
function hangingPose(): Landmark[] {
  return pose({
    [LANDMARK.LEFT_SHOULDER]: [-0.2, -0.5, 0],
    [LANDMARK.RIGHT_SHOULDER]: [0.2, -0.5, 0],
    [LANDMARK.LEFT_ELBOW]: [-0.2, -0.8, 0],
    [LANDMARK.RIGHT_ELBOW]: [0.2, -0.8, 0],
    [LANDMARK.LEFT_WRIST]: [-0.2, -1.1, 0],
    [LANDMARK.RIGHT_WRIST]: [0.2, -1.1, 0],
    [LANDMARK.LEFT_HIP]: [-0.15, 0, 0],
    [LANDMARK.RIGHT_HIP]: [0.15, 0, 0],
  });
}

describe("FrameSampler", () => {
  it("reads a straight arm as ~180 degrees", () => {
    const sample = new FrameSampler().sample(hangingPose(), hangingPose(), 0);
    expect(sample).not.toBeNull();
    expect(sample!.elbow_left_deg).toBeCloseTo(180, 3);
    expect(sample!.elbow_right_deg).toBeCloseTo(180, 3);
  });

  it("reads an upright torso as ~0 degrees of lean", () => {
    const sample = new FrameSampler().sample(hangingPose(), hangingPose(), 0);
    expect(sample!.trunk_deg).toBeCloseTo(0, 3);
  });

  it("returns null when a driving landmark is missing", () => {
    // The caller must treat this as "no data", never substitute a neutral pose:
    // a fabricated frame would move the state machine.
    const broken = hangingPose();
    broken.length = LANDMARK.LEFT_WRIST;
    expect(new FrameSampler().sample(broken, broken, 0)).toBeNull();
  });

  it("reports zero hip speed on the first frame", () => {
    // There is no previous position to difference against; inventing a speed
    // would show as phantom kipping on the first rep.
    const sample = new FrameSampler().sample(hangingPose(), hangingPose(), 0);
    expect(sample!.hip_speed).toBe(0);
  });

  it("measures lateral hip travel as kipping, and ignores vertical travel", () => {
    const sampler = new FrameSampler();
    sampler.sample(hangingPose(), hangingPose(), 0);

    const swung = hangingPose();
    swung[LANDMARK.LEFT_HIP] = { x: -0.05, y: 0, z: 0, visibility: 1 };
    swung[LANDMARK.RIGHT_HIP] = { x: 0.25, y: 0, z: 0, visibility: 1 };
    const lateral = sampler.sample(swung, swung, 100)!;
    expect(lateral.hip_speed).toBeCloseTo(1.0, 3); // 0.1 m over 0.1 s

    // A pull-up is vertical work: raising the hips is the exercise, not a fault.
    const sampler2 = new FrameSampler();
    sampler2.sample(hangingPose(), hangingPose(), 0);
    const lifted = hangingPose();
    lifted[LANDMARK.LEFT_HIP] = { x: -0.15, y: -0.3, z: 0, visibility: 1 };
    lifted[LANDMARK.RIGHT_HIP] = { x: 0.15, y: -0.3, z: 0, visibility: 1 };
    expect(sampler2.sample(lifted, lifted, 100)!.hip_speed).toBeCloseTo(0, 6);
  });
});

function calibrationSample(angle: number, confidence = 1): FrameSample {
  return {
    t_ms: 0,
    elbow_left_deg: angle,
    elbow_right_deg: angle,
    trunk_deg: 0,
    hip_speed: 0,
    confidence,
  };
}

describe("CalibrationRecorder", () => {
  it("captures the observed range", () => {
    const recorder = new CalibrationRecorder();
    for (let i = 0; i < 40; i += 1) recorder.add(calibrationSample(40 + i * 3));
    const result = recorder.finish();
    expect(result).not.toBeNull();
    expect(result!.rom_min_deg).toBeCloseTo(40, 6);
    expect(result!.rom_max_deg).toBeCloseTo(157, 6);
  });

  it("refuses to calibrate on too few frames", () => {
    const recorder = new CalibrationRecorder();
    for (let i = 0; i < 10; i += 1) recorder.add(calibrationSample(40 + i * 10));
    expect(recorder.finish()).toBeNull();
  });

  it("refuses to calibrate on a range too narrow to be real", () => {
    const recorder = new CalibrationRecorder();
    for (let i = 0; i < 60; i += 1) recorder.add(calibrationSample(150 + (i % 5)));
    expect(recorder.finish()).toBeNull();
  });

  it("ignores low-confidence frames", () => {
    // Calibrating on unreliable landmarks would bake a wrong range into every
    // subsequent session, so those frames must not widen the range.
    const recorder = new CalibrationRecorder();
    for (let i = 0; i < 40; i += 1) recorder.add(calibrationSample(90 + (i % 2), 1));
    recorder.add(calibrationSample(10, 0.2));
    recorder.add(calibrationSample(300, 0.2));
    expect(recorder.finish()).toBeNull(); // span stays 1 degree, not 290
  });

  it("reports the accepted fraction as confidence", () => {
    const recorder = new CalibrationRecorder();
    for (let i = 0; i < 40; i += 1) recorder.add(calibrationSample(40 + i * 3));
    for (let i = 0; i < 10; i += 1) recorder.add(calibrationSample(90, 0.1));
    expect(recorder.finish()!.confidence).toBeCloseTo(40 / 50, 6);
  });
});
