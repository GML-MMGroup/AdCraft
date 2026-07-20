import type { AssetVersionV2, WorkflowSlotV2 } from "../types-v2.ts";

export function isCompleteV2Asset(asset: AssetVersionV2 | null | undefined): asset is AssetVersionV2 {
  if (!asset) return false;
  if (asset.metadata?.id_only) return false;
  return Boolean(asset.public_url || asset.proxy_path || asset.thumbnail_path || asset.file_path);
}

export function v2AssetCompletenessScore(asset: AssetVersionV2 | null | undefined): number {
  if (!asset) return 0;
  const assetRecord = asset as AssetVersionV2 & Record<string, unknown>;
  let score = 1;
  if (!asset.metadata?.id_only) score += 2;
  if (asset.file_path) score += 2;
  if (asset.public_url) score += 4;
  if (asset.proxy_path) score += 3;
  if (asset.thumbnail_path) score += 2;
  if (assetRecord.prompt_summary || assetRecord.provider_prompt || asset.prompt_snapshot) score += 1;
  if (assetRecord.owner_display_name || assetRecord.display_name) score += 1;
  if (asset.quality_status) score += 1;
  return score;
}

export function mergeV2AssetVersions(...sources: Array<Array<AssetVersionV2 | null | undefined>>): AssetVersionV2[] {
  const byAssetId = new Map<string, AssetVersionV2>();
  const byVersionId = new Map<string, AssetVersionV2>();

  for (const source of sources) {
    for (const asset of source) {
      if (!asset?.asset_id && !asset?.version_id) continue;
      const existing =
        (asset.asset_id ? byAssetId.get(asset.asset_id) : undefined) ??
        (asset.version_id ? byVersionId.get(asset.version_id) : undefined);
      const winner = chooseMoreCompleteV2Asset(existing, asset);
      if (winner.asset_id) byAssetId.set(winner.asset_id, winner);
      if (winner.version_id) byVersionId.set(winner.version_id, winner);
    }
  }

  const result: AssetVersionV2[] = [];
  const seen = new Set<string>();
  for (const asset of [...byAssetId.values(), ...byVersionId.values()]) {
    const key = `${asset.asset_id || ""}:${asset.version_id || ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(asset);
  }
  return result;
}

export function v2AssetById(assets: AssetVersionV2[]): Map<string, AssetVersionV2> {
  const map = new Map<string, AssetVersionV2>();
  for (const asset of assets) {
    if (asset.asset_id) map.set(asset.asset_id, chooseMoreCompleteV2Asset(map.get(asset.asset_id), asset));
    if (asset.version_id) map.set(asset.version_id, chooseMoreCompleteV2Asset(map.get(asset.version_id), asset));
  }
  return map;
}

export function missingHydratedAssetIdsForSlots(slots: WorkflowSlotV2[], assets: Map<string, AssetVersionV2>): string[] {
  const ids = new Set<string>();
  for (const slot of slots) {
    for (const id of [
      slot.selected_asset_id,
      slot.current_working_asset_id,
      slot.current_working_version_id,
      ...(slot.history_version_ids ?? []),
    ]) {
      if (!id) continue;
      const asset = assets.get(id);
      if (!isCompleteV2Asset(asset)) ids.add(id);
    }
  }
  return Array.from(ids);
}

export type MissingV2SlotAssetRef = {
  slot_id: string;
  asset_id: string;
  pointer: "selected_asset_id" | "current_working_asset_id" | "current_working_version_id";
};

export function findMissingV2SlotAssetRefs(
  slots: WorkflowSlotV2[],
  assets: AssetVersionV2[],
): MissingV2SlotAssetRef[] {
  const byAssetId = new Set(assets.map((asset) => asset.asset_id).filter(Boolean));
  const byVersionId = new Set(assets.map((asset) => asset.version_id).filter(Boolean));
  const missing: MissingV2SlotAssetRef[] = [];

  for (const slot of slots) {
    if (slot.selected_asset_id && !byAssetId.has(slot.selected_asset_id)) {
      missing.push({ slot_id: slot.slot_id, asset_id: slot.selected_asset_id, pointer: "selected_asset_id" });
    }
    if (slot.current_working_asset_id && !byAssetId.has(slot.current_working_asset_id)) {
      missing.push({ slot_id: slot.slot_id, asset_id: slot.current_working_asset_id, pointer: "current_working_asset_id" });
    }
    if (slot.current_working_version_id && !byVersionId.has(slot.current_working_version_id)) {
      missing.push({ slot_id: slot.slot_id, asset_id: slot.current_working_version_id, pointer: "current_working_version_id" });
    }
  }

  return missing;
}

export function chooseMoreCompleteV2Asset(current: AssetVersionV2 | undefined, incoming: AssetVersionV2): AssetVersionV2 {
  if (!current) return incoming;
  if (v2AssetCompletenessScore(incoming) < v2AssetCompletenessScore(current)) return current;
  const metadata = {
    ...(current.metadata ?? {}),
    ...(incoming.metadata ?? {}),
  };
  if (isHydratedAssetRecord(incoming)) {
    delete metadata.id_only;
  }
  return {
    ...current,
    ...incoming,
    metadata,
  };
}

function isHydratedAssetRecord(asset: AssetVersionV2 | null | undefined) {
  return Boolean(asset && (asset.public_url || asset.proxy_path || asset.thumbnail_path || asset.file_path));
}
