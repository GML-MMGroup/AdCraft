import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "@xyflow/react/dist/style.css";
import { api } from "../../../api/client";
import { v2Api } from "../../../api/v2Client.ts";
import { useApp } from "../../../AppContextValue";
import { useConversationEventRouter } from "../copilot/useConversationEventRouter.ts";
import { useWorkflowConversationPageActions } from "../copilot/useWorkflowConversationPageActions.ts";
import { useWorkflowConversationController } from "../copilot/useWorkflowConversationController.ts";
import { formatEditableJson } from "./workflowPageFormatters.ts";
import {
  LOCAL_WORKFLOW_ID,
  isBackendWorkflowNode,
} from "./workflowSnapshotModel.ts";
import { useWorkflowPageUiState } from "./useWorkflowPageUiState.ts";
import { useWorkflowMutationGuards } from "./useWorkflowMutationGuards.ts";
import { useWorkflowFinalCompositionActionRefs } from "./useWorkflowFinalCompositionActionRefs.ts";
import { useWorkflowGraphMutationActionRefs } from "./useWorkflowGraphMutationActionRefs.ts";
import { useWorkflowPageLifecycle } from "./useWorkflowPageLifecycle.ts";
import { useWorkflowPageRuntimeControllers } from "./useWorkflowPageRuntimeControllers.ts";
import { useWorkflowPageRuntimeSummaries } from "./useWorkflowPageRuntimeSummaries.ts";
import { useWorkflowPageSurfaceAssembly } from "./useWorkflowPageSurfaceAssembly.tsx";
import { useWorkflowPageScreenplay } from "./useWorkflowPageScreenplay.tsx";
import { useWorkflowPageRunGraphControllers } from "./useWorkflowPageRunGraphControllers.ts";
import { useWorkflowPageSelectionState } from "./useWorkflowPageSelectionState.ts";
import { useWorkflowPageAssetUiState } from "./useWorkflowPageAssetUiState.ts";
import { useWorkflowPageAssetActionControllers } from "./useWorkflowPageAssetActionControllers.ts";
import { useWorkflowPromptPanelState } from "./useWorkflowPromptPanelState.ts";
import { useWorkflowPageRuntimeState } from "./useWorkflowPageRuntimeState.ts";
import { useWorkflowAssetOperations } from "../assets/useWorkflowAssetOperations.ts";
import { useAssetLibrarySaveDialog } from "../assets/useAssetLibrarySaveDialog.ts";
import { useDynamicItemDraftState } from "../assets/useDynamicItemDraftState.ts";
import { useLocalRevisionOperations } from "../assets/useLocalRevisionOperations.ts";
import { useWorkflowReferenceState } from "../assets/useWorkflowReferenceState.ts";
import { createNodeRunMap } from "../../../workflow/runtimeResults.ts";
import { shouldApplyWorkflowScopedResult } from "../../../workflow/sessionGuards.ts";
import { useWorkflowNodeDebugState } from "../../../workflow/useWorkflowNodeDebugState.ts";
import type { CanvasNode } from "../types.ts";
import { getWorkflowNodeType } from "../canvas/workflowNodeModel.ts";
import { useWorkflowCanvasController } from "../canvas/useWorkflowCanvasController.ts";
import { useWorkflowCanvasHistory } from "../canvas/useWorkflowCanvasHistory.ts";
import { useWorkflowDisplayNodeCallbacks } from "../canvas/useWorkflowDisplayNodeCallbacks.ts";
import { useWorkflowDisplayNodes } from "../canvas/useWorkflowDisplayNodes.ts";
import { useCanvasRuntimeEventController, type ScopedWorkflowRefreshPlan } from "../runtime/useCanvasRuntimeEventController.ts";
import { useWorkflowRunController } from "../runtime/useWorkflowRunController.ts";
import { useV2RuntimeController } from "../runtime/useV2RuntimeController.ts";
import { useWorkflowGraphMutationController } from "../graph/useWorkflowGraphMutationController.ts";
import { useWorkflowGraphSyncController } from "../graph/useWorkflowGraphSyncController.ts";
import { useWorkflowWorkbenchModel } from "../workbench/useWorkflowWorkbenchModel.ts";
import { useFinalCompositionPageController } from "../final-composition/useFinalCompositionPageController.ts";
import { useFinalCompositionOperations } from "../final-composition/useFinalCompositionOperations.ts";
import { useV2WorkflowAssets } from "../v2/assets/useV2WorkflowAssets.ts";
import { v2RegionItemsForNode } from "../v2/v2RegionNode.ts";
import { isV2WorkflowId, useWorkflowV2Model } from "../../../workflow-v2/pageAdapter.ts";
import { selectedAssetForSlot } from "../../../workflow-v2/selectors.ts";
import {
  ASSET_LIBRARY_UPLOAD_KIND_OPTIONS,
  DEBUG_LIST_PREVIEW_LIMIT,
  defaultAdRequest,
  demoEdges,
  demoNodes,
  nodeTypes,
} from "./workflowPageDefaults.ts";
import { useSlotMicroEdit } from "../v2/slots/useSlotMicroEdit.ts";
import { useV2SlotOperations } from "../v2/slots/useV2SlotOperations.ts";
import {
  assetLibraryEntityTypeForV2ImageSlot,
  v2ImageSlotLibrarySaveDisplayName,
} from "../v2/slots/v2SlotAssetLibraryModel.ts";
import type {
  AdRequest,
  DynamicMediaItem,
  FrontDeskMessage,
  NodeRunResult,
  WorkflowVariable,
  WorkflowGraph,
  WorkflowNode,
} from "../../../types";

type PendingNodePatch = {
  patch: Partial<WorkflowNode>;
  baseNode: WorkflowNode;
  sourceFlowNode?: CanvasNode;
  timerId: number;
};

export function useWorkflowPageModel() {
  const {
    messages,
    selectedAssets,
    promptLibraryEntities,
    workflow: rawWorkflow,
    nodeRuns,
    activeProjectId,
    workspaceHydrated,
    workspaceRestoreError,
    setMessages,
    setPromptLibraryEntities,
    setWorkflow,
    saveProject,
    startNewProject,
    refreshWorkflowNodes,
  } = useApp();
  const workflowV2Model = useWorkflowV2Model(rawWorkflow);
  const workflow = workflowV2Model.workflow;
  const workflowInlineV2AssetVersions = useMemo(
    () => workflowV2Model.workflowV2?.asset_versions ?? [],
    [workflowV2Model.workflowV2],
  );
  const v2WorkflowAssets = useV2WorkflowAssets({
    workflowId: workflowV2Model.isV2 ? workflow?.workflow_id : null,
    baseAssetVersions: workflowInlineV2AssetVersions,
    listWorkflowAssets: v2Api.listWorkflowAssets,
  });
  const { clearWorkflowAssets } = v2WorkflowAssets;
  const workflowUi = useWorkflowPageUiState();
  const {
    collapsed,
    detailsOpen,
    adPanelOpen,
    videoPanelOpen,
    runPanelOpen,
    variablesPanelOpen,
    mediaLightbox,
    panelOffsets,
  } = workflowUi.state;
  const {
    setCollapsed,
    setDetailsOpen,
    setAdPanelOpen,
    setVideoPanelOpen,
    setRunPanelOpen,
    setVariablesPanelOpen,
    setMediaLightbox,
    commitPanelOffset,
  } = workflowUi.actions;
  const workflowRuntime = useWorkflowPageRuntimeState();
  const {
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
  } = workflowRuntime.state;
  const {
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
  } = workflowRuntime.actions;
  const workflowCanvas = useWorkflowCanvasController({
    workflow,
    initialNodes: demoNodes,
  });
  const {
    selectedNodeId,
    selectedEdgeId,
    reactFlow,
    canvasNodes,
    flowNodes,
    flowEdges,
  } = workflowCanvas.state;
  const {
    setSelectedNodeId,
    setSelectedEdgeId,
    setReactFlow,
    setCanvasNodes,
    setFlowNodes,
    setFlowEdges,
    onNodesChange,
    onEdgesChange,
  } = workflowCanvas.actions;
  const workflowPromptPanel = useWorkflowPromptPanelState(defaultAdRequest);
  const {
    workflowPrompt,
    adRequest,
    runSettings,
    overridePrompt,
  } = workflowPromptPanel.state;
  const {
    setWorkflowPrompt,
    setAdRequest,
    setRunSettings,
    setOverridePrompt,
  } = workflowPromptPanel.actions;
  const canvasHistoryController = useWorkflowCanvasHistory({
    canvasNodes,
    flowNodes,
    flowEdges,
    workflowVariables,
    setCanvasNodes,
    setFlowNodes,
    setFlowEdges,
    setWorkflowVariables,
    setSelectedNodeId,
    setStatus,
  });
  const {
    canvasHistory,
    canvasFuture,
  } = canvasHistoryController.state;
  const {
    snapshotCanvasState,
    captureCanvasHistory,
    restoreCanvasState,
    undoCanvas,
    redoCanvas,
    clearCanvasHistory,
  } = canvasHistoryController.actions;
  const workflowAssetUi = useWorkflowPageAssetUiState();
  const {
    nodeAssetInputRef,
    uploadingAsset,
    nodeUploadKind,
    nodeUploadName,
    nodeUploadTags,
    revisionTarget,
    revisionInstruction,
    v2ProviderTaskRefreshKeyBySlotId,
    revisionHistoryTarget,
    qualityOverrideRevisionId,
  } = workflowAssetUi.state;
  const {
    setUploadingAsset,
    setNodeUploadKind,
    setNodeUploadName,
    setNodeUploadTags,
    setRevisionTarget,
    setRevisionInstruction,
    setV2ProviderTaskRefreshKeyBySlotId,
    setRevisionHistoryTarget,
    setQualityOverrideRevisionId,
  } = workflowAssetUi.actions;
  const workflowAssetOperations = useWorkflowAssetOperations();
  const {
    localRevisionByKey,
    canvasCandidateSummaryByNodeId,
    v2SlotVersionsById,
    revisionCandidateBusyById,
  } = workflowAssetOperations.state;
  const {
    setLocalRevisionByKey,
    setCanvasCandidateSummaryByNodeId,
    setV2SlotVersionsById,
    setRevisionCandidateBusyById,
  } = workflowAssetOperations.actions;
  const dynamicItemDrafts = useDynamicItemDraftState();
  const [activeV2StoryboardItemId, setActiveV2StoryboardItemId] = useState<string | null>(null);
  const {
    libraryEntitiesById: dynamicItemLibraryEntitiesById,
    primaryReferenceIdsById: dynamicItemPrimaryReferenceIdsById,
    referenceTargetId: dynamicItemReferenceTargetId,
    promptDrafts: dynamicItemPromptDrafts,
    promptSavingById: dynamicItemPromptSavingById,
    runningById: dynamicItemRunningById,
  } = dynamicItemDrafts.state;
  const {
    setLibraryEntitiesById: setDynamicItemLibraryEntitiesById,
    setPrimaryReferenceIdsById: setDynamicItemPrimaryReferenceIdsById,
    setReferenceTargetId: setDynamicItemReferenceTargetId,
    setPromptDrafts: setDynamicItemPromptDrafts,
    setPromptSavingById: setDynamicItemPromptSavingById,
    setRunningById: setDynamicItemRunningById,
    resetDynamicItemState,
    changeDynamicItemPrompt,
    removeDynamicItemLibraryEntity,
    toggleDynamicItemPrimaryReference,
  } = dynamicItemDrafts.actions;
  const finalCompositionPage = useFinalCompositionPageController();
  const {
    timelineState: finalCompositionTimelineState,
    timelineBaselineVersion: finalCompositionTimelineBaselineVersion,
    exportId,
    exportResult,
    exportSettings,
  } = finalCompositionPage.state;
  const {
    setExportId,
    setExportResult,
    setExportSettings,
    resetExportState,
    timelineLoadStarted,
    timelineLoadFailed,
    applyTimelineResponse: applyFinalCompositionTimelineResponse,
    setTimelineConflict: setFinalCompositionTimelineConflict,
    markTimelineEventDirty,
    timelineSaveStarted,
    timelineSaveFailed,
    timelineRenderStarted,
    timelineRenderFailed,
    timelineRenderFinished,
    moveClip: moveFinalCompositionClip,
    toggleClip: toggleFinalCompositionClip,
    changeClipNumber: changeFinalCompositionClipNumber,
    changeSubtitleText: changeFinalCompositionSubtitleText,
    selectAudioSource: selectFinalCompositionAudioSource,
    addSourceAsImageClip: addFinalCompositionSourceAsImageClip,
    removeClip: removeFinalCompositionClip,
  } = finalCompositionPage.actions;
  const finalCompositionOperationsRef = useRef<ReturnType<typeof useFinalCompositionOperations> | null>(null);
  const {
    prepareFinalCompositionRun,
    pollStoryboardVideoMedia,
    refreshMediaStatus,
    refreshSelectedNodeRun,
    reviewSelectedNodeQuality,
    exportEditedVideo,
    refreshVideoExport,
    loadFinalCompositionTimeline,
    saveFinalCompositionTimeline,
    renderFinalCompositionTimeline,
    applyMediaStatusToCanvas,
  } = useWorkflowFinalCompositionActionRefs(finalCompositionOperationsRef);
  const workflowGraphMutationsRef = useRef<ReturnType<typeof useWorkflowGraphMutationController> | null>(null);
  const {
    saveCanvas,
    createNewProjectFromCanvas,
    updateSelectedPrompt,
    applySystemSuggestion,
    applyOptimizedPrompt,
    regenerateOptimizedPrompt,
    updateSelectedConfig,
    uploadAssetForSelectedNode,
    removeSelectedInputAsset,
    addWorkflowVariable,
    updateWorkflowVariable,
    deleteWorkflowVariable,
    deleteSelection,
    deleteNodeFromBackend,
    deleteEdgeFromBackend,
    autoLayout,
    persistNodePosition,
    handleConnect,
    handleReconnect,
    handleReconnectEnd,
  } = useWorkflowGraphMutationActionRefs(workflowGraphMutationsRef);
  const v2SlotMicroEdit = useSlotMicroEdit();
  const workflowConversation = useWorkflowConversationController();
  const {
    agentConversations,
    activeConversationId,
    conversationEventsById,
    conversationMentionReferences,
    conversationNodeReferences,
    conversationTargetReferences,
    conversationLoading,
    conversationSending,
    conversationError,
    actionBusyById,
  } = workflowConversation.state;
  const {
    setAgentConversations,
    setActiveConversationId,
    setConversationEventsById,
    setConversationMentionReferences,
    setConversationNodeReferences,
    setConversationTargetReferences,
    setConversationLoading,
    setConversationSending,
    setConversationError,
    setActionBusyById,
  } = workflowConversation.actions;
  const nodeRunByType = useMemo(() => createNodeRunMap(nodeRuns), [nodeRuns]);
  const workflowMutationGuards = useWorkflowMutationGuards({
    workflowId: workflow?.workflow_id,
    activeProjectId,
    selectedNodeId,
  });
  const {
    activeWorkflowIdRef,
    selectedNodeIdRef,
    currentNodeRunRequestRef,
    chatCanvasExecutionRequestRef,
  } = workflowMutationGuards.state;
  const {
    beginWorkflowMutationScope,
    shouldApplyWorkflowMutationScope,
    shouldApplyCurrentNodeRun,
  } = workflowMutationGuards.actions;
  const pendingNodePatches = useRef<Map<string, PendingNodePatch>>(new Map());
  const currentNodeRunningRef = useRef(false);
  const v2RuntimeRef = useRef<ReturnType<typeof useV2RuntimeController> | null>(null);
  const v2SlotOperationsRef = useRef<ReturnType<typeof useV2SlotOperations> | null>(null);
  const localRevisionOperationsRef = useRef<ReturnType<typeof useLocalRevisionOperations> | null>(null);
  const bridgeFrontDeskMessagesToAgentConversationRef = useRef<((requestWorkflowId: string, plannedMessages: FrontDeskMessage[]) => Promise<void>) | null>(null);
  const selectedDynamicMediaItemsRef = useRef<DynamicMediaItem[]>([]);
  const canvasRuntimeActionsRef = useRef<Pick<ReturnType<typeof useCanvasRuntimeEventController>["actions"], "queueScopedWorkflowRefresh" | "scopedRefreshPlanFromHints"> | null>(null);
  const workflowRunActionsRef = useRef<Pick<ReturnType<typeof useWorkflowRunController>["actions"], "refreshExecutionRuntime" | "applyWorkflowRunSummary"> | null>(null);
  const workflowId = workflow?.workflow_id ?? LOCAL_WORKFLOW_ID;
  const isRestoringWorkspace = Boolean(activeProjectId && !workspaceHydrated && !workflow);
  const workflowGraphSync = useWorkflowGraphSyncController({
    workflow,
    workflowV2Model,
    flowNodes,
    flowEdges,
    nodeRunByType,
    selectedAssets,
    v2SlotVersionsById,
    activeWorkflowIdRef,
    reactFlow,
    v2WorkflowAssets,
    syncV2RuntimeSnapshot: async (requestWorkflowId) => {
      await v2RuntimeRef.current?.syncSnapshot(requestWorkflowId);
    },
    refreshWorkflowNodes,
    refreshMediaStatus,
    setWorkflow,
    setAdRequest,
    setWorkflowVariables,
    setCanvasNodes,
    setFlowNodes,
    setFlowEdges,
    setSelectedNodeId,
    setDetailsOpen,
    setSavedAt,
    setV2SlotVersionsById,
    setValidationResult,
    setStatus,
    setAffectedNodes,
  });
  const {
    applyWorkflowGraph,
    applyWorkflowV2,
    captureV2WorkflowApplicationRevision,
    isCurrentV2WorkflowApplicationRevision,
    refreshV2WorkflowGraph,
    refreshV2WorkflowStructure,
    refreshV2AssetsAndRetryMissing,
    currentWorkflowIsV2,
    assertNotV2WorkflowForV1Api,
    loadV2ResolvedInputs,
    loadV2NodeVersions,
    refreshWorkflowGraph,
    validateBackendGraph,
    patchWorkflowNodeState,
    markNodesStale,
    noteAffected,
    syncFrontDeskAdRequest,
    syncWorkflowAdRequest,
    applyNodeRunsToCanvas,
  } = workflowGraphSync.actions;
  const screenplay = useWorkflowPageScreenplay({
    activeWorkflowId: workflowV2Model.isV2 ? workflow?.workflow_id ?? null : null,
    workflowItems: workflowV2Model.workflowV2?.items ?? canvasNodes.flatMap(v2RegionItemsForNode),
    refreshV2WorkflowGraph,
    refreshV2WorkflowStructure,
    syncV2RuntimeSnapshot: async (requestWorkflowId) => v2RuntimeRef.current?.syncSnapshot(requestWorkflowId),
  });
  const {
    selectedResolvedInputs,
    setSelectedResolvedInputs,
    nodeVersions,
    setNodeVersions,
    debugLoadState,
    ensureNodeVersions,
    refreshNodeVersions,
    ensureSelectedResolvedInputs,
    refreshSelectedResolvedInputs,
    invalidateNodeDebugCache,
  } = useWorkflowNodeDebugState({
    workflowId: workflow?.workflow_id,
    selectedNodeId,
    isBackendWorkflowNode: (nodeId) => isBackendWorkflowNode(nodeId, workflow),
    isCurrentWorkflow: (requestWorkflowId) => shouldApplyWorkflowScopedResult(requestWorkflowId, activeWorkflowIdRef.current),
    loadResolvedInputs: (requestWorkflowId, nodeId) =>
      currentWorkflowIsV2() ? loadV2ResolvedInputs(requestWorkflowId, nodeId) : api.resolvedNodeInputs(requestWorkflowId, nodeId),
    loadNodeVersions: (requestWorkflowId, nodeId) =>
      currentWorkflowIsV2() ? loadV2NodeVersions(requestWorkflowId, nodeId) : api.workflowNodeVersions(requestWorkflowId, nodeId),
  });
  const {
    appendConversationEventForConversation,
    appendConversationEventsForConversation,
    selectConversationActionTarget,
    clearPendingNodePatch,
    clearNodeDebugCache,
    dynamicMediaItemAssetFromRevisionEvent,
  } = useWorkflowConversationPageActions({
    selectedDynamicMediaItemsRef,
    pendingNodePatches,
    setConversationEventsById,
    setSelectedNodeId,
    setDetailsOpen,
    invalidateNodeDebugCache,
  });
  const conversationEventRouter = useConversationEventRouter({
    activeWorkflowIdRef,
    selectedNodeIdRef,
    chatCanvasExecutionRequestRef,
    setStatus,
    setDynamicItemPromptDrafts,
    setDynamicItemRunningById,
    setActiveExecutionId,
    setExecutionPollingState,
    setWorkflowRun,
    clearPendingNodePatch,
    clearNodeDebugCache,
    markNodesStale,
    queueScopedWorkflowRefresh: (requestWorkflowId, plan) => {
      canvasRuntimeActionsRef.current?.queueScopedWorkflowRefresh(requestWorkflowId, plan);
    },
    scopedRefreshPlanFromHints: (refreshHints, targetNodeId) =>
      canvasRuntimeActionsRef.current?.scopedRefreshPlanFromHints(refreshHints, targetNodeId) ?? { nodeIds: [], resolvedInputNodeIds: [] },
    refreshExecutionRuntime: (requestWorkflowId, executionId) =>
      workflowRunActionsRef.current?.refreshExecutionRuntime(requestWorkflowId, executionId) ?? Promise.resolve(null),
    applyWorkflowRunSummary: (result) => {
      workflowRunActionsRef.current?.applyWorkflowRunSummary(result);
    },
    updateLocalRevisionCardState: (key, patch) => {
      localRevisionOperationsRef.current?.actions.updateLocalRevisionCardState(key, patch);
    },
    loadLocalAssetHistory: (requestWorkflowId, nodeId, asset) =>
      localRevisionOperationsRef.current?.actions.loadLocalAssetHistory(requestWorkflowId, nodeId, asset) ?? Promise.resolve(null),
    dynamicMediaItemAssetFromRevisionEvent,
  });
  const {
    handleAgentConversationEvents,
    handleNodePromptUpdatedEvent,
    handleItemPromptUpdatedEvent,
    handleRevisionConversationEvent,
  } = conversationEventRouter.actions;
  const workflowPageRuntimeControllers = useWorkflowPageRuntimeControllers({
    workflow,
    workflowV2Model,
    activeWorkflowIdRef,
    selectedNodeIdRef,
    activeConversationId,
    revisionHistoryTarget,
    v2SlotVersionsById,
    v2SlotMicroEdit,
    v2RuntimeRef,
    v2SlotOperationsRef,
    localRevisionOperationsRef,
    currentWorkflowIsV2,
    nodeRunByType,
    setWorkflow,
    syncWorkflowAdRequest,
    setCanvasNodes,
    setWorkflowVariables,
    setFlowNodes,
    setFlowEdges,
    setSelectedNodeId,
    setSavedAt,
    setActiveExecutionId,
    setExecutionPollingState,
    setWorkflowRunning,
    setStatus,
    setRunningNodeIds,
    setMediaStatus,
    setCanvasCandidateSummaryByNodeId,
    setLocalRevisionByKey,
    setQualityOverrideRevisionId,
    setV2ProviderTaskRefreshKeyBySlotId,
    setSelectedNodeRun,
    applyMediaStatusToCanvas,
    applyNodeRunsToCanvas,
    clearNodeDebugCache,
    refreshSelectedResolvedInputs,
    refreshWorkflowGraph,
    refreshMediaStatus,
    refreshV2WorkflowGraph,
    refreshV2WorkflowStructure,
    refreshV2AssetsAndRetryMissing,
    noteAffected,
    timelineLoadStarted,
    timelineLoadFailed,
    applyFinalCompositionTimelineResponse,
    markTimelineEventDirty,
    timelineRenderStarted,
    timelineRenderFailed,
    timelineRenderFinished,
    appendConversationEventForConversation,
    handleAgentConversationEvents,
    handleNodePromptUpdatedEvent,
    handleItemPromptUpdatedEvent,
    handleRevisionConversationEvent,
    screenplayActionsRef: screenplay.actionsRef,
  });
  const { canvasRuntimeEvents, v2Runtime, workflowV2Controller, v2NodeRuntimeStatusById, v2ActiveEdgeSourceNodeIds, v2SlotRuntimeStatusById } = workflowPageRuntimeControllers;
  const {
    canvasRuntimeConnectionState,
    canvasRuntimeStatusById,
    canvasRuntimeActiveEdgeIds,
  } = canvasRuntimeEvents.state;
  const {
    applyV2RuntimeEventsToPage,
    startCanvasRuntimeSubscription,
    stopCanvasRuntimeSubscription,
    queueScopedWorkflowRefresh,
    scopedRefreshPlanFromHints,
  } = canvasRuntimeEvents.actions;
  canvasRuntimeActionsRef.current = canvasRuntimeEvents.actions;
  const canvasRuntimeNodeStatusById = useMemo(
    () => ({ ...executionNodeStatusById, ...canvasRuntimeStatusById }),
    [executionNodeStatusById, canvasRuntimeStatusById],
  );
  const {
    visibleCanvasNodes,
    visibleNodeRuns,
    selectedPlanNode,
    copilotPanelEvents,
    selectedRunType,
    selectedRun,
  } = useWorkflowPageSelectionState({
    workflow,
    messages,
    canvasNodes,
    nodeRuns,
    nodeRunByType,
    selectedNodeId,
    selectedNodeRun,
    activeConversationId,
    conversationEventsById,
  });
  const workflowReferenceState = useWorkflowReferenceState({
    selectedPlanNode,
    selectedAssets,
    promptLibraryEntities,
    setPromptLibraryEntities,
    dynamicItemLibraryEntitiesById,
    setDynamicItemLibraryEntitiesById,
    dynamicItemPrimaryReferenceIdsById,
    setDynamicItemPrimaryReferenceIdsById,
    dynamicItemReferenceTargetId,
    setDynamicItemReferenceTargetId,
  });
  const {
    pickerTarget,
    nodeRunLibraryEntities,
    revisionLibraryEntities,
    promptPrimaryReferenceIds,
    nodeRunPrimaryReferenceIds,
    revisionPrimaryReferenceIds,
    workflowPromptMentionReferences,
    nodePromptMentionReferences,
    overrideMentionReferences,
  } = workflowReferenceState.state;
  const {
    setPickerTarget,
    setRevisionLibraryEntities,
    setRevisionPrimaryReferenceIds,
    setWorkflowPromptMentionReferences,
    setNodePromptMentionReferences,
    setOverrideMentionReferences,
    chatAssetReferences,
    workflowPromptAssetReferences,
    nodeScopedAssetReferences,
    dynamicItemScopedAssetReferences,
    openDynamicItemLibraryReference,
    selectedLibraryEntitiesForTarget,
    toggleLibraryEntityForTarget,
    removeLibraryEntityForTarget,
    togglePrimaryReferenceForTarget,
  } = workflowReferenceState.actions;
  const workflowWorkbenchModel = useWorkflowWorkbenchModel({
    selectedPlanNode,
    selectedRun,
    selectedResolvedInputs,
    mediaStatus,
    currentWorkflowIsV2,
  });
  const {
    selectedOutputAssets,
    selectedDynamicMediaItems,
    selectedStrictReferenceFailure,
    selectedActiveOutputWarning,
    selectedPanelModel,
    selectedNodeUsesV2InlineRegionEditing,
    selectedEditablePrompt,
    selectedSystemSuggestion,
    selectedOptimizedPrompt,
    selectedProviderPrompt,
    hasNewSystemSuggestion,
    selectedResolvedContext,
    selectedResolvedAssets,
    selectedMaterializedPrompt,
    selectedMaterializedAssets,
    selectedSourceMappings,
    selectedReferencePolicy,
    selectedProviderDebug,
    selectedProviderReferencePlan,
    selectedAssetFlowDebug,
    selectedAssetBindings,
    selectedIdentityCertification,
    selectedPromptOptimizerDebug,
    selectedQualitySummary,
    selectedMissingInputs,
    selectedStaleUpstreamNodes,
    selectedLockedUpstreamNodes,
    assetLibrarySourceMappings,
    displayInputAssets,
    assetLibraryResolvedAssets,
    derivedLibraryEntityIds,
    hasResolvedDebugData,
  } = workflowWorkbenchModel;
  selectedDynamicMediaItemsRef.current = selectedDynamicMediaItems;
  const assetLibrarySaveDialog = useAssetLibrarySaveDialog({
    workflow,
    selectedPlanNode,
    selectedOutputAssets,
    setStatus,
  });
  const {
    assetLibrarySaveTarget,
    assetLibraryDisplayName,
    assetLibraryTags,
    assetLibrarySaveFeedback: assetLibraryFeedback,
    savingAssetLibrary: assetLibrarySaving,
  } = assetLibrarySaveDialog.state;
  const {
    setAssetLibrarySaveTarget,
    setAssetLibraryDisplayName,
    setAssetLibraryTags,
    setAssetLibrarySaveFeedback,
    openAssetLibrarySaveDialog,
    submitAssetLibrarySave,
  } = assetLibrarySaveDialog.actions;
  const {
    videoTimeline,
    activeV2SlotId,
    selectedV2Items,
    selectedV2Slots,
    selectedV2SlotsByItemId,
    slotVersionAssets,
    selectedV2AssetVersions,
    v2ReferenceAssetsBySlotId,
    selectedV2ReferenceAssets,
    v2LibraryReferenceOptions,
    selectedFreeGenerationMediaType,
    selectedFreeAbsorbTargetNodes,
    v2SlotOperations,
    localRevisionOperations,
    finalCompositionOperations,
    dynamicMediaOperations,
  } = useWorkflowPageAssetActionControllers({
    workflow,
    workflowV2Model,
    v2WorkflowAssets,
    selectedPlanNode,
    selectedAssets,
    promptLibraryEntities,
    v2SlotVersionsById,
    visibleCanvasNodes,
    v2SlotMicroEdit,
    currentWorkflowIsV2,
    activeWorkflowIdRef,
    dynamicItemPromptDrafts,
    setStatus,
    setSelectedNodeId,
    setDynamicItemPromptSavingById,
    setDynamicItemPromptDrafts,
    setV2SlotVersionsById,
    applyWorkflowV2,
    captureV2WorkflowApplicationRevision,
    isCurrentV2WorkflowApplicationRevision,
    refreshV2WorkflowGraph,
    v2Runtime,
    refreshV2AssetsAndRetryMissing,
    selectedNodeIdRef,
    v2SlotOperationsRef,
    revisionTarget,
    revisionInstruction,
    revisionLibraryEntities,
    revisionPrimaryReferenceIds,
    setRevisionInstruction,
    setRevisionTarget,
    setRevisionLibraryEntities,
    setRevisionPrimaryReferenceIds,
    setRevisionHistoryTarget,
    setLocalRevisionByKey,
    setRevisionCandidateBusyById,
    setQualityOverrideRevisionId,
    setSelectedNodeRun,
    saveCanvas,
    refreshWorkflowNodes,
    refreshWorkflowGraph,
    refreshMediaStatus,
    refreshSelectedResolvedInputs,
    applyNodeRunsToCanvas,
    noteAffected,
    localRevisionOperationsRef,
    canvasNodes,
    nodeRuns,
    mediaStatus,
    flowNodes,
    selectedRun,
    finalCompositionTimelineState,
    finalCompositionTimelineBaselineVersion,
    exportId,
    exportSettings,
    setMediaStatus,
    setCanvasNodes,
    setFlowNodes,
    setSelectedResolvedInputs,
    setQualityReviewingNodeIds,
    setExportResult,
    setExportId,
    timelineLoadStarted,
    timelineLoadFailed,
    applyFinalCompositionTimelineResponse,
    setFinalCompositionTimelineConflict,
    timelineSaveStarted,
    timelineSaveFailed,
    timelineRenderStarted,
    timelineRenderFailed,
    timelineRenderFinished,
    patchWorkflowNodeState,
    finalCompositionOperationsRef,
    selectedNodeId,
    dynamicItemLibraryEntitiesById,
    detailsOpen,
    setDynamicItemRunningById,
    dynamicItemScopedAssetReferences,
  });
  const {
    saveV2ItemPrompt,
    saveV2SlotPrompt,
    v2SlotById,
    setActiveV2SlotId,
    openV2SlotEditor,
    changeV2SlotPrompt,
    changeV2SlotNegativePrompt,
    syncV2SlotPromptReferences,
    uploadV2SlotReference,
    selectV2SlotLibraryReference,
    replaceV2SlotWithLibraryEntity,
    removeV2SlotReference,
    loadV2SlotVersions,
    defaultV2SlotForCurrentNode,
    submitV2SlotMicroPrompt,
    submitV2LocalSlotPrompt,
    submitV2StoryboardPrompt,
    runSelectedV2Slot,
    pollV2ProviderTask,
    selectV2SlotVersion,
    discardV2WorkingVersion,
    deleteV2SelectedSlotAsset,
    attachV2Reference,
    removeV2Reference,
    confirmV2ShotSummary,
    createV2FinalTimelineClip,
    deleteV2FinalTimelineClip,
    createV2FreeNode,
    generateV2FreeNode,
    absorbV2FreeNode,
    deleteV2FreeNode,
  } = v2SlotOperations.actions;
  const activeV2Slot = activeV2SlotId ? v2SlotById(activeV2SlotId) : null;
  const openV2SlotAssetLibraryReplace = useCallback((slotId: string) => {
    const slot = v2SlotById(slotId);
    if (!slot) return;
    const entityType = assetLibraryEntityTypeForV2ImageSlot(slot);
    if (!entityType) {
      setStatus("Only V2 image slots can be replaced from the Asset Library.");
      return;
    }
    openV2SlotEditor(slotId);
    setPickerTarget("v2-slot-replace");
  }, [openV2SlotEditor, setPickerTarget, setStatus, v2SlotById]);
  const openV2SlotAssetLibrarySave = useCallback((slotId: string) => {
    const slot = v2SlotById(slotId);
    if (!slot) return;
    const entityType = assetLibraryEntityTypeForV2ImageSlot(slot);
    if (!entityType) {
      setStatus("Only V2 image slots can be saved to the Asset Library.");
      return;
    }
    const asset = selectedAssetForSlot(slot, selectedV2AssetVersions);
    if (!asset?.asset_id) {
      setStatus("Current V2 image slot has no selected image to save.");
      return;
    }
    const displayName = v2ImageSlotLibrarySaveDisplayName(slot, asset);
    setAssetLibrarySaveTarget({
      node: {
        id: slot.node_id,
        workflow_id: workflow?.workflow_id,
        node_type: slot.node_id,
        category: "image_generation",
        title: displayName,
      },
      entityType,
      sourceEntityId: slot.slot_id,
      assetIds: [asset.asset_id],
      displayName,
    });
    setAssetLibraryDisplayName(displayName);
    setAssetLibraryTags("");
    setAssetLibrarySaveFeedback("");
  }, [
    selectedV2AssetVersions,
    setAssetLibraryDisplayName,
    setAssetLibrarySaveFeedback,
    setAssetLibrarySaveTarget,
    setAssetLibraryTags,
    setStatus,
    v2SlotById,
    workflow?.workflow_id,
  ]);
  const {
    updateLocalRevisionCardState,
    applyLocalRevisionState,
    submitAssetRevision,
    startLocalAssetRevision,
    pollLocalAssetRevision,
    loadLocalAssetHistory,
    openLocalAssetHistory,
    selectLocalAssetHistoryVersion,
    acceptLocalRevisionCandidate,
    rejectLocalRevisionCandidate,
  } = localRevisionOperations.actions;
  const {
    saveDynamicItemPrompt,
    runDynamicMediaItem,
    refreshDynamicItemBackendState,
    applyDynamicItemCurrentVersion,
    batchUseDynamicItemCurrentVersions,
    generateStoryboardShotVideo,
    generateMissingStaleStoryboardVideos,
    regenerateAllSelectedStoryboardVideos,
    applyCurrentStoryboardVideosForComposition,
    openDynamicItemHistory,
  } = dynamicMediaOperations.actions;
  const workflowPageRunGraphControllers = useWorkflowPageRunGraphControllers({
    ...workflowRuntime.state,
    ...workflowRuntime.actions,
    ...workflowCanvas.state,
    ...workflowCanvas.actions,
    ...workflowPromptPanel.state,
    ...workflowPromptPanel.actions,
    ...canvasHistoryController.actions,
    ...workflowAssetUi.state,
    ...workflowAssetUi.actions,
    workflow,
    workflowId,
    workflowConversation,
    messages,
    setMessages,
    nodeRuns,
    nodeRunByType,
    selectedAssets,
    promptLibraryEntities,
    workflowVariables,
    activeProjectId,
    isRestoringWorkspace,
    selectedPlanNode,
    selectedRunType,
    selectedSystemSuggestion,
    selectedOptimizedPrompt,
    selectedResolvedInputs,
    selectedV2Items,
    visibleCanvasNodes,
    promptPrimaryReferenceIds,
    nodeRunLibraryEntities,
    nodeScopedAssetReferences,
    workflowPromptAssetReferences,
    dynamicItemScopedAssetReferences,
    staleReason,
    currentWorkflowIsV2,
    assertNotV2WorkflowForV1Api,
    beginWorkflowMutationScope,
    shouldApplyWorkflowMutationScope,
    shouldApplyCurrentNodeRun,
    activeWorkflowIdRef,
    currentNodeRunningRef,
    currentNodeRunRequestRef,
    bridgeFrontDeskMessagesToAgentConversationRef,
    workflowRunActionsRef,
    workflowGraphMutationsRef,
    pendingNodePatches,
    v2Runtime,
    workflowV2Controller,
    defaultV2SlotForCurrentNode,
    flushV2SlotDrafts: () => v2SlotOperationsRef.current?.actions.flushV2SlotDrafts() ?? Promise.resolve(),
    refreshV2AssetsAndRetryMissing,
    refreshV2WorkflowGraph,
    refreshWorkflowGraph,
    refreshWorkflowNodes,
    refreshMediaStatus,
    refreshSelectedResolvedInputs,
    refreshNodeVersions,
    validateBackendGraph,
    saveCanvas,
    prepareFinalCompositionRun,
    pollStoryboardVideoMedia,
    applyNodeRunsToCanvas,
    applyMediaStatusToCanvas,
    patchWorkflowNodeState,
    markNodesStale,
    noteAffected,
    syncFrontDeskAdRequest,
    applyWorkflowV2,
    applyV2RuntimeEventsToPage,
    handleAgentConversationEvents,
    queueScopedWorkflowRefresh,
    getWorkflowNodeType,
    saveProject,
    startNewProject,
    resetExportState,
  });
  const { uploadV2PromptInputAsset } = workflowPageRunGraphControllers;
  const {
    getCurrentRunAdRequest,
    clearExecutionRuntime,
    refreshExecutionRuntime,
    executeWorkflowRun,
    applyWorkflowRunSummary,
    runFrontDeskChatOnly,
    planWorkflowFromPanelChat,
    generateWorkflowFromPanelChat,
    planStructuredWorkflow,
    generateStructuredWorkflow,
    runWorkflow,
    runFromSelected,
    runNode,
  } = workflowPageRunGraphControllers.workflowRunController.actions;
  const {
    loadAgentConversations,
    createAgentConversation,
    sendAgentConversationMessage,
    sendV2ChatTargetMessage,
    sendCopilotMessage,
    applyConversationAction,
    rejectConversationAction,
  } = workflowPageRunGraphControllers.agentConversationBridge.actions;
  const {
    effectiveNodeStatusById,
    conversationNodeMentionOptions,
    candidateSummaryByNodeId,
    dynamicItemRunningByNodeId,
  } = useWorkflowPageRuntimeSummaries({
    workflowIsV2: workflowV2Model.isV2,
    v2NodeRuntimeStatusById,
    canvasRuntimeNodeStatusById,
    canvasNodes,
    selectedPlanNode,
    selectedNodeId,
    selectedDynamicMediaItems,
    selectedOutputAssets,
    localRevisionByKey,
    workflowId,
    canvasCandidateSummaryByNodeId,
    dynamicItemRunningById,
  });
  const { openMediaLightbox, displayNodeCallbacks } = useWorkflowDisplayNodeCallbacks({
    selectedNodeIdRef,
    setSelectedNodeId,
    setDetailsOpen,
    setMediaLightbox,
    onOpenScreenplay: screenplay.openScreenplay,
    workflowV2Items: workflowV2Model.workflowV2?.items,
    setActiveV2StoryboardItemId,
    openV2SlotEditor,
    setActiveV2SlotId,
    changeV2SlotPrompt,
    changeV2SlotNegativePrompt,
    uploadV2SlotReference,
    selectV2SlotLibraryReference,
    removeV2SlotReference,
    openV2SlotAssetLibraryReplace,
    openV2SlotAssetLibrarySave,
    saveV2ItemPrompt,
    submitV2SlotMicroPrompt,
    selectV2SlotVersion,
    discardV2WorkingVersion,
    loadV2SlotVersions,
  });
  const { displayNodes, activeRuntimeEdgeIds, displayEdges } = useWorkflowDisplayNodes({
    flowNodes,
    flowEdges,
    selectedEdgeId,
    effectiveNodeStatusById,
    candidateSummaryByNodeId,
    activeProjectId,
    workflowId,
    dynamicItemRunningByNodeId,
    v2AssetVersions: v2WorkflowAssets.assetVersions,
    slotVersionAssets,
    v2Runtime: v2Runtime.runtime,
    v2FallbackRuntime: workflowV2Model.workflowV2?.runtime,
    v2SlotRuntimeStatusById,
    activeV2SlotId,
    activeV2StoryboardItemId,
    v2SlotDraftsById: v2SlotMicroEdit.state.draftsBySlotId,
    v2ReferenceAssetsBySlotId,
    v2LibraryReferenceOptions,
    canvasRuntimeActiveEdgeIds,
    runningNodeIds,
    v2ActiveEdgeSourceNodeIds,
    isV2: workflowV2Model.isV2,
    callbacks: displayNodeCallbacks,
  });

  useEffect(() => {
    clearExecutionRuntime();
    setV2SlotVersionsById({});
    clearWorkflowAssets(workflow?.workflow_id ?? null);
  }, [workflow?.workflow_id, activeProjectId, clearExecutionRuntime, clearWorkflowAssets, setV2SlotVersionsById]);

  useEffect(() => {
    if (!workflow?.workflow_id || workflow.workflow_id === LOCAL_WORKFLOW_ID) {
      stopCanvasRuntimeSubscription();
      return;
    }
    if (isV2WorkflowId(workflow.workflow_id) || currentWorkflowIsV2()) {
      stopCanvasRuntimeSubscription();
      return;
    }
    startCanvasRuntimeSubscription(workflow.workflow_id);
    return () => stopCanvasRuntimeSubscription();
  }, [
    workflow?.workflow_id,
    workflowV2Model.isV2,
    workflow?.metadata?.workflow_schema_version,
    activeProjectId,
    currentWorkflowIsV2,
    startCanvasRuntimeSubscription,
    stopCanvasRuntimeSubscription,
  ]);

  useEffect(() => {
    setNodePromptMentionReferences([]);
    setOverrideMentionReferences([]);
    resetDynamicItemState();
  }, [selectedNodeId, resetDynamicItemState, setNodePromptMentionReferences, setOverrideMentionReferences]);

  useEffect(() => {
    if (!detailsOpen || !workflow?.workflow_id || selectedNodeId !== "final-composition") return;
    void loadFinalCompositionTimeline(workflow.workflow_id);
  }, [detailsOpen, workflow?.workflow_id, selectedNodeId, loadFinalCompositionTimeline]);

  useWorkflowPageLifecycle({
    workflow,
    workflowId,
    workflowSchemaVersion: workflow?.metadata?.workflow_schema_version,
    workflowV2IsV2: workflowV2Model.isV2,
    activeProjectId,
    isRestoringWorkspace,
    currentWorkflowIsV2,
    nodeRunByType,
    canvasNodes,
    flowNodes,
    flowEdges,
    selectedNodeId,
    reactFlow,
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
  });

  useEffect(() => {
    const nodePatches = pendingNodePatches.current;
    return () => {
      nodePatches.forEach((pending) => window.clearTimeout(pending.timerId));
      nodePatches.clear();
    };
  }, []);

  const workflowPageSurface = useWorkflowPageSurfaceAssembly({
    ...workflowUi.state, ...workflowUi.actions,
    ...workflowRuntime.state, ...workflowRuntime.actions,
    ...workflowCanvas.state, ...workflowCanvas.actions,
    ...workflowPromptPanel.state, ...workflowPromptPanel.actions,
    ...canvasHistoryController.state, ...canvasHistoryController.actions,
    ...workflowAssetUi.state, ...workflowAssetUi.actions,
    ...workflowAssetOperations.state, ...workflowAssetOperations.actions,
    ...dynamicItemDrafts.state, ...dynamicItemDrafts.actions,
    ...finalCompositionPage.state, ...finalCompositionPage.actions,
    ...workflowConversation.state, ...workflowConversation.actions,
    workflow, workflowV2Model, workflowWorkbenchModel, v2Runtime, screenplay,
    displayNodes, displayEdges, nodeTypes, isRestoringWorkspace, workspaceRestoreError,
    selectedPlanNode, selectedRun, selectedAssets, selectedOutputAssets, selectedNodeId, selectedEdgeId,
    selectedV2Items, selectedV2SlotsByItemId, selectedV2AssetVersions, selectedV2ReferenceAssets,
    v2LibraryReferenceOptions, selectedFreeGenerationMediaType, selectedFreeAbsorbTargetNodes,
    selectedNodeUsesV2InlineRegionEditing, visibleNodeRuns, visibleCanvasNodes, activeV2SlotId, activeV2Slot,
    activeV2StoryboardItemId, setActiveV2StoryboardItemId,
    slotVersionAssets, v2SlotRuntimeStatusById, v2SlotDraftsById: v2SlotMicroEdit.state.draftsBySlotId,
    v2ReferenceAssetsBySlotId, v2ActiveEdgeSourceNodeIds,
    videoTimeline, copilotPanelEvents, nodeRunLibraryEntities, nodeRunPrimaryReferenceIds,
    nodePromptMentionReferences, workflowPromptMentionReferences, overrideMentionReferences, promptPrimaryReferenceIds,
    dynamicItemPromptDrafts, dynamicItemPromptSavingById, dynamicItemRunningById,
    dynamicItemLibraryEntitiesById, dynamicItemPrimaryReferenceIdsById,
    revisionLibraryEntities, revisionPrimaryReferenceIds, assetLibrarySaveTarget, assetLibraryDisplayName,
    assetLibraryTags, assetLibraryFeedback, assetLibrarySaving,
    assetLibraryUploadKindOptions: ASSET_LIBRARY_UPLOAD_KIND_OPTIONS,
    finalCompositionTimelineState, debugLoadState, nodeVersions, debugListPreviewLimit: DEBUG_LIST_PREVIEW_LIMIT, formatEditableJson,
    canvasRuntimeConnectionState, canvasRuntimeActiveEdgeIds,
    handleConnect, handleReconnect, handleReconnectEnd, deleteNodeFromBackend, deleteEdgeFromBackend,
    persistNodePosition, createNewProjectFromCanvas, runWorkflow, saveCanvas, deleteSelection, autoLayout,
    refreshSelectedNodeRun, refreshV2WorkflowGraph,
    saveV2ItemPrompt, confirmV2ShotSummary, createV2FinalTimelineClip, deleteV2FinalTimelineClip,
    runSelectedV2Slot, loadV2SlotVersions, saveV2SlotPrompt, selectV2SlotVersion, discardV2WorkingVersion,
    setActiveV2SlotId, changeV2SlotPrompt, changeV2SlotNegativePrompt, uploadV2SlotReference,
    syncV2SlotPromptReferences, selectV2SlotLibraryReference, replaceV2SlotWithLibraryEntity, removeV2SlotReference,
    openV2SlotAssetLibraryReplace, openV2SlotAssetLibrarySave, submitV2SlotMicroPrompt,
    submitV2LocalSlotPrompt, submitV2StoryboardPrompt,
    deleteV2SelectedSlotAsset, pollV2ProviderTask, attachV2Reference, createV2FreeNode, generateV2FreeNode,
    absorbV2FreeNode, deleteV2FreeNode, removeV2Reference,
    updateSelectedPrompt, applySystemSuggestion, regenerateOptimizedPrompt, applyOptimizedPrompt,
    uploadAssetForSelectedNode, removeSelectedInputAsset, openMediaLightbox,
    removeLibraryEntityForTarget, togglePrimaryReferenceForTarget, currentWorkflowIsV2, runNode,
    openAssetLibrarySaveDialog, loadFinalCompositionTimeline, saveFinalCompositionTimeline, renderFinalCompositionTimeline,
    moveFinalCompositionClip, toggleFinalCompositionClip, changeFinalCompositionClipNumber,
    changeFinalCompositionSubtitleText, selectFinalCompositionAudioSource, addFinalCompositionSourceAsImageClip,
    removeFinalCompositionClip, acceptLocalRevisionCandidate, rejectLocalRevisionCandidate, selectLocalAssetHistoryVersion,
    saveDynamicItemPrompt, openDynamicItemLibraryReference, runDynamicMediaItem, applyDynamicItemCurrentVersion,
    batchUseDynamicItemCurrentVersions, generateStoryboardShotVideo, generateMissingStaleStoryboardVideos,
    regenerateAllSelectedStoryboardVideos, applyCurrentStoryboardVideosForComposition,
    startLocalAssetRevision, openDynamicItemHistory, openLocalAssetHistory, submitAssetRevision,
    loadLocalAssetHistory, submitAssetLibrarySave, setAssetLibrarySaveTarget, setAssetLibraryDisplayName, setAssetLibraryTags,
    updateSelectedConfig, getWorkflowNodeType,
    ensureSelectedResolvedInputs, reviewSelectedNodeQuality, ensureNodeVersions, refreshNodeVersions,
    uploadV2PromptInputAsset, createAgentConversation, sendCopilotMessage, applyConversationAction,
    rejectConversationAction, selectConversationActionTarget, runFrontDeskChatOnly, planWorkflowFromPanelChat,
    generateWorkflowFromPanelChat, planStructuredWorkflow, generateStructuredWorkflow, exportEditedVideo,
    refreshVideoExport, addWorkflowVariable, updateWorkflowVariable, deleteWorkflowVariable,
    validateBackendGraph, runFromSelected, pickerTarget, setPickerTarget, selectedLibraryEntitiesForTarget, toggleLibraryEntityForTarget,
  });

  return workflowPageSurface;
}

function recordFromUnknown(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function canShowLocalRevisionActions(node?: WorkflowNode | null) {
  if (!node) return false;
  const nodeType = getWorkflowNodeType(node).toLowerCase();
  if (nodeType === "final-composition") return false;
  return ["character-generation", "scene-generation", "storyboard", "storyboard-video-generation", "bgm"].includes(nodeType);
}
