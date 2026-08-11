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

import type { PoseAssets } from "./assets";

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
}

export interface Detection {
  /**
   * Wall-clock cost of this inference, in milliseconds.
   *
   * Reported whether or not a pose was found, and that is the point: an empty
   * frame costs a full inference. Timing only the successful frames would
   * quietly drop every moment the athlete is out of shot from the average and
   * report a latency the device never achieved.
   */
  inferenceMs: number;
  /** `null` when no pose was found — never a neutral or default pose. */
  pose: PoseFrame | null;
}

/**
 * Where the runtime and model come from is resolved by `resolveAssets()` and
 * passed in, rather than decided here: the caller is the one that has to tell
 * the athlete whether this session will survive losing the network.
 */
export async function createLandmarker(assets: PoseAssets): Promise<PoseLandmarker> {
  const fileset = await FilesetResolver.forVisionTasks(assets.wasmBase);
  return PoseLandmarker.createFromOptions(fileset, {
    baseOptions: {
      modelAssetPath: assets.modelUrl,
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
 * Run one inference. `pose` is `null` when nothing was found — the caller must
 * treat that as "no data this frame", never as a neutral/default pose.
 */
export function detect(
  landmarker: PoseLandmarker,
  video: HTMLVideoElement,
  timestampMs: number,
): Detection {
  const started = performance.now();
  const result = landmarker.detectForVideo(video, timestampMs);
  const inferenceMs = performance.now() - started;

  const world = result.worldLandmarks[0];
  const normalized = result.landmarks[0];
  if (!world || !normalized) return { inferenceMs, pose: null };

  return { inferenceMs, pose: { world, normalized } };
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
