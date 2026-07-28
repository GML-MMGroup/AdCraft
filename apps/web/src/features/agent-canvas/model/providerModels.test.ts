import { describe, expect, it } from "vitest";

import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../../types-v2.ts";
import { providerInputTypes } from "./providerModels.ts";

function node(nodeId: string, nodeType: CanvasNodeV2["node_type"]): CanvasNodeV2 {
  return {
    node_id: nodeId,
    workflow_id: "workflow-1",
    node_type: nodeType,
    semantic_role: nodeType,
    role_contract_version: "ad-media-role-v1",
    title: nodeType,
    status: "ready",
    summary_prompt: null,
    generation_prompt: null,
    structured_content: {},
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: nodeType === "image" || nodeType === "video" || nodeType === "audio"
      ? `${nodeId}-asset`
      : null,
    video_skill_run_id: null,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    created_at: "2026-07-28T00:00:00Z",
    updated_at: "2026-07-28T00:00:00Z",
  };
}

describe("providerInputTypes", () => {
  it("derives the complete provider input set from node and image-asset bindings", () => {
    const workflow: AgentCanvasWorkflowV2 = {
      workflow_id: "workflow-1",
      project_id: "project-1",
      workflow_schema_version: 2,
      canvas_model: "agent_canvas_v1",
      revision: 3,
      nodes: [
        node("script-1", "script"),
        node("video-1", "video"),
        { ...node("target-1", "video"), status: "draft", output_asset_id: null },
      ],
      bindings: [
        {
          binding_id: "binding-script",
          workflow_id: "workflow-1",
          source: { kind: "node", node_id: "script-1" },
          target_node_id: "target-1",
          binding_kind: "script_context",
          required: true,
          display_order: 0,
          created_at: "2026-07-28T00:00:00Z",
        },
        {
          binding_id: "binding-video",
          workflow_id: "workflow-1",
          source: { kind: "node", node_id: "video-1" },
          target_node_id: "target-1",
          binding_kind: "video_reference",
          required: false,
          display_order: 1,
          created_at: "2026-07-28T00:00:00Z",
        },
        {
          binding_id: "binding-image",
          workflow_id: "workflow-1",
          source: { kind: "image_asset", asset_id: "asset-reference" },
          target_node_id: "target-1",
          binding_kind: "image_reference",
          required: false,
          display_order: 2,
          created_at: "2026-07-28T00:00:00Z",
        },
      ],
      assets: [],
    };

    expect(providerInputTypes(workflow, "target-1")).toEqual(["image", "text", "video"]);
  });
});
