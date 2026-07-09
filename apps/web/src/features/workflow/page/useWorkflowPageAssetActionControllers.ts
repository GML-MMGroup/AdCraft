import { useMemo } from "react";
import { buildVideoTimeline } from "../final-composition/finalCompositionTimelineModel.ts";
import { useV2SlotOperations } from "../v2/slots/useV2SlotOperations.ts";
import { useLocalRevisionOperations } from "../assets/useLocalRevisionOperations.ts";
import { useFinalCompositionOperations } from "../final-composition/useFinalCompositionOperations.ts";
import { useDynamicMediaOperations } from "../assets/useDynamicMediaOperations.ts";
import { canShowLocalRevisionActions } from "./workflowPageNodeGuards.ts";
import { getWorkflowNodeType } from "../canvas/workflowNodeModel.ts";
import { useWorkflowV2DerivedState } from "../v2/useWorkflowV2DerivedState.ts";

// Adapter value bag used while the page model is being decomposed into stable controllers.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type WorkflowPageAssetActionControllersArgs = Record<string, any>;

export function useWorkflowPageAssetActionControllers(args: WorkflowPageAssetActionControllersArgs) {
  const videoTimeline = useMemo(
    () => buildVideoTimeline(args.workflow?.workflow_id, args.exportSettings, args.mediaStatus, args.nodeRuns, args.canvasNodes),
    [args.workflow?.workflow_id, args.exportSettings, args.mediaStatus, args.nodeRuns, args.canvasNodes],
  );
  const activeV2SlotId = args.v2SlotMicroEdit.state.openSlotId;
  const v2DerivedState = useWorkflowV2DerivedState({
    workflowV2: args.workflowV2Model.workflowV2,
    selectedPlanNode: args.selectedPlanNode,
    selectedAssets: args.selectedAssets,
    promptLibraryEntities: args.promptLibraryEntities,
    v2SlotVersionsById: args.v2SlotVersionsById,
    workflowAssetVersions: args.workflowV2Model.workflowV2?.asset_versions ?? [],
    hydratedAssetVersions: args.v2WorkflowAssets.assetVersions,
    slotDraftsBySlotId: args.v2SlotMicroEdit.state.draftsBySlotId,
    visibleCanvasNodes: args.visibleCanvasNodes,
  });
  const {
    selectedV2Items,
    selectedV2Slots,
    allV2Slots,
    selectedV2SlotsByItemId,
    slotVersionAssets,
    selectedV2AssetVersions,
    v2ReferenceAssetsBySlotId,
    selectedV2ReferenceAssets,
    v2LibraryReferenceOptions,
    selectedFreeGenerationMediaType,
    selectedFreeAbsorbTargetNodes,
  } = v2DerivedState;

  const v2SlotOperations = useV2SlotOperations({
    workflowId: args.workflow?.workflow_id,
    workflowV2: args.workflowV2Model.workflowV2,
    currentWorkflowIsV2: args.currentWorkflowIsV2,
    activeWorkflowIdRef: args.activeWorkflowIdRef,
    selectedPlanNode: args.selectedPlanNode,
    selectedV2Items,
    selectedV2Slots,
    allV2Slots,
    selectedV2AssetVersions,
    selectedAssets: args.selectedAssets,
    activeV2SlotId,
    selectedFreeGenerationMediaType,
    dynamicItemPromptDrafts: args.dynamicItemPromptDrafts,
    v2SlotVersionsById: args.v2SlotVersionsById,
    v2SlotMicroEdit: args.v2SlotMicroEdit,
    setStatus: args.setStatus,
    setSelectedNodeId: args.setSelectedNodeId,
    setDynamicItemPromptSavingById: args.setDynamicItemPromptSavingById,
    setDynamicItemPromptDrafts: args.setDynamicItemPromptDrafts,
    setV2SlotVersionsById: args.setV2SlotVersionsById,
    applyWorkflowV2: args.applyWorkflowV2,
    refreshV2WorkflowGraph: args.refreshV2WorkflowGraph,
    syncV2Snapshot: (requestWorkflowId: string) => args.v2Runtime.syncSnapshot(requestWorkflowId),
    refreshV2AssetsAndRetryMissing: args.refreshV2AssetsAndRetryMissing,
    selectedNodeIdRef: args.selectedNodeIdRef,
  });
  args.v2SlotOperationsRef.current = v2SlotOperations;

  const localRevisionOperations = useLocalRevisionOperations({
    workflow: args.workflow,
    selectedPlanNode: args.selectedPlanNode,
    revisionTarget: args.revisionTarget,
    revisionInstruction: args.revisionInstruction,
    revisionLibraryEntities: args.revisionLibraryEntities,
    revisionPrimaryReferenceIds: args.revisionPrimaryReferenceIds,
    activeWorkflowIdRef: args.activeWorkflowIdRef,
    currentWorkflowIsV2: args.currentWorkflowIsV2,
    canShowLocalRevisionActions,
    getWorkflowNodeType,
    setStatus: args.setStatus,
    setRevisionInstruction: args.setRevisionInstruction,
    setRevisionTarget: args.setRevisionTarget,
    setRevisionLibraryEntities: args.setRevisionLibraryEntities,
    setRevisionPrimaryReferenceIds: args.setRevisionPrimaryReferenceIds,
    setRevisionHistoryTarget: args.setRevisionHistoryTarget,
    setLocalRevisionByKey: args.setLocalRevisionByKey,
    setRevisionCandidateBusyById: args.setRevisionCandidateBusyById,
    setQualityOverrideRevisionId: args.setQualityOverrideRevisionId,
    setSelectedNodeRun: args.setSelectedNodeRun,
    saveCanvas: args.saveCanvas,
    refreshWorkflowNodes: args.refreshWorkflowNodes,
    refreshWorkflowGraph: args.refreshWorkflowGraph,
    refreshMediaStatus: args.refreshMediaStatus,
    refreshSelectedResolvedInputs: args.refreshSelectedResolvedInputs,
    applyNodeRunsToCanvas: args.applyNodeRunsToCanvas,
    noteAffected: args.noteAffected,
  });
  args.localRevisionOperationsRef.current = localRevisionOperations;

  const finalCompositionOperations = useFinalCompositionOperations({
    workflow: args.workflow,
    canvasNodes: args.canvasNodes,
    nodeRuns: args.nodeRuns,
    mediaStatus: args.mediaStatus,
    flowNodes: args.flowNodes,
    selectedPlanNode: args.selectedPlanNode,
    selectedRun: args.selectedRun,
    visibleCanvasNodes: args.visibleCanvasNodes,
    videoTimeline,
    finalCompositionTimelineState: args.finalCompositionTimelineState,
    finalCompositionTimelineBaselineVersion: args.finalCompositionTimelineBaselineVersion,
    exportId: args.exportId,
    exportSettings: args.exportSettings,
    activeWorkflowIdRef: args.activeWorkflowIdRef,
    currentWorkflowIsV2: args.currentWorkflowIsV2,
    setStatus: args.setStatus,
    setMediaStatus: args.setMediaStatus,
    setCanvasNodes: args.setCanvasNodes,
    setFlowNodes: args.setFlowNodes,
    setSelectedNodeRun: args.setSelectedNodeRun,
    setSelectedResolvedInputs: args.setSelectedResolvedInputs,
    setQualityReviewingNodeIds: args.setQualityReviewingNodeIds,
    setExportResult: args.setExportResult,
    setExportId: args.setExportId,
    timelineLoadStarted: args.timelineLoadStarted,
    timelineLoadFailed: args.timelineLoadFailed,
    applyFinalCompositionTimelineResponse: args.applyFinalCompositionTimelineResponse,
    setFinalCompositionTimelineConflict: args.setFinalCompositionTimelineConflict,
    timelineSaveStarted: args.timelineSaveStarted,
    timelineSaveFailed: args.timelineSaveFailed,
    timelineRenderStarted: args.timelineRenderStarted,
    timelineRenderFailed: args.timelineRenderFailed,
    timelineRenderFinished: args.timelineRenderFinished,
    syncV2Snapshot: (requestWorkflowId: string) => args.v2Runtime.syncSnapshot(requestWorkflowId),
    refreshV2WorkflowGraph: args.refreshV2WorkflowGraph,
    saveCanvas: args.saveCanvas,
    refreshWorkflowNodes: args.refreshWorkflowNodes,
    refreshWorkflowGraph: args.refreshWorkflowGraph,
    refreshSelectedResolvedInputs: args.refreshSelectedResolvedInputs,
    patchWorkflowNodeState: args.patchWorkflowNodeState,
    applyNodeRunsToCanvas: args.applyNodeRunsToCanvas,
    updateLocalRevisionCardState: localRevisionOperations.actions.updateLocalRevisionCardState,
    applyLocalRevisionState: localRevisionOperations.actions.applyLocalRevisionState,
    loadLocalAssetHistory: localRevisionOperations.actions.loadLocalAssetHistory,
  });
  args.finalCompositionOperationsRef.current = finalCompositionOperations;

  const dynamicMediaOperations = useDynamicMediaOperations({
    workflow: args.workflow,
    selectedPlanNode: args.selectedPlanNode,
    selectedNodeId: args.selectedNodeId,
    selectedV2Slots,
    dynamicItemPromptDrafts: args.dynamicItemPromptDrafts,
    dynamicItemLibraryEntitiesById: args.dynamicItemLibraryEntitiesById,
    detailsOpen: args.detailsOpen,
    activeWorkflowIdRef: args.activeWorkflowIdRef,
    currentWorkflowIsV2: args.currentWorkflowIsV2,
    setStatus: args.setStatus,
    setDynamicItemPromptSavingById: args.setDynamicItemPromptSavingById,
    setDynamicItemPromptDrafts: args.setDynamicItemPromptDrafts,
    setDynamicItemRunningById: args.setDynamicItemRunningById,
    setRevisionHistoryTarget: args.setRevisionHistoryTarget,
    refreshWorkflowNodes: args.refreshWorkflowNodes,
    refreshWorkflowGraph: args.refreshWorkflowGraph,
    refreshMediaStatus: args.refreshMediaStatus,
    refreshSelectedResolvedInputs: args.refreshSelectedResolvedInputs,
    saveCanvas: args.saveCanvas,
    dynamicItemScopedAssetReferences: args.dynamicItemScopedAssetReferences,
    noteAffected: args.noteAffected,
    submitV2SlotMicroPrompt: v2SlotOperations.actions.submitV2SlotMicroPrompt,
    selectV2SlotVersion: v2SlotOperations.actions.selectV2SlotVersion,
    loadFinalCompositionTimeline: finalCompositionOperations.actions.loadFinalCompositionTimeline,
    loadLocalAssetHistory: localRevisionOperations.actions.loadLocalAssetHistory,
  });

  return {
    videoTimeline,
    activeV2SlotId,
    ...v2DerivedState,
    v2SlotOperations,
    localRevisionOperations,
    finalCompositionOperations,
    dynamicMediaOperations,
  };
}
