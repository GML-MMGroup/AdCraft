import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import { AgentCanvasEditingPanel } from "./AgentCanvasEditingPanel.tsx";

function node(
  nodeId: string,
  nodeType: CanvasNodeV2["node_type"],
  outputAssetId: string | null,
): CanvasNodeV2 {
  return {
    node_id: nodeId,
    workflow_id: "workflow-1",
    node_type: nodeType,
    creative_role: nodeType === "video" ? "general_video" : nodeType === "audio" ? "bgm" : "editing",
    role_contract_version: "ad-media-role-v1",
    title: nodeType === "video" ? "Shot 1" : nodeType === "audio" ? "Campaign BGM" : "Final edit",
    status: "ready",
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
    created_at: "2026-07-30T00:00:00Z",
    updated_at: "2026-07-30T00:00:00Z",
  };
}

function asset(
  assetId: string,
  mediaType: ProjectAssetSummaryV2["media_type"],
): ProjectAssetSummaryV2 {
  return {
    asset_id: assetId,
    media_type: mediaType,
    source_type: "generated",
    display_name: assetId,
    mime_type: mediaType === "video" ? "video/mp4" : "audio/mpeg",
    status: "ready",
    preview_url: mediaType === "video" ? `/api/v2/assets/${assetId}/content` : null,
    media_url: `/api/v2/assets/${assetId}/content`,
    width: mediaType === "video" ? 1920 : null,
    height: mediaType === "video" ? 1080 : null,
    duration_seconds: 8,
    checksum: `${assetId}-checksum`,
  };
}

describe("AgentCanvasEditingPanel", () => {
  it("renders the final per-track and BGM authoring controls", async () => {
    const video = node("video-1", "video", "asset-video");
    const audio = node("audio-1", "audio", "asset-audio");
    const editing = {
      ...node("editing-1", "editing", null),
      structured_content: {
        manifest: {
          video_entries: [{
            binding_id: "binding-video",
            asset_id: null,
            enabled: true,
            trim_start_seconds: 0,
            trim_end_seconds: null,
            volume: 1,
            preserve_native_audio: true,
            transition: "fade",
            transition_duration_seconds: 0.5,
            fit_mode: "fit",
          }],
          bgm: {
            binding_id: "binding-audio",
            asset_id: null,
            enabled: true,
            trim_start_seconds: 0,
            trim_end_seconds: null,
            volume: 0.2,
            fade_in_seconds: 1,
            fade_out_seconds: 1,
          },
          output: {
            resolution: null,
            aspect_ratio: null,
            fps: null,
            video_codec: "h264",
            audio_codec: "aac",
            container: "mp4",
          },
          manifest_revision: 2,
        },
        dirty: true,
        preview: {
          clips: [],
          bgm_binding_id: "binding-audio",
          bgm_node_id: audio.node_id,
          bgm_asset_id: audio.output_asset_id,
          estimated_duration_seconds: 8,
          warnings: [],
        },
        last_successful_export: null,
        active_export: null,
      },
    } satisfies CanvasNodeV2;
    const workflow: AgentCanvasWorkflowV2 = {
      workflow_id: "workflow-1",
      project_id: "project-1",
      workflow_schema_version: 2,
      canvas_model: "agent_canvas_v1",
      revision: 3,
      layout_revision: 1,
      nodes: [video, audio, editing],
      bindings: [
        {
          binding_id: "binding-video",
          workflow_id: "workflow-1",
          source: { kind: "node_output", source_node_id: video.node_id },
          target_node_id: editing.node_id,
          input_role: "video_reference",
          required: true,
          enabled: true,
          order: 0,
          label: null,
          metadata: {},
          created_at: "2026-07-30T00:00:00Z",
          updated_at: "2026-07-30T00:00:00Z",
        },
        {
          binding_id: "binding-audio",
          workflow_id: "workflow-1",
          source: { kind: "node_output", source_node_id: audio.node_id },
          target_node_id: editing.node_id,
          input_role: "audio_reference",
          required: false,
          enabled: true,
          order: 1,
          label: null,
          metadata: {},
          created_at: "2026-07-30T00:00:00Z",
          updated_at: "2026-07-30T00:00:00Z",
        },
      ],
      assets: [asset("asset-video", "video"), asset("asset-audio", "audio")],
    };
    const patchNode = vi.fn().mockResolvedValue(undefined);

    render(
      <AgentCanvasEditingPanel
        workflow={workflow}
        node={editing}
        patchNode={patchNode}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Shot 1")).toBeTruthy();
    expect(screen.getByText("Transition")).toBeTruthy();
    expect(screen.getByText("Transition duration")).toBeTruthy();
    expect(screen.getAllByText("Fit")).toHaveLength(2);
    expect(screen.getByText("Fade in")).toBeTruthy();
    expect(screen.getByText("Fade out")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("BGM volume"), { target: { value: "0.45" } });
    await waitFor(() => expect(patchNode).toHaveBeenCalledWith(
      editing.node_id,
      expect.objectContaining({
        structured_content: expect.objectContaining({
          bgm: expect.objectContaining({ volume: 0.45 }),
          video_entries: expect.any(Array),
        }),
      }),
      { coalesce: true },
    ));
  });
});
