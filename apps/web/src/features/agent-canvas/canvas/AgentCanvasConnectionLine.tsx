import {
  getBezierPath,
  type ConnectionLineComponentProps,
} from "@xyflow/react";

import type { AgentCanvasFlowNode } from "./AgentCanvasNode.tsx";
import { nodeBorderPointFromHandleCenter } from "./canvasConnectionGeometry.ts";

export function AgentCanvasConnectionLine({
  connectionLineStyle,
  connectionStatus,
  fromPosition,
  fromX,
  fromY,
  toHandle,
  toNode,
  toPosition,
  toX,
  toY,
}: ConnectionLineComponentProps<AgentCanvasFlowNode>) {
  const source = nodeBorderPointFromHandleCenter(
    { x: fromX, y: fromY },
    fromPosition,
  );
  const target = connectionStatus === "valid" && toHandle && toNode
    ? nodeBorderPointFromHandleCenter({ x: toX, y: toY }, toPosition)
    : { x: toX, y: toY };
  const [path] = getBezierPath({
    sourceX: source.x,
    sourceY: source.y,
    targetX: target.x,
    targetY: target.y,
    sourcePosition: fromPosition,
    targetPosition: toPosition,
  });

  return (
    <path
      className="react-flow__connection-path agent-canvas-connection-line"
      d={path}
      data-connection-status={connectionStatus ?? "pending"}
      fill="none"
      style={connectionLineStyle}
    />
  );
}
