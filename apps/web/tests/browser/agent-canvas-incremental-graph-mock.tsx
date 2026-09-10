import { StrictMode, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
  CanvasRuntimeSnapshotV2,
  NodeRuntimeV2,
} from "../../src/types-v2.ts";
import {
  highlightNodeRelatedCanvasEdges,
  patchAgentCanvasFlowNodes,
  reconcileCanvasFlowSnapshot,
  runtimeChangedCanvasNodeIds,
  toAgentCanvasFlowEdges,
  toAgentCanvasFlowNodes,
} from "../../src/features/agent-canvas/canvas/canvasGraphModel.ts";

const workflow = makeWorkflow();

function App() {
  const initialNodes = useRef(toAgentCanvasFlowNodes(workflow, makeRuntime("working"), {})).current;
  const initialEdges = useRef(toAgentCanvasFlowEdges(workflow.bindings, workflow.nodes)).current;
  const nodesRef = useRef(initialNodes);
  const edgesRef = useRef(initialEdges);
  const [report, setReport] = useState({
    nodeReplacements: 0,
    edgeReplacements: 0,
    nodeSnapshotReused: false,
    edgeSnapshotReused: false,
  });

  const updateRuntime = (status: "ready" | "working") => {
    const previous = nodesRef.current;
    const nextRuntime = makeRuntime(status);
    const changedNodeIds = runtimeChangedCanvasNodeIds(previous, nextRuntime);
    const next = patchAgentCanvasFlowNodes(workflow, nextRuntime, {}, previous, changedNodeIds);
    const committed = reconcileCanvasFlowSnapshot(previous, next);
    nodesRef.current = committed;
    setReport({
      nodeReplacements: countReplacements(previous, committed),
      edgeReplacements: 0,
      nodeSnapshotReused: committed === previous,
      edgeSnapshotReused: true,
    });
  };

  const updateSelection = (nodeId: string | null) => {
    const previous = edgesRef.current;
    const next = highlightNodeRelatedCanvasEdges(previous, nodeId, previous);
    const committed = reconcileCanvasFlowSnapshot(previous, next);
    edgesRef.current = committed;
    setReport({
      nodeReplacements: 0,
      edgeReplacements: countReplacements(previous, committed),
      nodeSnapshotReused: true,
      edgeSnapshotReused: committed === previous,
    });
  };

  return (
    <main>
      <h1>Canvas incremental graph updates</h1>
      <button type="button" onClick={() => updateRuntime("ready")}>Runtime update</button>
      <button type="button" onClick={() => updateRuntime("ready")}>Runtime no-op</button>
      <button type="button" onClick={() => updateSelection("video-1")}>Select video</button>
      <button type="button" onClick={() => updateSelection("image-1")}>Select image</button>
      <dl>
        <div><dt>Node replacements</dt><dd data-testid="node-replacements">{report.nodeReplacements}</dd></div>
        <div><dt>Edge replacements</dt><dd data-testid="edge-replacements">{report.edgeReplacements}</dd></div>
        <div><dt>Node snapshot reused</dt><dd data-testid="node-snapshot-reused">{String(report.nodeSnapshotReused)}</dd></div>
        <div><dt>Edge snapshot reused</dt><dd data-testid="edge-snapshot-reused">{String(report.edgeSnapshotReused)}</dd></div>
      </dl>
    </main>
  );
}

function countReplacements<T>(previous: readonly T[], next: readonly T[]) {
  return next.reduce((count, item, index) => count + (item === previous[index] ? 0 : 1), 0);
}

function makeWorkflow(): AgentCanvasWorkflowV2 {
  const nodes = [
    makeNode("image-1", "image"),
    makeNode("video-1", "video"),
    makeNode("audio-1", "audio"),
    makeNode("editing-1", "editing"),
  ];
  return {
    workflow_id: "workflow-incremental",
    project_id: "project-incremental",
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: 1,
    layout_revision: 1,
    nodes,
    bindings: [
      makeBinding("binding-image-video", "image-1", "video-1"),
      makeBinding("binding-video-editing", "video-1", "editing-1"),
      makeBinding("binding-audio-editing", "audio-1", "editing-1"),
    ],
    assets: [],
  } as AgentCanvasWorkflowV2;
}

function makeNode(nodeId: string, nodeType: CanvasNodeV2["node_type"]): CanvasNodeV2 {
  return {
    node_id: nodeId,
    workflow_id: "workflow-incremental",
    node_type: nodeType,
    creative_role: "general_text",
    role_contract_version: "v1",
    title: nodeId,
    status: "draft",
    summary_prompt: null,
    generation_prompt: null,
    structured_content: {},
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    output_asset_id: null,
    created_at: "2026-09-03T00:00:00Z",
    updated_at: "2026-09-03T00:00:00Z",
  } as CanvasNodeV2;
}

function makeBinding(bindingId: string, sourceNodeId: string, targetNodeId: string) {
  return {
    binding_id: bindingId,
    workflow_id: "workflow-incremental",
    source: { kind: "node_output", source_node_id: sourceNodeId },
    target_node_id: targetNodeId,
    input_role: "video_reference",
    enabled: true,
    order: 0,
    label: null,
    metadata: {},
    created_at: "2026-09-03T00:00:00Z",
    updated_at: "2026-09-03T00:00:00Z",
  };
}

function makeRuntime(status: "working" | "ready"): CanvasRuntimeSnapshotV2 {
  return {
    workflow_id: "workflow-incremental",
    active_execution_id: "execution-1",
    execution_status: "running",
    node_runtime: {
      "image-1": {
        node_id: "image-1",
        visible_status: status,
        phase: "running",
        execution_id: "execution-1",
        provider_task_id: null,
        waiting_for_node_ids: [],
        blocked_by_node_ids: [],
        attempt_no: 1,
        updated_at: "2026-09-03T00:00:01Z",
        error: null,
      } as NodeRuntimeV2,
    },
    queued_node_ids: [],
    working_node_ids: status === "working" ? ["image-1"] : [],
    waiting_node_ids: [],
    ready_node_ids: status === "ready" ? ["image-1"] : [],
    failed_node_ids: [],
    events_cursor: 1,
    updated_at: "2026-09-03T00:00:01Z",
  };
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
