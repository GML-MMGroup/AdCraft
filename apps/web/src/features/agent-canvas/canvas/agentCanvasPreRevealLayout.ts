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
} from "./canvasAutoLayout.ts";
import {
  progressiveRevealPlanFromPositions,
  type ProgressiveNodePlacementPlan,
} from "./agentCanvasProgressivePlacement.ts";
import { isAgentCanvasVisibleNodeType } from "../model/nodeDefaults.ts";

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

export function buildAgentCanvasPreRevealLayout(
  input: AgentCanvasPreRevealLayoutInput,
): AgentCanvasPreRevealLayout {
  const visibleNodes = input.nodes.filter((node) => isAgentCanvasVisibleNodeType(node.node_type));
  const layoutNodes = visibleNodes.map((node) => (
    agentCanvasLayoutNodeFromCanvasNode(node, input.assets)
  ));
  const visibleNodeIds = new Set(layoutNodes.map((node) => node.id));
  const layout = computeAgentCanvasAutoLayout(
    layoutNodes,
    enabledNodeLayoutEdges(input.bindings, visibleNodeIds),
    input.isolatedRowWidth === undefined
      ? undefined
      : { isolatedRowWidth: input.isolatedRowWidth },
  );
  return {
    positions: layout.positions,
    revealPlan: progressiveRevealPlanFromPositions({
      nodes: input.nodes,
      bindings: input.bindings,
      affectedNodeIds: input.affectedNodeIds,
      positions: layout.positions,
    }),
  };
}
