import { Position, type XYPosition } from "@xyflow/react";

export const AGENT_CANVAS_HANDLE_CENTER_OFFSET = 12;
export const AGENT_CANVAS_HANDLE_HIT_SIZE = 40;
export const AGENT_CANVAS_HANDLE_RING_SIZE = 14;
export const AGENT_CANVAS_CONNECTION_RADIUS = 24;
export const AGENT_CANVAS_EDGE_TYPE = "agentCanvasEdge";
// Permanent edge props use the outer Handle boundary; preview props use its center.
export const AGENT_CANVAS_HANDLE_BORDER_INSET =
  AGENT_CANVAS_HANDLE_CENTER_OFFSET + AGENT_CANVAS_HANDLE_HIT_SIZE / 2;

export function nodeBorderPointFromHandleCenter(
  point: XYPosition,
  position: Position,
): XYPosition {
  return nodeBorderPointFromHandleBoundary(point, position, AGENT_CANVAS_HANDLE_CENTER_OFFSET);
}

export function nodeBorderPointFromHandleBoundary(
  point: XYPosition,
  position: Position,
  inset = AGENT_CANVAS_HANDLE_BORDER_INSET,
): XYPosition {
  switch (position) {
    case Position.Left:
      return { x: point.x + inset, y: point.y };
    case Position.Right:
      return { x: point.x - inset, y: point.y };
    case Position.Top:
      return { x: point.x, y: point.y + inset };
    case Position.Bottom:
      return { x: point.x, y: point.y - inset };
  }
}
