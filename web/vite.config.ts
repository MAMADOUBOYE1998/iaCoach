import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, type Plugin } from "vite";

const HERE = fileURLToPath(new URL(".", import.meta.url));

/**
 * The CDN fallback has to serve the WASM runtime matching the installed JS
 * wrapper. Hard-coding the version drifts silently the first time the package
 * is bumped — it already had: the source said 0.10.18 while npm had installed
 * 0.10.35 — and the resulting mismatch only shows up at runtime, on whichever
 * machine has no vendored copy.
 */
const tasksVisionVersion: string = JSON.parse(
  readFileSync(resolve(HERE, "node_modules/@mediapipe/tasks-vision/package.json"), "utf8"),
).version;

/**
 * Emits `asset-manifest.json`: the hashed JS and CSS of this build, for the
 * service worker to precache. Generated rather than hand-maintained — a list of
 * content-hashed filenames is wrong the moment anything is edited.
 */
function assetManifest(): Plugin {
  let base = "/";
  return {
    name: "iacoach-asset-manifest",
    configResolved(config) {
      base = config.base;
    },
    generateBundle(_options, bundle) {
      const files = Object.keys(bundle)
        .filter((name) => name.startsWith("assets/") && /\.(js|css)$/.test(name))
        .map((name) => `${base}${name}`)
        .sort();
      this.emitFile({
        type: "asset",
        fileName: "asset-manifest.json",
        source: `${JSON.stringify(files, null, 2)}\n`,
      });
    },
  };
}

export default defineConfig({
  // `/` locally, `/iaCoach/` when GitHub Pages serves it from a repository
  // sub-path. Everything that builds a URL — the worker's scope, the vendored
  // asset paths, the precache list — derives from this rather than assuming the
  // root, because on Pages the root belongs to another site entirely.
  base: process.env["BASE_PATH"] ?? "/",
  plugins: [assetManifest()],
  define: {
    __TASKS_VISION_VERSION__: JSON.stringify(tasksVisionVersion),
  },
  server: {
    // getUserMedia requires a secure context. localhost counts as secure, so
    // plain http is fine for desktop dev; testing on a phone over the LAN needs
    // HTTPS (see docs/PHONE_TESTING.md).
    host: true,
    port: 5173,
  },
  build: {
    target: "es2022",
    sourcemap: true,
    rollupOptions: {
      // The worker is a second entry rather than a hand-written file in
      // `public/`: it shares `pwa/policy.ts` with the unit tests, so the rules
      // that are tested are literally the rules that ship.
      input: {
        main: resolve(HERE, "index.html"),
        sw: resolve(HERE, "src/sw.ts"),
      },
      output: {
        // A worker only controls pages at or below its own path, so `/sw.js` at
        // the root is the difference between caching the whole app and caching
        // nothing. Everything else keeps the hashed default.
        entryFileNames: (chunk) => (chunk.name === "sw" ? "sw.js" : "assets/[name]-[hash].js"),
        // Keeping the worker's dependencies inlined keeps it a single classic
        // script — `npm run check:sw` fails the build if that stops holding.
        inlineDynamicImports: false,
      },
    },
  },
});
