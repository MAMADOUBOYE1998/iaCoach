import { describe, expect, it, vi } from "vitest";

import type { SessionSummary } from "../types/contracts";
import { QUEUE_KEY, SessionSync, readQueue, type QueueStorage } from "./sync";

class MemoryStorage implements QueueStorage {
  private readonly data = new Map<string, string>();

  getItem(key: string): string | null {
    return this.data.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.data.set(key, value);
  }
}

function session(id: string): SessionSummary {
  return {
    session_id: id,
    athlete_id: "a1",
    started_at: "2026-08-01T09:00:00Z",
    duration_s: 600,
    sets: [],
  };
}

const ok = (): Response => new Response(null, { status: 200 });
const rejected = (): Response => new Response(null, { status: 422 });
const serverError = (): Response => new Response(null, { status: 503 });

describe("queue storage", () => {
  it("starts empty", () => {
    expect(readQueue(new MemoryStorage())).toEqual([]);
  });

  it("recovers from a corrupt entry instead of throwing forever", () => {
    const storage = new MemoryStorage();
    storage.setItem(QUEUE_KEY, "{not json");
    expect(readQueue(storage)).toEqual([]);
  });

  it("ignores a non-array payload", () => {
    const storage = new MemoryStorage();
    storage.setItem(QUEUE_KEY, '{"session_id":"s1"}');
    expect(readQueue(storage)).toEqual([]);
  });
});

describe("SessionSync.enqueue", () => {
  it("queues a session", () => {
    const sync = new SessionSync("http://api", new MemoryStorage());
    sync.enqueue(session("s1"));
    expect(sync.pending.map((s) => s.session_id)).toEqual(["s1"]);
  });

  it("replaces an earlier copy of the same session", () => {
    const sync = new SessionSync("http://api", new MemoryStorage());
    sync.enqueue(session("s1"));
    sync.enqueue({ ...session("s1"), duration_s: 900 });
    expect(sync.pending).toHaveLength(1);
    expect(sync.pending[0]!.duration_s).toBe(900);
  });
});

describe("SessionSync.flush", () => {
  it("sends and clears the queue", async () => {
    const storage = new MemoryStorage();
    const sync = new SessionSync("http://api", storage, vi.fn(async () => ok()));
    sync.enqueue(session("s1"));
    sync.enqueue(session("s2"));

    expect(await sync.flush()).toEqual({ sent: 2, retained: 0, discarded: 0 });
    expect(sync.pending).toEqual([]);
  });

  it("keeps sessions when the network is down", async () => {
    // The whole point of the queue: a session finished in a basement gym has to
    // survive until there is a connection.
    const failing = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    const sync = new SessionSync("http://api", new MemoryStorage(), failing);
    sync.enqueue(session("s1"));

    expect(await sync.flush()).toEqual({ sent: 0, retained: 1, discarded: 0 });
    expect(sync.pending).toHaveLength(1);
  });

  it("keeps sessions on a server error", async () => {
    const sync = new SessionSync("http://api", new MemoryStorage(), vi.fn(async () => serverError()));
    sync.enqueue(session("s1"));
    expect((await sync.flush()).retained).toBe(1);
  });

  it("discards a payload the server will never accept", async () => {
    // A 4xx says this body is unsendable. Retaining it would block every later
    // session behind it forever.
    const sync = new SessionSync("http://api", new MemoryStorage(), vi.fn(async () => rejected()));
    sync.enqueue(session("s1"));

    expect(await sync.flush()).toEqual({ sent: 0, retained: 0, discarded: 1 });
    expect(sync.pending).toEqual([]);
  });

  it("does not let one bad session block the others", async () => {
    const fetchImpl = vi.fn(async (_url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as SessionSummary;
      return body.session_id === "bad" ? rejected() : ok();
    });
    const sync = new SessionSync("http://api", new MemoryStorage(), fetchImpl as unknown as typeof fetch);
    sync.enqueue(session("bad"));
    sync.enqueue(session("good"));

    expect(await sync.flush()).toEqual({ sent: 1, retained: 0, discarded: 1 });
  });

  it("retries a retained session on the next flush", async () => {
    let online = false;
    const fetchImpl = vi.fn(async () => {
      if (!online) throw new TypeError("offline");
      return ok();
    });
    const sync = new SessionSync("http://api", new MemoryStorage(), fetchImpl as unknown as typeof fetch);
    sync.enqueue(session("s1"));

    await sync.flush();
    online = true;
    expect((await sync.flush()).sent).toBe(1);
    expect(sync.pending).toEqual([]);
  });
});

describe("SessionSync.debrief", () => {
  it("returns the debrief with its deterministic bounds", async () => {
    const payload = {
      coach: { diagnostic: "ok", confiance: "moyen" },
      load: { acute_reps: 20, chronic_reps_per_week: 18, ratio: 1.1, form_trend: 0, sessions_28d: 5 },
      constraints: { max_total_reps: 22, rationale: ["Progression plafonnée."] },
      adjustments: [],
    };
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify(payload), { status: 200 }));
    const sync = new SessionSync("http://api", new MemoryStorage(), fetchImpl as unknown as typeof fetch);
    const result = await sync.debrief("s1");
    expect(result?.coach.diagnostic).toBe("ok");
    // The bounds travel with the answer: the client never has to ask separately
    // what the model was allowed to prescribe.
    expect(result?.constraints.max_total_reps).toBe(22);
  });

  it("returns null when coaching is unavailable", async () => {
    // Offline-first: no API key, or no network, is a normal state. The
    // measurements still stand on their own.
    const sync = new SessionSync("http://api", new MemoryStorage(), vi.fn(async () => serverError()));
    expect(await sync.debrief("s1")).toBeNull();
  });

  it("throws on an unexpected status", async () => {
    const sync = new SessionSync(
      "http://api",
      new MemoryStorage(),
      vi.fn(async () => new Response(null, { status: 500 })) as unknown as typeof fetch,
    );
    await expect(sync.debrief("s1")).rejects.toThrow(/500/);
  });

  it("escapes the session id in the URL", async () => {
    const urls: string[] = [];
    const fetchImpl = (async (url: string) => {
      urls.push(url);
      return new Response("{}", { status: 200 });
    }) as unknown as typeof fetch;
    const sync = new SessionSync("http://api", new MemoryStorage(), fetchImpl);
    await sync.debrief("a/b?c");
    expect(urls[0]).toBe("http://api/sessions/a%2Fb%3Fc/debrief");
  });
});
