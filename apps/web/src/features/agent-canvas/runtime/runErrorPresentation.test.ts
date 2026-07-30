import { describe, expect, it } from "vitest";

import { V2ApiError } from "../../../api/v2Client.ts";
import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";
import {
  presentAgentCanvasNodeError,
  presentAgentCanvasRunError,
} from "./runErrorPresentation.ts";

function node(nodeId: string, title: string): CanvasNodeV2 {
  return {
    node_id: nodeId,
    workflow_id: "workflow-1",
    node_type: "image",
    semantic_role: "generic_image",
    role_contract_version: "ad-media-role-v1",
    title,
    status: "draft",
    summary_prompt: null,
    generation_prompt: null,
    structured_content: {},
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    video_skill_run_id: null,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    variation_draft: null,
    created_at: "2026-07-30T00:00:00Z",
    updated_at: "2026-07-30T00:00:00Z",
  };
}

const workflow: AgentCanvasWorkflowV2 = {
  workflow_id: "workflow-1",
  project_id: "project-1",
  workflow_schema_version: 2,
  canvas_model: "agent_canvas_v1",
  revision: 1,
  layout_revision: 1,
  nodes: [
    node("node-storyboard", "Storyboard Grid"),
    node("node-scene", "Scene Design Board"),
  ],
  bindings: [],
  assets: [],
};

function error(code: string, details: Record<string, unknown> = {}) {
  return new V2ApiError({
    status: 409,
    code,
    message: code,
    details,
    violations: [],
    suggestedActions: [],
    payload: null,
  });
}

describe("Agent Canvas run error presentation", () => {
  it("identifies and highlights missing required upstream nodes", () => {
    expect(presentAgentCanvasRunError(error("upstream_inputs_not_ready", {
      missing_node_ids: ["node-storyboard", "node-scene"],
    }), workflow)).toEqual({
      message: "Generate the required inputs first: Storyboard Grid, Scene Design Board.",
      attentionNodeIds: ["node-storyboard", "node-scene"],
    });
  });

  it("explains the dual-grid contract without guessing from names", () => {
    expect(presentAgentCanvasRunError(
      error("storyboard_video_input_contract_invalid"),
      workflow,
    ).message).toMatch(/exactly one required Storyboard Grid and one required Scene Design Board/i);
  });

  it("explains reference limits, incompatible providers, and delivery failures", () => {
    expect(presentAgentCanvasRunError(error("canvas_reference_limit_exceeded", {
      media_type: "image",
      count: 10,
      limit: 9,
    }), workflow).message).toBe("This node has 10 image references; the selected model supports 9.");

    expect(presentAgentCanvasRunError(error("provider_inputs_unsupported", {
      compatible_model_ids: ["seedance-2", "seedance-lite"],
    }), workflow).message).toContain("seedance-2, seedance-lite");

    expect(presentAgentCanvasRunError(error("provider_reference_delivery_unavailable", {
      binding_id: "binding-video",
      asset_id: "asset-video",
    }), workflow).message).toContain("asset-video");
  });

  it("maps canonical asynchronous node errors without requiring request details", () => {
    expect(presentAgentCanvasNodeError({
      code: "storyboard_video_input_contract_invalid",
      message: "contract failed",
      retryable: false,
    })).toMatch(/Storyboard Grid.*Scene Design Board/i);
    expect(presentAgentCanvasNodeError({
      code: "provider_reference_delivery_unavailable",
      message: "delivery failed",
      retryable: true,
    })).toMatch(/cannot be delivered/i);
  });
});
