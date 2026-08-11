/**
 * TypeScript mirror of `backend/src/iacoach/contracts.py`.
 *
 * The Pydantic models are the source of truth. This file is hand-written and
 * kept in sync against the JSON Schema exported to `contracts/schema/`; CI fails
 * if the schemas are stale relative to the Python models, which is the signal
 * that this file needs updating too.
 *
 * Field names stay English. Only `CoachResponse` uses French keys, because those
 * strings surface directly in the UI.
 */

export type Exercise =
  | "pull_up"
  | "chin_up"
  | "dip"
  | "push_up"
  | "squat"
  | "muscle_up"
  | "l_sit"
  | "unknown";

export type RepPhase = "idle" | "eccentric" | "bottom" | "concentric" | "top";

/** A normalised score in [0, 1]. 1.0 = ideal. Never a boolean. */
export type Unit = number;

export interface Anthropometry {
  height_m: number;
  mass_kg?: number | null;
  arm_span_m?: number | null;
}

export interface ExerciseCalibration {
  exercise: Exercise;
  joint: string;
  rom_min_deg: number;
  rom_max_deg: number;
  captured_at: string;
  confidence: Unit;
}

export interface AthleteProfile {
  athlete_id: string;
  level: "debutant" | "intermediaire" | "avance";
  goals: string[];
  constraints: string[];
  anthropometry?: Anthropometry | null;
  calibrations: ExerciseCalibration[];
}

export interface Tempo {
  eccentric_s: number;
  bottom_pause_s: number;
  concentric_s: number;
  top_pause_s: number;
}

export interface FormScores {
  rom: Unit;
  symmetry: Unit;
  kipping: Unit;
  tempo_control: Unit;
  alignment: Unit;
}

export interface RepEvent {
  rep_index: number;
  exercise: Exercise;
  started_at_ms: number;
  duration_ms: number;
  tempo: Tempo;
  scores: FormScores;
  peak_angle_deg: number;
  min_angle_deg: number;
  confidence: Unit;
  counted: boolean;
  flags: string[];
}

export interface SetSummary {
  exercise: Exercise;
  reps: RepEvent[];
}

export interface SessionSummary {
  session_id: string;
  athlete_id: string;
  started_at: string;
  duration_s: number;
  sets: SetSummary[];
  perceived_effort?: number | null;
  notes?: string | null;
}

export interface HistoryPoint {
  date: string;
  exercise: Exercise;
  total_reps: number;
  valid_reps: number;
  mean_rom: Unit;
  mean_form: Unit;
}

export interface CoachRequest {
  athlete: AthleteProfile;
  session: SessionSummary;
  history: HistoryPoint[];
}

export interface SuggestedExercise {
  nom: string;
  raison: string;
  series_reps: string;
}

export interface NextSession {
  focus: string;
  exercices: SuggestedExercise[];
  duree_estimee_min: number;
}

export interface CoachResponse {
  diagnostic: string;
  points_faibles: string[];
  exercices_suggeres: SuggestedExercise[];
  seance_suivante: NextSession;
  confiance: "eleve" | "moyen" | "faible";
}

/**
 * Corrections are suppressed below this. Mirrors the Python side: a wrong
 * correction is worse than none, so a low-confidence rep is recorded and shown
 * but never coached on.
 */
export const MIN_COACHABLE_CONFIDENCE = 0.7;
