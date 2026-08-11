import { describe, expect, it } from "vitest";

import { accumulate, formatPace, haversine, paceSecondsPerKm, type Fix } from "./pace";

function fix(t_ms: number, lat: number, lon: number, accuracy_m = 5): Fix {
  return { t_ms, lat, lon, accuracy_m };
}

/** ~111.32 km per degree of latitude at the equator. */
const METRES_PER_DEG_LAT = 111_320;

describe("haversine", () => {
  it("is zero for the same point", () => {
    expect(haversine(fix(0, 48.85, 2.35), fix(0, 48.85, 2.35))).toBe(0);
  });

  it("measures a degree of latitude", () => {
    const d = haversine(fix(0, 0, 0), fix(0, 1, 0));
    expect(d).toBeCloseTo(METRES_PER_DEG_LAT, -3);
  });

  it("is symmetric", () => {
    const a = fix(0, 48.85, 2.35);
    const b = fix(0, 48.86, 2.36);
    expect(haversine(a, b)).toBeCloseTo(haversine(b, a), 6);
  });
});

describe("accumulate", () => {
  it("sums a straight track", () => {
    // 10 fixes 1 s apart, ~3 m each: about 3 m/s, a realistic jogging pace.
    const step = 3 / METRES_PER_DEG_LAT;
    const fixes = Array.from({ length: 10 }, (_, i) => fix(i * 1000, i * step, 0));
    const track = accumulate(fixes);
    expect(track.distance_m).toBeCloseTo(27, 0);
    expect(track.duration_s).toBeCloseTo(9, 6);
    expect(track.rejected).toBe(0);
  });

  it("drops low-accuracy fixes", () => {
    // A phone under trees emits fixes that jitter by tens of metres; integrated
    // naively, standing still accumulates a kilometre.
    const step = 3 / METRES_PER_DEG_LAT;
    const fixes = [
      fix(0, 0, 0),
      fix(1000, 0.5, 0, 200), // wild jump, reported as inaccurate
      fix(2000, step, 0),
    ];
    const track = accumulate(fixes);
    expect(track.rejected).toBe(1);
    expect(track.distance_m).toBeCloseTo(3, 0);
  });

  it("drops implausible speeds even when accuracy looks fine", () => {
    // A confident-looking fix can still be a jump; 500 m in a second is not a
    // human, whatever the accuracy field claims.
    const fixes = [fix(0, 0, 0), fix(1000, 500 / METRES_PER_DEG_LAT, 0, 5)];
    const track = accumulate(fixes);
    expect(track.rejected).toBe(1);
    expect(track.distance_m).toBe(0);
  });

  it("ignores out-of-order or duplicate timestamps", () => {
    const step = 3 / METRES_PER_DEG_LAT;
    const track = accumulate([fix(0, 0, 0), fix(0, step, 0), fix(1000, 2 * step, 0)]);
    expect(track.rejected).toBe(1);
  });

  it("handles an empty and a single-fix track", () => {
    expect(accumulate([])).toEqual({ distance_m: 0, duration_s: 0, rejected: 0 });
    expect(accumulate([fix(0, 0, 0)]).duration_s).toBe(0);
  });
});

describe("paceSecondsPerKm", () => {
  it("computes pace from a real track", () => {
    // 300 m in 90 s = 5'00"/km.
    const pace = paceSecondsPerKm({ distance_m: 300, duration_s: 90, rejected: 0 });
    expect(pace).toBeCloseTo(300, 6);
  });

  it("refuses to divide a track too short to mean anything", () => {
    // Returning a number from a 3-metre track would be arithmetic, not
    // measurement.
    expect(paceSecondsPerKm({ distance_m: 3, duration_s: 2, rejected: 0 })).toBeNull();
  });

  it("returns null with no elapsed time", () => {
    expect(paceSecondsPerKm({ distance_m: 500, duration_s: 0, rejected: 0 })).toBeNull();
  });
});

describe("formatPace", () => {
  it("formats the way runners read it", () => {
    expect(formatPace(300)).toBe("5'00\"");
    expect(formatPace(272)).toBe("4'32\"");
  });

  it("pads the seconds", () => {
    expect(formatPace(305)).toBe("5'05\"");
  });

  it("carries a rounded 60 instead of printing 4'60\"", () => {
    expect(formatPace(299.7)).toBe("5'00\"");
  });
});
