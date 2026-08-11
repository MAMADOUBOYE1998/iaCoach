/**
 * Running cadence and regularity, from the phone's accelerometer.
 *
 * **Not from the camera.** The brief asks to reuse the vision layer "where
 * relevant"; for running it is not. Filming yourself running requires a second
 * person or a fixed tripod you then run away from, which describes a track
 * session and not a run. The phone is already strapped to the athlete and its
 * accelerometer measures gait directly, so that is the sensor.
 *
 * The camera pipeline stays relevant for running *drills* filmed in place —
 * that is a later module, not this one.
 *
 * Cadence is the vertical oscillation frequency of the body: each foot strike
 * produces an acceleration peak. Detection is peak-based with a refractory
 * period, which is robust to the amplitude differences between a phone in a
 * hand, an armband, or a pocket.
 */

export interface MotionSample {
  t_ms: number;
  /** Acceleration including gravity, m/s². */
  x: number;
  y: number;
  z: number;
}

export interface StepEvent {
  t_ms: number;
  /** Interval since the previous step, ms. `null` for the first one. */
  interval_ms: number | null;
}

/** Physiological bounds: below 100 spm is walking, above 240 is not running. */
export const MIN_STEP_INTERVAL_MS = 250;
export const MAX_STEP_INTERVAL_MS = 1200;

/**
 * Peak height, in m/s², on the gravity-removed signal.
 *
 * Calibrated on synthetic signals only. Real foot-strike amplitude varies with
 * surface, shoe and where the phone is carried; this needs recalibrating on
 * recorded runs before any cadence figure is shown as fact.
 */
export const DEFAULT_PEAK_THRESHOLD = 1.2;

/** Window used to estimate the gravity component. */
const GRAVITY_WINDOW_MS = 1000;

export function magnitude(sample: MotionSample): number {
  return Math.sqrt(sample.x * sample.x + sample.y * sample.y + sample.z * sample.z);
}

/**
 * Removes the gravity offset with a trailing mean.
 *
 * A trailing mean is used rather than a centred one because this has to run
 * live: a centred window would need future samples the athlete has not produced
 * yet. The lag it introduces shifts every peak equally, so step *intervals* —
 * which is all cadence depends on — are unaffected.
 */
export function removeGravity(samples: MotionSample[]): number[] {
  const out: number[] = [];
  let start = 0;
  let sum = 0;

  for (let i = 0; i < samples.length; i += 1) {
    sum += magnitude(samples[i]!);
    while (samples[i]!.t_ms - samples[start]!.t_ms > GRAVITY_WINDOW_MS) {
      sum -= magnitude(samples[start]!);
      start += 1;
    }
    const mean = sum / (i - start + 1);
    out.push(magnitude(samples[i]!) - mean);
  }
  return out;
}

/**
 * Detects foot strikes.
 *
 * A step is a local maximum above the threshold, at least `MIN_STEP_INTERVAL_MS`
 * after the previous one. The refractory period is what stops a single noisy
 * strike from being counted two or three times — without it, cadence roughly
 * doubles on rough ground.
 */
export function detectSteps(
  samples: MotionSample[],
  threshold: number = DEFAULT_PEAK_THRESHOLD,
): StepEvent[] {
  const signal = removeGravity(samples);
  const steps: StepEvent[] = [];
  let lastStepMs: number | null = null;

  for (let i = 1; i < signal.length - 1; i += 1) {
    const value = signal[i]!;
    if (value < threshold) continue;
    if (value < signal[i - 1]! || value < signal[i + 1]!) continue;

    const t = interpolatePeakTime(samples, signal, i);
    if (lastStepMs !== null && t - lastStepMs < MIN_STEP_INTERVAL_MS) continue;

    steps.push({ t_ms: t, interval_ms: lastStepMs === null ? null : t - lastStepMs });
    lastStepMs = t;
  }
  return steps;
}

/**
 * Sub-sample peak timing by fitting a parabola through the peak and its
 * neighbours.
 *
 * This is not polish. Accelerometers sample at 50–100 Hz, so a raw peak index is
 * only accurate to ±10–20 ms. Against a ~350 ms stride that quantisation alone
 * produces several percent of apparent step-interval variability — enough to
 * make a metronomic gait score as erratic and to bias cadence by a few spm.
 * Interpolating removes a measurement artefact that would otherwise be reported
 * as the athlete's gait.
 */
function interpolatePeakTime(
  samples: MotionSample[],
  signal: number[],
  index: number,
): number {
  const before = signal[index - 1]!;
  const peak = signal[index]!;
  const after = signal[index + 1]!;
  const curvature = before - 2 * peak + after;
  const t = samples[index]!.t_ms;
  // A flat or upward curvature means this is not a clean peak; keep the sample
  // time rather than extrapolating from a shape that is not a parabola.
  if (curvature >= 0) return t;

  const offsetSamples = (0.5 * (before - after)) / curvature;
  if (!Number.isFinite(offsetSamples) || Math.abs(offsetSamples) > 1) return t;

  const dt = (samples[index + 1]!.t_ms - samples[index - 1]!.t_ms) / 2;
  return t + offsetSamples * dt;
}

/** Step intervals that fall inside the running range. */
export function runningIntervals(steps: StepEvent[]): number[] {
  return steps
    .map((step) => step.interval_ms)
    .filter(
      (interval): interval is number =>
        interval !== null &&
        interval >= MIN_STEP_INTERVAL_MS &&
        interval <= MAX_STEP_INTERVAL_MS,
    );
}

/** Steps per minute, or `null` when there are too few steps to mean anything. */
export function cadenceSpm(steps: StepEvent[]): number | null {
  const intervals = runningIntervals(steps);
  if (intervals.length < 3) return null;
  const mean = intervals.reduce((a, b) => a + b, 0) / intervals.length;
  return 60_000 / mean;
}

/**
 * Tolerance at which regularity reaches 0, as a coefficient of variation.
 *
 * Placeholder. Trained runners sit around 2–4% step-interval variability, so
 * 0.20 is deliberately loose — it flags a genuinely erratic gait and stays quiet
 * otherwise. Needs recalibrating on recorded runs before the number is shown as
 * anything but indicative.
 */
export const REGULARITY_TOLERANCE = 0.2;

/**
 * Gait regularity in [0, 1]. 1.0 = metronomic.
 *
 * Continuous, like every other score in this project: "irregular" is a degree,
 * not a verdict.
 */
export function regularity(steps: StepEvent[]): number | null {
  const intervals = runningIntervals(steps);
  if (intervals.length < 3) return null;
  const mean = intervals.reduce((a, b) => a + b, 0) / intervals.length;
  if (mean <= 0) return null;
  const variance =
    intervals.reduce((total, value) => total + (value - mean) ** 2, 0) / intervals.length;
  const cv = Math.sqrt(variance) / mean;
  return Math.max(0, Math.min(1, 1 - cv / REGULARITY_TOLERANCE));
}
