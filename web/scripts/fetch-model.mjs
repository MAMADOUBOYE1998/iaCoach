/**
 * Vendors the MediaPipe pose model into `public/models/`.
 *
 * The app loads the model from a CDN by default, which is fine for development
 * but incompatible with the offline-first requirement: rep counting and form
 * scoring must work with no network. Run this once, then point
 * `MODEL_URL` in `src/pose/landmarker.ts` at `/models/<file>`.
 *
 * The .task file is a few MB of binary — it is gitignored on purpose. Ship it
 * with the build artifact, not through git.
 */

import { createWriteStream } from "node:fs";
import { mkdir, stat } from "node:fs/promises";
import { dirname, join } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = join(HERE, "..", "public", "models");
const FILENAME = "pose_landmarker_full.task";
const URL_ =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task";

const target = join(OUT_DIR, FILENAME);

try {
  const existing = await stat(target);
  console.log(`Already present: ${target} (${existing.size} bytes)`);
  process.exit(0);
} catch {
  // Not downloaded yet — continue.
}

await mkdir(OUT_DIR, { recursive: true });
console.log(`Downloading ${URL_}`);

const response = await fetch(URL_);
if (!response.ok || !response.body) {
  console.error(`Download failed: HTTP ${response.status}`);
  process.exit(1);
}

await pipeline(Readable.fromWeb(response.body), createWriteStream(target));
const written = await stat(target);
console.log(`Wrote ${target} (${written.size} bytes)`);
console.log("Now set MODEL_URL in src/pose/landmarker.ts to '/models/" + FILENAME + "'.");
