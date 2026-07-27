import type { ReactNode, RefObject } from "react";
import type { ReactFlowInstance } from "@xyflow/react";
import type {
  AssetLibraryEntitySummary,
  MediaStatus,
  WorkflowGraph,
  WorkflowNode,
} from "../../../types.ts";
import type {
  V2AssetLibraryCategory,
  WorkflowItemV2,
  WorkflowSlotV2,
} from "../../../types-v2.ts";
import type { CanvasEdge, CanvasNode } from "../types.ts";
import type { AssetLibraryPickerTarget } from "../types.ts";
import type { useWorkflowCopilotPlanning } from "../copilot/useWorkflowCopilotPlanning.ts";
import type { useAgentConversationBridge } from "../copilot/useAgentConversationBridge.ts";
import type { useWorkflowRunController } from "../runtime/useWorkflowRunController.ts";
import type { useWorkflowGraphMutationController } from "../graph/useWorkflowGraphMutationController.ts";
import type { useWorkflowV2Model } from "../../../workflow-v2/pageAdapter.ts";
import type { useCanvasRuntimeEventController } from "../runtime/useCanvasRuntimeEventController.ts";
import type { useV2RuntimeController } from "../runtime/useV2RuntimeController.ts";
import type { useV2SlotOperations } from "../v2/slots/useV2SlotOperations.ts";
import type { useLocalRevisionOperations } from "../assets/useLocalRevisionOperations.ts";
import type { useFinalCompositionOperations } from "../final-composition/useFinalCompositionOperations.ts";
import type { useDynamicMediaOperations } from "../assets/useDynamicMediaOperations.ts";
import type { useWorkflowV2DerivedState } from "../v2/useWorkflowV2DerivedState.ts";
import type { useSlotMicroEdit } from "../v2/slots/useSlotMicroEdit.ts";
import type { useWorkflowPageScreenplay } from "./useWorkflowPageScreenplay.tsx";
import type {
  WorkflowCanvasSurfaceActions,
  WorkflowCanvasSurfaceModel,
} from "./WorkflowCanvasSurface.tsx";
import type {
  WorkflowSidePanelsSurfaceActions,
  WorkflowSidePanelsSurfaceModel,
} from "./WorkflowSidePanelsSurface.tsx";
import type {
  WorkflowBottomToolbarActions,
  WorkflowBottomToolbarModel,
} from "./WorkflowBottomToolbar.tsx";
import type {
  WorkflowPageUiActions,
  WorkflowPageUiChrome,
  MediaLightboxState,
} from "./workflowPageTypes.ts";
import type { WorkflowLocalSnapshotControllerArgs } from "./useWorkflowLocalSnapshotController.ts";
import type { AssetLibrarySaveTarget } from "../assets/useAssetLibrarySaveDialog.ts";
import type { DraggablePanelKey, PanelOffset } from "../../../components/WorkflowDraggablePanel.tsx";
import type { WorkflowPageAssetUiState } from "./useWorkflowPageAssetUiState.ts";
import type { WorkflowAssetOperationsController } from "../assets/useWorkflowAssetOperations.ts";
import type { useDynamicItemDraftState } from "../assets/useDynamicItemDraftState.ts";

type StrictOmit<T, K extends keyof T> = Omit<T, K>;
type CanvasRuntimeControllerArgs = Parameters<typeof useCanvasRuntimeEventController>[0];
type WorkflowGraphMutationControllerArgs = Parameters<typeof useWorkflowGraphMutationController>[0];
type V2SlotOperations = ReturnType<typeof useV2SlotOperations>;
type LocalRevisionOperations = ReturnType<typeof useLocalRevisionOperations>;
type FinalCompositionOperations = ReturnType<typeof useFinalCompositionOperations>;

export type WorkflowPageRuntimeControllersArgs = {
  workflow: WorkflowGraph | null | undefined;
  workflowV2Model: ReturnType<typeof useWorkflowV2Model>;
  canvasEvents: StrictOmit<
    CanvasRuntimeControllerArgs,
    | "localWorkflowId"
    | "getActiveConversationId"
    | "getRevisionHistoryTarget"
    | "getV2SlotVersionsById"
    | "getActiveV2SlotId"
    | "getWorkflowV2"
    | "v2Runtime"
    | "onApplySnapshotGraph"
    | "onPatchNodeStatus"
    | "onRefreshWorkflowGraph"
    | "onLoadV2SlotVersions"
    | "onLoadLocalAssetHistory"
    | "onApplyLocalRevisionState"
    | "onUpdateLocalRevisionCardState"
    | "finalCompositionErrorMessage"
  >;
  document: {
    nodeRunByType: Parameters<typeof import("../canvas/workflowCanvasModel.ts").mapWorkflowNodes>[1];
    setWorkflow: WorkflowGraphMutationControllerArgs["setWorkflow"];
    syncWorkflowAdRequest: (workflow: WorkflowGraph) => void;
    setCanvasNodes: WorkflowGraphMutationControllerArgs["setCanvasNodes"];
    setWorkflowVariables: WorkflowGraphMutationControllerArgs["setWorkflowVariables"];
    setFlowNodes: WorkflowGraphMutationControllerArgs["setFlowNodes"];
    setFlowEdges: WorkflowGraphMutationControllerArgs["setFlowEdges"];
    setSelectedNodeId: WorkflowGraphMutationControllerArgs["setSelectedNodeId"];
    setSavedAt: WorkflowGraphMutationControllerArgs["setSavedAt"];
    refreshWorkflowGraph: WorkflowGraphMutationControllerArgs["refreshWorkflowGraph"];
  };
  activeConversationId: string | null;
  revisionHistoryTarget: WorkflowPageAssetUiState["revisionHistoryTarget"];
  v2SlotVersionsById: WorkflowAssetOperationsController["state"]["v2SlotVersionsById"];
  v2SlotMicroEdit: ReturnType<typeof useSlotMicroEdit>;
  refs: {
    v2Runtime: RefObject<ReturnType<typeof useV2RuntimeController> | null>;
    v2SlotOperations: RefObject<V2SlotOperations | null>;
    localRevisionOperations: RefObject<LocalRevisionOperations | null>;
    screenplayActions: ReturnType<typeof useWorkflowPageScreenplay>["actionsRef"];
  };
};

type WorkflowCopilotPlanningArgs = Parameters<typeof useWorkflowCopilotPlanning>[0];
type WorkflowRunControllerArgs = Parameters<typeof useWorkflowRunController>[0];
type AgentConversationBridgeArgs = Parameters<typeof useAgentConversationBridge>[0];

export type WorkflowPageRunGraphControllersArgs = {
  planning: StrictOmit<WorkflowCopilotPlanningArgs, "bridgeFrontDeskMessagesToAgentConversation">;
  run: StrictOmit<
    WorkflowRunControllerArgs,
    "defaultAdRequest" | "v2PlanFromPromptRequest" | "syncV2Events" | "syncV2Snapshot" | "runV2Workflow"
  >;
  conversation: StrictOmit<AgentConversationBridgeArgs, "askCopilot">;
  snapshot: WorkflowLocalSnapshotControllerArgs;
  graph: StrictOmit<
    WorkflowGraphMutationControllerArgs,
    | "getCurrentRunAdRequest"
    | "persistLocalSnapshot"
    | "persistNodePositionSnapshot"
  >;
  runtime: {
    v2Runtime: ReturnType<typeof useV2RuntimeController>;
    workflowV2Controller: ReturnType<typeof import("../v2/useWorkflowV2Controller.ts").useWorkflowV2Controller>;
  };
  refs: {
    bridgeFrontDeskMessagesToAgentConversation: RefObject<
      ReturnType<typeof useAgentConversationBridge>["actions"]["bridgeFrontDeskMessagesToAgentConversation"] | null
    >;
    workflowRunActions: RefObject<
      Pick<
        ReturnType<typeof useWorkflowRunController>["actions"],
        "refreshExecutionRuntime" | "applyWorkflowRunSummary"
      > | null
    >;
    workflowGraphMutations: RefObject<ReturnType<typeof useWorkflowGraphMutationController> | null>;
  };
};

type V2SlotOperationsArgs = Parameters<typeof useV2SlotOperations>[0];
type LocalRevisionOperationsArgs = Parameters<typeof useLocalRevisionOperations>[0];
type FinalCompositionOperationsArgs = Parameters<typeof useFinalCompositionOperations>[0];
type DynamicMediaOperationsArgs = Parameters<typeof useDynamicMediaOperations>[0];

export type WorkflowPageAssetActionControllersArgs = {
  timeline: {
    workflowId: Parameters<typeof import("../final-composition/finalCompositionTimelineModel.ts").buildVideoTimeline>[0];
    exportSettings: Parameters<typeof import("../final-composition/finalCompositionTimelineModel.ts").buildVideoTimeline>[1];
    mediaStatus: Parameters<typeof import("../final-composition/finalCompositionTimelineModel.ts").buildVideoTimeline>[2];
    nodeRuns: Parameters<typeof import("../final-composition/finalCompositionTimelineModel.ts").buildVideoTimeline>[3];
    canvasNodes: Parameters<typeof import("../final-composition/finalCompositionTimelineModel.ts").buildVideoTimeline>[4];
  };
  derived: Parameters<typeof useWorkflowV2DerivedState>[0];
  slotMicroEdit: ReturnType<typeof useSlotMicroEdit>;
  slotRebaseWorkflow: Parameters<typeof import("../v2/slots/v2SlotRebaseSnapshot.ts").deriveV2SlotRebaseSnapshot>[0];
  slotOperations: StrictOmit<
    V2SlotOperationsArgs,
    | "selectedV2Items"
    | "selectedV2Slots"
    | "allV2Slots"
    | "selectedV2AssetVersions"
    | "activeV2SlotId"
    | "selectedFreeGenerationMediaType"
    | "v2SlotMicroEdit"
    | "syncV2Snapshot"
  >;
  localRevisions: StrictOmit<
    LocalRevisionOperationsArgs,
    "canShowLocalRevisionActions" | "getWorkflowNodeType"
  >;
  finalComposition: StrictOmit<
    FinalCompositionOperationsArgs,
    | "videoTimeline"
    | "syncV2Snapshot"
    | "updateLocalRevisionCardState"
    | "applyLocalRevisionState"
    | "loadLocalAssetHistory"
  >;
  dynamicMedia: StrictOmit<
    DynamicMediaOperationsArgs,
    | "selectedV2Slots"
    | "submitV2SlotMicroPrompt"
    | "selectV2SlotVersion"
    | "loadFinalCompositionTimeline"
    | "loadLocalAssetHistory"
  >;
  syncV2Snapshot: (workflowId: string) => Promise<void>;
  refs: {
    v2SlotOperations: RefObject<V2SlotOperations | null>;
    localRevisionOperations: RefObject<LocalRevisionOperations | null>;
    finalCompositionOperations: RefObject<FinalCompositionOperations | null>;
  };
};

export type WorkflowPageCanvasAssemblyArgs = {
  model: WorkflowCanvasSurfaceModel;
  workflowId: string | null;
  flowNodes: CanvasNode[];
  flowEdges: CanvasEdge[];
  selectedEdgeId: string | null;
  currentWorkflowIsV2: () => boolean;
  setSelectedNodeId: WorkflowGraphMutationControllerArgs["setSelectedNodeId"];
  setSelectedEdgeId: WorkflowGraphMutationControllerArgs["setSelectedEdgeId"];
  setDetailsOpen: (value: boolean) => void;
  setActiveV2SlotId: (slotId: string | null) => void;
  setActiveV2StoryboardItemId: (itemId: string | null) => void;
  setCanvasNodes: WorkflowGraphMutationControllerArgs["setCanvasNodes"];
  setFlowEdges: WorkflowGraphMutationControllerArgs["setFlowEdges"];
  deleteNodeFromBackend: (nodeId: string) => Promise<unknown> | unknown;
  deleteEdgeFromBackend: (edgeId: string) => Promise<unknown> | unknown;
  actions: Pick<
    WorkflowCanvasSurfaceActions,
    | "onInit"
    | "onNodesChange"
    | "onEdgesChange"
    | "onConnect"
    | "onReconnect"
    | "onReconnectEnd"
    | "onNodeDragStop"
  >;
};

type SidePanelDerivedModelKey =
  | "timelineClipCount"
  | "mediaStatusLabel"
  | "exportVideoUrl"
  | "currentWorkflowIsV2";

export type WorkflowPageSidePanelsAssemblyArgs = {
  model: StrictOmit<WorkflowSidePanelsSurfaceModel, SidePanelDerivedModelKey>;
  mediaStatus: MediaStatus | null | undefined;
  currentWorkflowIsV2: () => boolean;
  actions: WorkflowSidePanelsSurfaceActions;
};

export type WorkflowPageCopilotAssemblyArgs = WorkflowPageSidePanelsAssemblyArgs;

export type WorkflowPageToolbarAssemblyArgs = {
  status: string;
  activeExecutionId: string | null;
  workflowRunExecutionId: string | null | undefined;
  executionPollingState: "idle" | "starting" | "polling" | "completed" | "failed";
  runtimeConnectionLabel: string;
  savedAt: string | null;
  canvasHistoryCount: number;
  canvasFutureCount: number;
  hasCanvasSelection: boolean;
  hasSelectedPlanNode: boolean;
  workflowRunning: boolean;
  saving: boolean;
  reactFlow: ReactFlowInstance<CanvasNode, CanvasEdge> | null;
  createNewProject: WorkflowBottomToolbarActions["createNewProject"];
  runWorkflow: WorkflowBottomToolbarActions["runWorkflow"];
  saveCanvas: WorkflowBottomToolbarActions["saveCanvas"];
  undoCanvas: WorkflowBottomToolbarActions["undoCanvas"];
  redoCanvas: WorkflowBottomToolbarActions["redoCanvas"];
  deleteSelection: WorkflowBottomToolbarActions["deleteSelection"];
  autoLayout: WorkflowBottomToolbarActions["autoLayout"];
};

export type WorkflowPageSurfaceVisibilityArgs = {
  isV2: boolean;
  detailsOpen: boolean;
  selectedNodeId: string;
  workflowId: string | null;
};

export type WorkflowPagePickerSelectionArgs = {
  pickerTarget: AssetLibraryPickerTarget;
  activeV2SlotId: string | null;
  entity: AssetLibraryEntitySummary;
  replaceV2SlotWithLibraryEntity: (slotId: string, entity: AssetLibraryEntitySummary) => Promise<unknown> | unknown;
  toggleLibraryEntityForTarget: (target: AssetLibraryPickerTarget, entity: AssetLibraryEntitySummary) => void;
  closePicker: () => void;
};

export type WorkflowPageFloatingEditorsArgs = {
  isV2: boolean;
  workflowId: string | null;
  workflowItems: WorkflowItemV2[];
  activeV2SlotId: string | null;
  activeV2Slot: WorkflowSlotV2 | null;
  activeV2StoryboardItemId: string | null;
  slotDraftsById: ReturnType<typeof useSlotMicroEdit>["state"]["draftsBySlotId"];
  storyboardPromptDrafts: ReturnType<typeof useDynamicItemDraftState>["state"]["promptDrafts"];
  storyboardPromptSavingById: ReturnType<typeof useDynamicItemDraftState>["state"]["promptSavingById"];
  setActiveV2SlotId: (slotId: string | null) => void;
  setActiveV2StoryboardItemId: (itemId: string | null) => void;
  changeV2SlotPrompt: V2SlotOperations["actions"]["changeV2SlotPrompt"];
  syncV2SlotPromptReferences: V2SlotOperations["actions"]["syncV2SlotPromptReferences"];
  uploadV2PromptInputAsset: WorkflowSidePanelsSurfaceActions["uploadV2PromptInputAsset"];
  uploadV2SlotReference: V2SlotOperations["actions"]["uploadV2SlotReference"];
  removeV2SlotReference: V2SlotOperations["actions"]["removeV2SlotReference"];
  submitV2LocalSlotPrompt: V2SlotOperations["actions"]["submitV2LocalSlotPrompt"];
  openV2SlotAssetLibraryReplace: (slotId: string) => void;
  openV2SlotAssetLibrarySave: (slotId: string) => void;
  submitV2StoryboardPrompt: V2SlotOperations["actions"]["submitV2StoryboardPrompt"];
};

export type WorkflowPageOverlaysArgs = {
  finalComposition: {
    isV2: boolean;
    detailsOpen: boolean;
    selectedNodeId: string;
    workflowId: string | null;
    offset: PanelOffset;
    onOffsetCommit: (panelKey: DraggablePanelKey, offset: PanelOffset) => void;
    onClose: () => void;
    onWorkflowRefresh: (workflowId: string) => Promise<unknown> | unknown;
  };
  mediaLightbox: MediaLightboxState | null;
  closeMediaLightbox: () => void;
  assetLibrarySave: {
    isV2: boolean;
    target: AssetLibrarySaveTarget | null;
    displayName: string;
    tags: string;
    feedback: string;
    saving: boolean;
    setDisplayName: (value: string) => void;
    setTags: (value: string) => void;
    close: () => void;
    submit: (category?: V2AssetLibraryCategory) => Promise<unknown> | unknown;
  };
  picker: {
    target: AssetLibraryPickerTarget | null;
    activeV2SlotId: string | null;
    activeV2Slot: WorkflowSlotV2 | null;
    selectedEntitiesForTarget: (target: AssetLibraryPickerTarget) => AssetLibraryEntitySummary[];
    toggleLibraryEntityForTarget: (target: AssetLibraryPickerTarget, entity: AssetLibraryEntitySummary) => void;
    replaceV2SlotWithLibraryEntity: (slotId: string, entity: AssetLibraryEntitySummary) => Promise<unknown> | unknown;
    close: () => void;
  };
};

export type WorkflowPageSurfaceAssemblyArgs = {
  chrome: {
    model: WorkflowPageUiChrome;
    setCollapsed: WorkflowPageUiActions["setCollapsed"];
    setDetailsOpen: WorkflowPageUiActions["setDetailsOpen"];
    setRunPanelOpen: WorkflowPageUiActions["setRunPanelOpen"];
    setVariablesPanelOpen: WorkflowPageUiActions["setVariablesPanelOpen"];
  };
  canvas: WorkflowPageCanvasAssemblyArgs;
  sidePanels: WorkflowPageSidePanelsAssemblyArgs;
  toolbar: WorkflowPageToolbarAssemblyArgs;
  floatingEditors: WorkflowPageFloatingEditorsArgs;
  overlays: WorkflowPageOverlaysArgs;
  screenplayPanel: ReactNode;
};

export type WorkflowPageBuiltSurfaces = {
  canvas: {
    model: WorkflowCanvasSurfaceModel;
    actions: WorkflowCanvasSurfaceActions;
  };
  sidePanels: {
    model: WorkflowSidePanelsSurfaceModel;
    actions: WorkflowSidePanelsSurfaceActions;
  };
  toolbar: {
    model: WorkflowBottomToolbarModel;
    actions: WorkflowBottomToolbarActions;
  };
};
