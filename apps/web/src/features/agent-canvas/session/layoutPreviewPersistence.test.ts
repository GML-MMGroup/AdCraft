import { describe, expect, it, vi } from "vitest";

import type { CanvasLayoutPositionV2 } from "../../../types-v2.ts";
import { AgentCanvasLayoutQueue } from "./layoutQueue.ts";
import {
  persistAgentCanvasLayoutPreview,
} from "./layoutPreviewPersistence.ts";

function positions(prefix: "target" | "original"): CanvasLayoutPositionV2[] {
  return Array.from({ length: 205 }, (_, index) => ({
    node_id: `node-${index}`,
    x: prefix === "target" ? 1_000 + index : index,
    y: prefix === "target" ? 2_000 + index : index * 2,
  }));
}

describe("persistAgentCanvasLayoutPreview", () => {
  it("compensates all original positions before exposing a later target-batch failure", async () => {
    const target = positions("target");
    const original = positions("original");
    const saveError = new Error("Target batch 2 failed");
    const batches: CanvasLayoutPositionV2[][] = [];
    const flush = vi.fn(async (batch: CanvasLayoutPositionV2[]) => {
      batches.push(batch);
      if (batches.length === 2) throw saveError;
    });
    const queue = new AgentCanvasLayoutQueue(flush);

    await expect(persistAgentCanvasLayoutPreview({
      targetPositions: target,
      originalPositions: original,
      persistPositions: (next) => queue.enqueue(next),
    })).rejects.toBe(saveError);

    expect(batches).toEqual([
      target.slice(0, 200),
      target.slice(200),
      original.slice(0, 200),
      original.slice(200),
    ]);
  });

  it("keeps the primary error and adds bounded compensation detail", async () => {
    const primary = new Error("Primary layout save failed");
    const compensation = new Error(`Compensation failed ${"x".repeat(400)}`);
    const persistPositions = vi.fn()
      .mockRejectedValueOnce(primary)
      .mockRejectedValueOnce(compensation);

    await expect(persistAgentCanvasLayoutPreview({
      targetPositions: positions("target").slice(0, 1),
      originalPositions: positions("original").slice(0, 1),
      persistPositions,
    })).rejects.toMatchObject({
      message: expect.stringMatching(/^Primary layout save failed\. Server rollback also failed:/),
      cause: primary,
    });

    try {
      await persistAgentCanvasLayoutPreview({
        targetPositions: positions("target").slice(0, 1),
        originalPositions: positions("original").slice(0, 1),
        persistPositions: vi.fn()
          .mockRejectedValueOnce(primary)
          .mockRejectedValueOnce(compensation),
      });
    } catch (error) {
      expect((error as Error).message.length).toBeLessThanOrEqual(260);
    }
  });
});
