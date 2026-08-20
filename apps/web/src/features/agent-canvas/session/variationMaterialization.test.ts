import { describe, expect, it } from "vitest";

import type { CanvasVariationMaterializeResponseV2 } from "../../../types-v2.ts";
import { variationMaterializationPlacement } from "./variationMaterialization.ts";

function response(
  overrides: Partial<CanvasVariationMaterializeResponseV2> = {},
): CanvasVariationMaterializeResponseV2 {
  return {
    workflow_id: "workflow-1",
    workflow_revision: 4,
    source_node_id: "node-source",
    sibling_node: { node_id: "node-main" } as CanvasVariationMaterializeResponseV2["sibling_node"],
    copied_binding_ids: [],
    run: null,
    run_error: null,
    placement_hint: {
      intent: "right_sibling",
      anchor_node_id: "node-source",
      group_key: null,
    },
    created_node_ids: [],
    created_binding_ids: [],
    placement_hints: [],
    ...overrides,
  };
}

describe("variationMaterializationPlacement", () => {
  it("uses the complete canonical node and placement lists", () => {
    const result = variationMaterializationPlacement(response({
      created_node_ids: ["node-main", "node-turnaround"],
      placement_hints: [{
        intent: "right_sibling",
        anchor_node_id: "node-source",
        group_key: "pair-1",
      }, {
        intent: "right_sibling",
        anchor_node_id: "node-main",
        group_key: "pair-1",
      }],
    }));

    expect(result.nodeIds).toEqual(["node-main", "node-turnaround"]);
    expect(result.placementHints).toHaveLength(2);
  });

  it("falls back to the legacy sibling fields for older responses", () => {
    const result = variationMaterializationPlacement(response());

    expect(result.nodeIds).toEqual(["node-main"]);
    expect(result.placementHints).toEqual([{
      intent: "right_sibling",
      anchor_node_id: "node-source",
      group_key: null,
    }]);
  });
});
