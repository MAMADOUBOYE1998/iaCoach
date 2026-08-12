import { describe, expect, it } from "vitest";

import {
  DEFAULT_VARIANT,
  LOCAL_WASM_BASE,
  assetsLabel,
  cdnModelUrl,
  localModelUrl,
  modelVariant,
  resolveAssets,
} from "./assets";

const LOCAL_MODEL_URL = localModelUrl(DEFAULT_VARIANT);
const CDN_MODEL_URL = cdnModelUrl(DEFAULT_VARIANT);

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
      DEFAULT_VARIANT,
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
    const assets = await resolveAssets(DEFAULT_VARIANT, fakeFetch({}));
    expect(assets.source).toBe("cdn");
    expect(assets.modelUrl).toBe(CDN_MODEL_URL);
  });

  it("falls back to the CDN when only the model is vendored", async () => {
    // Half-vendored is not offline-capable: the runtime still needs network.
    const assets = await resolveAssets(DEFAULT_VARIANT, fakeFetch({ [LOCAL_MODEL_URL]: OK_BINARY }));
    expect(assets.source).toBe("cdn");
  });

  it("falls back to the CDN when only the runtime is vendored", async () => {
    const assets = await resolveAssets(
      DEFAULT_VARIANT,
      fakeFetch({ [`${LOCAL_WASM_BASE}/vision_wasm_internal.wasm`]: OK_BINARY }),
    );
    expect(assets.source).toBe("cdn");
  });

  it("is not fooled by an SPA fallback answering 200 with HTML", async () => {
    // The failure this prevents: MediaPipe being handed index.html as a model.
    const assets = await resolveAssets(
      DEFAULT_VARIANT,
      fakeFetch({
        [LOCAL_MODEL_URL]: SPA_FALLBACK,
        [`${LOCAL_WASM_BASE}/vision_wasm_internal.wasm`]: SPA_FALLBACK,
      }),
    );
    expect(assets.source).toBe("cdn");
  });

  it("falls back to the CDN when the probe itself throws", async () => {
    const throwing = (() => Promise.reject(new TypeError("offline"))) as unknown as typeof fetch;
    const assets = await resolveAssets(DEFAULT_VARIANT, throwing);
    expect(assets.source).toBe("cdn");
  });
});

describe("modelVariant", () => {
  it("defaults when nothing is asked for", () => {
    expect(modelVariant("")).toBe(DEFAULT_VARIANT);
    expect(modelVariant("?other=1")).toBe(DEFAULT_VARIANT);
  });

  it("reads the requested variant", () => {
    expect(modelVariant("?model=lite")).toBe("lite");
    expect(modelVariant("?model=heavy")).toBe("heavy");
  });

  it("ignores a value it does not know", () => {
    // A typo must not send MediaPipe after a URL that does not exist.
    expect(modelVariant("?model=turbo")).toBe(DEFAULT_VARIANT);
  });
});

describe("model urls", () => {
  it("points each variant at its own file", () => {
    expect(localModelUrl("lite")).toContain("pose_landmarker_lite.task");
    expect(cdnModelUrl("lite")).toContain("/pose_landmarker_lite/float16/1/");
  });

  it("goes to the CDN for the variant that is not vendored", async () => {
    // `heavy` is 29 MB; shipping it to make a comparison point available
    // offline would cost every athlete for a measurement run by nobody.
    const assets = await resolveAssets(
      "heavy",
      fakeFetch({
        [localModelUrl("heavy")]: OK_BINARY,
        [`${LOCAL_WASM_BASE}/vision_wasm_internal.wasm`]: OK_BINARY,
      }),
    );
    expect(assets.source).toBe("cdn");
    expect(assets.modelUrl).toBe(cdnModelUrl("heavy"));
  });
});

describe("assetsLabel", () => {
  it("says plainly that a CDN load will not survive going offline", async () => {
    const cdn = assetsLabel(await resolveAssets(DEFAULT_VARIANT, fakeFetch({})));
    expect(cdn).toContain("hors-ligne");
  });
});
