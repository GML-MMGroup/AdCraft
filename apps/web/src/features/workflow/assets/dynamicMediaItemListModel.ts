import { ApiError } from "../../../api/client";
import type { DynamicMediaItemWorkingVersion, GraphValidationIssue, WorkflowNodeVersion } from "../../../types";

export function workingVersionDebugKey(version: WorkflowNodeVersion) {
  return stableKeyPart("node-version", version.version, version.node_run_id, version.output_hash, version.created_at, version.status);
}

export function validationIssueKey(issue: GraphValidationIssue) {
  return stableKeyPart("validation", issue.level, issue.code, issue.node_id, issue.edge_id, issue.message);
}

export function isWorkingVersionQualityFailed(version?: DynamicMediaItemWorkingVersion | null) {
  return String(version?.quality_status ?? "").toLowerCase() === "failed";
}

export function workingVersionResultText(result: Record<string, unknown>, fallback: string) {
  return stringFromUnknown(result.message) || fallback;
}

export function workingVersionBatchText(result: Record<string, unknown>) {
  const applied = stringArrayFromUnknown(result.applied_item_ids).length;
  const skipped = Array.isArray(result.skipped_items) ? result.skipped_items.length : 0;
  const failed = Array.isArray(result.failed_items) ? result.failed_items.length : 0;
  const perShot = Array.isArray(result.per_shot_status) ? result.per_shot_status.length : 0;
  if (applied || skipped || failed) return `已使用 ${applied} 个 · 跳过 ${skipped} 个 · 失败 ${failed} 个`;
  if (perShot) return `已处理 ${perShot} 个镜头视频`;
  return stringFromUnknown(result.message) || "Operation submitted";
}

export function workingVersionErrorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    const payload = recordFromUnknown(error.payload);
    const detail = recordFromUnknown(payload?.detail);
    const code = stringFromUnknown(detail?.code) || stringFromUnknown(payload?.code);
    if (code === "shot_video_reference_required") return "需要先生成分镜图、选择参考图，或上传参考图。";
    if (code === "quality_blocked") return "当前工作版本质量未通过，不能直接使用。";
    if (code) return `${code}: ${error.message}`;
  }
  return error instanceof Error ? error.message : fallback;
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

function stableKeyPart(...values: Array<string | number | boolean | null | undefined>) {
  return values
    .filter((value) => value !== null && value !== undefined && value !== "")
    .map((value) => String(value).replace(/[^a-zA-Z0-9_.:-]+/g, "_"))
    .join(":");
}
