import type {
  AgentPlacementHintV2,
  CanvasVariationMaterializeResponseV2,
} from "../../../types-v2.ts";

export function variationMaterializationPlacement(
  response: CanvasVariationMaterializeResponseV2,
): {
  nodeIds: string[];
  placementHints: AgentPlacementHintV2[];
} {
  return {
    nodeIds: response.created_node_ids.length
      ? response.created_node_ids
      : [response.sibling_node.node_id],
    placementHints: response.placement_hints.length
      ? response.placement_hints
      : [response.placement_hint],
  };
}
