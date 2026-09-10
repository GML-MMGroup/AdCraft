import { useState } from "react";
import { createRoot } from "react-dom/client";
import { ReactFlow, type Connection, type Edge, type IsValidConnection } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { AgentCanvasNodeRenderer, type AgentCanvasFlowNode } from "../../src/features/agent-canvas/canvas/AgentCanvasNode.tsx";
import { AgentCanvasEdge } from "../../src/features/agent-canvas/canvas/AgentCanvasEdge.tsx";
import { AgentCanvasConnectionLine } from "../../src/features/agent-canvas/canvas/AgentCanvasConnectionLine.tsx";
import { AGENT_CANVAS_CONNECTION_RADIUS, AGENT_CANVAS_EDGE_TYPE } from "../../src/features/agent-canvas/canvas/canvasConnectionGeometry.ts";
import { connectionRuleForPair } from "../../src/features/agent-canvas/canvas/connectionPolicy.ts";
import type { CanvasConnectionPolicyV2, CanvasNodeV2, ProjectAssetSummaryV2 } from "../../src/types-v2.ts";

const query = new URLSearchParams(location.search);
const zoom = Number(query.get("zoom") ?? 1);
const shape = query.get("shape") ?? "square";
const dimensions = shape === "landscape" ? [1600, 900] : shape === "portrait" ? [900, 1600] : [1000, 1000];
const policy = {
  input_roles: [{ source_node_type: "image", target_node_type: "image", roles: ["image_reference"], default_role: "image_reference" }],
} as CanvasConnectionPolicyV2;

function makeNode(id: string, x: number, y: number, nodeType: "image" | "text" = "image"): AgentCanvasFlowNode {
  const node: CanvasNodeV2 = {
    node_id: id, workflow_id: "connection-fixture", node_type: nodeType,
    creative_role: nodeType === "image" ? "general_image" : "general_text",
    role_contract_version: "ad-media-role-v1", title: id, status: "draft", execution_mode: "generative",
    summary_prompt: null, generation_prompt: null, structured_content: {},
    model_id: null, model_selection_mode: "default", model_ref: null, model_summary: null,
    parameters: {}, metadata: {}, parameter_provenance: {}, prompt_context_snapshot_id: null,
    prompt_presentation: null, prompt_preparation: null,
    output_asset_id: null, output_asset_version_id: null, latest_attempt: null,
    position: { x, y }, revision: 1, error: null,
    created_at: "2026-09-07T00:00:00Z", updated_at: "2026-09-07T00:00:00Z",
  };
  const asset = {
    asset_id: `${id}-asset`, version_id: "v1", media_type: "image",
    status: "ready", width: dimensions[0], height: dimensions[1],
    preview_url: "/api/v2/assets/connection-fixture/preview?v=v1",
    media_url: "/api/v2/assets/connection-fixture/preview?v=v1",
  } as ProjectAssetSummaryV2;
  return { id, type: "agentCanvas", position: node.position, data: { node, asset: nodeType === "image" ? asset : null } };
}

const nodes = [makeNode("source", 80, 90), makeNode("target", 520, 190), makeNode("invalid", 520, 620, "text")];
const nodeTypes = { agentCanvas: AgentCanvasNodeRenderer };
const edgeTypes = { [AGENT_CANVAS_EDGE_TYPE]: AgentCanvasEdge };
const isValidConnection: IsValidConnection = (connection) => {
  const source = nodes.find((node) => node.id === connection.source);
  const target = nodes.find((node) => node.id === connection.target);
  return !!source && !!target && source.id !== target.id
    && !!connectionRuleForPair(policy, source.data.node.node_type, target.data.node.node_type);
};

function App() {
  const [edges, setEdges] = useState<Edge[]>([]);
  const [submits, setSubmits] = useState(0);
  const connect = (connection: Connection) => {
    setSubmits((count) => count + 1);
    setEdges((current) => [...current, { ...connection, id: `edge-${current.length}`, type: AGENT_CANVAS_EDGE_TYPE }]);
  };
  return (
    <main style={{ width: "100vw", height: "100vh" }}>
      <output data-testid="submits" style={{ position: "absolute", right: 8, top: 8, zIndex: 10 }}>{submits}</output>
      <ReactFlow<AgentCanvasFlowNode>
        nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
        connectionLineComponent={AgentCanvasConnectionLine} connectionRadius={AGENT_CANVAS_CONNECTION_RADIUS}
        isValidConnection={isValidConnection} onConnect={connect}
        defaultViewport={{ x: 0, y: 0, zoom }} minZoom={0.25} maxZoom={2}
        autoPanOnConnect={false} nodesDraggable={false} onlyRenderVisibleElements
      />
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
