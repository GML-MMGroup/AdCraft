import { DynamicMediaItemPanel } from "../../../components/DynamicMediaItemPanel";
import { FinalCompositionPanel } from "../../../components/FinalCompositionPanel";
import { NodeOutputAssetsPanel } from "../../../components/NodeOutputAssetsPanel";
import { DynamicMediaItemList } from "../assets/DynamicMediaItemList.tsx";
import { AssetLibrarySaveModal, AssetRevisionPanel } from "../assets/AssetLibraryPanels.tsx";
import { AssetRevisionHistoryPanel, NodeAssetHistoryPreview } from "../assets/AssetRevisionPanels.tsx";
import { dynamicItemActionAsset } from "../assets/dynamicItemAssetModel.ts";
import { localRevisionStateKey } from "../../../workflow/localRevision.ts";
import { FinalCompositionTimelinePanel } from "../final-composition/FinalCompositionTimelinePanel.tsx";
import { finalCompositionRenderDisabledReason } from "../final-composition/useFinalCompositionPageController.ts";
import type { WorkflowWorkbenchSurfaceActions, WorkflowWorkbenchSurfaceModel } from "./WorkflowWorkbenchSurface.tsx";

export function WorkflowWorkbenchAssetsSection({
  model,
  actions,
}: {
  model: WorkflowWorkbenchSurfaceModel;
  actions: WorkflowWorkbenchSurfaceActions;
}) {
  const {
    selectedPlanNode,
    workflow,
    selectedOutputAssets,
    selectedActiveOutputWarning,
    selectedStrictReferenceFailure,
    selectedNodeId,
    finalCompositionTimelineState,
    finalCompositionTimelineDraft,
    finalCompositionRevisionState,
    revisionCandidateBusyById,
    qualityOverrideRevisionId,
    finalCompositionTargetAsset,
    selectedDynamicMediaItems,
    dynamicItemPromptDrafts,
    dynamicItemPromptSavingById,
    dynamicItemRunningById,
    dynamicItemLibraryEntitiesById,
    dynamicItemPrimaryReferenceIdsById,
    canReviseSelectedAssets,
    localRevisionByKey,
    revisionTarget,
    revisionInstruction,
    revisionLibraryEntities,
    revisionPrimaryReferenceIds,
    revisionHistoryTarget,
    assetLibrarySaveTarget,
    assetLibraryDisplayName,
    assetLibraryTags,
    assetLibraryFeedback,
    assetLibrarySaving,
    canSaveNodeToAssetLibrary,
  } = model;
  const {
    currentWorkflowIsV2,
    openAssetLibrarySaveDialog,
    loadFinalCompositionTimeline,
    saveFinalCompositionTimeline,
    renderFinalCompositionTimeline,
    moveFinalCompositionClip,
    toggleFinalCompositionClip,
    changeFinalCompositionClipNumber,
    changeFinalCompositionSubtitleText,
    selectFinalCompositionAudioSource,
    addFinalCompositionSourceAsImageClip,
    removeFinalCompositionClip,
    openMediaLightbox,
    acceptLocalRevisionCandidate,
    rejectLocalRevisionCandidate,
    selectLocalAssetHistoryVersion,
    setQualityOverrideRevisionId,
    saveDynamicItemPrompt,
    openDynamicItemLibraryReference,
    removeDynamicItemLibraryEntity,
    toggleDynamicItemPrimaryReference,
    runNode,
    runDynamicMediaItem,
    applyDynamicItemCurrentVersion,
    batchUseDynamicItemCurrentVersions,
    generateStoryboardShotVideo,
    generateMissingStaleStoryboardVideos,
    regenerateAllSelectedStoryboardVideos,
    applyCurrentStoryboardVideosForComposition,
    startLocalAssetRevision,
    setRevisionTarget,
    openDynamicItemHistory,
    openLocalAssetHistory,
    setRevisionInstruction,
    setRevisionLibraryEntities,
    setRevisionPrimaryReferenceIds,
    setPickerTarget,
    removeLibraryEntityForTarget,
    togglePrimaryReferenceForTarget,
    submitAssetRevision,
    setRevisionHistoryTarget,
    loadLocalAssetHistory,
    setAssetLibraryDisplayName,
    setAssetLibraryTags,
    setAssetLibrarySaveTarget,
    saveAssetLibraryTarget,
  } = actions;

  if (!selectedPlanNode) return null;

  return (
    <NodeOutputAssetsPanel>
      <div className="asset-preview-heading-row">
        <span className="asset-preview-heading">Output assets</span>
        {canSaveNodeToAssetLibrary ? (
          <button className="small-action asset-library-save-trigger" type="button" disabled={!workflow?.workflow_id || !selectedOutputAssets.length} onClick={openAssetLibrarySaveDialog}>
            Save to Asset Library
          </button>
        ) : null}
      </div>
      {selectedActiveOutputWarning ? <span className="active-output-warning">Latest run failed, current preview keeps the last successful output.</span> : null}
      {selectedStrictReferenceFailure ? (
        <div className="reference-policy-recovery">
          <strong>Strict reference constraints failed.</strong>
          <span>Change provider, reduce reference count, choose one primary reference, or remove the conflicting reference.</span>
        </div>
      ) : null}
      {!currentWorkflowIsV2() && workflow?.workflow_id && selectedNodeId === "final-composition" ? (
        <FinalCompositionPanel>
          <FinalCompositionTimelinePanel
            state={finalCompositionTimelineState}
            timeline={finalCompositionTimelineDraft}
            activeAsset={finalCompositionRevisionState?.activeAsset ?? selectedOutputAssets[0] ?? null}
            revisionState={finalCompositionRevisionState}
            busyByRevisionId={revisionCandidateBusyById}
            qualityOverrideRevisionId={qualityOverrideRevisionId}
            renderDisabledReason={finalCompositionRenderDisabledReason(finalCompositionTimelineDraft, finalCompositionTimelineState)}
            onRefresh={() => void loadFinalCompositionTimeline(workflow.workflow_id)}
            onSave={() => void saveFinalCompositionTimeline()}
            onRender={() => void renderFinalCompositionTimeline()}
            onMoveClip={moveFinalCompositionClip}
            onToggleClip={toggleFinalCompositionClip}
            onChangeClipNumber={changeFinalCompositionClipNumber}
            onChangeSubtitleText={changeFinalCompositionSubtitleText}
            onSelectAudioSource={selectFinalCompositionAudioSource}
            onAddSourceAsImageClip={addFinalCompositionSourceAsImageClip}
            onRemoveClip={removeFinalCompositionClip}
            onOpenAsset={openMediaLightbox}
            onAcceptCandidate={(revision, overrideQualityFailure) => {
              if (finalCompositionTargetAsset) void acceptLocalRevisionCandidate(finalCompositionTargetAsset, revision, overrideQualityFailure);
            }}
            onRejectCandidate={(revision) => {
              if (finalCompositionTargetAsset) void rejectLocalRevisionCandidate(finalCompositionTargetAsset, revision);
            }}
            onUseVersion={(asset) => {
              if (finalCompositionTargetAsset) void selectLocalAssetHistoryVersion(finalCompositionTargetAsset, asset);
            }}
            onCancelQualityOverride={() => setQualityOverrideRevisionId(null)}
          />
        </FinalCompositionPanel>
      ) : null}
      {selectedDynamicMediaItems.length ? (
        <DynamicMediaItemPanel>
          <DynamicMediaItemList
            items={selectedDynamicMediaItems}
            promptDrafts={dynamicItemPromptDrafts}
            promptSavingById={dynamicItemPromptSavingById}
            runningById={dynamicItemRunningById}
            libraryEntitiesByItemId={dynamicItemLibraryEntitiesById}
            primaryReferenceIdsByItemId={dynamicItemPrimaryReferenceIdsById}
            canReviseAssets={canReviseSelectedAssets}
            revisionStateForAsset={(asset) => {
              const revisionKey = workflow?.workflow_id && selectedPlanNode ? localRevisionStateKey(workflow.workflow_id, selectedPlanNode.id, asset) : "";
              return revisionKey ? localRevisionByKey[revisionKey] : undefined;
            }}
            busyByRevisionId={revisionCandidateBusyById}
            qualityOverrideRevisionId={qualityOverrideRevisionId}
            onChangePrompt={actions.changeDynamicItemPrompt}
            onSavePrompt={(item) => void saveDynamicItemPrompt(item)}
            onOpenLibrary={openDynamicItemLibraryReference}
            onRemoveLibrary={removeDynamicItemLibraryEntity}
            onTogglePrimary={toggleDynamicItemPrimaryReference}
            onRunNode={() => void runNode()}
            onForceRerunNode={() => {
              if (window.confirm("Force rerun every active item in this node? Old assets will remain in history.")) void runNode();
            }}
            onRunItem={(item) => void runDynamicMediaItem(item)}
            onUseCurrentVersion={(item, forceUse) => void applyDynamicItemCurrentVersion(item, { forceUse })}
            onBatchUseCurrentVersions={(items) => void batchUseDynamicItemCurrentVersions(items)}
            onGenerateShotVideo={(item) => void generateStoryboardShotVideo(item)}
            onGenerateMissingStaleShotVideos={() => void generateMissingStaleStoryboardVideos()}
            onRegenerateAllSelectedShotVideos={() => void regenerateAllSelectedStoryboardVideos()}
            onUseCurrentShotVideosForComposition={(items) => void applyCurrentStoryboardVideosForComposition(items)}
            onOpenAsset={openMediaLightbox}
            onRegenerateAsset={(item, asset) => void startLocalAssetRevision(dynamicItemActionAsset(item, asset))}
            onReviseAsset={(item, asset) => setRevisionTarget(dynamicItemActionAsset(item, asset))}
            onViewHistory={openDynamicItemHistory}
            onAcceptCandidate={(targetAsset, revision, overrideQualityFailure) => void acceptLocalRevisionCandidate(targetAsset, revision, overrideQualityFailure)}
            onRejectCandidate={(targetAsset, revision) => void rejectLocalRevisionCandidate(targetAsset, revision)}
            onCancelQualityOverride={() => setQualityOverrideRevisionId(null)}
            onUseVersion={(targetAsset, asset) => void selectLocalAssetHistoryVersion(targetAsset, asset)}
          />
        </DynamicMediaItemPanel>
      ) : null}
      <div className="node-attachment-list asset-preview-list" aria-label="Output assets">
        {selectedOutputAssets.map((asset) => {
          const revisionKey = workflow?.workflow_id && selectedPlanNode ? localRevisionStateKey(workflow.workflow_id, selectedPlanNode.id, asset) : "";
          const revisionState = revisionKey ? localRevisionByKey[revisionKey] : undefined;
          const showRevisionActions = canReviseSelectedAssets && !asset.is_archived;
          return (
            <NodeAssetHistoryPreview
              key={asset.asset_id}
              asset={asset}
              revisionState={revisionState}
              onOpen={() => openMediaLightbox(asset)}
              onRegenerate={showRevisionActions ? () => void startLocalAssetRevision(asset) : undefined}
              onRevise={showRevisionActions ? () => setRevisionTarget(asset) : undefined}
              onViewHistory={showRevisionActions ? () => openLocalAssetHistory(asset) : undefined}
            />
          );
        })}
        {!selectedOutputAssets.length ? <em>No output assets yet.</em> : null}
      </div>
      <AssetRevisionPanel
        asset={revisionTarget}
        revisionInstruction={revisionInstruction}
        libraryEntities={revisionLibraryEntities}
        primaryReferenceIds={new Set(revisionPrimaryReferenceIds)}
        onChangeInstruction={setRevisionInstruction}
        onOpenLibrary={() => setPickerTarget("revision")}
        onRemoveLibrary={(entityId) => removeLibraryEntityForTarget("revision", entityId)}
        onTogglePrimary={(entity) => togglePrimaryReferenceForTarget("revision", entity)}
        onCancel={() => {
          setRevisionTarget(null);
          setRevisionInstruction("");
          setRevisionLibraryEntities([]);
          setRevisionPrimaryReferenceIds([]);
        }}
        onSubmit={() => void submitAssetRevision()}
      />
      <AssetRevisionHistoryPanel
        asset={revisionHistoryTarget}
        state={
          revisionHistoryTarget && workflow?.workflow_id && selectedPlanNode
            ? localRevisionByKey[localRevisionStateKey(workflow.workflow_id, selectedPlanNode.id, revisionHistoryTarget)]
            : undefined
        }
        onClose={() => setRevisionHistoryTarget(null)}
        onRefresh={() => {
          if (revisionHistoryTarget && workflow?.workflow_id && selectedPlanNode) {
            void loadLocalAssetHistory(workflow.workflow_id, selectedPlanNode.id, revisionHistoryTarget);
          }
        }}
        onUseVersion={(asset) => {
          if (revisionHistoryTarget) void selectLocalAssetHistoryVersion(revisionHistoryTarget, asset);
        }}
        busyByRevisionId={revisionCandidateBusyById}
        qualityOverrideRevisionId={qualityOverrideRevisionId}
        onAcceptCandidate={(revision, overrideQualityFailure) => {
          if (revisionHistoryTarget) void acceptLocalRevisionCandidate(revisionHistoryTarget, revision, overrideQualityFailure);
        }}
        onRejectCandidate={(revision) => {
          if (revisionHistoryTarget) void rejectLocalRevisionCandidate(revisionHistoryTarget, revision);
        }}
        onCancelQualityOverride={() => setQualityOverrideRevisionId(null)}
      />
      <AssetLibrarySaveModal
        target={assetLibrarySaveTarget}
        displayName={assetLibraryDisplayName}
        tags={assetLibraryTags}
        feedback={assetLibraryFeedback}
        saving={assetLibrarySaving}
        onChangeDisplayName={setAssetLibraryDisplayName}
        onChangeTags={setAssetLibraryTags}
        onCancel={() => setAssetLibrarySaveTarget(null)}
        onSubmit={() => void saveAssetLibraryTarget()}
      />
    </NodeOutputAssetsPanel>
  );
}
