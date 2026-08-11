/**
 * Camera -> on-device pose -> calibration -> rep counting, with the latency
 * instrumentation the project's performance claims will be measured against.
 *
 * No network call happens in this loop, and none ever will: the correction
 * window is ~100 ms and a cloud round trip costs 150-400 ms. The backend is for
 * asynchronous work only.
 */

import type { PoseLandmarker } from "@mediapipe/tasks-vision";

import { CalibrationRecorder, FrameSampler } from "./analysis/frame";
import { RepCounter, type FrameSample } from "./analysis/counting";
import { CameraError, startCamera, type CameraHandle } from "./pose/camera";
import { createLandmarker, detect } from "./pose/landmarker";
import { feedbackFor, formatPercent, scoreLines } from "./ui/feedback";
import { clear, drawSkeleton, resizeToVideo } from "./ui/overlay";
import type { ExerciseCalibration, RepEvent } from "./types/contracts";
import "./styles.css";

const el = <T extends HTMLElement>(id: string): T => {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing element #${id}`);
  return node as T;
};

const video = el<HTMLVideoElement>("video");
const canvas = el<HTMLCanvasElement>("overlay");
const startButton = el<HTMLButtonElement>("start");
const calibrateButton = el<HTMLButtonElement>("calibrate");
const statusLine = el<HTMLParagraphElement>("status");
const repsOut = el<HTMLSpanElement>("reps");
const confidenceOut = el<HTMLSpanElement>("confidence");
const fpsOut = el<HTMLSpanElement>("fps");
const latencyOut = el<HTMLSpanElement>("latency");
const lastRepPanel = el<HTMLElement>("last-rep");
const lastRepScores = el<HTMLUListElement>("last-rep-scores");
const lastRepFeedback = el<HTMLParagraphElement>("last-rep-feedback");

// Extracted so the non-null result is carried into the closures below; a
// narrowed `const` does not survive the function boundary.
function requireContext(target: HTMLCanvasElement): CanvasRenderingContext2D {
  const context = target.getContext("2d");
  if (!context) throw new Error("Canvas 2D context unavailable");
  return context;
}

const ctx = requireContext(canvas);

const CALIBRATION_MS = 8000;

/**
 * Rolling mean over a fixed window. Used for the *display* of fps and latency
 * only — never for the pose signal itself, where a moving average would add
 * ~80 ms of lag and flatten the angular-velocity peaks that carry the fatigue
 * signal. That signal goes through the One-Euro filter instead.
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

type Mode =
  | { kind: "idle" }
  | { kind: "calibrating"; recorder: CalibrationRecorder; startedAt: number }
  | { kind: "counting"; counter: RepCounter };

interface RunState {
  camera: CameraHandle;
  landmarker: PoseLandmarker;
  sampler: FrameSampler;
  rafId: number;
  mode: Mode;
}

let running: RunState | null = null;

function setStatus(message: string, isError = false): void {
  statusLine.textContent = message;
  statusLine.classList.toggle("error", isError);
}

function showRep(event: RepEvent): void {
  lastRepPanel.hidden = false;
  lastRepScores.replaceChildren(
    ...scoreLines(event).map(({ label, value }) => {
      const item = document.createElement("li");
      item.textContent = `${label} : ${formatPercent(value)}`;
      // Only the low end is highlighted: colouring every score turns the panel
      // into decoration and hides the one thing worth reacting to.
      if (value < 0.7) item.classList.add("warn");
      return item;
    }),
  );
  lastRepFeedback.textContent = feedbackFor(event);
  lastRepFeedback.classList.toggle("warn", event.flags.length > 0);
}

function buildCalibration(
  range: { rom_min_deg: number; rom_max_deg: number; confidence: number },
): ExerciseCalibration {
  return {
    exercise: "pull_up",
    joint: "elbow",
    rom_min_deg: range.rom_min_deg,
    rom_max_deg: range.rom_max_deg,
    captured_at: new Date().toISOString(),
    confidence: range.confidence,
  };
}

function onCalibrationFrame(state: RunState, sample: FrameSample, now: number): void {
  if (state.mode.kind !== "calibrating") return;
  const { recorder, startedAt } = state.mode;
  recorder.add(sample);

  const remaining = Math.max(0, CALIBRATION_MS - (now - startedAt));
  if (remaining > 0) {
    setStatus(
      `Calibration : une traction lente et complète… ${(remaining / 1000).toFixed(0)} s`,
    );
    return;
  }

  const range = recorder.finish();
  if (!range) {
    // Refusing to calibrate is the correct outcome: a bad range silently
    // corrupts every score that follows.
    state.mode = { kind: "idle" };
    calibrateButton.hidden = false;
    setStatus(
      "Calibration insuffisante : amplitude trop faible ou suivi trop instable. Recadre-toi et recommence.",
      true,
    );
    return;
  }

  state.mode = { kind: "counting", counter: new RepCounter("pull_up", buildCalibration(range)) };
  repsOut.textContent = "0";
  setStatus(
    `Calibré sur ${range.rom_min_deg.toFixed(0)}°–${range.rom_max_deg.toFixed(0)}°. ` +
      "Vas-y, je compte.",
  );
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

      const sample = state.sampler.sample(frame.world, frame.normalized, timestamp);
      if (sample) {
        confidenceOut.textContent = formatPercent(sample.confidence);
        confidenceOut.classList.toggle("warn", sample.confidence < 0.7);

        if (state.mode.kind === "calibrating") {
          onCalibrationFrame(state, sample, now);
        } else if (state.mode.kind === "counting") {
          const event = state.mode.counter.push(sample);
          if (event) {
            repsOut.textContent = String(
              // The displayed figure is valid reps, not attempts. Short reps are
              // still recorded and shown in the panel below.
              Number(repsOut.textContent ?? "0") + (event.counted ? 1 : 0),
            );
            showRep(event);
          }
        }
      }
    } else {
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

  running = {
    camera,
    landmarker,
    sampler: new FrameSampler(),
    rafId: 0,
    mode: { kind: "idle" },
  };
  startButton.textContent = "Arrêter";
  startButton.disabled = false;
  calibrateButton.hidden = false;
  setStatus("Place-toi de profil, corps entier dans le cadre, puis calibre ton amplitude.");
  loop(running);
}

function stop(): void {
  if (!running) return;
  cancelAnimationFrame(running.rafId);
  running.camera.stop();
  running.landmarker.close();
  running = null;
  clear(ctx);
  for (const out of [repsOut, confidenceOut, fpsOut, latencyOut]) out.textContent = "—";
  confidenceOut.classList.remove("warn");
  lastRepPanel.hidden = true;
  calibrateButton.hidden = true;
  startButton.textContent = "Démarrer la caméra";
  setStatus("Arrêté.");
}

startButton.addEventListener("click", () => {
  if (running) stop();
  else void start();
});

calibrateButton.addEventListener("click", () => {
  if (!running) return;
  running.sampler.reset();
  running.mode = {
    kind: "calibrating",
    recorder: new CalibrationRecorder(),
    startedAt: performance.now(),
  };
  calibrateButton.hidden = true;
  lastRepPanel.hidden = true;
  repsOut.textContent = "—";
  setStatus("Calibration : une traction lente et complète…");
});

// Releasing the camera on unload matters on mobile: a stream left open keeps the
// hardware busy and the indicator light on after the tab is gone.
window.addEventListener("pagehide", stop);
