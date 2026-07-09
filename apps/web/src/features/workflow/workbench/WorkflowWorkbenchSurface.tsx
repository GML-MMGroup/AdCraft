import { NodeWorkbenchPanel } from "../../../components/NodeWorkbenchPanel";
import { WorkflowDraggablePanel } from "../../../components/WorkflowDraggablePanel";
import type { RefObject } from "react";
import type { DraggablePanelKey, PanelOffset } from "../../../components/WorkflowDraggablePanel";
import { FinalCompositionTimelinePanel } from "../final-composition/FinalCompositionTimelinePanel.tsx";
import type {
  AssetBinding,
  AssetFlowDebug,
  AssetLibraryEntitySummary,
  AssetLibraryReference,
  AssetLibraryUploadKind,
  DynamicMediaItem,
  FinalCompositionTimeline,
  GraphValidationResult,
  IdentityCertificationMetadata,
  NodeRunResult,
  PromptOptimizerMetadata,
  ProviderReferencePlan,
  ProviderStrategyDebug,
  QualityReviewSummary,
  ReferencePolicy,
  ResolvedNodeInputs,
  UploadedAsset,
  WorkflowGraph,
  WorkflowNode,
  WorkflowNodeVersion,
  WorkflowRevisionState,
} from "../../../types.ts";
import type {
  AssetVersionV2,
  SlotVersionsResponseV2,
  V2ReferenceAttachRequest,
  WorkflowItemV2,
  WorkflowRuntimeV2,
  WorkflowSlotV2,
} from "../../../types-v2.ts";
import type { NodeDebugLoadState } from "../../../workflow/useWorkflowNodeDebugState.ts";
import type { NodePanelModel } from "../../../workflow/nodePanelModel.ts";
import type { AssetLibrarySaveTarget } from "../assets/useAssetLibrarySaveDialog.ts";
import type { LocalRevisionCardState, RevisionCandidateBusyState } from "../assets/useWorkflowAssetOperations.ts";
import type { FinalCompositionTimelineViewState } from "../final-composition/useFinalCompositionPageController.ts";
import type { V2LibraryReferenceOption } from "../types.ts";
import type { useWorkflowWorkbenchModel } from "./useWorkflowWorkbenchModel.ts";
import { WorkflowWorkbenchV2Section } from "./WorkflowWorkbenchV2Section.tsx";
import { WorkflowWorkbenchPromptSection } from "./WorkflowWorkbenchPromptSection.tsx";
import { WorkflowWorkbenchAssetsSection } from "./WorkflowWorkbenchAssetsSection.tsx";
import { WorkflowWorkbenchDebugSection } from "./WorkflowWorkbenchDebugSection.tsx";

type StateSetter<T> = (value: T | ((current: T) => T)) => void;
type MaybePromise<T = unknown> = T | Promise<T>;
type AssetLibraryPickerTarget = "prompt" | "node" | "revision" | "dynamic-item" | "v2-slot-replace";
type V2SlotReferenceAsset = {
  asset_id: string;
  version_id?: string | null;
  display_name?: string;
  media_type?: string;
  public_url?: string | null;
  preview_url?: string | null;
};

export type WorkflowWorkbenchSurfaceModel = ReturnType<typeof useWorkflowWorkbenchModel> & {
  detailsOpen: boolean;
  selectedPlanNode?: WorkflowNode | null;
  panelOffsets: Record<DraggablePanelKey, PanelOffset>;
  workflow?: WorkflowGraph | null;
  selectedPanelModel: NodePanelModel | null;
  selectedNodeUsesV2InlineRegionEditing: boolean;
  selectedV2Items: WorkflowItemV2[];
  selectedV2SlotsByItemId: Map<string, WorkflowSlotV2[]>;
  dynamicItemPromptDrafts: Record<string, string>;
  dynamicItemPromptSavingById: Record<string, boolean | undefined>;
  selectedAssets: UploadedAsset[];
  selectedV2AssetVersions: Map<string, AssetVersionV2>;
  workflowV2Runtime?: WorkflowRuntimeV2;
  v2SlotVersionsById: Record<string, SlotVersionsResponseV2 | undefined>;
  selectedV2ReferenceAssets: V2SlotReferenceAsset[];
  v2LibraryReferenceOptions: V2LibraryReferenceOption[];
  v2ProviderTaskRefreshKeyBySlotId: Record<string, number | undefined>;
  selectedFreeGenerationMediaType?: string | null;
  selectedFreeAbsorbTargetNodes: WorkflowNode[];
  nodePromptMentionReferences: AssetLibraryReference[];
  workflowRunning: boolean;
  uploadingAsset: boolean;
  nodeAssetInputRef: RefObject<HTMLInputElement | null>;
  nodeUploadKind: AssetLibraryUploadKind;
  nodeUploadName: string;
  nodeUploadTags: string;
  assetLibraryUploadKindOptions: Array<{ value: AssetLibraryUploadKind; label: string }>;
  nodeRunLibraryEntities: AssetLibraryEntitySummary[];
  nodeRunPrimaryReferenceIds: string[];
  currentNodeRunning: boolean;
  selectedNodeId: string;
  finalCompositionTimelineState: FinalCompositionTimelineViewState;
  finalCompositionTimelineDraft: FinalCompositionTimeline | null;
  finalCompositionRevisionState?: LocalRevisionCardState;
  revisionCandidateBusyById: RevisionCandidateBusyState;
  qualityOverrideRevisionId: string | null;
  finalCompositionTargetAsset: UploadedAsset | null;
  dynamicItemRunningById: Record<string, boolean | undefined>;
  dynamicItemLibraryEntitiesById: Record<string, AssetLibraryEntitySummary[]>;
  dynamicItemPrimaryReferenceIdsById: Record<string, string[]>;
  canReviseSelectedAssets: boolean;
  localRevisionByKey: Record<string, LocalRevisionCardState>;
  revisionTarget: UploadedAsset | null;
  revisionInstruction: string;
  revisionLibraryEntities: AssetLibraryEntitySummary[];
  revisionPrimaryReferenceIds: string[];
  revisionHistoryTarget: UploadedAsset | null;
  assetLibrarySaveTarget: AssetLibrarySaveTarget | null;
  assetLibraryDisplayName: string;
  assetLibraryTags: string;
  assetLibraryFeedback: string;
  assetLibrarySaving: boolean;
  staleReason: string;
  selectedRun?: NodeRunResult | null;
  debugLoadState: NodeDebugLoadState;
  selectedQualitySummary?: QualityReviewSummary | null;
  qualityReviewingNodeIds: Record<string, boolean | undefined>;
  selectedReferencePolicy?: ReferencePolicy | null;
  selectedProviderDebug?: ProviderStrategyDebug | null;
  selectedProviderReferencePlan?: ProviderReferencePlan | null;
  selectedAssetFlowDebug?: AssetFlowDebug | null;
  selectedAssetBindings: AssetBinding[];
  selectedPromptOptimizerDebug?: PromptOptimizerMetadata | null;
  selectedIdentityCertification?: IdentityCertificationMetadata | null;
  selectedSourceMappings: Array<Record<string, unknown>>;
  assetLibrarySourceMappings: Array<Record<string, unknown>>;
  displayInputAssets: UploadedAsset[];
  assetLibraryResolvedAssets: UploadedAsset[];
  derivedLibraryEntityIds: string[];
  hasResolvedDebugData: boolean;
  selectedMaterializedPrompt?: string | null;
  selectedMaterializedAssets: UploadedAsset[];
  selectedResolvedContext?: Record<string, unknown> | null;
  selectedResolvedAssets: UploadedAsset[];
  nodeVersions: WorkflowNodeVersion[];
  selectedMissingInputs: NonNullable<ResolvedNodeInputs["missing_inputs"]>;
  selectedStaleUpstreamNodes: string[];
  selectedLockedUpstreamNodes: string[];
  validationResult: GraphValidationResult | null;
  affectedNodes: string[];
  debugListPreviewLimit: number;
  canSaveNodeToAssetLibrary: boolean;
  formatEditableJson: (value: unknown) => string;
};

export type WorkflowWorkbenchSurfaceActions = {
  commitPanelOffset: (panelKey: DraggablePanelKey, offset: PanelOffset) => void;
  setDetailsOpen: (value: boolean) => void;
  refreshSelectedNodeRun: () => MaybePromise;
  refreshV2WorkflowGraph: (workflowId: string) => MaybePromise;
  syncV2Snapshot: (workflowId: string) => MaybePromise;
  changeDynamicItemPrompt: (itemId: string, value: string) => void;
  saveV2ItemPrompt: (item: WorkflowItemV2, prompt: string) => MaybePromise;
  confirmV2ShotSummary: (item: WorkflowItemV2) => MaybePromise;
  createV2FinalTimelineClip: (sourceAssetId: string) => MaybePromise;
  deleteV2FinalTimelineClip: (clipId: string) => MaybePromise;
  runSelectedV2Slot: (slotId?: string) => MaybePromise;
  loadV2SlotVersions: (slotId: string) => MaybePromise;
  saveV2SlotPrompt: (slotId: string, prompt: string, negativePrompt?: string) => MaybePromise;
  selectV2SlotVersion: (slotId: string, versionId: string) => MaybePromise;
  discardV2WorkingVersion: (slotId: string) => MaybePromise;
  deleteV2SelectedSlotAsset: (slotId: string) => MaybePromise;
  pollV2ProviderTask: (taskId: string) => MaybePromise;
  attachV2Reference: (request: V2ReferenceAttachRequest) => MaybePromise;
  createV2FreeNode: () => MaybePromise;
  generateV2FreeNode: (nodeId: string) => MaybePromise;
  absorbV2FreeNode: (nodeId: string, assetId: string, targetNodeId: string) => MaybePromise;
  deleteV2FreeNode: (nodeId: string) => MaybePromise;
  removeV2Reference: (relationId: string) => MaybePromise;
  updateSelectedPrompt: (prompt: string) => void;
  setNodePromptMentionReferences: (references: AssetLibraryReference[]) => void;
  applySystemSuggestion: () => void;
  regenerateOptimizedPrompt: () => MaybePromise;
  applyOptimizedPrompt: () => void;
  uploadAssetForSelectedNode: (files: FileList | null) => MaybePromise;
  setNodeUploadKind: (kind: AssetLibraryUploadKind) => void;
  setNodeUploadName: (value: string) => void;
  setNodeUploadTags: (value: string) => void;
  setPickerTarget: (target: AssetLibraryPickerTarget | null) => void;
  removeSelectedInputAsset: (assetId: string) => void;
  openMediaLightbox: (asset: UploadedAsset) => void;
  removeLibraryEntityForTarget: (target: AssetLibraryPickerTarget, entityId: string) => void;
  togglePrimaryReferenceForTarget: (target: AssetLibraryPickerTarget, entity: AssetLibraryEntitySummary) => void;
  currentWorkflowIsV2: () => boolean;
  runNode: (options?: { useRunPanelOverride?: boolean }) => MaybePromise;
  openAssetLibrarySaveDialog: () => void;
  loadFinalCompositionTimeline: (workflowId: string) => MaybePromise;
  saveFinalCompositionTimeline: () => MaybePromise;
  renderFinalCompositionTimeline: () => MaybePromise;
  moveFinalCompositionClip: (trackId: string, clipId: string, direction: -1 | 1) => void;
  toggleFinalCompositionClip: (trackId: string, clipId: string, enabled: boolean) => void;
  changeFinalCompositionClipNumber: (trackId: string, clipId: string, field: "start_time" | "duration" | "trim_start" | "trim_end", value: number) => void;
  changeFinalCompositionSubtitleText: (trackId: string, clipId: string, text: string) => void;
  selectFinalCompositionAudioSource: (trackId: string, clipId: string, sourceAssetId: string) => void;
  addFinalCompositionSourceAsImageClip: Parameters<typeof FinalCompositionTimelinePanel>[0]["onAddSourceAsImageClip"];
  removeFinalCompositionClip: (trackId: string, clipId: string) => void;
  acceptLocalRevisionCandidate: (targetAsset: UploadedAsset, revision: WorkflowRevisionState, overrideQualityFailure?: boolean) => MaybePromise;
  rejectLocalRevisionCandidate: (targetAsset: UploadedAsset, revision: WorkflowRevisionState) => MaybePromise;
  selectLocalAssetHistoryVersion: (targetAsset: UploadedAsset, asset: UploadedAsset) => MaybePromise;
  setQualityOverrideRevisionId: StateSetter<string | null>;
  saveDynamicItemPrompt: (item: DynamicMediaItem) => MaybePromise;
  openDynamicItemLibraryReference: (itemId: string) => void;
  removeDynamicItemLibraryEntity: (itemId: string, entityId: string) => void;
  toggleDynamicItemPrimaryReference: (itemId: string, entity: AssetLibraryEntitySummary) => void;
  runDynamicMediaItem: (item: DynamicMediaItem) => MaybePromise;
  applyDynamicItemCurrentVersion: (item: DynamicMediaItem, options?: { forceUse?: boolean }) => MaybePromise;
  batchUseDynamicItemCurrentVersions: (items: DynamicMediaItem[]) => MaybePromise;
  generateStoryboardShotVideo: (item: DynamicMediaItem) => MaybePromise;
  generateMissingStaleStoryboardVideos: () => MaybePromise;
  regenerateAllSelectedStoryboardVideos: () => MaybePromise;
  applyCurrentStoryboardVideosForComposition: (items: DynamicMediaItem[]) => MaybePromise;
  startLocalAssetRevision: (asset: UploadedAsset) => MaybePromise;
  setRevisionTarget: StateSetter<UploadedAsset | null>;
  openDynamicItemHistory: (item: DynamicMediaItem) => void;
  openLocalAssetHistory: (asset: UploadedAsset) => void;
  setRevisionInstruction: StateSetter<string>;
  setRevisionLibraryEntities: StateSetter<AssetLibraryEntitySummary[]>;
  setRevisionPrimaryReferenceIds: StateSetter<string[]>;
  submitAssetRevision: () => MaybePromise;
  setRevisionHistoryTarget: StateSetter<UploadedAsset | null>;
  loadLocalAssetHistory: (workflowId: string, nodeId: string, asset: UploadedAsset) => MaybePromise;
  setAssetLibraryDisplayName: (value: string) => void;
  setAssetLibraryTags: (value: string) => void;
  setAssetLibrarySaveTarget: StateSetter<AssetLibrarySaveTarget | null>;
  saveAssetLibraryTarget: () => MaybePromise;
  updateSelectedConfig: (value: string) => void;
  setStaleReason: (value: string) => void;
  getWorkflowNodeType: (node: WorkflowNode) => string;
  ensureSelectedResolvedInputs: () => MaybePromise;
  reviewSelectedNodeQuality: () => MaybePromise;
  ensureNodeVersions: () => MaybePromise;
  refreshNodeVersions: (nodeId?: string, options?: { force?: boolean }) => MaybePromise;
};

export type WorkflowWorkbenchSurfaceProps = {
  model: WorkflowWorkbenchSurfaceModel;
  actions: WorkflowWorkbenchSurfaceActions;
};

export function WorkflowWorkbenchSurface({ model, actions }: WorkflowWorkbenchSurfaceProps) {
  const {
    detailsOpen,
    selectedPlanNode,
    panelOffsets,
    selectedPanelModel,
  } = model;
  const {
    commitPanelOffset,
    setDetailsOpen,
    refreshSelectedNodeRun,
  } = actions;

  if (!detailsOpen || !selectedPlanNode) return null;

  return (
    <WorkflowDraggablePanel
      as="aside"
      panelKey="detail"
      offset={panelOffsets.detail}
      className="node-detail-panel is-open"
      onOffsetCommit={commitPanelOffset}
      heading={
        <>
          <strong>{selectedPlanNode.title}</strong>
          <span className="panel-drag-grip" aria-hidden="true">::</span>
          <button className="small-action" onClick={() => setDetailsOpen(false)}>
            Hide
          </button>
        </>
      }
    >
      <>
        {selectedPanelModel ? (
          <>
            {selectedPanelModel.sections.requirements ? (
              <section className="node-preview-panel requirements-summary-panel">
                <div className="node-preview-heading">
                  <span>Requirement Summary</span>
                  <button className="small-action" onClick={() => void refreshSelectedNodeRun()}>
                    Refresh
                  </button>
                </div>
                {selectedPanelModel.requirementFields.length ? (
                  <div className="requirement-field-grid">
                    {selectedPanelModel.requirementFields.map((field) => (
                      <div key={field.key} className="requirement-field">
                        <span>{field.label}</span>
                        <strong>{field.value}</strong>
                      </div>
                    ))}
                  </div>
                ) : (
                  <span className="empty-output">No analyzed requirements yet. Run this node or refresh its result.</span>
                )}
              </section>
            ) : null}

            <NodeWorkbenchPanel>
              <WorkflowWorkbenchV2Section model={model} actions={actions} />
              <WorkflowWorkbenchPromptSection model={model} actions={actions} />
              <WorkflowWorkbenchAssetsSection model={model} actions={actions} />
            </NodeWorkbenchPanel>

            <WorkflowWorkbenchDebugSection model={model} actions={actions} />
          </>
        ) : null}
      </>
    </WorkflowDraggablePanel>
  );
}
