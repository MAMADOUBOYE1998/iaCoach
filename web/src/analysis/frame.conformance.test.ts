/**
 * Landmark-level conformance — the TypeScript half.
 *
 * `fixtures/landmarks/` is produced by `iacoach.frame` and replayed here. It
 * locks the stage *before* the counter: the elbow angles, the trunk lean and
 * the hip speed that every downstream score is computed from.
 *
 * Why this matters more than it looks: the phone runs this sampler live, and
 * the offline evaluation runs the Python one over recorded video. If the two
 * drift, an accuracy figure measured on a dataset stops describing what the
 * athlete's phone actually does — and nothing would say so.
 */

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { FrameSampler } from "./frame";
import type { FrameSample } from "./counting";
import type { Landmark } from "../pose/landmarker";

const HERE = dirname(fileURLToPath(import.meta.url));
const LANDMARKS = join(HERE, "..", "..", "..", "fixtures", "landmarks");

interface LandmarkFixture {
  name: string;
  description: string;
  fps: number;
  frames: { t_ms: number; world: Landmark[]; normalized: Landmark[] }[];
  expected: FrameSample[];
}

const files = readdirSync(LANDMARKS)
  .filter((f: string) => f.endsWith(".json"))
  .sort();

describe("landmark fixtures", () => {
  it("finds the fixtures", () => {
    expect(files.length).toBeGreaterThan(0);
  });
});

for (const file of files) {
  const fixture = JSON.parse(
    readFileSync(join(LANDMARKS, file), "utf-8"),
  ) as LandmarkFixture;

  describe(`${fixture.name}: ${fixture.description}`, () => {
    const sampler = new FrameSampler();
    const produced = fixture.frames.map((frame) =>
      sampler.sample(frame.world, frame.normalized, frame.t_ms),
    );

    it("produces a sample for every frame", () => {
      expect(produced.every((sample) => sample !== null)).toBe(true);
      expect(produced).toHaveLength(fixture.expected.length);
    });

    it("matches the Python sampler", () => {
      produced.forEach((sample, index) => {
        const expected = fixture.expected[index];
        expect(sample).not.toBeNull();
        expect(expected).toBeDefined();
        for (const key of [
          "t_ms",
          "elbow_left_deg",
          "elbow_right_deg",
          "trunk_deg",
          "hip_speed",
          "confidence",
        ] as const) {
          // 1e-9: the two languages both use IEEE 754 doubles, so anything
          // looser would hide a real divergence rather than absorb rounding.
          expect(
            Math.abs(sample![key] - expected![key]),
            `${fixture.name} frame ${index} ${key}: ${sample![key]} vs ${expected![key]}`,
          ).toBeLessThan(1e-9);
        }
      });
    });
  });
}
