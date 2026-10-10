import {
  getBezierPath,
  useStore,
  type ConnectionLineComponentProps,
} from "@xyflow/react";
import { useLayoutEffect, useRef, useState } from "react";

import type { AgentCanvasFlowNode } from "./AgentCanvasNode.tsx";
import { nodeBorderPointFromHandleCenter } from "./canvasConnectionGeometry.ts";
import { canvasConnectionColor } from "./connection-effects/connectionColor.ts";
import { CanvasConnectionSpark } from "./connection-effects/CanvasConnectionSpark.tsx";
import { findNearbyConnectionHandle } from "./connection-effects/connectionProximity.ts";

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
  const nodeLookup = useStore(state => state.nodeLookup);
  const zoom = useStore(state => state.transform[2]);
  const validate = useStore(state => state.isValidConnection);
  const nearby = connectionStatus == null && fromHandle
    ? findNearbyConnectionHandle(nodeLookup.values(), { x: toX, y: toY }, fromNode.id, fromHandle, zoom, validate)
    : null;
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
  const color = canvasConnectionColor(fromHandle?.type === "target" ? toNode?.id ?? nearby?.nodeId ?? "" : fromNode.id ?? "");

  return (
    <>
    <path
      ref={pathRef}
      className="react-flow__connection-path agent-canvas-connection-line"
      d={path}
      data-connection-status={connectionStatus ?? "pending"}
      data-proximity-target={nearby?.nodeId}
      fill="none"
      style={{ ...connectionLineStyle, strokeDasharray: activeTail?.dash }}
    />
    {activeTail ? <CanvasConnectionSpark start={activeTail} end={{ x: toX, y: toY }} color={color}/>
      : nearby ? <CanvasConnectionSpark start={{ x: toX, y: toY }} end={nearby.center} color={color} strength={nearby.strength}/> : null}
    </>
  );
}
