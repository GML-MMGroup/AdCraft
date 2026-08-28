import { describe, expect, it } from "vitest";

import type {
  AgentPlacementHintV2,
  CanvasBindingV2,
  CanvasNodeV2,
  CanvasPositionV2,
} from "../../../types-v2.ts";
import { agentCanvasNodePlacementSize } from "./nodeGeometry.ts";
import { planProgressiveNodePlacement } from "./agentCanvasProgressivePlacement.ts";

function node(
  nodeId: string,
  nodeType: CanvasNodeV2["node_type"],
  position: CanvasPositionV2 = { x: 0, y: 0 },
): CanvasNodeV2 {
  return {
    node_id: nodeId,
    workflow_id: "workflow-1",
    node_type: nodeType,
    creative_role: nodeType === "text" ? "general_text" : nodeType === "script" ? "script" : `general_${nodeType}` as CanvasNodeV2["creative_role"],
    role_contract_version: "ad-media-role-v1",
    title: nodeId,
    status: "draft",
    summary_prompt: null,
    generation_prompt: null,
    structured_content: {},
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    position,
    revision: 1,
    error: null,
    variation_draft: null,
    created_at: "2026-08-28T00:00:00Z",
    updated_at: "2026-08-28T00:00:00Z",
  };
}

function binding(bindingId: string, sourceNodeId: string, targetNodeId: string): CanvasBindingV2 {
  return {
    binding_id: bindingId,
    workflow_id: "workflow-1",
    source: { kind: "node_output", source_node_id: sourceNodeId },
    target_node_id: targetNodeId,
    input_role: "text_context",
    required: true,
    enabled: true,
    order: 0,
    label: null,
    metadata: {},
    created_at: "2026-08-28T00:00:00Z",
    updated_at: "2026-08-28T00:00:00Z",
  };
}

function hint(
  intent: AgentPlacementHintV2["intent"] = "append_flow",
  anchorNodeId: string | null = null,
  groupKey: string | null = null,
): AgentPlacementHintV2 {
  return { intent, anchor_node_id: anchorNodeId, group_key: groupKey };
}

describe("planProgressiveNodePlacement", () => {
  it("centers a first root node when the canvas has no existing visible nodes", () => {
    const result = planProgressiveNodePlacement({
      nodes: [node("world", "text")],
      bindings: [],
      affectedNodeIds: ["world"],
      placementHints: [hint()],
      viewportCenter: { x: 600, y: 400 },
    });
    const size = agentCanvasNodePlacementSize("text");
    expect(result.positions).toEqual([{
      node_id: "world",
      x: 600 - size.width / 2,
      y: 400 - size.height / 2,
    }]);
    expect(result.levels).toEqual([{ level: 0, nodeIds: ["world"] }]);
  });

  it("uses the planned root position for a child created in the same batch", () => {
    const result = planProgressiveNodePlacement({
      nodes: [node("world", "text"), node("script", "script")],
      bindings: [binding("world-script", "world", "script")],
      affectedNodeIds: ["world", "script"],
      placementHints: [hint(), hint("after_anchor", "world")],
      viewportCenter: { x: 600, y: 400 },
    });
    const world = result.positions.find((item) => item.node_id === "world");
    const script = result.positions.find((item) => item.node_id === "script");
    expect(result.orderedNodeIds).toEqual(["world", "script"]);
    expect(script?.x).toBeGreaterThan(world?.x ?? 0);
    expect(script?.y).toBe(world?.y);
  });

  it("keeps cyclic bindings finite while placing downstream nodes", () => {
    const result = planProgressiveNodePlacement({
      nodes: [node("a", "text"), node("b", "text"), node("c", "image")],
      bindings: [binding("a-b", "a", "b"), binding("b-a", "b", "a"), binding("b-c", "b", "c")],
      affectedNodeIds: ["a", "b", "c"],
      placementHints: [hint(), hint("after_anchor", "a"), hint("after_anchor", "b")],
      viewportCenter: { x: 600, y: 400 },
    });

    expect(result.orderedNodeIds).toEqual(["a", "b", "c"]);
    expect(result.levels).toEqual([
      { level: 0, nodeIds: ["a", "b"] },
      { level: 1, nodeIds: ["c"] },
    ]);
    expect(result.positions).toHaveLength(3);
  });

  it("does not move existing nodes and avoids overlap", () => {
    const result = planProgressiveNodePlacement({
      nodes: [node("existing", "image", { x: 300, y: 240 }), node("new", "video")],
      bindings: [],
      affectedNodeIds: ["new"],
      placementHints: [hint()],
      viewportCenter: { x: 600, y: 400 },
    });
    expect(result.positions.find((item) => item.node_id === "existing")).toBeUndefined();
    expect(result.positions.find((item) => item.node_id === "new")).toBeDefined();
    const placed = result.positions.find((item) => item.node_id === "new")!;
    const existing = node("existing", "image", { x: 300, y: 240 });
    const existingSize = agentCanvasNodePlacementSize("image");
    const newSize = agentCanvasNodePlacementSize("video");
    expect(
      placed.x >= existing.position.x + existingSize.width
        || placed.x + newSize.width <= existing.position.x
        || placed.y >= existing.position.y + existingSize.height
        || placed.y + newSize.height <= existing.position.y,
    ).toBe(true);
  });
});
