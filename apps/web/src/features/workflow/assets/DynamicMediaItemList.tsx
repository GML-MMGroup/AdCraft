import { dedupeAssets } from "../../../workflow/assets.ts";
import { pendingVisibleRevisionCandidates, revisionCandidateAsset, revisionCandidateState } from "../../../workflow/localRevision.ts";
import { AssetQualityNotice, LocalRevisionCandidateCard, LocalRevisionPromptMetadata, NodeAssetHistoryPreview } from "./AssetRevisionPanels.tsx";
import { LibraryReferenceChips } from "./LibraryReferenceChips.tsx";
import { NodeAttachmentPreview } from "../components/NodeAttachmentPreview.tsx";
import {
  isWorkingVersionQualityFailed,
  validationIssueKey,
  workingVersionBatchText,
  workingVersionDebugKey,
  workingVersionErrorMessage,
  workingVersionResultText,
} from "./dynamicMediaItemListModel.ts";
import type {
  AssetLibraryEntitySummary,
  DynamicMediaItem,
  DynamicMediaItemWorkingVersion,
  QualityReviewIssue,
  UploadedAsset,
  WorkflowRevisionState,
} from "../../../types";
import type { LocalRevisionCardState } from "./useWorkflowAssetOperations.ts";

function localRevisionPendingCandidatesForState(state?: LocalRevisionCardState) {
  return pendingVisibleRevisionCandidates(dedupeRevisionStates([...(state?.revisions ?? []), ...(state?.candidates ?? [])]));
}

function dedupeRevisionStates(revisions: WorkflowRevisionState[]) {
  const seen = new Set<string>();
  return revisions.filter((revision) => {
    const key = revision.revision_id || JSON.stringify([revision.status, revision.updated_at, revision.created_at, revision.target_asset_id, revision.semantic_type]);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function isLocalRevisionRunningStatus(status?: string | null) {
  const normalized = (status ?? "").toLowerCase();
  return normalized === "queued" || normalized === "running" || normalized === "waiting" || normalized === "pending";
}

function isLocalRevisionCompletedStatus(status?: string | null) {
  const normalized = (status ?? "").toLowerCase();
  return normalized === "completed" || normalized === "succeeded" || normalized === "ready";
}

function localRevisionPromptMetadataFromAsset(asset?: UploadedAsset | null) {
  if (!asset) return null;
  const metadata = recordFromUnknown(asset.metadata) ?? {};
  const promptMetadata = recordFromUnknown(metadata.prompt_metadata) ?? metadata;
  const result = {
    prompt: stringFromUnknown(promptMetadata.prompt) || stringFromUnknown(promptMetadata.user_prompt),
    providerPrompt: stringFromUnknown(promptMetadata.provider_prompt),
    optimizedRevisionPrompt: stringFromUnknown(promptMetadata.optimized_revision_prompt),
    providerRevisionPrompt: stringFromUnknown(promptMetadata.provider_revision_prompt),
    revisionRequirements: promptMetadata.revision_requirements,
    revisionId: stringFromUnknown(promptMetadata.revision_id),
    generatedAt: stringFromUnknown(promptMetadata.generated_at),
    specialistResultId: stringFromUnknown(promptMetadata.specialist_result_id),
    qualityStatus: stringFromUnknown(promptMetadata.quality_status),
    reviewer: stringFromUnknown(promptMetadata.reviewer),
  };
  return Object.values(result).some((value) => value !== undefined && value !== null && value !== "") ? result : null;
}

function statusClass(value: string) {
  return value.replace(/[^a-z0-9_-]/gi, "-").toLowerCase();
}

function recordFromUnknown(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function stringArrayFromUnknown(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim())) : [];
}
export function DynamicMediaItemList({
  items,
  promptDrafts,
  promptSavingById,
  runningById,
  libraryEntitiesByItemId,
  primaryReferenceIdsByItemId,
  canReviseAssets,
  revisionStateForAsset,
  busyByRevisionId,
  qualityOverrideRevisionId,
  onChangePrompt,
  onSavePrompt,
  onOpenLibrary,
  onRemoveLibrary,
  onTogglePrimary,
  onRunNode,
  onForceRerunNode,
  onRunItem,
  onUseCurrentVersion,
  onBatchUseCurrentVersions,
  onGenerateShotVideo,
  onGenerateMissingStaleShotVideos,
  onRegenerateAllSelectedShotVideos,
  onUseCurrentShotVideosForComposition,
  onOpenAsset,
  onRegenerateAsset,
  onReviseAsset,
  onViewHistory,
  onAcceptCandidate,
  onRejectCandidate,
  onCancelQualityOverride,
  onUseVersion,
}: {
  items: DynamicMediaItem[];
  promptDrafts: Record<string, string>;
  promptSavingById: Record<string, boolean | undefined>;
  runningById: Record<string, boolean | undefined>;
  libraryEntitiesByItemId: Record<string, AssetLibraryEntitySummary[]>;
  primaryReferenceIdsByItemId: Record<string, string[]>;
  canReviseAssets: boolean;
  revisionStateForAsset: (asset: UploadedAsset) => LocalRevisionCardState | undefined;
  busyByRevisionId: Record<string, "accept" | "reject" | undefined>;
  qualityOverrideRevisionId: string | null;
  onChangePrompt: (itemId: string, value: string) => void;
  onSavePrompt: (item: DynamicMediaItem) => void;
  onOpenLibrary: (itemId: string) => void;
  onRemoveLibrary: (itemId: string, entityId: string) => void;
  onTogglePrimary: (itemId: string, entity: AssetLibraryEntitySummary) => void;
  onRunNode: () => void;
  onForceRerunNode: () => void;
  onRunItem: (item: DynamicMediaItem) => void;
  onUseCurrentVersion: (item: DynamicMediaItem, forceUse?: boolean) => void;
  onBatchUseCurrentVersions: (items: DynamicMediaItem[]) => void;
  onGenerateShotVideo: (item: DynamicMediaItem) => void;
  onGenerateMissingStaleShotVideos: () => void;
  onRegenerateAllSelectedShotVideos: () => void;
  onUseCurrentShotVideosForComposition: (items: DynamicMediaItem[]) => void;
  onOpenAsset: (asset: UploadedAsset) => void;
  onRegenerateAsset: (item: DynamicMediaItem, asset: UploadedAsset) => void;
  onReviseAsset: (item: DynamicMediaItem, asset: UploadedAsset) => void;
  onViewHistory: (item: DynamicMediaItem) => void;
  onAcceptCandidate: (targetAsset: UploadedAsset, revision: WorkflowRevisionState, overrideQualityFailure?: boolean) => void;
  onRejectCandidate: (targetAsset: UploadedAsset, revision: WorkflowRevisionState) => void;
  onCancelQualityOverride: () => void;
  onUseVersion: (targetAsset: UploadedAsset, asset: UploadedAsset) => void;
}) {
  return (
    <div className="dynamic-media-item-list" aria-label="Dynamic media items">
      <div className="dynamic-media-item-toolbar">
        <span>Items</span>
        <button className="small-action" type="button" onClick={() => onBatchUseCurrentVersions(items)}>
          {dynamicItemBatchUseLabel(items)}
        </button>
        {items.some((item) => item.itemType === "storyboard_image") ? (
          <>
            <button className="small-action" type="button" onClick={onGenerateMissingStaleShotVideos}>
              生成全部缺失/过期镜头视频
            </button>
            <button className="small-action" type="button" onClick={onRegenerateAllSelectedShotVideos}>
              全部重新生成一版
            </button>
            <button className="small-action" type="button" onClick={() => onUseCurrentShotVideosForComposition(items)}>
              使用当前全部进入剪辑
            </button>
          </>
        ) : null}
        <button className="small-action" type="button" onClick={onRunNode}>
          Run node
        </button>
        <button className="small-action" type="button" onClick={onForceRerunNode}>
          Force rerun node
        </button>
      </div>
      {items.map((item) => {
        const itemPrompt = promptDrafts[item.itemId] ?? item.prompt;
        const promptSaving = Boolean(promptSavingById[item.itemId]);
        const itemRunning = Boolean(runningById[item.itemId]) || item.status === "running" || item.status === "waiting" || item.status === "queued";
        const libraryEntities = libraryEntitiesByItemId[item.itemId] ?? [];
        const primaryReferenceIds = new Set(primaryReferenceIdsByItemId[item.itemId] ?? []);
        const displayReferenceAssets = dedupeAssets([...item.referenceAssets, ...item.inputAssets]);
        const itemActionAsset = dynamicMediaItemActionAssetForView(item);
        const itemRevisionState = revisionStateForAsset(itemActionAsset);
        const pendingItemCandidates = localRevisionPendingCandidatesForState(itemRevisionState);
        const itemHistoryAssets = dedupeAssets([...(itemRevisionState?.history ?? []), ...(itemRevisionState?.assets ?? [])]);
        const activeItemAssetId = itemRevisionState?.activeAsset?.asset_id ?? item.outputAssets[0]?.asset_id ?? itemActionAsset.asset_id;
        const historicalItemAssets = itemHistoryAssets.filter((historyAsset) => historyAsset.asset_id !== activeItemAssetId);
        const visibleItemHistoryAssets = historicalItemAssets.slice(0, 3);
        const selectedVersion = item.selectedVersion ?? workingVersionFromAssets(item.outputAssets, "selected");
        const currentWorkingVersion = item.currentWorkingVersion ?? workingVersionFromRevisionCandidates(pendingItemCandidates);
        const historyVersions = item.historyVersions?.length ? item.historyVersions : visibleItemHistoryAssets.map((asset) => workingVersionFromAssets([asset], "history")).filter((version): version is NonNullable<typeof version> => Boolean(version));
        const needsApply = item.needsApply ?? workingVersionNeedsApply(currentWorkingVersion, selectedVersion);
        const currentQualityFailed = isWorkingVersionQualityFailed(currentWorkingVersion);
        const lifecycleLabel = item.lifecycleState === "draft" ? "草稿" : item.lifecycleState === "archived" ? "已归档" : item.lifecycleState === "active" ? "已启用" : item.lifecycleState;
        return (
          <section
            key={item.itemId}
            className={`dynamic-media-item-card status-${statusClass(item.status)} ${itemRunning ? "is-running" : ""}`}
            data-item-id={item.itemId}
            data-workbench-item-id={item.itemId}
          >
            <div className="dynamic-media-item-heading">
              <span>
                <strong>{item.displayName}</strong>
                <em>{[item.itemType, item.semanticType, lifecycleLabel].filter(Boolean).join(" · ")}</em>
              </span>
              <b>{item.status}</b>
            </div>
            {needsApply ? <span className="dynamic-media-item-needs-apply">未使用新版本</span> : null}
            {item.error || item.errorCode ? (
              <span className="dynamic-media-item-error">
                {[item.errorCode, item.error].filter(Boolean).join(" · ")}
                {item.outputAssets.length ? " · Current preview keeps the last successful output." : ""}
              </span>
            ) : null}
            <ShotScopedReferenceBindingStatus item={item} />
            <ProductStrictReferenceStatus item={item} />
            <label className="node-config-field dynamic-media-item-prompt">
              <span>Item prompt</span>
              <textarea value={itemPrompt} onChange={(event) => onChangePrompt(item.itemId, event.target.value)} />
            </label>
            <div className="asset-revision-actions">
              <button className="small-action" type="button" disabled={promptSaving || !itemPrompt.trim()} onClick={() => onSavePrompt(item)}>
                {promptSaving ? "Saving..." : "Save prompt"}
              </button>
            </div>
            <div className="library-reference-row">
              <button className="pill-btn library-reference-trigger" type="button" onClick={() => onOpenLibrary(item.itemId)}>
                Item reference
              </button>
              <LibraryReferenceChips
                entities={libraryEntities}
                primaryReferenceIds={primaryReferenceIds}
                onRemove={(entityId) => onRemoveLibrary(item.itemId, entityId)}
                onTogglePrimary={(entity) => onTogglePrimary(item.itemId, entity)}
              />
            </div>
            {displayReferenceAssets.length ? (
              <div className="dynamic-media-item-assets">
                <span>References</span>
                <div className="node-attachment-list asset-preview-list">
                  {displayReferenceAssets.map((asset) => (
                    <NodeAttachmentPreview key={asset.asset_id} asset={asset} onOpen={() => onOpenAsset(asset)} />
                  ))}
                </div>
              </div>
            ) : null}
            <div className="dynamic-media-item-versioning" data-versioning="candidate-active-history">
              <div className="asset-revision-section">
                <div className="asset-revision-section-heading">当前工作版本</div>
                <WorkingVersionPreview
                  version={currentWorkingVersion}
                  emptyLabel="No current working version yet."
                  onOpenAsset={onOpenAsset}
                />
                {currentQualityFailed ? <span className="dynamic-media-item-error">Quality failed. 请再来一版、编辑 Prompt 或选历史版本。</span> : null}
                <div className="asset-revision-actions">
                  <button className="small-action" type="button" disabled={!isWorkingVersionReady(currentWorkingVersion) || currentQualityFailed} onClick={() => onUseCurrentVersion(item, false)}>
                    使用当前版本
                  </button>
                  {currentQualityFailed ? (
                    <button className="small-action" type="button" onClick={() => onUseCurrentVersion(item, true)}>
                      仍要使用
                    </button>
                  ) : null}
                  <button className="small-action" type="button" aria-label="Run item" title="Run item" disabled={itemRunning} onClick={() => onRunItem(item)}>
                    {itemRunning ? "生成中..." : "再来一版"}
                  </button>
                  {item.lifecycleState === "draft" ? (
                    <button className="small-action" type="button" disabled>
                      移除草稿
                    </button>
                  ) : null}
                </div>
                <div className="asset-revision-candidate-list">
                  {pendingItemCandidates.map((revision) => (
                    <LocalRevisionCandidateCard
                      key={revision.revision_id || `${revision.updated_at ?? revision.created_at ?? ""}-${revision.status}`}
                      revision={revision}
                      busy={busyByRevisionId[revision.revision_id]}
                      qualityOverrideRevisionId={qualityOverrideRevisionId}
                      acceptLabel="使用当前版本"
                      forceAcceptLabel="仍要使用"
                      rejectLabel="移除草稿"
                      onAccept={(overrideQualityFailure) => onAcceptCandidate(itemActionAsset, revision, overrideQualityFailure)}
                      onReject={() => onRejectCandidate(itemActionAsset, revision)}
                      onCancelQualityOverride={onCancelQualityOverride}
                    />
                  ))}
                </div>
              </div>
              <div className="asset-revision-section">
                <div className="asset-revision-section-heading">已使用版本</div>
                <div className="node-attachment-list asset-preview-list">
                  {item.outputAssets.map((asset) => {
                    const actionAsset = dynamicMediaItemActionAssetForView(item, asset);
                    const revisionState = revisionStateForAsset(actionAsset);
                    const showRevisionActions = canReviseAssets && !actionAsset.is_archived;
                    return (
                      <NodeAssetHistoryPreview
                        key={actionAsset.asset_id}
                        asset={actionAsset}
                        revisionState={revisionState}
                        onOpen={() => onOpenAsset(actionAsset)}
                        onRegenerate={showRevisionActions ? () => onRegenerateAsset(item, actionAsset) : undefined}
                        onRevise={showRevisionActions ? () => onReviseAsset(item, actionAsset) : undefined}
                        onViewHistory={showRevisionActions ? () => onViewHistory(item) : undefined}
                      />
                    );
                  })}
                  {!item.outputAssets.length ? <em>No active output asset yet.</em> : null}
                </div>
                <WorkingVersionPreview version={selectedVersion} emptyLabel="No selected version yet." onOpenAsset={onOpenAsset} />
                <LocalRevisionPromptMetadata metadata={localRevisionPromptMetadataFromAsset(itemRevisionState?.activeAsset ?? item.outputAssets[0])} />
              </div>
              <div className="asset-revision-section">
                <div className="asset-revision-section-heading">历史版本</div>
                <WorkingVersionList versions={historyVersions} onOpenAsset={onOpenAsset} />
                <div className="dynamic-media-item-history-list">
                  {visibleItemHistoryAssets.map((item) => (
                    <div key={item.asset_id} className="asset-revision-history-item">
                      <NodeAttachmentPreview asset={item} onOpen={() => onOpenAsset(item)} />
                      <span>{item.filename}</span>
                      <span>{[item.version ? `v${item.version}` : "", item.semantic_type ?? "", item.run_id ? `run ${item.run_id}` : ""].filter(Boolean).join(" · ")}</span>
                      <button className="asset-revision-trigger" type="button" disabled={item.asset_id === activeItemAssetId || isLocalRevisionRunningStatus(itemRevisionState?.status)} onClick={() => onUseVersion(itemActionAsset, item)}>
                        使用这个历史版本
                      </button>
                      <LocalRevisionPromptMetadata metadata={localRevisionPromptMetadataFromAsset(item)} />
                    </div>
                  ))}
                  {historicalItemAssets.length > visibleItemHistoryAssets.length ? <span className="asset-revision-history-more">+{historicalItemAssets.length - visibleItemHistoryAssets.length} more history assets</span> : null}
                  {!historicalItemAssets.length ? <em>No older versions yet.</em> : null}
                </div>
              </div>
              {item.itemType === "storyboard_image" ? (
                <div className="asset-revision-section">
                  <div className="asset-revision-section-heading">镜头视频</div>
                  <WorkingVersionPreview version={item.videoCurrentWorkingVersion ?? null} emptyLabel="No shot video working version yet." onOpenAsset={onOpenAsset} />
                  <WorkingVersionPreview version={item.videoSelectedVersion ?? null} emptyLabel="No selected shot video yet." onOpenAsset={onOpenAsset} />
                  <WorkingVersionList versions={item.videoHistoryVersions ?? []} onOpenAsset={onOpenAsset} />
                  <div className="asset-revision-actions">
                    <button className="small-action" type="button" disabled={Boolean(runningById[`${item.itemId}:video`])} onClick={() => onGenerateShotVideo(item)}>
                      {runningById[`${item.itemId}:video`] ? "生成中..." : "生成这个镜头视频"}
                    </button>
                    <button className="small-action" type="button" onClick={() => onGenerateShotVideo(item)}>
                      再来一版视频
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
            <div className="asset-revision-actions">
              <button className="small-action" type="button" onClick={() => onViewHistory(item)}>
                选历史版本
              </button>
            </div>
          </section>
        );
      })}
    </div>
  );
}

function WorkingVersionPreview({
  version,
  emptyLabel,
  onOpenAsset,
}: {
  version?: DynamicMediaItemWorkingVersion | null;
  emptyLabel: string;
  onOpenAsset: (asset: UploadedAsset) => void;
}) {
  if (!version) return <em className="working-version-empty">{emptyLabel}</em>;
  const assets = version.assets ?? [];
  const meta = [
    version.version_id ? `version ${version.version_id}` : "",
    version.revision_id ? `revision ${version.revision_id}` : "",
    version.status ?? "",
    version.quality_status ? `quality ${version.quality_status}` : "",
    version.quality_override ? "quality override" : "",
  ].filter(Boolean);

  return (
    <div className={`working-version-preview quality-${statusClass(String(version.quality_status ?? ""))}`}>
      <div className="working-version-meta">
        {meta.map((item) => (
          <em key={item}>{item}</em>
        ))}
      </div>
      {version.prompt ? <span>{version.prompt}</span> : null}
      {version.provider_prompt ? <small>{version.provider_prompt}</small> : null}
      {version.quality_issues?.length ? (
        <div className="working-version-issues">
          {version.quality_issues.map((issue) => (
            <span key={workingVersionQualityIssueKey(version, issue)}>{formatQualityIssue(issue)}</span>
          ))}
        </div>
      ) : null}
      {assets.length ? (
        <div className="node-attachment-list asset-preview-list">
          {assets.map((asset) => (
            <NodeAttachmentPreview key={asset.asset_id} asset={asset} onOpen={() => onOpenAsset(asset)} />
          ))}
        </div>
      ) : version.asset_ids?.length ? (
        <div className="working-version-meta">
          {version.asset_ids.map((assetId) => (
            <em key={assetId}>{assetId}</em>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function WorkingVersionList({ versions, onOpenAsset }: { versions: DynamicMediaItemWorkingVersion[]; onOpenAsset: (asset: UploadedAsset) => void }) {
  if (!versions.length) return <em className="working-version-empty">No history versions yet.</em>;
  return (
    <div className="working-version-list">
      {versions.slice(0, 3).map((version) => (
        <WorkingVersionPreview
          key={workingVersionListItemKey(version)}
          version={version}
          emptyLabel="No version data."
          onOpenAsset={onOpenAsset}
        />
      ))}
      {versions.length > 3 ? <span className="asset-revision-history-more">+{versions.length - 3} more history versions</span> : null}
    </div>
  );
}

function workingVersionQualityIssueKey(version: DynamicMediaItemWorkingVersion, issue: QualityReviewIssue) {
  return stableKeyPart(
    workingVersionListItemKey(version),
    "quality",
    issue.code,
    issue.asset_id,
    issue.entity_id,
    issue.semantic_type,
    issue.severity,
    issue.message,
  );
}

function workingVersionListItemKey(version: DynamicMediaItemWorkingVersion) {
  return stableKeyPart(
    "working-version",
    version.version_id,
    version.revision_id,
    version.asset_ids?.join("."),
    version.assets?.map((asset) => asset.asset_id).join("."),
    version.created_at,
    version.status,
    version.source,
  );
}

function stableKeyPart(...values: Array<string | number | boolean | null | undefined>) {
  return values
    .filter((value) => value !== null && value !== undefined && value !== "")
    .map((value) => String(value).replace(/[^a-zA-Z0-9_.:-]+/g, "_"))
    .join(":");
}

function workingVersionFromAssets(assets: UploadedAsset[], source: string): DynamicMediaItemWorkingVersion | null {
  if (!assets.length) return null;
  return {
    version_id: String(assets[0].version ?? assets[0].asset_id),
    asset_ids: assets.map((asset) => asset.asset_id),
    assets,
    status: source === "selected" ? "selected" : "ready",
    source,
  };
}

function workingVersionFromRevisionCandidates(revisions: WorkflowRevisionState[]): DynamicMediaItemWorkingVersion | null {
  const revision = revisions.find((item) => revisionCandidateAsset(item));
  const asset = revision ? revisionCandidateAsset(revision) : null;
  if (!revision || !asset) return null;
  return {
    version_id: revision.revision_id,
    revision_id: revision.revision_id,
    asset_ids: [asset.asset_id],
    assets: [asset],
    status: isLocalRevisionCompletedStatus(revision.status) ? "ready" : revision.status,
    quality_status: String(asset.quality_status ?? revisionCandidateState(revision).qualityStatus ?? ""),
    quality_issues: asset.quality_issues,
    created_at: revision.created_at,
    source: "candidate",
  };
}

function workingVersionNeedsApply(current?: DynamicMediaItemWorkingVersion | null, selected?: DynamicMediaItemWorkingVersion | null) {
  const currentId = stringFromUnknown(current?.version_id) || current?.asset_ids?.[0] || current?.assets?.[0]?.asset_id || "";
  const selectedId = stringFromUnknown(selected?.version_id) || selected?.asset_ids?.[0] || selected?.assets?.[0]?.asset_id || "";
  return Boolean(currentId && selectedId && currentId !== selectedId);
}

function isWorkingVersionReady(version?: DynamicMediaItemWorkingVersion | null) {
  const status = String(version?.status ?? "").toLowerCase();
  return Boolean(version && (status === "ready" || status === "selected" || status === "completed"));
}

function formatQualityIssue(issue: QualityReviewIssue | Record<string, unknown>) {
  return [
    stringFromUnknown(issue.code),
    stringFromUnknown(issue.message),
    stringFromUnknown(issue.severity),
  ].filter(Boolean).join(" · ") || JSON.stringify(issue);
}

function dynamicItemBatchUseLabel(items: DynamicMediaItem[]) {
  if (items.every((item) => item.itemType === "storyboard_video")) return "使用当前镜头视频全部进入剪辑";
  if (items.every((item) => item.itemType === "storyboard_image")) return "使用当前分镜图全部";
  if (items.every((item) => item.itemType === "character")) return "使用当前角色全部";
  if (items.every((item) => item.itemType === "scene")) return "使用当前场景全部";
  if (items.every((item) => item.itemType === "product_image")) return "使用当前产品图全部";
  return "使用当前全部";
}

const PRODUCT_REFERENCE_ERROR_MESSAGES: Record<string, string> = {
  product_reference_required: "A product reference image is required before this item can generate.",
  product_reference_missing: "A product reference image is missing for this item.",
  product_reference_provider_unsupported: "The selected provider cannot satisfy strict product reference generation.",
  product_reference_dropped: "The backend reported that the product reference was dropped.",
};

function ShotScopedReferenceBindingStatus({ item }: { item: DynamicMediaItem }) {
  const metadata = item.metadata ?? {};
  const referenceBindings = item.referenceBindings ?? recordFromUnknown(metadata.reference_bindings);
  const referencedByShotIds = stringArrayFromUnknown(metadata.referenced_by_shot_ids).concat(stringArrayFromUnknown(metadata.referenced_by_shots));
  const invalidReferenceIds = stringArrayFromUnknown(metadata.invalid_reference_ids).concat(stringArrayFromUnknown(metadata.invalid_reference_id));
  const failedRule = stringFromUnknown(metadata.failed_rule) || stringFromUnknown(metadata.rule);
  const errorCode =
    shotScopedReferenceErrorCode(item.errorCode) ||
    shotScopedReferenceErrorCode(stringFromUnknown(metadata.error_code)) ||
    shotScopedReferenceErrorCode(stringFromUnknown(metadata.code));
  const rows = [
    { label: "Shot type", values: item.shotType ? [item.shotType] : [] },
    { label: "Segment id", values: item.segmentId ? [item.segmentId] : [] },
    { label: "Primary scene", values: item.primarySceneId ? [item.primarySceneId] : [] },
    { label: "Scene references", values: item.sceneReferenceIds ?? [] },
    { label: "Character references", values: item.characterIds ?? [] },
    { label: "Product references", values: item.productReferenceIds ?? [] },
    { label: "Style references", values: item.styleReferenceIds ?? [] },
    { label: "Input asset ids", values: item.inputAssetIds ?? [] },
    { label: "No scene reason", values: item.noSceneReason ? [item.noSceneReason] : [] },
    { label: "Referenced shots", values: referencedByShotIds },
    { label: "Invalid reference ids", values: invalidReferenceIds },
    { label: "Failed rule", values: failedRule ? [failedRule] : [] },
  ].filter((row) => row.values.length);
  const shouldShow =
    item.itemType === "storyboard_image" ||
    item.itemType === "storyboard_video" ||
    item.itemType === "scene" ||
    rows.length > 0 ||
    Boolean(referenceBindings) ||
    Boolean(errorCode) ||
    Boolean(item.legacyFallback);

  if (!shouldShow) return null;

  return (
    <div className={`shot-scoped-reference-binding ${errorCode || item.missingSceneBinding ? "has-error" : ""}`}>
      <strong>Read-only binding</strong>
      {errorCode ? <span>{shotScopedReferenceErrorMessage(errorCode)}</span> : null}
      {item.missingSceneBinding ? <span>Missing scene binding</span> : null}
      <div className="shot-scoped-reference-grid">
        {rows.map((row) => (
          <div key={row.label} className="shot-scoped-reference-row">
            <span>{row.label}</span>
            <div>
              {row.values.map((value) => (
                <em key={`${row.label}-${value}`}>{value}</em>
              ))}
            </div>
          </div>
        ))}
      </div>
      {referenceBindings ? (
        <div className="shot-scoped-reference-row">
          <span>reference_bindings</span>
          <code>{JSON.stringify(referenceBindings)}</code>
        </div>
      ) : null}
      {item.legacyFallback ? <small>Legacy fallback</small> : null}
    </div>
  );
}

function shotScopedReferenceErrorCode(value?: string | null) {
  if (value === "shot_reference_binding_invalid" || value === "entity_mapping_unavailable") return value;
  return "";
}

function shotScopedReferenceErrorMessage(errorCode: string) {
  if (errorCode === "shot_reference_binding_invalid") return "shot_reference_binding_invalid";
  if (errorCode === "entity_mapping_unavailable") return "entity_mapping_unavailable";
  return errorCode;
}

function ProductStrictReferenceStatus({ item }: { item: DynamicMediaItem }) {
  const metadata = item.metadata ?? {};
  const referenceMode = item.referenceMode || stringFromUnknown(metadata.reference_mode);
  const errorCode =
    productReferenceErrorCode(item.errorCode) ||
    productReferenceErrorCode(stringFromUnknown(metadata.product_reference_error)) ||
    productReferenceErrorCode(stringFromUnknown(metadata.error_code)) ||
    productReferenceErrorCode(stringFromUnknown(metadata.code));
  const referenceRequired = item.referenceRequired ?? productBooleanFromUnknown(metadata.product_reference_required) ?? false;
  const identityLocked = item.identityLocked ?? productBooleanFromUnknown(metadata.product_identity_locked) ?? false;
  const semanticType = (item.semanticType ?? "").toLowerCase();
  const shouldShow =
    item.itemType === "product_image" ||
    semanticType.includes("product") ||
    referenceMode === "strict" ||
    referenceRequired ||
    identityLocked ||
    Boolean(errorCode);

  if (!shouldShow) return null;

  const message = errorCode
    ? PRODUCT_REFERENCE_ERROR_MESSAGES[errorCode]
    : identityLocked
      ? "Backend product consistency is active for this item."
      : referenceRequired
        ? "Backend requires a product reference for this item."
        : referenceMode === "strict"
          ? "Backend is using strict product reference mode for this item."
          : "Using backend product reference policy for this item.";

  return (
    <div className={`product-strict-reference-status ${errorCode ? "has-error" : ""}`}>
      <strong>Strict product reference</strong>
      <span>{message}</span>
      <div className="product-strict-reference-meta">
        {referenceMode ? <em>reference_mode: {referenceMode}</em> : null}
        {referenceRequired ? <em>product_reference_required</em> : null}
        {identityLocked ? <em>product_identity_locked</em> : null}
        {errorCode ? <b>{errorCode}</b> : null}
      </div>
      {errorCode && item.outputAssets.length ? <small>Current active preview remains available.</small> : null}
    </div>
  );
}

function productReferenceErrorCode(value?: string | null) {
  if (!value) return "";
  return PRODUCT_REFERENCE_ERROR_MESSAGES[value] ? value : "";
}

function productBooleanFromUnknown(value: unknown) {
  if (typeof value === "boolean") return value;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (normalized === "true") return true;
    if (normalized === "false") return false;
  }
  return undefined;
}

function dynamicMediaItemActionAssetForView(item: DynamicMediaItem, asset?: UploadedAsset): UploadedAsset {
  const base = asset ?? item.outputAssets[0];
  const semanticType = item.semanticType ?? base?.semantic_type ?? "unknown";
  return {
    ...(base ?? {}),
    asset_id: base?.asset_id ?? item.itemId,
    asset_type: base?.asset_type ?? (item.itemType === "storyboard_video" ? "video" : "image"),
    asset_role: base?.asset_role ?? (item.itemType === "product_image" ? "product" : "reference"),
    filename: base?.filename ?? item.displayName,
    mime_type: base?.mime_type ?? "application/octet-stream",
    local_path: base?.local_path ?? "",
    entity_id: item.itemId,
    semantic_type: semanticType,
  };
}
