import { afterEach, describe, expect, it, vi } from "vitest";

import { v2Api } from "./v2Client.ts";

const timelinePayload = {
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
    version: 2,
    duration_seconds: 5,
    aspect_ratio: "16:9",
    resolution: { width: 1280, height: 720 },
    fps: 24,
    tracks: [],
    clips: [],
    metadata: {},
  },
  available_sources: [],
  stale_clip_ids: [],
  missing_source_clip_ids: [],
  runtime: null,
};

const renderStatePayload = {
  workflow_id: "workflow-1",
  render_id: "render-1",
  slot_id: "final-slot",
  status: "running",
  progress_percent: 40,
  timeline_id: "timeline-1",
  timeline_version: 2,
  output_asset_id: null,
  output_version_id: null,
  error_code: null,
  error_message: null,
  created_at: "2026-07-23T00:00:00Z",
  updated_at: "2026-07-23T00:00:01Z",
  completed_at: null,
  cancellation_requested_at: null,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("V2 Final Composition client", () => {
  it("uses the timeline and operational render endpoints without semantic If-Match headers", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/final-composition/timeline")) {
        return jsonResponse(timelinePayload);
      }
      if (url.endsWith("/final-composition/render")) {
        return jsonResponse({
          workflow_id: "workflow-1",
          render_id: "render-1",
          status: "queued",
          timeline_id: "timeline-1",
          timeline_version: 2,
          events_cursor: 11,
        });
      }
      if (url.endsWith("/renders/render-1/cancel")) {
        return jsonResponse({
          ...renderStatePayload,
          status: "cancellation_requested",
        });
      }
      return jsonResponse(renderStatePayload);
    });
    vi.stubGlobal("fetch", fetchMock);

    await v2Api.getFinalTimeline("workflow-1");
    await v2Api.renderFinalTimeline("workflow-1", {
      timeline_id: "timeline-1",
      timeline_version: 2,
      render_settings: {
        video_codec: "h264",
        audio_codec: "aac",
        video_bitrate: null,
        audio_bitrate: null,
      },
    });
    await v2Api.getFinalTimelineRender("workflow-1", "render-1");
    await v2Api.cancelFinalTimelineRender("workflow-1", "render-1");

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(fetchMock.mock.calls.map(([url, init]) => ({
      url: String(url),
      method: init?.method ?? "GET",
      ifMatch: new Headers(init?.headers).get("If-Match"),
    }))).toEqual([
      {
        url: "/api/v2/workflows/workflow-1/final-composition/timeline",
        method: "GET",
        ifMatch: null,
      },
      {
        url: "/api/v2/workflows/workflow-1/final-composition/render",
        method: "POST",
        ifMatch: null,
      },
      {
        url: "/api/v2/workflows/workflow-1/final-composition/renders/render-1",
        method: "GET",
        ifMatch: null,
      },
      {
        url: "/api/v2/workflows/workflow-1/final-composition/renders/render-1/cancel",
        method: "POST",
        ifMatch: null,
      },
    ]);
  });
});

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
