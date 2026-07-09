import type { NodeRunResult, QualityReviewResponse, QualityReviewStatus, QualityReviewSummary, UploadedAsset, WorkflowNode } from "../../../types.ts";
import { dedupeAssets } from "../../../workflow/assets.ts";
import { isCanvasEntityAreaNode } from "../../../workflow/canvasEntityAreas.ts";
import { semanticGalleryPreviewAssets } from "../../../workflow/semanticGallery.ts";
import { textFromWorkflowOutput, workflowNodeContentPreview } from "../../../workflow/runtimeResults.ts";
import { getWorkflowNodeType } from "../canvas/workflowNodeModel.ts";

export function getNodeContentPreview(node: WorkflowNode, run?: { output?: Record<string, unknown> }) {
  return workflowNodeContentPreview(node, run);
}

export function getNodeOutputAssets(node: WorkflowNode, run?: { output_assets?: unknown[] }) {
  const assets = [...((run?.output_assets as UploadedAsset[] | undefined) ?? []), ...(node.output_assets ?? [])];
  return dedupeAssets(assets.filter(isUploadedAsset));
}

export function getNodePreviewAssets(node: WorkflowNode, run?: { output_assets?: unknown[] }) {
  return previewAssetsForCanvasNodeType(getWorkflowNodeType(node), getNodeOutputAssets(node, run));
}

export function previewAssetsForCanvasNodeType(nodeType: string, assets: UploadedAsset[]) {
  const activeAssets = activeWorkflowAssets(assets);
  if (isCanvasEntityAreaNode(nodeType)) return activeAssets;
  return semanticGalleryPreviewAssets(nodeType, activeAssets);
}

export function getNodeOutputCount(node: WorkflowNode, run?: { output?: Record<string, unknown> | null; output_assets?: unknown[] }) {
  const assetCount = getNodeOutputAssets(node, run).length;
  if (assetCount) return assetCount;
  return textFromWorkflowOutput(run?.output) || textFromWorkflowOutput(node.output) ? 1 : 0;
}

function isUploadedAsset(value: unknown): value is UploadedAsset {
  return Boolean(value && typeof value === "object");
}

export function activeWorkflowAssets(assets: UploadedAsset[]) {
  const activeAssets = assets.filter((asset) => asset.is_active === true && !asset.is_archived);
  if (activeAssets.length) return activeAssets;
  const unarchivedAssets = assets.filter((asset) => !asset.is_archived);
  return unarchivedAssets.length ? unarchivedAssets : assets;
}

export function qualitySummaryForNode(node?: WorkflowNode | null, run?: Pick<NodeRunResult, "output" | "output_assets"> | null): QualityReviewSummary | null {
  return qualitySummaryFromOutput(run?.output) ?? qualitySummaryFromOutput(node?.output) ?? qualitySummaryFromAssets(run?.output_assets) ?? qualitySummaryFromAssets(node?.output_assets);
}

export function qualitySummaryFromOutput(output?: Record<string, unknown> | null): QualityReviewSummary | null {
  const summary = output?.quality_summary;
  return summary && typeof summary === "object" && !Array.isArray(summary) ? (summary as QualityReviewSummary) : null;
}

export function qualitySummaryFromAssets(assets?: UploadedAsset[] | null): QualityReviewSummary | null {
  const statuses = (assets ?? []).map((asset) => normalizedQualityStatus(asset.quality_status)).filter((status) => status !== "unchecked");
  if (!statuses.length) return null;
  const failedCount = statuses.filter((status) => status === "failed").length;
  const warningCount = statuses.filter((status) => status === "warning").length;
  const unavailableCount = statuses.filter((status) => status === "unavailable").length;
  const status: QualityReviewStatus = failedCount ? "failed" : warningCount ? "warning" : unavailableCount ? "unavailable" : "passed";
  return {
    status,
    checked_asset_count: statuses.length,
    warning_count: warningCount,
    failed_count: failedCount,
    unavailable_count: unavailableCount,
  };
}

export function qualitySummaryFromResponse(response: QualityReviewResponse): QualityReviewSummary | null {
  return (
    response.quality_summary ??
    qualitySummaryFromOutput(response.output) ??
    qualitySummaryFromOutput(response.node?.output) ??
    qualitySummaryFromOutput(response.run?.output) ??
    qualitySummaryFromOutput(response.node_run?.output) ??
    qualitySummaryFromAssets(response.output_assets) ??
    qualitySummaryFromAssets(response.assets) ??
    null
  );
}

export function normalizedQualityStatus(status?: QualityReviewStatus | string | null): QualityReviewStatus {
  const value = typeof status === "string" && status.trim() ? status.trim().toLowerCase() : "unchecked";
  if (value === "ok" || value === "success" || value === "succeeded") return "passed";
  if (value === "warn") return "warning";
  if (value === "error") return "failed";
  return value as QualityReviewStatus;
}
