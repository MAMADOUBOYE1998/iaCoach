/**
 * Exercise classification from a sliding window of pose landmarks.
 *
 * Mirror of `backend/src/iacoach/classify.py`. Both must agree on the fixtures
 * in `fixtures/classify/`, replayed by both languages in CI — the phone
 * classifies live, the server classifies recorded video, and a silent
 * divergence would make a stored session incomparable with the next.
 *
 * Why this exists, in one measurement: on 100 clips of *other* movements the
 * repetition counter invented reps on 31 of them (`docs/BENCHMARKS.md`). It
 * counts elbow-flexion cycles, and rowing is one. Nothing upstream ever asked
 * whether the athlete was doing the exercise at all. This is that question.
 *
 * Every threshold is a fraction of the athlete's own limb lengths or a joint
 * range in degrees — never an absolute metre, so the same numbers hold for a
 * 1.60 m and a 1.95 m athlete. They are geometric priors, not measurements:
 * checked for refusal on 100 out-of-domain clips, never fitted to annotated
 * positives, because we have none.
 */

import type { Exercise } from "../types/contracts";
import { LANDMARK, usableFraction, type Landmark } from "../pose/landmarker";

/**
 * Wider than the counter's driving set: telling a squat from a pull-up needs
 * the legs. Ankles are excluded on purpose — they are the first thing to leave
 * frame when an athlete films themselves on a bar, and requiring them would
 * refuse the very footage we most want to classify.
 */
export const CLASSIFIER_LANDMARKS = [
  LANDMARK.LEFT_SHOULDER,
  LANDMARK.RIGHT_SHOULDER,
  LANDMARK.LEFT_ELBOW,
  LANDMARK.RIGHT_ELBOW,
  LANDMARK.LEFT_WRIST,
  LANDMARK.RIGHT_WRIST,
  LANDMARK.LEFT_HIP,
  LANDMARK.RIGHT_HIP,
  LANDMARK.LEFT_KNEE,
  LANDMARK.RIGHT_KNEE,
];

/**
 * Exercises in the contract this classifier deliberately never emits. Written
 * down rather than silently absent: an athlete doing chin-ups deserves to know
 * the label is approximate, and a future reader deserves to know these were
 * omitted on purpose rather than forgotten.
 */
export const UNCLASSIFIABLE: Partial<Record<Exercise, string>> = {
  chin_up:
    "indistinguishable from a pull-up here: the difference is grip supination, " +
    "and forearm rotation is not recoverable from the landmarks this stage uses",
  muscle_up:
    "needs a model of the transition over the bar, and we have no annotated " +
    "example of one. A muscle-up will read as PULL_UP during its pull phase",
};

export interface ClassifierConfig {
  /** Long enough to contain a full repetition at a slow tempo — the joint
   *  ranges below are meaningless over a fraction of a cycle. */
  windowS: number;
  minFrames: number;
  minConfidence: number;
  /** Below this the window is `unknown`. Refusing is cheap: a misrouted rule
   *  set corrects the wrong thing, which is worse than not correcting. */
  minScore: number;
  /** A challenger must beat the incumbent by `switchMargin` on `switchWindows`
   *  consecutive windows. Same hysteresis reasoning as the rep state machine:
   *  a label that flickers mid-set is worse than a stale one. */
  switchMargin: number;
  switchWindows: number;
}

export const DEFAULT_CLASSIFIER_CONFIG: ClassifierConfig = {
  windowS: 2.0,
  minFrames: 20,
  minConfidence: 0.7,
  minScore: 0.45,
  switchMargin: 0.15,
  switchWindows: 3,
};

export interface FrameFeatures {
  t_ms: number;
  /** Height of the hands above the shoulders, in arm lengths. Positive means
   *  overhead. The single most discriminating quantity here. */
  wrist_above_shoulder: number;
  /** 1.0 when the trunk is aligned with gravity, 0.0 when horizontal. */
  trunk_verticality: number;
  elbow_deg: number;
  knee_deg: number;
  hip_deg: number;
  confidence: number;
}

export interface WindowFeatures {
  wrist_above_shoulder: number;
  trunk_verticality: number;
  elbow_rom_deg: number;
  knee_rom_deg: number;
  hip_rom_deg: number;
  knee_deg: number;
  hip_deg: number;
  frames: number;
  confidence: number;
}

export interface Classification {
  exercise: Exercise;
  confidence: number;
  scores: Partial<Record<Exercise, number>>;
  reason: string;
  features: WindowFeatures | null;
}

interface Point3 {
  x: number;
  y: number;
  z: number;
}

function quantile(sorted: number[], q: number): number {
  const rank = (sorted.length - 1) * q;
  const low = Math.trunc(rank);
  const high = Math.min(low + 1, sorted.length - 1);
  return sorted[low]! + (sorted[high]! - sorted[low]!) * (rank - low);
}

/**
 * p90 − p10 rather than max − min. The counter learned this the hard way on
 * real footage: on clip `082` the calibrated range was set by seven frames out
 * of 791, and every threshold being a fraction of it, those seven starved the
 * other 784.
 */
function robustRange(values: number[]): number {
  if (values.length < 2) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return quantile(sorted, 0.9) - quantile(sorted, 0.1);
}

function median(values: number[]): number {
  if (values.length === 0) return 0;
  return quantile([...values].sort((a, b) => a - b), 0.5);
}

function point(landmarks: Landmark[], index: number): Point3 | null {
  const lm = landmarks[index];
  return lm === undefined ? null : { x: lm.x, y: lm.y, z: lm.z };
}

function subtract(a: Point3, b: Point3): Point3 {
  return { x: a.x - b.x, y: a.y - b.y, z: a.z - b.z };
}

function norm(v: Point3): number {
  return Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
}

function midpoint(a: Point3, b: Point3): Point3 {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: (a.z + b.z) / 2 };
}

/** Interior angle at `vertex`, in degrees. 180 for a degenerate configuration —
 *  the "extended" reading, which never fabricates a flexed position. */
function angleDeg(a: Point3, vertex: Point3, c: Point3): number {
  const v1 = subtract(a, vertex);
  const v2 = subtract(c, vertex);
  const n1 = norm(v1);
  const n2 = norm(v2);
  if (n1 === 0 || n2 === 0) return 180;
  const cosine = (v1.x * v2.x + v1.y * v2.y + v1.z * v2.z) / (n1 * n2);
  return (Math.acos(Math.max(-1, Math.min(1, cosine))) * 180) / Math.PI;
}

/** 1.0 at or above `threshold`, fading to 0.0 `soft` below it. */
function atLeast(value: number, threshold: number, soft: number): number {
  if (soft <= 0) return value >= threshold ? 1 : 0;
  return Math.max(0, Math.min(1, (value - threshold) / soft + 1));
}

function atMost(value: number, threshold: number, soft: number): number {
  return atLeast(-value, -threshold, soft);
}

function band(value: number, low: number, high: number, soft: number): number {
  return Math.min(atLeast(value, low, soft), atMost(value, high, soft));
}

const REQUIRED = [
  "LEFT_SHOULDER",
  "RIGHT_SHOULDER",
  "LEFT_ELBOW",
  "RIGHT_ELBOW",
  "LEFT_WRIST",
  "RIGHT_WRIST",
  "LEFT_HIP",
  "RIGHT_HIP",
  "LEFT_KNEE",
  "RIGHT_KNEE",
] as const;

/**
 * One frame of landmarks, reduced. `null` when the frame lacks a joint — never
 * a neutral substitute, because a fabricated posture would be classified as
 * confidently as a real one.
 */
export function frameFeatures(
  world: Landmark[],
  normalized: Landmark[],
  tMs: number,
): FrameFeatures | null {
  const p: Record<string, Point3> = {};
  for (const name of REQUIRED) {
    const found = point(world, LANDMARK[name]);
    if (found === null) return null;
    p[name] = found;
  }

  const leftShoulder = p.LEFT_SHOULDER!;
  const rightShoulder = p.RIGHT_SHOULDER!;
  const leftElbow = p.LEFT_ELBOW!;
  const rightElbow = p.RIGHT_ELBOW!;
  const leftWrist = p.LEFT_WRIST!;
  const rightWrist = p.RIGHT_WRIST!;
  const leftHip = p.LEFT_HIP!;
  const rightHip = p.RIGHT_HIP!;
  const leftKnee = p.LEFT_KNEE!;
  const rightKnee = p.RIGHT_KNEE!;

  const shoulder = midpoint(leftShoulder, rightShoulder);
  const hip = midpoint(leftHip, rightHip);
  const wrist = midpoint(leftWrist, rightWrist);
  const knee = midpoint(leftKnee, rightKnee);

  // Scale reference: the athlete's own arm. Every length below is divided by
  // it, so nothing in this module carries an absolute metre.
  const arm =
    (norm(subtract(leftElbow, leftShoulder)) +
      norm(subtract(leftWrist, leftElbow)) +
      norm(subtract(rightElbow, rightShoulder)) +
      norm(subtract(rightWrist, rightElbow))) /
    2;
  if (arm <= 0) return null;

  // y points down in world landmarks, so "above" is a smaller y.
  const wristAboveShoulder = (shoulder.y - wrist.y) / arm;

  const trunk = subtract(shoulder, hip);
  const trunkLength = norm(trunk);
  if (trunkLength <= 0) return null;
  const trunkVerticality = Math.abs(trunk.y) / trunkLength;

  const elbow =
    (angleDeg(leftShoulder, leftElbow, leftWrist) +
      angleDeg(rightShoulder, rightElbow, rightWrist)) /
    2;

  // A missing ankle yields the degenerate 180 deg — "leg extended", the reading
  // that makes the classifier refuse a squat rather than assert one. Ankles
  // leave frame constantly; refusing the whole frame over them would throw away
  // most self-filmed footage.
  const leftAnkle = point(world, LANDMARK.LEFT_ANKLE) ?? leftKnee;
  const rightAnkle = point(world, LANDMARK.RIGHT_ANKLE) ?? rightKnee;
  const kneeDeg =
    (angleDeg(leftHip, leftKnee, leftAnkle) + angleDeg(rightHip, rightKnee, rightAnkle)) / 2;

  return {
    t_ms: tMs,
    wrist_above_shoulder: wristAboveShoulder,
    trunk_verticality: trunkVerticality,
    elbow_deg: elbow,
    knee_deg: kneeDeg,
    hip_deg: angleDeg(shoulder, hip, knee),
    confidence: usableFraction(normalized, CLASSIFIER_LANDMARKS),
  };
}

/** Aggregate a window. Postures use the median, work uses a robust range. */
export function windowFeatures(frames: FrameFeatures[]): WindowFeatures {
  return {
    wrist_above_shoulder: median(frames.map((f) => f.wrist_above_shoulder)),
    trunk_verticality: median(frames.map((f) => f.trunk_verticality)),
    elbow_rom_deg: robustRange(frames.map((f) => f.elbow_deg)),
    knee_rom_deg: robustRange(frames.map((f) => f.knee_deg)),
    hip_rom_deg: robustRange(frames.map((f) => f.hip_deg)),
    knee_deg: median(frames.map((f) => f.knee_deg)),
    hip_deg: median(frames.map((f) => f.hip_deg)),
    frames: frames.length,
    confidence: median(frames.map((f) => f.confidence)),
  };
}

/**
 * Score every exercise, take the best, or refuse.
 *
 * Each rule is a conjunction combined with `min` rather than a product: the
 * weakest piece of evidence should cap the confidence, and a product would
 * penalise an exercise merely for being defined by more criteria than another.
 */
export function classifyWindow(
  f: WindowFeatures,
  config: ClassifierConfig = DEFAULT_CLASSIFIER_CONFIG,
): Classification {
  const hangs = atLeast(f.wrist_above_shoulder, 0.5, 0.5);
  // A dip supports the whole body on hands at hip height, so the wrists sit
  // roughly an arm's length below the shoulders and the trunk is near-plumb.
  // Both bounds are tight on purpose: at -0.3 the hands are barely below
  // shoulder height, which describes a rowing stroke or a bent-over row just as
  // well, and those cycle the elbow through a full range without the athlete
  // being on bars at all. Rowing is the largest single source of invented reps
  // in the specificity run.
  const onBars = atMost(f.wrist_above_shoulder, -0.6, 0.3);
  const plumb = atLeast(f.trunk_verticality, 0.9, 0.12);
  // Looser than `plumb`, because a kipping pull-up leans and we want it
  // classified as a pull-up and then flagged, not refused. Hands overhead
  // already separates the hanging family from everything else.
  const upright = atLeast(f.trunk_verticality, 0.85, 0.2);
  const horizontal = atMost(f.trunk_verticality, 0.35, 0.25);
  const armsWork = atLeast(f.elbow_rom_deg, 40, 25);
  const armsStill = atMost(f.elbow_rom_deg, 25, 25);
  const legsStill = atMost(f.knee_rom_deg, 30, 30);
  const legsWork = atLeast(f.knee_rom_deg, 50, 30);
  // A squat folds the hip as much as the knee — roughly 130 deg of it. Without
  // this term the rule read "standing, legs moving, arms still", which also
  // describes walking, cycling and skipping rope: it labelled 34 of the 100
  // out-of-domain clips a squat, and 16 of them still produced invented reps.
  const hipsFold = atLeast(f.hip_rom_deg, 60, 30);

  const scores: Partial<Record<Exercise, number>> = {
    pull_up: Math.min(hangs, upright, armsWork, legsStill),
    dip: Math.min(onBars, plumb, armsWork, legsStill),
    push_up: Math.min(horizontal, armsWork, legsStill),
    squat: Math.min(legsWork, hipsFold, armsStill, atLeast(f.trunk_verticality, 0.6, 0.3)),
    l_sit: Math.min(
      band(f.hip_deg, 70, 115, 30),
      atLeast(f.knee_deg, 150, 30),
      armsStill,
      atMost(f.knee_rom_deg, 20, 20),
    ),
  };

  const refuse = (confidence: number, reason: string): Classification => ({
    exercise: "unknown",
    confidence,
    scores,
    reason,
    features: f,
  });

  if (f.frames < config.minFrames) return refuse(0, "fenêtre trop courte");
  // Same rule as everywhere else in the analysis stage: unreliable landmarks
  // produce no assertion, only the fact that they were unreliable.
  if (f.confidence < config.minConfidence) return refuse(0, "suivi insuffisant");

  const entries = Object.entries(scores) as [Exercise, number][];
  const [best, bestScore] = entries.reduce((a, b) => (b[1] > a[1] ? b : a));
  if (bestScore < config.minScore) return refuse(bestScore, "aucun exercice reconnu");

  const runnerUp = entries.filter(([e]) => e !== best).reduce((a, b) => Math.max(a, b[1]), 0);
  // Two labels fit equally well. Naming one would route the athlete to a rule
  // set on a coin toss.
  if (bestScore - runnerUp < 0.1) return refuse(bestScore, "ambigu");

  return { exercise: best, confidence: bestScore, scores, reason: "", features: f };
}

/**
 * Streaming classifier over a sliding window. Stateful for the same reason the
 * counter is: the phone needs an answer while the set is happening.
 */
export class ExerciseClassifier {
  private frames: FrameFeatures[] = [];
  private label: Exercise = "unknown";
  private challenger: Exercise = "unknown";
  private challengerWindows = 0;

  constructor(private readonly config: ClassifierConfig = DEFAULT_CLASSIFIER_CONFIG) {}

  get current(): Exercise {
    return this.label;
  }

  reset(): void {
    this.frames = [];
    this.label = "unknown";
    this.challenger = "unknown";
    this.challengerWindows = 0;
  }

  /** Feed one frame. `null` until the window holds enough of them. */
  push(world: Landmark[], normalized: Landmark[], tMs: number): Classification | null {
    const features = frameFeatures(world, normalized, tMs);
    if (features === null) return null;
    this.frames.push(features);
    const horizon = tMs - this.config.windowS * 1000;
    while (this.frames.length > 0 && this.frames[0]!.t_ms < horizon) this.frames.shift();
    if (this.frames.length < this.config.minFrames) return null;

    return this.settle(classifyWindow(windowFeatures(this.frames), this.config));
  }

  /**
   * Hysteresis on the label itself. A single bad window must not rename the
   * exercise mid-set — the label routes the rule set, so flipping it changes
   * which corrections the athlete is given.
   */
  private settle(proposal: Classification): Classification {
    if (proposal.exercise === this.label) {
      this.challengerWindows = 0;
      return proposal;
    }

    if (proposal.exercise !== this.challenger) {
      this.challenger = proposal.exercise;
      this.challengerWindows = 1;
    } else {
      this.challengerWindows += 1;
    }

    const incumbent = proposal.scores[this.label] ?? 0;
    const clearsMargin = proposal.confidence - incumbent >= this.config.switchMargin;
    if (this.challengerWindows >= this.config.switchWindows && clearsMargin) {
      this.label = proposal.exercise;
      this.challengerWindows = 0;
      return proposal;
    }

    return {
      exercise: this.label,
      confidence: incumbent,
      scores: proposal.scores,
      reason: `maintenu (${proposal.exercise} en attente)`,
      features: proposal.features,
    };
  }
}
