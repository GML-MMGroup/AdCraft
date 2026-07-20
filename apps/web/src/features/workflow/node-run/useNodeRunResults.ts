import type { MediaStatus, NodeRunResult } from "../../../types.ts";
import type { CanvasNode } from "../types.ts";

export function useNodeRunResults() {
  function applyNodeRunsToCanvas(runs: NodeRunResult[]) {
    void runs;
  }
  function applyMediaStatusToCanvas(status: MediaStatus | null) {
    void status;
  }
  async function refreshSelectedNodeRun() {
    return null;
  }
  return { applyNodeRunsToCanvas, applyMediaStatusToCanvas, refreshSelectedNodeRun };
}
