import { isV2WorkflowId, isWorkflowV2Graph } from "../../../workflow-v2/pageAdapter";
import { dedupeV2AssetVersions } from "./v2AssetViewModel";
import {
  v2RegionAssetVersionsForNode,
  v2RegionItemsForNode,
  v2RegionSlotsForNode,
} from "./v2RegionNode";
import { uploadedAssetFromV2AssetVersion } from "./v2AssetViewModel";
import type { ResolvedNodeInputs, WorkflowGraph, WorkflowNodeVersion } from "../../../types";
import type { AssetVersionV2, SlotVersionsResponseV2, WorkflowItemV2, WorkflowSlotV2, WorkflowV2 } from "../../../types-v2";

export function isCurrentWorkflowV2(workflow: WorkflowGraph | null | undefined, modelIsV2: boolean) {
  const currentWorkflowId = workflow?.workflow_id ?? null;
  return modelIsV2 || isWorkflowV2Graph(workflow) || isV2WorkflowId(currentWorkflowId);
}

export function assertV1ApiAllowedForWorkflow(workflowId: string, operation: string, isV2: boolean) {
  if (isV2WorkflowId(workflowId) || isV2) {
    throw new Error(`Blocked V1 ${operation} for V2 workflow ${workflowId} matching adwf_v2_ or adapted V2 graph.`);
  }
}

export function v2NodeForDebug(workflow: WorkflowGraph | null | undefined, nodeId: string) {
  return workflow?.nodes.find((node) => node.id === nodeId || node.node_type === nodeId) ?? null;
}

export function v2ItemsForDebug(workflow: WorkflowGraph | null | undefined, workflowV2: WorkflowV2 | null | undefined, nodeId: string): WorkflowItemV2[] {
  const rawItems = workflowV2?.items.filter((item) => item.node_id === nodeId && item.lifecycle_state !== "archived") ?? [];
  if (rawItems.length) return rawItems;
  const node = v2NodeForDebug(workflow, nodeId);
  return node ? v2RegionItemsForNode(node) : [];
}

export function v2SlotsForDebug(workflow: WorkflowGraph | null | undefined, workflowV2: WorkflowV2 | null | undefined, nodeId: string): WorkflowSlotV2[] {
  const items = v2ItemsForDebug(workflow, workflowV2, nodeId);
  const itemIds = new Set(items.map((item) => item.item_id));
  const rawSlots =
    workflowV2?.slots.filter((slot) => slot.node_id === nodeId || itemIds.has(slot.item_id)) ?? [];
  if (rawSlots.length) return rawSlots;
  const node = v2NodeForDebug(workflow, nodeId);
  return node ? v2RegionSlotsForNode(node) : [];
}

export function v2AssetVersionsForDebug(workflow: WorkflowGraph | null | undefined, workflowV2: WorkflowV2 | null | undefined, nodeId: string): AssetVersionV2[] {
  const rawAssets = workflowV2?.asset_versions.filter((asset) => asset.node_id === nodeId) ?? [];
  const node = v2NodeForDebug(workflow, nodeId);
  const nodeAssets = node ? v2RegionAssetVersionsForNode(node) : [];
  return dedupeV2AssetVersions([...rawAssets, ...nodeAssets]);
}

export function buildV2ResolvedInputs(args: {
  workflowId: string;
  nodeId: string;
  items: WorkflowItemV2[];
  slots: WorkflowSlotV2[];
  assetVersions: AssetVersionV2[];
  runtime: unknown;
}): ResolvedNodeInputs {
  const referenceIds = new Set<string>();
  args.slots.forEach((slot) => {
    [...(slot.implicit_reference_ids ?? []), ...(slot.explicit_reference_ids ?? []), ...(slot.media_prompt_asset_ids ?? [])].forEach((id) => referenceIds.add(id));
  });
  const resolvedAssets = args.assetVersions
    .filter((asset) => referenceIds.has(asset.asset_id) || referenceIds.has(asset.version_id))
    .map(uploadedAssetFromV2AssetVersion);
  return {
    workflow_id: args.workflowId,
    node_id: args.nodeId,
    resolved_input_context: {
      v2_items: args.items,
      v2_slots: args.slots,
      v2_runtime: args.runtime,
      v2_debug_source: "workflow_v2_adapter",
    },
    resolved_input_assets: resolvedAssets,
    source_mappings: args.slots.flatMap((slot) =>
      [...(slot.implicit_reference_ids ?? []), ...(slot.explicit_reference_ids ?? []), ...(slot.media_prompt_asset_ids ?? [])].map((assetId) => ({
        source_type: "workflow_v2_slot_reference",
        node_id: args.nodeId,
        item_id: slot.item_id,
        slot_id: slot.slot_id,
        asset_id: assetId,
      })),
    ),
    missing_inputs: args.slots
      .filter((slot) => slot.required && (slot.status === "empty" || slot.status === "blocked"))
      .map((slot) => ({
        key: slot.slot_id,
        input_key: slot.slot_type,
        reason: slot.status,
        message: slot.status === "blocked" ? "V2 slot is blocked by upstream dependencies." : "V2 slot is empty.",
        source_node_id: slot.node_id,
        required: true,
      })),
  };
}

export function buildV2NodeVersions(args: {
  nodeId: string;
  slots: WorkflowSlotV2[];
  assetVersions: AssetVersionV2[];
  fetched: Array<SlotVersionsResponseV2 | null>;
}) {
  const versions = dedupeV2AssetVersions([
    ...args.assetVersions,
    ...args.fetched.flatMap((response) => response?.versions ?? []),
  ]).map((asset, index): WorkflowNodeVersion => ({
    version: index + 1,
    node_run_id: asset.asset_id,
    status: asset.status ?? asset.quality_status ?? "available",
    created_at: asset.created_at,
    output_hash: asset.version_id,
    active: args.slots.some((slot) => slot.selected_asset_id === asset.asset_id || slot.selected_asset_id === asset.version_id),
  }));
  return { node_id: args.nodeId, versions };
}
