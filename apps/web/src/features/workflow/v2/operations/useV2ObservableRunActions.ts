import { useCallback, useState } from "react";
import { v2Api } from "../../../../api/v2Client.ts";
import type { V2GlobalRunRequest, WorkflowRuntimeEventV2, WorkflowRuntimeV2, WorkflowV2RunResponse } from "../../../../types-v2.ts";

type V2ObservableRunActionsOptions = {
  workflowId?: string | null;
  runWorkflowAsync?: (workflowId: string, body?: V2GlobalRunRequest) => Promise<WorkflowV2RunResponse>;
  refreshRuntime?: (workflowId: string) => Promise<WorkflowRuntimeV2 | void> | WorkflowRuntimeV2 | void;
  refreshAssets?: (workflowId: string, response: WorkflowV2RunResponse) => Promise<void> | void;
  appendRuntimeEvent?: (event: WorkflowRuntimeEventV2) => void;
};

export function useV2ObservableRunActions({
  workflowId,
  runWorkflowAsync = v2Api.runWorkflowAsync,
  refreshRuntime,
  refreshAssets,
  appendRuntimeEvent,
}: V2ObservableRunActionsOptions) {
  const [runStarting, setRunStarting] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const runWorkflow = useCallback(async (body: V2GlobalRunRequest = { mode: "fill_missing_required_slots" }) => {
    if (!workflowId) {
      const message = "Generate a V2 workflow before running it.";
      setRunError(message);
      throw new Error(message);
    }
    setRunStarting(true);
    setRunError(null);
    try {
      const response = await runWorkflowAsync(workflowId, body);
      appendRuntimeEvent?.(workflowRunStartedEvent(workflowId, response));
      await refreshRuntime?.(workflowId);
      await refreshAssets?.(workflowId, response);
      return response;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Workflow V2 run failed";
      setRunError(message);
      throw error;
    } finally {
      setRunStarting(false);
    }
  }, [appendRuntimeEvent, refreshAssets, refreshRuntime, runWorkflowAsync, workflowId]);

  return {
    runStarting,
    runError,
    runWorkflow,
  };
}

function workflowRunStartedEvent(workflowId: string, response: WorkflowV2RunResponse): WorkflowRuntimeEventV2 {
  const seq = response.events_cursor ?? response.runtime?.events_cursor ?? Date.now();
  return {
    seq,
    workflow_id: response.workflow_id || response.workflow?.workflow_id || workflowId,
    event_type: "execution_started",
    created_at: new Date().toISOString(),
    payload: {
      execution_id: response.execution_id ?? response.runtime?.active_execution_id ?? null,
      status: response.status ?? response.runtime?.execution_status ?? "running",
    },
  };
}
