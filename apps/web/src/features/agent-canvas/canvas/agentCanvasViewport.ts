import type { Viewport } from "@xyflow/react";

export function viewportStorageKey(workflowId: string): string {
  return `adcraft:agent-canvas:viewport:${workflowId}`;
}

export function readAgentCanvasViewport(
  workflowId: string,
  storage: Pick<Storage, "getItem"> = window.localStorage,
): Viewport | null {
  try {
    const value = storage.getItem(viewportStorageKey(workflowId));
    if (!value) return null;
    const parsed = JSON.parse(value) as Partial<Viewport>;
    if (
      typeof parsed.x !== "number"
      || typeof parsed.y !== "number"
      || typeof parsed.zoom !== "number"
    ) return null;
    return { x: parsed.x, y: parsed.y, zoom: parsed.zoom };
  } catch {
    return null;
  }
}

export function writeAgentCanvasViewport(
  workflowId: string,
  viewport: Viewport,
  storage: Pick<Storage, "setItem"> = window.localStorage,
): void {
  try {
    storage.setItem(viewportStorageKey(workflowId), JSON.stringify(viewport));
  } catch {
    // Viewport persistence is disposable and must never block the canvas.
  }
}

type ViewportInstaller = {
  setViewport: (viewport: Viewport, options: { duration: number }) => Promise<unknown> | unknown;
  fitView: (options: {
    nodes: Array<{ id: string }>;
    padding: number;
    maxZoom: number;
    duration: number;
  }) => Promise<unknown> | unknown;
};

export async function installAgentCanvasWorkflowViewport({
  instance,
  workflowId,
  nodeIds,
  reducedMotion,
  storage = window.localStorage,
}: {
  instance: ViewportInstaller;
  workflowId: string;
  nodeIds: string[];
  reducedMotion: boolean;
  storage?: Pick<Storage, "getItem">;
}): Promise<"saved" | "fit" | "empty"> {
  const saved = readAgentCanvasViewport(workflowId, storage);
  if (saved) {
    await instance.setViewport(saved, { duration: 0 });
    return "saved";
  }
  if (!nodeIds.length) return "empty";
  await instance.fitView({
    nodes: nodeIds.map((id) => ({ id })),
    padding: 0.22,
    maxZoom: 1,
    duration: reducedMotion ? 0 : 350,
  });
  return "fit";
}
