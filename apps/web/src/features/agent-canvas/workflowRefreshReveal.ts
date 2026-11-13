import type { CanvasNodeV2, CanvasRuntimeEventV2 } from "../../types-v2.ts";

export function releaseWorkflowRefreshNodeFromEvent(
  event: Pick<CanvasRuntimeEventV2, "event_type" | "node_id" | "payload">,
  immediateRevealNodeIds: Set<string>,
  releaseNodeIds: (nodeIds: readonly string[]) => void,
): void {
  // Guided Editing is persisted with its own topology receipt, without the
  // node_created/action receipt events that normally release new canvas nodes.
  const guidedEditing = event.event_type === "guided_editing_updated"
    || event.event_type === "editing_prepared"
    || event.event_type === "guided_editing_ready";
  if (event.event_type !== "node_created" && !guidedEditing) return;
  const nodeId = event.node_id
    ?? (guidedEditing && typeof event.payload?.editing_node_id === "string"
      ? event.payload.editing_node_id
      : null);
  if (!nodeId) return;
  // Remember early releases so the following workflow refresh cannot reserve
  // the same node again before it becomes canonical.
  immediateRevealNodeIds.add(nodeId);
  releaseNodeIds([nodeId]);
}

export function workflowRefreshRevealNodeIds(
  currentNodes: readonly Pick<CanvasNodeV2, "node_id">[],
  nextNodes: readonly Pick<CanvasNodeV2, "node_id">[],
  immediateRevealNodeIds: ReadonlySet<string>,
): string[] {
  const knownNodeIds = new Set(currentNodes.map((node) => node.node_id));
  return nextNodes
    .filter((node) => !knownNodeIds.has(node.node_id) && !immediateRevealNodeIds.has(node.node_id))
    .map((node) => node.node_id);
}

export function reserveWorkflowRefreshNodes(
  currentNodes: readonly Pick<CanvasNodeV2, "node_id">[],
  nextNodes: readonly Pick<CanvasNodeV2, "node_id">[],
  immediateRevealNodeIds: Set<string>,
  reserveNodeIds: (nodeIds: readonly string[]) => void,
): void {
  const createdNodeIds = workflowRefreshRevealNodeIds(currentNodes, nextNodes, immediateRevealNodeIds);
  if (createdNodeIds.length) reserveNodeIds(createdNodeIds);
  // Consecutive refreshes may finish before React renders nextNodes. Retain
  // their early releases until currentNodes actually contains those nodes.
  currentNodes.forEach((node) => immediateRevealNodeIds.delete(node.node_id));
}
