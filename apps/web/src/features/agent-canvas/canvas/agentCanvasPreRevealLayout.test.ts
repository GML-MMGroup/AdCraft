import { describe, expect, it } from "vitest";

import type {
  CanvasBindingV2,
  CanvasNodeV2,
  CanvasPositionV2,
} from "../../../types-v2.ts";
import {
  agentCanvasLayoutNodeFromCanvasNode,
  computeAgentCanvasAutoLayout,
  enabledNodeLayoutEdges,
} from "./canvasAutoLayout.ts";
import { buildAgentCanvasPreRevealLayout } from "./agentCanvasPreRevealLayout.ts";

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

describe("buildAgentCanvasPreRevealLayout", () => {
  it("returns the full automatic layout before affected nodes can be revealed", () => {
    const nodes = [
      node("root", "text"),
      node("existing", "image", { x: 820, y: 20 }),
      node("created", "video"),
    ];
    const bindings = [binding("root-created", "root", "created")];
    const result = buildAgentCanvasPreRevealLayout({
      nodes,
      bindings,
      affectedNodeIds: ["created"],
    });
    const visibleNodeIds = new Set(nodes.map((item) => item.node_id));
    const expected = computeAgentCanvasAutoLayout(
      nodes.map((item) => agentCanvasLayoutNodeFromCanvasNode(item)),
      enabledNodeLayoutEdges(bindings, visibleNodeIds),
    );

    expect(result.positions).toEqual(expected.positions);
    expect(result.revealPlan.positions).toEqual([
      expected.positions.find((position) => position.node_id === "created"),
    ]);
    expect(result.revealPlan.orderedNodeIds).toEqual(["created"]);
    expect(result.positions.find((position) => position.node_id === "created")).not.toEqual({
      node_id: "created",
      x: 0,
      y: 0,
    });
  });

  it("orders affected nodes by graph level while preserving all persisted positions", () => {
    const nodes = [node("root", "text"), node("child", "script"), node("grandchild", "image")];
    const bindings = [
      binding("root-child", "root", "child"),
      binding("child-grandchild", "child", "grandchild"),
    ];
    const result = buildAgentCanvasPreRevealLayout({
      nodes,
      bindings,
      affectedNodeIds: ["grandchild", "child", "root"],
    });

    expect(result.positions).toHaveLength(3);
    expect(result.revealPlan.orderedNodeIds).toEqual(["root", "child", "grandchild"]);
    expect(result.revealPlan.levels).toEqual([
      { level: 0, nodeIds: ["root"] },
      { level: 1, nodeIds: ["child"] },
      { level: 2, nodeIds: ["grandchild"] },
    ]);
  });

  it("deduplicates repeated receipt node IDs without dropping their persisted coordinates", () => {
    const nodes = [node("root", "text"), node("child", "image")];
    const result = buildAgentCanvasPreRevealLayout({
      nodes,
      bindings: [binding("root-child", "root", "child")],
      affectedNodeIds: ["child", "child", "root"],
    });

    expect(result.positions).toHaveLength(2);
    expect(result.revealPlan.positions).toHaveLength(2);
    expect(result.revealPlan.orderedNodeIds).toEqual(["root", "child"]);
  });
});
