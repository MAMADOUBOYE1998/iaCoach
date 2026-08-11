/**
 * Turns a pose frame into a `FrameSample`.
 *
 * This is the seam between pose estimation and analysis: everything downstream
 * consumes derived scalars, never landmarks. That is what lets the same counting
 * logic run on-device from MediaPipe and server-side from a heavier model.
 *
 * Every quantity here comes from `worldLandmarks` — metric 3D, origin at the hip
 * midpoint. The normalised 2D set depends on framing and camera distance, so a
 * range of motion measured from it is not comparable between sessions.
 */

import { angleDeg, midpoint, norm, subtract, type Point3 } from "../pose/angles";
import { LANDMARK, usableFraction, type Landmark } from "../pose/landmarker";
import type { FrameSample } from "./counting";

/** Landmarks the pull-up counter depends on. Drives the confidence figure. */
export const DRIVING_LANDMARKS = [
  LANDMARK.LEFT_SHOULDER,
  LANDMARK.RIGHT_SHOULDER,
  LANDMARK.LEFT_ELBOW,
  LANDMARK.RIGHT_ELBOW,
  LANDMARK.LEFT_WRIST,
  LANDMARK.RIGHT_WRIST,
];

function point(lm: Landmark | undefined): Point3 | null {
  return lm ? { x: lm.x, y: lm.y, z: lm.z } : null;
}

function jointAngle(
  world: Landmark[],
  a: number,
  vertex: number,
  c: number,
): number | null {
  const pa = point(world[a]);
  const pv = point(world[vertex]);
  const pc = point(world[c]);
  if (!pa || !pv || !pc) return null;
  return angleDeg(pa, pv, pc);
}

export class FrameSampler {
  private previousHip: Point3 | null = null;
  private previousTMs: number | null = null;

  reset(): void {
    this.previousHip = null;
    this.previousTMs = null;
  }

  /**
   * Returns `null` when the frame lacks the landmarks the counter needs. The
   * caller must treat that as "no data", never substitute a neutral pose — a
   * fabricated frame would move the state machine.
   */
  sample(world: Landmark[], normalizedLandmarks: Landmark[], tMs: number): FrameSample | null {
    const left = jointAngle(
      world,
      LANDMARK.LEFT_SHOULDER,
      LANDMARK.LEFT_ELBOW,
      LANDMARK.LEFT_WRIST,
    );
    const right = jointAngle(
      world,
      LANDMARK.RIGHT_SHOULDER,
      LANDMARK.RIGHT_ELBOW,
      LANDMARK.RIGHT_WRIST,
    );
    if (left === null || right === null) return null;

    const leftHip = point(world[LANDMARK.LEFT_HIP]);
    const rightHip = point(world[LANDMARK.RIGHT_HIP]);
    const leftShoulder = point(world[LANDMARK.LEFT_SHOULDER]);
    const rightShoulder = point(world[LANDMARK.RIGHT_SHOULDER]);
    if (!leftHip || !rightHip || !leftShoulder || !rightShoulder) return null;

    const hip = midpoint(leftHip, rightHip);
    const shoulder = midpoint(leftShoulder, rightShoulder);

    // Trunk lean: angle between the hip->shoulder vector and vertical. In world
    // landmarks the y axis points down, so "up" is -y.
    const trunkDeg = angleDeg(shoulder, hip, { x: hip.x, y: hip.y - 1, z: hip.z });

    // Kipping signal: hip travel orthogonal to the movement axis. A pull-up is
    // vertical work, so lateral and fore-aft hip speed is parasitic momentum.
    let hipSpeed = 0;
    if (this.previousHip && this.previousTMs !== null) {
      const dtSeconds = (tMs - this.previousTMs) / 1000;
      if (dtSeconds > 0) {
        const delta = subtract(hip, this.previousHip);
        hipSpeed = norm({ x: delta.x, y: 0, z: delta.z }) / dtSeconds;
      }
    }
    this.previousHip = hip;
    this.previousTMs = tMs;

    return {
      t_ms: tMs,
      elbow_left_deg: left,
      elbow_right_deg: right,
      trunk_deg: trunkDeg,
      hip_speed: hipSpeed,
      confidence: usableFraction(normalizedLandmarks, DRIVING_LANDMARKS),
    };
  }
}

/**
 * Records the athlete's own range of motion.
 *
 * Thresholds are expressed as a fraction of this range rather than as fixed
 * angles, so the counter behaves the same for a 1.60 m and a 1.95 m athlete.
 * Frames below the visibility threshold are ignored: calibrating on unreliable
 * landmarks would bake a wrong range into every subsequent session.
 */
export class CalibrationRecorder {
  private minDeg = Number.POSITIVE_INFINITY;
  private maxDeg = Number.NEGATIVE_INFINITY;
  private accepted = 0;
  private seen = 0;

  /** Enough spread to be a real range rather than a twitch. */
  static readonly MIN_SPAN_DEG = 40;
  static readonly MIN_FRAMES = 30;
  static readonly MIN_CONFIDENCE = 0.7;

  add(sample: FrameSample): void {
    this.seen += 1;
    if (sample.confidence < CalibrationRecorder.MIN_CONFIDENCE) return;
    const angle = (sample.elbow_left_deg + sample.elbow_right_deg) / 2;
    this.minDeg = Math.min(this.minDeg, angle);
    this.maxDeg = Math.max(this.maxDeg, angle);
    this.accepted += 1;
  }

  get progress(): { accepted: number; seen: number; spanDeg: number } {
    const span = this.accepted === 0 ? 0 : this.maxDeg - this.minDeg;
    return { accepted: this.accepted, seen: this.seen, spanDeg: span };
  }

  /**
   * Returns the calibrated range, or `null` if the recording is not good enough
   * to trust. Refusing to calibrate is the correct outcome here: a bad range
   * silently corrupts every score that follows.
   */
  finish(): { rom_min_deg: number; rom_max_deg: number; confidence: number } | null {
    if (this.accepted < CalibrationRecorder.MIN_FRAMES) return null;
    if (this.maxDeg - this.minDeg < CalibrationRecorder.MIN_SPAN_DEG) return null;
    return {
      rom_min_deg: this.minDeg,
      rom_max_deg: this.maxDeg,
      confidence: this.accepted / this.seen,
    };
  }

  reset(): void {
    this.minDeg = Number.POSITIVE_INFINITY;
    this.maxDeg = Number.NEGATIVE_INFINITY;
    this.accepted = 0;
    this.seen = 0;
  }
}
