/**
 * Camera -> on-device pose -> calibration -> rep counting -> session sync.
 *
 * No network call happens in the analysis loop, and none ever will: the
 * correction window is ~100 ms and a cloud round trip costs 150-400 ms. The
 * backend is touched only when a session ends, and its absence degrades the app
 * to "counts and scores locally, syncs later" rather than breaking it.
 */

import type { PoseLandmarker } from "@mediapipe/tasks-vision";

import { RepCounter, type FrameSample } from "./analysis/counting";
import { CalibrationRecorder, FrameSampler } from "./analysis/frame";
import { API_BASE, athleteId, preferredFacing, rememberFacing } from "./config";
import {
  CameraError,
  hasMultipleCameras,
  otherFacing,
  startCamera,
  type CameraHandle,
  type Facing,
} from "./pose/camera";
import { assetsLabel, resolveAssets } from "./pose/assets";
import { createLandmarker, detect, type Detection } from "./pose/landmarker";
import { registerServiceWorker } from "./pwa/register";
import { SessionRecorder, newSessionId } from "./session/recorder";
import { SessionSync } from "./session/sync";
import { renderDebrief, renderDebriefUnavailable } from "./ui/debrief";
import { feedbackFor, formatPercent, scoreLines } from "./ui/feedback";
import {
  captureConsole,
  formatReport,
  summarise,
  type Sample,
  type Summary,
} from "./ui/diagnostics";
import { clear, drawSkeleton, resizeToVideo } from "./ui/overlay";
import { renderProgress } from "./ui/progress";
import type { ExerciseCalibration, ProgressPoint, RepEvent } from "./types/contracts";
import "./styles.css";

const el = <T extends HTMLElement>(id: string): T => {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing element #${id}`);
  return node as T;
};

const video = el<HTMLVideoElement>("video");
const stage = el<HTMLElement>("stage");
const canvas = el<HTMLCanvasElement>("overlay");
const startButton = el<HTMLButtonElement>("start");
const flipButton = el<HTMLButtonElement>("flip");
const calibrateButton = el<HTMLButtonElement>("calibrate");
const newSetButton = el<HTMLButtonElement>("new-set");
const finishButton = el<HTMLButtonElement>("finish");
const statusLine = el<HTMLParagraphElement>("status");
const repsOut = el<HTMLSpanElement>("reps");
const confidenceOut = el<HTMLSpanElement>("confidence");
const fpsOut = el<HTMLSpanElement>("fps");
const latencyOut = el<HTMLSpanElement>("latency");
const lastRepPanel = el<HTMLElement>("last-rep");
const lastRepScores = el<HTMLUListElement>("last-rep-scores");
const lastRepFeedback = el<HTMLParagraphElement>("last-rep-feedback");
const debriefPanel = el<HTMLElement>("debrief-panel");
const debriefOut = el<HTMLDivElement>("debrief");
const progressOut = el<HTMLDivElement>("progress");
const syncStatus = el<HTMLParagraphElement>("sync-status");
const measureButton = el<HTMLButtonElement>("measure");
const diagToggle = el<HTMLButtonElement>("diag-toggle");
const diagCopy = el<HTMLButtonElement>("diag-copy");
const diagOut = el<HTMLPreElement>("diag");

// Installed before anything else runs: MediaPipe reports the GL context it got
// on the console during initialisation, and that line is the only evidence of
// whether the GPU delegate was really used. Miss it and a latency figure cannot
// be interpreted.
const consoleLines = captureConsole();

// Extracted so the non-null result is carried into the closures below; a
// narrowed `const` does not survive the function boundary.
function requireContext(target: HTMLCanvasElement): CanvasRenderingContext2D {
  const context = target.getContext("2d");
  if (!context) throw new Error("Canvas 2D context unavailable");
  return context;
}

const ctx = requireContext(canvas);
const sync = new SessionSync(API_BASE, localStorage);
const ATHLETE_ID = athleteId();

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

/**
 * A timed measurement run.
 *
 * `WARMUP_MS` is dropped from the result: the first seconds after the graph
 * starts are dominated by shader compilation and texture allocation, and a
 * phone throttles down later — averaging the two together describes no state
 * the device is ever actually in.
 */
const WARMUP_MS = 5_000;
const MEASURE_MS = 60_000;

interface Measurement {
  startedAt: number;
  samples: Sample[];
}

let measurement: Measurement | null = null;
let lastSummary: Summary | null = null;
/** Resolved at startup; reported because it changes what offline means. */
let assetSource: "local" | "cdn" = "cdn";

type Mode =
  | { kind: "idle" }
  | { kind: "calibrating"; recorder: CalibrationRecorder; startedAt: number }
  | { kind: "counting"; counter: RepCounter; session: SessionRecorder };

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

async function refreshProgress(): Promise<void> {
  try {
    const response = await fetch(
      `${API_BASE}/athletes/${encodeURIComponent(ATHLETE_ID)}/progress?exercise=pull_up`,
    );
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderProgress(progressOut, (await response.json()) as ProgressPoint[]);
  } catch {
    // The backend is optional. A missing history view is not an error state.
    renderProgress(progressOut, []);
  }
}

function reportPending(): void {
  const pending = sync.pending.length;
  syncStatus.textContent =
    pending === 0 ? "" : `${pending} séance(s) en attente de synchronisation.`;
}

function buildCalibration(range: {
  rom_min_deg: number;
  rom_max_deg: number;
  confidence: number;
}): ExerciseCalibration {
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

  state.mode = {
    kind: "counting",
    counter: new RepCounter("pull_up", buildCalibration(range)),
    session: new SessionRecorder(newSessionId(), ATHLETE_ID),
  };
  repsOut.textContent = "0";
  newSetButton.hidden = false;
  finishButton.hidden = false;
  debriefPanel.hidden = true;
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

    let detection: Detection | null = null;
    try {
      detection = detect(state.landmarker, video, timestamp);
    } catch (error) {
      // Only a throw leaves the cost unknown, and only then is it left out of
      // the average.
      console.error("pose inference failed", error);
    }
    if (detection) latency.push(detection.inferenceMs);

    clear(ctx);

    const frame = detection?.pose ?? null;
    if (frame) {
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
            state.mode.session.addRep(event);
            // The displayed figure is valid reps, not attempts. Short reps are
            // still recorded and shown in the panel below.
            repsOut.textContent = String(state.mode.session.validReps);
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

    if (measurement && detection) {
      const elapsed = now - measurement.startedAt;
      if (elapsed >= WARMUP_MS) {
        measurement.samples.push({ fps: 1000 / delta, latencyMs: detection.inferenceMs });
      }
      if (elapsed >= WARMUP_MS + MEASURE_MS) finishMeasurement();
      else {
        const left = Math.ceil((WARMUP_MS + MEASURE_MS - elapsed) / 1000);
        measureButton.textContent =
          elapsed < WARMUP_MS ? "Échauffement…" : `Mesure — ${left} s`;
      }
    }

    state.rafId = requestAnimationFrame(tick);
  };

  state.rafId = requestAnimationFrame(tick);
}

async function finishSession(): Promise<void> {
  if (!running || running.mode.kind !== "counting") return;
  const { session } = running.mode;

  if (session.isEmpty) {
    setStatus("Aucune rep enregistrée : rien à sauvegarder.");
    return;
  }

  const summary = session.finish();
  // Queue before sending: if the tab dies mid-request, the session survives.
  sync.enqueue(summary);
  running.mode = { kind: "idle" };
  newSetButton.hidden = true;
  finishButton.hidden = true;
  calibrateButton.hidden = false;

  setStatus(`Séance terminée : ${session.validReps}/${session.totalReps} reps validées.`);

  const result = await sync.flush();
  reportPending();
  debriefPanel.hidden = false;

  if (result.sent === 0) {
    renderDebriefUnavailable(
      debriefOut,
      "Séance non synchronisée — pas de connexion au backend.",
    );
    return;
  }

  debriefOut.textContent = "Analyse en cours…";
  try {
    const debrief = await sync.debrief(summary.session_id);
    if (debrief) renderDebrief(debriefOut, debrief);
    else renderDebriefUnavailable(debriefOut, "Coaching indisponible (pas de clé API).");
  } catch (error) {
    console.error(error);
    renderDebriefUnavailable(debriefOut, "Le débrief a échoué.");
  }

  await refreshProgress();
}

async function start(): Promise<void> {
  startButton.disabled = true;
  setStatus("Chargement du modèle de pose…");

  let landmarker: PoseLandmarker;
  try {
    const assets = await resolveAssets();
    assetSource = assets.source;
    // Also logged, so it lands in the captured console lines alongside
    // MediaPipe's own output.
    console.info(assetsLabel(assets));
    landmarker = await createLandmarker(assets);
  } catch (error) {
    console.error(error);
    setStatus("Échec du chargement du modèle de pose. Vérifie ta connexion.", true);
    startButton.disabled = false;
    return;
  }

  setStatus("Autorise l'accès à la caméra…");
  let camera: CameraHandle;
  try {
    camera = await startCamera(video, preferredFacing());
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
  applyCamera(camera);
  measureButton.hidden = false;
  // Only meaningful once permission is granted: before that the browser hides
  // the device list, so asking earlier would always answer "one camera".
  flipButton.hidden = !(await hasMultipleCameras());
  setStatus("Place-toi de profil, corps entier dans le cadre, puis calibre ton amplitude.");
  loop(running);
}

function startMeasurement(): void {
  if (!running) return;
  measurement = { startedAt: performance.now(), samples: [] };
  measureButton.disabled = true;
  measureButton.textContent = "Échauffement…";
  setStatus("Mesure en cours : garde le cadrage et ne touche à rien.");
}

function finishMeasurement(): void {
  if (!measurement) return;
  lastSummary = summarise(measurement.samples, MEASURE_MS / 1000);
  measurement = null;
  measureButton.disabled = false;
  measureButton.textContent = "Mesurer 60 s";
  showDiagnostics(true);
  setStatus("Mesure terminée. Capture le panneau Diagnostic.");
}

/**
 * Builds the report from the live state.
 *
 * Regenerated on each display rather than cached: a report describing a camera
 * that has since been switched would be worse than none.
 */
function report(): string {
  const track = running?.camera.stream.getVideoTracks()[0];
  const settings = track?.getSettings();
  return formatReport({
    modelSource: assetSource,
    facing: running?.camera.facing ?? "—",
    videoWidth: video.videoWidth,
    videoHeight: video.videoHeight,
    trackFrameRate: settings?.frameRate ?? null,
    summary: lastSummary,
    consoleLines: consoleLines(),
  });
}

function showDiagnostics(visible: boolean): void {
  diagOut.hidden = !visible;
  diagCopy.hidden = !visible;
  diagToggle.textContent = visible ? "Masquer le diagnostic" : "Diagnostic";
  if (visible) diagOut.textContent = report();
}

/** Reflect the open camera in the UI: mirror the preview, label the switch. */
function applyCamera(camera: CameraHandle): void {
  stage.classList.toggle("mirrored", camera.mirrored);
  flipButton.textContent =
    otherFacing(camera.facing) === "user" ? "Caméra avant" : "Caméra arrière";
}

/**
 * Swap cameras without ending the session.
 *
 * The landmarker, the counter and the recorded sets are untouched: switching
 * camera mid-set is a framing fix, not a reason to lose the reps already
 * counted. Only the calibration is invalidated — a new viewpoint changes the
 * measured range, and keeping the old one would silently score every following
 * rep against a range from a different angle.
 */
async function flipCamera(): Promise<void> {
  if (!running) return;
  const target: Facing = otherFacing(running.camera.facing);
  flipButton.disabled = true;
  running.camera.stop();

  try {
    running.camera = await startCamera(video, target);
    rememberFacing(running.camera.facing);
  } catch (error) {
    console.error(error);
    // Put the previous one back rather than leaving a dead preview.
    try {
      running.camera = await startCamera(video, otherFacing(target));
      setStatus("Impossible de changer de caméra.", true);
    } catch {
      stop();
      setStatus("Caméra perdue. Redémarre-la.", true);
      return;
    }
  } finally {
    flipButton.disabled = false;
  }

  applyCamera(running.camera);
  running.sampler.reset();
  if (running.mode.kind === "calibrating") {
    running.mode = { kind: "idle" };
    calibrateButton.hidden = false;
    setStatus("Caméra changée — recommence la calibration.");
  }
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
  for (const button of [calibrateButton, newSetButton, finishButton, flipButton, measureButton]) {
    button.hidden = true;
  }
  measurement = null;
  measureButton.disabled = false;
  measureButton.textContent = "Mesurer 60 s";
  stage.classList.remove("mirrored");
  startButton.textContent = "Démarrer la caméra";
  setStatus("Arrêté.");
}

startButton.addEventListener("click", () => {
  if (running) stop();
  else void start();
});

flipButton.addEventListener("click", () => void flipCamera());

measureButton.addEventListener("click", startMeasurement);

diagToggle.addEventListener("click", () => showDiagnostics(diagOut.hidden));

diagCopy.addEventListener("click", () => {
  const text = report();
  diagOut.textContent = text;
  // The clipboard is a convenience; the panel is the guarantee. If copying is
  // refused — no permission, no secure context — the text is still on screen
  // and a screenshot carries it.
  void navigator.clipboard
    ?.writeText(text)
    .then(() => {
      diagCopy.textContent = "Copié";
      setTimeout(() => (diagCopy.textContent = "Copier"), 1500);
    })
    .catch(() => {
      diagCopy.textContent = "Copie refusée — capture l'écran";
    });
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

newSetButton.addEventListener("click", () => {
  if (!running || running.mode.kind !== "counting") return;
  running.mode.session.startSet("pull_up");
  setStatus(`Série ${running.mode.session.setCount} — vas-y.`);
});

finishButton.addEventListener("click", () => void finishSession());

// Releasing the camera on unload matters on mobile: a stream left open keeps the
// hardware busy and the indicator light on after the tab is gone.
window.addEventListener("pagehide", stop);

// Flush anything left over from a previous offline session before showing the
// history, so the chart reflects everything recorded rather than everything sent.
void sync.flush().then(reportPending).then(refreshProgress);

registerServiceWorker();
