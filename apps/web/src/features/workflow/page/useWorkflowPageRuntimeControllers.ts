import { useMemo } from "react";
import { LOCAL_WORKFLOW_ID } from "./workflowSnapshotModel.ts";
import { useCanvasRuntimeEventController } from "../runtime/useCanvasRuntimeEventController.ts";
import { useV2RuntimeController } from "../runtime/useV2RuntimeController.ts";
import { useV2ObservableRunActions } from "../v2/operations/useV2ObservableRunActions.ts";
import { useWorkflowV2Controller } from "../v2/useWorkflowV2Controller.ts";
import {
  v2RuntimeActiveEdgeSourceNodeIds,
  v2RuntimeNodeStatusById,
  v2RuntimeSlotStatusById,
} from "../../../workflow-v2/runtime.ts";
import { shouldApplyWorkflowScopedResult } from "../../../workflow/sessionGuards.ts";
import { finalCompositionErrorMessage } from "../runtime/workflowExecutionViewModel.ts";
import { firstVisibleWorkflowNodeId, isUserVisibleWorkflowNode } from "../../../workflow/visibility.ts";
import { mapWorkflowEdges, mapWorkflowNodes } from "../canvas/workflowCanvasModel.ts";
import type { CanvasNode } from "../types.ts";

// Adapter value bag used while the page model is being decomposed into stable controllers.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type WorkflowPageRuntimeControllersArgs = Record<string, any>;

const ACTIVE_V2_EXECUTION_STATUSES = new Set(["queued", "running", "waiting", "pending", "processing", "in_progress"]);
const TERMINAL_V2_EXECUTION_STATUSES = new Set(["completed", "complete", "success", "succeeded", "failed", "error", "cancelled", "canceled", "partial_failed", "timeout", "timed_out", "done", "finish", "finished"]);

function hasActiveV2Runtime(runtime: {
  active_execution_id?: string | null;
  execution_status?: string | null;
  running_node_ids?: string[];
  waiting_node_ids?: string[];
  running_slot_ids?: string[];
  waiting_slot_ids?: string[];
}) {
  const executionStatus = String(runtime.execution_status ?? "").toLowerCase();
  return Boolean(
    runtime.running_node_ids?.length ||
      runtime.waiting_node_ids?.length ||
      runtime.running_slot_ids?.length ||
      runtime.waiting_slot_ids?.length ||
      ACTIVE_V2_EXECUTION_STATUSES.has(executionStatus) ||
      (runtime.active_execution_id && !TERMINAL_V2_EXECUTION_STATUSES.has(executionStatus)),
  );
}

export function useWorkflowPageRuntimeControllers(args: WorkflowPageRuntimeControllersArgs) {
  const canvasRuntimeEvents = useCanvasRuntimeEventController({
    localWorkflowId: LOCAL_WORKFLOW_ID,
    activeWorkflowIdRef: args.activeWorkflowIdRef,
    selectedNodeIdRef: args.selectedNodeIdRef,
    getActiveConversationId: () => args.activeConversationId,
    getRevisionHistoryTarget: () => args.revisionHistoryTarget,
    getV2SlotVersionsById: () => args.v2SlotVersionsById,
    getActiveV2SlotId: () => args.v2SlotMicroEdit.state.openSlotId,
    getWorkflowV2: () => args.workflowV2Model.workflowV2,
    currentWorkflowIsV2: args.currentWorkflowIsV2,
    v2Runtime: {
      syncSnapshot: async (requestWorkflowId: string) => {
        await args.v2RuntimeRef.current?.syncSnapshot(requestWorkflowId);
      },
      slotNodeId: (slotId: string) => args.v2RuntimeRef.current?.store.slotNodeIds[slotId] ?? null,
    },
    setActiveExecutionId: args.setActiveExecutionId,
    setExecutionPollingState: args.setExecutionPollingState,
    setWorkflowRunning: args.setWorkflowRunning,
    setStatus: args.setStatus,
    setRunningNodeIds: args.setRunningNodeIds,
    setMediaStatus: args.setMediaStatus,
    setCanvasCandidateSummaryByNodeId: args.setCanvasCandidateSummaryByNodeId,
    setLocalRevisionByKey: args.setLocalRevisionByKey,
    setQualityOverrideRevisionId: args.setQualityOverrideRevisionId,
    setV2ProviderTaskRefreshKeyBySlotId: args.setV2ProviderTaskRefreshKeyBySlotId,
    setSelectedNodeRun: args.setSelectedNodeRun,
    onApplySnapshotGraph: (graph) => {
      args.setWorkflow(graph);
      args.syncWorkflowAdRequest(graph);
      args.setCanvasNodes(graph.nodes);
      args.setWorkflowVariables(graph.variables ?? []);
      args.setFlowNodes((current: CanvasNode[]) => {
        const nextFlowNodes = mapWorkflowNodes(graph.nodes, args.nodeRunByType, current);
        args.setFlowEdges(mapWorkflowEdges(graph.edges, nextFlowNodes));
        return nextFlowNodes;
      });
      args.setSelectedNodeId((current: string | null) =>
        current && graph.nodes.some((node) => node.id === current && isUserVisibleWorkflowNode(node))
          ? current
          : firstVisibleWorkflowNodeId(graph.nodes),
      );
      args.setSavedAt(graph.updated_at ?? new Date().toISOString());
    },
    onApplyMediaStatusToCanvas: args.applyMediaStatusToCanvas,
    onPatchNodeStatus: (nodeId, nextStatus) => {
      if (!nodeId || !nextStatus) return;
      args.setCanvasNodes((current: Array<{ id: string; status?: string }>) => current.map((node) => (node.id === nodeId ? { ...node, status: nextStatus } : node)));
      args.setFlowNodes((current: Array<{ id: string; data: Record<string, unknown> }>) => current.map((node) => (node.id === nodeId ? { ...node, data: { ...node.data, status: nextStatus } } : node)));
    },
    onApplyNodeRunsToCanvas: args.applyNodeRunsToCanvas,
    onClearNodeDebugCache: args.clearNodeDebugCache,
    onRefreshSelectedResolvedInputs: args.refreshSelectedResolvedInputs,
    onRefreshWorkflowGraph: args.refreshWorkflowGraph,
    onRefreshMediaStatus: args.refreshMediaStatus,
    onRefreshV2WorkflowGraph: args.refreshV2WorkflowGraph,
    onRefreshV2AssetsAndRetryMissing: args.refreshV2AssetsAndRetryMissing,
    onLoadV2SlotVersions: (slotId) => args.v2SlotOperationsRef.current?.actions.loadV2SlotVersions(slotId),
    onLoadLocalAssetHistory: (workflowId, nodeId, asset) => args.localRevisionOperationsRef.current?.actions.loadLocalAssetHistory(workflowId, nodeId, asset) ?? Promise.resolve(null),
    onApplyLocalRevisionState: (key, revision) => args.localRevisionOperationsRef.current?.actions.applyLocalRevisionState(key, revision),
    onUpdateLocalRevisionCardState: (key, patch) => args.localRevisionOperationsRef.current?.actions.updateLocalRevisionCardState(key, patch),
    onNoteAffected: args.noteAffected,
    onTimelineLoadStarted: args.timelineLoadStarted,
    onTimelineLoadFailed: args.timelineLoadFailed,
    onApplyFinalCompositionTimelineResponse: args.applyFinalCompositionTimelineResponse,
    onMarkTimelineEventDirty: args.markTimelineEventDirty,
    onTimelineRenderStarted: args.timelineRenderStarted,
    onTimelineRenderFailed: args.timelineRenderFailed,
    onTimelineRenderFinished: args.timelineRenderFinished,
    finalCompositionErrorMessage,
    onAppendConversationEventForConversation: args.appendConversationEventForConversation,
    onHandleAgentConversationEvents: args.handleAgentConversationEvents,
    onHandleNodePromptUpdatedEvent: args.handleNodePromptUpdatedEvent,
    onHandleItemPromptUpdatedEvent: args.handleItemPromptUpdatedEvent,
    onHandleRevisionConversationEvent: args.handleRevisionConversationEvent,
  });

  const v2Runtime = useV2RuntimeController({
    workflowId: args.workflowV2Model.isV2 ? args.workflow?.workflow_id : null,
    runtime: args.workflowV2Model.workflowV2?.runtime,
    enabled: Boolean(args.workflowV2Model.isV2 && args.workflow?.workflow_id && args.workflow.workflow_id !== LOCAL_WORKFLOW_ID),
    onEvents: async (eventWorkflowId, events) => {
      if (!shouldApplyWorkflowScopedResult(eventWorkflowId, args.activeWorkflowIdRef.current)) return;
      canvasRuntimeEvents.actions.applyV2RuntimeEventsToPage(events);
    },
    onSnapshot: (snapshotWorkflowId, runtime) => {
      if (!shouldApplyWorkflowScopedResult(snapshotWorkflowId, args.activeWorkflowIdRef.current)) return;
      const hasActiveRuntime = hasActiveV2Runtime(runtime);
      if (runtime.active_execution_id) args.setActiveExecutionId(runtime.active_execution_id);
      args.setWorkflowRunning(hasActiveRuntime);
      args.setExecutionPollingState(hasActiveRuntime ? "polling" : "idle");
    },
  });
  args.v2RuntimeRef.current = v2Runtime;

  const v2ObservableRunActions = useV2ObservableRunActions({
    workflowId: args.workflowV2Model.isV2 ? args.workflow?.workflow_id : null,
    refreshRuntime: (requestWorkflowId) => v2Runtime.syncSnapshot(requestWorkflowId),
    refreshAssets: async (requestWorkflowId, response) => {
      await args.refreshV2AssetsAndRetryMissing(requestWorkflowId, "run-started", response.workflow ?? args.workflowV2Model.workflowV2);
    },
    appendRuntimeEvent: (event) => canvasRuntimeEvents.actions.applyV2RuntimeEventsToPage([event]),
  });
  const workflowV2Controller = useWorkflowV2Controller({
    workflowId: args.workflowV2Model.isV2 ? args.workflow?.workflow_id : null,
    runWorkflow: v2ObservableRunActions.runWorkflow,
    refreshRuntime: (requestWorkflowId) => v2Runtime.syncSnapshot(requestWorkflowId),
  });
  const v2NodeRuntimeStatusById = useMemo(
    () => v2RuntimeNodeStatusById(v2Runtime.store),
    [v2Runtime.store],
  );
  const v2ActiveEdgeSourceNodeIds = useMemo(
    () => v2RuntimeActiveEdgeSourceNodeIds(v2Runtime.store),
    [v2Runtime.store],
  );
  const v2SlotRuntimeStatusById = useMemo(
    () => v2RuntimeSlotStatusById(v2Runtime.store),
    [v2Runtime.store],
  );

  return {
    canvasRuntimeEvents,
    v2Runtime,
    v2ObservableRunActions,
    workflowV2Controller,
    v2NodeRuntimeStatusById,
    v2ActiveEdgeSourceNodeIds,
    v2SlotRuntimeStatusById,
  };
}
