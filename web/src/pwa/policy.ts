/**
 * Service worker caching policy, as a pure function.
 *
 * The worker itself is untestable in a unit test (it needs a real
 * `ServiceWorkerGlobalScope`), so the decision it makes lives here and the
 * worker is reduced to plumbing. Getting this wrong is not a performance bug:
 * caching the wrong response serves an athlete last week's debrief as if it
 * described today's session.
 *
 * Three routes:
 *
 *  - `cache-first` — immutable bytes. Hashed build assets, the vendored model
 *    and WASM runtime, icons. Fetched once, then free and offline-capable.
 *  - `network-first` — the app shell. Fresh when there is a network, cached
 *    copy when there is not.
 *  - `network-only` — everything else, and every non-GET. The worker does not
 *    intercept these at all.
 *
 * Every path is relative to a **base**: the app is served from `/` locally and
 * from `/iaCoach/` on GitHub Pages, and a worker that only knows about `/` would
 * cache nothing there while reporting success.
 */

export const CACHE_NAME = "iacoach-v1";

/** Cached on install so the shell exists before the first offline visit. */
export function precacheUrls(base: string): string[] {
  return [base, `${base}manifest.webmanifest`];
}

/**
 * Written by the build; lists the hashed JS and CSS of this exact bundle.
 *
 * Needed because on a first visit the page loads those files before this worker
 * controls anything, so on-demand caching alone would only catch them from the
 * *second* visit on — "works offline" would quietly mean "works offline from the
 * third visit". The worker fetches this list on install instead.
 */
export function assetManifestUrl(base: string): string {
  return `${base}asset-manifest.json`;
}

export type CacheStrategy = "cache-first" | "network-first" | "network-only";

export interface RoutedRequest {
  url: string;
  method: string;
  /** `Request.mode`; "navigate" marks a document load. */
  mode?: string;
}

/** Sub-paths holding content-addressed or immutable bytes. */
const IMMUTABLE = ["assets/", "models/", "vendor/", "icons/"];

/**
 * Backend routes, listed even though the API normally lives on another origin.
 *
 * If the API is ever deployed behind the same origin, the cross-origin rule
 * stops protecting it and this list is what keeps session history, progress and
 * debriefs from being served stale. Offline session handling is the sync
 * queue's job (`session/sync.ts`), and it is deliberately not the cache's.
 */
const API = ["sessions", "athletes", "coach", "health"];

export function strategyFor(
  request: RoutedRequest,
  origin: string,
  base = "/",
): CacheStrategy {
  if (request.method !== "GET") return "network-only";

  let url: URL;
  try {
    url = new URL(request.url, origin);
  } catch {
    return "network-only";
  }

  // The CDN fallback for the model is deliberately not cached: an opaque
  // cross-origin response cannot be validated, and vendoring is the supported
  // way to be offline-capable. Caching it would half-work and hide the gap.
  if (url.origin !== origin) return "network-only";

  // Outside our own base is someone else's app on the same host.
  if (!url.pathname.startsWith(base)) return "network-only";
  const path = url.pathname.slice(base.length);

  if (API.some((prefix) => path.startsWith(prefix))) return "network-only";

  if (IMMUTABLE.some((prefix) => path.startsWith(prefix))) return "cache-first";

  if (request.mode === "navigate") return "network-first";

  if (path === "manifest.webmanifest") return "network-first";

  return "network-only";
}
