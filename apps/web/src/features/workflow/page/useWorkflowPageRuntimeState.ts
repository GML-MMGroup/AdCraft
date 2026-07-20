import { useMemo, useState, type Dispatch, type SetStateAction } from "react";
import type { ExecutionPollingState } from "../../../workflow/executionRuntime.ts";
import type {
  GraphValidationResult,
  MediaStatus,
  NodeRunResult,
  WorkflowRunResponse,
  WorkflowVariable,
} from "../../../types";

type StateSetter<T> = Dispatch<SetStateAction<T>>;

export type WorkflowPageRuntimeState = {
  status: string;
  mediaStatus: MediaStatus | null;
  workflowRun: WorkflowRunResponse | null;
  activeExecutionId: string | null;
  executionNodeStatusById: Record<string, string>;
  runningNodeIds: string[];
  executionPollingState: ExecutionPollingState;
  workflowRunning: boolean;
  currentNodeRunning: boolean;
  qualityReviewingNodeIds: Record<string, boolean>;
  saving: boolean;
  savedAt: string | null;
  selectedNodeRun: NodeRunResult | null;
  validationResult: GraphValidationResult | null;
  affectedNodes: string[];
  staleReason: string;
  workflowVariables: WorkflowVariable[];
};

export type WorkflowPageRuntimeActions = {
  setStatus: StateSetter<string>;
  setMediaStatus: StateSetter<MediaStatus | null>;
  setWorkflowRun: StateSetter<WorkflowRunResponse | null>;
  setActiveExecutionId: StateSetter<string | null>;
  setExecutionNodeStatusById: StateSetter<Record<string, string>>;
  setRunningNodeIds: StateSetter<string[]>;
  setExecutionPollingState: StateSetter<ExecutionPollingState>;
  setWorkflowRunning: StateSetter<boolean>;
  setCurrentNodeRunning: StateSetter<boolean>;
  setQualityReviewingNodeIds: StateSetter<Record<string, boolean>>;
  setSaving: StateSetter<boolean>;
  setSavedAt: StateSetter<string | null>;
  setSelectedNodeRun: StateSetter<NodeRunResult | null>;
  setValidationResult: StateSetter<GraphValidationResult | null>;
  setAffectedNodes: StateSetter<string[]>;
  setStaleReason: StateSetter<string>;
  setWorkflowVariables: StateSetter<WorkflowVariable[]>;
};

export function useWorkflowPageRuntimeState(): {
  state: WorkflowPageRuntimeState;
  actions: WorkflowPageRuntimeActions;
} {
  const [status, setStatus] = useState("Ready");
  const [mediaStatus, setMediaStatus] = useState<MediaStatus | null>(null);
  const [workflowRun, setWorkflowRun] = useState<WorkflowRunResponse | null>(null);
  const [activeExecutionId, setActiveExecutionId] = useState<string | null>(null);
  const [executionNodeStatusById, setExecutionNodeStatusById] = useState<Record<string, string>>({});
  const [runningNodeIds, setRunningNodeIds] = useState<string[]>([]);
  const [executionPollingState, setExecutionPollingState] = useState<ExecutionPollingState>("idle");
  const [workflowRunning, setWorkflowRunning] = useState(false);
  const [currentNodeRunning, setCurrentNodeRunning] = useState(false);
  const [qualityReviewingNodeIds, setQualityReviewingNodeIds] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [selectedNodeRun, setSelectedNodeRun] = useState<NodeRunResult | null>(null);
  const [validationResult, setValidationResult] = useState<GraphValidationResult | null>(null);
  const [affectedNodes, setAffectedNodes] = useState<string[]>([]);
  const [staleReason, setStaleReason] = useState("Manual canvas change");
  const [workflowVariables, setWorkflowVariables] = useState<WorkflowVariable[]>([]);

  const state = useMemo<WorkflowPageRuntimeState>(() => ({
    status,
    mediaStatus,
    workflowRun,
    activeExecutionId,
    executionNodeStatusById,
    runningNodeIds,
    executionPollingState,
    workflowRunning,
    currentNodeRunning,
    qualityReviewingNodeIds,
    saving,
    savedAt,
    selectedNodeRun,
    validationResult,
    affectedNodes,
    staleReason,
    workflowVariables,
  }), [
    activeExecutionId,
    affectedNodes,
    currentNodeRunning,
    executionNodeStatusById,
    executionPollingState,
    mediaStatus,
    qualityReviewingNodeIds,
    runningNodeIds,
    savedAt,
    saving,
    selectedNodeRun,
    staleReason,
    status,
    validationResult,
    workflowRun,
    workflowRunning,
    workflowVariables,
  ]);

  const actions = useMemo<WorkflowPageRuntimeActions>(() => ({
    setStatus,
    setMediaStatus,
    setWorkflowRun,
    setActiveExecutionId,
    setExecutionNodeStatusById,
    setRunningNodeIds,
    setExecutionPollingState,
    setWorkflowRunning,
    setCurrentNodeRunning,
    setQualityReviewingNodeIds,
    setSaving,
    setSavedAt,
    setSelectedNodeRun,
    setValidationResult,
    setAffectedNodes,
    setStaleReason,
    setWorkflowVariables,
  }), []);

  return { state, actions };
}
