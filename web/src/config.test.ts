import { describe, expect, it } from "vitest";

import { athleteId, preferredFacing, rememberFacing } from "./config";
import { otherFacing } from "./pose/camera";

function memoryStorage(seed: Record<string, string> = {}): Storage {
  const map = new Map(Object.entries(seed));
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => void map.set(key, value),
    removeItem: (key: string) => void map.delete(key),
    clear: () => map.clear(),
    key: (i: number) => [...map.keys()][i] ?? null,
    get length() {
      return map.size;
    },
  };
}

describe("athleteId", () => {
  it("is stable across calls", () => {
    const storage = memoryStorage();
    expect(athleteId(storage)).toBe(athleteId(storage));
  });

  it("keeps an existing id rather than minting a new one", () => {
    // Losing it would make every past session unattributable.
    const storage = memoryStorage({ "iacoach.athlete-id": "a-1" });
    expect(athleteId(storage)).toBe("a-1");
  });
});

describe("preferredFacing", () => {
  it("defaults to the front camera", () => {
    // You cannot frame yourself in a preview you cannot see.
    expect(preferredFacing(memoryStorage())).toBe("user");
  });

  it("round-trips a choice", () => {
    const storage = memoryStorage();
    rememberFacing("environment", storage);
    expect(preferredFacing(storage)).toBe("environment");
    rememberFacing("user", storage);
    expect(preferredFacing(storage)).toBe("user");
  });

  it("falls back to the default on a junk value", () => {
    const storage = memoryStorage({ "iacoach.camera-facing": "sideways" });
    expect(preferredFacing(storage)).toBe("user");
  });
});

describe("otherFacing", () => {
  it("is its own inverse", () => {
    expect(otherFacing("user")).toBe("environment");
    expect(otherFacing(otherFacing("user"))).toBe("user");
  });
});
