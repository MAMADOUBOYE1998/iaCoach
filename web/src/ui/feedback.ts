/**
 * Renders a `RepEvent` for the athlete.
 *
 * Flags are stored as machine-readable codes and translated here, at the edge.
 * Storing French in the database would make the data unusable for anything but
 * this UI.
 *
 * The wording is deliberately specific and quantified: "tu ne descends pas assez
 * bas" is what separates this from a rep counter that says "invalide".
 */

import type { RepEvent } from "../types/contracts";

const FLAG_MESSAGES: Record<string, string> = {
  rom_short: "Amplitude incomplète : monte plus haut, ou descends bras tendus.",
  kipping: "Élan des jambes détecté : garde le bassin gainé.",
  asymmetry: "Un bras tire plus que l'autre.",
  jerky: "Montée saccadée : cherche une vitesse régulière.",
  trunk_swing: "Le buste balance : gaine davantage.",
  low_confidence:
    "Suivi peu fiable sur cette rep — recadre-toi. Aucune correction ne peut être donnée sur ces images.",
};

export interface ScoreLine {
  label: string;
  value: number;
}

export function scoreLines(event: RepEvent): ScoreLine[] {
  return [
    { label: "Amplitude", value: event.scores.rom },
    { label: "Symétrie", value: event.scores.symmetry },
    { label: "Sans élan", value: event.scores.kipping },
    { label: "Régularité", value: event.scores.tempo_control },
    { label: "Alignement", value: event.scores.alignment },
  ];
}

/**
 * One actionable sentence, or a plain confirmation.
 *
 * Only the worst issue is surfaced: a list of five corrections between reps is
 * not something anyone can act on mid-set. The rest is kept in the RepEvent for
 * the end-of-session debrief.
 */
export function feedbackFor(event: RepEvent): string {
  if (event.flags.length === 0) {
    return event.counted ? "Rep propre." : "Rep enregistrée.";
  }
  // FLAG_MESSAGES is ordered by how much the issue matters mid-set; the counter
  // emits flags in that same order, so the first one is the one to say.
  const first = event.flags[0];
  return (first && FLAG_MESSAGES[first]) ?? "Rep enregistrée.";
}

export function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}
