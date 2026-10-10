import type { Connection, Handle, InternalNode, XYPosition } from "@xyflow/react";
import { AGENT_CANVAS_CONNECTION_RADIUS } from "../canvasConnectionGeometry";

// Visual anticipation only. React Flow keeps its existing, smaller connection radius.
export const CONNECTION_PROXIMITY_SCREEN_RADIUS = 90;

export function findNearbyConnectionHandle(
  nodes: Iterable<InternalNode>,
  pointer: XYPosition,
  fromNodeId: string,
  fromHandle: Pick<Handle, "type" | "id">,
  zoom: number,
  validate?: (connection: Connection) => boolean,
) {
  if (!validate || zoom <= 0) return null;
  const reverse = fromHandle.type === "target";
  let closest: { nodeId: string; center: XYPosition; strength: number } | null = null;
  let nearest = CONNECTION_PROXIMITY_SCREEN_RADIUS;
  for (const node of nodes) {
    if (node.id === fromNodeId || node.hidden || node.connectable === false) continue;
    for (const handle of node.internals.handleBounds?.[reverse ? "source" : "target"] ?? []) {
      const center = {
        x: node.internals.positionAbsolute.x + handle.x + handle.width / 2,
        y: node.internals.positionAbsolute.y + handle.y + handle.height / 2,
      };
      const distance = Math.hypot(center.x - pointer.x, center.y - pointer.y) * zoom;
      if (distance >= nearest) continue;
      const connection: Connection = reverse
        ? { source: node.id, sourceHandle: handle.id ?? null, target: fromNodeId, targetHandle: fromHandle.id ?? null }
        : { source: fromNodeId, sourceHandle: fromHandle.id ?? null, target: node.id, targetHandle: handle.id ?? null };
      if (!validate(connection)) continue;
      nearest = distance;
      closest = {
        nodeId: node.id,
        center,
        strength: Math.min(1, (CONNECTION_PROXIMITY_SCREEN_RADIUS - distance)
          / Math.max(1, CONNECTION_PROXIMITY_SCREEN_RADIUS - AGENT_CANVAS_CONNECTION_RADIUS * zoom)),
      };
    }
  }
  return closest;
}
