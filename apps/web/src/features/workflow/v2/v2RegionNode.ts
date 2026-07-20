import type { AssetVersionV2, WorkflowItemV2, WorkflowSlotV2 } from "../../../types-v2.ts";
import type { WorkflowNode } from "../../../types.ts";
import { getWorkflowNodeType } from "../canvas/workflowNodeModel.ts";

export function v2RegionItemsForNode(node: WorkflowNode): WorkflowItemV2[] {
  const items = arrayFromUnknown(node.metadata?.v2_items) ?? arrayFromUnknown(node.input_context?.v2_items);
  return items ? items.filter(isWorkflowItemV2) : [];
}

export function v2RegionSlotsForNode(node: WorkflowNode): WorkflowSlotV2[] {
  const slots = arrayFromUnknown(node.metadata?.v2_slots) ?? arrayFromUnknown(node.input_context?.v2_slots);
  if (slots) return slots.filter(isWorkflowSlotV2);
  return v2RegionItemsForNode(node).flatMap((item) => (Array.isArray(item.slots) ? item.slots.filter(isWorkflowSlotV2) : []));
}

export function v2RegionAssetVersionsForNode(node: WorkflowNode): AssetVersionV2[] {
  const assetVersions = arrayFromUnknown(node.metadata?.v2_asset_versions) ?? arrayFromUnknown(node.input_context?.v2_asset_versions);
  return assetVersions ? assetVersions.filter(isAssetVersionV2) : [];
}

export function isV2RegionWorkflowNode(node: WorkflowNode) {
  return node.metadata?.workflow_schema_version === 2 || v2RegionItemsForNode(node).length > 0 || v2RegionSlotsForNode(node).length > 0;
}

export function isV2InlineRegionNode(node: WorkflowNode) {
  const nodeType = getWorkflowNodeType(node);
  return ["product-generation", "character-generation", "scene-generation"].includes(nodeType) && isV2RegionWorkflowNode(node);
}

function arrayFromUnknown(value: unknown): unknown[] | null {
  return Array.isArray(value) ? value : null;
}

function isWorkflowItemV2(value: unknown): value is WorkflowItemV2 {
  return Boolean(value && typeof value === "object" && typeof (value as { item_id?: unknown }).item_id === "string");
}

function isWorkflowSlotV2(value: unknown): value is WorkflowSlotV2 {
  return Boolean(value && typeof value === "object" && typeof (value as { slot_id?: unknown }).slot_id === "string");
}

function isAssetVersionV2(value: unknown): value is AssetVersionV2 {
  return Boolean(value && typeof value === "object" && typeof (value as { asset_id?: unknown }).asset_id === "string");
}
