/**
 * MediaPipe Pose Landmarker wrapper.
 *
 * Two things matter here beyond "load the model":
 *
 * 1. We consume `worldLandmarks` — metric 3D coordinates in metres, origin at
 *    the hip midpoint — not the normalised 2D `landmarks`. Every biomechanical
 *    computation downstream depends on that. The 2D set is kept only for drawing
 *    the overlay, where pixel coordinates are what we actually want.
 * 2. Inference latency is measured per frame from the start, because "≥ 25 fps
 *    on a mid-range phone" is a claim this project has to prove, not assert.
 */

import { FilesetResolver, PoseLandmarker } from "@mediapipe/tasks-vision";

/** MediaPipe BlazePose landmark indices we actually use. */
export const LANDMARK = {
  LEFT_SHOULDER: 11,
  RIGHT_SHOULDER: 12,
  LEFT_ELBOW: 13,
  RIGHT_ELBOW: 14,
  LEFT_WRIST: 15,
  RIGHT_WRIST: 16,
  LEFT_HIP: 23,
  RIGHT_HIP: 24,
  LEFT_KNEE: 25,
  RIGHT_KNEE: 26,
  LEFT_ANKLE: 27,
  RIGHT_ANKLE: 28,
} as const;

/**
 * Below this, a landmark is not trusted for any correction. A wrong correction
 * is worse than no correction, so the threshold is deliberately conservative.
 */
export const VISIBILITY_THRESHOLD = 0.6;

const WASM_BASE =
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18/wasm";

/**
 * Served from a CDN for now. Vendoring it under `public/models/` is a
 * prerequisite for the offline-first requirement — see `scripts/fetch-model.mjs`
 * and the M0 notes in docs/ROADMAP.md.
 */
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

export interface PoseFrame {
  /** Metric 3D landmarks, in metres. Use these for every angle computation. */
  world: Landmark[];
  /** Normalised [0,1] image-space landmarks. Overlay drawing only. */
  normalized: Landmark[];
  /** Wall-clock cost of this inference, in milliseconds. */
  inferenceMs: number;
}

export async function createLandmarker(): Promise<PoseLandmarker> {
  const fileset = await FilesetResolver.forVisionTasks(WASM_BASE);
  return PoseLandmarker.createFromOptions(fileset, {
    baseOptions: {
      modelAssetPath: MODEL_URL,
      // GPU delegate is what makes the 25 fps target reachable on a phone.
      // MediaPipe falls back to CPU on its own if WebGL is unavailable.
      delegate: "GPU",
    },
    runningMode: "VIDEO",
    numPoses: 1,
    minPoseDetectionConfidence: 0.5,
    minPosePresenceConfidence: 0.5,
    minTrackingConfidence: 0.5,
  });
}

/**
 * Run one inference. Returns `null` when no pose was found — the caller must
 * treat that as "no data this frame", never as a neutral/default pose.
 */
export function detect(
  landmarker: PoseLandmarker,
  video: HTMLVideoElement,
  timestampMs: number,
): PoseFrame | null {
  const started = performance.now();
  const result = landmarker.detectForVideo(video, timestampMs);
  const inferenceMs = performance.now() - started;

  const world = result.worldLandmarks[0];
  const normalized = result.landmarks[0];
  if (!world || !normalized) return null;

  return { world, normalized, inferenceMs };
}

/**
 * Fraction of the given landmarks that are above the visibility threshold.
 *
 * This is the per-frame input to `RepEvent.confidence`. MediaPipe omits
 * `visibility` on some builds; a missing value is treated as unusable rather
 * than assumed visible, so a model that stops reporting confidence degrades to
 * "suppress corrections" instead of silently asserting them.
 */
export function usableFraction(landmarks: Landmark[], indices: number[]): number {
  if (indices.length === 0) return 0;
  let usable = 0;
  for (const i of indices) {
    const lm = landmarks[i];
    if (lm && (lm.visibility ?? 0) >= VISIBILITY_THRESHOLD) usable += 1;
  }
  return usable / indices.length;
}
