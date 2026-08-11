/**
 * One-Euro filter. Mirrors `backend/src/iacoach/filter.py` exactly.
 *
 * Why not a moving average: a 5-frame mean at 30 fps adds ~80 ms of lag and
 * flattens the angular-velocity peaks, which are the fatigue signal we most want
 * to keep. The One-Euro filter adapts its cutoff to the signal's own speed, so it
 * smooths a still limb hard and a fast one barely at all — low jitter at rest,
 * low lag in movement, which is the trade a rep counter actually needs.
 *
 * Reference: Casiez, Roussel & Vogel, "1e Filter" (CHI 2012).
 */

/**
 * Tuned for joint angles in degrees at 25-60 fps. Identical values live in the
 * Python mirror; changing one without the other breaks conformance.
 */
export const DEFAULT_MIN_CUTOFF = 1.0;
export const DEFAULT_BETA = 0.05;
export const DEFAULT_DERIVATIVE_CUTOFF = 1.0;

function alpha(cutoffHz: number, dtSeconds: number): number {
  const tau = 1 / (2 * Math.PI * cutoffHz);
  return 1 / (1 + tau / dtSeconds);
}

/** Stateful, single-channel. One instance per filtered signal. */
export class OneEuroFilter {
  private xHat: number | null = null;
  private dxHat = 0;
  private tPrevMs: number | null = null;

  constructor(
    private readonly minCutoff = DEFAULT_MIN_CUTOFF,
    private readonly beta = DEFAULT_BETA,
    private readonly derivativeCutoff = DEFAULT_DERIVATIVE_CUTOFF,
  ) {}

  reset(): void {
    this.xHat = null;
    this.dxHat = 0;
    this.tPrevMs = null;
  }

  filter(value: number, tMs: number): number {
    if (this.xHat === null || this.tPrevMs === null) {
      this.xHat = value;
      this.dxHat = 0;
      this.tPrevMs = tMs;
      return value;
    }

    const dtSeconds = (tMs - this.tPrevMs) / 1000;
    if (dtSeconds <= 0) {
      // Duplicate or out-of-order timestamp: hold the last estimate rather than
      // dividing by zero or letting a stale sample move the output.
      return this.xHat;
    }

    const dx = (value - this.xHat) / dtSeconds;
    const aD = alpha(this.derivativeCutoff, dtSeconds);
    this.dxHat = aD * dx + (1 - aD) * this.dxHat;

    const cutoff = this.minCutoff + this.beta * Math.abs(this.dxHat);
    const a = alpha(cutoff, dtSeconds);
    this.xHat = a * value + (1 - a) * this.xHat;
    this.tPrevMs = tMs;
    return this.xHat;
  }
}
