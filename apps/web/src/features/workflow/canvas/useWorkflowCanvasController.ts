import { useState, type Dispatch, type SetStateAction } from "react";
import {
  useEdgesState,
  useNodesState,
  type EdgeChange,
  type NodeChange,
  type ReactFlowInstance,
} from "@xyflow/react";
import type { WorkflowGraph, WorkflowNode } from "../../../types";
import type { CanvasEdge, CanvasNode } from "../types";

export type WorkflowCanvasControllerArgs = {
  workflow: WorkflowGraph | null;
  initialNodes: WorkflowNode[];
};

export type WorkflowCanvasController = {
  state: {
    selectedNodeId: string;
    selectedEdgeId: string | null;
    reactFlow: ReactFlowInstance<CanvasNode, CanvasEdge> | null;
    canvasNodes: WorkflowNode[];
    flowNodes: CanvasNode[];
    flowEdges: CanvasEdge[];
  };
  actions: {
    setSelectedNodeId: Dispatch<SetStateAction<string>>;
    setSelectedEdgeId: Dispatch<SetStateAction<string | null>>;
    setReactFlow: (instance: ReactFlowInstance<CanvasNode, CanvasEdge> | null) => void;
    setCanvasNodes: Dispatch<SetStateAction<WorkflowNode[]>>;
    setFlowNodes: Dispatch<SetStateAction<CanvasNode[]>>;
    setFlowEdges: Dispatch<SetStateAction<CanvasEdge[]>>;
    onNodesChange: (changes: NodeChange<CanvasNode>[]) => void;
    onEdgesChange: (changes: EdgeChange<CanvasEdge>[]) => void;
  };
};

export function useWorkflowCanvasController({ initialNodes }: WorkflowCanvasControllerArgs): WorkflowCanvasController {
  const [selectedNodeId, setSelectedNodeId] = useState("prompt");
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [reactFlow, setReactFlow] = useState<ReactFlowInstance<CanvasNode, CanvasEdge> | null>(null);
  const [canvasNodes, setCanvasNodes] = useState<WorkflowNode[]>(initialNodes);
  const [flowNodes, setFlowNodes, onNodesChange] = useNodesState<CanvasNode>([]);
  const [flowEdges, setFlowEdges, onEdgesChange] = useEdgesState<CanvasEdge>([]);

  return {
    state: {
      selectedNodeId,
      selectedEdgeId,
      reactFlow,
      canvasNodes,
      flowNodes,
      flowEdges,
    },
    actions: {
      setSelectedNodeId,
      setSelectedEdgeId,
      setReactFlow,
      setCanvasNodes,
      setFlowNodes,
      setFlowEdges,
      onNodesChange,
      onEdgesChange,
    },
  };
}
