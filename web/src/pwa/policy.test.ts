import { describe, expect, it } from "vitest";

import { strategyFor, type RoutedRequest } from "./policy";

const ORIGIN = "https://coach.local";

function get(url: string, mode?: string): RoutedRequest {
  return mode === undefined ? { url, method: "GET" } : { url, method: "GET", mode };
}

describe("strategyFor", () => {
  it("serves hashed build assets from the cache", () => {
    expect(strategyFor(get(`${ORIGIN}/assets/index-a1b2c3.js`), ORIGIN)).toBe("cache-first");
    expect(strategyFor(get(`${ORIGIN}/assets/index-a1b2c3.css`), ORIGIN)).toBe("cache-first");
  });

  it("serves the vendored model and runtime from the cache", () => {
    // The whole point of vendoring: these are the bytes that make an offline
    // session possible, and re-downloading 44 MB per visit is not an option.
    expect(strategyFor(get(`${ORIGIN}/models/pose_landmarker_full.task`), ORIGIN)).toBe(
      "cache-first",
    );
    expect(strategyFor(get(`${ORIGIN}/vendor/tasks-vision/vision_wasm_internal.wasm`), ORIGIN)).toBe(
      "cache-first",
    );
  });

  it("serves the shell network-first", () => {
    expect(strategyFor(get(`${ORIGIN}/`, "navigate"), ORIGIN)).toBe("network-first");
    expect(strategyFor(get(`${ORIGIN}/manifest.webmanifest`), ORIGIN)).toBe("network-first");
  });

  it("never caches a write", () => {
    expect(strategyFor({ url: `${ORIGIN}/sessions`, method: "POST" }, ORIGIN)).toBe("network-only");
    expect(strategyFor({ url: `${ORIGIN}/assets/x.js`, method: "POST" }, ORIGIN)).toBe(
      "network-only",
    );
  });

  it("never caches backend reads", () => {
    // A cached debrief or progress series would present stale training data as
    // current — worse than showing nothing.
    for (const path of ["/sessions/s1", "/athletes/a1/progress", "/coach/debrief", "/health"]) {
      expect(strategyFor(get(`${ORIGIN}${path}`), ORIGIN)).toBe("network-only");
    }
  });

  it("never caches another origin", () => {
    expect(strategyFor(get("https://api.example.com/sessions"), ORIGIN)).toBe("network-only");
    expect(strategyFor(get("https://cdn.jsdelivr.net/npm/x/wasm/y.wasm"), ORIGIN)).toBe(
      "network-only",
    );
  });

  it("leaves unknown same-origin paths alone", () => {
    // Default deny: a route nobody thought about is passed straight through
    // rather than silently cached.
    expect(strategyFor(get(`${ORIGIN}/whatever`), ORIGIN)).toBe("network-only");
  });

  it("does not throw on a malformed url", () => {
    expect(strategyFor({ url: "http://[::1", method: "GET" }, ORIGIN)).toBe("network-only");
  });
});
