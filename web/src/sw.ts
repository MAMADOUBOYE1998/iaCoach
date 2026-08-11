/**
 * Service worker: app-shell and asset caching.
 *
 * All routing decisions live in `pwa/policy.ts`, which is unit-tested; this file
 * is the plumbing that carries them out. It is built as a separate rollup entry
 * so it lands at `/sw.js`, at the root scope a worker needs.
 *
 * Scope of the promise: after one online visit, the shell, the hashed build
 * assets and the vendored model are cached, and a subsequent visit works with
 * no network at all. Before that first visit nothing is cached — a worker
 * cannot pre-fetch bytes it has never seen. Training data is never cached; a
 * session finished offline is held by the sync queue and sent later.
 */

import { ASSET_MANIFEST, CACHE_NAME, PRECACHE, strategyFor } from "./pwa/policy";

// The DOM lib is what the rest of the app compiles against, and pulling in the
// WebWorker lib alongside it collides on the shared globals. The handful of
// worker-only members actually used are declared here instead.
interface ExtendableEventLike extends Event {
  waitUntil(promise: Promise<unknown>): void;
}

interface FetchEventLike extends ExtendableEventLike {
  request: Request;
  respondWith(response: Response | Promise<Response>): void;
}

interface WorkerScope {
  location: Location;
  skipWaiting(): Promise<void>;
  clients: { claim(): Promise<void> };
  addEventListener(type: "install" | "activate", listener: (event: ExtendableEventLike) => void): void;
  addEventListener(type: "fetch", listener: (event: FetchEventLike) => void): void;
}

const worker = self as unknown as WorkerScope;

/** Only a fresh, non-opaque, same-origin 200 is worth storing. */
function isCacheable(response: Response): boolean {
  return response.status === 200 && response.type === "basic";
}

async function cacheFirst(request: Request): Promise<Response> {
  const cache = await caches.open(CACHE_NAME);
  const hit = await cache.match(request);
  if (hit) return hit;

  const response = await fetch(request);
  if (isCacheable(response)) await cache.put(request, response.clone());
  return response;
}

async function networkFirst(request: Request): Promise<Response> {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request);
    if (isCacheable(response)) await cache.put(request, response.clone());
    return response;
  } catch (error) {
    const hit = (await cache.match(request)) ?? (await cache.match("/"));
    if (hit) return hit;
    throw error;
  }
}

/**
 * Cache the shell and this build's hashed assets.
 *
 * The 20 MB of model and WASM runtime are deliberately *not* precached: forcing
 * that download at install time, possibly on mobile data, to serve an offline
 * session that may never happen is not a trade the athlete agreed to. They are
 * cached on first use instead, which is the moment their cost is justified.
 */
async function precache(): Promise<void> {
  const cache = await caches.open(CACHE_NAME);
  await cache.addAll([...PRECACHE]);

  try {
    const response = await fetch(ASSET_MANIFEST, { cache: "no-cache" });
    if (!response.ok) return;
    const listed: unknown = await response.json();
    if (!Array.isArray(listed)) return;
    await cache.addAll(listed.filter((file): file is string => typeof file === "string"));
  } catch {
    // No manifest (dev server) or a failed install fetch: the shell alone is
    // still worth having, and the assets fall back to on-demand caching.
  }
}

worker.addEventListener("install", (event) => {
  // Take over immediately: the alternative is an athlete on a stale worker
  // until every tab is closed, which on a phone is approximately never.
  event.waitUntil(precache().then(() => worker.skipWaiting()));
});

worker.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name))),
      )
      .then(() => worker.clients.claim()),
  );
});

worker.addEventListener("fetch", (event) => {
  const strategy = strategyFor(
    { url: event.request.url, method: event.request.method, mode: event.request.mode },
    worker.location.origin,
  );
  // `network-only` is handled by not responding at all: the browser performs the
  // request exactly as it would with no worker installed.
  if (strategy === "cache-first") event.respondWith(cacheFirst(event.request));
  else if (strategy === "network-first") event.respondWith(networkFirst(event.request));
});
