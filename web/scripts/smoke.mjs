/**
 * End-to-end smoke test of a production build.
 *
 * Answers four questions no unit test can:
 *
 *   1. does the service worker install and cache what the policy says it should;
 *   2. does a **second visit with the network cut** still load the app;
 *   3. are the vendored assets actually the ones fetched (no CDN origin touched);
 *   4. does the pose pipeline run end to end, model included.
 *
 * It is **not** a benchmark. The fps and latency it prints come from whatever
 * machine it runs on, and on a headless CI box that is a software rasteriser —
 * roughly two orders of magnitude off a phone GPU. The performance targets are
 * measured on a real device, per `docs/PHONE_TESTING.md`.
 *
 * Not wired into CI: it needs a Chromium and Playwright, which the repo does not
 * depend on. Run it by hand:
 *
 *   npm run build && npm run vendor-assets
 *   npx vite preview --port 4173 &
 *   npx --yes playwright@1 node scripts/smoke.mjs        # or: node scripts/smoke.mjs
 *
 * A camera is faked by Chromium (`--use-fake-device-for-media-stream`), so the
 * frames contain a test pattern and no pose is ever found. That is expected:
 * detection quality is what the fixtures cover.
 */

import { chromium } from "playwright";

const BASE = process.env.SMOKE_URL ?? "http://127.0.0.1:4173/";
const SAMPLES = 6;
const SAMPLE_INTERVAL_MS = 2000;

const failures = [];
/** @param {boolean} ok @param {string} what */
function check(ok, what) {
  console.log(`${ok ? "ok  " : "FAIL"}  ${what}`);
  if (!ok) failures.push(what);
}

const launchOptions = { args: [
  "--use-fake-ui-for-media-stream",
  "--use-fake-device-for-media-stream",
  // Headless boxes have no GPU; without this MediaPipe cannot get a WebGL
  // context at all and the run fails for a reason unrelated to the app.
  "--enable-unsafe-swiftshader",
] };
if (process.env.CHROMIUM_PATH) launchOptions.executablePath = process.env.CHROMIUM_PATH;

const browser = await chromium.launch(launchOptions);
const context = await browser.newContext({ permissions: ["camera"] });
const page = await context.newPage();

/** @type {string[]} */
const requested = [];
page.on("request", (r) => requested.push(r.url()));
page.on("pageerror", (e) => console.log(`  [pageerror] ${e.message}`));

await page.goto(BASE, { waitUntil: "load" });

const registration = await page.evaluate(async () => {
  const reg = await navigator.serviceWorker.ready;
  return { scope: reg.scope, state: reg.active?.state ?? null };
});
check(registration.scope === BASE, `service worker controls the root scope (${registration.scope})`);

const startedAt = Date.now();
await page.click("#start");
await page.waitForFunction(() => (document.getElementById("fps")?.textContent ?? "—") !== "—", {
  timeout: 120_000,
});
console.log(`\nfirst frame after ${((Date.now() - startedAt) / 1000).toFixed(1)} s`);

for (let i = 0; i < SAMPLES; i += 1) {
  await page.waitForTimeout(SAMPLE_INTERVAL_MS);
  const [fps, latency] = await page.evaluate(() => [
    document.getElementById("fps")?.textContent,
    document.getElementById("latency")?.textContent,
  ]);
  console.log(`  t+${(i + 1) * (SAMPLE_INTERVAL_MS / 1000)}s  fps=${fps}  ms/frame=${latency}`);
}
console.log("  (this machine, not a phone — see the header of this file)\n");

const origin = new URL(BASE).origin;
const foreign = [...new Set(requested.map((u) => new URL(u).origin))].filter(
  // The API origin is expected and unrelated to asset loading.
  (o) => o !== origin && !o.includes("localhost:8000"),
);
check(foreign.length === 0, `no third-party origin fetched${foreign.length ? `: ${foreign}` : ""}`);
check(
  requested.some((u) => u.startsWith(`${origin}/models/`)),
  "pose model served from our own origin",
);
check(
  requested.some((u) => u.startsWith(`${origin}/vendor/tasks-vision/`)),
  "WASM runtime served from our own origin",
);

const cached = await page.evaluate(async () => {
  const names = await caches.keys();
  const keys = await (await caches.open(names[0])).keys();
  return { names, paths: keys.map((r) => new URL(r.url).pathname) };
});
console.log(`\ncache ${cached.names.join(", ")}:`);
for (const path of cached.paths) console.log(`  ${path}`);
check(cached.names.length === 1, "exactly one cache version is live");
check(cached.paths.includes("/"), "app shell cached");
check(
  cached.paths.some((p) => p.startsWith("/assets/") && p.endsWith(".js")),
  "hashed build assets cached on install",
);
check(
  cached.paths.some((p) => p.endsWith(".task")),
  "pose model cached",
);
check(
  cached.paths.every((p) => !p.startsWith("/sessions") && !p.startsWith("/athletes")),
  "no training data cached",
);

// The claim itself: cut the network, open the app again.
await context.setOffline(true);
const offline = await context.newPage();
const errors = [];
offline.on("pageerror", (e) => errors.push(e.message));
const response = await offline.goto(BASE, { waitUntil: "load" }).catch(() => null);
check(response !== null, "app loads with the network cut");
// Not `#start` — that button is static HTML and stays visible even when the
// bundle failed to load. `#progress` is empty in index.html and only ever
// filled by the app, so its content is proof the JS actually ran.
const ranOffline =
  response !== null &&
  (await offline
    .waitForFunction(() => (document.getElementById("progress")?.childElementCount ?? 0) > 0, {
      timeout: 10_000,
    })
    .then(() => true)
    .catch(() => false));
check(ranOffline, "the app bundle executes offline, not just the shell HTML");
check(errors.length === 0, `no page error offline${errors.length ? `: ${errors[0]}` : ""}`);

await browser.close();

console.log(`\n${failures.length === 0 ? "All checks passed." : `${failures.length} FAILED.`}`);
process.exit(failures.length === 0 ? 0 : 1);
