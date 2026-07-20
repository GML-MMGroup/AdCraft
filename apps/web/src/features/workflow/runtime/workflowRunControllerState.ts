import type { MutableRefObject } from "react";
import type {
  AdRequest,
  AssetLibraryEntitySummary,
  AssetLibraryReference,
  FrontDeskMessage,
  MediaStatus,
  NodeRunResult,
  ResolvedNodeInputs,
  UploadedAsset,
  WorkflowGraph,
  WorkflowNode,
  WorkflowRunRequest,
  WorkflowRunResponse,
  WorkflowVariable,
} from "../../../types.ts";
import type { V2PlanFromPromptRequest, WorkflowV2, WorkflowV2RunResponse } from "../../../types-v2.ts";
import type { ExecutionPollingState } from "../../../workflow/executionRuntime.ts";
import type { StoryboardVideoReadiness } from "../../../workflow/mediaSegments.ts";
import type { CanvasEdge, CanvasNode } from "../types.ts";

export const workflowRunControllerState = true;

type StateSetter<T> = (value: T | ((current: T) => T)) => void;

export type WorkflowRunMessages = {
  running: string;
  complete: string;
  failed: string;
};

export type WorkflowRunControllerArgs = {
  defaultAdRequest: AdRequest;
  workflow: WorkflowGraph | null | undefined;
  canvasNodes: WorkflowNode[];
  visibleCanvasNodes: WorkflowNode[];
  flowNodes: CanvasNode[];
  flowEdges: CanvasEdge[];
  selectedAssets: UploadedAsset[];
  selectedPlanNode: WorkflowNode | null | undefined;
  selectedRunType: string;
  selectedResolvedInputs: ResolvedNodeInputs | null | undefined;
  nodeRuns: NodeRunResult[];
  workflowVariables: WorkflowVariable[];
  runSettings: Partial<WorkflowRunRequest>;
  adRequest: AdRequest;
  workflowPrompt: string;
  messages: FrontDeskMessage[];
  promptLibraryEntities: AssetLibraryEntitySummary[];
  promptPrimaryReferenceIds: string[];
  nodeRunLibraryEntities: AssetLibraryEntitySummary[];
  overridePrompt: string;
  currentNodeRunning: boolean;
  activeWorkflowIdRef: MutableRefObject<string | null>;
  currentNodeRunningRef: MutableRefObject<boolean>;
  currentNodeRunRequestRef: MutableRefObject<number>;
  setActiveExecutionId: StateSetter<string | null>;
  setExecutionNodeStatusById: StateSetter<Record<string, string>>;
  setRunningNodeIds: StateSetter<string[]>;
  setExecutionPollingState: StateSetter<ExecutionPollingState>;
  setWorkflowRunning: StateSetter<boolean>;
  setWorkflowRun: StateSetter<WorkflowRunResponse | null>;
  setMediaStatus: StateSetter<MediaStatus | null>;
  setStatus: StateSetter<string>;
  setCanvasNodes: StateSetter<WorkflowNode[]>;
  setFlowNodes: StateSetter<CanvasNode[]>;
  setMessages: StateSetter<FrontDeskMessage[]>;
  setAdRequest: StateSetter<AdRequest>;
  setCurrentNodeRunning: StateSetter<boolean>;
  setSelectedNodeRun: StateSetter<NodeRunResult | null>;
  setSelectedResolvedInputs: StateSetter<ResolvedNodeInputs | null>;
  setWorkflow: StateSetter<WorkflowGraph | null>;
  currentWorkflowIsV2: () => boolean;
  assertNotV2WorkflowForV1Api: (workflowId: string, operation: string) => void;
  beginWorkflowMutationScope: () => { token: number; projectId: string | null; workflowId: string | null };
  shouldApplyWorkflowMutationScope: (scope: { token: number; projectId: string | null; workflowId: string | null }) => boolean;
  workflowPromptAssetReferences: () => AssetLibraryReference[];
  syncFrontDeskAdRequest: (nextAdRequest?: AdRequest | null) => void;
  applyWorkflowV2: (workflow: WorkflowV2, options?: { refreshAssetsReason?: string | false }) => Promise<void>;
  v2PlanFromPromptRequest: () => V2PlanFromPromptRequest;
  syncV2Events: (workflowId: string) => Promise<unknown>;
  syncV2Snapshot: (workflowId: string) => Promise<unknown>;
  flushV2SlotDrafts: () => Promise<unknown>;
  runV2Workflow: (payload: { mode: "fill_missing_required_slots" }) => Promise<WorkflowV2RunResponse>;
  refreshV2AssetsAndRetryMissing: (workflowId: string, reason: string, workflow?: WorkflowV2 | null) => Promise<unknown>;
  saveCanvas: (options?: { quiet?: boolean; requireBackend?: boolean }) => Promise<boolean>;
  validateBackendGraph: (options?: { quiet?: boolean }) => Promise<{ valid: boolean; errors?: unknown[] }>;
  prepareFinalCompositionRun: (node: WorkflowNode) => Promise<StoryboardVideoReadiness | null>;
  refreshWorkflowNodes: (workflowId: string) => Promise<unknown>;
  refreshWorkflowGraph: (workflowId?: string, runtimeRuns?: NodeRunResult[]) => Promise<unknown>;
  refreshMediaStatus: (workflowId?: string) => Promise<MediaStatus | null>;
  refreshSelectedResolvedInputs: (nodeId: string, options?: { force?: boolean }) => Promise<ResolvedNodeInputs | null | undefined>;
  patchWorkflowNodeState: (nodeIds: string[] | Set<string>, patch: Partial<WorkflowNode>) => void;
  shouldApplyCurrentNodeRun: (workflowId: string | null, nodeId: string, requestId: number) => boolean;
  nodeScopedAssetReferences: () => AssetLibraryReference[];
  runSelectedV2Slot: () => Promise<void>;
  pollStoryboardVideoMedia: (workflowId: string) => Promise<unknown>;
  applyNodeRunsToCanvas: (runs: NodeRunResult[]) => void;
  applyMediaStatusToCanvas: (status: MediaStatus | null) => void;
};
