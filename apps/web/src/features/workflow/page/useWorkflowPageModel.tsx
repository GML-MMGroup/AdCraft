import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "@xyflow/react/dist/style.css";
import { api } from "../../../api/client";
import { v2Api } from "../../../api/v2Client.ts";
import { useApp } from "../../../AppContextValue";
import { useConversationEventRouter } from "../copilot/useConversationEventRouter.ts";
import { useWorkflowConversationPageActions } from "../copilot/useWorkflowConversationPageActions.ts";
import { useWorkflowConversationController } from "../copilot/useWorkflowConversationController.ts";
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
import { assetLibraryOutputAssetsForNode } from "../../../workflow/assetLibrarySave.ts";
import { dynamicMediaItemsForNode } from "../../../workflow/dynamicMediaItems.ts";
import {
  createNodeRunMap,
  optimizedPromptForNode,
  systemSuggestedPromptForNode,
} from "../../../workflow/runtimeResults.ts";
import { shouldApplyWorkflowScopedResult } from "../../../workflow/sessionGuards.ts";
import { useWorkflowNodeDebugState } from "../../../workflow/useWorkflowNodeDebugState.ts";
import type { CanvasNode } from "../types.ts";
import { getWorkflowNodeType } from "../canvas/workflowNodeModel.ts";
import { useWorkflowCanvasController } from "../canvas/useWorkflowCanvasController.ts";
import { useWorkflowCanvasHistory } from "../canvas/useWorkflowCanvasHistory.ts";
import { useWorkflowDisplayNodeCallbacks } from "../canvas/useWorkflowDisplayNodeCallbacks.ts";
import { useWorkflowDisplayNodes } from "../canvas/useWorkflowDisplayNodes.ts";
import { formatCanvasRuntimeConnectionState } from "../canvas/WorkflowCanvasNodeModel.ts";
import { useCanvasRuntimeEventController, type ScopedWorkflowRefreshPlan } from "../runtime/useCanvasRuntimeEventController.ts";
import { useWorkflowRunController } from "../runtime/useWorkflowRunController.ts";
import { useV2RuntimeController } from "../runtime/useV2RuntimeController.ts";
import { useWorkflowGraphMutationController } from "../graph/useWorkflowGraphMutationController.ts";
import { useWorkflowGraphSyncController } from "../graph/useWorkflowGraphSyncController.ts";
import { useFinalCompositionPageController } from "../final-composition/useFinalCompositionPageController.ts";
import { useFinalCompositionOperations } from "../final-composition/useFinalCompositionOperations.ts";
import { useV2WorkflowAssets } from "../v2/assets/useV2WorkflowAssets.ts";
import { isV2InlineRegionNode, v2RegionItemsForNode } from "../v2/v2RegionNode.ts";
import { isV2WorkflowId, useWorkflowV2Model } from "../../../workflow-v2/pageAdapter.ts";
import { selectedAssetForSlot } from "../../../workflow-v2/selectors.ts";
import {
  defaultAdRequest,
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
  const initialCanvasNodes = workflow?.nodes ?? [];
  const workflowCanvas = useWorkflowCanvasController({
    workflow,
    initialNodes: initialCanvasNodes,
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
    canvasEvents: {
      activeWorkflowIdRef,
      selectedNodeIdRef,
      currentWorkflowIsV2,
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
      onApplyMediaStatusToCanvas: applyMediaStatusToCanvas,
      onApplyNodeRunsToCanvas: applyNodeRunsToCanvas,
      onClearNodeDebugCache: clearNodeDebugCache,
      onRefreshSelectedResolvedInputs: refreshSelectedResolvedInputs,
      onRefreshMediaStatus: refreshMediaStatus,
      onRefreshV2AssetsAndRetryMissing: refreshV2AssetsAndRetryMissing,
      onNoteAffected: noteAffected,
      onTimelineLoadStarted: timelineLoadStarted,
      onTimelineLoadFailed: timelineLoadFailed,
      onApplyFinalCompositionTimelineResponse: applyFinalCompositionTimelineResponse,
      onMarkTimelineEventDirty: markTimelineEventDirty,
      onTimelineRenderStarted: timelineRenderStarted,
      onTimelineRenderFailed: timelineRenderFailed,
      onTimelineRenderFinished: timelineRenderFinished,
      onAppendConversationEventForConversation: appendConversationEventForConversation,
      onHandleAgentConversationEvents: handleAgentConversationEvents,
      onHandleNodePromptUpdatedEvent: handleNodePromptUpdatedEvent,
      onHandleItemPromptUpdatedEvent: handleItemPromptUpdatedEvent,
      onHandleRevisionConversationEvent: handleRevisionConversationEvent,
    },
    document: {
      nodeRunByType,
      setWorkflow,
      syncWorkflowAdRequest,
      setCanvasNodes,
      setWorkflowVariables,
      setFlowNodes,
      setFlowEdges,
      setSelectedNodeId,
      setSavedAt,
      refreshWorkflowGraph,
    },
    activeConversationId,
    revisionHistoryTarget,
    v2SlotVersionsById,
    v2SlotMicroEdit,
    refs: {
      v2Runtime: v2RuntimeRef,
      v2SlotOperations: v2SlotOperationsRef,
      localRevisionOperations: localRevisionOperationsRef,
      screenplayActions: screenplay.actionsRef,
    },
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
  const selectedOutputAssets = useMemo(
    () => (
      selectedPlanNode
        ? assetLibraryOutputAssetsForNode(selectedPlanNode, selectedRun, mediaStatus)
        : []
    ),
    [mediaStatus, selectedPlanNode, selectedRun],
  );
  const selectedDynamicMediaItems = useMemo(
    () => (
      selectedPlanNode
        ? dynamicMediaItemsForNode(selectedPlanNode, {
            run: selectedRun ?? undefined,
            resolvedInputs: selectedResolvedInputs ?? undefined,
            outputAssets: selectedOutputAssets,
          })
        : []
    ),
    [selectedOutputAssets, selectedPlanNode, selectedResolvedInputs, selectedRun],
  );
  const selectedNodeUsesV2InlineRegionEditing = Boolean(
    currentWorkflowIsV2()
      && selectedPlanNode
      && isV2InlineRegionNode(selectedPlanNode),
  );
  const selectedSystemSuggestion = selectedPlanNode
    ? systemSuggestedPromptForNode(selectedPlanNode)
    : "";
  const selectedOptimizedPrompt = selectedPlanNode
    ? optimizedPromptForNode(selectedPlanNode)
    : "";
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
    timeline: {
      workflowId: workflow?.workflow_id,
      exportSettings,
      mediaStatus,
      nodeRuns,
      canvasNodes,
    },
    derived: {
      workflowV2: workflowV2Model.workflowV2,
      selectedPlanNode,
      selectedAssets,
      promptLibraryEntities,
      v2SlotVersionsById,
      workflowAssetVersions: workflowV2Model.workflowV2?.asset_versions ?? [],
      hydratedAssetVersions: v2WorkflowAssets.assetVersions,
      slotDraftsBySlotId: v2SlotMicroEdit.state.draftsBySlotId,
      visibleCanvasNodes,
    },
    slotMicroEdit: v2SlotMicroEdit,
    slotRebaseWorkflow: workflowV2Model.workflowV2 ?? workflowV2Model.workflow,
    slotOperations: {
      workflowId: workflow?.workflow_id,
      workflowV2: workflowV2Model.workflowV2,
      currentWorkflowIsV2,
      activeWorkflowIdRef,
      selectedPlanNode,
      selectedAssets,
      dynamicItemPromptDrafts,
      v2SlotVersionsById,
      setStatus,
      setSelectedNodeId,
      setDynamicItemPromptSavingById,
      setDynamicItemPromptDrafts,
      setV2SlotVersionsById,
      applyWorkflowV2,
      captureV2WorkflowApplicationRevision,
      isCurrentV2WorkflowApplicationRevision,
      refreshV2WorkflowGraph,
      refreshV2AssetsAndRetryMissing,
      selectedNodeIdRef,
    },
    localRevisions: {
      workflow,
      selectedPlanNode,
      revisionTarget,
      revisionInstruction,
      revisionLibraryEntities,
      revisionPrimaryReferenceIds,
      activeWorkflowIdRef,
      currentWorkflowIsV2,
      setStatus,
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
    },
    finalComposition: {
      workflow,
      canvasNodes,
      nodeRuns,
      mediaStatus,
      flowNodes,
      selectedPlanNode,
      selectedRun,
      visibleCanvasNodes,
      finalCompositionTimelineState,
      finalCompositionTimelineBaselineVersion,
      exportId,
      exportSettings,
      activeWorkflowIdRef,
      currentWorkflowIsV2,
      setStatus,
      setMediaStatus,
      setCanvasNodes,
      setFlowNodes,
      setSelectedNodeRun,
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
      refreshV2WorkflowGraph,
      saveCanvas,
      refreshWorkflowNodes,
      refreshWorkflowGraph,
      refreshSelectedResolvedInputs,
      patchWorkflowNodeState,
      applyNodeRunsToCanvas,
    },
    dynamicMedia: {
      workflow,
      selectedPlanNode,
      selectedNodeId,
      dynamicItemPromptDrafts,
      dynamicItemLibraryEntitiesById,
      detailsOpen,
      activeWorkflowIdRef,
      currentWorkflowIsV2,
      setStatus,
      setDynamicItemPromptSavingById,
      setDynamicItemPromptDrafts,
      setDynamicItemRunningById,
      setRevisionHistoryTarget,
      refreshWorkflowNodes,
      refreshWorkflowGraph,
      refreshMediaStatus,
      refreshSelectedResolvedInputs,
      saveCanvas,
      dynamicItemScopedAssetReferences,
      noteAffected,
    },
    syncV2Snapshot: async (requestWorkflowId) => {
      await v2Runtime.syncSnapshot(requestWorkflowId);
    },
    refs: {
      v2SlotOperations: v2SlotOperationsRef,
      localRevisionOperations: localRevisionOperationsRef,
      finalCompositionOperations: finalCompositionOperationsRef,
    },
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
    const v2SaveShape = entityType === "character"
      ? { entityType: "character" as const, category: "characters" as const }
      : entityType === "scene"
        ? { entityType: "scene" as const, category: "scenes" as const }
        : entityType === "product"
          ? { entityType: "product" as const, category: "props" as const }
          : null;
    if (!v2SaveShape) {
      setStatus("Only character, scene, and product slots can be saved to My Assets.");
      return;
    }
    const asset = selectedAssetForSlot(slot, selectedV2AssetVersions);
    if (!asset?.asset_id || !asset.version_id) {
      setStatus("Current V2 image slot needs an asset and version id before saving.");
      return;
    }
    const displayName = v2ImageSlotLibrarySaveDisplayName(slot, asset);
    const siblingSlots = (workflowV2Model.workflowV2?.slots ?? [slot])
      .filter((candidate) => candidate.item_id === slot.item_id && candidate.media_type === "image");
    const members = siblingSlots.flatMap((candidate, index) => {
      const candidateAsset = selectedAssetForSlot(candidate, selectedV2AssetVersions);
      if (!candidateAsset?.asset_id || !candidateAsset.version_id) return [];
      return [{
        asset_id: candidateAsset.asset_id,
        version_id: candidateAsset.version_id,
        semantic_type: candidateAsset.semantic_type || candidate.slot_type,
        is_primary: candidate.slot_id === slot.slot_id || index === 0,
        is_default_reference: true,
        sort_order: index,
      }];
    });
    setAssetLibrarySaveTarget({
      node: {
        id: slot.node_id,
        workflow_id: workflow?.workflow_id,
        node_type: slot.node_id,
        category: "image_generation",
        title: displayName,
      },
      entityType: v2SaveShape.entityType,
      libraryCategory: v2SaveShape.category,
      sourceEntityId: slot.item_id,
      members,
      displayName,
    });
    setAssetLibraryDisplayName(displayName);
    setAssetLibraryTags("");
    setAssetLibrarySaveFeedback("");
  }, [
    selectedV2AssetVersions,
    workflowV2Model.workflowV2?.slots,
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
    planning: {
      messages,
      workflowPrompt,
      adRequest,
      promptLibraryEntities,
      selectedAssets,
      workflowPromptAssetReferences,
      beginWorkflowMutationScope,
      shouldApplyWorkflowMutationScope,
      setMessages,
      setStatus,
      syncFrontDeskAdRequest,
      applyWorkflowV2,
    },
    run: {
      workflow,
      canvasNodes,
      visibleCanvasNodes,
      flowNodes,
      flowEdges,
      selectedAssets,
      selectedPlanNode,
      selectedRunType,
      selectedResolvedInputs,
      nodeRuns,
      workflowVariables,
      runSettings,
      adRequest,
      workflowPrompt,
      messages,
      promptLibraryEntities,
      promptPrimaryReferenceIds,
      nodeRunLibraryEntities,
      overridePrompt,
      currentNodeRunning,
      activeWorkflowIdRef,
      currentNodeRunningRef,
      currentNodeRunRequestRef,
      setActiveExecutionId,
      setExecutionNodeStatusById,
      setRunningNodeIds,
      setExecutionPollingState,
      setWorkflowRunning,
      setWorkflowRun,
      setMediaStatus,
      setStatus,
      setCanvasNodes,
      setFlowNodes,
      setMessages,
      setAdRequest,
      setCurrentNodeRunning,
      setSelectedNodeRun,
      setSelectedResolvedInputs,
      setWorkflow,
      currentWorkflowIsV2,
      assertNotV2WorkflowForV1Api,
      beginWorkflowMutationScope,
      shouldApplyWorkflowMutationScope,
      workflowPromptAssetReferences,
      syncFrontDeskAdRequest,
      applyWorkflowV2,
      flushV2SlotDrafts: () =>
        v2SlotOperationsRef.current?.actions.flushV2SlotDrafts() ?? Promise.resolve(),
      refreshV2AssetsAndRetryMissing,
      saveCanvas,
      validateBackendGraph,
      prepareFinalCompositionRun,
      refreshWorkflowNodes,
      refreshWorkflowGraph,
      refreshMediaStatus,
      refreshSelectedResolvedInputs,
      patchWorkflowNodeState,
      shouldApplyCurrentNodeRun,
      nodeScopedAssetReferences,
      runSelectedV2Slot,
      pollStoryboardVideoMedia,
      applyNodeRunsToCanvas,
      applyMediaStatusToCanvas,
    },
    conversation: {
      workflow,
      selectedPlanNode,
      activeWorkflowIdRef,
      conversation: workflowConversation,
      messages,
      currentWorkflowIsV2,
      getWorkflowNodeType,
      defaultV2SlotForCurrentNode,
      selectedV2Items,
      setStatus,
      applyWorkflowV2,
      applyV2RuntimeEventsToPage,
      handleAgentConversationEvents,
      queueScopedWorkflowRefresh,
    },
    snapshot: {
      workflowId,
      canvasNodes,
      flowNodes,
      flowEdges,
      workflowVariables,
      reactFlow,
      activeProjectId,
      isRestoringWorkspace,
      workflow,
      messages,
      nodeRuns,
      selectedAssets,
      promptLibraryEntities,
      saveProject,
      setSavedAt,
      setStatus,
    },
    graph: {
      workflow,
      workflowId,
      canvasNodes,
      flowNodes,
      flowEdges,
      nodeRuns,
      nodeRunByType,
      workflowVariables,
      selectedAssets,
      promptLibraryEntities,
      messages,
      selectedPlanNode,
      selectedNodeId,
      selectedEdgeId,
      selectedSystemSuggestion,
      selectedOptimizedPrompt,
      selectedRunType,
      selectedResolvedInputs,
      nodeUploadKind,
      nodeUploadName,
      nodeUploadTags,
      staleReason,
      reactFlow,
      pendingNodePatches,
      activeWorkflowIdRef,
      currentNodeRunningRef,
      currentNodeRunRequestRef,
      setWorkflow,
      setCanvasNodes,
      setFlowNodes,
      setFlowEdges,
      setWorkflowVariables,
      setSelectedNodeId,
      setSelectedEdgeId,
      setSelectedNodeRun,
      setSelectedResolvedInputs,
      setMediaStatus,
      setWorkflowRun,
      setWorkflowRunning,
      setCurrentNodeRunning,
      setValidationResult,
      setNodeVersions,
      setAffectedNodes,
      setSavedAt,
      setSaving,
      setStatus,
      setDetailsOpen,
      setMediaLightbox,
      setUploadingAsset,
      setVariablesPanelOpen,
      currentWorkflowIsV2,
      assertNotV2WorkflowForV1Api,
      refreshV2WorkflowGraph,
      refreshWorkflowGraph,
      refreshNodeVersions,
      refreshSelectedResolvedInputs,
      nodeScopedAssetReferences,
      applyNodeRunsToCanvas,
      patchWorkflowNodeState,
      markNodesStale,
      noteAffected,
      saveProject,
      startNewProject,
      captureCanvasHistory,
      clearCanvasHistory,
      resetExportState,
    },
    runtime: {
      v2Runtime,
      workflowV2Controller,
    },
    refs: {
      bridgeFrontDeskMessagesToAgentConversation:
        bridgeFrontDeskMessagesToAgentConversationRef,
      workflowRunActions: workflowRunActionsRef,
      workflowGraphMutations: workflowGraphMutationsRef,
    },
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
    v2AudioMode: workflowV2Model.workflowV2?.audio_mode,
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
    if (currentWorkflowIsV2() || !detailsOpen || !workflow?.workflow_id || selectedNodeId !== "final-composition") return;
    void loadFinalCompositionTimeline(workflow.workflow_id);
  }, [currentWorkflowIsV2, detailsOpen, workflow?.workflow_id, selectedNodeId, loadFinalCompositionTimeline]);

  useWorkflowPageLifecycle({
    workflow,
    workflowId,
    workflowSchemaVersion: workflow?.metadata?.workflow_schema_version,
    workflowV2IsV2: workflowV2Model.isV2,
    isRestoringWorkspace,
    currentWorkflowIsV2,
    nodeRunByType,
    canvasNodes,
    flowNodes,
    flowEdges,
    selectedNodeId,
    reactFlow,
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
    chrome: {
      model: {
        collapsed,
        status,
        detailsOpen,
        runPanelOpen,
        variablesPanelOpen,
      },
      setCollapsed,
      setDetailsOpen,
      setRunPanelOpen,
      setVariablesPanelOpen,
    },
    canvas: {
      model: {
        nodes: displayNodes,
        edges: displayEdges,
        nodeTypes,
        isRestoringWorkspace,
        workspaceRestoreError,
      },
      workflowId: workflow?.workflow_id ?? null,
      flowNodes,
      flowEdges,
      selectedEdgeId,
      currentWorkflowIsV2,
      setSelectedNodeId,
      setSelectedEdgeId,
      setDetailsOpen,
      setActiveV2SlotId,
      setActiveV2StoryboardItemId,
      setCanvasNodes,
      setFlowEdges,
      deleteNodeFromBackend,
      deleteEdgeFromBackend,
      actions: {
        onInit: setReactFlow,
        onNodesChange,
        onEdgesChange,
        onConnect: handleConnect,
        onReconnect: handleReconnect,
        onReconnectEnd: handleReconnectEnd,
        onNodeDragStop: (_event, node) => persistNodePosition(node),
      },
    },
    sidePanels: {
      model: {
        collapsed,
        agentConversations,
        activeConversationId,
        copilotPanelEvents,
        workflowId: workflow?.workflow_id,
        focusNodeId: selectedPlanNode?.id ?? null,
        conversationLoading,
        conversationSending,
        conversationError,
        actionBusyById,
        conversationMentionReferences,
        conversationNodeReferences,
        conversationTargetReferences,
        conversationNodeMentionOptions,
        panelOffsets,
        adPanelOpen,
        workflowPrompt,
        workflowPromptMentionReferences,
        promptLibraryEntities,
        promptPrimaryReferenceIds,
        adRequest,
        videoPanelOpen,
        exportSettings,
        exportId,
        exportResult,
        videoTimeline,
        variablesPanelOpen,
        workflowVariables,
        runPanelOpen,
        selectedNodeId,
        visibleCanvasNodes,
        overridePrompt,
        overrideMentionReferences,
        selectedPlanNodeId: selectedPlanNode?.id,
        runSettings,
        workflowRunning,
        currentNodeRunning,
        selectedNodeUsesV2InlineRegionEditing,
        activeV2SlotId,
      },
      mediaStatus,
      currentWorkflowIsV2,
      actions: {
        uploadV2PromptInputAsset,
        setConversationMentionReferences,
        setConversationNodeReferences,
        setConversationTargetReferences,
        setCollapsed,
        setActiveConversationId,
        createAgentConversation,
        sendCopilotMessage,
        applyConversationAction,
        rejectConversationAction,
        selectConversationActionTarget,
        commitPanelOffset,
        setAdPanelOpen,
        setWorkflowPrompt,
        setWorkflowPromptMentionReferences,
        setPickerTarget,
        removeLibraryEntityForTarget,
        togglePrimaryReferenceForTarget,
        runFrontDeskChatOnly,
        planWorkflowFromPanelChat,
        generateWorkflowFromPanelChat,
        setAdRequest,
        planStructuredWorkflow,
        generateStructuredWorkflow,
        setVideoPanelOpen,
        setExportSettings,
        exportEditedVideo,
        setExportId,
        refreshVideoExport,
        setVariablesPanelOpen,
        addWorkflowVariable,
        updateWorkflowVariable,
        deleteWorkflowVariable,
        setSelectedNodeId,
        setDetailsOpen,
        setRunPanelOpen,
        setOverridePrompt,
        setOverrideMentionReferences,
        setRunSettings,
        validateBackendGraph,
        runSelectedV2Slot,
        runNode,
        runFromSelected,
      },
    },
    toolbar: {
      status,
      activeExecutionId,
      workflowRunExecutionId: workflowRun?.execution_id,
      executionPollingState,
      runtimeConnectionLabel: formatCanvasRuntimeConnectionState(
        workflowV2Model.isV2
          ? v2Runtime.connectionState
          : canvasRuntimeConnectionState,
      ),
      savedAt,
      canvasHistoryCount: canvasHistory.length,
      canvasFutureCount: canvasFuture.length,
      hasCanvasSelection:
        flowNodes.some((node) => node.selected) ||
        flowEdges.some((edge) => edge.selected),
      hasSelectedPlanNode: Boolean(selectedPlanNode),
      workflowRunning,
      saving,
      reactFlow,
      createNewProject: createNewProjectFromCanvas,
      runWorkflow,
      saveCanvas,
      undoCanvas,
      redoCanvas,
      deleteSelection,
      autoLayout,
    },
    floatingEditors: {
      isV2: currentWorkflowIsV2(),
      workflowId: workflow?.workflow_id ?? null,
      workflowItems: workflowV2Model.workflowV2?.items ?? [],
      activeV2SlotId,
      activeV2Slot,
      activeV2StoryboardItemId,
      slotDraftsById: v2SlotMicroEdit.state.draftsBySlotId,
      storyboardPromptDrafts: dynamicItemPromptDrafts,
      storyboardPromptSavingById: dynamicItemPromptSavingById,
      setActiveV2SlotId,
      setActiveV2StoryboardItemId,
      changeV2SlotPrompt,
      syncV2SlotPromptReferences,
      uploadV2PromptInputAsset,
      uploadV2SlotReference,
      removeV2SlotReference,
      submitV2LocalSlotPrompt,
      openV2SlotAssetLibraryReplace,
      openV2SlotAssetLibrarySave,
      submitV2StoryboardPrompt,
    },
    overlays: {
      finalComposition: {
        isV2: currentWorkflowIsV2(),
        detailsOpen,
        selectedNodeId,
        workflowId: workflow?.workflow_id ?? null,
        offset: panelOffsets.detail,
        onOffsetCommit: commitPanelOffset,
        onClose: () => setDetailsOpen(false),
        onWorkflowRefresh: refreshV2WorkflowGraph,
      },
      mediaLightbox,
      closeMediaLightbox: () => setMediaLightbox(null),
      assetLibrarySave: {
        isV2: currentWorkflowIsV2(),
        target: assetLibrarySaveTarget,
        displayName: assetLibraryDisplayName,
        tags: assetLibraryTags,
        feedback: assetLibraryFeedback,
        saving: assetLibrarySaving,
        setDisplayName: setAssetLibraryDisplayName,
        setTags: setAssetLibraryTags,
        close: () => setAssetLibrarySaveTarget(null),
        submit: submitAssetLibrarySave,
      },
      picker: {
        target: pickerTarget,
        activeV2SlotId,
        activeV2Slot,
        selectedEntitiesForTarget: selectedLibraryEntitiesForTarget,
        toggleLibraryEntityForTarget,
        replaceV2SlotWithLibraryEntity,
        close: () => setPickerTarget(null),
      },
    },
    screenplayPanel: screenplay.panel,
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
