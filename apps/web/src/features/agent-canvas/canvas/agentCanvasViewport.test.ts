import { describe, expect, it, vi } from "vitest";

import {
  installAgentCanvasWorkflowViewport,
  viewportStorageKey,
} from "./agentCanvasViewport.ts";

function memoryStorage(initial: Record<string, string> = {}): Storage {
  const values = new Map(Object.entries(initial));
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => Array.from(values.keys())[index] ?? null,
    removeItem: (key) => { values.delete(key); },
    setItem: (key, value) => { values.set(key, value); },
  };
}

describe("installAgentCanvasWorkflowViewport", () => {
  it("installs the selected workflow's saved viewport without fitting old nodes", async () => {
    const setViewport = vi.fn().mockResolvedValue(true);
    const fitView = vi.fn();
    const storage = memoryStorage({
      [viewportStorageKey("workflow-new")]: JSON.stringify({ x: 18, y: -32, zoom: 0.8 }),
    });

    await installAgentCanvasWorkflowViewport({
      instance: { setViewport, fitView },
      workflowId: "workflow-new",
      nodeIds: ["new-node"],
      reducedMotion: false,
      storage,
    });

    expect(setViewport).toHaveBeenCalledWith({ x: 18, y: -32, zoom: 0.8 }, { duration: 0 });
    expect(fitView).not.toHaveBeenCalled();
  });

  it("fits only the new workflow nodes when no saved viewport exists", async () => {
    const setViewport = vi.fn();
    const fitView = vi.fn().mockResolvedValue(true);

    await installAgentCanvasWorkflowViewport({
      instance: { setViewport, fitView },
      workflowId: "workflow-new",
      nodeIds: ["new-a", "new-b"],
      reducedMotion: true,
      storage: memoryStorage(),
    });

    expect(setViewport).not.toHaveBeenCalled();
    expect(fitView).toHaveBeenCalledWith({
      nodes: [{ id: "new-a" }, { id: "new-b" }],
      padding: 0.22,
      maxZoom: 1,
      duration: 0,
    });
  });

  it("reuses one mounted canvas while replacing the old workflow viewport with the new one", async () => {
    const setViewport = vi.fn().mockResolvedValue(true);
    const fitView = vi.fn();
    const storage = memoryStorage({
      [viewportStorageKey("workflow-old")]: JSON.stringify({ x: 10, y: 20, zoom: 0.5 }),
      [viewportStorageKey("workflow-new")]: JSON.stringify({ x: -80, y: 45, zoom: 0.9 }),
    });
    const instance = { setViewport, fitView };

    await installAgentCanvasWorkflowViewport({
      instance,
      workflowId: "workflow-old",
      nodeIds: ["old-node"],
      reducedMotion: false,
      storage,
    });
    await installAgentCanvasWorkflowViewport({
      instance,
      workflowId: "workflow-new",
      nodeIds: ["new-node"],
      reducedMotion: false,
      storage,
    });

    expect(setViewport.mock.calls).toEqual([
      [{ x: 10, y: 20, zoom: 0.5 }, { duration: 0 }],
      [{ x: -80, y: 45, zoom: 0.9 }, { duration: 0 }],
    ]);
    expect(fitView).not.toHaveBeenCalled();
  });
});
