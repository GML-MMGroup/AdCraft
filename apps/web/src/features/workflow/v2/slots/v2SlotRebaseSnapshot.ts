import type { WorkflowGraph, WorkflowNode } from "../../../../types.ts";
import type { WorkflowItemV2, WorkflowSlotV2, WorkflowV2 } from "../../../../types-v2.ts";
import { isWorkflowV2Graph } from "../../../../workflowSchema.ts";

export type V2SlotRebaseSnapshot = {
  slots: WorkflowSlotV2[];
  archivedSlotIds: string[];
  removedSlotIds: string[];
  authoritative: boolean;
};

/** Builds an authoritative V2 slot snapshot from either API data or its graph adapter. */
export function deriveV2SlotRebaseSnapshot(
  source: WorkflowV2 | WorkflowGraph | null | undefined,
  partialSlots: WorkflowSlotV2[] = [],
): V2SlotRebaseSnapshot {
  if (isWorkflowV2(source)) return snapshotFromItemsAndSlots(source.items, source.slots, true);
  if (source && isWorkflowV2Graph(source)) {
    const items = uniqueItemsById(source.nodes.flatMap(v2ItemsForGraphNode));
    const slots = uniqueSlotsById(source.nodes.flatMap(v2SlotsForGraphNode));
    return snapshotFromItemsAndSlots(items, slots, true);
  }
  return { slots: partialSlots, archivedSlotIds: [], removedSlotIds: [], authoritative: false };
}

function snapshotFromItemsAndSlots(items: WorkflowItemV2[], slots: WorkflowSlotV2[], authoritative: boolean): V2SlotRebaseSnapshot {
  const archivedItemIds = new Set(items.filter((item) => item.lifecycle_state === "archived").map((item) => item.item_id));
  return {
    slots: slots.filter((slot) => !archivedItemIds.has(slot.item_id)),
    archivedSlotIds: slots.filter((slot) => archivedItemIds.has(slot.item_id)).map((slot) => slot.slot_id),
    removedSlotIds: [],
    authoritative,
  };
}

function v2ItemsForGraphNode(node: WorkflowNode): WorkflowItemV2[] {
  return arrayFromNode(node, "v2_items").filter(isWorkflowItemV2);
}

function v2SlotsForGraphNode(node: WorkflowNode): WorkflowSlotV2[] {
  const slots = arrayFromNode(node, "v2_slots").filter(isWorkflowSlotV2);
  return slots.length ? slots : v2ItemsForGraphNode(node).flatMap((item) => Array.isArray(item.slots) ? item.slots.filter(isWorkflowSlotV2) : []);
}

function arrayFromNode(node: WorkflowNode, key: "v2_items" | "v2_slots"): unknown[] {
  const input = node.input_context?.[key];
  if (Array.isArray(input)) return input;
  const metadata = node.metadata?.[key];
  return Array.isArray(metadata) ? metadata : [];
}

function uniqueItemsById(values: WorkflowItemV2[]): WorkflowItemV2[] {
  return [...new Map(values.map((value) => [value.item_id, value])).values()];
}

function uniqueSlotsById(values: WorkflowSlotV2[]): WorkflowSlotV2[] {
  return [...new Map(values.map((value) => [value.slot_id, value])).values()];
}

function isWorkflowV2(value: WorkflowV2 | WorkflowGraph | null | undefined): value is WorkflowV2 {
  return Boolean(value && "items" in value && Array.isArray(value.items) && "slots" in value && Array.isArray(value.slots));
}

function isWorkflowItemV2(value: unknown): value is WorkflowItemV2 {
  return Boolean(value && typeof value === "object" && typeof (value as { item_id?: unknown }).item_id === "string");
}

function isWorkflowSlotV2(value: unknown): value is WorkflowSlotV2 {
  return Boolean(value && typeof value === "object" && typeof (value as { slot_id?: unknown }).slot_id === "string");
}
