import type {
  CanvasBindingV2,
  CanvasLayoutPositionV2,
  CanvasNodeV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import {
  agentCanvasLayoutNodeFromCanvasNode,
  computeAgentCanvasAutoLayout,
  enabledNodeLayoutEdges,
  type AgentCanvasLayoutNode,
} from "./canvasAutoLayout.ts";
import {
  progressiveRevealPlanFromPositions,
  type ProgressiveNodePlacementPlan,
} from "./agentCanvasProgressivePlacement.ts";
import { isAgentCanvasVisibleNodeType } from "../model/nodeDefaults.ts";

// Matches the gap the automatic layout leaves between layout sections.
const USER_NODE_CLEARANCE = 220;

export interface AgentCanvasPreRevealLayoutInput {
  nodes: readonly CanvasNodeV2[];
  bindings: readonly CanvasBindingV2[];
  affectedNodeIds: readonly string[];
  assets?: readonly ProjectAssetSummaryV2[];
  isolatedRowWidth?: number;
}

export interface AgentCanvasPreRevealLayout {
  positions: CanvasLayoutPositionV2[];
  revealPlan: ProgressiveNodePlacementPlan;
}

/** Nodes the user created on the canvas stay outside Agent journeys and Agent layout. */
export function isUserAuthoredCanvasNode(node: Pick<CanvasNodeV2, "metadata">): boolean {
  return node.metadata?.authoring_origin === "user";
}

export function buildAgentCanvasPreRevealLayout(
  input: AgentCanvasPreRevealLayoutInput,
): AgentCanvasPreRevealLayout {
  const visibleNodes = input.nodes.filter((node) => isAgentCanvasVisibleNodeType(node.node_type));
  const userNodes = visibleNodes
    .filter(isUserAuthoredCanvasNode)
    .map((node) => agentCanvasLayoutNodeFromCanvasNode(node, input.assets));
  const layoutNodes = visibleNodes
    .filter((node) => !isUserAuthoredCanvasNode(node))
    .map((node) => agentCanvasLayoutNodeFromCanvasNode(node, input.assets));
  const visibleNodeIds = new Set(layoutNodes.map((node) => node.id));
  const layout = computeAgentCanvasAutoLayout(
    layoutNodes,
    enabledNodeLayoutEdges(input.bindings, visibleNodeIds),
    input.isolatedRowWidth === undefined
      ? undefined
      : { isolatedRowWidth: input.isolatedRowWidth },
  );
  const positions = clearOfUserNodes(layout.positions, layoutNodes, userNodes);
  return {
    positions,
    revealPlan: progressiveRevealPlanFromPositions({
      nodes: input.nodes,
      bindings: input.bindings,
      affectedNodeIds: input.affectedNodeIds,
      positions,
    }),
  };
}

/** Shift the Agent layout below user-created nodes when the two regions would overlap. */
function clearOfUserNodes(
  positions: CanvasLayoutPositionV2[],
  layoutNodes: readonly AgentCanvasLayoutNode[],
  userNodes: readonly AgentCanvasLayoutNode[],
): CanvasLayoutPositionV2[] {
  if (!positions.length || !userNodes.length) return positions;
  const sizes = new Map(layoutNodes.map((node) => [node.id, node.size]));
  const overlaps = positions.some((position) => {
    const size = sizes.get(position.node_id)!;
    return userNodes.some((user) => (
      position.x < user.position.x + user.size.width
      && position.x + size.width > user.position.x
      && position.y < user.position.y + user.size.height
      && position.y + size.height > user.position.y
    ));
  });
  if (!overlaps) return positions;
  const userBottom = Math.max(...userNodes.map((user) => user.position.y + user.size.height));
  const layoutTop = Math.min(...positions.map((position) => position.y));
  const offset = userBottom + USER_NODE_CLEARANCE - layoutTop;
  return positions.map((position) => ({ ...position, y: position.y + offset }));
}
