import type { Edge } from "@xyflow/react";

export type FrozenCanvasEdgeSnapshot = {
  id: string;
  markup: string;
};

export function edgeIdsConnectedToNodes<T extends Pick<Edge, "id" | "source" | "target">>(
  edges: readonly T[],
  draggedNodeIds: ReadonlySet<string>,
): Set<string> {
  const liveEdgeIds = new Set<string>();
  if (!draggedNodeIds.size) return liveEdgeIds;

  for (const edge of edges) {
    if (draggedNodeIds.has(edge.source) || draggedNodeIds.has(edge.target)) {
      liveEdgeIds.add(edge.id);
    }
  }
  return liveEdgeIds;
}

export function partitionCanvasEdges<T extends Pick<Edge, "id" | "source" | "target">>(
  edges: readonly T[],
  draggedNodeIds: ReadonlySet<string>,
): { liveEdges: T[]; frozenEdges: T[] } {
  const liveEdgeIds = edgeIdsConnectedToNodes(edges, draggedNodeIds);
  const liveEdges: T[] = [];
  const frozenEdges: T[] = [];

  for (const edge of edges) {
    (liveEdgeIds.has(edge.id) ? liveEdges : frozenEdges).push(edge);
  }

  return { liveEdges, frozenEdges };
}

/**
 * Captures edge geometry before a drag starts. A missing path is deliberately
 * treated as an incomplete snapshot so callers can fall back to live edges.
 */
export function captureFrozenCanvasEdges(
  edgeIds: ReadonlySet<string>,
  root: ParentNode | null,
): FrozenCanvasEdgeSnapshot[] {
  if (!root || !edgeIds.size) return [];
  const snapshots: FrozenCanvasEdgeSnapshot[] = [];

  for (const group of root.querySelectorAll<SVGGElement>(".react-flow__edge")) {
    const id = group.dataset.id;
    if (!id || !edgeIds.has(id)) continue;
    const path = group.querySelector<SVGPathElement>(".react-flow__edge-path");
    if (!path?.getAttribute("d")) continue;
    snapshots.push({ id, markup: group.outerHTML });
  }

  return snapshots;
}
