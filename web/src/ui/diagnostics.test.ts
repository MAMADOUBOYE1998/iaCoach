import { describe, expect, it, vi } from "vitest";

import {
  captureConsole,
  compactLine,
  compactUserAgent,
  percentile,
  relevantLines,
  summarise,
} from "./diagnostics";

describe("percentile", () => {
  it("returns the median of an odd sample", () => {
    expect(percentile([3, 1, 2], 0.5)).toBe(2);
  });

  it("interpolates between neighbours", () => {
    expect(percentile([0, 10], 0.5)).toBe(5);
  });

  it("hits the ends exactly", () => {
    expect(percentile([1, 2, 3, 4], 0)).toBe(1);
    expect(percentile([1, 2, 3, 4], 1)).toBe(4);
  });

  it("is not fooled by an unsorted input", () => {
    expect(percentile([100, 1, 2, 3], 0.95)).toBeCloseTo(85.45, 1);
  });

  it("returns zero on no samples rather than NaN", () => {
    // A NaN would render as "NaN ms" in the report and read like a crash.
    expect(percentile([], 0.5)).toBe(0);
  });
});

describe("summarise", () => {
  it("reports the bad tail, not just the middle", () => {
    // One frame in ten stalls. The mean would read ~48 ms and sound acceptable;
    // p95 shows the stutter the athlete actually feels.
    const samples = [
      ...Array.from({ length: 90 }, () => ({ fps: 30, latencyMs: 20 })),
      ...Array.from({ length: 10 }, () => ({ fps: 3, latencyMs: 300 })),
    ];
    const summary = summarise(samples, 60);
    expect(summary.latencyP50).toBe(20);
    expect(summary.latencyP95).toBe(300);
    expect(summary.fpsP05).toBe(3);
    expect(summary.frames).toBe(100);
  });

  it("does not let a lone outlier dominate a small sample", () => {
    // 19 clean frames and one stall leaves p95 near the clean value, because
    // interpolation over 20 points cannot resolve a 5 % tail. That is correct,
    // and it is why the measurement runs 60 s: at 25 fps that is ~1500 frames,
    // where the 95th percentile means something. Reading p95 off a handful of
    // frames would be reporting noise as a tail.
    const samples = [
      ...Array.from({ length: 19 }, () => ({ fps: 30, latencyMs: 20 })),
      { fps: 3, latencyMs: 300 },
    ];
    expect(summarise(samples, 1).latencyP95).toBeLessThan(50);
  });
});

describe("captureConsole", () => {
  it("still calls the original console", () => {
    const original = console.info;
    const spy = vi.fn();
    console.info = spy;
    const lines = captureConsole();
    console.info("hello");
    expect(spy).toHaveBeenCalledWith("hello");
    expect(lines()).toContain("info: hello");
    console.info = original;
  });

  it("keeps only the last N lines", () => {
    const original = { log: console.log, info: console.info, warn: console.warn, error: console.error };
    const lines = captureConsole(3);
    for (let i = 0; i < 10; i += 1) console.log(`line ${i}`);
    const captured = lines();
    expect(captured).toHaveLength(3);
    expect(captured[2]).toBe("log: line 9");
    Object.assign(console, original);
  });

  it("does not throw on a circular object", () => {
    const original = console.log;
    const lines = captureConsole();
    const circular: Record<string, unknown> = {};
    circular["self"] = circular;
    expect(() => console.log(circular)).not.toThrow();
    expect(lines()).toHaveLength(1);
    console.log = original;
  });
});

describe("relevantLines", () => {
  it("keeps the GL context line and drops the noise", () => {
    const kept = relevantLines([
      "log: some unrelated chatter",
      "log: GL version: 3.0, renderer: Adreno (TM) 750",
      "info: another unrelated line",
    ]);
    expect(kept).toEqual(["log: GL version: 3.0, renderer: Adreno (TM) 750"]);
  });

  it("keeps failures", () => {
    expect(relevantLines(["error: model load failed"])).toHaveLength(1);
  });

  it("strips the glog prefix it passes through", () => {
    const [line] = relevantLines([
      "log: I0811 23:24:28.575000 2136208 gl_context.cc:407] GL version: 3.0, renderer: Adreno",
    ]);
    expect(line).toBe("log: GL version: 3.0, renderer: Adreno");
  });
});

describe("compactLine", () => {
  it("leaves an ordinary line alone", () => {
    expect(compactLine("info: Modèle embarqué")).toBe("info: Modèle embarqué");
  });
});

describe("compactUserAgent", () => {
  it("keeps the device model and the engine version", () => {
    // The device model is the single most important field in a benchmark row.
    expect(
      compactUserAgent(
        "Mozilla/5.0 (Linux; Android 16; SM-S942B) AppleWebKit/537.36 " +
          "(KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36",
      ),
    ).toBe("Linux; Android 16; SM-S942B · Chrome/141");
  });

  it("handles iOS, where the engine is reported differently", () => {
    expect(
      compactUserAgent(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 " +
          "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
      ),
    ).toBe("iPhone; CPU iPhone OS 18_0 like Mac OS X · Version/18");
  });

  it("degrades to the raw string rather than losing it", () => {
    expect(compactUserAgent("weird-agent")).toBe("weird-agent");
  });
});
