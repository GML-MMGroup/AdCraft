import type { CanvasNodeV2 } from "../../types-v2.ts";

export function workflowRefreshRevealNodeIds(
  currentNodes: readonly Pick<CanvasNodeV2, "node_id">[],
  nextNodes: readonly Pick<CanvasNodeV2, "node_id">[],
  plainCreatedNodeIds: ReadonlySet<string>,
): string[] {
  const knownNodeIds = new Set(currentNodes.map((node) => node.node_id));
  return nextNodes
    .filter((node) => !knownNodeIds.has(node.node_id) && !plainCreatedNodeIds.has(node.node_id))
    .map((node) => node.node_id);
}
