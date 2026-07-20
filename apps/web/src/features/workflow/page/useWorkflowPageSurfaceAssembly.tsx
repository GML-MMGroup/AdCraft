import { useCallback, useEffect, useState } from "react";
import { mediaUrl } from "../../../api/client";
import { LocalPromptComposer, type PromptGenerateContext } from "../../../components/PromptComposer.tsx";
import { WorkflowDraggablePanel, type PanelOffset } from "../../../components/WorkflowDraggablePanel.tsx";
import { AssetsIcon, CloseIcon, SaveIcon } from "../../../icons";
import type { WorkflowItemV2, WorkflowSlotV2 } from "../../../types-v2.ts";
import { effectiveSlotPrompt } from "../../../types-v2.ts";
import { AssetLibraryPicker, AssetLibrarySaveModal } from "../assets/AssetLibraryPanels.tsx";
import { canSaveNodeToAssetLibrary } from "../assets/assetLibraryReferenceModel.ts";
import { V2FinalCompositionPanel } from "../final-composition/V2FinalCompositionPanel.tsx";
import { finalCompositionTimelineTargetAsset } from "../final-composition/useFinalCompositionOperations.ts";
import { getTimelineClipCount } from "../final-composition/finalCompositionTimelineModel.ts";
import { MediaLightbox } from "../panels/WorkflowDebugSections.tsx";
import { localRevisionStateKey } from "../../../workflow/localRevision.ts";
import { DEFAULT_LAYOUT_VIEWPORT_PADDING, validateConnection } from "../canvas/workflowCanvasModel.ts";
import { formatCanvasRuntimeConnectionState } from "../canvas/WorkflowCanvasNodeModel.ts";
import { WorkflowBottomToolbar, type WorkflowBottomToolbarActions, type WorkflowBottomToolbarModel } from "./WorkflowBottomToolbar.tsx";
import { WorkflowCanvasSurface, type WorkflowCanvasSurfaceActions, type WorkflowCanvasSurfaceModel } from "./WorkflowCanvasSurface.tsx";
import {
  WorkflowSidePanelsSurface,
  type WorkflowSidePanelsSurfaceActions,
  type WorkflowSidePanelsSurfaceModel,
} from "./WorkflowSidePanelsSurface.tsx";
import { formatSavedAt } from "./workflowPageFormatters.ts";
import type { MediaLightboxState } from "./workflowPageTypes.ts";
import { WorkflowWorkbenchSurface, type WorkflowWorkbenchSurfaceActions, type WorkflowWorkbenchSurfaceModel } from "../workbench/WorkflowWorkbenchSurface.tsx";
import { canShowLocalRevisionActions } from "./workflowPageNodeGuards.ts";
import type { WorkflowNode } from "../../../types";
import type { SlotMicroEditDraft } from "../v2/slots/useSlotMicroEdit.ts";
import { assetLibraryEntityTypeForV2ImageSlot } from "../v2/slots/v2SlotAssetLibraryModel.ts";
import { v2EditableItemPrompt } from "../v2/v2PromptModel.ts";

type AssetLibraryPickerTarget = "prompt" | "node" | "revision" | "dynamic-item" | "v2-slot-replace";

// Adapter value bag used while the page model is being decomposed into stable controllers.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type WorkflowPageSurfaceAssemblyArgs = Record<string, any>;

export function useWorkflowPageSurfaceAssembly(args: WorkflowPageSurfaceAssemblyArgs) {
  const finalCompositionTimelineDraft = args.finalCompositionTimelineState.draft;
  const finalCompositionTargetAsset = args.workflow?.workflow_id ? finalCompositionTimelineTargetAsset(args.workflow.workflow_id) : null;
  const finalCompositionRevisionState =
    args.workflow?.workflow_id && finalCompositionTargetAsset
      ? args.localRevisionByKey[localRevisionStateKey(args.workflow.workflow_id, "final-composition", finalCompositionTargetAsset)]
      : undefined;
  const exportVideoPath = args.exportResult?.public_url || args.exportResult?.local_path || "";
  const hasSelection = args.flowNodes.some((node: { selected?: boolean }) => node.selected) || args.flowEdges.some((edge: { selected?: boolean }) => edge.selected);
  const toolbarExecutionId = args.activeExecutionId ?? args.workflowRun?.execution_id;
  const toolbarExecutionState = args.executionPollingState !== "idle" ? ` · ${args.executionPollingState}` : "";
  const runtimeConnectionState = args.workflowV2Model.isV2 ? args.v2Runtime.connectionState : args.canvasRuntimeConnectionState;
  const canvasRuntimeConnectionLabel = formatCanvasRuntimeConnectionState(runtimeConnectionState);
  const activeV2SlotId = typeof args.activeV2SlotId === "string" ? args.activeV2SlotId : null;
  const activeV2Slot = args.activeV2Slot as WorkflowSlotV2 | null | undefined;
  const activeV2StoryboardItemId = typeof args.activeV2StoryboardItemId === "string" ? args.activeV2StoryboardItemId : null;
  const activeV2StoryboardItem = activeV2StoryboardItemId
    ? ((args.workflowV2Model.workflowV2?.items ?? []).find((item: WorkflowItemV2) => item.item_id === activeV2StoryboardItemId) as WorkflowItemV2 | undefined)
    : undefined;
  const activeV2StoryboardPromptDraft = activeV2StoryboardItemId && activeV2StoryboardItem
    ? (args.dynamicItemPromptDrafts?.[activeV2StoryboardItemId] ?? v2EditableItemPrompt(activeV2StoryboardItem))
    : "";
  const activeV2StoryboardPromptSaving = Boolean(activeV2StoryboardItemId && args.dynamicItemPromptSavingById?.[activeV2StoryboardItemId]);
  const activeV2SlotDraft =
    activeV2SlotId && activeV2Slot
      ? ((args.v2SlotDraftsById?.[activeV2SlotId] as SlotMicroEditDraft | undefined) ?? draftFromV2Slot(activeV2Slot))
      : undefined;
  const showV2FloatingSlotComposer = Boolean(
    args.currentWorkflowIsV2() &&
      activeV2SlotId &&
      (activeV2Slot?.media_type === "image" || activeV2Slot?.media_type === "video") &&
      activeV2SlotDraft &&
      args.submitV2LocalSlotPrompt,
  );
  const [v2SlotComposerOffset, setV2SlotComposerOffset] = useState<PanelOffset>({ x: 0, y: 0 });
  const [v2SlotComposerAnchor, setV2SlotComposerAnchor] = useState<{ slotId: string; left: number; top: number } | null>(null);
  const activeV2SlotComposerAnchor = v2SlotComposerAnchor?.slotId === activeV2SlotId ? v2SlotComposerAnchor : null;
  const showV2StoryboardPromptComposer = Boolean(
    args.currentWorkflowIsV2() &&
      activeV2StoryboardItemId &&
      activeV2StoryboardItem &&
      args.changeDynamicItemPrompt &&
      args.submitV2StoryboardPrompt,
  );
  const activeV2SlotSupportsLibraryResource = Boolean(assetLibraryEntityTypeForV2ImageSlot(activeV2Slot));
  const [v2StoryboardPromptOffset, setV2StoryboardPromptOffset] = useState<PanelOffset>({ x: 0, y: 0 });
  const [v2StoryboardPromptAnchor, setV2StoryboardPromptAnchor] = useState<{ itemId: string; left: number; top: number } | null>(null);
  const activeV2StoryboardPromptAnchor = v2StoryboardPromptAnchor?.itemId === activeV2StoryboardItemId ? v2StoryboardPromptAnchor : null;

  useEffect(() => {
    setV2SlotComposerOffset({ x: 0, y: 0 });
    if (!activeV2SlotId) {
      setV2SlotComposerAnchor(null);
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      const page = document.querySelector<HTMLElement>(".workflow-page");
      const slotTarget = Array.from(document.querySelectorAll<HTMLElement>("[data-slot-action-target]")).find(
        (element) => element.dataset.slotActionTarget === activeV2SlotId,
      );
      const pageRect = page?.getBoundingClientRect();
      const slotRect = slotTarget?.getBoundingClientRect();
      if (!pageRect || !slotRect) {
        setV2SlotComposerAnchor(null);
        return;
      }
      const panelWidth = Math.min(410, Math.max(320, pageRect.width - 48));
      const left = Math.min(Math.max(slotRect.left - pageRect.left, 24), Math.max(24, pageRect.width - panelWidth - 24));
      const top = Math.min(Math.max(slotRect.bottom - pageRect.top + 10, 24), Math.max(24, pageRect.height - 300));
      setV2SlotComposerAnchor({ slotId: activeV2SlotId, left, top });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeV2SlotId]);

  const commitV2SlotComposerOffset = useCallback((_panelKey: string, offset: PanelOffset) => {
    setV2SlotComposerOffset(offset);
  }, []);

  useEffect(() => {
    setV2StoryboardPromptOffset({ x: 0, y: 0 });
    if (!activeV2StoryboardItemId) {
      setV2StoryboardPromptAnchor(null);
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      const page = document.querySelector<HTMLElement>(".workflow-page");
      const summaryTarget = Array.from(document.querySelectorAll<HTMLElement>("[data-storyboard-summary-action-target]")).find(
        (element) => element.dataset.storyboardSummaryActionTarget === activeV2StoryboardItemId,
      );
      const pageRect = page?.getBoundingClientRect();
      const summaryRect = summaryTarget?.getBoundingClientRect();
      if (!pageRect || !summaryRect) {
        setV2StoryboardPromptAnchor(null);
        return;
      }
      const panelWidth = Math.min(430, Math.max(320, pageRect.width - 48));
      const left = Math.min(Math.max(summaryRect.left - pageRect.left, 24), Math.max(24, pageRect.width - panelWidth - 24));
      const top = Math.min(Math.max(summaryRect.bottom - pageRect.top + 10, 24), Math.max(24, pageRect.height - 280));
      setV2StoryboardPromptAnchor({ itemId: activeV2StoryboardItemId, left, top });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeV2StoryboardItemId]);

  const commitV2StoryboardPromptOffset = useCallback((_panelKey: string, offset: PanelOffset) => {
    setV2StoryboardPromptOffset(offset);
  }, []);

  const workflowWorkbenchSurfaceModel = {
    ...args.workflowWorkbenchModel,
    detailsOpen: args.detailsOpen,
    selectedPlanNode: args.selectedPlanNode,
    panelOffsets: args.panelOffsets,
    workflow: args.workflow,
    selectedV2Items: args.selectedV2Items,
    selectedV2SlotsByItemId: args.selectedV2SlotsByItemId,
    dynamicItemPromptDrafts: args.dynamicItemPromptDrafts,
    dynamicItemPromptSavingById: args.dynamicItemPromptSavingById,
    selectedAssets: args.selectedAssets,
    selectedV2AssetVersions: args.selectedV2AssetVersions,
    workflowV2Runtime: args.workflowV2Model.workflowV2?.runtime,
    v2SlotVersionsById: args.v2SlotVersionsById,
    selectedV2ReferenceAssets: args.selectedV2ReferenceAssets,
    v2LibraryReferenceOptions: args.v2LibraryReferenceOptions,
    v2ProviderTaskRefreshKeyBySlotId: args.v2ProviderTaskRefreshKeyBySlotId,
    selectedFreeGenerationMediaType: args.selectedFreeGenerationMediaType,
    selectedFreeAbsorbTargetNodes: args.selectedFreeAbsorbTargetNodes,
    nodePromptMentionReferences: args.nodePromptMentionReferences,
    workflowRunning: args.workflowRunning,
    uploadingAsset: args.uploadingAsset,
    nodeAssetInputRef: args.nodeAssetInputRef,
    nodeUploadKind: args.nodeUploadKind,
    nodeUploadName: args.nodeUploadName,
    nodeUploadTags: args.nodeUploadTags,
    assetLibraryUploadKindOptions: args.assetLibraryUploadKindOptions,
    nodeRunLibraryEntities: args.nodeRunLibraryEntities,
    nodeRunPrimaryReferenceIds: args.nodeRunPrimaryReferenceIds,
    currentNodeRunning: args.currentNodeRunning,
    selectedNodeId: args.selectedNodeId,
    finalCompositionTimelineState: args.finalCompositionTimelineState,
    finalCompositionTimelineDraft,
    finalCompositionRevisionState,
    revisionCandidateBusyById: args.revisionCandidateBusyById,
    qualityOverrideRevisionId: args.qualityOverrideRevisionId,
    finalCompositionTargetAsset,
    dynamicItemRunningById: args.dynamicItemRunningById,
    dynamicItemLibraryEntitiesById: args.dynamicItemLibraryEntitiesById,
    dynamicItemPrimaryReferenceIdsById: args.dynamicItemPrimaryReferenceIdsById,
    canReviseSelectedAssets: canShowLocalRevisionActions(args.selectedPlanNode),
    localRevisionByKey: args.localRevisionByKey,
    revisionTarget: args.revisionTarget,
    revisionInstruction: args.revisionInstruction,
    revisionLibraryEntities: args.revisionLibraryEntities,
    revisionPrimaryReferenceIds: args.revisionPrimaryReferenceIds,
    revisionHistoryTarget: args.revisionHistoryTarget,
    assetLibrarySaveTarget: args.assetLibrarySaveTarget,
    assetLibraryDisplayName: args.assetLibraryDisplayName,
    assetLibraryTags: args.assetLibraryTags,
    assetLibraryFeedback: args.assetLibraryFeedback,
    assetLibrarySaving: args.assetLibrarySaving,
    staleReason: args.staleReason,
    selectedRun: args.selectedRun,
    debugLoadState: args.debugLoadState,
    qualityReviewingNodeIds: args.qualityReviewingNodeIds,
    nodeVersions: args.nodeVersions,
    validationResult: args.validationResult,
    affectedNodes: args.affectedNodes,
    debugListPreviewLimit: args.debugListPreviewLimit,
    canSaveNodeToAssetLibrary: args.selectedPlanNode ? canSaveNodeToAssetLibrary(args.selectedPlanNode) : false,
    formatEditableJson: args.formatEditableJson,
  } as WorkflowWorkbenchSurfaceModel;

  const workflowWorkbenchSurfaceActions = {
    commitPanelOffset: args.commitPanelOffset,
    setDetailsOpen: args.setDetailsOpen,
    refreshSelectedNodeRun: args.refreshSelectedNodeRun,
    refreshV2WorkflowGraph: args.refreshV2WorkflowGraph,
    syncV2Snapshot: (requestWorkflowId: string) => args.v2Runtime.syncSnapshot(requestWorkflowId),
    changeDynamicItemPrompt: args.changeDynamicItemPrompt,
    saveV2ItemPrompt: args.saveV2ItemPrompt,
    confirmV2ShotSummary: args.confirmV2ShotSummary,
    createV2FinalTimelineClip: args.createV2FinalTimelineClip,
    deleteV2FinalTimelineClip: args.deleteV2FinalTimelineClip,
    runSelectedV2Slot: args.runSelectedV2Slot,
    loadV2SlotVersions: args.loadV2SlotVersions,
    saveV2SlotPrompt: args.saveV2SlotPrompt,
    selectV2SlotVersion: args.selectV2SlotVersion,
    discardV2WorkingVersion: args.discardV2WorkingVersion,
    deleteV2SelectedSlotAsset: args.deleteV2SelectedSlotAsset,
    pollV2ProviderTask: args.pollV2ProviderTask,
    attachV2Reference: args.attachV2Reference,
    createV2FreeNode: args.createV2FreeNode,
    generateV2FreeNode: args.generateV2FreeNode,
    absorbV2FreeNode: args.absorbV2FreeNode,
    deleteV2FreeNode: args.deleteV2FreeNode,
    removeV2Reference: args.removeV2Reference,
    updateSelectedPrompt: args.updateSelectedPrompt,
    setNodePromptMentionReferences: args.setNodePromptMentionReferences,
    applySystemSuggestion: args.applySystemSuggestion,
    regenerateOptimizedPrompt: args.regenerateOptimizedPrompt,
    applyOptimizedPrompt: args.applyOptimizedPrompt,
    uploadAssetForSelectedNode: args.uploadAssetForSelectedNode,
    setNodeUploadKind: args.setNodeUploadKind,
    setNodeUploadName: args.setNodeUploadName,
    setNodeUploadTags: args.setNodeUploadTags,
    setPickerTarget: args.setPickerTarget,
    removeSelectedInputAsset: args.removeSelectedInputAsset,
    openMediaLightbox: args.openMediaLightbox,
    removeLibraryEntityForTarget: args.removeLibraryEntityForTarget,
    togglePrimaryReferenceForTarget: args.togglePrimaryReferenceForTarget,
    currentWorkflowIsV2: args.currentWorkflowIsV2,
    runNode: args.runNode,
    openAssetLibrarySaveDialog: args.openAssetLibrarySaveDialog,
    loadFinalCompositionTimeline: args.loadFinalCompositionTimeline,
    saveFinalCompositionTimeline: args.saveFinalCompositionTimeline,
    renderFinalCompositionTimeline: args.renderFinalCompositionTimeline,
    moveFinalCompositionClip: args.moveFinalCompositionClip,
    toggleFinalCompositionClip: args.toggleFinalCompositionClip,
    changeFinalCompositionClipNumber: args.changeFinalCompositionClipNumber,
    changeFinalCompositionSubtitleText: args.changeFinalCompositionSubtitleText,
    selectFinalCompositionAudioSource: args.selectFinalCompositionAudioSource,
    addFinalCompositionSourceAsImageClip: args.addFinalCompositionSourceAsImageClip,
    removeFinalCompositionClip: args.removeFinalCompositionClip,
    acceptLocalRevisionCandidate: args.acceptLocalRevisionCandidate,
    rejectLocalRevisionCandidate: args.rejectLocalRevisionCandidate,
    selectLocalAssetHistoryVersion: args.selectLocalAssetHistoryVersion,
    setQualityOverrideRevisionId: args.setQualityOverrideRevisionId,
    saveDynamicItemPrompt: args.saveDynamicItemPrompt,
    openDynamicItemLibraryReference: args.openDynamicItemLibraryReference,
    removeDynamicItemLibraryEntity: args.removeDynamicItemLibraryEntity,
    toggleDynamicItemPrimaryReference: args.toggleDynamicItemPrimaryReference,
    runDynamicMediaItem: args.runDynamicMediaItem,
    applyDynamicItemCurrentVersion: args.applyDynamicItemCurrentVersion,
    batchUseDynamicItemCurrentVersions: args.batchUseDynamicItemCurrentVersions,
    generateStoryboardShotVideo: args.generateStoryboardShotVideo,
    generateMissingStaleStoryboardVideos: args.generateMissingStaleStoryboardVideos,
    regenerateAllSelectedStoryboardVideos: args.regenerateAllSelectedStoryboardVideos,
    applyCurrentStoryboardVideosForComposition: args.applyCurrentStoryboardVideosForComposition,
    startLocalAssetRevision: args.startLocalAssetRevision,
    setRevisionTarget: args.setRevisionTarget,
    openDynamicItemHistory: args.openDynamicItemHistory,
    openLocalAssetHistory: args.openLocalAssetHistory,
    setRevisionInstruction: args.setRevisionInstruction,
    setRevisionLibraryEntities: args.setRevisionLibraryEntities,
    setRevisionPrimaryReferenceIds: args.setRevisionPrimaryReferenceIds,
    submitAssetRevision: args.submitAssetRevision,
    setRevisionHistoryTarget: args.setRevisionHistoryTarget,
    loadLocalAssetHistory: args.loadLocalAssetHistory,
    setAssetLibraryDisplayName: args.setAssetLibraryDisplayName,
    setAssetLibraryTags: args.setAssetLibraryTags,
    setAssetLibrarySaveTarget: args.setAssetLibrarySaveTarget,
    saveAssetLibraryTarget: args.submitAssetLibrarySave,
    updateSelectedConfig: args.updateSelectedConfig,
    setStaleReason: args.setStaleReason,
    getWorkflowNodeType: args.getWorkflowNodeType,
    ensureSelectedResolvedInputs: args.ensureSelectedResolvedInputs,
    reviewSelectedNodeQuality: args.reviewSelectedNodeQuality,
    ensureNodeVersions: args.ensureNodeVersions,
    refreshNodeVersions: args.refreshNodeVersions,
  } as WorkflowWorkbenchSurfaceActions;

  const workflowCanvasSurfaceModel: WorkflowCanvasSurfaceModel = {
    nodes: args.displayNodes,
    edges: args.displayEdges,
    nodeTypes: args.nodeTypes,
    isRestoringWorkspace: args.isRestoringWorkspace,
    workspaceRestoreError: args.workspaceRestoreError,
  };
  const workflowCanvasSurfaceActions = {
    onInit: args.setReactFlow,
    onNodesChange: args.onNodesChange,
    onEdgesChange: args.onEdgesChange,
    onConnect: args.handleConnect,
    onReconnect: args.handleReconnect,
    onReconnectEnd: args.handleReconnectEnd,
    isValidConnection: (connection) => validateConnection(connection, args.flowNodes, args.flowEdges).ok,
    onNodeClick: (_event, node) => {
      args.setSelectedEdgeId(null);
      args.setSelectedNodeId(node.id);
      if (args.currentWorkflowIsV2()) {
        args.setActiveV2SlotId(null);
        args.setActiveV2StoryboardItemId?.(null);
        args.setDetailsOpen(node.id === "final-composition");
      } else {
        args.setDetailsOpen(true);
      }
    },
    onEdgeClick: (event, edge) => {
      event.stopPropagation();
      args.setSelectedEdgeId(edge.id);
      if (args.currentWorkflowIsV2()) args.setDetailsOpen(false);
      args.setFlowEdges((current: Array<{ id: string }>) => current.map((item) => ({ ...item, selected: item.id === edge.id })));
    },
    onNodeDragStop: (_event, node) => args.persistNodePosition(node),
    onPaneClick: () => {
      args.setSelectedEdgeId(null);
      args.setActiveV2SlotId(null);
      args.setActiveV2StoryboardItemId?.(null);
      args.setDetailsOpen(false);
    },
    onNodesDelete: (deleted) => {
      const ids = new Set(deleted.map((node) => node.id));
      if (args.workflow?.workflow_id) deleted.forEach((node) => void args.deleteNodeFromBackend(node.id));
      args.setCanvasNodes((current: WorkflowNode[]) => current.filter((node) => !ids.has(node.id)));
    },
    onEdgesDelete: (deleted) => {
      const ids = new Set(deleted.map((edge) => edge.id));
      if (args.selectedEdgeId && ids.has(args.selectedEdgeId)) args.setSelectedEdgeId(null);
      if (args.workflow?.workflow_id) deleted.forEach((edge) => void args.deleteEdgeFromBackend(edge.id));
      args.setFlowEdges((current: Array<{ id: string }>) => current.filter((edge) => !ids.has(edge.id)));
    },
  } as WorkflowCanvasSurfaceActions;

  const toolbarStatus = `${args.status}${toolbarExecutionId && !args.status.includes(toolbarExecutionId) ? ` · ${toolbarExecutionId}` : ""}${toolbarExecutionState}${canvasRuntimeConnectionLabel ? ` · ${canvasRuntimeConnectionLabel}` : ""}${args.savedAt ? ` · saved ${formatSavedAt(args.savedAt)}` : ""}`;
  const workflowBottomToolbarModel: WorkflowBottomToolbarModel = {
    workflowRunning: args.workflowRunning,
    saving: args.saving,
    canUndo: Boolean(args.canvasHistory.length),
    canRedo: Boolean(args.canvasFuture.length),
    canDeleteSelection: hasSelection || Boolean(args.selectedPlanNode),
    toolbarStatus,
  };
  const workflowBottomToolbarActions = {
    createNewProject: args.createNewProjectFromCanvas,
    runWorkflow: args.runWorkflow,
    saveCanvas: args.saveCanvas,
    undoCanvas: args.undoCanvas,
    redoCanvas: args.redoCanvas,
    deleteSelection: args.deleteSelection,
    autoLayout: args.autoLayout,
    fitView: () => args.reactFlow?.fitView({ padding: DEFAULT_LAYOUT_VIEWPORT_PADDING }),
  } as WorkflowBottomToolbarActions;

  const workflowSidePanelsModel = {
    collapsed: args.collapsed,
    agentConversations: args.agentConversations,
    activeConversationId: args.activeConversationId,
    copilotPanelEvents: args.copilotPanelEvents,
    workflowId: args.workflow?.workflow_id,
    focusNodeId: args.selectedPlanNode?.id ?? null,
    conversationLoading: args.conversationLoading,
    conversationSending: args.conversationSending,
    conversationError: args.conversationError,
    actionBusyById: args.actionBusyById,
    conversationMentionReferences: args.conversationMentionReferences,
    conversationNodeReferences: args.conversationNodeReferences,
    conversationTargetReferences: args.conversationTargetReferences,
    conversationNodeMentionOptions: args.conversationNodeMentionOptions,
    panelOffsets: args.panelOffsets,
    adPanelOpen: args.adPanelOpen,
    workflowPrompt: args.workflowPrompt,
    workflowPromptMentionReferences: args.workflowPromptMentionReferences,
    promptLibraryEntities: args.promptLibraryEntities,
    promptPrimaryReferenceIds: args.promptPrimaryReferenceIds,
    adRequest: args.adRequest,
    videoPanelOpen: args.videoPanelOpen,
    exportSettings: args.exportSettings,
    exportId: args.exportId,
    exportResult: args.exportResult,
    videoTimeline: args.videoTimeline,
    timelineClipCount: getTimelineClipCount(args.videoTimeline),
    mediaStatusLabel: args.mediaStatus?.status ?? "media unknown",
    exportVideoUrl: exportVideoPath ? mediaUrl(exportVideoPath) : "",
    variablesPanelOpen: args.variablesPanelOpen,
    workflowVariables: args.workflowVariables,
    runPanelOpen: args.runPanelOpen,
    selectedNodeId: args.selectedNodeId,
    visibleCanvasNodes: args.visibleCanvasNodes,
    overridePrompt: args.overridePrompt,
    overrideMentionReferences: args.overrideMentionReferences,
    selectedPlanNodeId: args.selectedPlanNode?.id,
    runSettings: args.runSettings,
    workflowRunning: args.workflowRunning,
    currentNodeRunning: args.currentNodeRunning,
    currentWorkflowIsV2: args.currentWorkflowIsV2(),
    selectedNodeUsesV2InlineRegionEditing: args.selectedNodeUsesV2InlineRegionEditing,
    activeV2SlotId: args.activeV2SlotId,
  } as WorkflowSidePanelsSurfaceModel;
  const workflowSidePanelsActions = {
    uploadV2PromptInputAsset: args.uploadV2PromptInputAsset,
    setConversationMentionReferences: args.setConversationMentionReferences,
    setConversationNodeReferences: args.setConversationNodeReferences,
    setConversationTargetReferences: args.setConversationTargetReferences,
    setCollapsed: args.setCollapsed,
    setActiveConversationId: args.setActiveConversationId,
    createAgentConversation: args.createAgentConversation,
    sendCopilotMessage: args.sendCopilotMessage,
    applyConversationAction: args.applyConversationAction,
    rejectConversationAction: args.rejectConversationAction,
    selectConversationActionTarget: args.selectConversationActionTarget,
    commitPanelOffset: args.commitPanelOffset,
    setAdPanelOpen: args.setAdPanelOpen,
    setWorkflowPrompt: args.setWorkflowPrompt,
    setWorkflowPromptMentionReferences: args.setWorkflowPromptMentionReferences,
    setPickerTarget: args.setPickerTarget,
    removeLibraryEntityForTarget: args.removeLibraryEntityForTarget,
    togglePrimaryReferenceForTarget: args.togglePrimaryReferenceForTarget,
    runFrontDeskChatOnly: args.runFrontDeskChatOnly,
    planWorkflowFromPanelChat: args.planWorkflowFromPanelChat,
    generateWorkflowFromPanelChat: args.generateWorkflowFromPanelChat,
    setAdRequest: args.setAdRequest,
    planStructuredWorkflow: args.planStructuredWorkflow,
    generateStructuredWorkflow: args.generateStructuredWorkflow,
    setVideoPanelOpen: args.setVideoPanelOpen,
    setExportSettings: args.setExportSettings,
    exportEditedVideo: args.exportEditedVideo,
    setExportId: args.setExportId,
    refreshVideoExport: args.refreshVideoExport,
    setVariablesPanelOpen: args.setVariablesPanelOpen,
    addWorkflowVariable: args.addWorkflowVariable,
    updateWorkflowVariable: args.updateWorkflowVariable,
    deleteWorkflowVariable: args.deleteWorkflowVariable,
    setSelectedNodeId: args.setSelectedNodeId,
    setDetailsOpen: args.setDetailsOpen,
    setRunPanelOpen: args.setRunPanelOpen,
    setOverridePrompt: args.setOverridePrompt,
    setOverrideMentionReferences: args.setOverrideMentionReferences,
    setRunSettings: args.setRunSettings,
    validateBackendGraph: args.validateBackendGraph,
    runSelectedV2Slot: args.runSelectedV2Slot,
    runNode: args.runNode,
    runFromSelected: args.runFromSelected,
  } as WorkflowSidePanelsSurfaceActions;

  const canvas = (
    <section className="workflow-page">
      <WorkflowCanvasSurface model={workflowCanvasSurfaceModel} actions={workflowCanvasSurfaceActions} />
      <WorkflowSidePanelsSurface model={workflowSidePanelsModel} actions={workflowSidePanelsActions} />

      {!args.currentWorkflowIsV2() ? <WorkflowWorkbenchSurface model={workflowWorkbenchSurfaceModel} actions={workflowWorkbenchSurfaceActions} /> : null}

      {args.currentWorkflowIsV2() && args.detailsOpen && args.selectedNodeId === "final-composition" && args.workflow?.workflow_id ? (
        <V2FinalCompositionPanel
          workflowId={args.workflow.workflow_id}
          offset={args.panelOffsets.detail}
          onOffsetCommit={args.commitPanelOffset}
          onClose={() => args.setDetailsOpen(false)}
          onWorkflowRefresh={(workflowId) => args.refreshV2WorkflowGraph(workflowId)}
        />
      ) : null}

      {showV2FloatingSlotComposer && activeV2SlotComposerAnchor && activeV2Slot && activeV2SlotId && activeV2SlotDraft ? (
        <WorkflowDraggablePanel
          panelKey="v2-slot-composer"
          offset={v2SlotComposerOffset}
          className="v2-floating-slot-composer nodrag"
          headingClassName="v2-floating-slot-composer-heading"
          style={{ left: activeV2SlotComposerAnchor.left, top: activeV2SlotComposerAnchor.top, bottom: "auto" }}
          heading={
            <>
              <span>{formatV2SlotComposerTitle(activeV2Slot)}</span>
              <button
                type="button"
                className="v2-floating-slot-composer-close"
                aria-label="Close image prompt"
                title="Close image prompt"
                onPointerDown={(event) => event.stopPropagation()}
                onClick={(event) => {
                  event.stopPropagation();
                  args.setActiveV2SlotId(null);
                }}
              >
                <CloseIcon />
              </button>
            </>
          }
          onOffsetCommit={commitV2SlotComposerOffset}
        >
          <div
            className="v2-floating-slot-composer-body"
            data-floating-slot-composer-id={activeV2SlotId}
            data-v2-local-prompt-composer-target={`slot:${activeV2SlotId}`}
          >
            <LocalPromptComposer
              placeholder="Ask the agent team..."
              initialValue={activeV2SlotDraft.prompt}
              disabled={activeV2SlotDraft.isSubmitting}
              assetMentionContext={{ workflowId: args.workflow?.workflow_id, nodeId: activeV2Slot.node_id }}
              referenceScope="item_revision"
              referenceTargetContext={{
                referenceScope: "item_revision",
                nodeId: activeV2Slot.node_id,
                itemId: activeV2Slot.item_id,
                semanticType: activeV2Slot.slot_type,
              }}
              onUploadInputAsset={args.uploadV2PromptInputAsset}
              onDraftChange={(prompt, context) => {
                args.changeV2SlotPrompt(activeV2SlotId, prompt);
                args.syncV2SlotPromptReferences?.(activeV2SlotId, context);
              }}
              onGenerate={(prompt: string, context?: PromptGenerateContext) => void args.submitV2LocalSlotPrompt(activeV2SlotId, prompt, context)}
              secondaryActions={
                activeV2SlotSupportsLibraryResource ? (
                  <>
                    <button
                      className="pill-btn icon-only"
                      type="button"
                      aria-label="Replace from asset library"
                      title="Replace from asset library"
                      disabled={activeV2SlotDraft.isSubmitting}
                      onClick={() => args.openV2SlotAssetLibraryReplace?.(activeV2SlotId)}
                    >
                      <AssetsIcon />
                    </button>
                    <button
                      className="pill-btn icon-only"
                      type="button"
                      aria-label="Save as resource"
                      title="Save as resource"
                      disabled={activeV2SlotDraft.isSubmitting}
                      onClick={() => args.openV2SlotAssetLibrarySave?.(activeV2SlotId)}
                    >
                      <SaveIcon />
                    </button>
                  </>
                ) : null
              }
            />
          </div>
        </WorkflowDraggablePanel>
      ) : null}
      {showV2StoryboardPromptComposer && activeV2StoryboardPromptAnchor && activeV2StoryboardItem && activeV2StoryboardItemId ? (
        <WorkflowDraggablePanel
          panelKey="v2-storyboard-prompt-composer"
          offset={v2StoryboardPromptOffset}
          className="v2-floating-slot-composer v2-floating-storyboard-composer nodrag"
          headingClassName="v2-floating-slot-composer-heading"
          style={{ left: activeV2StoryboardPromptAnchor.left, top: activeV2StoryboardPromptAnchor.top, bottom: "auto" }}
          heading={
            <>
              <span>{activeV2StoryboardItem.display_name || activeV2StoryboardItem.item_id}</span>
              <button
                type="button"
                className="v2-floating-slot-composer-close"
                aria-label="Close storyboard prompt"
                title="Close storyboard prompt"
                onPointerDown={(event) => event.stopPropagation()}
                onClick={(event) => {
                  event.stopPropagation();
                  args.setActiveV2StoryboardItemId(null);
                }}
              >
                <CloseIcon />
              </button>
            </>
          }
          onOffsetCommit={commitV2StoryboardPromptOffset}
        >
          <div
            className="v2-floating-slot-composer-body"
            data-v2-local-prompt-composer-target={`storyboard:${activeV2StoryboardItemId}`}
          >
            <LocalPromptComposer
              placeholder="Ask the agent team..."
              initialValue={activeV2StoryboardPromptDraft}
              disabled={activeV2StoryboardPromptSaving}
              assetMentionContext={{ workflowId: args.workflow?.workflow_id, nodeId: activeV2StoryboardItem.node_id }}
              referenceScope="item_revision"
              referenceTargetContext={{
                referenceScope: "item_revision",
                nodeId: activeV2StoryboardItem.node_id,
                itemId: activeV2StoryboardItem.item_id,
              }}
              onUploadInputAsset={args.uploadV2PromptInputAsset}
              onGenerate={(prompt: string, context?: PromptGenerateContext) => void args.submitV2StoryboardPrompt(activeV2StoryboardItem, prompt, context)}
            />
          </div>
        </WorkflowDraggablePanel>
      ) : null}
      <WorkflowBottomToolbar model={workflowBottomToolbarModel} actions={workflowBottomToolbarActions} />
      {args.mediaLightbox ? <MediaLightbox item={args.mediaLightbox as MediaLightboxState} onClose={() => args.setMediaLightbox(null)} /> : null}
      {args.currentWorkflowIsV2() && args.assetLibrarySaveTarget ? (
        <div className="asset-library-save-floating nodrag">
          <AssetLibrarySaveModal
            target={args.assetLibrarySaveTarget}
            displayName={args.assetLibraryDisplayName}
            tags={args.assetLibraryTags}
            feedback={args.assetLibraryFeedback}
            saving={args.assetLibrarySaving}
            onChangeDisplayName={args.setAssetLibraryDisplayName}
            onChangeTags={args.setAssetLibraryTags}
            onCancel={() => args.setAssetLibrarySaveTarget(null)}
            onSubmit={() => void args.submitAssetLibrarySave()}
          />
        </div>
      ) : null}
      {args.pickerTarget ? (
        <AssetLibraryPicker
          selectedEntities={args.selectedLibraryEntitiesForTarget(args.pickerTarget)}
          lockedEntityType={args.pickerTarget === "v2-slot-replace" ? assetLibraryEntityTypeForV2ImageSlot(args.activeV2Slot) : null}
          selectionMode={args.pickerTarget === "v2-slot-replace" ? "single" : "multi"}
          onToggle={(entity) => {
            if (args.pickerTarget === "v2-slot-replace") {
              if (args.activeV2SlotId) void args.replaceV2SlotWithLibraryEntity(args.activeV2SlotId, entity);
              args.setPickerTarget(null);
              return;
            }
            args.toggleLibraryEntityForTarget(args.pickerTarget, entity);
          }}
          onClose={() => args.setPickerTarget(null)}
        />
      ) : null}
    </section>
  );

  return {
    model: {
      chrome: {
        collapsed: args.collapsed,
        status: args.status,
        detailsOpen: args.detailsOpen,
        runPanelOpen: args.runPanelOpen,
        variablesPanelOpen: args.variablesPanelOpen,
      },
      canvas,
      copilot: null,
      panels: args.screenplay.panel,
      modals: null,
    },
    actions: {
      toggleCollapsed: () => args.setCollapsed((value: boolean) => !value),
      setDetailsOpen: args.setDetailsOpen,
      setRunPanelOpen: args.setRunPanelOpen,
      setVariablesPanelOpen: args.setVariablesPanelOpen,
    },
  };
}

function draftFromV2Slot(slot: WorkflowSlotV2): SlotMicroEditDraft {
  return {
    prompt: effectiveSlotPrompt(slot),
    negative_prompt: slot.negative_prompt ?? "",
    reference_asset_ids: [...(slot.explicit_reference_ids ?? [])],
    uploaded_asset_ids: [],
    library_entity_ids: [],
    attachments: (slot.explicit_reference_ids ?? []).map((assetId) => ({
      id: `reference:${assetId}`,
      source: "reference_asset",
      source_asset_id: assetId,
      status: "attached",
    })),
    dirty: false,
    promptDirty: false,
    referenceDirty: false,
    base_prompt: effectiveSlotPrompt(slot),
    base_negative_prompt: slot.negative_prompt ?? "",
    isSubmitting: false,
  };
}

function formatV2SlotComposerTitle(slot: WorkflowSlotV2) {
  return slot.slot_type.replace(/_/g, " ");
}
