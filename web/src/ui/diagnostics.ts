/**
 * On-screen diagnostics.
 *
 * Everything needed to interpret a latency measurement has to be visible on the
 * phone itself. Without a computer there is no DevTools, so anything logged to
 * the console — the GPU renderer MediaPipe actually got, whether the model came
 * from the CDN or from our own origin — is unreachable, and a number without
 * those is not a measurement, it is a number.
 *
 * A single screenshot of this panel should be enough to fill a row in
 * docs/BENCHMARKS.md and to know it is trustworthy.
 */

/** Build identifier, injected by vite. Identifies which code a report describes. */
declare const __BUILD_SHA__: string;

export interface Sample {
  fps: number;
  latencyMs: number;
}

export interface Summary {
  frames: number;
  seconds: number;
  fpsP50: number;
  fpsP05: number;
  latencyP50: number;
  latencyP95: number;
}

/**
 * Linear-interpolated percentile.
 *
 * p95 latency matters more than the mean: a stall every twentieth frame is what
 * an athlete perceives as a stutter, and an average hides it completely.
 */
export function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const rank = (sorted.length - 1) * p;
  const low = Math.floor(rank);
  const high = Math.ceil(rank);
  const lo = sorted[low] ?? 0;
  if (low === high) return lo;
  const hi = sorted[high] ?? lo;
  return lo + (hi - lo) * (rank - low);
}

export function summarise(samples: Sample[], seconds: number): Summary {
  return {
    frames: samples.length,
    seconds,
    fpsP50: percentile(
      samples.map((s) => s.fps),
      0.5,
    ),
    // The 5th percentile of fps is the bad end — the same tail as p95 latency.
    fpsP05: percentile(
      samples.map((s) => s.fps),
      0.05,
    ),
    latencyP50: percentile(
      samples.map((s) => s.latencyMs),
      0.5,
    ),
    latencyP95: percentile(
      samples.map((s) => s.latencyMs),
      0.95,
    ),
  };
}

/**
 * Captures console output into a bounded ring buffer.
 *
 * MediaPipe reports the graph's GL context on the console and nowhere else
 * (`GL version: ... renderer: ...`). That line is the only direct evidence of
 * whether the GPU delegate was used or whether it silently fell back to CPU —
 * which changes what a latency figure means entirely.
 *
 * The original console methods are still called: this observes, it does not
 * replace.
 */
export function captureConsole(limit = 80): () => string[] {
  const lines: string[] = [];
  const methods = ["log", "info", "warn", "error"] as const;

  for (const method of methods) {
    const original = console[method].bind(console);
    console[method] = (...args: unknown[]): void => {
      original(...args);
      lines.push(`${method}: ${args.map(stringify).join(" ")}`);
      if (lines.length > limit) lines.shift();
    };
  }

  return () => [...lines];
}

function stringify(value: unknown): string {
  if (typeof value === "string") return value;
  if (value instanceof Error) return `${value.name}: ${value.message}`;
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}

/** Lines worth surfacing: GPU/graph state, and anything that failed. */
export function relevantLines(lines: string[]): string[] {
  const interesting = /gl version|renderer|graph|delegate|webgl|cdn|modèle|error|fail/i;
  return lines.filter((line) => interesting.test(line)).map(compactLine).slice(-6);
}

/**
 * Strips glog's prefix (`I0811 23:24:28.575000 2136208 gl_context.cc:407]`).
 *
 * Pure noise on a phone screen, and it costs a wrapped line each time — which
 * is the difference between a report that fits in one screenshot and one that
 * does not.
 */
export function compactLine(line: string): string {
  return line.replace(/([IWEF]\d{4} [\d:.]+ \d+ [\w.]+:\d+\] )/, "");
}

/**
 * The identifying half of a user-agent string.
 *
 * `Mozilla/5.0 (Linux; Android 16; SM-S942B) AppleWebKit/537.36 (KHTML, like
 * Gecko) Chrome/141.0.0.0 Mobile Safari/537.36` becomes
 * `Linux; Android 16; SM-S942B · Chrome/141`. Everything dropped is a fossil
 * every browser sends; what is kept — the device model and the engine version —
 * is what a benchmark row has to record.
 */
export function compactUserAgent(ua: string): string {
  const platform = /\(([^)]*)\)/.exec(ua)?.[1] ?? ua;
  const engine = /(Chrome|CriOS|Firefox|Version)\/(\d+)/.exec(ua);
  return engine ? `${platform} · ${engine[1]}/${engine[2]}` : platform;
}

/**
 * The GPU as the browser reports it.
 *
 * Independent of MediaPipe: it says what hardware is *available*, while the
 * captured console line says what was actually used. Both are reported because
 * a mismatch between them is exactly the failure worth catching.
 */
export function gpuRenderer(): string {
  const canvas = document.createElement("canvas");
  const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
  if (!gl) return "aucun contexte WebGL";
  const debug = gl.getExtension("WEBGL_debug_renderer_info");
  const renderer = debug
    ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)
    : gl.getParameter(gl.RENDERER);
  return String(renderer ?? "inconnu");
}

export interface ReportInput {
  modelSource: "local" | "cdn";
  facing: string;
  videoWidth: number;
  videoHeight: number;
  trackFrameRate: number | null;
  summary: Summary | null;
  consoleLines: string[];
}

/**
 * A plain-text report, sized to be legible in one screenshot and pasteable as
 * text. Text rather than JSON on purpose: it is read by a person on a phone.
 */
export function formatReport(input: ReportInput): string {
  const lines: string[] = [];
  lines.push(`build      ${__BUILD_SHA__}`);
  lines.push(`modèle     pose_landmarker_full (${input.modelSource})`);
  lines.push(`caméra     ${input.facing} · ${input.videoWidth}×${input.videoHeight}`
    + (input.trackFrameRate === null ? "" : ` · ${input.trackFrameRate} i/s`));
  lines.push(`gpu        ${gpuRenderer()}`);
  lines.push(`écran      ${window.screen.width}×${window.screen.height} @${devicePixelRatio}x`);
  lines.push(`appareil   ${compactUserAgent(navigator.userAgent)}`);

  if (input.summary) {
    const s = input.summary;
    lines.push("");
    lines.push(`mesure     ${s.frames} frames sur ${s.seconds.toFixed(0)} s`);
    lines.push(`fps        p50 ${s.fpsP50.toFixed(1)} · p05 ${s.fpsP05.toFixed(1)}`);
    lines.push(`ms/frame   p50 ${s.latencyP50.toFixed(1)} · p95 ${s.latencyP95.toFixed(1)}`);
  } else {
    lines.push("");
    lines.push("mesure     non lancée");
  }

  const relevant = relevantLines(input.consoleLines);
  if (relevant.length > 0) {
    lines.push("");
    lines.push("console");
    for (const line of relevant) lines.push(`  ${line.slice(0, 160)}`);
  }

  return lines.join("\n");
}
