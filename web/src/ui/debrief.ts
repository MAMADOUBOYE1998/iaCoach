/**
 * Renders the coach's debrief.
 *
 * The confidence level is shown, not hidden. A `faible` debrief built on shaky
 * measurements should look different from a confident one — presenting both the
 * same way would quietly launder uncertainty into advice.
 */

import type { CoachResponse } from "../types/contracts";

const CONFIDENCE_LABEL: Record<CoachResponse["confiance"], string> = {
  eleve: "Confiance élevée",
  moyen: "Confiance moyenne",
  faible: "Confiance faible — mesures peu fiables",
};

function section(title: string, body: Node): HTMLElement {
  const wrapper = document.createElement("section");
  const heading = document.createElement("h3");
  heading.textContent = title;
  wrapper.append(heading, body);
  return wrapper;
}

function list(items: string[]): HTMLUListElement {
  const ul = document.createElement("ul");
  ul.append(
    ...items.map((text) => {
      const li = document.createElement("li");
      li.textContent = text;
      return li;
    }),
  );
  return ul;
}

export function renderDebrief(container: HTMLElement, debrief: CoachResponse): void {
  container.replaceChildren();

  const badge = document.createElement("p");
  badge.className = `confidence confidence-${debrief.confiance}`;
  badge.textContent = CONFIDENCE_LABEL[debrief.confiance];

  const diagnostic = document.createElement("p");
  diagnostic.className = "diagnostic";
  diagnostic.textContent = debrief.diagnostic;

  container.append(badge, diagnostic);

  if (debrief.points_faibles.length > 0) {
    container.append(section("Points faibles", list(debrief.points_faibles)));
  }

  if (debrief.exercices_suggeres.length > 0) {
    const ul = document.createElement("ul");
    for (const exercise of debrief.exercices_suggeres) {
      const li = document.createElement("li");
      const name = document.createElement("strong");
      name.textContent = `${exercise.nom} — ${exercise.series_reps}`;
      const reason = document.createElement("span");
      reason.className = "muted";
      reason.textContent = ` ${exercise.raison}`;
      li.append(name, reason);
      ul.append(li);
    }
    container.append(section("Exercices suggérés", ul));
  }

  const next = debrief.seance_suivante;
  const nextBody = document.createElement("div");
  const focus = document.createElement("p");
  focus.textContent = `${next.focus} · ~${next.duree_estimee_min} min`;
  nextBody.append(focus);
  if (next.exercices.length > 0) {
    nextBody.append(list(next.exercices.map((e) => `${e.nom} — ${e.series_reps}`)));
  }
  container.append(section("Séance suivante", nextBody));
}

export function renderDebriefUnavailable(container: HTMLElement, reason: string): void {
  container.replaceChildren();
  const message = document.createElement("p");
  message.className = "muted";
  // The measurements are the product; the debrief is an addition to them. Saying
  // so keeps a missing debrief from reading as a lost session.
  message.textContent = `${reason} Ta séance est enregistrée : les mesures restent valables.`;
  container.append(message);
}
