import { useMemo, useRef } from "react";
import { v2Api } from "../../../api/v2Client.ts";
import { v2EtagStore } from "../../../api/v2EtagStore.ts";
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
import type { WorkflowGraph } from "../../../types.ts";
import { workflowV2ToWorkflowGraph } from "../../../workflow-v2/pageAdapter.ts";
import {
  createV2AuthoringRuntimeEventPolicy,
  createWorkflowRevisionRefreshCoalescer,
  shouldApplyRuntimeWorkflowRead,
  shouldApplyWorkflowRevisionRead,
} from "../runtime/v2AuthoringRuntimeEventPolicy.ts";
import { dispatchWorkflowDocumentCommand } from "../state/workflowDocumentCommands.ts";
import type { WorkflowPageRuntimeControllersArgs } from "./workflowPageContracts.ts";

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
  const argsRef = useRef(args);
  argsRef.current = args;
  const currentWorkflowRevisionRef = useRef<WorkflowGraph | null>(null);
  if (
    !currentWorkflowRevisionRef.current
    || currentWorkflowRevisionRef.current.workflow_id !== args.workflow?.workflow_id
    || shouldApplyRuntimeWorkflowRead(args.workflow, currentWorkflowRevisionRef.current)
  ) {
    currentWorkflowRevisionRef.current = args.workflow ?? null;
  }
  const applyWorkflowGraph = (graph: WorkflowGraph) => {
    const currentArgs = argsRef.current;
    currentArgs.document.setWorkflow(graph);
    currentArgs.document.syncWorkflowAdRequest(graph);
    currentArgs.document.setCanvasNodes(graph.nodes);
    currentArgs.document.setWorkflowVariables(graph.variables ?? []);
    currentArgs.document.setFlowNodes((current: CanvasNode[]) => {
      const nextFlowNodes = mapWorkflowNodes(graph.nodes, currentArgs.document.nodeRunByType, current);
      currentArgs.document.setFlowEdges(mapWorkflowEdges(graph.edges, nextFlowNodes));
      return nextFlowNodes;
    });
    currentArgs.document.setSelectedNodeId((current: string | null) =>
      current && graph.nodes.some((node) => node.id === current && isUserVisibleWorkflowNode(node))
        ? current
        : firstVisibleWorkflowNodeId(graph.nodes),
    );
    currentArgs.document.setSavedAt(graph.updated_at ?? new Date().toISOString());
  };
  const applyRuntimeWorkflowRead = async (
    workflowId: string,
    options: { captureValidatedEtag: boolean; reason: string },
  ) => {
    const baselineEtag = options.captureValidatedEtag
      ? v2EtagStore.getWorkflow(workflowId)
      : null;
    const latest = await v2Api.workflowWithEtagWithoutCapture(workflowId);
    const currentArgs = argsRef.current;
    const shouldApply = options.captureValidatedEtag
      ? shouldApplyWorkflowRevisionRead(latest.value, currentWorkflowRevisionRef.current, {
          requestedWorkflowId: workflowId,
          activeWorkflowId: currentArgs.canvasEvents.activeWorkflowIdRef.current,
          baselineEtag,
          currentEtag: v2EtagStore.getWorkflow(workflowId),
        })
      : shouldApplyWorkflowScopedResult(workflowId, currentArgs.canvasEvents.activeWorkflowIdRef.current)
        && shouldApplyRuntimeWorkflowRead(latest.value, currentWorkflowRevisionRef.current);
    if (!shouldApply) return;
    const graph = workflowV2ToWorkflowGraph(latest.value);
    currentWorkflowRevisionRef.current = graph;
    applyWorkflowGraph(graph);
    if (options.captureValidatedEtag && latest.etag) {
      v2EtagStore.set("workflow", workflowId, latest.etag);
    }
    await currentArgs.canvasEvents.onRefreshV2AssetsAndRetryMissing(
      workflowId,
      options.reason,
      latest.value,
    );
  };
  const authoringWorkflowRefreshRef = useRef<ReturnType<typeof createWorkflowRevisionRefreshCoalescer> | null>(null);
  if (!authoringWorkflowRefreshRef.current) {
    authoringWorkflowRefreshRef.current = createWorkflowRevisionRefreshCoalescer(async (workflowId) => {
      try {
        await applyRuntimeWorkflowRead(workflowId, {
          captureValidatedEtag: true,
          reason: "workflow-revision-created",
        });
      } catch {
        // Runtime recovery continues through future events and polling.
      }
    });
  }
  const runtimeWorkflowRefreshRef = useRef<ReturnType<typeof createWorkflowRevisionRefreshCoalescer> | null>(null);
  if (!runtimeWorkflowRefreshRef.current) {
    runtimeWorkflowRefreshRef.current = createWorkflowRevisionRefreshCoalescer(async (workflowId) => {
      try {
        await applyRuntimeWorkflowRead(workflowId, {
          captureValidatedEtag: false,
          reason: "runtime-synchronization",
        });
      } catch {
        // Runtime recovery continues through future events and polling.
      }
    });
  }
  const canvasRuntimeEvents = useCanvasRuntimeEventController({
    localWorkflowId: LOCAL_WORKFLOW_ID,
    ...args.canvasEvents,
    getActiveConversationId: () => args.activeConversationId,
    getRevisionHistoryTarget: () => args.revisionHistoryTarget,
    getV2SlotVersionsById: () => args.v2SlotVersionsById,
    getActiveV2SlotId: () => args.v2SlotMicroEdit.state.openSlotId,
    getWorkflowV2: () => args.workflowV2Model.workflowV2,
    v2Runtime: {
      syncSnapshot: async (requestWorkflowId: string) => {
        await args.refs.v2Runtime.current?.syncSnapshot(requestWorkflowId);
      },
      slotNodeId: (slotId: string) => args.refs.v2Runtime.current?.store.slotNodeIds[slotId] ?? null,
    },
    onApplySnapshotGraph: applyWorkflowGraph,
    onPatchNodeStatus: (nodeId, nextStatus) => {
      if (!nodeId || !nextStatus) return;
      const currentArgs = argsRef.current;
      dispatchWorkflowDocumentCommand(
        {
          setWorkflow: currentArgs.document.setWorkflow,
          setCanvasNodes: currentArgs.document.setCanvasNodes,
          setFlowNodes: currentArgs.document.setFlowNodes,
        },
        {
          type: "patch-nodes",
          nodeIds: [nodeId],
          patch: { status: nextStatus },
        },
      );
    },
    onRefreshWorkflowGraph: (workflowId) => {
      if (!argsRef.current.canvasEvents.currentWorkflowIsV2()) {
        return argsRef.current.document.refreshWorkflowGraph(workflowId);
      }
      return runtimeWorkflowRefreshRef.current?.request(workflowId) ?? Promise.resolve();
    },
    onLoadV2SlotVersions: (slotId) => args.refs.v2SlotOperations.current?.actions.loadV2SlotVersions(slotId),
    onLoadLocalAssetHistory: (workflowId, nodeId, asset) => args.refs.localRevisionOperations.current?.actions.loadLocalAssetHistory(workflowId, nodeId, asset) ?? Promise.resolve(null),
    onApplyLocalRevisionState: (key, revision) => args.refs.localRevisionOperations.current?.actions.applyLocalRevisionState(key, revision),
    onUpdateLocalRevisionCardState: (key, patch) => args.refs.localRevisionOperations.current?.actions.updateLocalRevisionCardState(key, patch),
    finalCompositionErrorMessage,
  });

  const v2Runtime = useV2RuntimeController({
    workflowId: args.workflowV2Model.isV2 ? args.workflow?.workflow_id : null,
    runtime: args.workflowV2Model.workflowV2?.runtime,
    enabled: Boolean(args.workflowV2Model.isV2 && args.workflow?.workflow_id && args.workflow.workflow_id !== LOCAL_WORKFLOW_ID),
    onEvents: async (eventWorkflowId, events) => {
      if (!shouldApplyWorkflowScopedResult(eventWorkflowId, args.canvasEvents.activeWorkflowIdRef.current)) return;
      const authoringRuntimeEventPolicy = createV2AuthoringRuntimeEventPolicy(events);
      canvasRuntimeEvents.actions.applyV2RuntimeEventsToPage(events);
      if (authoringRuntimeEventPolicy.shouldRefreshAuthoringWorkflow) {
        await authoringWorkflowRefreshRef.current?.request(eventWorkflowId);
      } else if (authoringRuntimeEventPolicy.shouldRefreshRuntimeWorkflow) {
        await runtimeWorkflowRefreshRef.current?.request(eventWorkflowId);
      }
      await args.refs.screenplayActions.current?.handleRuntimeEvents(events);
    },
    onSnapshot: (snapshotWorkflowId, runtime) => {
      if (!shouldApplyWorkflowScopedResult(snapshotWorkflowId, args.canvasEvents.activeWorkflowIdRef.current)) return;
      const hasActiveRuntime = hasActiveV2Runtime(runtime);
      if (runtime.active_execution_id) args.canvasEvents.setActiveExecutionId(runtime.active_execution_id);
      args.canvasEvents.setWorkflowRunning(hasActiveRuntime);
      args.canvasEvents.setExecutionPollingState(hasActiveRuntime ? "polling" : "idle");
    },
  });
  args.refs.v2Runtime.current = v2Runtime;

  const v2ObservableRunActions = useV2ObservableRunActions({
    workflowId: args.workflowV2Model.isV2 ? args.workflow?.workflow_id : null,
    refreshRuntime: (requestWorkflowId) => v2Runtime.syncSnapshot(requestWorkflowId),
    refreshAssets: async (requestWorkflowId, response) => {
      await args.canvasEvents.onRefreshV2AssetsAndRetryMissing(
        requestWorkflowId,
        "run-started",
        response.workflow ?? args.workflowV2Model.workflowV2,
      );
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
