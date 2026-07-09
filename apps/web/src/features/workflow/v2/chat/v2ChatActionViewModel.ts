import type { CanvasTargetReference } from "../../../../types";
import type { V2AssetLocatorResponse, V2ChatActionResponse, WorkflowV2ChatTarget } from "../../../../types-v2";

export function v2ChatActionAttachmentsFromLocators(resolvedLocators: V2AssetLocatorResponse[]) {
  return resolvedLocators
    .map((item) => ({
      source_asset_id: item.asset.asset_id,
      semantic_type: item.asset.semantic_type || null,
      use_as_prompt: true,
    }))
    .filter((item) => Boolean(item.source_asset_id));
}

export function v2ChatActionResponseStartedGeneration(response: V2ChatActionResponse) {
  return response.action_mode === "revise_and_generate" || response.executed_slot_ids.length > 0 || response.asset_ids.length > 0 || response.version_ids.length > 0;
}

export function v2ChatTargetsFromCanvasReferences(references: CanvasTargetReference[] | undefined): WorkflowV2ChatTarget[] {
  return (references ?? [])
    .map((reference): WorkflowV2ChatTarget | null => {
      if (reference.target_type === "asset" && reference.asset_id) return { target_type: "asset", asset_id: reference.asset_id };
      if (reference.target_type === "slot" && reference.slot_id) return { target_type: "slot", node_id: reference.node_id ?? null, item_id: reference.item_id ?? null, slot_id: reference.slot_id };
      if (reference.target_type === "item" && reference.item_id) return { target_type: "item", node_id: reference.node_id ?? null, item_id: reference.item_id };
      if (reference.target_type === "node" && reference.node_id) return { target_type: "node", node_id: reference.node_id };
      return null;
    })
    .filter((reference): reference is WorkflowV2ChatTarget => Boolean(reference));
}
