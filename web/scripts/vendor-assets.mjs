/**
 * Vendors the MediaPipe runtime and pose model into `public/`.
 *
 * Offline-first is a product requirement, not a nicety: counting and form
 * scoring have to work in a basement gym with no network. Two things stand in
 * the way by default, and vendoring only one of them fixes nothing:
 *
 *   1. the pose model (`.task`), downloaded from Google's model storage;
 *   2. the MediaPipe WASM runtime, downloaded from a CDN.
 *
 * The WASM files are copied out of `node_modules`, not downloaded: they ship
 * inside `@mediapipe/tasks-vision`, so copying them keeps the runtime and the
 * JS wrapper on the same version by construction. A CDN URL with a version
 * pinned by hand drifts the first time the package is bumped.
 *
 * Both outputs are gitignored — ~44 MB of binary belongs in the build artifact,
 * not in git history. Run this before `npm run build` for an offline-capable
 * bundle; skip it and the app falls back to the CDN (see `src/pose/assets.ts`).
 */

import { createHash } from "node:crypto";
import { createWriteStream } from "node:fs";
import { copyFile, mkdir, readFile, readdir, stat } from "node:fs/promises";
import { dirname, join } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, "..");
const PACKAGE = join(WEB, "node_modules", "@mediapipe", "tasks-vision");
const WASM_SRC = join(PACKAGE, "wasm");
const WASM_OUT = join(WEB, "public", "vendor", "tasks-vision");
const MODEL_OUT = join(WEB, "public", "models");
const MODEL_FILE = "pose_landmarker_full.task";
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker" +
  "/pose_landmarker_full/float16/1/pose_landmarker_full.task";

const force = process.argv.includes("--force");

/** @param {string} path */
async function exists(path) {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

async function packageVersion() {
  const raw = await readFile(join(PACKAGE, "package.json"), "utf8");
  return JSON.parse(raw).version;
}

async function copyWasm() {
  if (!(await exists(WASM_SRC))) {
    console.error(
      `Missing ${WASM_SRC}. Run \`npm install\` first — the WASM runtime ships ` +
        "inside @mediapipe/tasks-vision.",
    );
    process.exit(1);
  }

  await mkdir(WASM_OUT, { recursive: true });
  // Every file: FilesetResolver picks the SIMD or no-SIMD build at runtime from
  // what the browser reports, so shipping only one of them would work on the
  // dev machine and fail on some phone.
  const files = await readdir(WASM_SRC);
  let copied = 0;
  for (const file of files) {
    const target = join(WASM_OUT, file);
    if (!force && (await exists(target))) continue;
    await copyFile(join(WASM_SRC, file), target);
    copied += 1;
  }
  console.log(
    `WASM runtime v${await packageVersion()} → ${WASM_OUT} ` +
      `(${copied} copied, ${files.length - copied} already present)`,
  );
}

async function fetchModel() {
  const target = join(MODEL_OUT, MODEL_FILE);
  if (!force && (await exists(target))) {
    const { size } = await stat(target);
    console.log(`Model already present: ${target} (${size} bytes)`);
    return target;
  }

  await mkdir(MODEL_OUT, { recursive: true });
  console.log(`Downloading ${MODEL_URL}`);
  const response = await fetch(MODEL_URL);
  if (!response.ok || !response.body) {
    console.error(`Download failed: HTTP ${response.status}`);
    process.exit(1);
  }
  await pipeline(Readable.fromWeb(response.body), createWriteStream(target));
  return target;
}

await copyWasm();
const model = await fetchModel();

// No digest is pinned: the upstream file carries no published checksum, so a
// hash computed from the download we just made would prove nothing about it.
// Printing it lets a first-run digest be recorded and compared later, which is
// the honest version of the same guarantee.
const digest = createHash("sha256").update(await readFile(model)).digest("hex");
const { size } = await stat(model);
console.log(`Model → ${model} (${size} bytes)`);
console.log(`sha256 ${digest}`);
console.log("\nAssets vendored. The app now loads them from the same origin.");
