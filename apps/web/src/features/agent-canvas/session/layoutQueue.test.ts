import { describe, expect, it, vi } from "vitest";

import { AgentCanvasLayoutQueue } from "./layoutQueue.ts";

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
});
