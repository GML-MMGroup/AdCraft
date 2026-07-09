import type { UploadedAsset } from "../types";

const URL_IDENTITY_FIELDS = ["public_url", "remote_url", "url"] as const;
const QUALITY_REVIEW_FIELDS = new Set(["quality_status", "quality_score", "quality_issues", "quality_warnings", "reviewer"]);

export function dedupeAssets<T extends UploadedAsset>(assets: readonly (T | null | undefined)[]): T[] {
  const result: T[] = [];
  const identityToIndex = new Map<string, number>();

  for (const asset of assets) {
    if (!asset || typeof asset !== "object") continue;
    const keys = assetIdentityKeys(asset);
    const existingIndex = keys.map((key) => identityToIndex.get(key)).find((index): index is number => typeof index === "number");

    if (existingIndex === undefined) {
      const nextIndex = result.length;
      result.push(asset);
      for (const key of keys) identityToIndex.set(key, nextIndex);
      continue;
    }

    const merged = mergeAssetFields(result[existingIndex], asset);
    result[existingIndex] = merged;
    for (const key of [...keys, ...assetIdentityKeys(merged)]) {
      identityToIndex.set(key, existingIndex);
    }
  }

  return result;
}

function assetIdentityKeys(asset: UploadedAsset) {
  const keys = [
    identityKey("asset_id", asset.asset_id),
    identityKey("local_path", asset.local_path),
    ...URL_IDENTITY_FIELDS.map((field) => identityKey("url", asset[field])),
  ].filter((key): key is string => Boolean(key));

  if (keys.length) return keys;

  const filename = normalizedValue(asset.filename);
  return filename ? [`filename:${filename}`] : [];
}

function identityKey(kind: string, value: unknown) {
  const normalized = normalizedValue(value);
  return normalized ? `${kind}:${normalized}` : undefined;
}

function normalizedValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function mergeAssetFields<T extends UploadedAsset>(primary: T, supplement: T): T {
  const merged = { ...primary } as Record<string, unknown>;
  for (const [key, value] of Object.entries(supplement)) {
    if (QUALITY_REVIEW_FIELDS.has(key) && Object.prototype.hasOwnProperty.call(merged, key)) {
      continue;
    }
    if (!hasUsableValue(merged[key]) && hasUsableValue(value)) {
      merged[key] = value;
    }
  }
  return merged as T;
}

function hasUsableValue(value: unknown) {
  if (value === undefined || value === null) return false;
  if (typeof value === "string") return Boolean(value.trim());
  if (Array.isArray(value)) return value.length > 0;
  return true;
}
