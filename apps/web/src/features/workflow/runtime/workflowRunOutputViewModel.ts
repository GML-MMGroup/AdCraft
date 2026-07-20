import { dedupeAssets } from "../../../workflow/assets";
import type { NodeRunResult, ReferencePolicy, UploadedAsset, WorkflowNode } from "../../../types";
import { isFailedNodeStatus } from "../quality/qualityReviewViewModel";
import { providerDebugItems } from "../debug/workflowDebugViewModel";

export function getReferencePolicyFromNode(node?: WorkflowNode | null): ReferencePolicy | undefined {
  const metadata = node?.metadata ?? {};
  const policy = metadata.reference_policy ?? node?.output?.reference_policy ?? node?.input_context?.reference_policy;
  return policy && typeof policy === "object" && !Array.isArray(policy) ? (policy as ReferencePolicy) : undefined;
}

export function referencePolicyItems(value: unknown): string[] {
  if (!value) return [];
  if (Array.isArray(value)) return value.flatMap(referencePolicyItems).filter(Boolean);
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return [String(value)];
  if (typeof value !== "object") return [];
  const record = value as Record<string, unknown>;
  const label =
    stringFromUnknown(record.display_name) ||
    stringFromUnknown(record.filename) ||
    stringFromUnknown(record.name) ||
    stringFromUnknown(record.entity_id) ||
    stringFromUnknown(record.library_entity_id) ||
    stringFromUnknown(record.asset_id) ||
    stringFromUnknown(record.code) ||
    stringFromUnknown(record.message) ||
    stringFromUnknown(record.reason);
  return label ? [label] : [JSON.stringify(record)];
}

export function formatReferencePolicySummary(policy?: ReferencePolicy | null) {
  if (!policy) return "";
  const accepted = referencePolicyItems(policy.accepted_assets).length;
  const promptOnly = referencePolicyItems(policy.prompt_only_assets).length;
  const rejected = referencePolicyItems(policy.rejected_assets).length;
  const warnings = referencePolicyItems(policy.warnings).length;
  const errors = referencePolicyItems(policy.errors).length;
  const parts = [
    accepted ? `${accepted} accepted` : "",
    promptOnly ? `${promptOnly} prompt-only` : "",
    rejected ? `${rejected} rejected` : "",
    warnings ? `${warnings} warning${warnings === 1 ? "" : "s"}` : "",
    errors ? `${errors} error${errors === 1 ? "" : "s"}` : "",
  ].filter(Boolean);
  return parts.join(" · ");
}

export function appendReferencePolicyStatus(message: string, policy?: ReferencePolicy | null) {
  const summary = formatReferencePolicySummary(policy);
  return summary ? `${message} · Reference Policy: ${summary}` : message;
}

export function hasActiveOutputFailure(run?: NodeRunResult | null, node?: WorkflowNode | null) {
  const metadata = node?.metadata ?? {};
  return Boolean(
    (run?.has_active_output || metadata.has_active_output) &&
      (isFailedNodeStatus(run?.status) || run?.last_failed_run_id || metadata.last_failed_run_id || metadata.last_error),
  );
}

export function isStrictReferenceFailure(run?: NodeRunResult | null) {
  if (!run) return false;
  const policy = run.reference_policy;
  const policyErrors = referencePolicyItems(policy?.errors).join(" ");
  const policyRejected = referencePolicyItems(policy?.rejected_assets).join(" ");
  const providerStrategy = run.provider_strategy;
  const providerFailures = [
    stringFromUnknown(providerStrategy?.reference_mode),
    ...providerDebugItems(providerStrategy?.fallback_warnings),
    ...providerDebugItems(providerStrategy?.rejected_providers),
    ...providerDebugItems(providerStrategy?.provider_attempts),
    ...providerDebugItems(run.provider_attempts),
    ...providerDebugItems(run.fallback_warnings),
  ].filter(Boolean).join(" ");
  const message = [run.error, run.last_error, policyErrors, policyRejected, providerFailures].filter(Boolean).join(" ");
  return Boolean(
    (isFailedNodeStatus(run.status) || policyErrors || policyRejected || providerFailures) &&
      /(strict|reference|provider_capability_missing)/i.test(message),
  );
}

export function normalizeRunAssets(value?: UploadedAsset[]) {
  if (!Array.isArray(value)) return [];
  return dedupeAssets(value
    .filter((asset) => asset && typeof asset === "object")
    .map((asset, index) => {
      const record = asset as UploadedAsset & Record<string, unknown>;
      const path = String(record.local_path ?? record.public_url ?? record.url ?? record.remote_url ?? "");
      return {
        ...record,
        asset_id: String(record.asset_id ?? record.id ?? `run-asset-${index}`),
        asset_type: normalizeRunAssetType(record.asset_type, path),
        asset_role: record.asset_role ?? "reference",
        filename: String(record.filename ?? record.name ?? record.asset_id ?? `asset-${index + 1}`),
        mime_type: String(record.mime_type ?? record.content_type ?? ""),
        local_path: String(record.local_path ?? path),
        url: typeof record.url === "string" ? record.url : undefined,
        remote_url: typeof record.remote_url === "string" ? record.remote_url : undefined,
        public_url: typeof record.public_url === "string" ? record.public_url : undefined,
      } as UploadedAsset;
    }));
}

function normalizeRunAssetType(value: unknown, path: string): UploadedAsset["asset_type"] {
  if (value === "image" || value === "video" || value === "audio" || value === "document") return value;
  const lowerPath = path.toLowerCase();
  if (/\.(mp4|mov|webm|mkv|avi)(\?|$)/.test(lowerPath)) return "video";
  if (/\.(mp3|wav|m4a|aac|ogg)(\?|$)/.test(lowerPath)) return "audio";
  if (/\.(md|txt|pdf|doc|docx)(\?|$)/.test(lowerPath)) return "document";
  return "image";
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}
