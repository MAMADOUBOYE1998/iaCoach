import { describe, expect, it } from "vitest";

import {
  CDN_MODEL_URL,
  LOCAL_MODEL_URL,
  LOCAL_WASM_BASE,
  assetsLabel,
  resolveAssets,
} from "./assets";

type Reply = { status: number; contentType: string };

/** A fetch stand-in driven by a path → reply table. Anything unlisted is a 404. */
function fakeFetch(table: Record<string, Reply>): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    const url = String(input);
    const reply = table[url] ?? { status: 404, contentType: "text/plain" };
    return {
      ok: reply.status >= 200 && reply.status < 300,
      status: reply.status,
      headers: { get: (name: string) => (name === "content-type" ? reply.contentType : null) },
    } as unknown as Response;
  }) as typeof fetch;
}

const OK_BINARY = { status: 200, contentType: "application/octet-stream" };
const SPA_FALLBACK = { status: 200, contentType: "text/html; charset=utf-8" };

describe("resolveAssets", () => {
  it("prefers vendored assets when both are present", async () => {
    const assets = await resolveAssets(
      fakeFetch({
        [LOCAL_MODEL_URL]: OK_BINARY,
        [`${LOCAL_WASM_BASE}/vision_wasm_internal.wasm`]: OK_BINARY,
      }),
    );
    expect(assets.source).toBe("local");
    expect(assets.modelUrl).toBe(LOCAL_MODEL_URL);
    expect(assets.wasmBase).toBe(LOCAL_WASM_BASE);
  });

  it("falls back to the CDN when nothing is vendored", async () => {
    const assets = await resolveAssets(fakeFetch({}));
    expect(assets.source).toBe("cdn");
    expect(assets.modelUrl).toBe(CDN_MODEL_URL);
  });

  it("falls back to the CDN when only the model is vendored", async () => {
    // Half-vendored is not offline-capable: the runtime still needs network.
    const assets = await resolveAssets(fakeFetch({ [LOCAL_MODEL_URL]: OK_BINARY }));
    expect(assets.source).toBe("cdn");
  });

  it("falls back to the CDN when only the runtime is vendored", async () => {
    const assets = await resolveAssets(
      fakeFetch({ [`${LOCAL_WASM_BASE}/vision_wasm_internal.wasm`]: OK_BINARY }),
    );
    expect(assets.source).toBe("cdn");
  });

  it("is not fooled by an SPA fallback answering 200 with HTML", async () => {
    // The failure this prevents: MediaPipe being handed index.html as a model.
    const assets = await resolveAssets(
      fakeFetch({
        [LOCAL_MODEL_URL]: SPA_FALLBACK,
        [`${LOCAL_WASM_BASE}/vision_wasm_internal.wasm`]: SPA_FALLBACK,
      }),
    );
    expect(assets.source).toBe("cdn");
  });

  it("falls back to the CDN when the probe itself throws", async () => {
    const throwing = (() => Promise.reject(new TypeError("offline"))) as unknown as typeof fetch;
    const assets = await resolveAssets(throwing);
    expect(assets.source).toBe("cdn");
  });
});

describe("assetsLabel", () => {
  it("says plainly that a CDN load will not survive going offline", async () => {
    const cdn = assetsLabel(await resolveAssets(fakeFetch({})));
    expect(cdn).toContain("hors-ligne");
  });
});
