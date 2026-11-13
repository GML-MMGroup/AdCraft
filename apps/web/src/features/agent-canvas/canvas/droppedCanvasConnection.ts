import { Position, type FinalConnectionState, type XYPosition } from "@xyflow/react";
import type { CanvasNodeTypeV2 } from "../../../types-v2.ts";
import { nodeBorderPointFromHandleCenter } from "./canvasConnectionGeometry.ts";
import { agentCanvasNodeSize } from "./nodeGeometry.ts";

export interface DroppedCanvasConnection {
  workflowId: string;
  anchorNodeId: string;
  direction: "upstream" | "downstream";
  point: XYPosition;
  flowPoint: XYPosition;
  from: XYPosition;
  fromPosition: Position;
  creating?: boolean;
  createdNodeId?: string;
}

export function droppedCanvasConnection(
  workflowId: string,
  event: MouseEvent | TouchEvent,
  connection: FinalConnectionState,
  screenToFlowPosition: (point: XYPosition) => XYPosition,
): DroppedCanvasConnection | null {
  if (connection.isValid || connection.toNode || !connection.fromNode || !connection.fromHandle
    || !connection.from || !connection.fromPosition) return null;
  const pointer = "changedTouches" in event ? event.changedTouches[0] : event;
  if (!pointer) return null;
  // Touch events retain the start element as their target; hit-test the release instead.
  const element = document.elementFromPoint(pointer.clientX, pointer.clientY);
  if (!element?.classList.contains("react-flow__pane")) return null;
  const point = { x: pointer.clientX, y: pointer.clientY };
  return {
    workflowId,
    anchorNodeId: connection.fromNode.id,
    direction: connection.fromHandle.type === "source" ? "downstream" : "upstream",
    point,
    flowPoint: screenToFlowPosition(point),
    from: nodeBorderPointFromHandleCenter(connection.from, connection.fromPosition),
    fromPosition: connection.fromPosition,
  };
}

export function droppedCanvasNodePosition(connection: DroppedCanvasConnection, nodeType: CanvasNodeTypeV2): XYPosition {
  const size = agentCanvasNodeSize(nodeType);
  // Put the new card's connected border at the released endpoint.
  return {
    x: connection.flowPoint.x - (connection.direction === "upstream" ? size.width : 0),
    y: connection.flowPoint.y - size.height / 2,
  };
}
