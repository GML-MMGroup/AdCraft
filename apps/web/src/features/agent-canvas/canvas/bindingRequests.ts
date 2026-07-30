import type {
  CanvasBindingCreateRequestV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";
import {
  bindingKindForSourceNode,
  inputRoleForSourceNode,
} from "./canvasGraphModel.ts";

export function bindingRequestForNode(
  source: CanvasNodeV2,
  targetNodeId: string,
  displayOrder: number,
): CanvasBindingCreateRequestV2 {
  return {
    source: { kind: "node", node_id: source.node_id },
    target_node_id: targetNodeId,
    binding_kind: bindingKindForSourceNode(source),
    input_role: inputRoleForSourceNode(source),
    required: true,
    display_order: displayOrder,
  };
}

export function bindingRequestForImageAsset(
  assetId: string,
  targetNodeId: string,
  displayOrder: number,
): CanvasBindingCreateRequestV2 {
  return {
    source: { kind: "image_asset", asset_id: assetId },
    target_node_id: targetNodeId,
    binding_kind: "image_reference",
    input_role: "visual_reference",
    required: true,
    display_order: displayOrder,
  };
}
