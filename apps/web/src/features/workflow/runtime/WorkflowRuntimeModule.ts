import { useCallback, useMemo, useState } from "react";
import { api } from "../../../api/client.ts";
import { v2Api } from "../../../api/v2Client.ts";
import type { WorkflowNode, WorkflowRunRequest } from "../../../types.ts";
import type { V2GlobalRunRequest, WorkflowRuntimeEventV2, WorkflowRuntimeV2 } from "../../../types-v2.ts";
import {
  v2RuntimeActiveEdgeSourceNodeIds,
  v2RuntimeNodeStatusById,
  v2RuntimeSlotStatusById,
} from "../../../workflow-v2/runtime.ts";
import { useV2RuntimeController } from "./useV2RuntimeController.ts";

export type WorkflowRuntimeKind = "v1" | "v2";

export type WorkflowRuntimeView = {
  connectionState: string;
  activeExecutionId: string | null;
  runningNodeIds: string[];
  waitingNodeIds: string[];
  runningSlotIds: string[];
  waitingSlotIds: string[];
  nodeStatusById: Record<string, string>;
  slotStatusById: Record<string, string>;
  activeEdgeSourceNodeIds: string[];
  workflowRunning: boolean;
  currentNodeRunning: boolean;
};

export type WorkflowRuntimeModuleArgs = {
  workflowId: string | null;
  kind: WorkflowRuntimeKind;
  workflowV2Runtime?: WorkflowRuntimeV2 | null;
  nodes: WorkflowNode[];
  selectedNodeId: string | null;
  onWorkflowChanged: (workflowId: string) => Promise<void> | void;
  onAssetsChanged: (workflowId: string) => Promise<void> | void;
  onError: (message: string) => void;
};

export type WorkflowRuntimeModule = {
  runtimeView: WorkflowRuntimeView;
  runWorkflow: () => Promise<void>;
  runCurrentNode: (nodeId: string) => Promise<void>;
  refreshRuntime: () => Promise<void>;
  applyEvents: (events: WorkflowRuntimeEventV2[]) => void;
};

function nodeTypeForRun(nodes: WorkflowNode[], nodeId: string) {
  const node = nodes.find((candidate) => candidate.id === nodeId);
  const record = node as (WorkflowNode & { node_type?: string }) | undefined;
  return record?.node_type ?? record?.type ?? nodeId;
}

function v2CurrentNodeRunRequest(nodeId: string): V2GlobalRunRequest {
  return {
    mode: "fill_missing_required_slots",
    start_node_id: nodeId,
    target_node_id: nodeId,
  } as V2GlobalRunRequest;
}

export function useWorkflowRuntimeModule(args: WorkflowRuntimeModuleArgs): WorkflowRuntimeModule {
  const [v1RunningNodeIds, setV1RunningNodeIds] = useState<string[]>([]);
  const [v1WaitingNodeIds, setV1WaitingNodeIds] = useState<string[]>([]);
  const [v1ConnectionState, setV1ConnectionState] = useState("disconnected");
  const [currentRunNodeId, setCurrentRunNodeId] = useState<string | null>(null);

  const workflowId = args.workflowId;
  const kind = args.kind;
  const selectedNodeId = args.selectedNodeId;

  const v2Runtime = useV2RuntimeController({
    workflowId: kind === "v2" ? workflowId : null,
    runtime: args.workflowV2Runtime ?? undefined,
    enabled: Boolean(kind === "v2" && workflowId),
    onEvents: async (eventWorkflowId, events) => {
      const refreshAssets = events.some((event) =>
        event.event_type === "node_assets_updated" ||
        event.event_type === "asset_version_created" ||
        event.event_type === "slot_working_version_created" ||
        event.event_type === "slot_selected_version_updated" ||
        event.event_type === "execution_completed"
      );
      const refreshWorkflow = events.some((event) =>
        event.event_type === "workflow_updated" ||
        event.event_type === "graph_updated" ||
        event.event_type === "execution_completed"
      );
      if (refreshWorkflow) await args.onWorkflowChanged(eventWorkflowId);
      if (refreshAssets) await args.onAssetsChanged(eventWorkflowId);
    },
    onSnapshot: async (snapshotWorkflowId) => {
      await args.onAssetsChanged(snapshotWorkflowId);
    },
  });

  const runtimeView = useMemo<WorkflowRuntimeView>(() => {
    if (kind === "v2") {
      const canvasRuntime = v2Runtime.store;
      const nodeStatusById = v2RuntimeNodeStatusById(canvasRuntime);
      const slotStatusById = v2RuntimeSlotStatusById(canvasRuntime);
      const activeEdgeSourceNodeIds = v2RuntimeActiveEdgeSourceNodeIds(canvasRuntime);
      const runningNodeIds = [...canvasRuntime.runningNodeIds];
      const waitingNodeIds = [...canvasRuntime.waitingNodeIds];
      const workflowRunning = runningNodeIds.length > 0 || waitingNodeIds.length > 0 || canvasRuntime.executionStatus === "running" || canvasRuntime.executionStatus === "waiting";
      return {
        connectionState: v2Runtime.connectionState,
        activeExecutionId: canvasRuntime.activeExecutionId,
        runningNodeIds,
        waitingNodeIds,
        runningSlotIds: [...canvasRuntime.runningSlotIds],
        waitingSlotIds: [...canvasRuntime.waitingSlotIds],
        nodeStatusById,
        slotStatusById,
        activeEdgeSourceNodeIds,
        workflowRunning,
        currentNodeRunning: Boolean(selectedNodeId && (runningNodeIds.includes(selectedNodeId) || waitingNodeIds.includes(selectedNodeId))),
      };
    }

    const nodeStatusById: Record<string, string> = {};
    for (const nodeId of v1RunningNodeIds) nodeStatusById[nodeId] = "running";
    for (const nodeId of v1WaitingNodeIds) nodeStatusById[nodeId] = "waiting";

    return {
      connectionState: v1ConnectionState,
      activeExecutionId: null,
      runningNodeIds: v1RunningNodeIds,
      waitingNodeIds: v1WaitingNodeIds,
      runningSlotIds: [],
      waitingSlotIds: [],
      nodeStatusById,
      slotStatusById: {},
      activeEdgeSourceNodeIds: v1RunningNodeIds,
      workflowRunning: v1RunningNodeIds.length > 0 || v1WaitingNodeIds.length > 0,
      currentNodeRunning: Boolean(currentRunNodeId),
    };
  }, [currentRunNodeId, kind, selectedNodeId, v1ConnectionState, v1RunningNodeIds, v1WaitingNodeIds, v2Runtime.connectionState, v2Runtime.store]);

  const refreshRuntime = useCallback(async () => {
    if (!workflowId) return;
    if (kind === "v2") {
      await v2Runtime.syncSnapshot(workflowId);
      return;
    }
    setV1ConnectionState("connected");
  }, [kind, v2Runtime, workflowId]);

  const runWorkflow = useCallback(async () => {
    if (!workflowId) return;
    try {
      if (kind === "v2") {
        await v2Api.runWorkflowAsync(workflowId, { mode: "fill_missing_required_slots" });
        await refreshRuntime();
        await args.onAssetsChanged(workflowId);
        return;
      }
      setV1ConnectionState("connected");
      setV1RunningNodeIds(args.nodes.map((node) => node.id).filter(Boolean));
      await api.runWorkflow(workflowId, { only_missing: true } as WorkflowRunRequest);
      await args.onWorkflowChanged(workflowId);
    } catch (error) {
      args.onError(error instanceof Error ? error.message : "Workflow run failed");
    } finally {
      if (kind === "v1") {
        setV1RunningNodeIds([]);
        setV1WaitingNodeIds([]);
      }
    }
  }, [args, kind, refreshRuntime, workflowId]);

  const runCurrentNode = useCallback(async (nodeId: string) => {
    if (!workflowId || !nodeId) return;
    setCurrentRunNodeId(nodeId);
    try {
      if (kind === "v2") {
        await v2Api.runWorkflowAsync(workflowId, v2CurrentNodeRunRequest(nodeId));
        await refreshRuntime();
        await args.onAssetsChanged(workflowId);
        return;
      }
      setV1ConnectionState("connected");
      setV1RunningNodeIds([nodeId]);
      await api.runNode({
        workflow_id: workflowId,
        node_id: nodeId,
        node_type: nodeTypeForRun(args.nodes, nodeId),
        run_downstream: false,
      });
      await args.onWorkflowChanged(workflowId);
    } catch (error) {
      args.onError(error instanceof Error ? error.message : "Node run failed");
    } finally {
      setCurrentRunNodeId(null);
      if (kind === "v1") {
        setV1RunningNodeIds([]);
        setV1WaitingNodeIds([]);
      }
    }
  }, [args, kind, refreshRuntime, workflowId]);

  const applyEvents = useCallback((_events: WorkflowRuntimeEventV2[]) => {
    if (!workflowId || kind !== "v2") return;
    void v2Runtime.syncEvents(workflowId);
  }, [kind, v2Runtime, workflowId]);

  return {
    runtimeView,
    runWorkflow,
    runCurrentNode,
    refreshRuntime,
    applyEvents,
  };
}
