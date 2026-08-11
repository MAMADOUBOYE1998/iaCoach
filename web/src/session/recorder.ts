/**
 * Accumulates `RepEvent`s into a `SessionSummary`.
 *
 * The recorder holds the whole session in memory during the workout and only
 * produces the summary at the end. Nothing here talks to the network — syncing
 * is `sync.ts`'s job, and keeping the two apart is what lets the session survive
 * a dead connection.
 */

import type { Exercise, RepEvent, SessionSummary, SetSummary } from "../types/contracts";

export interface RecorderClock {
  /** Wall-clock now, for the session's `started_at`. */
  now(): Date;
  /** Monotonic milliseconds, for durations. */
  elapsed(): number;
}

export const systemClock: RecorderClock = {
  now: () => new Date(),
  elapsed: () => performance.now(),
};

/**
 * A session in progress.
 *
 * Sets are opened explicitly rather than inferred from a rest gap: guessing
 * where a set ended from timing alone would silently merge two sets when the
 * athlete is quick, and split one when they pause to breathe.
 */
export class SessionRecorder {
  private readonly sets: SetSummary[] = [];
  private readonly startedAt: Date;
  private readonly startedElapsed: number;

  constructor(
    readonly sessionId: string,
    readonly athleteId: string,
    private readonly clock: RecorderClock = systemClock,
  ) {
    this.startedAt = clock.now();
    this.startedElapsed = clock.elapsed();
  }

  get setCount(): number {
    return this.sets.length;
  }

  get totalReps(): number {
    return this.sets.reduce((total, set) => total + set.reps.length, 0);
  }

  get validReps(): number {
    return this.sets.reduce(
      (total, set) => total + set.reps.filter((rep) => rep.counted).length,
      0,
    );
  }

  /** Whether anything worth persisting has been recorded. */
  get isEmpty(): boolean {
    return this.totalReps === 0;
  }

  startSet(exercise: Exercise): void {
    this.sets.push({ exercise, reps: [] });
  }

  addRep(event: RepEvent): void {
    if (this.sets.length === 0) this.startSet(event.exercise);
    const current = this.sets[this.sets.length - 1]!;
    // An exercise change mid-set means the classifier switched; that is a new
    // set by definition, not a mislabelled rep in the current one.
    if (current.exercise !== event.exercise) {
      this.startSet(event.exercise);
      this.sets[this.sets.length - 1]!.reps.push(event);
      return;
    }
    current.reps.push(event);
  }

  finish(options: { perceivedEffort?: number; notes?: string } = {}): SessionSummary {
    return {
      session_id: this.sessionId,
      athlete_id: this.athleteId,
      started_at: this.startedAt.toISOString(),
      duration_s: Math.max(0, (this.clock.elapsed() - this.startedElapsed) / 1000),
      // Empty sets happen when a set is opened and abandoned; they carry no
      // information and would only add noise to the coach payload.
      sets: this.sets.filter((set) => set.reps.length > 0),
      ...(options.perceivedEffort !== undefined
        ? { perceived_effort: options.perceivedEffort }
        : {}),
      ...(options.notes !== undefined ? { notes: options.notes } : {}),
    };
  }
}

export function newSessionId(): string {
  return crypto.randomUUID();
}
