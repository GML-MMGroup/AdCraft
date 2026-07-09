import type { NodeRunResult, QualityReviewIssue, QualityReviewResponse, QualityReviewStatus, QualityReviewSummary, UploadedAsset, WorkflowNode, WorkflowRevisionState } from "../../../types.ts";
import { dedupeAssets } from "../../../workflow/assets.ts";
import { revisionCandidateState } from "../../../workflow/localRevision.ts";
import { visibleWorkflowNodes } from "../../../workflow/visibility.ts";
import { statusClass } from "../page/workflowPageFormatters.ts";
import { normalizedQualityStatus, qualitySummaryForNode, qualitySummaryFromOutput, qualitySummaryFromResponse } from "../assets/workflowAssetPreviewModel.ts";

export function isNodeStatusTerminal(status?: string | null) {
  if (!status) return false;
  return ["completed", "complete", "success", "succeeded", "failed", "error", "cancelled", "canceled", "skipped", "done", "finish", "finished"].includes(
    status.toLowerCase(),
  );
}

export function isSuccessfulNodeStatus(status?: string | null) {
  if (!status) return false;
  return ["completed", "complete", "success", "succeeded", "done", "finish", "finished"].includes(status.toLowerCase());
}

export function isFailedNodeStatus(status?: string | null) {
  if (!status) return false;
  return ["failed", "error", "cancelled", "canceled"].includes(status.toLowerCase());
}

export function workflowIsFullyCompleted(nodes: WorkflowNode[]) {
  const visibleNodes = visibleWorkflowNodes(nodes);
  return visibleNodes.length > 0 && visibleNodes.every((node) => isSuccessfulNodeStatus(node.status) && !node.stale);
}

export function mergeOutputPreservingQuality(
  current?: WorkflowNode["output"] | null,
  next?: WorkflowNode["output"] | null,
  explicitSummary?: QualityReviewSummary | null,
): WorkflowNode["output"] | undefined {
  if (!next && !current && !explicitSummary) return undefined;
  const nextOutput = next ? { ...next } : current ? { ...current } : {};
  const summary = explicitSummary ?? qualitySummaryFromOutput(next) ?? qualitySummaryFromOutput(current);
  if (summary) nextOutput.quality_summary = summary;
  return nextOutput;
}

export function mergeQualityReviewResponseIntoNode(node: WorkflowNode, response: QualityReviewResponse): WorkflowNode {
  const summary = qualitySummaryFromResponse(response) ?? qualitySummaryForNode(node);
  const responseOutput = response.output ?? response.node?.output ?? response.run?.output ?? response.node_run?.output;
  const responseAssets = dedupeAssets([
    ...(response.output_assets ?? []),
    ...(response.assets ?? []),
    ...(response.node?.output_assets ?? []),
    ...(response.run?.output_assets ?? []),
    ...(response.node_run?.output_assets ?? []),
  ]);
  const outputAssets = responseAssets.length ? dedupeAssets([...responseAssets, ...(node.output_assets ?? [])]) : node.output_assets;
  return {
    ...node,
    output: mergeOutputPreservingQuality(node.output, responseOutput, summary),
    ...(outputAssets ? { output_assets: outputAssets } : {}),
  };
}

export function mergeQualityReviewResponseIntoRun(run: NodeRunResult, response: QualityReviewResponse): NodeRunResult {
  const summary = qualitySummaryFromResponse(response) ?? qualitySummaryFromOutput(run.output);
  const responseOutput = response.output ?? response.run?.output ?? response.node_run?.output ?? response.node?.output;
  const responseAssets = dedupeAssets([
    ...(response.output_assets ?? []),
    ...(response.assets ?? []),
    ...(response.run?.output_assets ?? []),
    ...(response.node_run?.output_assets ?? []),
    ...(response.node?.output_assets ?? []),
  ]);
  return {
    ...run,
    output: mergeOutputPreservingQuality(run.output, responseOutput, summary),
    output_assets: responseAssets.length ? dedupeAssets([...responseAssets, ...(run.output_assets ?? [])]) : run.output_assets,
  };
}

export function qualityStatusLabel(status?: QualityReviewStatus | string | null) {
  const normalized = normalizedQualityStatus(status);
  if (normalized === "failed") return "Needs review";
  if (normalized === "warning") return "Warning";
  if (normalized === "passed") return "Passed";
  if (normalized === "unavailable") return "Unavailable";
  return "Not reviewed yet";
}

export function qualityStatusClass(status?: QualityReviewStatus | string | null) {
  return statusClass(normalizedQualityStatus(status));
}

export function isRevisionCandidateQualityFailed(revision: WorkflowRevisionState) {
  return normalizedQualityStatus(revisionCandidateState(revision).qualityStatus) === "failed";
}

export function shouldShowNodeQualityBadge(summary?: QualityReviewSummary | null) {
  return ["warning", "failed"].includes(normalizedQualityStatus(summary?.status ?? summary?.quality_status));
}

export function qualityIssuesForAsset(asset: UploadedAsset): QualityReviewIssue[] {
  return Array.isArray(asset.quality_issues) ? asset.quality_issues : [];
}

export function qualityWarningsForAsset(asset: UploadedAsset): QualityReviewIssue[] {
  return Array.isArray(asset.quality_warnings) ? asset.quality_warnings : [];
}

export function qualityIssueMessage(issue: QualityReviewIssue) {
  return stringFromUnknown(issue.message) || stringFromUnknown(issue.code) || JSON.stringify(issue);
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}
