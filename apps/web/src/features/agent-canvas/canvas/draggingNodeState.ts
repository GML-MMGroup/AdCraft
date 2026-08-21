interface DragStateNode {
  id: string;
  position: { x: number; y: number };
  selected?: boolean;
  dragging?: boolean;
}

interface DragLayoutPosition {
  node_id: string;
  x: number;
  y: number;
}

interface DeferredNodeSnapshot<T> {
  nodes: T[] | null;
  pendingNodes: readonly T[] | null;
}

interface FinishedNodeDrag<T> {
  nodes: T[];
  positions: DragLayoutPosition[];
}

function isFinitePosition(position: DragStateNode["position"]): boolean {
  return Number.isFinite(position.x) && Number.isFinite(position.y);
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
    const canonicalPosition = isFinitePosition(node.position)
      ? node.position
      : current && isFinitePosition(current.position)
        ? current.position
        : { x: 0, y: 0 };

    if (!activeDraggedNodeIds.has(node.id)) {
      const { dragging: _dragging, ...settledNode } = node;
      return { ...settledNode, position: canonicalPosition, selected } as T;
    }

    return {
      ...node,
      position: current && isFinitePosition(current.position)
        ? current.position
        : canonicalPosition,
      dragging: true,
      selected,
    } as T;
  });
}

export function deferNodeSnapshotDuringDrag<T extends DragStateNode>(
  canonicalNodes: readonly T[],
  currentNodes: readonly T[],
  activeDraggedNodeIds: ReadonlySet<string>,
): DeferredNodeSnapshot<T> {
  if (activeDraggedNodeIds.size > 0) {
    return { nodes: null, pendingNodes: canonicalNodes };
  }
  return {
    nodes: reconcileDragAwareNodes(canonicalNodes, currentNodes, activeDraggedNodeIds),
    pendingNodes: null,
  };
}

export function finishNodeDrag<T extends DragStateNode>(
  canonicalNodes: readonly T[],
  currentNodes: readonly T[],
  activeDraggedNodeIds: Set<string>,
  stoppedNodes: readonly T[],
): FinishedNodeDrag<T> {
  const currentById = new Map(currentNodes.map((node) => [node.id, node]));
  const stoppedById = new Map(stoppedNodes.map((node) => [node.id, node]));
  const finalNodeIds = new Set([
    ...activeDraggedNodeIds,
    ...stoppedNodes.map((node) => node.id),
  ]);
  const positions: DragLayoutPosition[] = [];

  for (const nodeId of finalNodeIds) {
    const finalNode = stoppedById.get(nodeId) ?? currentById.get(nodeId);
    if (
      finalNode
      && isFinitePosition(finalNode.position)
    ) {
      positions.push({
        node_id: nodeId,
        x: finalNode.position.x,
        y: finalNode.position.y,
      });
    }
  }

  activeDraggedNodeIds.clear();
  const positionByNodeId = new Map(positions.map((position) => [position.node_id, position]));
  const nodes = reconcileDragAwareNodes(canonicalNodes, currentNodes, activeDraggedNodeIds)
    .map((node) => {
      const position = positionByNodeId.get(node.id);
      if (!position) return node;
      return {
        ...node,
        position: { x: position.x, y: position.y },
      } as T;
    });

  return { nodes, positions };
}
