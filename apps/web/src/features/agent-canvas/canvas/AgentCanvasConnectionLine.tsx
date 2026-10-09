import {
  getBezierPath,
  type ConnectionLineComponentProps,
} from "@xyflow/react";
import { useLayoutEffect, useRef, useState } from "react";

import type { AgentCanvasFlowNode } from "./AgentCanvasNode.tsx";
import { nodeBorderPointFromHandleCenter } from "./canvasConnectionGeometry.ts";
import { canvasConnectionColor } from "./connection-effects/connectionColor.ts";
import { CanvasConnectionSpark } from "./connection-effects/CanvasConnectionSpark.tsx";

export function AgentCanvasConnectionLine({
  connectionLineStyle,
  connectionStatus,
  fromPosition,
  fromX,
  fromY,
  fromNode,
  fromHandle,
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

  const pathRef = useRef<SVGPathElement>(null);
  const [tail, setTail] = useState<{ x: number; y: number; dash: string; path: string } | null>(null);
  const valid = connectionStatus === "valid" && Boolean(toHandle && toNode);
  useLayoutEffect(() => {
    const element = pathRef.current;
    if (!valid || !element?.getTotalLength) { setTail(null); return; }
    const length = element.getTotalLength();
    const tailLength = Math.min(40, length * .35);
    const start = element.getPointAtLength(length - tailLength);
    setTail({ x: start.x, y: start.y, dash: `${length - tailLength} ${length}`, path });
  }, [path, valid]);
  const activeTail = valid && tail?.path === path ? tail : null;
  const color = canvasConnectionColor(fromHandle?.type === "target" ? toNode?.id ?? "" : fromNode.id ?? "");

  return (
    <>
    <path
      ref={pathRef}
      className="react-flow__connection-path agent-canvas-connection-line"
      d={path}
      data-connection-status={connectionStatus ?? "pending"}
      fill="none"
      style={{ ...connectionLineStyle, strokeDasharray: activeTail?.dash }}
    />
    {activeTail ? <CanvasConnectionSpark start={activeTail} end={{ x: toX, y: toY }} color={color}/> : null}
    </>
  );
}
