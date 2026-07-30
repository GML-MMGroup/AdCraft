import { describe, expect, it } from "vitest";

import type { CanvasNodeV2 } from "../../../types-v2.ts";
import {
  bindingRequestForImageAsset,
  bindingRequestForNode,
} from "./bindingRequests.ts";

function sourceNode(nodeType: CanvasNodeV2["node_type"]): CanvasNodeV2 {
  return {
    node_id: `node-${nodeType}`,
    workflow_id: "workflow-1",
    node_type: nodeType,
    semantic_role: nodeType === "image" ? "storyboard_grid" : nodeType,
    role_contract_version: "ad-media-role-v1",
    title: nodeType,
    status: "ready",
    summary_prompt: null,
    generation_prompt: null,
    structured_content: {},
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: nodeType === "image" ? "asset-grid" : null,
    video_skill_run_id: null,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    variation_draft: null,
    created_at: "2026-07-30T00:00:00Z",
    updated_at: "2026-07-30T00:00:00Z",
  };
}

describe("Agent Canvas binding requests", () => {
  it("creates required node dependencies with canonical roles", () => {
    expect(bindingRequestForNode(sourceNode("image"), "node-video", 0)).toEqual({
      source: { kind: "node", node_id: "node-image" },
      target_node_id: "node-video",
      binding_kind: "image_reference",
      input_role: "visual_reference",
      required: true,
      display_order: 0,
    });
    expect(bindingRequestForNode(sourceNode("video"), "node-editing", 1))
      .toMatchObject({
        binding_kind: "video_reference",
        input_role: "source_video",
        required: true,
      });
  });

  it("keeps complete image assets as required visual references", () => {
    expect(bindingRequestForImageAsset("asset-scene-board", "node-video", 2)).toEqual({
      source: { kind: "image_asset", asset_id: "asset-scene-board" },
      target_node_id: "node-video",
      binding_kind: "image_reference",
      input_role: "visual_reference",
      required: true,
      display_order: 2,
    });
  });
});
