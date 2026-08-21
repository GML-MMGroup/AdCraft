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

function samePresentationValue(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  if (!left || !right || typeof left !== "object" || typeof right !== "object") {
    return false;
  }
  if (Array.isArray(left) || Array.isArray(right)) {
    return Array.isArray(left)
      && Array.isArray(right)
      && left.length === right.length
      && left.every((value, index) => samePresentationValue(value, right[index]));
  }

  const leftRecord = left as Record<string, unknown>;
  const rightRecord = right as Record<string, unknown>;
  const leftKeys = Object.keys(leftRecord);
  const rightKeys = Object.keys(rightRecord);
  return leftKeys.length === rightKeys.length
    && leftKeys.every((key) => (
      Object.prototype.hasOwnProperty.call(rightRecord, key)
      && samePresentationValue(leftRecord[key], rightRecord[key])
    ));
}

function sameNodeState<T extends DragStateNode>(left: T, right: T): boolean {
  const leftKeys = Object.keys(left) as Array<keyof T>;
  const rightKeys = Object.keys(right) as Array<keyof T>;
  if (leftKeys.length !== rightKeys.length) return false;
  return leftKeys.every((key) => {
    if (!(key in right)) return false;
    if (key === "position") {
      return left.position.x === right.position.x && left.position.y === right.position.y;
    }
    return samePresentationValue(left[key], right[key]);
  });
}

function reuseCurrentNode<T extends DragStateNode>(current: T | undefined, next: T): T {
  return current && sameNodeState(current, next) ? current : next;
}

export function beginNodeDrag(
  activeDraggedNodeIds: Set<string>,
  fallbackNodeId: string,
  draggedNodeIds: readonly string[],
): void {
  activeDraggedNodeIds.clear();
  setDraggedNodeIds(activeDraggedNodeIds, fallbackNodeId, draggedNodeIds, true);
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
      const next = {
        ...current,
        ...settledNode,
        position: canonicalPosition,
        selected,
      } as T;
      delete next.dragging;
      return reuseCurrentNode(current, next);
    }

    const next = {
      ...current,
      ...node,
      position: current && isFinitePosition(current.position)
        ? current.position
        : canonicalPosition,
      dragging: true,
      selected,
    } as T;
    return reuseCurrentNode(current, next);
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

export function cancelNodeDrag<T extends DragStateNode>(
  canonicalNodes: readonly T[],
  currentNodes: readonly T[],
  activeDraggedNodeIds: Set<string>,
): T[] {
  activeDraggedNodeIds.clear();
  return reconcileDragAwareNodes(canonicalNodes, currentNodes, activeDraggedNodeIds);
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
