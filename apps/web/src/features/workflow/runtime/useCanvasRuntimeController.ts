import { useMemo, useState } from "react";
import type { CanvasEdge } from "../types.ts";
import type { CanvasRuntimeConnectionState, CanvasRuntimeEvent, CanvasRuntimeSnapshot, CanvasRuntimeStore } from "../../../workflow/canvasRuntime.ts";
import { initialCanvasRuntimeStore } from "../../../workflow/canvasRuntime.ts";

export function useCanvasRuntimeController(options: {
  workflowId?: string | null;
  edges?: CanvasEdge[];
  onEvent?: (workflowId: string, event: CanvasRuntimeEvent) => Promise<void> | void;
  onSnapshot?: (workflowId: string, snapshot: CanvasRuntimeSnapshot) => Promise<void> | void;
} = {}) {
  const [store] = useState<CanvasRuntimeStore>({ ...initialCanvasRuntimeStore });
  const [connectionState, setConnectionState] = useState<CanvasRuntimeConnectionState>("disconnected");
  const nodeStatusById = useMemo(() => new Map<string, string>(), []);
  const activeEdgeIds = useMemo(() => new Set<string>(), []);

  function start(nextWorkflowId: string) {
    setConnectionState(nextWorkflowId ? "connecting" : "disconnected");
  }
  function stop() {
    setConnectionState("disconnected");
  }
  function patchNodeStatus(nodeId: string | null | undefined, status: string | null | undefined) {
    if (nodeId && status) nodeStatusById.set(nodeId, status);
  }

  void options;
  return { store, connectionState, nodeStatusById, activeEdgeIds, start, stop, patchNodeStatus };
}
