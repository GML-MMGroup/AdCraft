import { describe, expect, it } from "vitest";

import type { CanvasNodeV2 } from "../../../types-v2.ts";
import { nodeRunRequest } from "./runRequest.ts";

function draftNode(): CanvasNodeV2 {
  return {
    node_id: "node-video-1",
    workflow_id: "workflow-1",
    node_type: "video",
    creative_role: "general_video",
    role_contract_version: "ad-media-role-v1",
    title: "Video",
    status: "draft",
    summary_prompt: null,
    generation_prompt: "Launch film",
    structured_content: {},
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    variation_draft: null,
    created_at: "2026-07-28T00:00:00Z",
    updated_at: "2026-07-28T00:00:00Z",
  };
}

describe("nodeRunRequest", () => {
  it("preserves an explicit Retry click before Workflow status catches up with runtime", () => {
    expect(nodeRunRequest(draftNode(), true)).toEqual({
      scope: "selected_nodes",
      node_ids: ["node-video-1"],
      retry_failed: true,
      source_action: "retry_failed",
    });
  });

  it("runs a normal Draft without retry semantics", () => {
    expect(nodeRunRequest(draftNode())).toEqual({
      scope: "selected_nodes",
      node_ids: ["node-video-1"],
      retry_failed: false,
      source_action: "node_run",
    });
  });
});
