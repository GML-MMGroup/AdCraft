import type { UploadedAsset } from "../types";

export function assetFileMissing(asset: UploadedAsset) {
  const metadata = recordFromUnknown(asset.metadata) ?? {};
  const state = stringFromUnknown(asset.asset_state) || stringFromUnknown(metadata.asset_state);
  const missingReason = stringFromUnknown(metadata.missing_reason) || stringFromUnknown(metadata.missing_file_reason);
  return (
    state === "deleted_missing_file" ||
    metadata.missing_file === true ||
    metadata.file_missing === true ||
    missingReason.toLowerCase().includes("missing")
  );
}

export function assetLifecycleState(asset: UploadedAsset) {
  const metadata = recordFromUnknown(asset.metadata) ?? {};
  const state = stringFromUnknown(asset.asset_state) || stringFromUnknown(metadata.asset_state);
  if (state) return state;
  if (assetFileMissing(asset)) return "deleted_missing_file";
  if (asset.is_archived) return "archived";
  if (asset.is_active === false) return "history";
  return "active";
}

export function assetLineageDetails(
  asset: UploadedAsset,
  labels: { workflow: string; node: string; revision: string; workingVersion: string; missing: string },
) {
  const metadata = recordFromUnknown(asset.metadata) ?? {};
  const lineage = recordFromUnknown(asset.lineage) ?? recordFromUnknown(metadata.lineage) ?? {};
  const details = [
    stringFromUnknown(lineage.workflow_id) ? `${labels.workflow} ${stringFromUnknown(lineage.workflow_id)}` : "",
    stringFromUnknown(lineage.node_id) ? `${labels.node} ${stringFromUnknown(lineage.node_id)}` : "",
    stringFromUnknown(lineage.node_run_id) ? `run ${stringFromUnknown(lineage.node_run_id)}` : "",
    stringFromUnknown(lineage.revision_id) ? `${labels.revision} ${stringFromUnknown(lineage.revision_id)}` : "",
    stringFromUnknown(lineage.working_version_id) ? `${labels.workingVersion} ${stringFromUnknown(lineage.working_version_id)}` : "",
    assetFileMissing(asset) ? labels.missing : "",
  ];
  return details.filter(Boolean);
}

function recordFromUnknown(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}
