import type { WorkflowMediaTypeV2 } from "../types-v2.ts";
import { freeAbsorbTargetsForMedia } from "./agentRouting.ts";

export function absorbTargetsForFreeAsset(mediaType: WorkflowMediaTypeV2) {
  return freeAbsorbTargetsForMedia(mediaType);
}

export type V2DeleteActionKind = "selected_slot_asset" | "working_version" | "history_entry" | "item" | "shot" | "timeline_clip" | "reference_relation" | "free_node";

export function v2DeleteEffectSummary(kind: V2DeleteActionKind) {
  if (kind === "selected_slot_asset") return "Clears the selected slot relation and keeps the asset file.";
  if (kind === "working_version") return "Clears the working version relation and keeps the selected asset.";
  if (kind === "history_entry") return "Removes the history relation and keeps the asset file.";
  if (kind === "timeline_clip") return "Removes the timeline clip relation and keeps the source asset.";
  if (kind === "reference_relation") return "Removes the reference relation and keeps the source asset.";
  if (kind === "free_node") return "Archives the free node and keeps generated asset records.";
  return "Archives the item and keeps asset version records.";
}
