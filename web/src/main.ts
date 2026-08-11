/**
 * M0: camera -> on-device pose -> overlay, with the latency instrumentation the
 * project's performance claims will be measured against.
 *
 * No network call happens in this loop, and none ever will: the correction
 * window is ~100 ms and a cloud round trip costs 150-400 ms. The backend is for
 * asynchronous work only.
 *
 * The elbow angle shown here is a live sanity check that `worldLandmarks` are
 * being read correctly — the rep FSM that consumes it lands in M1.
 */

import type { PoseLandmarker } from "@mediapipe/tasks-vision";

import { angleDeg, type Point3 } from "./pose/angles";
import { startCamera, CameraError, type CameraHandle } from "./pose/camera";
import {
  createLandmarker,
  detect,
  LANDMARK,
  usableFraction,
  type Landmark,
} from "./pose/landmarker";
import { clear, drawSkeleton, resizeToVideo } from "./ui/overlay";
import "./styles.css";

const el = <T extends HTMLElement>(id: string): T => {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing element #${id}`);
  return node as T;
};

const video = el<HTMLVideoElement>("video");
const canvas = el<HTMLCanvasElement>("overlay");
const startButton = el<HTMLButtonElement>("start");
const statusLine = el<HTMLParagraphElement>("status");
const fpsOut = el<HTMLSpanElement>("fps");
const latencyOut = el<HTMLSpanElement>("latency");
const elbowOut = el<HTMLSpanElement>("elbow");
const confidenceOut = el<HTMLSpanElement>("confidence");

// Extracted so the non-null result is carried into the closures below; a
// narrowed `const` does not survive the function boundary.
function requireContext(target: HTMLCanvasElement): CanvasRenderingContext2D {
  const context = target.getContext("2d");
  if (!context) throw new Error("Canvas 2D context unavailable");
  return context;
}

const ctx = requireContext(canvas);

/** Landmarks the pull-up FSM will depend on; drives the confidence readout. */
const DRIVING_LANDMARKS = [
  LANDMARK.LEFT_SHOULDER,
  LANDMARK.RIGHT_SHOULDER,
  LANDMARK.LEFT_ELBOW,
  LANDMARK.RIGHT_ELBOW,
  LANDMARK.LEFT_WRIST,
  LANDMARK.RIGHT_WRIST,
];

/**
 * Rolling mean over a fixed window. Used for the *display* of fps and latency
 * only — never for the pose signal itself, where a moving average would add
 * ~80 ms of lag and flatten the angular-velocity peaks that carry the fatigue
 * signal (a One-Euro filter handles that, in M1).
 */
class Rolling {
  private readonly samples: number[] = [];

  constructor(private readonly size: number) {}

  push(value: number): void {
    this.samples.push(value);
    if (this.samples.length > this.size) this.samples.shift();
  }

  get mean(): number {
    if (this.samples.length === 0) return 0;
    return this.samples.reduce((a, b) => a + b, 0) / this.samples.length;
  }
}

function toPoint3(lm: Landmark | undefined): Point3 | null {
  return lm ? { x: lm.x, y: lm.y, z: lm.z } : null;
}

/** Mean elbow angle across both arms, ignoring an arm whose landmarks are absent. */
function elbowAngle(world: Landmark[]): number | null {
  const sides: Array<[number, number, number]> = [
    [LANDMARK.LEFT_SHOULDER, LANDMARK.LEFT_ELBOW, LANDMARK.LEFT_WRIST],
    [LANDMARK.RIGHT_SHOULDER, LANDMARK.RIGHT_ELBOW, LANDMARK.RIGHT_WRIST],
  ];

  const angles: number[] = [];
  for (const [s, e, w] of sides) {
    const shoulder = toPoint3(world[s]);
    const elbow = toPoint3(world[e]);
    const wrist = toPoint3(world[w]);
    if (shoulder && elbow && wrist) angles.push(angleDeg(shoulder, elbow, wrist));
  }
  if (angles.length === 0) return null;
  return angles.reduce((a, b) => a + b, 0) / angles.length;
}

interface RunState {
  camera: CameraHandle;
  landmarker: PoseLandmarker;
  rafId: number;
}

let running: RunState | null = null;

function setStatus(message: string, isError = false): void {
  statusLine.textContent = message;
  statusLine.classList.toggle("error", isError);
}

function loop(state: RunState): void {
  const fps = new Rolling(30);
  const latency = new Rolling(30);
  let lastFrameAt = performance.now();
  // MediaPipe's VIDEO mode requires strictly increasing timestamps; a repeated
  // value makes detectForVideo throw, so we track the last one we sent.
  let lastTimestamp = -1;

  const tick = (): void => {
    const now = performance.now();
    const delta = now - lastFrameAt;
    lastFrameAt = now;
    if (delta > 0) fps.push(1000 / delta);

    resizeToVideo(canvas, video);

    const timestamp = Math.max(Math.round(now), lastTimestamp + 1);
    lastTimestamp = timestamp;

    let frame: ReturnType<typeof detect> = null;
    try {
      frame = detect(state.landmarker, video, timestamp);
    } catch (error) {
      console.error("pose inference failed", error);
    }

    clear(ctx);

    if (frame) {
      latency.push(frame.inferenceMs);
      drawSkeleton(ctx, frame.normalized);

      const angle = elbowAngle(frame.world);
      elbowOut.textContent = angle === null ? "—" : `${angle.toFixed(0)}°`;

      const confidence = usableFraction(frame.normalized, DRIVING_LANDMARKS);
      confidenceOut.textContent = `${Math.round(confidence * 100)}%`;
      confidenceOut.classList.toggle("warn", confidence < 0.7);
    } else {
      elbowOut.textContent = "—";
      confidenceOut.textContent = "0%";
      confidenceOut.classList.add("warn");
    }

    fpsOut.textContent = fps.mean.toFixed(0);
    latencyOut.textContent = latency.mean.toFixed(1);

    state.rafId = requestAnimationFrame(tick);
  };

  state.rafId = requestAnimationFrame(tick);
}

async function start(): Promise<void> {
  startButton.disabled = true;
  setStatus("Chargement du modèle de pose…");

  let landmarker: PoseLandmarker;
  try {
    landmarker = await createLandmarker();
  } catch (error) {
    console.error(error);
    setStatus("Échec du chargement du modèle de pose. Vérifie ta connexion.", true);
    startButton.disabled = false;
    return;
  }

  setStatus("Autorise l'accès à la caméra…");
  let camera: CameraHandle;
  try {
    camera = await startCamera(video);
  } catch (error) {
    console.error(error);
    setStatus(
      error instanceof CameraError ? error.message : "Impossible d'ouvrir la caméra.",
      true,
    );
    landmarker.close();
    startButton.disabled = false;
    return;
  }

  running = { camera, landmarker, rafId: 0 };
  setStatus("Détection en cours. Place-toi de profil, corps entier dans le cadre.");
  startButton.textContent = "Arrêter";
  startButton.disabled = false;
  loop(running);
}

function stop(): void {
  if (!running) return;
  cancelAnimationFrame(running.rafId);
  running.camera.stop();
  running.landmarker.close();
  running = null;
  clear(ctx);
  fpsOut.textContent = "—";
  latencyOut.textContent = "—";
  elbowOut.textContent = "—";
  confidenceOut.textContent = "—";
  startButton.textContent = "Démarrer la caméra";
  setStatus("Arrêté.");
}

startButton.addEventListener("click", () => {
  if (running) stop();
  else void start();
});

// Releasing the camera on unload matters on mobile: a stream left open keeps the
// hardware busy and the indicator light on after the tab is gone.
window.addEventListener("pagehide", stop);
