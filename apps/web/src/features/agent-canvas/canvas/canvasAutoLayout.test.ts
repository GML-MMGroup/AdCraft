import { describe, expect, it } from "vitest";

import type { CanvasBindingV2, CanvasLayoutPositionV2, CanvasNodeV2, CanvasPositionV2, ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import type { AgentCanvasFlowNode } from "./AgentCanvasNode.tsx";
import type { AgentCanvasNodeSize } from "./nodeGeometry.ts";
import { agentCanvasNodePlacementSize } from "./nodeGeometry.ts";
import {
  agentCanvasLayoutNodeFromFlowNode,
  agentCanvasLayoutNodeFromCanvasNode,
  computeAgentCanvasAutoLayout,
  enabledNodeLayoutEdges,
  type AgentCanvasLayoutEdge,
  type AgentCanvasLayoutNode,
  type AgentCanvasAutoLayoutResult,
} from "./canvasAutoLayout.ts";
import productionLayout from "./fixtures/productionLayout.json";

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

function storyboardNode(
  id: string,
  number: unknown,
  role: "storyboard_sequence" | "storyboard_video" = "storyboard_sequence",
  metadata: Record<string, unknown> = {},
): CanvasNodeV2 {
  return {
    ...productionLayout.nodes.find(item => item.creative_role === role),
    node_id: id,
    metadata: { sequence_index: number, source_agent_document_id: "document-1", ...metadata },
  } as CanvasNodeV2;
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

function verticalCenters(result: AgentCanvasAutoLayoutResult, nodes: AgentCanvasLayoutNode[]): Record<string, number> {
  const sizes = new Map(nodes.map(item => [item.id, item.size]));
  return Object.fromEntries(result.positions.map(position => [
    position.node_id, position.y + sizes.get(position.node_id)!.height / 2,
  ]));
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

  it("passes the same persisted creative identity from measured and canonical nodes", () => {
    for (const canonical of productionLayout.nodes as CanvasNodeV2[]) {
      const flow = flowNode({ nodeType: canonical.node_type });
      flow.data.node = canonical;
      expect(agentCanvasLayoutNodeFromFlowNode(flow).identity)
        .toEqual(agentCanvasLayoutNodeFromCanvasNode(canonical).identity);
    }
    expect(agentCanvasLayoutNodeFromFlowNode({
      ...flowNode({ nodeType: "image" }),
      data: { node: storyboardNode("grid", 4), asset: null },
    } as AgentCanvasFlowNode).identity?.number).toBe(4);
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
  it("orders a production canvas by creative identity and aligns each image with its matching output", () => {
    const canonicalNodes = productionLayout.nodes as CanvasNodeV2[];
    const assets = productionLayout.assets as ProjectAssetSummaryV2[];
    const nodes = canonicalNodes.map(item => agentCanvasLayoutNodeFromCanvasNode(item, assets));
    const result = computeAgentCanvasAutoLayout(nodes, productionLayout.edges);
    const positions = positionsById(result.positions);
    const sizes = new Map(nodes.map(item => [item.id, item.size]));
    const center = (item: CanvasNodeV2) => positions[item.node_id]!.y + sizes.get(item.node_id)!.height / 2;

    for (const role of ["storyboard_sequence", "storyboard_video"] as const) {
      const ordered = canonicalNodes.filter(item => item.creative_role === role).sort((a, b) => center(a) - center(b));
      expect(ordered.map(item => item.metadata.sequence_index)).toEqual([1, 2, 3, 4, 5]);
    }
    for (const grid of canonicalNodes.filter(item => item.creative_role === "storyboard_sequence")) {
      const video = canonicalNodes.find(item => item.creative_role === "storyboard_video"
        && item.metadata.source_sequence_id === grid.metadata.source_sequence_id)!;
      expect(Math.abs(center(grid) - center(video))).toBeLessThanOrEqual(1);
      expect(positions[grid.node_id]!.x).toBeLessThan(positions[video.node_id]!.x);
    }
    for (const phase of ["main", "turnaround"]) {
      const ordered = canonicalNodes.filter(item => item.creative_role === "character" && item.metadata.character_phase === phase)
        .sort((a, b) => center(a) - center(b));
      expect(ordered.map(item => item.metadata.occurrence_id)).toEqual(["character-1", "character-2", "character-3"]);
    }
    for (const main of canonicalNodes.filter(item => item.creative_role === "character" && item.metadata.character_phase === "main")) {
      const turnaround = canonicalNodes.find(item => item.creative_role === "character"
        && item.metadata.character_phase === "turnaround" && item.metadata.occurrence_id === main.metadata.occurrence_id)!;
      expect(Math.abs(center(main) - center(turnaround))).toBeLessThanOrEqual(1);
    }
    assertCompleteIntegerBounds(result, nodes);
    expect(computeAgentCanvasAutoLayout([...nodes].reverse(), [...productionLayout.edges].reverse())).toEqual(result);
    expect(computeAgentCanvasAutoLayout(nodes.map(item => ({ ...item, position: positions[item.id]! })), productionLayout.edges))
      .toEqual(result);
  });

  it("keeps disconnected sequence pairs in numeric order, including double-digit numbers", () => {
    const canonical = [10, 2, 1].flatMap(number => [
      storyboardNode(`grid-${number}`, number),
      storyboardNode(`video-${number}`, number, "storyboard_video"),
    ]);
    const nodes = canonical.map(item => agentCanvasLayoutNodeFromCanvasNode(item));
    const edges = [1, 2, 10].map(number => edge(`pair-${number}`, `grid-${number}`, `video-${number}`));
    const result = computeAgentCanvasAutoLayout(nodes, edges);
    const positions = positionsById(result.positions);
    const centers = verticalCenters(result, nodes);
    expect(positions["grid-1"]!.y).toBeLessThan(positions["grid-2"]!.y);
    expect(positions["grid-2"]!.y).toBeLessThan(positions["grid-10"]!.y);
    for (const number of [1, 2, 10]) {
      expect(centers[`grid-${number}`]).toBe(centers[`video-${number}`]);
    }
    assertCompleteIntegerBounds(result, nodes);
  });

  it("does not merge equal sequence numbers from different documents or sequence identities", () => {
    const canonical = [
      storyboardNode("grid-a", 1, "storyboard_sequence", { source_sequence_id: "a" }),
      storyboardNode("video-a", 1, "storyboard_video", { source_sequence_id: "a" }),
      storyboardNode("grid-b", 1, "storyboard_sequence", { source_sequence_id: "b" }),
      storyboardNode("video-b", 1, "storyboard_video", { source_sequence_id: "a", source_agent_document_id: "document-2" }),
    ];
    const nodes = canonical.map(item => agentCanvasLayoutNodeFromCanvasNode(item));
    const result = computeAgentCanvasAutoLayout(nodes, [
      edge("a-a", "grid-a", "video-a"),
      edge("a-b", "grid-a", "video-b"),
    ]);
    const centers = verticalCenters(result, nodes);
    expect(centers["grid-a"]).toBe(centers["video-a"]);
    expect(new Set([centers["grid-a"], centers["grid-b"], centers["video-b"]]).size).toBe(3);
    assertCompleteIntegerBounds(result, nodes);
  });

  it("separates duplicate variants without losing their input/output pairing", () => {
    const canonical = [
      storyboardNode("grid-a", 1),
      storyboardNode("grid-b", 1),
      storyboardNode("video-a", 1, "storyboard_video"),
      storyboardNode("video-b", 1, "storyboard_video"),
      storyboardNode("grid-next", 2),
    ];
    const nodes = canonical.map(item => agentCanvasLayoutNodeFromCanvasNode(item));
    const result = computeAgentCanvasAutoLayout(nodes, [
      edge("a-b", "grid-a", "video-b"),
      edge("b-a", "grid-b", "video-a"),
    ]);
    const centers = verticalCenters(result, nodes);
    expect(centers["grid-a"]).toBe(centers["video-b"]);
    expect(centers["grid-b"]).toBe(centers["video-a"]);
    expect(centers["grid-next"]!).toBeGreaterThan(Math.max(centers["grid-a"]!, centers["grid-b"]!));
    assertCompleteIntegerBounds(result, nodes);
  });

  it("keeps unnumbered and malformed legacy nodes clear of numbered lanes", () => {
    const canonical = [
      storyboardNode("grid", 1),
      storyboardNode("video", 1, "storyboard_video"),
      storyboardNode("missing", undefined),
      storyboardNode("invalid", "2"),
    ];
    const nodes = canonical.map(item => agentCanvasLayoutNodeFromCanvasNode(item));
    expect(nodes.filter(item => item.identity).map(item => item.id)).toEqual(["grid", "video"]);
    const result = computeAgentCanvasAutoLayout(nodes, [
      edge("grid-video", "grid", "video"),
      edge("missing-video", "missing", "video"),
      edge("invalid-video", "invalid", "video"),
    ]);
    assertCompleteIntegerBounds(result, nodes);
  });

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
