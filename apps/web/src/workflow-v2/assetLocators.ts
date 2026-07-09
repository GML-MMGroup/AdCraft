import type { AssetVersionV2, V2AssetOwnerDisplay } from "../types-v2.ts";

export const V2_ASSET_LOCATOR_PATTERN = /\basset:[a-zA-Z0-9_-]+@[a-zA-Z0-9_-]+\b/g;

export interface ParsedV2AssetLocator {
  assetId: string;
  versionId?: string | null;
}

export function formatV2AssetLocator(assetOrIds: AssetVersionV2 | { asset_id?: string | null; version_id?: string | null }) {
  const assetId = assetOrIds.asset_id?.trim();
  const versionId = assetOrIds.version_id?.trim();
  return assetId && versionId ? `asset:${assetId}@${versionId}` : "";
}

export function parseV2AssetLocator(value: string): ParsedV2AssetLocator | null {
  const match = value.trim().match(/^asset:([A-Za-z0-9_-]+)(?:@([A-Za-z0-9_-]+))?$/);
  if (!match) return null;
  return { assetId: match[1], versionId: match[2] ?? null };
}

export function extractV2AssetLocators(value: string) {
  return Array.from(new Set(value.match(V2_ASSET_LOCATOR_PATTERN) ?? []));
}

export function ownerDisplayLabel(owner?: V2AssetOwnerDisplay | null, fallback = "Referenced asset") {
  return owner?.owner_display_name || owner?.owner_item_id || owner?.owner_slot_id || fallback;
}

export async function copyV2AssetLocator(asset: AssetVersionV2 | { asset_id?: string | null; version_id?: string | null }) {
  const locator = formatV2AssetLocator(asset);
  if (!locator) return "";
  if (typeof navigator === "undefined" || !navigator.clipboard) return locator;
  await navigator.clipboard.writeText(locator);
  return locator;
}
