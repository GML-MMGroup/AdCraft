import {
  BaseEdge,
  getBezierPath,
  type EdgeProps,
} from "@xyflow/react";
import { memo } from "react";

import { nodeBorderPointFromHandleBoundary } from "./canvasConnectionGeometry.ts";

function AgentCanvasEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerStart,
  markerEnd,
  style,
  interactionWidth,
}: EdgeProps) {
  const source = nodeBorderPointFromHandleBoundary(
    { x: sourceX, y: sourceY },
    sourcePosition,
  );
  const target = nodeBorderPointFromHandleBoundary(
    { x: targetX, y: targetY },
    targetPosition,
  );
  const [path] = getBezierPath({
    sourceX: source.x,
    sourceY: source.y,
    targetX: target.x,
    targetY: target.y,
    sourcePosition,
    targetPosition,
  });

  return (
    <BaseEdge
      id={id}
      path={path}
      markerStart={markerStart}
      markerEnd={markerEnd}
      style={style}
      interactionWidth={interactionWidth}
    />
  );
}

export const AgentCanvasEdge = memo(AgentCanvasEdgeComponent);
