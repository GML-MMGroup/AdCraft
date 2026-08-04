import { describe, expect, it, vi } from "vitest";

import { createSettledQueryResource, stableQueryKey } from "./settledQueryResource.ts";

describe("settled query resource", () => {
  it("uses deterministic keys and deduplicates concurrent reads", async () => {
    const resource = createSettledQueryResource();
    const load = vi.fn(async (_signal: AbortSignal) => "cover");

    const first = resource.get({ workflowId: "workflow-1", updatedAt: "2" }, () => load());
    const second = resource.get({ updatedAt: "2", workflowId: "workflow-1" }, () => load());

    expect(stableQueryKey({ b: 2, a: 1 })).toBe(stableQueryKey({ a: 1, b: 2 }));
    await expect(Promise.all([first, second])).resolves.toEqual(["cover", "cover"]);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("recovers from a failed request and lets invalidation replace an obsolete result", async () => {
    const resource = createSettledQueryResource();
    let resolveOld: ((value: string) => void) | undefined;
    const oldRead = resource.get("project-1", () => new Promise<string>((resolve) => { resolveOld = resolve; }));

    resource.invalidate("project-1");
    const nextRead = resource.get("project-1", async () => "fresh");
    resolveOld?.("stale");

    await expect(oldRead).resolves.toBe("stale");
    await expect(nextRead).resolves.toBe("fresh");
    await expect(resource.get("project-1", async () => "wrong")).resolves.toBe("fresh");

    await expect(resource.get("recover", async () => { throw new Error("temporary"); })).rejects.toThrow("temporary");
    await expect(resource.get("recover", async () => "recovered")).resolves.toBe("recovered");
  });

  it("clears every settled value when invalidated without a key", async () => {
    const resource = createSettledQueryResource();
    await resource.get("first", async () => "first");
    await resource.get("second", async () => "second");

    resource.invalidate();

    await expect(resource.get("first", async () => "new first")).resolves.toBe("new first");
    await expect(resource.get("second", async () => "new second")).resolves.toBe("new second");
  });

  it("expires settled values after the configured TTL", async () => {
    let now = 0;
    const resource = createSettledQueryResource<string>({
      ttlMs: 100,
      now: () => now,
    });
    const load = vi.fn(async () => "fresh");

    await expect(resource.get("asset", load)).resolves.toBe("fresh");
    now = 99;
    await expect(resource.get("asset", async () => "wrong")).resolves.toBe("fresh");
    now = 100;
    await expect(resource.get("asset", load)).resolves.toBe("fresh");

    expect(load).toHaveBeenCalledTimes(2);
  });

  it("evicts the least-recently-used settled value at its configured capacity", async () => {
    let now = 0;
    const resource = createSettledQueryResource<string>({
      maxEntries: 2,
      now: () => now,
    });

    await resource.get("first", async () => "first");
    now += 1;
    await resource.get("second", async () => "second");
    now += 1;
    await expect(resource.get("first", async () => "wrong")).resolves.toBe("first");
    now += 1;
    await resource.get("third", async () => "third");

    await expect(resource.get("first", async () => "wrong")).resolves.toBe("first");
    await expect(resource.get("second", async () => "second reloaded")).resolves.toBe("second reloaded");
  });

  it("does not let pending work consume settled-cache capacity", async () => {
    const resource = createSettledQueryResource<string>({ maxEntries: 2 });
    await resource.get("first", async () => "first");
    await resource.get("second", async () => "second");
    const pending = resource.subscribe("pending", () => new Promise<string>(() => {}));

    await expect(resource.get("first", async () => "wrong")).resolves.toBe("first");
    await expect(resource.get("second", async () => "wrong")).resolves.toBe("second");

    pending.release();
  });

  it("aborts an evicted pending entry when its final subscriber releases", () => {
    const resource = createSettledQueryResource();
    let signal: AbortSignal | undefined;
    const subscription = resource.subscribe("pending", (nextSignal) => {
      signal = nextSignal;
      return new Promise<string>(() => {});
    });

    resource.evict("pending");
    expect(signal?.aborted).toBe(false);
    subscription.release();

    expect(signal?.aborted).toBe(true);
  });
});
