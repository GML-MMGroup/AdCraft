import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { V2ApiError, v2Api } from "../../../api/v2Client.ts";
import {
  normalizeAssetVersionV2,
  normalizeV2FinalTimelineResponse,
  normalizeWorkflowItemV2,
  normalizeWorkflowSlotV2,
  normalizeWorkflowV2,
} from "../../../api/v2Normalizers.ts";
import { useV2FinalCompositionEditor } from "./useV2FinalCompositionEditor.ts";

function simpleTimelineResponse() {
  return normalizeV2FinalTimelineResponse({
    workflow_id: "workflow-1",
    node_id: "final-composition",
    item_id: "final-item",
    source: "saved",
    composition_capabilities: {
      render_mode: "simple_sequence",
      supports_timeline_controls: false,
      supports_shot_reorder: false,
      supports_bgm_volume_edit: false,
    },
    timeline: {
      timeline_id: "timeline-1",
      version: 4,
      duration_seconds: 5,
      aspect_ratio: "16:9",
      resolution: { width: 1280, height: 720 },
      fps: 24,
      tracks: [{ track_id: "video-track", track_type: "video", order: 1, enabled: true, metadata: {} }],
      clips: [{
        clip_id: "shot-1",
        track_id: "video-track",
        clip_type: "video",
        source_asset_id: "shot-asset",
        source_version_id: "shot-version",
        source_slot_id: "shot-slot",
        start_time: 0,
        duration: 5,
        trim_in: 0,
        trim_out: 5,
        enabled: true,
      }],
      metadata: {},
    },
    available_sources: [{
      asset_id: "shot-asset",
      version_id: "shot-version",
      media_type: "video",
      display_name: "Shot 1",
      public_url: "/media/shot.mp4",
      origin: "selected_slot",
      slot_id: "shot-slot",
    }],
  });
}

function workflowWithFinalVideo(publicUrl = "/media/final.mp4") {
  const item = normalizeWorkflowItemV2({
    item_id: "final-item",
    node_id: "final-composition",
    item_type: "final_composition",
    display_name: "Final Composition",
    status: "completed",
    lifecycle_state: "active",
  });
  const slot = normalizeWorkflowSlotV2({
    slot_id: "final-slot",
    node_id: "final-composition",
    item_id: "final-item",
    slot_type: "final_video",
    media_type: "video",
    required: true,
    status: "completed",
    selected_asset_id: "final-asset",
    selected_version_id: "final-version",
  });
  const asset = normalizeAssetVersionV2({
    asset_id: "final-asset",
    version_id: "final-version",
    media_type: "video",
    source_type: "generated",
    semantic_type: "final_video",
    public_url: publicUrl,
    status: "completed",
  });
  return normalizeWorkflowV2({
    workflow_id: "workflow-1",
    workflow_schema_version: 2,
    title: "Workflow",
    nodes: [],
    edges: [],
    items: [item],
    slots: [slot],
    asset_versions: [asset],
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("useV2FinalCompositionEditor", () => {
  it("exports a simple sequence with GET timeline, POST render, polling, and a full workflow refresh", async () => {
    const timeline = simpleTimelineResponse();
    const refreshedWorkflow = workflowWithFinalVideo();
    const getTimeline = vi.spyOn(v2Api, "getFinalTimeline").mockResolvedValue(timeline);
    vi.spyOn(v2Api, "workflow").mockResolvedValue(refreshedWorkflow);
    const saveTimeline = vi.spyOn(v2Api, "saveFinalTimeline");
    const startRender = vi.spyOn(v2Api, "renderFinalTimeline").mockResolvedValue({
      workflow_id: "workflow-1",
      render_id: "render-1",
      status: "queued",
      timeline_id: "timeline-1",
      timeline_version: 4,
      events_cursor: 2,
    });
    const getRender = vi.spyOn(v2Api, "getFinalTimelineRender").mockResolvedValue({
      workflow_id: "workflow-1",
      render_id: "render-1",
      slot_id: "final-slot",
      status: "completed",
      timeline_id: "timeline-1",
      timeline_version: 4,
      events_cursor: 3,
      progress_seconds: 5,
      total_seconds: 5,
      progress_percent: 100,
      asset_id: "final-asset",
      version_id: "final-version",
      error_code: null,
      error_message: null,
      created_at: "2026-07-23T00:00:00Z",
      updated_at: "2026-07-23T00:00:05Z",
    });
    const onWorkflowRefresh = vi.fn().mockResolvedValue(refreshedWorkflow);

    const { result } = renderHook(() => useV2FinalCompositionEditor({
      workflowId: "workflow-1",
      active: true,
      onWorkflowRefresh,
    }));

    await waitFor(() => expect(result.current.draft?.timeline_id).toBe("timeline-1"));
    await act(async () => {
      await result.current.render();
    });
    await waitFor(() => expect(getRender).toHaveBeenCalledWith("workflow-1", "render-1"));
    await waitFor(() => expect(onWorkflowRefresh).toHaveBeenCalledWith("workflow-1"));

    expect(getTimeline).toHaveBeenCalledTimes(3);
    expect(getTimeline.mock.invocationCallOrder[1]).toBeLessThan(startRender.mock.invocationCallOrder[0]);
    expect(saveTimeline).not.toHaveBeenCalled();
    expect(result.current.finalVideo?.version_id).toBe("final-version");
    expect(result.current.autoPlayFinalVideo).toBe(true);
  });

  it("maps unsettled inputs to a bounded waiting notice instead of a render failure", async () => {
    const timeline = simpleTimelineResponse();
    vi.spyOn(v2Api, "getFinalTimeline").mockResolvedValue(timeline);
    vi.spyOn(v2Api, "workflow").mockResolvedValue(workflowWithFinalVideo("/media/previous.mp4"));
    vi.spyOn(v2Api, "renderFinalTimeline").mockRejectedValue(new V2ApiError({
      status: 409,
      code: "composition_inputs_not_settled",
      message: "Inputs are not settled.",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }));

    const { result } = renderHook(() => useV2FinalCompositionEditor({
      workflowId: "workflow-1",
      active: true,
    }));

    await waitFor(() => expect(result.current.finalVideo?.public_url).toBe("/media/previous.mp4"));
    await act(async () => {
      await result.current.render();
    });

    expect(result.current.renderIssue).toEqual({
      kind: "waiting",
      status: "blocked",
      message: "正在等待视频/BGM 生成完成",
    });
    expect(result.current.error).toBe("");
    expect(result.current.finalVideo?.public_url).toBe("/media/previous.mp4");
  });
});
