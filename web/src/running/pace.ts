/**
 * Pace and distance from GPS fixes.
 *
 * The hard part is not the arithmetic, it is knowing which fixes to trust. A
 * phone parked under trees emits fixes that jitter by tens of metres; integrated
 * naively, standing still accumulates a kilometre. Every fix is therefore
 * filtered on reported accuracy, and implausible speeds are dropped rather than
 * averaged in.
 */

export interface Fix {
  t_ms: number;
  lat: number;
  lon: number;
  /** Reported horizontal accuracy in metres. */
  accuracy_m: number;
}

/** Fixes worse than this are noise, not position. */
export const MAX_ACCURACY_M = 25;

/** Above this, the "movement" is a GPS jump, not a human. ~36 km/h. */
export const MAX_PLAUSIBLE_SPEED_MS = 10;

const EARTH_RADIUS_M = 6_371_000;

const toRadians = (degrees: number): number => (degrees * Math.PI) / 180;

/** Great-circle distance in metres. */
export function haversine(a: Fix, b: Fix): number {
  const dLat = toRadians(b.lat - a.lat);
  const dLon = toRadians(b.lon - a.lon);
  const lat1 = toRadians(a.lat);
  const lat2 = toRadians(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

export interface Track {
  distance_m: number;
  duration_s: number;
  /** Fixes dropped for poor accuracy or implausible speed. */
  rejected: number;
}

/**
 * Accumulates a track from raw fixes.
 *
 * Duration is measured between the first and last *accepted* fix, not wall
 * clock: time spent with no usable signal is not time the athlete was measured
 * running, and counting it would silently deflate the pace.
 */
export function accumulate(fixes: Fix[]): Track {
  const usable = fixes.filter((fix) => fix.accuracy_m <= MAX_ACCURACY_M);
  let rejected = fixes.length - usable.length;

  let distance = 0;
  let first: Fix | null = null;
  let last: Fix | null = null;

  for (const fix of usable) {
    if (last === null) {
      first = fix;
      last = fix;
      continue;
    }
    const dt = (fix.t_ms - last.t_ms) / 1000;
    if (dt <= 0) {
      rejected += 1;
      continue;
    }
    const step = haversine(last, fix);
    if (step / dt > MAX_PLAUSIBLE_SPEED_MS) {
      rejected += 1;
      continue;
    }
    distance += step;
    last = fix;
  }

  const duration =
    first && last && last !== first ? (last.t_ms - first.t_ms) / 1000 : 0;
  return { distance_m: distance, duration_s: duration, rejected };
}

/**
 * Pace in seconds per kilometre, or `null` when there is not enough movement to
 * divide by. Returning a number from a 3-metre track would be arithmetic, not
 * measurement.
 */
export function paceSecondsPerKm(track: Track): number | null {
  if (track.distance_m < 50 || track.duration_s <= 0) return null;
  return (track.duration_s / track.distance_m) * 1000;
}

/** `4'32"` — the notation runners actually read. */
export function formatPace(secondsPerKm: number): string {
  const minutes = Math.floor(secondsPerKm / 60);
  const seconds = Math.round(secondsPerKm - minutes * 60);
  // 4'60" is not a thing; carry it.
  if (seconds === 60) return `${minutes + 1}'00"`;
  return `${minutes}'${String(seconds).padStart(2, "0")}"`;
}
