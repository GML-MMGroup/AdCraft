import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  CanvasNodePatchRequestV2,
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
  beforeEach(() => {
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => undefined);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows nodes omitted by the backend composition plan without adding controls", () => {
    const omittedVideo = {
      ...node("video-omitted", "video", null),
      title: "Missing product close-up",
      status: "draft" as const,
    };
    const editing = {
      ...node("editing-1", "editing", null),
      structured_content: {
        manifest: {
          video_entries: [],
          bgm: null,
          output: {
            resolution: null,
            aspect_ratio: null,
            fps: null,
            video_codec: "h264",
            audio_codec: "aac",
            container: "mp4",
          },
          manifest_revision: 1,
        },
        dirty: false,
        preview: {
          clips: [],
          bgm_binding_id: null,
          bgm_node_id: null,
          bgm_asset_id: null,
          estimated_duration_seconds: 0,
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
      nodes: [omittedVideo, editing],
      bindings: [],
      assets: [],
    };

    render(
      <AgentCanvasEditingPanel
        workflow={workflow}
        node={editing}
        omittedNodeIds={[omittedVideo.node_id, "video-not-materialized"]}
        patchNode={vi.fn().mockResolvedValue(undefined)}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "Omitted planned inputs" })).toBeTruthy();
    expect(screen.getByText("Missing product close-up")).toBeTruthy();
    expect(screen.getByText("video-not-materialized")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /missing product close-up/i })).toBeNull();
    expect(screen.queryByRole("button", { name: "Download exported video" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add exported video to canvas" })).toBeNull();
    expect(screen.getByRole("button", { name: "Export" }).hasAttribute("disabled")).toBe(true);
  });

  it("allows backend export for a ready source without a browser media URL", () => {
    const video = node("video-export-only", "video", "asset-export-only");
    const editing = {
      ...node("editing-export-only", "editing", null),
      structured_content: {
        manifest: {
          video_entries: [{
            binding_id: "binding-export-only",
            asset_id: null,
            enabled: true,
            trim_start_seconds: 0,
            trim_end_seconds: null,
            volume: 1,
            preserve_native_audio: true,
            transition: "cut",
            transition_duration_seconds: 0,
            fit_mode: "fit",
          }],
          bgm: null,
          output: {
            resolution: null,
            aspect_ratio: null,
            fps: null,
            video_codec: "h264",
            audio_codec: "aac",
            container: "mp4",
          },
          manifest_revision: 1,
        },
        dirty: false,
        preview: {
          clips: [],
          bgm_binding_id: null,
          bgm_node_id: null,
          bgm_asset_id: null,
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
      nodes: [video, editing],
      bindings: [{
        binding_id: "binding-export-only",
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
      }],
      assets: [{ ...asset("asset-export-only", "video"), media_url: null }],
    };

    render(
      <AgentCanvasEditingPanel
        workflow={workflow}
        node={editing}
        patchNode={vi.fn().mockResolvedValue(undefined)}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Play preview" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "Export" }).hasAttribute("disabled")).toBe(false);
  });

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
      assets: [
        { ...asset("asset-video", "video"), duration_seconds: 0.5 },
        asset("asset-audio", "audio"),
      ],
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

    expect(screen.getByRole("group", { name: "Video track" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Audio track" })).toBeTruthy();
    expect(screen.getByText("Video Track")).toBeTruthy();
    expect(screen.getByText("Audio Track")).toBeTruthy();
    expect(screen.getByRole("slider", { name: "Timeline playhead" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Play preview" }).hasAttribute("disabled")).toBe(false);
    expect(screen.getByTestId("editing-preview-video").getAttribute("src"))
      .toBe("/api/v2/assets/asset-video/content");
    fireEvent.click(screen.getByRole("button", { name: "Fast forward preview" }));
    expect((screen.getByTestId("editing-preview-video") as HTMLVideoElement).currentTime).toBe(0.5);
    fireEvent.click(screen.getByRole("button", { name: "Play preview" }));
    expect((screen.getByTestId("editing-preview-video") as HTMLVideoElement).currentTime).toBe(0);
    expect(screen.getByRole("button", { name: "Pause preview" })).toBeTruthy();
    expect(screen.queryByText("Selected clip")).toBeNull();
    const clipProperties = screen.getByRole("toolbar", { name: "Clip properties" });
    expect(within(clipProperties).queryByRole("spinbutton", { name: "Trim start" })).toBeNull();
    expect(within(clipProperties).queryByRole("spinbutton", { name: "Trim end" })).toBeNull();
    expect(screen.getByRole("slider", { name: "Trim start Shot 1" })).toBeTruthy();
    expect(screen.getByRole("slider", { name: "Trim end Shot 1" })).toBeTruthy();

    expect(screen.getByText("Shot 1")).toBeTruthy();
    expect(screen.getByText("Transition")).toBeTruthy();
    expect(screen.getByText("Transition duration")).toBeTruthy();
    expect(screen.getAllByText("Fit")).toHaveLength(2);
    expect(screen.queryByText("Fade in")).toBeNull();
    expect(screen.queryByText("Fade out")).toBeNull();

    fireEvent.change(screen.getByLabelText("BGM volume"), { target: { value: "0.45" } });
    await waitFor(() => expect(patchNode).toHaveBeenCalledWith(
      editing.node_id,
      expect.objectContaining({
        structured_content: expect.objectContaining({
          bgm: expect.objectContaining({
            fade_in_seconds: 0,
            fade_out_seconds: 0,
            volume: 0.45,
          }),
          video_entries: expect.any(Array),
        }),
      }),
      { coalesce: true },
    ));

    fireEvent.change(screen.getByLabelText("Resolution"), { target: { value: "1920x1080" } });
    fireEvent.change(screen.getByLabelText("Aspect ratio"), { target: { value: "16:9" } });
    fireEvent.change(screen.getByLabelText("FPS"), { target: { value: "30" } });

    await waitFor(() => {
      const latestPatch = patchNode.mock.calls.at(-1)?.[1] as CanvasNodePatchRequestV2 | undefined;
      expect(latestPatch?.structured_content?.output).toMatchObject({
        resolution: "1920x1080",
        aspect_ratio: "16:9",
        fps: 30,
      });
    });
    expect(patchNode.mock.calls.every((call) => call[2]?.coalesce === true)).toBe(true);
  });

  it("offers Download and Add to Canvas only for a readable terminal export", async () => {
    const editing = {
      ...node("editing-1", "editing", "asset-export"),
      structured_content: {
        manifest: {
          video_entries: [],
          bgm: null,
          output: {
            resolution: null,
            aspect_ratio: null,
            fps: null,
            video_codec: "h264",
            audio_codec: "aac",
            container: "mp4",
          },
          manifest_revision: 5,
        },
        dirty: false,
        preview: {
          clips: [],
          bgm_binding_id: null,
          bgm_node_id: null,
          bgm_asset_id: null,
          estimated_duration_seconds: 30,
          warnings: [],
        },
        last_successful_export: {
          export_id: "export-30s",
          status: "completed",
          manifest_revision: 5,
          fingerprint: "fingerprint-30s",
          ready_video_node_ids: [],
          skipped_inputs: [],
          bgm_node_id: null,
          output_asset_id: "asset-export",
          error: null,
          started_at: "2026-08-24T00:00:00Z",
          finished_at: "2026-08-24T00:00:10Z",
        },
        active_export: null,
      },
    } satisfies CanvasNodeV2;
    const workflow: AgentCanvasWorkflowV2 = {
      workflow_id: "workflow-1",
      project_id: "project-1",
      workflow_schema_version: 2,
      canvas_model: "agent_canvas_v1",
      revision: 5,
      layout_revision: 1,
      nodes: [editing],
      bindings: [],
      assets: [asset("asset-export", "video")],
    };
    const onDownload = vi.fn().mockResolvedValue(undefined);
    const onAddToCanvas = vi.fn().mockResolvedValue(undefined);

    render(
      <AgentCanvasEditingPanel
        workflow={workflow}
        node={editing}
        patchNode={vi.fn().mockResolvedValue(undefined)}
        onClose={vi.fn()}
        onDownloadExport={onDownload}
        onAddExportToCanvas={onAddToCanvas}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Download exported video" }));
    fireEvent.click(screen.getByRole("button", { name: "Add exported video to canvas" }));

    await waitFor(() => {
      expect(onDownload).toHaveBeenCalledWith("asset-export");
      expect(onAddToCanvas).toHaveBeenCalledWith("export-30s");
    });
  });
});
