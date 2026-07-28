import { describe, expect, it, vi } from "vitest";

import { AgentCanvasAuthoringQueue } from "./authoringQueue.ts";

describe("AgentCanvasAuthoringQueue", () => {
  it("runs semantic mutations serially without blocking enqueue callers", async () => {
    const releases: Array<() => void> = [];
    const order: string[] = [];
    const queue = new AgentCanvasAuthoringQueue();

    const first = queue.enqueue("node-1", async () => {
      order.push("first-start");
      await new Promise<void>((resolve) => releases.push(resolve));
      order.push("first-end");
    });
    const second = queue.enqueue("node-2", async () => {
      order.push("second");
    });

    expect(order).toEqual(["first-start"]);
    releases.shift()?.();
    await Promise.all([first, second]);
    expect(order).toEqual(["first-start", "first-end", "second"]);
  });

  it("coalesces queued node positions while preserving the running write", async () => {
    let releaseFirst = () => {};
    const calls: string[] = [];
    const queue = new AgentCanvasAuthoringQueue();

    const first = queue.enqueue("position:node-1", async () => {
      calls.push("first");
      await new Promise<void>((resolve) => {
        releaseFirst = resolve;
      });
    }, { coalesce: true });
    const replaced = queue.enqueue("position:node-1", async () => {
      calls.push("stale");
    }, { coalesce: true });
    const latest = queue.enqueue("position:node-1", async () => {
      calls.push("latest");
    }, { coalesce: true });

    releaseFirst();
    await Promise.all([first, replaced, latest]);

    expect(calls).toEqual(["first", "latest"]);
  });

  it("continues after one mutation fails and reports the error", async () => {
    const onError = vi.fn();
    const queue = new AgentCanvasAuthoringQueue({ onError });

    await expect(queue.enqueue("broken", async () => {
      throw new Error("conflict");
    })).rejects.toThrow("conflict");
    await expect(queue.enqueue("next", async () => {})).resolves.toBeUndefined();

    expect(onError).toHaveBeenCalledTimes(1);
  });

  it("returns the semantic mutation result to its caller", async () => {
    const queue = new AgentCanvasAuthoringQueue();

    await expect(queue.enqueue("create-binding", async () => ({
      binding_id: "binding-1",
    }))).resolves.toEqual({
      binding_id: "binding-1",
    });
  });
});
