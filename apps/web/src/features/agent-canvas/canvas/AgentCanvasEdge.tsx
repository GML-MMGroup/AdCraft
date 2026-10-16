import {
  BaseEdge,
  getBezierPath,
  type EdgeProps,
} from "@xyflow/react";
import { memo, type CSSProperties } from "react";

import { nodeBorderPointFromHandleBoundary } from "./canvasConnectionGeometry.ts";

import { canvasConnectionColor } from "./connection-effects/connectionColor.ts";
import { CanvasEdgeFlow } from "./connection-effects/CanvasEdgeFlow.tsx";

function AgentCanvasEdgeComponent({
  source: sourceNodeId,
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
    <g className="canvas-colored-connection" style={{ "--connection-color": canvasConnectionColor(sourceNodeId) } as CSSProperties}>
      <BaseEdge
        id={id}
        path={path}
        markerStart={markerStart}
        markerEnd={markerEnd}
        style={style}
        interactionWidth={interactionWidth}
      />
      <CanvasEdgeFlow path={path} />
    </g>
  );
}

export const AgentCanvasEdge = memo(AgentCanvasEdgeComponent);
