import { describe, expect, it, vi } from "vitest";

import { AgentCanvasLayoutQueue } from "./layoutQueue.ts";

function deferred() {
  let resolve = () => {};
  const promise = new Promise<void>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

async function nextMicrotask() {
  await Promise.resolve();
  await Promise.resolve();
}

describe("AgentCanvasLayoutQueue", () => {
  it("runs independently and coalesces latest positions into bounded batches", async () => {
    let releaseFirst = () => {};
    const flush = vi.fn(async (positions) => {
      if (flush.mock.calls.length === 1) {
        await new Promise<void>((resolve) => {
          releaseFirst = resolve;
        });
      }
      return positions;
    });
    const queue = new AgentCanvasLayoutQueue(flush);

    const first = queue.enqueue([{ node_id: "node-1", x: 100, y: 80 }]);
    const stale = queue.enqueue([{ node_id: "node-2", x: 300, y: 80 }]);
    const latest = queue.enqueue([
      { node_id: "node-1", x: 180, y: 120 },
      { node_id: "node-2", x: 420, y: 120 },
    ]);

    expect(flush).toHaveBeenCalledTimes(1);
    releaseFirst();
    await Promise.all([first, stale, latest]);

    expect(flush).toHaveBeenCalledTimes(2);
    expect(flush.mock.calls[1]?.[0]).toEqual([
      { node_id: "node-2", x: 420, y: 120 },
      { node_id: "node-1", x: 180, y: 120 },
    ]);
  });

  it("splits more than 200 positions without losing the latest node value", async () => {
    const batches: unknown[][] = [];
    const queue = new AgentCanvasLayoutQueue(async (positions) => {
      batches.push(positions);
    });
    const positions = Array.from({ length: 205 }, (_, index) => ({
      node_id: `node-${index}`,
      x: index,
      y: index * 2,
    }));

    await queue.enqueue(positions);

    expect(batches.map((batch) => batch.length)).toEqual([200, 5]);
  });

  it("runs a preview transaction exclusively between prior and later position writes", async () => {
    const priorGate = deferred();
    const exclusiveGate = deferred();
    const events: string[] = [];
    const queue = new AgentCanvasLayoutQueue(async (positions) => {
      events.push(`positions:${positions.map(({ node_id }) => node_id).join(",")}`);
      if (positions.some(({ node_id }) => node_id === "prior-drag")) {
        await priorGate.promise;
      }
    });

    const prior = queue.enqueue([{ node_id: "prior-drag", x: 10, y: 10 }]);
    const preview = queue.runExclusive(async () => {
      events.push("preview:batch-1");
      await exclusiveGate.promise;
      events.push("preview:batch-2");
      return "saved";
    });
    const staleLater = queue.enqueue([{ node_id: "later-drag", x: 20, y: 20 }]);
    const latestLater = queue.enqueue([{ node_id: "later-drag", x: 30, y: 30 }]);

    await nextMicrotask();
    expect(events).toEqual(["positions:prior-drag"]);

    priorGate.resolve();
    await prior;
    await nextMicrotask();
    expect(events).toEqual(["positions:prior-drag", "preview:batch-1"]);

    exclusiveGate.resolve();
    await expect(preview).resolves.toBe("saved");
    await Promise.all([staleLater, latestLater]);

    expect(events).toEqual([
      "positions:prior-drag",
      "preview:batch-1",
      "preview:batch-2",
      "positions:later-drag",
    ]);
  });

  it("continues with later position writes after an exclusive transaction fails", async () => {
    const failure = new Error("preview failed");
    const events: string[] = [];
    const queue = new AgentCanvasLayoutQueue(async (positions) => {
      events.push(`positions:${positions[0]?.node_id}`);
    });

    const preview = queue.runExclusive(async () => {
      events.push("preview");
      throw failure;
    });
    const later = queue.enqueue([{ node_id: "later-drag", x: 20, y: 20 }]);

    await expect(preview).rejects.toBe(failure);
    await expect(later).resolves.toBeUndefined();
    expect(events).toEqual(["preview", "positions:later-drag"]);
  });

  it("keeps exclusive transactions isolated per workflow queue", async () => {
    const workflowAGate = deferred();
    const events: string[] = [];
    const workflowA = new AgentCanvasLayoutQueue(async () => {});
    const workflowB = new AgentCanvasLayoutQueue(async (positions) => {
      events.push(`workflow-b:${positions[0]?.node_id}`);
    });

    const previewA = workflowA.runExclusive(async () => {
      events.push("workflow-a:preview");
      await workflowAGate.promise;
    });
    const dragB = workflowB.enqueue([{ node_id: "node-b", x: 40, y: 40 }]);

    await dragB;
    expect(events).toEqual(["workflow-a:preview", "workflow-b:node-b"]);

    workflowAGate.resolve();
    await previewA;
  });
});
