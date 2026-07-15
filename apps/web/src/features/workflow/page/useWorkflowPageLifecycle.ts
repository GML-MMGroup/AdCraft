import { useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import type { ReactFlowInstance } from "@xyflow/react";
import type { CanvasPosition, NodeRunResult, WorkflowEdge, WorkflowGraph, WorkflowNode, WorkflowVariable } from "../../../types";
import { createNodeRunMap } from "../../../workflow/runtimeResults.ts";
import { firstVisibleWorkflowNodeId } from "../../../workflow/visibility.ts";
import type { CanvasEdge, CanvasNode } from "../types.ts";
import { isV2WorkflowId } from "../../../workflow-v2/pageAdapter.ts";
import {
  DEFAULT_LAYOUT_VIEWPORT_PADDING,
  hasCanvasNodeOverlap,
  layoutNodes,
  mapWorkflowEdges,
  mapWorkflowNodes,
  mergeNodeRuntimeData,
  normalizeFlowEdges,
  normalizeFlowNodes,
  syncWorkflowNodePositions,
} from "../canvas/workflowCanvasModel.ts";
import { applyV2SnapshotLayoutOnly } from "../workflowAutosave.ts";
import {
  clearSnapshot,
  isSnapshotCompatibleWithWorkflow,
  loadSnapshot,
} from "./workflowSnapshotModel.ts";

export function useWorkflowPageLifecycle({
  workflow,
  workflowId,
  workflowSchemaVersion,
  workflowV2IsV2,
  activeProjectId,
  isRestoringWorkspace,
  currentWorkflowIsV2,
  nodeRunByType,
  canvasNodes,
  flowNodes,
  flowEdges,
  selectedNodeId,
  reactFlow,
  demoNodes,
  demoEdges,
  setCanvasNodes,
  setFlowNodes,
  setFlowEdges,
  setWorkflowVariables,
  setSavedAt,
  setSelectedNodeId,
  setStatus,
  refreshWorkflowGraph,
  refreshMediaStatus,
  loadAgentConversations,
  setSelectedNodeRun,
}: {
  workflow?: WorkflowGraph | null;
  workflowId: string;
  workflowSchemaVersion?: unknown;
  workflowV2IsV2: boolean;
  activeProjectId?: string | null;
  isRestoringWorkspace: boolean;
  currentWorkflowIsV2: () => boolean;
  nodeRunByType: ReturnType<typeof createNodeRunMap>;
  canvasNodes: WorkflowNode[];
  flowNodes: CanvasNode[];
  flowEdges: CanvasEdge[];
  selectedNodeId: string;
  reactFlow: ReactFlowInstance<CanvasNode, CanvasEdge> | null;
  demoNodes: WorkflowGraph["nodes"];
  demoEdges: WorkflowEdge[];
  setCanvasNodes: Dispatch<SetStateAction<WorkflowNode[]>>;
  setFlowNodes: Dispatch<SetStateAction<CanvasNode[]>>;
  setFlowEdges: Dispatch<SetStateAction<CanvasEdge[]>>;
  setWorkflowVariables: Dispatch<SetStateAction<WorkflowVariable[]>>;
  setSavedAt: Dispatch<SetStateAction<string | null>>;
  setSelectedNodeId: Dispatch<SetStateAction<string>>;
  setStatus: Dispatch<SetStateAction<string>>;
  refreshWorkflowGraph: (workflowId: string) => Promise<unknown>;
  refreshMediaStatus: (workflowId: string) => Promise<unknown>;
  loadAgentConversations: () => Promise<unknown>;
  setSelectedNodeRun: Dispatch<SetStateAction<NodeRunResult | null>>;
}) {
  const flowNodesRef = useRef(flowNodes);
  const hydratedWorkflowIdRef = useRef<string | null>(null);
  const initialLayoutSourceRef = useRef<{ workflowId: string; source: "default" | "snapshot" } | null>(null);
  const measuredLayoutWorkflowIdRef = useRef<string | null>(null);

  useEffect(() => {
    flowNodesRef.current = flowNodes;
  }, [flowNodes]);

  useEffect(() => {
    if (isRestoringWorkspace) {
      hydratedWorkflowIdRef.current = null;
      initialLayoutSourceRef.current = null;
      measuredLayoutWorkflowIdRef.current = null;
      setCanvasNodes([]);
      setFlowNodes([]);
      setFlowEdges([]);
      setWorkflowVariables([]);
      setStatus("Restoring current project...");
      return;
    }
    const shouldUseDemoGraph = Boolean(!activeProjectId && !workflow);
    const baseNodes = workflow?.nodes?.length ? workflow.nodes : shouldUseDemoGraph ? demoNodes : [];
    const isSameV2WorkflowRefresh = Boolean(
      workflow?.workflow_id &&
      hydratedWorkflowIdRef.current === workflow.workflow_id &&
      (isV2WorkflowId(workflow.workflow_id) || currentWorkflowIsV2()),
    );
    const canReuseCurrentFlowNodes = hydratedWorkflowIdRef.current === workflow?.workflow_id;
    const currentFlowNodes = canReuseCurrentFlowNodes ? currentFlowNodesForWorkflow(baseNodes, flowNodesRef.current) : [];
    const baseFlowNodes = mapWorkflowNodes(baseNodes, nodeRunByType, currentFlowNodes);
    const baseEdges = workflow?.edges?.length
      ? mapWorkflowEdges(workflow.edges, baseFlowNodes)
      : shouldUseDemoGraph ? mapWorkflowEdges(demoEdges, baseFlowNodes) : [];
    const baseLayoutNodes = isSameV2WorkflowRefresh
      ? baseFlowNodes
      : layoutNodes(baseFlowNodes, baseEdges, {
          preservePositionNodeIds: positionedNodeIds(currentFlowNodes),
        });
    const snapshot = loadSnapshot(workflowId);
    hydratedWorkflowIdRef.current = workflow?.workflow_id ?? null;

    if (!isSameV2WorkflowRefresh && snapshot?.nodes?.length && isSnapshotCompatibleWithWorkflow(snapshot, workflow)) {
      const isCurrentV2Workflow = isV2WorkflowId(workflow?.workflow_id) || currentWorkflowIsV2();
      if (isCurrentV2Workflow) {
        initialLayoutSourceRef.current = { workflowId, source: "snapshot" };
        measuredLayoutWorkflowIdRef.current = null;
        const restored = applyV2SnapshotLayoutOnly(
          syncWorkflowNodePositions(baseNodes, baseLayoutNodes),
          baseLayoutNodes,
          snapshot,
        );
        setCanvasNodes(restored.nodes);
        setFlowNodes(restored.flowNodes);
        setFlowEdges(normalizeFlowEdges(snapshot.edges.length ? snapshot.edges : baseEdges, restored.flowNodes));
        setWorkflowVariables(workflow?.variables ?? []);
        setSavedAt(snapshot.savedAt);
        setSelectedNodeId((current) => isSameV2WorkflowRefresh ? preserveSelectedNodeId(restored.nodes, current) : firstVisibleWorkflowNodeId(restored.nodes, "prompt"));
        return;
      }
      const snapshotFlowNodes = normalizeFlowNodes(snapshot.flowNodes.length ? snapshot.flowNodes : mapWorkflowNodes(snapshot.nodes, nodeRunByType, []));
      setCanvasNodes(snapshot.nodes);
      setFlowNodes(snapshotFlowNodes);
      setFlowEdges(normalizeFlowEdges(snapshot.edges, snapshotFlowNodes));
      setWorkflowVariables(workflow?.variables ?? []);
      setSavedAt(snapshot.savedAt);
      setSelectedNodeId((current) => isSameV2WorkflowRefresh ? preserveSelectedNodeId(snapshot.nodes, current) : firstVisibleWorkflowNodeId(snapshot.nodes, "prompt"));
      return;
    }
    if (snapshot?.nodes?.length && workflow?.workflow_id) clearSnapshot(workflow.workflow_id);

    if (!isSameV2WorkflowRefresh) {
      initialLayoutSourceRef.current = { workflowId, source: "default" };
      measuredLayoutWorkflowIdRef.current = null;
    }
    setCanvasNodes(syncWorkflowNodePositions(baseNodes, baseLayoutNodes));
    setFlowNodes(baseLayoutNodes);
    setFlowEdges(baseEdges);
    setWorkflowVariables(workflow?.variables ?? []);
    setSelectedNodeId((current) => isSameV2WorkflowRefresh ? preserveSelectedNodeId(baseNodes, current) : firstVisibleWorkflowNodeId(baseNodes, "prompt"));
  }, [
    activeProjectId,
    currentWorkflowIsV2,
    demoEdges,
    demoNodes,
    isRestoringWorkspace,
    nodeRunByType,
    setCanvasNodes,
    setFlowEdges,
    setFlowNodes,
    setSavedAt,
    setSelectedNodeId,
    setStatus,
    setWorkflowVariables,
    workflow,
    workflowId,
  ]);

  useEffect(() => {
    const initialLayout = initialLayoutSourceRef.current;
    const isV2Workflow = isV2WorkflowId(workflow?.workflow_id) || currentWorkflowIsV2();
    if (!initialLayout || initialLayout.workflowId !== workflowId || !isV2Workflow) return;
    if (measuredLayoutWorkflowIdRef.current === workflowId) return;
    if (!flowNodes.length || !flowNodes.every(hasMeasuredCanvasDimensions)) return;

    const shouldReflow = initialLayout.source === "default" || hasCanvasNodeOverlap(flowNodes);
    measuredLayoutWorkflowIdRef.current = workflowId;
    if (!shouldReflow) return;

    const measuredLayoutNodes = layoutNodes(flowNodes, flowEdges);
    setCanvasNodes((nodes) => syncWorkflowNodePositions(nodes, measuredLayoutNodes));
    setFlowNodes(measuredLayoutNodes);
    window.requestAnimationFrame(() => reactFlow?.fitView({ padding: DEFAULT_LAYOUT_VIEWPORT_PADDING }));
  }, [currentWorkflowIsV2, flowEdges, flowNodes, reactFlow, setCanvasNodes, setFlowNodes, workflow?.workflow_id, workflowId]);

  useEffect(() => {
    setFlowNodes((current) => mergeNodeRuntimeData(current, canvasNodes, nodeRunByType));
  }, [canvasNodes, nodeRunByType, setFlowNodes]);

  useEffect(() => {
    if (!workflow?.workflow_id) return;
    void refreshWorkflowGraph(workflow.workflow_id);
    if (currentWorkflowIsV2()) return;
    void refreshMediaStatus(workflow.workflow_id);
  }, [
    currentWorkflowIsV2,
    refreshMediaStatus,
    refreshWorkflowGraph,
    workflow?.workflow_id,
    workflowSchemaVersion,
    workflowV2IsV2,
  ]);

  useEffect(() => {
    void loadAgentConversations();
  }, [workflow?.workflow_id, loadAgentConversations]);

  useEffect(() => {
    setSelectedNodeRun(null);
  }, [selectedNodeId, setSelectedNodeRun, workflow?.workflow_id]);
}

function currentFlowNodesForWorkflow(nodes: WorkflowNode[], flowNodes: CanvasNode[]) {
  const nodeIds = new Set(nodes.map((node) => node.id));
  return flowNodes.filter((node) => nodeIds.has(node.id) && hasCanvasPosition(node.position));
}

function positionedNodeIds(flowNodes: CanvasNode[]) {
  const ids = new Set<string>();
  flowNodes.forEach((node) => {
    if (hasCanvasPosition(node.position)) ids.add(node.id);
  });
  return ids;
}

function hasCanvasPosition(position?: CanvasPosition) {
  return Number.isFinite(position?.x) && Number.isFinite(position?.y);
}

function hasMeasuredCanvasDimensions(node: CanvasNode) {
  const measured = node as CanvasNode & {
    measured?: { width?: number | null; height?: number | null };
    width?: number | null;
    height?: number | null;
  };
  const width = measured.measured?.width ?? measured.width;
  const height = measured.measured?.height ?? measured.height;
  return Number.isFinite(width) && Number.isFinite(height);
}

function preserveSelectedNodeId(nodes: WorkflowNode[], selectedNodeId: string) {
  return nodes.some((node) => node.id === selectedNodeId)
    ? selectedNodeId
    : firstVisibleWorkflowNodeId(nodes, "prompt");
}
