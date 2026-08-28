import type {
  AgentPlacementHintV2,
  CanvasBindingV2,
  CanvasLayoutPositionV2,
  CanvasNodeV2,
  CanvasPositionV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import { isAgentCanvasVisibleNodeType } from "../model/nodeDefaults.ts";
import {
  AGENT_CANVAS_NODE_HORIZONTAL_GAP,
  AGENT_CANVAS_NODE_VERTICAL_GAP,
  agentCanvasNodePlacementSize,
  type AgentCanvasNodeSize,
} from "./nodeGeometry.ts";

export interface ProgressiveRevealLevel {
  level: number;
  nodeIds: string[];
}

export interface ProgressiveNodePlacementPlan {
  positions: CanvasLayoutPositionV2[];
  levels: ProgressiveRevealLevel[];
  orderedNodeIds: string[];
}

export interface ProgressiveNodePlacementInput {
  nodes: readonly CanvasNodeV2[];
  bindings: readonly CanvasBindingV2[];
  affectedNodeIds: readonly string[];
  placementHints: readonly AgentPlacementHintV2[];
  viewportCenter: CanvasPositionV2;
  assets?: readonly ProjectAssetSummaryV2[];
}

interface PlacementRect {
  position: CanvasPositionV2;
  size: AgentCanvasNodeSize;
}

interface OrderedAffectedNode {
  node: CanvasNodeV2;
  hint: AgentPlacementHintV2;
  originalIndex: number;
  level: number;
}

const DEFAULT_PLACEMENT_HINT: AgentPlacementHintV2 = {
  intent: "append_flow",
  anchor_node_id: null,
  group_key: null,
};

export function planProgressiveNodePlacement(
  input: ProgressiveNodePlacementInput,
): ProgressiveNodePlacementPlan {
  const visibleNodes = input.nodes.filter((node) => isAgentCanvasVisibleNodeType(node.node_type));
  const visibleNodeIds = new Set(visibleNodes.map((node) => node.node_id));
  const affectedNodeIds = new Set(input.affectedNodeIds);
  const nodesById = new Map(visibleNodes.map((node) => [node.node_id, node]));
  const assetsById = new Map((input.assets ?? []).map((asset) => [asset.asset_id, asset]));
  const levelsByNodeId = computeNodeLevels(visibleNodeIds, input.bindings);
  const ordered = input.affectedNodeIds.flatMap((nodeId, originalIndex) => {
    const node = nodesById.get(nodeId);
    if (!node) return [];
    return [{
      node,
      hint: input.placementHints[originalIndex] ?? DEFAULT_PLACEMENT_HINT,
      originalIndex,
      level: levelsByNodeId.get(nodeId) ?? 0,
    } satisfies OrderedAffectedNode];
  }).sort(compareAffectedNodes);

  const occupied: PlacementRect[] = visibleNodes
    .filter((node) => !affectedNodeIds.has(node.node_id))
    .map((node) => ({
      position: node.position,
      size: placementSize(node, assetsById),
    }));
  const existingVisibleNodes = visibleNodes.filter((node) => !affectedNodeIds.has(node.node_id));
  const plannedPositions = new Map<string, CanvasPositionV2>();
  const plannedRects: PlacementRect[] = [];
  const positions: CanvasLayoutPositionV2[] = [];

  ordered.forEach(({ node, hint }) => {
    const candidateSize = placementSize(node, assetsById);
    const anchor = hint.anchor_node_id ? nodesById.get(hint.anchor_node_id) ?? null : null;
    const anchorPosition = anchor
      ? plannedPositions.get(anchor.node_id) ?? anchor.position
      : null;
    const anchorSize = anchor ? placementSize(anchor, assetsById) : null;
    const preferred = preferredPosition({
      hint,
      anchorPosition,
      anchorSize,
      candidateSize,
      viewportCenter: input.viewportCenter,
      existingVisibleNodes,
      occupied: [...occupied, ...plannedRects],
      assetsById,
    });
    const position = findAvailableRectPosition(
      [...occupied, ...plannedRects],
      preferred,
      candidateSize,
    );
    plannedPositions.set(node.node_id, position);
    plannedRects.push({ position, size: candidateSize });
    positions.push({ node_id: node.node_id, ...position });
  });

  const orderedNodeIds = ordered.map(({ node }) => node.node_id);
  const groupedLevels = new Map<number, string[]>();
  ordered.forEach(({ node, level }) => {
    const nodeIds = groupedLevels.get(level) ?? [];
    nodeIds.push(node.node_id);
    groupedLevels.set(level, nodeIds);
  });

  return {
    positions,
    levels: [...groupedLevels.entries()]
      .sort(([left], [right]) => left - right)
      .map(([level, nodeIds]) => ({ level, nodeIds })),
    orderedNodeIds,
  };
}

function compareAffectedNodes(left: OrderedAffectedNode, right: OrderedAffectedNode): number {
  return left.level - right.level
    || (left.hint.anchor_node_id ?? "").localeCompare(right.hint.anchor_node_id ?? "")
    || (left.hint.group_key ?? "").localeCompare(right.hint.group_key ?? "")
    || left.originalIndex - right.originalIndex;
}

function preferredPosition(options: {
  hint: AgentPlacementHintV2;
  anchorPosition: CanvasPositionV2 | null;
  anchorSize: AgentCanvasNodeSize | null;
  candidateSize: AgentCanvasNodeSize;
  viewportCenter: CanvasPositionV2;
  existingVisibleNodes: readonly CanvasNodeV2[];
  occupied: readonly PlacementRect[];
  assetsById: ReadonlyMap<string, ProjectAssetSummaryV2>;
}): CanvasPositionV2 {
  const {
    hint,
    anchorPosition,
    anchorSize,
    candidateSize,
    viewportCenter,
    existingVisibleNodes,
    occupied,
    assetsById,
  } = options;
  if (hint.intent === "near_selection" && anchorPosition) return anchorPosition;
  if (
    (hint.intent === "right_sibling" || hint.intent === "after_anchor")
    && anchorPosition
    && anchorSize
  ) {
    return {
      x: anchorPosition.x + anchorSize.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP,
      y: anchorPosition.y,
    };
  }
  if (!existingVisibleNodes.length && !occupied.length) {
    return {
      x: Math.round(viewportCenter.x - candidateSize.width / 2),
      y: Math.round(viewportCenter.y - candidateSize.height / 2),
    };
  }
  if (hint.anchor_node_id && anchorPosition && anchorSize) {
    return {
      x: anchorPosition.x + anchorSize.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP,
      y: anchorPosition.y,
    };
  }
  if (existingVisibleNodes.length) {
    const leftmost = existingVisibleNodes.reduce((current, node) => (
      node.position.x < current.position.x ? node : current
    ));
    const leftmostSize = placementSize(leftmost, assetsById);
    return {
      x: leftmost.position.x - candidateSize.width - AGENT_CANVAS_NODE_HORIZONTAL_GAP,
      y: Math.round(viewportCenter.y - Math.min(candidateSize.height, leftmostSize.height) / 2),
    };
  }
  const rightEdge = Math.max(...occupied.map((rect) => rect.position.x + rect.size.width));
  return {
    x: rightEdge + AGENT_CANVAS_NODE_HORIZONTAL_GAP,
    y: Math.round(viewportCenter.y - candidateSize.height / 2),
  };
}

function placementSize(
  node: Pick<CanvasNodeV2, "node_type" | "output_asset_id">,
  assetsById: ReadonlyMap<string, ProjectAssetSummaryV2>,
): AgentCanvasNodeSize {
  const asset = node.output_asset_id ? assetsById.get(node.output_asset_id) : null;
  return agentCanvasNodePlacementSize(
    node.node_type,
    asset ? { width: asset.width, height: asset.height } : null,
  );
}

function findAvailableRectPosition(
  occupied: readonly PlacementRect[],
  preferred: CanvasPositionV2,
  candidateSize: AgentCanvasNodeSize,
): CanvasPositionV2 {
  if (!occupied.length) return preferred;
  const xCandidates = uniqueNumbers([
    preferred.x,
    ...occupied.flatMap((rect) => [
      rect.position.x + rect.size.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP,
      rect.position.x - candidateSize.width - AGENT_CANVAS_NODE_HORIZONTAL_GAP,
    ]),
  ]);
  const yCandidates = uniqueNumbers([
    preferred.y,
    ...occupied.flatMap((rect) => [
      rect.position.y + rect.size.height + AGENT_CANVAS_NODE_VERTICAL_GAP,
      rect.position.y - candidateSize.height - AGENT_CANVAS_NODE_VERTICAL_GAP,
    ]),
  ]);
  const candidates = yCandidates.flatMap((y) => xCandidates.map((x) => ({ x, y })));
  candidates.sort((left, right) => {
    const rowPriority = Number(left.y !== preferred.y) - Number(right.y !== preferred.y);
    return rowPriority || manhattanDistance(left, preferred) - manhattanDistance(right, preferred);
  });
  return candidates.find((position) => !occupied.some((rect) => (
    rectsOverlap(position, candidateSize, rect)
  ))) ?? {
    x: Math.max(...occupied.map((rect) => rect.position.x + rect.size.width))
      + AGENT_CANVAS_NODE_HORIZONTAL_GAP,
    y: preferred.y,
  };
}

function rectsOverlap(
  position: CanvasPositionV2,
  size: AgentCanvasNodeSize,
  occupied: PlacementRect,
): boolean {
  return position.x < occupied.position.x + occupied.size.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP
    && position.x + size.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP > occupied.position.x
    && position.y < occupied.position.y + occupied.size.height + AGENT_CANVAS_NODE_VERTICAL_GAP
    && position.y + size.height + AGENT_CANVAS_NODE_VERTICAL_GAP > occupied.position.y;
}

function uniqueNumbers(values: readonly number[]): number[] {
  return [...new Set(values)];
}

function manhattanDistance(left: CanvasPositionV2, right: CanvasPositionV2): number {
  return Math.abs(left.x - right.x) + Math.abs(left.y - right.y);
}

function computeNodeLevels(
  visibleNodeIds: ReadonlySet<string>,
  bindings: readonly CanvasBindingV2[],
): Map<string, number> {
  const adjacency = new Map([...visibleNodeIds].map((nodeId) => [nodeId, new Set<string>()]));
  bindings.forEach((binding) => {
    if (!binding.enabled || binding.source.kind !== "node_output") return;
    const sourceId = binding.source.source_node_id;
    if (!visibleNodeIds.has(sourceId) || !visibleNodeIds.has(binding.target_node_id)) return;
    adjacency.get(sourceId)?.add(binding.target_node_id);
  });
  const components = stronglyConnectedComponents(adjacency);
  const componentByNodeId = new Map<string, number>();
  components.forEach((nodeIds, componentIndex) => {
    nodeIds.forEach((nodeId) => componentByNodeId.set(nodeId, componentIndex));
  });
  const componentEdges = new Map(components.map((_, index) => [index, new Set<number>()]));
  const indegrees = new Map(components.map((_, index) => [index, 0]));
  adjacency.forEach((targets, sourceId) => {
    const sourceComponent = componentByNodeId.get(sourceId)!;
    targets.forEach((targetId) => {
      const targetComponent = componentByNodeId.get(targetId)!;
      if (sourceComponent === targetComponent || componentEdges.get(sourceComponent)!.has(targetComponent)) return;
      componentEdges.get(sourceComponent)!.add(targetComponent);
      indegrees.set(targetComponent, (indegrees.get(targetComponent) ?? 0) + 1);
    });
  });
  const componentLevels = new Map(components.map((_, index) => [index, 0]));
  const pending = [...indegrees.entries()]
    .filter(([, indegree]) => indegree === 0)
    .map(([index]) => index)
    .sort((left, right) => left - right);
  while (pending.length) {
    const component = pending.shift()!;
    [...(componentEdges.get(component) ?? [])].sort((left, right) => left - right).forEach((target) => {
      componentLevels.set(target, Math.max(
        componentLevels.get(target) ?? 0,
        (componentLevels.get(component) ?? 0) + 1,
      ));
      const indegree = (indegrees.get(target) ?? 1) - 1;
      indegrees.set(target, indegree);
      if (indegree === 0) pending.push(target);
    });
    pending.sort((left, right) => left - right);
  }
  return new Map([...visibleNodeIds].map((nodeId) => [
    nodeId,
    componentLevels.get(componentByNodeId.get(nodeId)!) ?? 0,
  ]));
}

function stronglyConnectedComponents(
  adjacency: ReadonlyMap<string, ReadonlySet<string>>,
): string[][] {
  let nextIndex = 0;
  const indices = new Map<string, number>();
  const lowLinks = new Map<string, number>();
  const stack: string[] = [];
  const onStack = new Set<string>();
  const components: string[][] = [];

  const visit = (nodeId: string): void => {
    indices.set(nodeId, nextIndex);
    lowLinks.set(nodeId, nextIndex);
    nextIndex += 1;
    stack.push(nodeId);
    onStack.add(nodeId);

    [...(adjacency.get(nodeId) ?? [])].sort().forEach((targetId) => {
      if (!indices.has(targetId)) {
        visit(targetId);
        lowLinks.set(nodeId, Math.min(lowLinks.get(nodeId)!, lowLinks.get(targetId)!));
      } else if (onStack.has(targetId)) {
        lowLinks.set(nodeId, Math.min(lowLinks.get(nodeId)!, indices.get(targetId)!));
      }
    });

    if (lowLinks.get(nodeId) !== indices.get(nodeId)) return;
    const component: string[] = [];
    let stackedNodeId: string;
    do {
      stackedNodeId = stack.pop()!;
      onStack.delete(stackedNodeId);
      component.push(stackedNodeId);
    } while (stackedNodeId !== nodeId);
    components.push(component.sort());
  };

  [...adjacency.keys()].sort().forEach((nodeId) => {
    if (!indices.has(nodeId)) visit(nodeId);
  });
  return components;
}
