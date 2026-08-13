/**
 * Classification conformance — the TypeScript half.
 *
 * `backend/tests/test_classify_conformance.py` is the other half and reads the
 * same files. The label decides which corrections an athlete is given, so a
 * divergence between the phone and the server would produce different coaching
 * from the same movement, with nothing to say why.
 *
 * The refusal fixtures matter as much as the positive ones: `rowing` and
 * `dead_hang` are the shapes that produced invented reps before this stage
 * existed, and they must stay `unknown` on both sides.
 */

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { classifyWindow, frameFeatures, windowFeatures } from "./classify";
import type { FrameFeatures, WindowFeatures } from "./classify";
import type { Landmark } from "../pose/landmarker";

const HERE = dirname(fileURLToPath(import.meta.url));
const CLASSIFY = join(HERE, "..", "..", "..", "fixtures", "classify");

interface ClassifyFixture {
  name: string;
  description: string;
  landmark_count: number;
  pad: Landmark;
  frames: { t_ms: number; landmarks: Record<string, Landmark> }[];
  expected_frames: FrameFeatures[];
  expected_window: WindowFeatures;
  expected: {
    exercise: string;
    confidence: number;
    reason: string;
    scores: Record<string, number>;
  };
}

const files = readdirSync(CLASSIFY)
  .filter((f: string) => f.endsWith(".json"))
  .sort();

describe("classification fixtures", () => {
  it("finds the fixtures", () => {
    expect(files.length).toBeGreaterThan(0);
  });
});

for (const file of files) {
  const fixture = JSON.parse(readFileSync(join(CLASSIFY, file), "utf-8")) as ClassifyFixture;

  describe(`classify ${fixture.name}`, () => {
    const features: FrameFeatures[] = [];

    it("reproduces every frame's features", () => {
      for (const [i, frame] of fixture.frames.entries()) {
        // Only the read landmarks are stored; the rest is inert padding that
        // nothing indexes, rebuilt here so the frame is complete.
        const landmarks: Landmark[] = Array.from({ length: fixture.landmark_count }, () => ({
          ...fixture.pad,
        }));
        for (const [index, lm] of Object.entries(frame.landmarks)) {
          landmarks[Number(index)] = lm;
        }
        const found = frameFeatures(landmarks, landmarks, frame.t_ms);
        expect(found).not.toBeNull();
        const expected = fixture.expected_frames[i]!;
        for (const key of Object.keys(expected) as (keyof FrameFeatures)[]) {
          expect(found![key]).toBeCloseTo(expected[key], 9);
        }
        features.push(found!);
      }
    });

    it("reproduces the window features", () => {
      const window = windowFeatures(features);
      for (const key of Object.keys(fixture.expected_window) as (keyof WindowFeatures)[]) {
        expect(window[key]).toBeCloseTo(fixture.expected_window[key], 9);
      }
    });

    it(`classifies it as ${fixture.expected.exercise}`, () => {
      const verdict = classifyWindow(windowFeatures(features));
      expect(verdict.exercise).toBe(fixture.expected.exercise);
      expect(verdict.confidence).toBeCloseTo(fixture.expected.confidence, 9);
      expect(verdict.reason).toBe(fixture.expected.reason);
    });
  });
}
