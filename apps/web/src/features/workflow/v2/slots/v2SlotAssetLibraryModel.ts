import type { AssetLibraryEntitySummary, AssetLibraryEntityType } from "../../../../types.ts";
import type { AssetVersionV2, WorkflowSlotV2 } from "../../../../types-v2.ts";

export function assetLibraryEntityTypeForV2ImageSlot(slot?: Pick<WorkflowSlotV2, "media_type" | "slot_type" | "item_id"> | null): AssetLibraryEntityType | null {
  if (!slot || slot.media_type !== "image") return null;
  const key = `${slot.slot_type} ${slot.item_id}`.toLowerCase();
  if (key.includes("product_main_image") || key.includes("product")) return "product";
  if (key.includes("character_main_image") || key.includes("character_three_view") || key.includes("character")) return "character";
  if (key.includes("scene_main_image") || key.includes("scene_multi_view_grid") || key.includes("scene")) return "scene";
  if (key.includes("shot_cell") || key.includes("storyboard")) return "storyboard_shot";
  return null;
}

export function v2ImageSlotMatchesAssetLibraryEntity(slot: WorkflowSlotV2, entity: AssetLibraryEntitySummary) {
  const expectedType = assetLibraryEntityTypeForV2ImageSlot(slot);
  return Boolean(expectedType && entity.entity_type === expectedType);
}

export function v2ImageSlotLibrarySaveDisplayName(slot: WorkflowSlotV2, asset?: Pick<AssetVersionV2, "semantic_type"> | null) {
  return humanizeSlotLabel(asset?.semantic_type || slot.slot_type || slot.slot_id);
}

function humanizeSlotLabel(value: string) {
  const normalized = value.trim().replace(/[_-]+/g, " ");
  return normalized ? normalized.replace(/\b\w/g, (letter) => letter.toUpperCase()) : "Image Slot";
}
