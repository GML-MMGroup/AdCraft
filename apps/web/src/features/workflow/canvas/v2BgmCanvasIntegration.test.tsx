import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import {
  normalizeAssetVersionV2,
  normalizeWorkflowItemV2,
  normalizeWorkflowRuntimeV2,
  normalizeWorkflowSlotV2,
} from "../../../api/v2Normalizers.ts";
import { v2Api } from "../../../api/v2Client.ts";
import { v2EtagStore } from "../../../api/v2EtagStore.ts";
import type { V2FinalCompositionTimeline, WorkflowSlotV2 } from "../../../types-v2.ts";
import {
  commitShotTimelineHistory,
  createShotTimelineHistory,
  rebaseReloadedShotTimelineHistory,
  undoShotTimelineHistory,
} from "../final-composition/shotTimelineHistory.ts";
import { V2RegionCardPreview } from "./V2RegionCardPreview.tsx";

const item = normalizeWorkflowItemV2({
  item_id: "bgm-item",
  node_id: "bgm",
  item_type: "bgm",
  display_name: "Background music",
  item_prompt: "Warm electronic music with a steady pulse",
  status: "completed",
  lifecycle_state: "active",
});

const selectedAsset = normalizeAssetVersionV2({
  asset_id: "selected-asset",
  version_id: "selected-version",
  media_type: "audio",
  source_type: "generated",
  semantic_type: "bgm",
  public_url: "/media/selected.mp3",
  duration_seconds: 18,
});

const workingAsset = normalizeAssetVersionV2({
  asset_id: "working-asset",
  version_id: "working-version",
  media_type: "audio",
  source_type: "generated",
  semantic_type: "bgm",
  public_url: "/media/working.mp3",
  duration_seconds: 18,
});

function bgmSlot(overrides: Partial<WorkflowSlotV2> = {}) {
  return normalizeWorkflowSlotV2({
    slot_id: "bgm-slot",
    node_id: "bgm",
    item_id: "bgm-item",
    slot_type: "bgm_audio",
    media_type: "audio",
    required: true,
    status: "completed",
    selected_asset_id: "selected-asset",
    selected_version_id: "selected-version",
    current_working_asset_id: "working-asset",
    current_working_version_id: "working-version",
    ...overrides,
  });
}

function runtime(status: string) {
  return normalizeWorkflowRuntimeV2({
    workflow_id: "workflow-1",
    slot_runtime: {
      "bgm-slot": { status },
    },
  });
}

afterEach(() => {
  cleanup();
  v2EtagStore.clear();
  vi.unstubAllGlobals();
});

describe("V2 BGM canvas integration", () => {
  it("keeps selection explicit across prompt, runtime refresh, and selected-version updates", () => {
    const onOpenSlotEditor = vi.fn();
    const onSelectSlotVersion = vi.fn();
    const onDiscardSlotWorkingVersion = vi.fn();
    const renderPreview = (
      slot: WorkflowSlotV2,
      runtimeStatus: string,
      openSlotId: string | null = null,
    ) => (
      <V2RegionCardPreview
        title="Background music"
        items={[item]}
        slots={[slot]}
        assetVersions={[selectedAsset, workingAsset]}
        runtime={runtime(runtimeStatus)}
        openSlotId={openSlotId}
        onOpenSlotEditor={onOpenSlotEditor}
        onSelectSlotVersion={onSelectSlotVersion}
        onDiscardSlotWorkingVersion={onDiscardSlotWorkingVersion}
      />
    );

    const view = render(renderPreview(bgmSlot(), "completed"));

    expect(screen.getByLabelText("Selected soundtrack audio player")).toBeTruthy();
    expect(screen.getByLabelText("Working soundtrack candidate audio player")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Edit BGM prompt" }));
    expect(onOpenSlotEditor).toHaveBeenCalledWith("bgm-slot");
    expect(onSelectSlotVersion).not.toHaveBeenCalled();

    view.rerender(renderPreview(bgmSlot(), "completed", "bgm-slot"));
    expect(screen.getByLabelText("BGM card").classList.contains("is-prompt-open")).toBe(true);
    expect(onSelectSlotVersion).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Use Working soundtrack" }));
    expect(onSelectSlotVersion).toHaveBeenCalledTimes(1);
    expect(onSelectSlotVersion).toHaveBeenCalledWith("bgm-slot", "working-version");

    fireEvent.click(screen.getByRole("button", { name: "Discard Working soundtrack" }));
    expect(onDiscardSlotWorkingVersion).toHaveBeenCalledTimes(1);
    expect(onDiscardSlotWorkingVersion).toHaveBeenCalledWith("bgm-slot");

    view.rerender(renderPreview(bgmSlot({ status: "waiting" }), "waiting", "bgm-slot"));
    expect(screen.getByLabelText("Selected soundtrack audio player")).toBeTruthy();
    expect(screen.getByLabelText("Working soundtrack candidate audio player")).toBeTruthy();
    expect(screen.getByLabelText("Generating")).toBeTruthy();
    expect(onSelectSlotVersion).toHaveBeenCalledTimes(1);

    view.rerender(renderPreview(bgmSlot({ status: "running" }), "running", "bgm-slot"));
    expect(screen.getByLabelText("Selected soundtrack audio player")).toBeTruthy();
    expect(screen.getByLabelText("Working soundtrack candidate audio player")).toBeTruthy();
    expect(screen.getByLabelText("Generating")).toBeTruthy();
    expect(onSelectSlotVersion).toHaveBeenCalledTimes(1);

    view.rerender(renderPreview(
      bgmSlot({
        selected_asset_id: "working-asset",
        selected_version_id: "working-version",
        current_working_asset_id: null,
        current_working_version_id: null,
      }),
      "completed",
      "bgm-slot",
    ));

    const selectedPlayer = screen.getByLabelText("Selected soundtrack audio player");
    expect(selectedPlayer.querySelector("audio")?.getAttribute("src")).toContain("/media/working.mp3");
    expect(screen.queryByLabelText("Working soundtrack candidate audio player")).toBeNull();
    expect(screen.queryByRole("button", { name: "Use Working soundtrack" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Discard Working soundtrack" })).toBeNull();
    expect(onSelectSlotVersion).toHaveBeenCalledTimes(1);
  });
});

describe("V2 runtime ETag isolation", () => {
  it("keeps ordinary runtime, polling, and SSE reads from replacing the authoring ETag", async () => {
    const workflowId = "workflow-runtime-etag";
    const authoringEtag = '"workflow-old"';
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({
        workflow_id: workflowId,
        execution_status: "running",
        events_cursor: 5,
      }, '"runtime-new"'))
      .mockResolvedValueOnce(jsonResponse({
        events: [{
          seq: 6,
          event_type: "slot_generation_waiting",
          workflow_id: workflowId,
          slot_id: "bgm-slot",
          payload: {},
        }],
        next_after_seq: 6,
      }, '"events-new"'));
    class MockEventSource {
      static urls: string[] = [];

      readonly url: string;

      constructor(url: string | URL) {
        this.url = String(url);
        MockEventSource.urls.push(this.url);
      }
    }

    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", MockEventSource);
    v2EtagStore.set("workflow", workflowId, authoringEtag);

    const runtimeResponse = await v2Api.runtime(workflowId);
    expect(runtimeResponse.execution_status).toBe("running");
    expect(v2EtagStore.getWorkflow(workflowId)).toBe(authoringEtag);

    const eventsResponse = await v2Api.events(workflowId, runtimeResponse.events_cursor);
    expect(eventsResponse.events.map((event) => event.event_type)).toEqual(["slot_generation_waiting"]);
    expect(eventsResponse.next_after_seq).toBe(6);
    expect(v2EtagStore.getWorkflow(workflowId)).toBe(authoringEtag);

    const stream = v2Api.openEventStream(workflowId, eventsResponse.next_after_seq);
    expect(stream).toBeInstanceOf(MockEventSource);
    expect(MockEventSource.urls).toEqual([
      `/api/v2/workflows/${workflowId}/events/stream?after_seq=6`,
    ]);
    expect(v2EtagStore.getWorkflow(workflowId)).toBe(authoringEtag);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      `/api/v2/workflows/${workflowId}/runtime`,
      `/api/v2/workflows/${workflowId}/events?after_seq=5`,
    ]);
  });
});

describe("Final Composition BGM refresh preservation", () => {
  it("rebases a dirty local edit onto the remote selected-BGM baseline without resetting history", () => {
    const requestDraft = timelineWithBgm("selected-bgm-v1", "bgm-version-v1", 1);
    const dirtyDraft = timelineWithBgm("selected-bgm-v1", "bgm-version-v1", 1);
    dirtyDraft.clips[0].audio.volume = 0.35;
    const dirtyHistory = commitShotTimelineHistory(
      createShotTimelineHistory(requestDraft),
      dirtyDraft,
    );
    const remoteTimeline = timelineWithBgm("selected-bgm-v2", "bgm-version-v2", 2);

    const rebased = rebaseReloadedShotTimelineHistory({
      history: dirtyHistory,
      requestDraft,
      remoteTimeline,
    });

    expect(rebased.present.version).toBe(2);
    expect(rebased.present.clips[0].source_asset_id).toBe("selected-bgm-v2");
    expect(rebased.present.clips[0].source_version_id).toBe("bgm-version-v2");
    expect(rebased.present.clips[0].audio.volume).toBe(0.35);
    expect(rebased.present).not.toEqual(remoteTimeline);
    expect(rebased.past).toEqual([remoteTimeline]);
    expect(undoShotTimelineHistory(rebased).present).toEqual(remoteTimeline);
  });
});

function jsonResponse(payload: unknown, etag: string) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      ETag: etag,
    },
  });
}

function timelineWithBgm(
  assetId: string,
  versionId: string,
  timelineVersion: number,
): V2FinalCompositionTimeline {
  return {
    timeline_id: "timeline-1",
    version: timelineVersion,
    duration_seconds: 18,
    aspect_ratio: "16:9",
    resolution: { width: 1920, height: 1080 },
    fps: 24,
    tracks: [{
      track_id: "bgm-track",
      track_type: "audio",
      order: 1,
      enabled: true,
      metadata: {},
    }],
    clips: [{
      clip_id: "bgm-clip",
      track_id: "bgm-track",
      clip_type: "audio",
      source_asset_id: assetId,
      source_version_id: versionId,
      source_slot_id: "bgm-slot",
      start_time: 0,
      duration: 18,
      trim_in: 0,
      trim_out: 18,
      volume: 1,
      muted: false,
      enabled: true,
      transform: {
        x: 0,
        y: 0,
        scale_x: 1,
        scale_y: 1,
        rotation_degrees: 0,
        opacity: 1,
        fit: "contain",
      },
      audio: {
        volume: 1,
        muted: false,
        fade_in_seconds: 0,
        fade_out_seconds: 0,
      },
      color: {
        preset_id: "none",
        brightness: 0,
        contrast: 1,
        saturation: 1,
        exposure: 0,
        temperature: 0,
        tint: 0,
        hue: 0,
      },
      text: null,
      subtitle_style: {
        font_size: 42,
        color: "#FFFFFF",
        position: "bottom_center",
      },
      metadata: { source: "selected_slot" },
    }],
    metadata: {},
  };
}
