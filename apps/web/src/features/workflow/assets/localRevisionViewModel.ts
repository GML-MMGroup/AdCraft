import type { CanvasRuntimeCandidatePayload } from "../../../workflow/canvasRuntime.ts";
import {
  isPendingVisibleRevisionCandidate,
  localRevisionEntityId,
  localRevisionSemanticType,
  pendingVisibleRevisionCandidates,
  revisionAcceptanceStatus,
  revisionCandidateState,
  revisionGenerationStatus,
  revisionVisibilityStatus,
} from "../../../workflow/localRevision.ts";
import type { UploadedAsset, WorkflowRevisionState } from "../../../types.ts";
import { humanizeNodeType } from "../canvas/workflowNodeModel.ts";
import { normalizedQualityStatus } from "./workflowAssetPreviewModel.ts";
import type { LocalRevisionCardState, LocalRevisionPromptMetadataState } from "./useWorkflowAssetOperations.ts";

export function isLocalRevisionRunningStatus(status?: string | null) {
  if (!status) return false;
  return ["queued", "running", "waiting"].includes(status.toLowerCase());
}

export function isLocalRevisionTerminalStatus(status?: string | null) {
  if (!status) return false;
  return ["completed", "complete", "success", "succeeded", "failed", "error", "cancelled", "canceled"].includes(status.toLowerCase());
}

export function isLocalRevisionCompletedStatus(status?: string | null) {
  if (!status) return false;
  return ["completed", "complete", "success", "succeeded"].includes(status.toLowerCase());
}

export function localRevisionStatusLabel(status?: string | null) {
  if (!status) return "";
  if (isLocalRevisionCompletedStatus(status)) return "Completed";
  if (status === "waiting") return "Waiting for media";
  if (status === "running") return "Running";
  if (status === "queued") return "Queued";
  if (status === "failed" || status === "error") return "Failed";
  if (status === "cancelled" || status === "canceled") return "Cancelled";
  return humanizeNodeType(status);
}

export function localRevisionCandidateLabel(revision: WorkflowRevisionState) {
  return [
    revisionGenerationStatus(revision) || localRevisionStatusLabel(revision.status),
    revisionAcceptanceStatus(revision),
    revisionVisibilityStatus(revision),
  ]
    .filter(Boolean)
    .map((value) => humanizeNodeType(value))
    .join(" · ");
}

export function assetLibraryStatusLabel(asset?: UploadedAsset | null) {
  if (!asset) return "";
  const state = String(asset.library_state ?? "").trim().toLowerCase();
  if (state === "failed") return "入库失败";
  if (state === "pending") return "入库中";
  if (state === "skipped") return "未入库";
  if (["created", "linked", "ready"].includes(state) || asset.library_entity_id || asset.library_asset_id || asset.library_asset_ids?.length) return "已入库";
  return "";
}

export function localRevisionPendingCandidatesForState(state?: LocalRevisionCardState) {
  return pendingVisibleRevisionCandidates(dedupeRevisionStates([...(state?.revisions ?? []), ...(state?.candidates ?? [])]));
}

export function localRevisionTargetsMatch(
  left: Pick<UploadedAsset, "asset_id" | "asset_type" | "entity_id" | "semantic_type">,
  right: Pick<UploadedAsset, "asset_id" | "asset_type" | "entity_id" | "semantic_type">,
) {
  return localRevisionEntityId(left) === localRevisionEntityId(right) && localRevisionSemanticType(left) === localRevisionSemanticType(right);
}

export function revisionMatchesCanvasCandidate(revision: WorkflowRevisionState, candidate: CanvasRuntimeCandidatePayload) {
  const entityId = revision.target_entity_id ?? revision.revision?.target_entity_id ?? null;
  const semanticType = revision.semantic_type ?? revision.revision?.semantic_type ?? null;
  if (candidate.entityId && entityId && candidate.entityId !== entityId) return false;
  if (candidate.semanticType && semanticType && candidate.semanticType !== semanticType) return false;
  return true;
}

export function assetTypeFromSemanticType(semanticType: string): UploadedAsset["asset_type"] {
  const value = semanticType.toLowerCase();
  if (value.includes("video")) return "video";
  if (value.includes("audio") || value.includes("bgm") || value.includes("music")) return "audio";
  if (value.includes("document") || value.includes("script") || value.includes("text")) return "document";
  return "image";
}

function dedupeRevisionStates(revisions: WorkflowRevisionState[]) {
  const seen = new Set<string>();
  return revisions.filter((revision, index) => {
    const key = revision.revision_id || `${revision.status}-${revision.updated_at ?? revision.created_at ?? index}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function isRevisionCandidateNotable(revision: WorkflowRevisionState) {
  const candidate = revisionCandidateState(revision);
  const status = normalizedQualityStatus(candidate.qualityStatus);
  return status === "warning" || status === "failed" || candidate.issueCount > 0;
}

export function latestLocalRevisionPromptMetadata(revisions?: WorkflowRevisionState[]): LocalRevisionPromptMetadataState | null {
  if (!revisions?.length) return null;
  for (const revision of [...revisions].reverse()) {
    const metadata = localRevisionPromptMetadataFromState(revision);
    if (metadata) return metadata;
  }
  return null;
}

export function localRevisionPromptMetadataFromAsset(asset?: UploadedAsset | null): LocalRevisionPromptMetadataState | null {
  if (!asset) return null;
  const assetRecord = asset as UploadedAsset & Record<string, unknown>;
  const metadataRecord = recordFromUnknown(asset.metadata);
  const prompt =
    stringFromUnknown(assetRecord.prompt) ||
    stringFromUnknown(metadataRecord?.prompt) ||
    stringFromUnknown(metadataRecord?.generation_prompt);
  const providerPrompt =
    stringFromUnknown(assetRecord.provider_prompt) ||
    stringFromUnknown(metadataRecord?.provider_prompt) ||
    stringFromUnknown(metadataRecord?.providerPrompt);
  const revisionId =
    stringFromUnknown(assetRecord.revision_id) ||
    stringFromUnknown(metadataRecord?.revision_id) ||
    stringFromUnknown(metadataRecord?.revisionId);
  const generatedAt =
    stringFromUnknown(assetRecord.generated_at) ||
    stringFromUnknown(assetRecord.created_at) ||
    stringFromUnknown(metadataRecord?.generated_at) ||
    stringFromUnknown(metadataRecord?.created_at);
  const specialistResultId =
    stringFromUnknown(assetRecord.specialist_result_id) ||
    stringFromUnknown(metadataRecord?.specialist_result_id) ||
    stringFromUnknown(metadataRecord?.specialistResultId);
  const qualityStatus = stringFromUnknown(assetRecord.quality_status) || stringFromUnknown(metadataRecord?.quality_status);
  const reviewer = stringFromUnknown(assetRecord.reviewer) || stringFromUnknown(metadataRecord?.reviewer);
  const hasMetadata = Boolean(prompt || providerPrompt || revisionId || generatedAt || specialistResultId || qualityStatus || reviewer);
  if (!hasMetadata) return null;
  return {
    prompt: prompt || null,
    providerPrompt: providerPrompt || null,
    revisionId: revisionId || null,
    generatedAt: generatedAt || null,
    specialistResultId: specialistResultId || null,
    qualityStatus: qualityStatus || null,
    reviewer: reviewer || null,
  };
}

export function localRevisionPromptMetadataFromState(revision: WorkflowRevisionState): LocalRevisionPromptMetadataState | null {
  const record = revision as WorkflowRevisionState & Record<string, unknown>;
  const revisionRecord = recordFromUnknown(record.revision);
  const prompt =
    stringFromUnknown(record.prompt) ||
    stringFromUnknown(record.generation_prompt) ||
    stringFromUnknown(revisionRecord?.prompt) ||
    stringFromUnknown(revisionRecord?.generation_prompt);
  const providerPrompt =
    stringFromUnknown(record.provider_prompt) ||
    stringFromUnknown(record.providerPrompt) ||
    stringFromUnknown(revisionRecord?.provider_prompt) ||
    stringFromUnknown(revisionRecord?.providerPrompt);
  const optimizedRevisionPrompt =
    stringFromUnknown(record.optimizedRevisionPrompt) ||
    stringFromUnknown(record.optimized_revision_prompt) ||
    stringFromUnknown(revisionRecord?.optimizedRevisionPrompt) ||
    stringFromUnknown(revisionRecord?.optimized_revision_prompt);
  const providerRevisionPrompt =
    stringFromUnknown(record.providerRevisionPrompt) ||
    stringFromUnknown(record.provider_revision_prompt) ||
    stringFromUnknown(revisionRecord?.providerRevisionPrompt) ||
    stringFromUnknown(revisionRecord?.provider_revision_prompt);
  const revisionRequirements =
    record.revisionRequirements ??
    record.revision_requirements ??
    revisionRecord?.revisionRequirements ??
    revisionRecord?.revision_requirements;
  const generatedAt =
    stringFromUnknown(record.generated_at) ||
    stringFromUnknown(record.completed_at) ||
    stringFromUnknown(record.updated_at) ||
    stringFromUnknown(revisionRecord?.generated_at);
  const specialistResultId =
    stringFromUnknown(record.specialist_result_id) ||
    stringFromUnknown(record.specialistResultId) ||
    stringFromUnknown(revisionRecord?.specialist_result_id) ||
    stringFromUnknown(revisionRecord?.specialistResultId);
  const qualityStatus = stringFromUnknown(record.quality_status);
  const reviewer = stringFromUnknown(record.reviewer);
  const revisionId = stringFromUnknown(record.revision_id);
  const hasMetadata = Boolean(prompt || providerPrompt || optimizedRevisionPrompt || providerRevisionPrompt || revisionRequirements !== undefined || revisionId || generatedAt || specialistResultId || qualityStatus || reviewer);
  if (!hasMetadata) return null;
  return {
    prompt: prompt || null,
    providerPrompt: providerPrompt || null,
    optimizedRevisionPrompt: optimizedRevisionPrompt || null,
    providerRevisionPrompt: providerRevisionPrompt || null,
    revisionRequirements,
    revisionId: revisionId || null,
    generatedAt: generatedAt || null,
    specialistResultId: specialistResultId || null,
    qualityStatus: qualityStatus || null,
    reviewer: reviewer || null,
  };
}

export function localRevisionStatusText(revision: WorkflowRevisionState, asset: UploadedAsset) {
  const label = localRevisionStatusLabel(revision.status);
  const suffix = asset.filename ? ` for ${asset.filename}` : "";
  if (revision.error) return `Asset revision failed${suffix}: ${revision.error}`;
  if (revision.message) return revision.message;
  if (isPendingVisibleRevisionCandidate(revision)) return `Asset revision candidate ready for review${suffix}`;
  if (revision.status === "waiting") return `Asset revision waiting for media${suffix}`;
  if (isLocalRevisionCompletedStatus(revision.status)) return `Asset revision completed${suffix}`;
  return label ? `Asset revision ${label.toLowerCase()}${suffix}` : `Asset revision updated${suffix}`;
}

function recordFromUnknown(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}
