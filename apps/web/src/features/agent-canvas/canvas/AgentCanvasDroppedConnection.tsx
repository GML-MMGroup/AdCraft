import { getBezierPath, Position, useStore, ViewportPortal } from "@xyflow/react";
import { useEffect } from "react";
import type { DroppedCanvasConnection } from "./droppedCanvasConnection.ts";

export function AgentCanvasDroppedConnection({ connection, onConnected }: {
  connection: DroppedCanvasConnection;
  onConnected: () => void;
}) {
  const connected = useStore((state) => {
    if (!connection.createdNodeId) return false;
    const node = state.nodeLookup.get(connection.createdNodeId);
    return !!node?.internals.handleBounds && state.edges.some((edge) => (
      connection.direction === "downstream"
        ? edge.source === connection.anchorNodeId && edge.target === connection.createdNodeId
        : edge.source === connection.createdNodeId && edge.target === connection.anchorNodeId
    ));
  });
  useEffect(() => {
    if (connected) onConnected();
  }, [connected, onConnected]);
  const [path] = getBezierPath({
    sourceX: connection.from.x,
    sourceY: connection.from.y,
    sourcePosition: connection.fromPosition,
    targetX: connection.flowPoint.x,
    targetY: connection.flowPoint.y,
    targetPosition: connection.direction === "downstream" ? Position.Left : Position.Right,
  });
  if (connected) return null;
  return (
    <ViewportPortal>
      <svg aria-hidden="true" width="100%" height="100%" overflow="visible" style={{ position: "absolute", pointerEvents: "none" }}>
        <path className="agent-canvas-connection-line" data-connection-status="dropped" d={path} />
      </svg>
    </ViewportPortal>
  );
}
