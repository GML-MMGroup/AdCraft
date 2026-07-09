import type { WorkflowItemV2 } from "../../../types-v2.ts";
import type { UploadedAsset, WorkflowNode } from "../../../types.ts";
import { v2RegionSlotsForNode } from "./v2RegionNode.ts";

export function isV2StoryboardShotItem(item: WorkflowItemV2) {
  return item.item_type === "shot" || Boolean(item.shot_id);
}

export function v2EditableItemPrompt(item: WorkflowItemV2) {
  return isV2StoryboardShotItem(item)
    ? item.shot_summary_prompt ?? item.item_prompt ?? item.description ?? ""
    : item.item_prompt ?? item.description ?? "";
}

export function v2ItemPromptLabel(item: WorkflowItemV2) {
  return isV2StoryboardShotItem(item) ? "Shot summary prompt" : "Item prompt";
}

export function v2FreeGenerationMediaType(node: WorkflowNode, selectedAsset?: UploadedAsset | null) {
  const v2Node = node.metadata?.v2_node && typeof node.metadata.v2_node === "object" ? node.metadata.v2_node as { resolved_media_type?: unknown } : null;
  const resolvedMediaType = stringFromUnknown(v2Node?.resolved_media_type);
  if (resolvedMediaType) return resolvedMediaType;
  const slotMediaType = v2RegionSlotsForNode(node)[0]?.media_type;
  if (slotMediaType && slotMediaType !== "text") return slotMediaType;
  const assetMediaType = stringFromUnknown(selectedAsset?.media_type) || stringFromUnknown(selectedAsset?.asset_type);
  if (assetMediaType) return assetMediaType;
  return null;
}

export function promptFromNodePatch(patch: Partial<WorkflowNode>) {
  return (
    stringFromUnknown(patch.input_context?.user_prompt) ||
    stringFromUnknown(patch.prompt) ||
    stringFromUnknown(patch.override_prompt) ||
    null
  );
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}
