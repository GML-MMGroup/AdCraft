import {
  Background,
  BackgroundVariant,
  ConnectionLineType,
  Controls,
  MarkerType,
  MiniMap,
  type ReactFlowProps,
} from "@xyflow/react";
import { WorkflowCanvas } from "../../../components/WorkflowCanvas";
import { DEFAULT_LAYOUT_VIEWPORT_PADDING, edgeStyle, portColor } from "../canvas/workflowCanvasModel.ts";
import type { CanvasEdge, CanvasNode } from "../types.ts";

type CanvasProps = ReactFlowProps<CanvasNode, CanvasEdge>;

export type WorkflowCanvasSurfaceModel = {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  nodeTypes: CanvasProps["nodeTypes"];
  isRestoringWorkspace: boolean;
  workspaceRestoreError?: string | null;
};

export type WorkflowCanvasSurfaceActions = Pick<
  CanvasProps,
  | "onInit"
  | "onNodesChange"
  | "onEdgesChange"
  | "onConnect"
  | "onReconnect"
  | "onReconnectEnd"
  | "isValidConnection"
  | "onNodeClick"
  | "onEdgeClick"
  | "onNodeDragStop"
  | "onPaneClick"
  | "onNodesDelete"
  | "onEdgesDelete"
>;

export function WorkflowCanvasSurface({
  model,
  actions,
}: {
  model: WorkflowCanvasSurfaceModel;
  actions: WorkflowCanvasSurfaceActions;
}) {
  return (
    <div className="workflow-board">
      <WorkflowCanvas<CanvasNode, CanvasEdge>
        nodes={model.nodes}
        edges={model.edges}
        nodeTypes={model.nodeTypes}
        onInit={actions.onInit}
        onNodesChange={actions.onNodesChange}
        onEdgesChange={actions.onEdgesChange}
        onConnect={actions.onConnect}
        onReconnect={actions.onReconnect}
        onReconnectEnd={actions.onReconnectEnd}
        isValidConnection={actions.isValidConnection}
        onNodeClick={actions.onNodeClick}
        onEdgeClick={actions.onEdgeClick}
        onNodeDragStop={actions.onNodeDragStop}
        onPaneClick={actions.onPaneClick}
        onNodesDelete={actions.onNodesDelete}
        onEdgesDelete={actions.onEdgesDelete}
        fitView
        fitViewOptions={{ padding: DEFAULT_LAYOUT_VIEWPORT_PADDING }}
        onlyRenderVisibleElements
        minZoom={0.05}
        maxZoom={2}
        nodesDraggable
        nodesConnectable
        edgesReconnectable
        elementsSelectable
        connectOnClick
        connectionRadius={32}
        connectionLineType={ConnectionLineType.Bezier}
        defaultEdgeOptions={{
          type: "default",
          markerEnd: { type: MarkerType.ArrowClosed, color: portColor("data") },
          style: edgeStyle("data"),
        }}
        deleteKeyCode={["Backspace", "Delete"]}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1.7} color="rgba(108, 93, 171, 0.28)" />
        <Controls position="bottom-left" />
        <MiniMap
          position="bottom-right"
          nodeColor="rgba(108, 93, 171, 0.82)"
          maskColor="rgba(255, 255, 255, 0.46)"
          pannable
          zoomable
        />
      </WorkflowCanvas>
      {model.isRestoringWorkspace || model.workspaceRestoreError ? (
        <div className="workflow-restore-state" role="status">
          <strong>{model.workspaceRestoreError ? "Project restore failed" : "Restoring project"}</strong>
          <span>{model.workspaceRestoreError ?? "Loading the current project state from local storage."}</span>
        </div>
      ) : null}
    </div>
  );
}
