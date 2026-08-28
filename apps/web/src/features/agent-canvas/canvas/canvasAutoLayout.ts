import { Graph, layout } from "@dagrejs/dagre";

import type {
  CanvasBindingV2,
  CanvasLayoutPositionV2,
  CanvasNodeV2,
  CanvasPositionV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import type { AgentCanvasFlowNode } from "./AgentCanvasNode.tsx";
import {
  agentCanvasNodePlacementSize,
  type AgentCanvasNodeSize,
} from "./nodeGeometry.ts";

const COMPONENT_GAP = 160;
const ISOLATED_SECTION_GAP = 220;
const ISOLATED_NODE_GAP = 84;
const LAYOUT_ORIGIN = 120;

export interface AgentCanvasLayoutNode {
  id: string;
  position: CanvasPositionV2;
  size: AgentCanvasNodeSize;
}

export interface AgentCanvasLayoutEdge {
  id: string;
  source: string;
  target: string;
}

export interface AgentCanvasLayoutBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface AgentCanvasAutoLayoutResult {
  positions: CanvasLayoutPositionV2[];
  bounds: AgentCanvasLayoutBounds;
}

interface ConnectedComponent {
  nodes: AgentCanvasLayoutNode[];
  edges: AgentCanvasLayoutEdge[];
}

interface ComponentLayout {
  positions: Map<string, CanvasPositionV2>;
  width: number;
  height: number;
}

export function agentCanvasLayoutNodeFromFlowNode(
  node: AgentCanvasFlowNode,
): AgentCanvasLayoutNode {
  const measuredWidth = node.measured?.width;
  const measuredHeight = node.measured?.height;
  const fallback = agentCanvasNodePlacementSize(
    node.data.node.node_type,
    node.data.asset ? {
      width: node.data.asset.width,
      height: node.data.asset.height,
    } : null,
  );
  return {
    id: node.id,
    position: node.position,
    size: {
      width: measuredWidth && measuredWidth > 0 ? measuredWidth : fallback.width,
      height: measuredHeight && measuredHeight > 0 ? measuredHeight : fallback.height,
    },
  };
}

export function agentCanvasLayoutNodeFromCanvasNode(
  node: Pick<CanvasNodeV2, "node_id" | "node_type" | "output_asset_id" | "position">,
  assets: readonly ProjectAssetSummaryV2[] = [],
): AgentCanvasLayoutNode {
  const asset = node.output_asset_id
    ? assets.find((candidate) => candidate.asset_id === node.output_asset_id)
    : null;
  return {
    id: node.node_id,
    position: node.position,
    size: agentCanvasNodePlacementSize(
      node.node_type,
      asset ? { width: asset.width, height: asset.height } : null,
    ),
  };
}

export function enabledNodeLayoutEdges(
  bindings: readonly CanvasBindingV2[],
  visibleNodeIds: ReadonlySet<string>,
): AgentCanvasLayoutEdge[] {
  return bindings
    .filter((binding) => (
      binding.enabled
      && binding.source.kind === "node_output"
      && visibleNodeIds.has(binding.source.source_node_id)
      && visibleNodeIds.has(binding.target_node_id)
    ))
    .map((binding) => ({
      id: binding.binding_id,
      source: binding.source.kind === "node_output" ? binding.source.source_node_id : "",
      target: binding.target_node_id,
    }))
    .sort((left, right) => left.id.localeCompare(right.id));
}

export function computeAgentCanvasAutoLayout(
  nodes: readonly AgentCanvasLayoutNode[],
  edges: readonly AgentCanvasLayoutEdge[],
  options: { isolatedRowWidth?: number } = {},
): AgentCanvasAutoLayoutResult {
  if (!nodes.length) {
    return {
      positions: [],
      bounds: { x: LAYOUT_ORIGIN, y: LAYOUT_ORIGIN, width: 0, height: 0 },
    };
  }

  const sortedNodes = [...nodes].sort((left, right) => left.id.localeCompare(right.id));
  const nodesById = new Map(sortedNodes.map((node) => [node.id, node]));
  const layoutEdges = edges
    .filter((edge) => nodesById.has(edge.source) && nodesById.has(edge.target))
    .sort((left, right) => left.id.localeCompare(right.id));
  const { components, isolatedNodes } = discoverComponents(sortedNodes, layoutEdges);
  const packedPositions = new Map<string, CanvasPositionV2>();

  let connectedWidth = 0;
  let connectedBottom = 0;
  components.forEach((component, index) => {
    const componentLayout = layoutComponent(component);
    componentLayout.positions.forEach((position, nodeId) => {
      packedPositions.set(nodeId, { x: position.x, y: position.y + connectedBottom });
    });
    connectedWidth = Math.max(connectedWidth, componentLayout.width);
    connectedBottom += componentLayout.height;
    if (index < components.length - 1) connectedBottom += COMPONENT_GAP;
  });

  packIsolatedNodes(
    isolatedNodes,
    packedPositions,
    components.length ? connectedBottom + ISOLATED_SECTION_GAP : 0,
    Math.max(connectedWidth, options.isolatedRowWidth ?? 960),
  );

  return normalizedResult(sortedNodes, packedPositions);
}

function discoverComponents(
  nodes: readonly AgentCanvasLayoutNode[],
  edges: readonly AgentCanvasLayoutEdge[],
): { components: ConnectedComponent[]; isolatedNodes: AgentCanvasLayoutNode[] } {
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  const adjacentIds = new Map(nodes.map((node) => [node.id, new Set<string>()]));

  edges.forEach((edge) => {
    adjacentIds.get(edge.source)?.add(edge.target);
    adjacentIds.get(edge.target)?.add(edge.source);
  });

  const visited = new Set<string>();
  const components: ConnectedComponent[] = [];
  const isolatedNodes: AgentCanvasLayoutNode[] = [];
  nodes.forEach((node) => {
    if (visited.has(node.id)) return;

    const componentIds = collectComponentIds(node.id, adjacentIds, visited);
    const componentNodes = componentIds.map((nodeId) => nodesById.get(nodeId)!);
    const componentNodeIds = new Set(componentIds);
    const componentEdges = edges.filter((edge) => (
      componentNodeIds.has(edge.source) && componentNodeIds.has(edge.target)
    ));

    if (!componentEdges.length) {
      isolatedNodes.push(componentNodes[0]!);
      return;
    }
    components.push({ nodes: componentNodes, edges: componentEdges });
  });

  components.sort((left, right) => (
    right.nodes.length - left.nodes.length
    || right.edges.length - left.edges.length
    || left.nodes[0]!.id.localeCompare(right.nodes[0]!.id)
  ));
  isolatedNodes.sort((left, right) => (
    left.position.y - right.position.y
    || left.position.x - right.position.x
    || left.id.localeCompare(right.id)
  ));

  return { components, isolatedNodes };
}

function collectComponentIds(
  initialNodeId: string,
  adjacentIds: ReadonlyMap<string, ReadonlySet<string>>,
  visited: Set<string>,
): string[] {
  const pending = [initialNodeId];
  const nodeIds: string[] = [];
  while (pending.length) {
    const nodeId = pending.pop()!;
    if (visited.has(nodeId)) continue;
    visited.add(nodeId);
    nodeIds.push(nodeId);
    const neighbors = [...(adjacentIds.get(nodeId) ?? [])].sort((left, right) => (
      right.localeCompare(left)
    ));
    pending.push(...neighbors);
  }
  return nodeIds.sort((left, right) => left.localeCompare(right));
}

function layoutComponent(component: ConnectedComponent): ComponentLayout {
  const graph = new Graph({ multigraph: true });
  graph.setGraph({
    rankdir: "LR",
    ranksep: 140,
    nodesep: 84,
    edgesep: 28,
    marginx: 0,
    marginy: 0,
    ranker: "network-simplex",
  });
  graph.setDefaultEdgeLabel(() => ({}));

  component.nodes.forEach((node) => {
    graph.setNode(node.id, { width: node.size.width, height: node.size.height });
  });
  component.edges.forEach((edge) => {
    graph.setEdge(edge.source, edge.target, {}, edge.id);
  });
  layout(graph);

  const positions = new Map(component.nodes.map((node) => {
    const layoutNode = graph.node(node.id) as { x: number; y: number };
    return [node.id, {
      x: Math.round(layoutNode.x - node.size.width / 2),
      y: Math.round(layoutNode.y - node.size.height / 2),
    }];
  }));
  const componentPositions = [...positions.values()];
  const minX = Math.min(...componentPositions.map((position) => position.x));
  const minY = Math.min(...componentPositions.map((position) => position.y));
  const width = Math.max(...component.nodes.map((node) => (
    positions.get(node.id)!.x + node.size.width - minX
  )));
  const height = Math.max(...component.nodes.map((node) => (
    positions.get(node.id)!.y + node.size.height - minY
  )));

  positions.forEach((position, nodeId) => {
    positions.set(nodeId, { x: position.x - minX, y: position.y - minY });
  });
  return { positions, width, height };
}

function packIsolatedNodes(
  isolatedNodes: readonly AgentCanvasLayoutNode[],
  positions: Map<string, CanvasPositionV2>,
  initialY: number,
  rowWidth: number,
): void {
  let x = 0;
  let y = initialY;
  let rowHeight = 0;
  isolatedNodes.forEach((node) => {
    if (x > 0 && x + node.size.width > rowWidth) {
      x = 0;
      y += rowHeight + ISOLATED_NODE_GAP;
      rowHeight = 0;
    }
    positions.set(node.id, { x, y });
    x += node.size.width + ISOLATED_NODE_GAP;
    rowHeight = Math.max(rowHeight, node.size.height);
  });
}

function normalizedResult(
  nodes: readonly AgentCanvasLayoutNode[],
  packedPositions: ReadonlyMap<string, CanvasPositionV2>,
): AgentCanvasAutoLayoutResult {
  const minX = Math.min(...nodes.map((node) => packedPositions.get(node.id)!.x));
  const minY = Math.min(...nodes.map((node) => packedPositions.get(node.id)!.y));
  const positions = nodes.map((node) => {
    const position = packedPositions.get(node.id)!;
    return {
      node_id: node.id,
      x: Math.round(position.x - minX + LAYOUT_ORIGIN),
      y: Math.round(position.y - minY + LAYOUT_ORIGIN),
    };
  });
  const positionsById = new Map(positions.map((position) => [position.node_id, position]));
  const boundsX = Math.min(...positions.map((position) => position.x));
  const boundsY = Math.min(...positions.map((position) => position.y));
  const boundsRight = Math.max(...nodes.map((node) => {
    const position = positionsById.get(node.id)!;
    return position.x + node.size.width;
  }));
  const boundsBottom = Math.max(...nodes.map((node) => {
    const position = positionsById.get(node.id)!;
    return position.y + node.size.height;
  }));

  return {
    positions: positions.sort((left, right) => left.node_id.localeCompare(right.node_id)),
    bounds: {
      x: boundsX,
      y: boundsY,
      width: boundsRight - boundsX,
      height: boundsBottom - boundsY,
    },
  };
}
