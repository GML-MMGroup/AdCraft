import { useCallback, useEffect, useMemo, useRef } from "react";
import { shouldApplyWorkflowScopedResult } from "../../../workflow/sessionGuards.ts";

export type WorkflowMutationScope = {
  token: number;
  projectId: string | null;
  workflowId: string | null;
};

export function useWorkflowMutationGuards({
  workflowId,
  activeProjectId,
  selectedNodeId,
}: {
  workflowId?: string | null;
  activeProjectId?: string | null;
  selectedNodeId: string;
}) {
  const activeWorkflowIdRef = useRef<string | null>(workflowId ?? null);
  const activeProjectIdRef = useRef<string | null>(activeProjectId ?? null);
  const selectedNodeIdRef = useRef(selectedNodeId);
  const workflowMutationRequestRef = useRef(0);
  const currentNodeRunRequestRef = useRef(0);
  const chatCanvasExecutionRequestRef = useRef(0);

  useEffect(() => {
    activeWorkflowIdRef.current = workflowId ?? null;
  }, [workflowId]);

  useEffect(() => {
    activeProjectIdRef.current = activeProjectId ?? null;
  }, [activeProjectId]);

  useEffect(() => {
    selectedNodeIdRef.current = selectedNodeId;
  }, [selectedNodeId]);

  const beginWorkflowMutationScope = useCallback((): WorkflowMutationScope => {
    const token = workflowMutationRequestRef.current + 1;
    workflowMutationRequestRef.current = token;
    return {
      token,
      projectId: activeProjectIdRef.current,
      workflowId: activeWorkflowIdRef.current,
    };
  }, []);

  const shouldApplyWorkflowMutationScope = useCallback((scope: WorkflowMutationScope) => (
    scope.token === workflowMutationRequestRef.current &&
    scope.projectId === activeProjectIdRef.current &&
    scope.workflowId === activeWorkflowIdRef.current
  ), []);

  const shouldApplyCurrentNodeRun = useCallback((requestWorkflowId: string | null, requestNodeId: string, requestNodeRunId: number) => (
    requestNodeRunId === currentNodeRunRequestRef.current &&
    selectedNodeIdRef.current === requestNodeId &&
    (!requestWorkflowId || shouldApplyWorkflowScopedResult(requestWorkflowId, activeWorkflowIdRef.current))
  ), []);

  return useMemo(() => ({
    state: {
      activeWorkflowIdRef,
      activeProjectIdRef,
      selectedNodeIdRef,
      currentNodeRunRequestRef,
      chatCanvasExecutionRequestRef,
    },
    actions: {
      beginWorkflowMutationScope,
      shouldApplyWorkflowMutationScope,
      shouldApplyCurrentNodeRun,
    },
  }), [beginWorkflowMutationScope, shouldApplyCurrentNodeRun, shouldApplyWorkflowMutationScope]);
}
