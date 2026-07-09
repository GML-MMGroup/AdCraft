import { useState, type Dispatch, type SetStateAction } from "react";
import type { WorkflowVariable, WorkflowNode } from "../../../types";
import { firstVisibleWorkflowNodeId } from "../../../workflow/visibility";
import type { CanvasEdge, CanvasHistoryState, CanvasNode } from "../types";
import { normalizeFlowEdges, normalizeFlowNodes } from "./workflowCanvasModel";

export type WorkflowCanvasHistoryControllerArgs = {
  canvasNodes: WorkflowNode[];
  flowNodes: CanvasNode[];
  flowEdges: CanvasEdge[];
  workflowVariables: WorkflowVariable[];
  setCanvasNodes: Dispatch<SetStateAction<WorkflowNode[]>>;
  setFlowNodes: Dispatch<SetStateAction<CanvasNode[]>>;
  setFlowEdges: Dispatch<SetStateAction<CanvasEdge[]>>;
  setWorkflowVariables: Dispatch<SetStateAction<WorkflowVariable[]>>;
  setSelectedNodeId: Dispatch<SetStateAction<string>>;
  setStatus: Dispatch<SetStateAction<string>>;
};

export function useWorkflowCanvasHistory({
  canvasNodes,
  flowNodes,
  flowEdges,
  workflowVariables,
  setCanvasNodes,
  setFlowNodes,
  setFlowEdges,
  setWorkflowVariables,
  setSelectedNodeId,
  setStatus,
}: WorkflowCanvasHistoryControllerArgs) {
  const [canvasHistory, setCanvasHistory] = useState<CanvasHistoryState[]>([]);
  const [canvasFuture, setCanvasFuture] = useState<CanvasHistoryState[]>([]);

  function snapshotCanvasState(): CanvasHistoryState {
    return {
      nodes: canvasNodes,
      flowNodes,
      edges: flowEdges,
      variables: workflowVariables,
    };
  }

  function captureCanvasHistory() {
    const snapshot = snapshotCanvasState();
    setCanvasHistory((current) => [...current.slice(-29), snapshot]);
    setCanvasFuture([]);
  }

  function restoreCanvasState(snapshot: CanvasHistoryState) {
    const nextFlowNodes = normalizeFlowNodes(snapshot.flowNodes);
    setCanvasNodes(snapshot.nodes);
    setFlowNodes(nextFlowNodes);
    setFlowEdges(normalizeFlowEdges(snapshot.edges, nextFlowNodes));
    setWorkflowVariables(snapshot.variables);
    setSelectedNodeId(firstVisibleWorkflowNodeId(snapshot.nodes));
  }

  function undoCanvas() {
    const previous = canvasHistory[canvasHistory.length - 1];
    if (!previous) return;
    setCanvasFuture((current) => [snapshotCanvasState(), ...current.slice(0, 29)]);
    setCanvasHistory((current) => current.slice(0, -1));
    restoreCanvasState(previous);
    setStatus("Canvas undo applied");
  }

  function redoCanvas() {
    const next = canvasFuture[0];
    if (!next) return;
    setCanvasHistory((current) => [...current.slice(-29), snapshotCanvasState()]);
    setCanvasFuture((current) => current.slice(1));
    restoreCanvasState(next);
    setStatus("Canvas redo applied");
  }

  function clearCanvasHistory() {
    setCanvasHistory([]);
    setCanvasFuture([]);
  }

  return {
    state: {
      canvasHistory,
      canvasFuture,
    },
    actions: {
      snapshotCanvasState,
      captureCanvasHistory,
      restoreCanvasState,
      undoCanvas,
      redoCanvas,
      clearCanvasHistory,
    },
  };
}
