import { describe, expect, it } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  CanvasBindingV2,
  CanvasNodeV2,
  EditingNodeContentV2,
} from "../../../types-v2.ts";
import {
  buildEditingInputs,
  moveEditingVideoBinding,
  replaceEditingManifest,
} from "./editingModel.ts";

function node(
  nodeId: string,
  nodeType: CanvasNodeV2["node_type"],
  status: CanvasNodeV2["status"],
  outputAssetId: string | null,
  creativeRole: CanvasNodeV2["creative_role"] = nodeType === "video"
    ? "general_video"
    : nodeType === "audio"
      ? "general_audio"
      : "editing",
): CanvasNodeV2 {
  return {
    node_id: nodeId,
    workflow_id: "workflow-1",
    node_type: nodeType,
    creative_role: creativeRole,
    role_contract_version: "ad-media-role-v1",
    title: nodeId,
    status,
    summary_prompt: null,
    generation_prompt: null,
    structured_content: {},
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: outputAssetId,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    variation_draft: null,
    created_at: "2026-07-28T00:00:00Z",
    updated_at: "2026-07-28T00:00:00Z",
  };
}

function binding(
  bindingId: string,
  sourceNodeId: string,
  inputRole: CanvasBindingV2["input_role"],
  order: number,
): CanvasBindingV2 {
  return {
    binding_id: bindingId,
    workflow_id: "workflow-1",
    source: { kind: "node_output", source_node_id: sourceNodeId },
    target_node_id: "editing-1",
    input_role: inputRole,
    required: false,
    enabled: true,
    order,
    label: null,
    metadata: {},
    created_at: "2026-07-28T00:00:00Z",
    updated_at: "2026-07-28T00:00:00Z",
  };
}

const content: EditingNodeContentV2 = {
  manifest: {
    ordered_video_binding_ids: ["binding-video-2", "binding-video-1"],
    bgm_audio_binding_id: "binding-bgm",
    bgm_volume: 0.2,
    output: {
      resolution: null,
      aspect_ratio: null,
      fps: null,
      video_codec: "h264",
      audio_codec: "aac",
      container: "mp4",
    },
    manifest_revision: 4,
  },
  dirty: true,
  preview: {
    clips: [],
    bgm_binding_id: "binding-bgm",
    bgm_node_id: "bgm-1",
    bgm_asset_id: "asset-bgm",
    estimated_duration_seconds: 12,
    warnings: [],
  },
  last_successful_export: null,
  active_export: null,
};

const workflow: AgentCanvasWorkflowV2 = {
  workflow_id: "workflow-1",
  project_id: "project-1",
  workflow_schema_version: 2,
  canvas_model: "agent_canvas_v1",
  revision: 7,
  layout_revision: 1,
  nodes: [
    node("video-1", "video", "ready", "asset-video-1"),
    node("video-2", "video", "failed", "asset-video-2"),
    node("bgm-1", "audio", "ready", "asset-bgm", "bgm"),
    node("editing-1", "editing", "ready", "asset-final", "editing"),
  ],
  bindings: [
    binding("binding-video-1", "video-1", "video_reference", 0),
    binding("binding-video-2", "video-2", "video_reference", 1),
    binding("binding-bgm", "bgm-1", "audio_reference", 2),
  ],
  assets: [
    {
      asset_id: "asset-video-1",
      media_type: "video",
      source_type: "generated",
      display_name: "Shot 1",
      mime_type: "video/mp4",
      status: "ready",
      preview_url: "/shot-1.jpg",
      media_url: "/shot-1.mp4",
      width: 1920,
      height: 1080,
      duration_seconds: 6,
      checksum: "one",
    },
    {
      asset_id: "asset-video-2",
      media_type: "video",
      source_type: "generated",
      display_name: "Shot 2",
      mime_type: "video/mp4",
      status: "ready",
      preview_url: "/shot-2.jpg",
      media_url: "/shot-2.mp4",
      width: 1920,
      height: 1080,
      duration_seconds: 6,
      checksum: "two",
    },
    {
      asset_id: "asset-bgm",
      media_type: "audio",
      source_type: "generated",
      display_name: "BGM",
      mime_type: "audio/mpeg",
      status: "ready",
      preview_url: null,
      media_url: "/bgm.mp3",
      width: null,
      height: null,
      duration_seconds: 30,
      checksum: "bgm",
    },
  ],
};

describe("editingModel", () => {
  it("uses manifest binding IDs as the only canonical clip order", () => {
    const inputs = buildEditingInputs(workflow, "editing-1", content);

    expect(inputs.videos.map((item) => item.binding.binding_id)).toEqual([
      "binding-video-2",
      "binding-video-1",
    ]);
    expect(inputs.videos[0]?.node.status).toBe("failed");
    expect(inputs.videos[1]?.asset?.media_url).toBe("/shot-1.mp4");
    expect(inputs.bgm?.node.node_id).toBe("bgm-1");
  });

  it("moves one clip without synthesizing or dropping binding IDs", () => {
    expect(moveEditingVideoBinding(content.manifest, "binding-video-1", -1)
      .ordered_video_binding_ids).toEqual(["binding-video-1", "binding-video-2"]);
    expect(moveEditingVideoBinding(content.manifest, "missing", 1)).toBe(content.manifest);
  });

  it("builds the authoring payload from the manifest only", () => {
    expect(replaceEditingManifest(content, {
      ...content.manifest,
      bgm_volume: 0.35,
    })).toEqual({
      ordered_video_binding_ids: ["binding-video-2", "binding-video-1"],
      bgm_audio_binding_id: "binding-bgm",
      bgm_volume: 0.35,
      output: content.manifest.output,
      manifest_revision: 4,
    });
  });
});
