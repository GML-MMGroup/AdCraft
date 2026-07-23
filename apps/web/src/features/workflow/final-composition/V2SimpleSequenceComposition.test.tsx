import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { normalizeAssetVersionV2, normalizeV2FinalTimelineResponse } from "../../../api/v2Normalizers.ts";
import { V2SimpleSequenceComposition } from "./V2SimpleSequenceComposition.tsx";

function response() {
  return normalizeV2FinalTimelineResponse({
    workflow_id: "workflow-1",
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
      version: 1,
      duration_seconds: 8,
      aspect_ratio: "16:9",
      resolution: { width: 1280, height: 720 },
      fps: 24,
      tracks: [
        { track_id: "video", track_type: "video", order: 1, enabled: true, metadata: {} },
        { track_id: "audio", track_type: "audio", order: 2, enabled: true, metadata: { role: "bgm" } },
      ],
      clips: [
        {
          clip_id: "shot-2",
          track_id: "video",
          clip_type: "video",
          source_asset_id: "asset-2",
          source_version_id: "version-2",
          source_slot_id: "slot-2",
          start_time: 4,
          duration: 4,
          trim_in: 0,
          trim_out: 4,
          enabled: true,
        },
        {
          clip_id: "shot-1",
          track_id: "video",
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
        {
          clip_id: "bgm",
          track_id: "audio",
          clip_type: "audio",
          source_asset_id: "bgm-asset",
          source_version_id: "bgm-version",
          start_time: 0,
          duration: 8,
          trim_in: 0,
          trim_out: 8,
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
        display_name: "Opening shot",
        public_url: "/media/shot-1.mp4",
        origin: "selected_slot",
      },
      {
        asset_id: "asset-2",
        version_id: "version-2",
        media_type: "video",
        display_name: "Closing shot",
        public_url: "/media/shot-2.mp4",
        origin: "selected_slot",
      },
      {
        asset_id: "bgm-asset",
        version_id: "bgm-version",
        media_type: "audio",
        display_name: "Campaign BGM",
        public_url: "/media/bgm.mp3",
        origin: "selected_slot",
      },
    ],
    missing_source_clip_ids: ["shot-2"],
  });
}

afterEach(cleanup);

describe("V2SimpleSequenceComposition", () => {
  it("shows a read-only ordered shot sequence, material state, final video, and export only", () => {
    const timeline = response();
    const onExport = vi.fn();
    render(
      <V2SimpleSequenceComposition
        timeline={timeline.timeline}
        sources={timeline.available_sources}
        staleClipIds={timeline.stale_clip_ids}
        missingSourceClipIds={timeline.missing_source_clip_ids}
        finalVideo={normalizeAssetVersionV2({
          asset_id: "final-asset",
          version_id: "final-version",
          media_type: "video",
          source_type: "generated",
          semantic_type: "final_video",
          public_url: "/media/final.mp4",
        })}
        autoPlayFinalVideo
        renderStatus="completed"
        renderProgressPercent={100}
        renderIssue={null}
        rendering={false}
        cancellingRender={false}
        onExport={onExport}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByRole("list", { name: "Final video shot order" }).textContent).toMatch(
      /Opening shot[\s\S]*Closing shot/,
    );
    expect(screen.getAllByText("Ready")).toHaveLength(1);
    expect(screen.getByText("Missing")).toBeTruthy();
    expect(screen.queryByText("Campaign BGM")).toBeNull();
    expect(screen.getByLabelText("Final video preview")).toBeTruthy();
    expect(screen.queryByText("Save timeline")).toBeNull();
    expect(screen.queryByRole("button", { name: /move.*up/i })).toBeNull();
    expect(screen.queryByText("Trim")).toBeNull();
    expect(screen.queryByText("Subtitle")).toBeNull();
    expect(screen.queryByText("Overlay")).toBeNull();
    expect(screen.queryByLabelText(/BGM volume/i)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Export video" }));
    expect(onExport).toHaveBeenCalledTimes(1);
  });

  it("offers cancellation while an export is active", () => {
    const timeline = response();
    const onCancel = vi.fn();
    render(
      <V2SimpleSequenceComposition
        timeline={timeline.timeline}
        sources={timeline.available_sources}
        staleClipIds={[]}
        missingSourceClipIds={[]}
        finalVideo={null}
        autoPlayFinalVideo={false}
        renderStatus="running"
        renderProgressPercent={35}
        renderIssue={null}
        rendering
        cancellingRender={false}
        onExport={vi.fn()}
        onCancel={onCancel}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Cancel export" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(screen.getByText("35%")).toBeTruthy();
  });

  it("lets the backend classify an export when no successful shot is currently listed", () => {
    const timeline = response();
    const onExport = vi.fn();
    render(
      <V2SimpleSequenceComposition
        timeline={{ ...timeline.timeline, clips: [], duration_seconds: 0 }}
        sources={[]}
        staleClipIds={[]}
        missingSourceClipIds={[]}
        finalVideo={null}
        autoPlayFinalVideo={false}
        renderStatus={null}
        renderProgressPercent={null}
        renderIssue={null}
        rendering={false}
        cancellingRender={false}
        onExport={onExport}
        onCancel={vi.fn()}
      />,
    );

    const exportButton = screen.getByRole("button", { name: "Export video" });
    expect((exportButton as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(exportButton);
    expect(onExport).toHaveBeenCalledTimes(1);
  });
});
