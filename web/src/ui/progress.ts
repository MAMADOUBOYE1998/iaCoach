/**
 * Progression chart.
 *
 * Hand-built SVG rather than a charting library: two series over a handful of
 * points does not justify 100 kB of dependency on the critical path of an app
 * whose whole premise is staying fast on a phone.
 *
 * Two lines, deliberately: the session mean and the best single rep. They tell
 * different stories — a set taken closer to failure drags the mean down while
 * the best rep holds, which is progress, not regression.
 */

import type { ProgressPoint } from "../types/contracts";

const WIDTH = 320;
const HEIGHT = 120;
const PADDING = 8;

const SVG_NS = "http://www.w3.org/2000/svg";

export interface Series {
  label: string;
  colour: string;
  values: number[];
}

export function seriesFor(points: ProgressPoint[]): Series[] {
  return [
    {
      label: "Meilleure rep",
      colour: "#4ade80",
      values: points.map((p) => p.best_rom),
    },
    {
      label: "Moyenne séance",
      colour: "#60a5fa",
      values: points.map((p) => p.mean_rom),
    },
  ];
}

/**
 * Maps unit values onto an SVG polyline.
 *
 * The y axis is pinned to [0, 1] rather than auto-scaled to the data. An
 * auto-scaled axis makes a 3% wobble look like a breakthrough, which is exactly
 * the misreading this project should not encourage.
 */
export function polylinePoints(values: number[]): string {
  if (values.length === 0) return "";
  if (values.length === 1) {
    const y = PADDING + (1 - (values[0] ?? 0)) * (HEIGHT - 2 * PADDING);
    return `${PADDING},${y} ${WIDTH - PADDING},${y}`;
  }
  const step = (WIDTH - 2 * PADDING) / (values.length - 1);
  return values
    .map((value, i) => {
      const x = PADDING + i * step;
      const y = PADDING + (1 - Math.max(0, Math.min(1, value))) * (HEIGHT - 2 * PADDING);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

export function renderProgress(container: HTMLElement, points: ProgressPoint[]): void {
  container.replaceChildren();

  if (points.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "Pas encore de séance enregistrée.";
    container.append(empty);
    return;
  }

  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${WIDTH} ${HEIGHT}`);
  svg.setAttribute("role", "img");
  svg.setAttribute(
    "aria-label",
    `Amplitude sur les ${points.length} dernières séances, meilleure rep et moyenne.`,
  );

  // Reference lines at the counting floor and at full range, so a reader can see
  // where "this rep counts" sits without decoding the axis.
  for (const [value, colour] of [
    [0.75, "rgba(251,191,36,0.35)"],
    [1.0, "rgba(255,255,255,0.12)"],
  ] as const) {
    const line = document.createElementNS(SVG_NS, "line");
    const y = PADDING + (1 - value) * (HEIGHT - 2 * PADDING);
    line.setAttribute("x1", String(PADDING));
    line.setAttribute("x2", String(WIDTH - PADDING));
    line.setAttribute("y1", String(y));
    line.setAttribute("y2", String(y));
    line.setAttribute("stroke", colour);
    line.setAttribute("stroke-dasharray", "3 3");
    svg.append(line);
  }

  for (const series of seriesFor(points)) {
    const polyline = document.createElementNS(SVG_NS, "polyline");
    polyline.setAttribute("points", polylinePoints(series.values));
    polyline.setAttribute("fill", "none");
    polyline.setAttribute("stroke", series.colour);
    polyline.setAttribute("stroke-width", "2");
    polyline.setAttribute("stroke-linejoin", "round");
    svg.append(polyline);
  }

  const legend = document.createElement("ul");
  legend.className = "legend";
  for (const series of seriesFor(points)) {
    const item = document.createElement("li");
    item.textContent = series.label;
    item.style.setProperty("--dot", series.colour);
    legend.append(item);
  }

  const latest = points[points.length - 1]!;
  const caption = document.createElement("p");
  caption.className = "muted";
  caption.textContent =
    `${points.length} séance(s) · dernière : ${latest.valid_reps}/${latest.total_reps} reps validées, ` +
    `meilleure amplitude ${Math.round(latest.best_rom * 100)}%.`;

  container.append(svg, legend, caption);
}
