import type { MutableRefObject } from "react";
import type { ReactFlowInstance } from "@xyflow/react";
import type {
  AdRequest,
  AssetLibraryEntitySummary,
  AssetLibraryReference,
  AssetLibraryUploadKind,
  FrontDeskMessage,
  GraphValidationResult,
  MediaStatus,
  NodeRunResult,
  ResolvedNodeInputs,
  UploadedAsset,
  WorkflowGraph,
  WorkflowEdge,
  WorkflowNode,
  WorkflowNodeVersion,
  WorkflowRunResponse,
  WorkflowVariable,
} from "../../../types.ts";
import type { ProjectSessionState, SavedWorkflowProject } from "../../../projects/newProject.ts";
import type { CanvasEdge, CanvasNode } from "../types.ts";
import type { MediaLightboxState } from "../page/workflowPageTypes.ts";

export type PendingNodePatch = {
  patch: Partial<WorkflowNode>;
  baseNode: WorkflowNode;
  sourceFlowNode?: CanvasNode;
  timerId: number;
};

type StateSetter<T> = (value: T | ((current: T) => T)) => void;

export type SaveCanvasOptions = {
  quiet?: boolean;
  requireBackend?: boolean;
  nodes?: WorkflowNode[];
};

export type WorkflowGraphMutationControllerArgs = {
  workflow: WorkflowGraph | null | undefined;
  workflowId: string;
  demoNodes: WorkflowNode[];
  demoEdges: WorkflowEdge[];
  canvasNodes: WorkflowNode[];
  flowNodes: CanvasNode[];
  flowEdges: CanvasEdge[];
  nodeRuns: NodeRunResult[];
  nodeRunByType: Map<string, NodeRunResult>;
  workflowVariables: WorkflowVariable[];
  selectedAssets: UploadedAsset[];
  promptLibraryEntities: AssetLibraryEntitySummary[];
  messages: FrontDeskMessage[];
  selectedPlanNode: WorkflowNode | null | undefined;
  selectedNodeId: string;
  selectedEdgeId: string | null;
  selectedSystemSuggestion: string;
  selectedOptimizedPrompt: string;
  selectedRunType: string;
  selectedResolvedInputs: ResolvedNodeInputs | null;
  nodeUploadKind: AssetLibraryUploadKind;
  nodeUploadName: string;
  nodeUploadTags: string;
  staleReason: string;
  reactFlow: ReactFlowInstance<CanvasNode, CanvasEdge> | null;
  pendingNodePatches: MutableRefObject<Map<string, PendingNodePatch>>;
  activeWorkflowIdRef: MutableRefObject<string | null>;
  currentNodeRunningRef: MutableRefObject<boolean>;
  currentNodeRunRequestRef: MutableRefObject<number>;
  setWorkflow: StateSetter<WorkflowGraph | null>;
  setCanvasNodes: StateSetter<WorkflowNode[]>;
  setFlowNodes: StateSetter<CanvasNode[]>;
  setFlowEdges: StateSetter<CanvasEdge[]>;
  setWorkflowVariables: StateSetter<WorkflowVariable[]>;
  setSelectedNodeId: StateSetter<string>;
  setSelectedEdgeId: StateSetter<string | null>;
  setSelectedNodeRun: StateSetter<NodeRunResult | null>;
  setSelectedResolvedInputs: StateSetter<ResolvedNodeInputs | null>;
  setMediaStatus: StateSetter<MediaStatus | null>;
  setWorkflowRun: StateSetter<WorkflowRunResponse | null>;
  setWorkflowRunning: StateSetter<boolean>;
  setCurrentNodeRunning: StateSetter<boolean>;
  setValidationResult: StateSetter<GraphValidationResult | null>;
  setNodeVersions: StateSetter<WorkflowNodeVersion[]>;
  setAffectedNodes: StateSetter<string[]>;
  setSavedAt: StateSetter<string | null>;
  setSaving: StateSetter<boolean>;
  setStatus: StateSetter<string>;
  setDetailsOpen: (value: boolean) => void;
  setMediaLightbox: (value: MediaLightboxState | null) => void;
  setUploadingAsset: StateSetter<boolean>;
  setVariablesPanelOpen: (value: boolean) => void;
  currentWorkflowIsV2: () => boolean;
  assertNotV2WorkflowForV1Api: (workflowId: string, operation: string) => void;
  refreshV2WorkflowGraph: (workflowId: string) => Promise<unknown>;
  refreshWorkflowGraph: (workflowId?: string, runtimeRuns?: NodeRunResult[]) => Promise<WorkflowGraph | null | unknown>;
  refreshNodeVersions: (nodeId: string, options?: { force?: boolean }) => Promise<unknown>;
  refreshSelectedResolvedInputs: (nodeId: string, options?: { force?: boolean }) => Promise<ResolvedNodeInputs | null>;
  getCurrentRunAdRequest: () => AdRequest;
  nodeScopedAssetReferences: () => AssetLibraryReference[];
  applyNodeRunsToCanvas: (runs: NodeRunResult[]) => void;
  patchWorkflowNodeState: (nodeIds: string[] | Set<string>, patch: Partial<WorkflowNode>) => void;
  markNodesStale: (nodeIds: string[], reason?: string) => void;
  noteAffected: (nodes?: string[]) => void;
  saveProject: (payload?: ProjectSessionState) => SavedWorkflowProject | null;
  startNewProject: () => void;
  persistLocalSnapshot: (nodes?: WorkflowNode[], options?: { immediate?: boolean; flowNodes?: CanvasNode[] }) => void;
  persistNodePositionSnapshot: (nodes?: WorkflowNode[], options?: { flowNodes?: CanvasNode[] }) => void;
  captureCanvasHistory: () => void;
  clearCanvasHistory: () => void;
  resetExportState: () => void;
};
