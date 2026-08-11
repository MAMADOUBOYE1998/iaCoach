/**
 * Fails if the built service worker is not a classic script.
 *
 * `sw.ts` imports `pwa/policy.ts`, and rollup normally inlines that into the
 * worker chunk. If a future shared import makes it emit a real `import`
 * statement instead, the worker would need to be registered with
 * `{ type: "module" }` — and until it is, it silently fails to install in every
 * browser without module-worker support. That failure is invisible: the app
 * keeps working online and simply stops working offline.
 *
 * Cheap check, run right after `vite build`.
 */

import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const SW = join(dirname(fileURLToPath(import.meta.url)), "..", "dist", "sw.js");

let source;
try {
  source = await readFile(SW, "utf8");
} catch {
  console.error(`Missing ${SW} — did \`vite build\` run?`);
  process.exit(1);
}

const offender = source
  .split("\n")
  .findIndex((line) => /^\s*(import|export)\s|^\s*import\s*\(/.test(line));

if (offender >= 0) {
  console.error(
    `dist/sw.js line ${offender + 1} is an ES module statement:\n` +
      `  ${source.split("\n")[offender]?.trim()}\n` +
      "Register the worker with { type: 'module' } or keep its dependencies inlined.",
  );
  process.exit(1);
}

console.log(`dist/sw.js is a classic script (${source.length} bytes).`);
