/**
 * Generates the PWA icons.
 *
 * A script rather than two committed binaries nobody can edit: the icon is
 * ~40 lines of geometry, and regenerating it is how it gets changed. Written
 * with `node:zlib` alone — a build-time image dependency for two flat-colour
 * squares is not worth the supply chain.
 *
 * Without icons the manifest is not installable, and "PWA" means "a web page
 * that happens to have a manifest". The figure is drawn inside the maskable
 * safe zone (everything within a circle of radius 0.4 × side, centred), so
 * Android's mask cannot clip it.
 */

import { crc32, deflateSync } from "node:zlib";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "icons");
const SIZES = [192, 512];
/** Supersampling factor; hard-edged primitives are drawn large, then averaged. */
const SS = 4;

const BACKGROUND = [0x0d, 0x0f, 0x12];
const BAR = [0x4d, 0xa3, 0xff];
const FIGURE = [0xe8, 0xee, 0xf5];

/** @param {number} side @returns {Uint8Array} RGB pixels, row-major */
function draw(side) {
  const n = side * SS;
  const px = new Uint8Array(n * n * 3);
  for (let i = 0; i < n * n; i += 1) {
    px[i * 3] = BACKGROUND[0];
    px[i * 3 + 1] = BACKGROUND[1];
    px[i * 3 + 2] = BACKGROUND[2];
  }

  /** @param {number} x0 @param {number} y0 @param {number} x1 @param {number} y1 @param {number[]} rgb */
  const rect = (x0, y0, x1, y1, rgb) => {
    const [ax, ay, bx, by] = [x0 * n, y0 * n, x1 * n, y1 * n].map(Math.round);
    for (let y = Math.max(0, ay); y < Math.min(n, by); y += 1) {
      for (let x = Math.max(0, ax); x < Math.min(n, bx); x += 1) {
        const i = (y * n + x) * 3;
        px[i] = rgb[0];
        px[i + 1] = rgb[1];
        px[i + 2] = rgb[2];
      }
    }
  };

  /** @param {number} cx @param {number} cy @param {number} r @param {number[]} rgb */
  const disc = (cx, cy, r, rgb) => {
    const [px0, py0, rr] = [cx * n, cy * n, r * n];
    for (let y = Math.max(0, Math.floor(py0 - rr)); y < Math.min(n, Math.ceil(py0 + rr)); y += 1) {
      for (let x = Math.max(0, Math.floor(px0 - rr)); x < Math.min(n, Math.ceil(px0 + rr)); x += 1) {
        if ((x - px0) ** 2 + (y - py0) ** 2 > rr * rr) continue;
        const i = (y * n + x) * 3;
        px[i] = rgb[0];
        px[i + 1] = rgb[1];
        px[i + 2] = rgb[2];
      }
    }
  };

  // A hanging figure on a bar: the one image that says "street workout" without
  // a word of text, which matters for an app whose UI is French.
  rect(0.22, 0.275, 0.78, 0.315, BAR); // bar
  rect(0.362, 0.315, 0.398, 0.475, FIGURE); // left arm
  rect(0.602, 0.315, 0.638, 0.475, FIGURE); // right arm
  disc(0.5, 0.4, 0.072, FIGURE); // head
  rect(0.362, 0.44, 0.638, 0.475, FIGURE); // shoulders
  rect(0.45, 0.475, 0.55, 0.65, FIGURE); // torso
  rect(0.452, 0.65, 0.488, 0.78, FIGURE); // left leg
  rect(0.512, 0.65, 0.548, 0.78, FIGURE); // right leg

  // Box-downsample to the target size.
  const out = new Uint8Array(side * side * 3);
  for (let y = 0; y < side; y += 1) {
    for (let x = 0; x < side; x += 1) {
      const acc = [0, 0, 0];
      for (let dy = 0; dy < SS; dy += 1) {
        for (let dx = 0; dx < SS; dx += 1) {
          const i = ((y * SS + dy) * n + (x * SS + dx)) * 3;
          acc[0] += px[i];
          acc[1] += px[i + 1];
          acc[2] += px[i + 2];
        }
      }
      const j = (y * side + x) * 3;
      for (let c = 0; c < 3; c += 1) out[j + c] = Math.round(acc[c] / (SS * SS));
    }
  }
  return out;
}

/** @param {string} type @param {Buffer} data */
function chunk(type, data) {
  const body = Buffer.concat([Buffer.from(type, "latin1"), data]);
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, checksum]);
}

/** @param {Uint8Array} rgb @param {number} side */
function png(rgb, side) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(side, 0);
  header.writeUInt32BE(side, 4);
  header[8] = 8; // bit depth
  header[9] = 2; // colour type: truecolour RGB
  // 10-12: deflate / adaptive filtering / no interlace, all zero.

  // Each scanline is prefixed with its filter type; 0 (none) keeps the encoder
  // trivial and costs a few KB on a flat-colour image.
  const raw = Buffer.alloc(side * (side * 3 + 1));
  for (let y = 0; y < side; y += 1) {
    raw[y * (side * 3 + 1)] = 0;
    Buffer.from(rgb.subarray(y * side * 3, (y + 1) * side * 3)).copy(
      raw,
      y * (side * 3 + 1) + 1,
    );
  }

  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

await mkdir(OUT_DIR, { recursive: true });
for (const side of SIZES) {
  const file = join(OUT_DIR, `icon-${side}.png`);
  const bytes = png(draw(side), side);
  await writeFile(file, bytes);
  console.log(`${file} (${bytes.length} bytes)`);
}
