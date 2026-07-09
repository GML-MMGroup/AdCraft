import { useCallback, useMemo } from "react";
import {
  addEdge,
  reconnectEdge as reconnectReactFlowEdge,
  type Connection,
} from "@xyflow/react";
import type { WorkflowSaveEdgePayload } from "../../../types.ts";
import type { CanvasEdge, CanvasNode } from "../types.ts";
import { WorkflowCanvasNode } from "./WorkflowCanvasNode.tsx";
import {
  getNodeDefinition,
  getNodeInputPorts,
  getNodeOutputPorts,
  nodeRegistry,
} from "./nodePorts.ts";

export const nodeTypes = {
  workflowNode: WorkflowCanvasNode,
};

export type CanvasProjectionModuleArgs = {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  activeEdgeIds?: Iterable<string>;
};

export type CanvasProjectionModule = {
  nodeTypes: typeof nodeTypes;
  nodeRegistry: typeof nodeRegistry;
  projectedNodes: CanvasNode[];
  projectedEdges: CanvasEdge[];
  connectEdge: (connection: Connection, currentEdges: CanvasEdge[]) => CanvasEdge[];
  reconnectEdge: (oldEdge: CanvasEdge, connection: Connection, currentEdges: CanvasEdge[]) => CanvasEdge[];
  edgeToBackendPayload: (workflowId: string, edge: CanvasEdge) => WorkflowSaveEdgePayload;
  getNodeDefinition: typeof getNodeDefinition;
  getNodeInputPorts: typeof getNodeInputPorts;
  getNodeOutputPorts: typeof getNodeOutputPorts;
};

function withRuntimeEdgeState(edge: CanvasEdge, activeEdgeIds: Set<string>): CanvasEdge {
  const isRuntimeActive = activeEdgeIds.has(edge.id);
  const className = (edge.className ?? "")
    .split(/\s+/)
    .filter((item) => item && item !== "is-runtime-active-edge")
    .concat(isRuntimeActive ? ["is-runtime-active-edge"] : [])
    .join(" ");
  return {
    ...edge,
    animated: edge.animated || isRuntimeActive,
    className,
  };
}

export function edgeToBackendPayload(workflowId: string, edge: CanvasEdge): WorkflowSaveEdgePayload {
  return {
    id: edge.id,
    workflow_id: workflowId,
    source_node_id: edge.source,
    target_node_id: edge.target,
    source_handle: edge.sourceHandle ?? null,
    target_handle: edge.targetHandle ?? null,
    label: edge.label ? String(edge.label) : edge.data?.label,
    mapping: edge.data?.mapping,
    required: edge.data?.required,
  };
}

export function useCanvasProjectionModule(args: CanvasProjectionModuleArgs): CanvasProjectionModule {
  const activeEdgeIds = useMemo(() => new Set(args.activeEdgeIds ?? []), [args.activeEdgeIds]);
  const projectedNodes = useMemo(() => args.nodes, [args.nodes]);
  const projectedEdges = useMemo(
    () => args.edges.map((edge) => withRuntimeEdgeState(edge, activeEdgeIds)),
    [activeEdgeIds, args.edges],
  );

  const connectEdge = useCallback((connection: Connection, currentEdges: CanvasEdge[]) => addEdge(connection, currentEdges), []);
  const reconnectEdge = useCallback(
    (oldEdge: CanvasEdge, connection: Connection, currentEdges: CanvasEdge[]) => reconnectReactFlowEdge(oldEdge, connection, currentEdges),
    [],
  );

  return {
    nodeTypes,
    nodeRegistry,
    projectedNodes,
    projectedEdges,
    connectEdge,
    reconnectEdge,
    edgeToBackendPayload,
    getNodeDefinition,
    getNodeInputPorts,
    getNodeOutputPorts,
  };
}
