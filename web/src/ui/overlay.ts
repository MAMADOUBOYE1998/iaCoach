/**
 * Skeleton overlay.
 *
 * Drawing is the one place normalised 2D landmarks are the right input: we want
 * image-space pixels, not metres. Landmarks below the visibility threshold are
 * drawn dimmed rather than hidden, so a decrochage is visible to the athlete
 * instead of looking like a clean tracking loss.
 */

import type { Landmark } from "../pose/landmarker";
import { VISIBILITY_THRESHOLD } from "../pose/landmarker";

/** BlazePose torso + limbs. Face and hand detail are noise for calisthenics. */
const CONNECTIONS: ReadonlyArray<readonly [number, number]> = [
  [11, 12],
  [11, 13],
  [13, 15],
  [12, 14],
  [14, 16],
  [11, 23],
  [12, 24],
  [23, 24],
  [23, 25],
  [25, 27],
  [24, 26],
  [26, 28],
];

const TRACKED = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28];

export function resizeToVideo(canvas: HTMLCanvasElement, video: HTMLVideoElement): void {
  const { videoWidth, videoHeight } = video;
  if (videoWidth === 0 || videoHeight === 0) return;
  if (canvas.width !== videoWidth || canvas.height !== videoHeight) {
    canvas.width = videoWidth;
    canvas.height = videoHeight;
  }
}

export function clear(ctx: CanvasRenderingContext2D): void {
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
}

export function drawSkeleton(
  ctx: CanvasRenderingContext2D,
  landmarks: Landmark[],
): void {
  const { width, height } = ctx.canvas;
  const visible = (lm: Landmark | undefined): boolean =>
    (lm?.visibility ?? 0) >= VISIBILITY_THRESHOLD;

  ctx.lineWidth = Math.max(2, width / 320);
  for (const [from, to] of CONNECTIONS) {
    const a = landmarks[from];
    const b = landmarks[to];
    if (!a || !b) continue;
    ctx.strokeStyle = visible(a) && visible(b) ? "#4ade80" : "rgba(248,113,113,0.45)";
    ctx.beginPath();
    ctx.moveTo(a.x * width, a.y * height);
    ctx.lineTo(b.x * width, b.y * height);
    ctx.stroke();
  }

  const radius = Math.max(3, width / 240);
  for (const index of TRACKED) {
    const lm = landmarks[index];
    if (!lm) continue;
    ctx.fillStyle = visible(lm) ? "#f8fafc" : "rgba(248,113,113,0.5)";
    ctx.beginPath();
    ctx.arc(lm.x * width, lm.y * height, radius, 0, Math.PI * 2);
    ctx.fill();
  }
}
