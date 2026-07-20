import { NodeAttachmentPreview } from "../components/NodeAttachmentPreview.tsx";
import { assetFileMissing, assetLifecycleState, assetLineageDetails } from "../../../workflow/assetLifecycle.ts";
import { dedupeAssets } from "../../../workflow/assets.ts";
import {
  isPendingVisibleRevisionCandidate,
  pendingVisibleRevisionCandidates,
  revisionCandidateAsset,
  revisionCandidateLibraryLabel,
  revisionCandidateState,
  revisionCandidateWorkflowUsageLabel,
} from "../../../workflow/localRevision.ts";
import type { QualityReviewIssue, QualityReviewStatus, UploadedAsset, WorkflowRevisionState } from "../../../types";
import type { LocalRevisionCardState, LocalRevisionPromptMetadataState } from "./useWorkflowAssetOperations.ts";

const LOCAL_REVISION_HISTORY_PREVIEW_LIMIT = 12;

function normalizedQualityStatus(status?: QualityReviewStatus | string | null): QualityReviewStatus {
  const value = typeof status === "string" && status.trim() ? status.trim().toLowerCase() : "unchecked";
  if (value === "ok" || value === "success" || value === "succeeded") return "passed";
  if (value === "warn") return "warning";
  if (value === "error") return "failed";
  return value as QualityReviewStatus;
}

function qualityStatusLabel(status?: QualityReviewStatus | string | null) {
  const normalized = normalizedQualityStatus(status);
  if (normalized === "failed") return "Needs review";
  if (normalized === "warning") return "Warning";
  if (normalized === "passed") return "Passed";
  if (normalized === "unavailable") return "Unavailable";
  return "Not reviewed yet";
}

function statusClass(value: string) {
  return value.replace(/[^a-z0-9_-]/gi, "-").toLowerCase();
}

function qualityStatusClass(status?: QualityReviewStatus | string | null) {
  return statusClass(normalizedQualityStatus(status));
}

function qualityIssuesForAsset(asset: UploadedAsset): QualityReviewIssue[] {
  return Array.isArray(asset.quality_issues) ? asset.quality_issues : [];
}

function qualityWarningsForAsset(asset: UploadedAsset): QualityReviewIssue[] {
  return Array.isArray(asset.quality_warnings) ? asset.quality_warnings : [];
}

function qualityIssueMessage(issue: QualityReviewIssue) {
  return stringFromUnknown(issue.message) || stringFromUnknown(issue.code) || JSON.stringify(issue);
}

function isLocalRevisionRunningStatus(status?: string | null) {
  const normalized = (status ?? "").toLowerCase();
  return normalized === "queued" || normalized === "running" || normalized === "waiting" || normalized === "pending";
}

function isLocalRevisionCompletedStatus(status?: string | null) {
  const normalized = (status ?? "").toLowerCase();
  return normalized === "completed" || normalized === "succeeded" || normalized === "ready";
}

function localRevisionStatusLabel(status?: string | null) {
  if (!status) return "";
  if (isLocalRevisionRunningStatus(status)) return "Generating / waiting";
  if (isLocalRevisionCompletedStatus(status)) return "Completed";
  if (["failed", "error"].includes(status.toLowerCase())) return "Failed";
  return status;
}

function localRevisionCandidateLabel(revision: WorkflowRevisionState) {
  const status = localRevisionStatusLabel(revision.status);
  const asset = revisionCandidateAsset(revision);
  const version = asset?.version ? "v" + asset.version : "";
  const run = asset?.run_id ? "run " + asset.run_id : "";
  return [status, version, run].filter(Boolean).join(" · ") || "candidate";
}

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

function isRevisionCandidateQualityFailed(revision: WorkflowRevisionState) {
  return normalizedQualityStatus(revisionCandidateState(revision).qualityStatus) === "failed";
}

function localRevisionPromptMetadataFromAsset(asset?: UploadedAsset | null): LocalRevisionPromptMetadataState | null {
  if (!asset) return null;
  const metadata = recordFromUnknown(asset.metadata) ?? {};
  const promptMetadata = recordFromUnknown(metadata.prompt_metadata) ?? metadata;
  return localRevisionPromptMetadataFromRecord(promptMetadata);
}

function localRevisionPromptMetadataFromState(revision: WorkflowRevisionState): LocalRevisionPromptMetadataState | null {
  const metadata = recordFromUnknown(revision.metadata) ?? {};
  return localRevisionPromptMetadataFromRecord({
    ...metadata,
    revision_id: revision.revision_id,
    generated_at: revision.updated_at ?? revision.created_at,
    quality_status: revisionCandidateState(revision).qualityStatus,
    reviewer: revisionCandidateState(revision).reviewer,
  });
}

function localRevisionPromptMetadataFromRecord(record: Record<string, unknown>): LocalRevisionPromptMetadataState | null {
  const result: LocalRevisionPromptMetadataState = {
    prompt: stringFromUnknown(record.prompt) || stringFromUnknown(record.user_prompt),
    providerPrompt: stringFromUnknown(record.provider_prompt),
    optimizedRevisionPrompt: stringFromUnknown(record.optimized_revision_prompt),
    providerRevisionPrompt: stringFromUnknown(record.provider_revision_prompt),
    revisionRequirements: record.revision_requirements,
    revisionId: stringFromUnknown(record.revision_id),
    generatedAt: stringFromUnknown(record.generated_at),
    specialistResultId: stringFromUnknown(record.specialist_result_id),
    qualityStatus: stringFromUnknown(record.quality_status),
    reviewer: stringFromUnknown(record.reviewer),
  };
  return Object.values(result).some((value) => value !== undefined && value !== null && value !== "") ? result : null;
}

function assetLibraryStatusLabel(asset?: UploadedAsset | null) {
  if (!asset) return "";
  if (asset.library_state === "ready" || asset.library_state === "linked" || asset.library_state === "created") return "已入资源库";
  if (asset.library_state === "pending") return "入库中";
  if (asset.library_state === "failed") return "入库失败";
  return asset.library_entity_id || asset.library_asset_id ? "已关联资源库" : "";
}

function recordFromUnknown(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function formatJson(value: unknown) {
  const text = JSON.stringify(value, null, 2);
  return text.length > 1400 ? text.slice(0, 1400) + "\n..." : text;
}
export function AssetQualityNotice({ asset }: { asset: UploadedAsset }) {
  const status = normalizedQualityStatus(asset.quality_status);
  const issues = qualityIssuesForAsset(asset);
  const warnings = qualityWarningsForAsset(asset);
  const hasQuality = status !== "unchecked" || issues.length || warnings.length || asset.reviewer || asset.quality_score !== undefined;
  if (!hasQuality) return null;
  return (
    <details className={`asset-quality-notice status-${qualityStatusClass(status)}`}>
      <summary>
        <span>{qualityStatusLabel(status)}</span>
        {issues.length ? <em>{issues.length} quality issue{issues.length > 1 ? "s" : ""}</em> : null}
        {warnings.length ? <em>{warnings.length} quality warning{warnings.length > 1 ? "s" : ""}</em> : null}
      </summary>
      <div className="asset-quality-details">
        {asset.reviewer ? <span>Reviewer: {asset.reviewer}</span> : null}
        {asset.quality_score !== undefined && asset.quality_score !== null ? <span>Score: {asset.quality_score}</span> : null}
        {issues.map((issue, index) => <span key={`asset-quality-issue-${index}`}>Issue: {qualityIssueMessage(issue)}</span>)}
        {warnings.map((issue, index) => <span key={`asset-quality-warning-${index}`}>Warning: {qualityIssueMessage(issue)}</span>)}
      </div>
    </details>
  );
}

export function AssetRevisionHistoryPanel({
  asset,
  state,
  onClose,
  onRefresh,
  onUseVersion,
  busyByRevisionId,
  qualityOverrideRevisionId,
  onAcceptCandidate,
  onRejectCandidate,
  onCancelQualityOverride,
}: {
  asset: UploadedAsset | null;
  state?: LocalRevisionCardState;
  onClose: () => void;
  onRefresh: () => void;
  onUseVersion: (asset: UploadedAsset) => void;
  busyByRevisionId: Record<string, "accept" | "reject" | undefined>;
  qualityOverrideRevisionId: string | null;
  onAcceptCandidate: (revision: WorkflowRevisionState, overrideQualityFailure?: boolean) => void;
  onRejectCandidate: (revision: WorkflowRevisionState) => void;
  onCancelQualityOverride: () => void;
}) {
  if (!asset) return null;
  const historyAssets = dedupeAssets([...(state?.history ?? []), ...(state?.assets ?? [])]);
  const activeAssetId = state?.activeAsset?.asset_id ?? asset.asset_id;
  const currentAsset = state?.activeAsset ?? historyAssets.find((item) => item.asset_id === activeAssetId) ?? asset;
  const pendingRevisionCandidates = localRevisionPendingCandidatesForState(state);
  const historicalAssets = historyAssets.filter((item) => item.asset_id !== currentAsset.asset_id);
  const visibleHistoryAssets = historicalAssets.slice(0, LOCAL_REVISION_HISTORY_PREVIEW_LIMIT);
  const historicalRevisions = (state?.revisions ?? []).filter((revision) => !isPendingVisibleRevisionCandidate(revision));

  return (
    <section className="asset-revision-history-panel">
      <div className="asset-revision-history-heading">
        <span>History for {asset.filename}</span>
        <div className="asset-revision-history-actions">
          <button className="small-action" type="button" disabled={state?.historyLoading} onClick={onRefresh}>
            Refresh
          </button>
          <button className="small-action" type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
      {state?.historyError ? <span className="asset-revision-status error">{state.historyError}</span> : null}
      {state?.historyLoading ? <span className="asset-revision-status">Loading history...</span> : null}
      <div className="asset-revision-section">
        <div className="asset-revision-section-heading">Current Version</div>
        <div className="asset-revision-history-item active">
          <NodeAttachmentPreview asset={currentAsset} />
          <span>{currentAsset.filename}</span>
          <span>{[currentAsset.version ? `v${currentAsset.version}` : "", currentAsset.semantic_type ?? "", currentAsset.run_id ? `run ${currentAsset.run_id}` : "", assetLibraryStatusLabel(currentAsset), "已用于当前工作流"].filter(Boolean).join(" · ")}</span>
          <LocalRevisionPromptMetadata metadata={localRevisionPromptMetadataFromAsset(currentAsset)} />
        </div>
      </div>
      <div className="asset-revision-section">
        <div className="asset-revision-section-heading">Pending Candidates</div>
        <div className="asset-revision-candidate-list">
          {pendingRevisionCandidates.map((revision) => (
            <LocalRevisionCandidateCard
              key={revision.revision_id || `${revision.updated_at ?? revision.created_at ?? ""}-${revision.status}`}
              revision={revision}
              busy={busyByRevisionId[revision.revision_id]}
              qualityOverrideRevisionId={qualityOverrideRevisionId}
              onAccept={(overrideQualityFailure) => onAcceptCandidate(revision, overrideQualityFailure)}
              onReject={() => onRejectCandidate(revision)}
              onCancelQualityOverride={onCancelQualityOverride}
            />
          ))}
          {!pendingRevisionCandidates.length && !state?.historyLoading ? <em>No pending candidates.</em> : null}
        </div>
      </div>
      <div className="asset-revision-section">
        <div className="asset-revision-section-heading">History</div>
        <div className="asset-revision-history-list">
          {visibleHistoryAssets.map((item) => (
            <div key={item.asset_id} className={`asset-revision-history-item ${item.asset_id === activeAssetId ? "active" : ""}`}>
              <NodeAttachmentPreview asset={item} />
              <span>{item.filename}</span>
              <span>{[item.version ? `v${item.version}` : "", item.semantic_type ?? "", item.run_id ? `run ${item.run_id}` : "", assetLibraryStatusLabel(item), item.asset_id === activeAssetId ? "已用于当前工作流" : "未用于当前工作流"].filter(Boolean).join(" · ")}</span>
              <button className="asset-revision-trigger" type="button" disabled={item.asset_id === activeAssetId || isLocalRevisionRunningStatus(state?.status)} onClick={() => onUseVersion(item)}>
                Use this version
              </button>
              <LocalRevisionPromptMetadata metadata={localRevisionPromptMetadataFromAsset(item)} />
            </div>
          ))}
          {historicalAssets.length > visibleHistoryAssets.length ? <span className="asset-revision-history-more">+{historicalAssets.length - visibleHistoryAssets.length} more history assets</span> : null}
          {!historicalAssets.length && !state?.historyLoading ? <em>No older versions yet.</em> : null}
        </div>
      </div>
      {historicalRevisions.length ? (
        <div className="asset-revision-history-revisions">
          {historicalRevisions.slice(0, 4).map((revision) => (
            <span key={revision.revision_id || `${revision.status}-${revision.updated_at ?? revision.created_at ?? ""}`}>
              {revision.revision_id || "revision"} · {localRevisionCandidateLabel(revision)}
              {revision.error ? ` · ${revision.error}` : ""}
            </span>
          ))}
        </div>
      ) : null}
      <LocalRevisionPromptMetadata metadata={state?.promptMetadata} />
    </section>
  );
}

export function LocalRevisionCandidateCard({
  revision,
  busy,
  qualityOverrideRevisionId,
  acceptLabel = "Accept",
  acceptBusyLabel = "Accepting...",
  forceAcceptLabel = "Accept anyway",
  rejectLabel = "Reject",
  rejectBusyLabel = "Rejecting...",
  onAccept,
  onReject,
  onCancelQualityOverride,
}: {
  revision: WorkflowRevisionState;
  busy?: "accept" | "reject";
  qualityOverrideRevisionId: string | null;
  acceptLabel?: string;
  acceptBusyLabel?: string;
  forceAcceptLabel?: string;
  rejectLabel?: string;
  rejectBusyLabel?: string;
  onAccept: (overrideQualityFailure?: boolean) => void;
  onReject: () => void;
  onCancelQualityOverride: () => void;
}) {
  const candidate = revisionCandidateState(revision);
  const asset = candidate.asset ?? revisionCandidateAsset(revision);
  const qualityFailed = isRevisionCandidateQualityFailed(revision);
  const needsOverride = qualityFailed && qualityOverrideRevisionId === revision.revision_id;
  const disabled = Boolean(busy);
  const libraryLabel = revisionCandidateLibraryLabel(candidate);
  const workflowUsageLabel = revisionCandidateWorkflowUsageLabel(candidate);
  const sourceLabel = candidate.source_type === "upload" ? "上传来源" : candidate.source_type === "workflow_generation" ? "生成来源" : candidate.source_type ? `source ${candidate.source_type}` : "";
  const details = [
    candidate.targetEntityId ? `entity ${candidate.targetEntityId}` : "",
    candidate.semanticType ?? "",
    candidate.reviewer ? `reviewer ${candidate.reviewer}` : "",
    libraryLabel,
    workflowUsageLabel,
    sourceLabel,
    candidate.library_error && libraryLabel === "入库失败" ? candidate.library_error : "",
  ].filter(Boolean);

  return (
    <div className={`asset-revision-candidate-card ${qualityFailed ? "quality-failed" : ""}`}>
      {asset ? <NodeAttachmentPreview asset={asset} /> : <span className="asset-revision-candidate-placeholder">Candidate</span>}
      <span className="asset-revision-candidate-title">{asset?.filename || revision.revision_id || "Revision candidate"}</span>
      <span className="asset-revision-candidate-meta">
        {localRevisionCandidateLabel(revision)}
        {candidate.issueCount ? ` · ${candidate.issueCount} issue(s)` : ""}
      </span>
      {details.length ? <span className="asset-revision-candidate-meta">{details.join(" · ")}</span> : null}
      {revision.message ? <span className="asset-revision-candidate-note">{revision.message}</span> : null}
      {needsOverride ? (
        <span className="asset-revision-candidate-confirm">
          <span>Quality failed. Accepting requires confirmation.</span>
          <button className="asset-revision-trigger" type="button" disabled={disabled} onClick={() => onAccept(true)}>
            {forceAcceptLabel}
          </button>
          <button className="asset-revision-trigger" type="button" disabled={disabled} onClick={onCancelQualityOverride}>
            Cancel
          </button>
        </span>
      ) : (
        <span className="asset-revision-candidate-actions">
          <button className="asset-revision-trigger" type="button" disabled={disabled} onClick={() => onAccept(false)}>
            {busy === "accept" ? acceptBusyLabel : acceptLabel}
          </button>
          <button className="asset-revision-trigger" type="button" disabled={disabled} onClick={onReject}>
            {busy === "reject" ? rejectBusyLabel : rejectLabel}
          </button>
        </span>
      )}
      <LocalRevisionPromptMetadata metadata={localRevisionPromptMetadataFromState(revision)} />
    </div>
  );
}

export function LocalRevisionPromptMetadata({ metadata }: { metadata?: LocalRevisionPromptMetadataState | null }) {
  if (!metadata) return null;
  const prompt = metadata.prompt?.trim();
  const providerPrompt = metadata.providerPrompt?.trim();
  const optimizedRevisionPrompt = metadata.optimizedRevisionPrompt?.trim();
  const providerRevisionPrompt = metadata.providerRevisionPrompt?.trim();
  const hasRevisionRequirements = metadata.revisionRequirements !== undefined && metadata.revisionRequirements !== null;
  const revisionId = metadata.revisionId?.trim();
  const generatedAt = metadata.generatedAt?.trim();
  const specialistResultId = metadata.specialistResultId?.trim();
  const qualityStatus = metadata.qualityStatus?.trim();
  const reviewer = metadata.reviewer?.trim();
  if (!prompt && !providerPrompt && !optimizedRevisionPrompt && !providerRevisionPrompt && !hasRevisionRequirements && !revisionId && !generatedAt && !specialistResultId && !qualityStatus && !reviewer) return null;

  return (
    <div className="local-revision-prompt-metadata">
      <strong>Revision prompt metadata</strong>
      {prompt ? (
        <span>
          <em>Prompt</em>
          <b>{prompt}</b>
        </span>
      ) : null}
      {providerPrompt ? (
        <span>
          <em>Provider prompt</em>
          <b>{providerPrompt}</b>
        </span>
      ) : null}
      {optimizedRevisionPrompt ? (
        <span>
          <em>Optimized revision prompt</em>
          <b>{optimizedRevisionPrompt}</b>
        </span>
      ) : null}
      {providerRevisionPrompt ? (
        <span>
          <em>Provider revision prompt</em>
          <b>{providerRevisionPrompt}</b>
        </span>
      ) : null}
      {hasRevisionRequirements ? (
        <span>
          <em>Revision requirements</em>
          <b>{formatJson(metadata.revisionRequirements)}</b>
        </span>
      ) : null}
      {revisionId ? (
        <span>
          <em>Revision</em>
          <b>{revisionId}</b>
        </span>
      ) : null}
      {generatedAt ? (
        <span>
          <em>Generated</em>
          <b>{generatedAt}</b>
        </span>
      ) : null}
      {specialistResultId ? (
        <span>
          <em>Specialist result</em>
          <b>{specialistResultId}</b>
        </span>
      ) : null}
      {qualityStatus || reviewer ? (
        <span>
          <em>Quality</em>
          <b>{[qualityStatus, reviewer ? `reviewer ${reviewer}` : ""].filter(Boolean).join(" · ")}</b>
        </span>
      ) : null}
    </div>
  );
}

export function NodeAssetHistoryPreview({
  asset,
  revisionState,
  onOpen,
  onRegenerate,
  onRevise,
  onViewHistory,
}: {
  asset: UploadedAsset;
  revisionState?: LocalRevisionCardState;
  onOpen?: () => void;
  onRegenerate?: () => void;
  onRevise?: () => void;
  onViewHistory?: () => void;
}) {
  const state = assetLifecycleState(asset);
  const details = [
    ...assetLineageDetails(asset, {
      workflow: "source workflow",
      node: "source node",
      revision: "revision",
      workingVersion: "working version",
      missing: "deleted_missing_file",
    }),
    asset.run_id ? `run ${asset.run_id}` : "",
    asset.entity_id ? `entity ${asset.entity_id}` : "",
    asset.semantic_type ?? "",
  ].filter(Boolean);
  const revisionRunning = isLocalRevisionRunningStatus(revisionState?.status);
  const revisionStatus = revisionState?.error || revisionState?.message || (revisionState?.status ? localRevisionStatusLabel(revisionState.status) : "");
  const candidateCount = revisionState?.candidates?.length ?? 0;
  const missingFile = assetFileMissing(asset);

  return (
    <span className={`node-asset-history-item ${revisionRunning ? "is-local-revision-running" : ""} ${missingFile ? "is-missing-file" : ""}`}>
      <NodeAttachmentPreview asset={asset} onOpen={onOpen} />
      <span className={`asset-history-state ${state}`}>{state}</span>
      {missingFile ? <span className="asset-revision-status error">文件缺失 / 不可预览</span> : null}
      {candidateCount ? <span className="asset-revision-candidate-summary">{candidateCount} pending candidate{candidateCount > 1 ? "s" : ""}</span> : null}
      <AssetQualityNotice asset={asset} />
      {details.length ? <span className="asset-history-meta">{details.join(" · ")}</span> : null}
      {onRegenerate || onRevise || onViewHistory ? (
        <span className="asset-revision-controls">
          {onRegenerate ? (
            <button className="asset-revision-trigger" type="button" disabled={revisionRunning} onClick={onRegenerate}>
              Regenerate this
            </button>
          ) : null}
          {onRevise ? (
            <button className="asset-revision-trigger" type="button" disabled={revisionRunning} onClick={onRevise}>
              Revise with instruction
            </button>
          ) : null}
          {onViewHistory ? (
            <button className="asset-revision-trigger" type="button" onClick={onViewHistory}>
              View history
            </button>
          ) : null}
        </span>
      ) : null}
      {revisionStatus ? (
        <span className={`asset-revision-status ${revisionState?.error ? "error" : ""}`}>
          {revisionRunning ? "Generating / waiting for media..." : revisionStatus}
        </span>
      ) : null}
    </span>
  );
}
