import { memo } from "react";
import { ReactFlow, type Edge, type Node, type ReactFlowProps } from "@xyflow/react";

export type WorkflowCanvasProps<NodeType extends Node = Node, EdgeType extends Edge = Edge> = ReactFlowProps<NodeType, EdgeType>;

function WorkflowCanvasBase<NodeType extends Node = Node, EdgeType extends Edge = Edge>(props: WorkflowCanvasProps<NodeType, EdgeType>) {
  return <ReactFlow<NodeType, EdgeType> {...props} />;
}

export const WorkflowCanvas = memo(WorkflowCanvasBase) as typeof WorkflowCanvasBase;
