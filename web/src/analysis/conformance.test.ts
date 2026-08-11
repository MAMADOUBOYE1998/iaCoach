/**
 * Fixture conformance — the TypeScript half.
 *
 * `backend/tests/test_conformance.py` is the other half and reads the same
 * files. The two must agree; that is the only thing standing between the
 * on-device and server-side analyses and a silent divergence.
 *
 * Each scenario is checked twice: against the hand-authored expectation in the
 * sequence file (semantics), and against the golden `RepEvent` stream produced
 * by the Python implementation (exact behaviour, cross-language).
 */

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import type { Exercise, ExerciseCalibration, RepEvent } from "../types/contracts";
import { analyseSequence, type FrameSample } from "./counting";

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, "..", "..", "..", "fixtures");
const SEQUENCES = join(FIXTURES, "sequences");
const GOLDEN = join(FIXTURES, "golden");

interface Fixture {
  name: string;
  description: string;
  exercise: Exercise;
  calibration: ExerciseCalibration;
  expected: { events: number; counted: number; flags: string[][] };
  frames: FrameSample[];
}

const read = <T,>(path: string): T => JSON.parse(readFileSync(path, "utf-8")) as T;

const files = readdirSync(SEQUENCES)
  .filter((f: string) => f.endsWith(".json"))
  .sort();

/**
 * Both implementations run the same IEEE-754 double operations in the same
 * order, so exact equality is expected. The epsilon guards against a JSON
 * round-trip artefact rather than a behavioural difference — anything larger
 * than this is real drift and should fail.
 */
const EPSILON = 1e-9;

function expectDeepClose(actual: unknown, expected: unknown, path: string): void {
  if (typeof expected === "number") {
    expect(typeof actual, `${path}: expected a number`).toBe("number");
    expect(Math.abs((actual as number) - expected), `${path} drifted`).toBeLessThan(
      EPSILON,
    );
    return;
  }
  if (Array.isArray(expected)) {
    expect(Array.isArray(actual), `${path}: expected an array`).toBe(true);
    const got = actual as unknown[];
    expect(got.length, `${path}: length`).toBe(expected.length);
    expected.forEach((value, i) => expectDeepClose(got[i], value, `${path}[${i}]`));
    return;
  }
  if (expected !== null && typeof expected === "object") {
    const got = actual as Record<string, unknown>;
    const want = expected as Record<string, unknown>;
    expect(Object.keys(got).sort(), `${path}: keys`).toEqual(Object.keys(want).sort());
    for (const key of Object.keys(want)) {
      expectDeepClose(got[key], want[key], `${path}.${key}`);
    }
    return;
  }
  expect(actual, path).toBe(expected);
}

describe("fixture conformance", () => {
  it("finds the fixtures", () => {
    // Guard against the suite below silently iterating an empty list.
    expect(files.length).toBeGreaterThanOrEqual(8);
  });

  for (const file of files) {
    describe(file.replace(/\.json$/, ""), () => {
      const fixture = read<Fixture>(join(SEQUENCES, file));
      const golden = read<RepEvent[]>(join(GOLDEN, file));
      const events = analyseSequence(
        fixture.exercise,
        fixture.calibration,
        fixture.frames,
      );

      it("matches the hand-authored expectation", () => {
        expect(events.length, fixture.description).toBe(fixture.expected.events);
        expect(events.filter((e) => e.counted).length).toBe(fixture.expected.counted);
        expect(events.map((e) => e.flags)).toEqual(fixture.expected.flags);
      });

      it("matches the golden stream from the Python implementation", () => {
        expectDeepClose(events, golden, file);
      });
    });
  }
});
