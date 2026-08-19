import { describe, expect, it } from "vitest";

import type { CanvasBindingV2, CanvasLayoutPositionV2, CanvasPositionV2 } from "../../../types-v2.ts";
import type { AgentCanvasFlowNode } from "./AgentCanvasNode.tsx";
import type { AgentCanvasNodeSize } from "./nodeGeometry.ts";
import { agentCanvasNodePlacementSize } from "./nodeGeometry.ts";
import {
  agentCanvasLayoutNodeFromFlowNode,
  computeAgentCanvasAutoLayout,
  enabledNodeLayoutEdges,
  type AgentCanvasLayoutEdge,
  type AgentCanvasLayoutNode,
  type AgentCanvasAutoLayoutResult,
} from "./canvasAutoLayout.ts";

const DEFAULT_SIZE: AgentCanvasNodeSize = { width: 272, height: 184 };

function flowNode({
  nodeType,
  measured,
}: {
  nodeType: AgentCanvasFlowNode["data"]["node"]["node_type"];
  measured?: AgentCanvasFlowNode["measured"];
}): AgentCanvasFlowNode {
  return {
    id: "flow-node",
    type: "agentCanvas",
    position: { x: 32, y: 48 },
    measured,
    data: {
      node: { node_type: nodeType } as AgentCanvasFlowNode["data"]["node"],
      asset: null,
    },
  } as AgentCanvasFlowNode;
}

function node(
  id: string,
  size: AgentCanvasNodeSize = DEFAULT_SIZE,
  position: CanvasPositionV2 = { x: 0, y: 0 },
): AgentCanvasLayoutNode {
  return { id, position, size };
}

function edge(id: string, source: string, target: string): AgentCanvasLayoutEdge {
  return { id, source, target };
}

function binding(
  id: string,
  source: string,
  target: string,
  overrides: Partial<CanvasBindingV2> = {},
): CanvasBindingV2 {
  return {
    binding_id: id,
    workflow_id: "workflow-1",
    source: { kind: "node_output", source_node_id: source },
    target_node_id: target,
    input_role: "image_reference",
    required: false,
    enabled: true,
    order: 0,
    label: null,
    metadata: {},
    created_at: "2026-08-18T00:00:00Z",
    updated_at: "2026-08-18T00:00:00Z",
    ...overrides,
  };
}

function assetBinding(id: string, assetId: string, target: string): CanvasBindingV2 {
  return binding(id, "unused", target, {
    source: { kind: "image_asset", source_asset_id: assetId },
  });
}

function positionsById(positions: CanvasLayoutPositionV2[]): Record<string, CanvasPositionV2> {
  return Object.fromEntries(positions.map((position) => [position.node_id, position]));
}

function overlappingPairs(
  positions: CanvasLayoutPositionV2[],
  sizes: ReadonlyMap<string, AgentCanvasNodeSize>,
): string[] {
  const pairs: string[] = [];
  for (let leftIndex = 0; leftIndex < positions.length; leftIndex += 1) {
    const left = positions[leftIndex]!;
    const leftSize = sizes.get(left.node_id)!;
    for (let rightIndex = leftIndex + 1; rightIndex < positions.length; rightIndex += 1) {
      const right = positions[rightIndex]!;
      const rightSize = sizes.get(right.node_id)!;
      if (
        left.x < right.x + rightSize.width
        && left.x + leftSize.width > right.x
        && left.y < right.y + rightSize.height
        && left.y + leftSize.height > right.y
      ) {
        pairs.push([left.node_id, right.node_id].sort().join(":"));
      }
    }
  }
  return pairs;
}

function assertCompleteIntegerBounds(
  result: AgentCanvasAutoLayoutResult,
  nodes: readonly AgentCanvasLayoutNode[],
): void {
  const sizes = new Map(nodes.map((item) => [item.id, item.size]));
  expect(result.positions.map((position) => position.node_id)).toEqual(
    [...nodes].map((item) => item.id).sort(),
  );
  expect(result.positions.every((position) => Number.isInteger(position.x) && Number.isInteger(position.y)))
    .toBe(true);
  expect(overlappingPairs(result.positions, sizes)).toEqual([]);
  result.positions.forEach((position) => {
    const size = sizes.get(position.node_id)!;
    expect(position.x).toBeGreaterThanOrEqual(result.bounds.x);
    expect(position.y).toBeGreaterThanOrEqual(result.bounds.y);
    expect(position.x + size.width).toBeLessThanOrEqual(result.bounds.x + result.bounds.width);
    expect(position.y + size.height).toBeLessThanOrEqual(result.bounds.y + result.bounds.height);
  });
}

describe("agentCanvasLayoutNodeFromFlowNode", () => {
  it("prefers current React Flow measurements over placement fallbacks", () => {
    const result = agentCanvasLayoutNodeFromFlowNode(flowNode({
      nodeType: "script",
      measured: { width: 418, height: 512 },
    }));

    expect(result).toEqual({
      id: "flow-node",
      position: { x: 32, y: 48 },
      size: { width: 418, height: 512 },
    });
  });

  it("uses the safe Script placement size before React Flow measures the node", () => {
    expect(agentCanvasLayoutNodeFromFlowNode(flowNode({ nodeType: "script" })).size)
      .toEqual(agentCanvasNodePlacementSize("script"));
  });
});

describe("enabledNodeLayoutEdges", () => {
  it("uses only enabled persisted node-output bindings", () => {
    const edges = enabledNodeLayoutEdges([
      binding("ab", "a", "b", { enabled: true }),
      binding("bc", "b", "c", { enabled: false }),
      assetBinding("asset-c", "asset-1", "c"),
      binding("external", "outside", "a"),
      binding("hidden", "a", "outside"),
    ], new Set(["a", "b", "c"]));

    expect(edges).toEqual([{ id: "ab", source: "a", target: "b" }]);
  });

  it("sorts participating bindings by stable binding ID", () => {
    expect(enabledNodeLayoutEdges([
      binding("z", "a", "b"),
      binding("a", "a", "b"),
    ], new Set(["a", "b"])).map((item) => item.id)).toEqual(["a", "z"]);
  });
});

describe("computeAgentCanvasAutoLayout", () => {
  it("returns an empty result for an empty canvas", () => {
    expect(computeAgentCanvasAutoLayout([], [])).toEqual({
      positions: [],
      bounds: { x: 120, y: 120, width: 0, height: 0 },
    });
  });

  it("places a single node at the normalized top-left origin", () => {
    const result = computeAgentCanvasAutoLayout([node("only", { width: 180, height: 360 })], []);

    expect(result).toEqual({
      positions: [{ node_id: "only", x: 120, y: 120 }],
      bounds: { x: 120, y: 120, width: 180, height: 360 },
    });
  });

  it("places dependencies in left-to-right ranks", () => {
    const result = computeAgentCanvasAutoLayout(
      [node("a"), node("b"), node("c")],
      [edge("ab", "a", "b"), edge("bc", "b", "c")],
    );
    const byId = positionsById(result.positions);

    expect(byId.a!.x).toBeLessThan(byId.b!.x);
    expect(byId.b!.x).toBeLessThan(byId.c!.x);
  });

  it("does not overlap differently sized nodes", () => {
    const nodes = [
      node("portrait", { width: 180, height: 360 }),
      node("script", { width: 248, height: 500 }),
      node("video", { width: 272, height: 184 }),
    ];
    const sizes = new Map(nodes.map((item) => [item.id, item.size]));
    const result = computeAgentCanvasAutoLayout(nodes, [
      edge("pv", "portrait", "video"),
      edge("sv", "script", "video"),
    ]);

    expect(overlappingPairs(result.positions, sizes)).toEqual([]);
  });

  it("keeps branches and merge points in their directed ranks", () => {
    const result = computeAgentCanvasAutoLayout(
      [node("source"), node("left"), node("right"), node("merge")],
      [
        edge("source-left", "source", "left"),
        edge("source-right", "source", "right"),
        edge("left-merge", "left", "merge"),
        edge("right-merge", "right", "merge"),
      ],
    );
    const byId = positionsById(result.positions);

    expect(byId.source!.x).toBeLessThan(byId.left!.x);
    expect(byId.source!.x).toBeLessThan(byId.right!.x);
    expect(byId.left!.x).toBeLessThan(byId.merge!.x);
    expect(byId.right!.x).toBeLessThan(byId.merge!.x);
  });

  it("keeps disconnected connected components separate", () => {
    const nodes = [node("a"), node("b"), node("c"), node("d")];
    const result = computeAgentCanvasAutoLayout(nodes, [edge("ab", "a", "b"), edge("cd", "c", "d")]);
    const byId = positionsById(result.positions);

    expect(byId.c!.y).toBeGreaterThanOrEqual(byId.a!.y + DEFAULT_SIZE.height + 160);
    assertCompleteIntegerBounds(result, nodes);
  });

  it("packs isolated nodes below every connected component", () => {
    const nodes = [node("a"), node("b"), node("c"), node("isolated")];
    const result = computeAgentCanvasAutoLayout(
      nodes,
      [edge("ab", "a", "b"), edge("bc", "b", "c")],
    );
    const byId = positionsById(result.positions);
    const connectedBottom = Math.max(
      byId.a!.y + DEFAULT_SIZE.height,
      byId.b!.y + DEFAULT_SIZE.height,
      byId.c!.y + DEFAULT_SIZE.height,
    );

    expect(byId.isolated!.y).toBeGreaterThanOrEqual(connectedBottom + 220);
    assertCompleteIntegerBounds(result, nodes);
  });

  it("uses pre-layout reading order when arranging isolated nodes", () => {
    const nodes = [
      node("lower", DEFAULT_SIZE, { x: 0, y: 200 }),
      node("top-right", DEFAULT_SIZE, { x: 300, y: 0 }),
      node("top-left", DEFAULT_SIZE, { x: 0, y: 0 }),
    ];
    const result = computeAgentCanvasAutoLayout(nodes, []);
    const byId = positionsById(result.positions);

    expect(byId["top-left"]!.y).toBe(byId["top-right"]!.y);
    expect(byId["top-left"]!.x).toBeLessThan(byId["top-right"]!.x);
    expect(byId.lower!.y).toBeGreaterThan(byId["top-left"]!.y);
    assertCompleteIntegerBounds(result, nodes);
  });

  it("wraps all-isolated nodes within the configured row width", () => {
    const nodes = Array.from({ length: 4 }, (_, index) => node(`node-${index + 1}`, {
      width: 300,
      height: 184,
    }, { x: index * 10, y: 0 }));
    const result = computeAgentCanvasAutoLayout(nodes, [], { isolatedRowWidth: 650 });

    expect(new Set(result.positions.map((position) => position.y)).size).toBeGreaterThan(1);
    assertCompleteIntegerBounds(result, nodes);
  });

  it("handles historical cycles without changing the returned directed edge model", () => {
    const nodes = [node("a"), node("b"), node("c")];
    const result = computeAgentCanvasAutoLayout(nodes, [
      edge("ab", "a", "b"),
      edge("bc", "b", "c"),
      edge("ca", "c", "a"),
    ]);

    assertCompleteIntegerBounds(result, nodes);
  });

  it("returns identical coordinates for identical shuffled input", () => {
    const nodes = [
      node("a", DEFAULT_SIZE, { x: 400, y: 40 }),
      node("b", DEFAULT_SIZE, { x: 0, y: 80 }),
      node("c", DEFAULT_SIZE, { x: 0, y: 0 }),
      node("isolated", DEFAULT_SIZE, { x: 80, y: 400 }),
    ];
    const edges = [edge("ab", "a", "b"), edge("bc", "b", "c")];
    const first = computeAgentCanvasAutoLayout(nodes, edges);
    const second = computeAgentCanvasAutoLayout([...nodes].reverse(), [...edges].reverse());

    expect(second).toEqual(first);
  });
});
