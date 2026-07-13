import { useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import type { CanvasPosition, NodeRunResult, WorkflowEdge, WorkflowGraph, WorkflowNode, WorkflowVariable } from "../../../types";
import { createNodeRunMap } from "../../../workflow/runtimeResults.ts";
import { firstVisibleWorkflowNodeId } from "../../../workflow/visibility.ts";
import type { CanvasEdge, CanvasNode } from "../types.ts";
import { isV2WorkflowId } from "../../../workflow-v2/pageAdapter.ts";
import {
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
  selectedNodeId,
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
  selectedNodeId: string;
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

  useEffect(() => {
    flowNodesRef.current = flowNodes;
  }, [flowNodes]);

  useEffect(() => {
    if (isRestoringWorkspace) {
      hydratedWorkflowIdRef.current = null;
      setCanvasNodes([]);
      setFlowNodes([]);
      setFlowEdges([]);
      setWorkflowVariables([]);
      setStatus("Restoring current project...");
      return;
    }
    const baseNodes = workflow?.nodes?.length ? workflow.nodes : demoNodes;
    const isSameV2WorkflowRefresh = Boolean(
      workflow?.workflow_id &&
      hydratedWorkflowIdRef.current === workflow.workflow_id &&
      (isV2WorkflowId(workflow.workflow_id) || currentWorkflowIsV2()),
    );
    const currentFlowNodes = currentFlowNodesForWorkflow(baseNodes, flowNodesRef.current);
    const baseFlowNodes = mapWorkflowNodes(baseNodes, nodeRunByType, currentFlowNodes);
    const baseEdges = workflow?.edges?.length ? mapWorkflowEdges(workflow.edges, baseFlowNodes) : mapWorkflowEdges(demoEdges, baseFlowNodes);
    const baseLayoutNodes = isSameV2WorkflowRefresh
      ? baseFlowNodes
      : layoutNodes(baseFlowNodes, baseEdges, {
          preservePositionNodeIds: positionedNodeIds(baseNodes, currentFlowNodes),
        });
    const snapshot = loadSnapshot(workflowId);
    hydratedWorkflowIdRef.current = workflow?.workflow_id ?? null;

    if (!isSameV2WorkflowRefresh && snapshot?.nodes?.length && isSnapshotCompatibleWithWorkflow(snapshot, workflow)) {
      const isCurrentV2Workflow = isV2WorkflowId(workflow?.workflow_id) || currentWorkflowIsV2();
      if (isCurrentV2Workflow) {
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

function positionedNodeIds(nodes: WorkflowNode[], flowNodes: CanvasNode[]) {
  const ids = new Set<string>();
  nodes.forEach((node) => {
    if (hasCanvasPosition(node.position)) ids.add(node.id);
  });
  flowNodes.forEach((node) => {
    if (hasCanvasPosition(node.position)) ids.add(node.id);
  });
  return ids;
}

function hasCanvasPosition(position?: CanvasPosition) {
  return Number.isFinite(position?.x) && Number.isFinite(position?.y);
}

function preserveSelectedNodeId(nodes: WorkflowNode[], selectedNodeId: string) {
  return nodes.some((node) => node.id === selectedNodeId)
    ? selectedNodeId
    : firstVisibleWorkflowNodeId(nodes, "prompt");
}
