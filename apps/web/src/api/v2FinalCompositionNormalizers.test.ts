import { describe, expect, it } from "vitest";

import {
  normalizeV2FinalTimelineRenderStateResponse,
  normalizeV2FinalTimelineResponse,
} from "./v2Normalizers.ts";

function timelineResponse(overrides: Record<string, unknown> = {}) {
  return {
    workflow_id: "workflow-1",
    node_id: "final-composition",
    item_id: "final-item",
    source: "saved",
    timeline: {
      timeline_id: "timeline-1",
      version: 3,
      duration_seconds: 4,
      aspect_ratio: "16:9",
      resolution: { width: 1280, height: 720 },
      fps: 24,
      tracks: [
        {
          track_id: "video-track",
          track_type: "video",
          order: 1,
          enabled: true,
          metadata: {},
        },
      ],
      clips: [
        {
          clip_id: "shot-1",
          track_id: "video-track",
          clip_type: "video",
          source_asset_id: "asset-1",
          source_version_id: "version-1",
          source_slot_id: "slot-1",
          start_time: 0,
          duration: 4,
          trim_in: 0,
          trim_out: 4,
          enabled: true,
        },
      ],
      metadata: {},
    },
    available_sources: [
      {
        asset_id: "asset-1",
        version_id: "version-1",
        media_type: "video",
        display_name: "Shot 1",
        public_url: "/media/shot-1.mp4",
        origin: "selected_slot",
        slot_id: "slot-1",
      },
    ],
    runtime: null,
    ...overrides,
  };
}

describe("V2 Final Composition normalizers", () => {
  it("normalizes explicit simple-sequence capabilities and clip health", () => {
    const response = normalizeV2FinalTimelineResponse(timelineResponse({
      composition_capabilities: {
        render_mode: "simple_sequence",
        supports_timeline_controls: false,
        supports_shot_reorder: false,
        supports_bgm_volume_edit: false,
      },
      stale_clip_ids: ["shot-stale"],
      missing_source_clip_ids: ["shot-missing"],
    }));

    expect(response.composition_capabilities).toEqual({
      render_mode: "simple_sequence",
      supports_timeline_controls: false,
      supports_shot_reorder: false,
      supports_bgm_volume_edit: false,
    });
    expect(response.stale_clip_ids).toEqual(["shot-stale"]);
    expect(response.missing_source_clip_ids).toEqual(["shot-missing"]);
    expect(response.available_sources[0].slot_id).toBe("slot-1");
  });

  it("enables advanced capabilities only when the backend explicitly returns timeline_editor", () => {
    const response = normalizeV2FinalTimelineResponse(timelineResponse({
      composition_capabilities: {
        render_mode: "timeline_editor",
        supports_timeline_controls: true,
        supports_shot_reorder: true,
        supports_bgm_volume_edit: true,
      },
    }));

    expect(response.composition_capabilities.render_mode).toBe("timeline_editor");
    expect(response.composition_capabilities.supports_timeline_controls).toBe(true);
    expect(response.composition_capabilities.supports_shot_reorder).toBe(true);
    expect(response.composition_capabilities.supports_bgm_volume_edit).toBe(true);
  });

  it("falls back to a read-only simple sequence when capabilities are absent or malformed", () => {
    const absent = normalizeV2FinalTimelineResponse(timelineResponse());
    const malformed = normalizeV2FinalTimelineResponse(timelineResponse({
      composition_capabilities: {
        render_mode: "future_editor",
        supports_timeline_controls: true,
        supports_shot_reorder: true,
        supports_bgm_volume_edit: true,
      },
    }));

    expect(absent.composition_capabilities).toEqual({
      render_mode: "simple_sequence",
      supports_timeline_controls: false,
      supports_shot_reorder: false,
      supports_bgm_volume_edit: false,
    });
    expect(malformed.composition_capabilities).toEqual({
      render_mode: "simple_sequence",
      supports_timeline_controls: false,
      supports_shot_reorder: false,
      supports_bgm_volume_edit: false,
    });
  });

  it.each([
    "queued",
    "running",
    "completed",
    "failed",
    "cancellation_requested",
    "cancelled",
  ] as const)("preserves the %s render state", (status) => {
    const response = normalizeV2FinalTimelineRenderStateResponse({
      workflow_id: "workflow-1",
      render_id: "render-1",
      slot_id: "final-slot",
      status,
      timeline_id: "timeline-1",
      timeline_version: 3,
      events_cursor: 4,
      created_at: "2026-07-23T00:00:00Z",
      updated_at: "2026-07-23T00:00:01Z",
    });

    expect(response.status).toBe(status);
  });
});
