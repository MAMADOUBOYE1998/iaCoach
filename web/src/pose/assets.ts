/**
 * Where the pose runtime and model are loaded from.
 *
 * Vendored copies under `public/` are preferred; the CDN is the fallback for a
 * checkout where `npm run vendor-assets` has not been run. The resolution is
 * done at startup rather than baked in at build time so a single bundle behaves
 * correctly either way.
 *
 * Two rules, both deliberate:
 *
 *  - **All or nothing.** A local model with a CDN runtime is still a bundle
 *    that fails without network, so a half-vendored install resolves to `cdn`.
 *    Reporting `local` there would be a lie the athlete only discovers offline.
 *  - **The source is surfaced in the UI.** "Works offline" is a promise this app
 *    makes; whether it currently holds is a fact the athlete can check before
 *    walking into a basement gym, not after.
 */

/**
 * Injected at build time from the installed `@mediapipe/tasks-vision` version
 * (see `vite.config.ts`). Written by hand it drifts from the JS wrapper the
 * first time the package is bumped, and the mismatch only surfaces at runtime
 * on a machine with no vendored copy.
 */
declare const __TASKS_VISION_VERSION__: string;

export const LOCAL_WASM_BASE = "/vendor/tasks-vision";
export const LOCAL_MODEL_URL = "/models/pose_landmarker_full.task";

export const CDN_WASM_BASE = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${__TASKS_VISION_VERSION__}/wasm`;
export const CDN_MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker" +
  "/pose_landmarker_full/float16/1/pose_landmarker_full.task";

/** One of the WASM files; its presence stands for the whole vendored runtime. */
const WASM_PROBE = `${LOCAL_WASM_BASE}/vision_wasm_internal.wasm`;

export interface PoseAssets {
  wasmBase: string;
  modelUrl: string;
  source: "local" | "cdn";
}

/**
 * Is this asset actually served from our own origin?
 *
 * The content-type check is load-bearing: a dev server with an SPA fallback
 * answers a missing path with `200 text/html` (the index page), so `response.ok`
 * alone would report a model that does not exist as vendored, and MediaPipe
 * would then fail on an HTML page it was told is a model.
 */
async function isVendored(url: string, fetchImpl: typeof fetch): Promise<boolean> {
  try {
    const response = await fetchImpl(url, { method: "HEAD" });
    if (!response.ok) return false;
    return !(response.headers.get("content-type") ?? "").startsWith("text/html");
  } catch {
    return false;
  }
}

export async function resolveAssets(fetchImpl: typeof fetch = fetch): Promise<PoseAssets> {
  const [model, wasm] = await Promise.all([
    isVendored(LOCAL_MODEL_URL, fetchImpl),
    isVendored(WASM_PROBE, fetchImpl),
  ]);

  if (model && wasm) {
    return { wasmBase: LOCAL_WASM_BASE, modelUrl: LOCAL_MODEL_URL, source: "local" };
  }
  return { wasmBase: CDN_WASM_BASE, modelUrl: CDN_MODEL_URL, source: "cdn" };
}

/** Short French line for the status bar. */
export function assetsLabel(assets: PoseAssets): string {
  return assets.source === "local"
    ? "Modèle embarqué : la séance fonctionne sans réseau."
    : "Modèle chargé depuis le CDN : une séance hors-ligne échouera au démarrage.";
}
