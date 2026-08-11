/**
 * Client configuration.
 *
 * The backend is optional by design: without it, counting and form scoring still
 * work and sessions queue locally. Nothing here is required for the app to be
 * useful — that is the offline-first requirement, not a fallback path.
 */

const ATHLETE_KEY = "iacoach.athlete-id";

/**
 * Backend origin. Set `VITE_API_BASE` when the API is not on the dev default —
 * notably when testing from a phone, where `localhost` is the phone itself.
 */
export const API_BASE: string =
  (import.meta.env["VITE_API_BASE"] as string | undefined) ?? "http://localhost:8000";

/**
 * A stable per-device athlete id.
 *
 * v1 is single-athlete, but every stored row carries an `athlete_id` so moving
 * to multiple athletes is a migration rather than a rewrite. Generating and
 * keeping one now means that history is not retroactively unattributable.
 */
export function athleteId(storage: Storage = localStorage): string {
  const existing = storage.getItem(ATHLETE_KEY);
  if (existing) return existing;
  const fresh = crypto.randomUUID();
  storage.setItem(ATHLETE_KEY, fresh);
  return fresh;
}
