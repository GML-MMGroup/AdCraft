import type { CanvasTargetReference } from "../types.ts";
import type { V2ChatActionMode, WorkflowItemV2, WorkflowMediaTypeV2, WorkflowSlotV2, WorkflowV2ChatTarget } from "../types-v2.ts";

type SlotTargetInput = Pick<WorkflowSlotV2, "node_id" | "item_id" | "slot_id">;
type ItemTargetInput = Pick<WorkflowItemV2, "node_id" | "item_id">;

export type V2ChatTargetBuildInput = {
  explicitTarget?: CanvasTargetReference | WorkflowV2ChatTarget | null;
  explicitAssetId?: string | null;
  fallbackSlot?: SlotTargetInput | null;
  fallbackItem?: ItemTargetInput | null;
  fallbackNodeId?: string | null;
};

export function buildV2ChatTarget(input: V2ChatTargetBuildInput): WorkflowV2ChatTarget {
  const explicitTarget = input.explicitTarget;
  if (explicitTarget?.target_type === "asset" && explicitTarget.asset_id) {
    return { target_type: "asset", asset_id: explicitTarget.asset_id };
  }
  if (input.explicitAssetId) {
    return { target_type: "asset", asset_id: input.explicitAssetId };
  }
  if (explicitTarget?.target_type === "slot" && explicitTarget.slot_id) {
    return {
      target_type: "slot",
      node_id: explicitTarget.node_id ?? input.fallbackNodeId ?? null,
      item_id: explicitTarget.item_id ?? input.fallbackItem?.item_id ?? null,
      slot_id: explicitTarget.slot_id,
    };
  }
  if (input.fallbackSlot) {
    return {
      target_type: "slot",
      node_id: input.fallbackSlot.node_id,
      item_id: input.fallbackSlot.item_id,
      slot_id: input.fallbackSlot.slot_id,
    };
  }
  if (explicitTarget?.target_type === "item" && explicitTarget.item_id) {
    return {
      target_type: "item",
      node_id: explicitTarget.node_id ?? input.fallbackNodeId ?? null,
      item_id: explicitTarget.item_id,
    };
  }
  if (input.fallbackItem) {
    return {
      target_type: "item",
      node_id: input.fallbackItem.node_id,
      item_id: input.fallbackItem.item_id,
    };
  }
  if (explicitTarget?.target_type === "node" && explicitTarget.node_id) {
    return { target_type: "node", node_id: explicitTarget.node_id };
  }
  return { target_type: "node", node_id: input.fallbackNodeId ?? null };
}

export function v2ChatActionMode(prompt: string): V2ChatActionMode {
  return /重新生成|重新出图|重新生成视频|重生|再来一版|再来|生成|generate|regenerate|rerun|run/i.test(prompt)
    ? "revise_and_generate"
    : "revise_prompt";
}

export function freeAbsorbTargetsForMedia(mediaType: WorkflowMediaTypeV2 | string | null | undefined) {
  if (mediaType === "image") return ["product-generation", "character-generation", "scene-generation", "storyboard"];
  if (mediaType === "audio") return ["bgm"];
  if (mediaType === "video") return ["final-composition"];
  return [];
}

export function isAllowedFreeAbsorbTarget(mediaType: WorkflowMediaTypeV2 | string | null | undefined, targetNodeId: string | null | undefined) {
  return Boolean(targetNodeId && freeAbsorbTargetsForMedia(mediaType).includes(targetNodeId));
}
