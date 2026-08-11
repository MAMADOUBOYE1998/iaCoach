/**
 * Offline-first session sync.
 *
 * Counting and form scoring never depend on the network, so a session finished
 * in a basement gym has to survive until there is one. Sessions are queued
 * locally and flushed opportunistically.
 *
 * The API is idempotent on `session_id`, so a retry we are not sure landed is
 * safe to send again — at-least-once is the delivery model on both sides.
 */

import type { SessionDebrief, SessionSummary } from "../types/contracts";

export const QUEUE_KEY = "iacoach.pending-sessions";

export interface QueueStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export interface FlushResult {
  sent: number;
  /** Kept for a later attempt — the network was the problem, not the payload. */
  retained: number;
  /** Dropped as unsendable; see `SessionSync.flush`. */
  discarded: number;
}

/**
 * Reads and writes the pending queue.
 *
 * A corrupt or hand-edited entry must not wedge the queue forever, so parsing
 * failures reset it rather than throwing on every subsequent flush.
 */
export function readQueue(storage: QueueStorage): SessionSummary[] {
  const raw = storage.getItem(QUEUE_KEY);
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as SessionSummary[]) : [];
  } catch {
    return [];
  }
}

export function writeQueue(storage: QueueStorage, sessions: SessionSummary[]): void {
  storage.setItem(QUEUE_KEY, JSON.stringify(sessions));
}

export class SessionSync {
  constructor(
    private readonly baseUrl: string,
    private readonly storage: QueueStorage,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  get pending(): SessionSummary[] {
    return readQueue(this.storage);
  }

  /** Queue a session. Replaces any earlier copy of the same session. */
  enqueue(summary: SessionSummary): void {
    const queue = readQueue(this.storage).filter(
      (item) => item.session_id !== summary.session_id,
    );
    queue.push(summary);
    writeQueue(this.storage, queue);
  }

  /**
   * Try to send everything queued.
   *
   * A rejected payload (HTTP 4xx) is **discarded**, not retried: the server has
   * told us this body will never be accepted, and keeping it would block every
   * later session behind it forever. A network failure or 5xx is retained —
   * that one is worth trying again.
   */
  async flush(): Promise<FlushResult> {
    const queue = readQueue(this.storage);
    const retained: SessionSummary[] = [];
    let sent = 0;
    let discarded = 0;

    for (const summary of queue) {
      try {
        const response = await this.fetchImpl(`${this.baseUrl}/sessions`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(summary),
        });
        if (response.ok) {
          sent += 1;
        } else if (response.status >= 400 && response.status < 500) {
          console.error(
            `Session ${summary.session_id} rejected (${response.status}); dropping it.`,
          );
          discarded += 1;
        } else {
          retained.push(summary);
        }
      } catch {
        retained.push(summary);
      }
    }

    writeQueue(this.storage, retained);
    return { sent, retained: retained.length, discarded };
  }

  /**
   * Ask the backend to debrief a session.
   *
   * Returns `null` when the coaching layer is unavailable (503) — the caller
   * shows the measurements without a debrief. The session data is the product;
   * the debrief is an addition to it.
   */
  async debrief(sessionId: string): Promise<SessionDebrief | null> {
    const response = await this.fetchImpl(
      `${this.baseUrl}/sessions/${encodeURIComponent(sessionId)}/debrief`,
      { method: "POST" },
    );
    if (response.status === 503) return null;
    if (!response.ok) throw new Error(`Debrief failed: HTTP ${response.status}`);
    return (await response.json()) as SessionDebrief;
  }
}
