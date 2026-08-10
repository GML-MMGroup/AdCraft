interface DragStateNode {
  id: string;
  position: { x: number; y: number };
  selected?: boolean;
  dragging?: boolean;
}

export function setDraggedNodeIds(
  activeDraggedNodeIds: Set<string>,
  fallbackNodeId: string,
  draggedNodeIds: readonly string[],
  isDragging: boolean,
): void {
  const nodeIds = draggedNodeIds.length > 0 ? draggedNodeIds : [fallbackNodeId];
  for (const nodeId of nodeIds) {
    if (isDragging) activeDraggedNodeIds.add(nodeId);
    else activeDraggedNodeIds.delete(nodeId);
  }
}

export function reconcileDragAwareNodes<T extends DragStateNode>(
  canonicalNodes: readonly T[],
  currentNodes: readonly T[],
  activeDraggedNodeIds: ReadonlySet<string>,
): T[] {
  const nodesById = new Map(currentNodes.map((node) => [node.id, node]));

  return canonicalNodes.map((node) => {
    const current = nodesById.get(node.id);
    const selected = current?.selected ?? false;

    if (!activeDraggedNodeIds.has(node.id)) {
      const { dragging: _dragging, ...settledNode } = node;
      return { ...settledNode, selected } as T;
    }

    return {
      ...node,
      position: current?.position ?? node.position,
      dragging: true,
      selected,
    } as T;
  });
}
