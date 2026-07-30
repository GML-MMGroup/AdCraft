import { describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
  CanvasRuntimeSnapshotV2,
} from "../../../types-v2.ts";
import {
  findAvailableCanvasPosition,
  inputRoleForSourceNode,
  incrementalPlacementForNodes,
  toAgentCanvasFlowEdges,
  toAgentCanvasFlowNodes,
} from "./canvasGraphModel.ts";

function node(nodeId: string, nodeType: CanvasNodeV2["node_type"]): CanvasNodeV2 {
  return {
    node_id: nodeId,
    workflow_id: "workflow-1",
    node_type: nodeType,
    creative_role: creativeRoleForNodeType(nodeType),
    role_contract_version: "ad-media-role-v1",
    title: nodeId,
    status: "draft",
    summary_prompt: null,
    generation_prompt: null,
    structured_content: {},
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: nodeType === "image" ? "asset-1" : null,
    position: { x: 40, y: 60 },
    revision: 1,
    error: null,
    variation_draft: null,
    created_at: "2026-07-28T00:00:00Z",
    updated_at: "2026-07-28T00:00:00Z",
  };
}

function creativeRoleForNodeType(nodeType: CanvasNodeV2["node_type"]): CanvasNodeV2["creative_role"] {
  switch (nodeType) {
    case "text":
      return "general_text";
    case "script":
      return "script";
    case "image":
      return "general_image";
    case "video":
      return "general_video";
    case "audio":
      return "general_audio";
    case "editing":
      return "editing";
  }
}

const workflow: AgentCanvasWorkflowV2 = {
  workflow_id: "workflow-1",
  project_id: "project-1",
  workflow_schema_version: 2,
  canvas_model: "agent_canvas_v1",
  revision: 3,
  layout_revision: 1,
  nodes: [node("image-1", "image"), node("video-1", "video")],
  bindings: [{
    binding_id: "binding-1",
    workflow_id: "workflow-1",
    source: { kind: "node_output", source_node_id: "image-1" },
    target_node_id: "video-1",
    input_role: "image_reference",
    required: true,
    enabled: true,
    order: 0,
    label: null,
    metadata: {},
    created_at: "2026-07-28T00:00:00Z",
    updated_at: "2026-07-28T00:00:00Z",
  }],
  assets: [{
    asset_id: "asset-1",
    media_type: "image",
    source_type: "generated",
    display_name: "Frame",
    mime_type: "image/webp",
    status: "ready",
    preview_url: "/frame.webp",
    media_url: "/frame.webp",
    width: 1024,
    height: 1024,
    duration_seconds: null,
    checksum: "frame",
  }],
};

const runtime: CanvasRuntimeSnapshotV2 = {
  workflow_id: "workflow-1",
  active_execution_id: "execution-1",
  execution_status: "running",
  node_runtime: {
    "image-1": {
      node_id: "image-1",
      visible_status: "working",
      phase: "running",
      execution_id: "execution-1",
      provider_task_id: null,
      waiting_for_node_ids: [],
      blocked_by_node_ids: [],
      attempt_no: 1,
      updated_at: "2026-07-28T00:00:01Z",
      error: null,
    },
  },
  queued_node_ids: [],
  working_node_ids: ["image-1"],
  waiting_node_ids: [],
  ready_node_ids: [],
  failed_node_ids: [],
  events_cursor: 2,
  updated_at: "2026-07-28T00:00:01Z",
};

describe("canvasGraphModel", () => {
  it("maps canonical nodes, assets and node runtime directly into React Flow data", () => {
    const nodes = toAgentCanvasFlowNodes(workflow, runtime, {
      onRun: vi.fn(),
      onRetry: vi.fn(),
      onExport: vi.fn(),
      onOpenMedia: vi.fn(),
    });

    expect(nodes).toHaveLength(2);
    expect(nodes[0]).toMatchObject({
      id: "image-1",
      type: "agentCanvas",
      position: { x: 40, y: 60 },
      data: {
        node: { node_id: "image-1" },
        asset: { asset_id: "asset-1" },
        runtime: { visible_status: "working" },
      },
    });
  });

  it("renders only backend bindings as edges", () => {
    expect(toAgentCanvasFlowEdges(workflow.bindings)).toEqual([expect.objectContaining({
      id: "binding-1",
      source: "image-1",
      target: "video-1",
    })]);
  });

  it("selects explicit input roles from canonical source node media types", () => {
    expect(inputRoleForSourceNode(node("brief", "text"))).toBe("text_context");
    expect(inputRoleForSourceNode(node("script", "script"))).toBe("text_context");
    expect(inputRoleForSourceNode(node("image", "image"))).toBe("image_reference");
    expect(inputRoleForSourceNode(node("video", "video"))).toBe("video_reference");
    expect(inputRoleForSourceNode(node("audio", "audio"))).toBe("audio_reference");
    expect(inputRoleForSourceNode(node("editing", "editing"))).toBe("video_reference");
  });

  it("places a new node near the preferred point without overlapping existing cards", () => {
    const existing = [
      { ...node("center", "image"), position: { x: 100, y: 100 } },
      { ...node("right", "video"), position: { x: 440, y: 100 } },
    ];

    expect(findAvailableCanvasPosition(existing, { x: 100, y: 100 })).toEqual({
      x: -240,
      y: 100,
    });
  });

  it("places only newly created nodes from backend placement hints", () => {
    const source = { ...node("source", "image"), position: { x: 100, y: 100 } };
    const unrelated = { ...node("unrelated", "video"), position: { x: 460, y: 100 } };
    const sibling = { ...node("sibling", "image"), position: { x: 460, y: 100 } };

    const positions = incrementalPlacementForNodes(
      [source, unrelated, sibling],
      ["sibling"],
      [{
        intent: "right_sibling",
        anchor_node_id: "source",
        group_key: null,
      }],
      { x: 200, y: 200 },
    );

    expect(positions).toEqual([
      { node_id: "sibling", x: 780, y: 100 },
    ]);
    expect(source.position).toEqual({ x: 100, y: 100 });
    expect(unrelated.position).toEqual({ x: 460, y: 100 });
  });

  it("keeps sibling-only Working state when the generated variation runs", () => {
    const source = {
      ...node("source", "image"),
      status: "ready" as const,
      output_asset_id: "asset-source",
    };
    const sibling = node("sibling", "image");
    const variationWorkflow = {
      ...workflow,
      nodes: [source, sibling],
      assets: [{
        ...workflow.assets[0]!,
        asset_id: "asset-source",
      }],
    };
    const variationRuntime: CanvasRuntimeSnapshotV2 = {
      ...runtime,
      node_runtime: {
        sibling: {
          ...runtime.node_runtime["image-1"]!,
          node_id: "sibling",
        },
      },
      working_node_ids: ["sibling"],
    };

    const nodes = toAgentCanvasFlowNodes(variationWorkflow, variationRuntime, {
      onRun: vi.fn(),
      onRetry: vi.fn(),
      onExport: vi.fn(),
      onOpenMedia: vi.fn(),
    });

    expect(nodes.find((item) => item.id === "source")?.data.runtime).toBeNull();
    expect(nodes.find((item) => item.id === "source")?.data.node.status).toBe("ready");
    expect(nodes.find((item) => item.id === "sibling")?.data.runtime?.visible_status).toBe("working");
  });
});
