/**
 * Repetition counting and form scoring.
 *
 * Mirrors `backend/src/iacoach/counting.py`. Both implementations must produce
 * identical `RepEvent` streams on the shared fixtures in `fixtures/` — that
 * conformance check is what stops the on-device and server-side analyses from
 * drifting apart (see docs/ARCHITECTURE.md §2). Arithmetic here is written to
 * match the Python operation-for-operation, not just semantically.
 *
 * Design notes that are load-bearing, not stylistic:
 *
 * - Every threshold is a fraction of the athlete's *own* calibrated range. There
 *   are no hard-coded joint angles: a 1.60 m and a 1.95 m athlete do not share a
 *   pull-up geometry.
 * - The state machine uses hysteresis on every boundary. A single threshold
 *   makes a rep flicker in and out at the turning point, which is where the
 *   signal is slowest and noisiest.
 * - A repetition that falls short is *recorded* with its scores and
 *   `counted: false`. Data is never discarded for being imperfect.
 * - When frame confidence is low, corrective flags are suppressed. A wrong
 *   correction is worse than no correction.
 */

import { OneEuroFilter } from "../pose/filter";
import type {
  Exercise,
  ExerciseCalibration,
  FormScores,
  RepEvent,
  RepPhase,
  Tempo,
} from "../types/contracts";

/** One frame, reduced to the signals the counter consumes. */
export interface FrameSample {
  t_ms: number;
  elbow_left_deg: number;
  elbow_right_deg: number;
  /** Trunk deviation from vertical, in degrees. 0 = upright. */
  trunk_deg: number;
  /** Hip speed orthogonal to the movement axis, m/s. The kipping signal. */
  hip_speed: number;
  confidence: number;
}

/**
 * Thresholds, in normalised-flexion units unless stated. `flexion` is 0.0 at
 * full extension (dead hang) and 1.0 at the athlete's calibrated maximum
 * flexion. Identical values live in the Python mirror.
 */
export interface CountingConfig {
  bottomEnter: number;
  bottomExit: number;
  topEnter: number;
  topExit: number;
  /** Below this peak the excursion is not a rep — it is a shrug or noise. */
  repFloor: number;
  /** At or above this peak, the rep counts. Between the two, `rom_short`. */
  countFloor: number;
  symmetryToleranceDeg: number;
  kipToleranceMs: number;
  trunkToleranceDeg: number;
  tempoCvTolerance: number;
  flagSymmetry: number;
  flagKipping: number;
  flagTempo: number;
  flagAlignment: number;
  minCoachableConfidence: number;
}

export const DEFAULT_CONFIG: CountingConfig = {
  bottomEnter: 0.12,
  bottomExit: 0.2,
  topEnter: 0.75,
  topExit: 0.65,
  repFloor: 0.5,
  countFloor: 0.75,
  symmetryToleranceDeg: 20.0,
  kipToleranceMs: 0.8,
  trunkToleranceDeg: 30.0,
  tempoCvTolerance: 1.5,
  flagSymmetry: 0.7,
  flagKipping: 0.7,
  flagTempo: 0.6,
  flagAlignment: 0.7,
  minCoachableConfidence: 0.7,
};

/**
 * Window used to estimate angular speed. Wide enough that landmark jitter does
 * not dominate the derivative, narrow enough to still resolve a stall inside a
 * one-second concentric.
 */
export const DIFFERENTIATION_WINDOW_MS = 100.0;

const clamp01 = (v: number): number => Math.max(0, Math.min(1, v));

function mean(values: number[]): number {
  if (values.length === 0) return 0;
  let total = 0;
  for (const v of values) total += v;
  return total / values.length;
}

function symmetryScore(leftDeg: number, rightDeg: number, toleranceDeg: number): number {
  return Math.max(0, 1 - Math.abs(leftDeg - rightDeg) / toleranceDeg);
}

function normalised(calibration: ExerciseCalibration, angleDeg: number): number {
  const span = calibration.rom_max_deg - calibration.rom_min_deg;
  if (span <= 0) return 0;
  return Math.max(0, Math.min(1, (angleDeg - calibration.rom_min_deg) / span));
}

const elbowMeanDeg = (s: FrameSample): number =>
  (s.elbow_left_deg + s.elbow_right_deg) / 2;

/**
 * Streaming counter: push frames, get a `RepEvent` when one completes.
 *
 * Streaming rather than batch because the on-device path has to emit feedback
 * within the ~100 ms correction window; the fixture runner just drives the same
 * object frame by frame.
 */
export class RepCounter {
  private readonly filter = new OneEuroFilter();
  private currentPhase: RepPhase = "idle";
  private repIndex = 0;

  private windowSamples: FrameSample[] = [];
  private windowFlexion: number[] = [];

  private bottomSinceMs: number | null = null;
  private pendingBottomPauseS = 0;
  private repStartMs: number | null = null;
  private topEnterMs: number | null = null;
  private topExitMs: number | null = null;
  private peakFlexion = 0;
  private peakMs: number | null = null;

  constructor(
    private readonly exercise: Exercise,
    private readonly calibration: ExerciseCalibration,
    private readonly config: CountingConfig = DEFAULT_CONFIG,
  ) {}

  get phase(): RepPhase {
    return this.currentPhase;
  }

  get completedReps(): number {
    return this.repIndex;
  }

  /** Filtered, normalised flexion for one frame: 0 = extended, 1 = flexed. */
  flexionOf(sample: FrameSample, tMs: number): number {
    const smoothed = this.filter.filter(elbowMeanDeg(sample), tMs);
    return 1 - normalised(this.calibration, smoothed);
  }

  /** Feed one frame. Returns a `RepEvent` on the frame a rep completes. */
  push(sample: FrameSample): RepEvent | null {
    const cfg = this.config;
    const t = sample.t_ms;
    const f = this.flexionOf(sample, t);

    if (this.currentPhase !== "idle" && this.repStartMs !== null) {
      this.windowSamples.push(sample);
      this.windowFlexion.push(f);
      if (f > this.peakFlexion) {
        this.peakFlexion = f;
        this.peakMs = t;
      }
    }

    switch (this.currentPhase) {
      case "idle":
        // Wait for a confirmed dead hang before counting anything: starting
        // mid-movement would fabricate a partial first rep.
        if (f <= cfg.bottomEnter) this.enterBottom(t);
        return null;

      case "bottom":
        if (f >= cfg.bottomExit) this.startRep(t, sample, f);
        return null;

      case "concentric":
        if (f >= cfg.topEnter) {
          this.currentPhase = "top";
          this.topEnterMs = t;
        } else if (f <= cfg.bottomEnter) {
          // Came back down without reaching the top: still a repetition attempt
          // if it went far enough, otherwise noise.
          return this.closeRep(t);
        }
        return null;

      case "top":
        if (f <= cfg.topExit) {
          this.currentPhase = "eccentric";
          this.topExitMs = t;
        }
        return null;

      case "eccentric":
        if (f <= cfg.bottomEnter) return this.closeRep(t);
        return null;
    }
  }

  // -- state transitions --------------------------------------------------- //

  private enterBottom(tMs: number): void {
    this.currentPhase = "bottom";
    this.bottomSinceMs = tMs;
  }

  private startRep(tMs: number, sample: FrameSample, flexion: number): void {
    this.currentPhase = "concentric";
    this.repStartMs = tMs;
    // The dead hang preceding this rep. Attributed to the rep that follows so
    // the event can be emitted the moment the rep ends, rather than deferred
    // until the athlete starts the next one.
    this.pendingBottomPauseS =
      this.bottomSinceMs === null ? 0 : (tMs - this.bottomSinceMs) / 1000;
    this.topEnterMs = null;
    this.topExitMs = null;
    this.peakFlexion = flexion;
    this.peakMs = tMs;
    this.windowSamples = [sample];
    this.windowFlexion = [flexion];
  }

  private closeRep(tMs: number): RepEvent | null {
    const start = this.repStartMs;
    const peak = this.peakFlexion;
    const samples = this.windowSamples;
    const flexion = this.windowFlexion;

    this.enterBottom(tMs);
    this.windowSamples = [];
    this.windowFlexion = [];
    this.repStartMs = null;

    if (start === null || peak < this.config.repFloor || samples.length < 2) return null;

    const event = this.buildEvent(start, tMs, peak, samples, flexion);
    this.repIndex += 1;
    return event;
  }

  // -- scoring ------------------------------------------------------------- //

  private buildEvent(
    startMs: number,
    endMs: number,
    peak: number,
    samples: FrameSample[],
    flexion: number[],
  ): RepEvent {
    const cfg = this.config;
    const peakMs = this.peakMs ?? endMs;
    // A rep that never reached the top has no plateau: concentric and eccentric
    // meet at the peak.
    const topEnter = this.topEnterMs ?? peakMs;
    const topExit = this.topExitMs ?? peakMs;

    const tempo: Tempo = {
      eccentric_s: Math.max(0, (endMs - topExit) / 1000),
      bottom_pause_s: Math.max(0, this.pendingBottomPauseS),
      concentric_s: Math.max(0, (topEnter - startMs) / 1000),
      top_pause_s: Math.max(0, (topExit - topEnter) / 1000),
    };

    let maxHipSpeed = samples[0]!.hip_speed;
    for (const s of samples) if (s.hip_speed > maxHipSpeed) maxHipSpeed = s.hip_speed;

    const scores: FormScores = {
      rom: clamp01(peak),
      symmetry: mean(
        samples.map((s) =>
          symmetryScore(s.elbow_left_deg, s.elbow_right_deg, cfg.symmetryToleranceDeg),
        ),
      ),
      kipping: clamp01(1 - maxHipSpeed / cfg.kipToleranceMs),
      tempo_control: this.tempoControl(samples, flexion, topEnter),
      alignment: mean(
        samples.map((s) => clamp01(1 - Math.abs(s.trunk_deg) / cfg.trunkToleranceDeg)),
      ),
    };

    const confidence = clamp01(mean(samples.map((s) => s.confidence)));
    const counted = peak >= cfg.countFloor;
    const angles = samples.map(elbowMeanDeg);

    return {
      rep_index: this.repIndex,
      exercise: this.exercise,
      started_at_ms: startMs,
      duration_ms: Math.max(1e-9, endMs - startMs),
      tempo,
      scores,
      peak_angle_deg: Math.max(...angles),
      min_angle_deg: Math.min(...angles),
      confidence,
      counted,
      flags: this.flagsFor(scores, confidence, counted),
    };
  }

  /**
   * Smoothness of the velocity profile: 1.0 = even pace, 0.0 = jerky.
   *
   * Restricted to the concentric phase on purpose. A deliberate pause at the top
   * or bottom is technique, not jerkiness; including those zero-speed frames
   * would penalise a controlled rep for being controlled.
   *
   * Speed is differentiated over a fixed window, not between adjacent frames.
   * Frame-to-frame differencing amplifies landmark jitter enough to flag
   * identical reps inconsistently, and it would make the score depend on frame
   * rate — the same clip analysed at 30 fps on-device and 60 fps server-side has
   * to yield the same number.
   */
  private tempoControl(
    samples: FrameSample[],
    flexion: number[],
    topEnterMs: number,
  ): number {
    const speeds: number[] = [];
    let j = 0;
    for (let i = 1; i < samples.length; i += 1) {
      if (samples[i]!.t_ms > topEnterMs) break;
      while (
        j + 1 < i &&
        samples[i]!.t_ms - samples[j + 1]!.t_ms >= DIFFERENTIATION_WINDOW_MS
      ) {
        j += 1;
      }
      const dtSeconds = (samples[i]!.t_ms - samples[j]!.t_ms) / 1000;
      if (dtSeconds <= 0) continue;
      speeds.push(Math.abs(flexion[i]! - flexion[j]!) / dtSeconds);
    }

    if (speeds.length < 2) return 1;
    const meanSpeed = mean(speeds);
    if (meanSpeed <= 0) return 1;
    let sumSquares = 0;
    for (const s of speeds) sumSquares += (s - meanSpeed) ** 2;
    const cv = Math.sqrt(sumSquares / speeds.length) / meanSpeed;
    return clamp01(1 - cv / this.config.tempoCvTolerance);
  }

  private flagsFor(scores: FormScores, confidence: number, counted: boolean): string[] {
    const cfg = this.config;
    if (confidence < cfg.minCoachableConfidence) {
      // Tracking was poor. Report that, and nothing else: every form score
      // derived from those frames is unreliable, and a confident-sounding
      // correction built on bad data is the failure mode to avoid.
      return ["low_confidence"];
    }

    const flags: string[] = [];
    if (!counted) flags.push("rom_short");
    if (scores.kipping < cfg.flagKipping) flags.push("kipping");
    if (scores.symmetry < cfg.flagSymmetry) flags.push("asymmetry");
    if (scores.tempo_control < cfg.flagTempo) flags.push("jerky");
    if (scores.alignment < cfg.flagAlignment) flags.push("trunk_swing");
    return flags;
  }
}

/** Batch helper over the same streaming counter. Used by the fixture runner. */
export function analyseSequence(
  exercise: Exercise,
  calibration: ExerciseCalibration,
  samples: FrameSample[],
  config: CountingConfig = DEFAULT_CONFIG,
): RepEvent[] {
  const counter = new RepCounter(exercise, calibration, config);
  const events: RepEvent[] = [];
  for (const sample of samples) {
    const event = counter.push(sample);
    if (event !== null) events.push(event);
  }
  return events;
}
