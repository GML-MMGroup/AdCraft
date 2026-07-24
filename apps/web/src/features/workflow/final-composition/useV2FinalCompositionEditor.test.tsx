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
import type {
  V2FinalCompositionTimeline,
  V2FinalTimelineRenderStateResponse,
  V2FinalTimelineUpdateResponse,
} from "../../../types-v2.ts";
import { useV2FinalCompositionEditor } from "./useV2FinalCompositionEditor.ts";

function simpleTimelineResponse({
  workflowId = "workflow-1",
  timelineId = "timeline-1",
  version = 4,
  duration = 5,
  advanced = false,
}: {
  workflowId?: string;
  timelineId?: string;
  version?: number;
  duration?: number;
  advanced?: boolean;
} = {}) {
  return normalizeV2FinalTimelineResponse({
    workflow_id: workflowId,
    node_id: "final-composition",
    item_id: "final-item",
    source: "saved",
    composition_capabilities: {
      render_mode: advanced ? "timeline_editor" : "simple_sequence",
      supports_timeline_controls: advanced,
      supports_shot_reorder: advanced,
      supports_bgm_volume_edit: advanced,
    },
    timeline: {
      timeline_id: timelineId,
      version,
      duration_seconds: duration,
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
        duration,
        trim_in: 0,
        trim_out: duration,
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

function workflowWithFinalVideo(publicUrl = "/media/final.mp4", workflowId = "workflow-1") {
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
    workflow_id: workflowId,
    workflow_schema_version: 2,
    title: "Workflow",
    nodes: [],
    edges: [],
    items: [item],
    slots: [slot],
    asset_versions: [asset],
  });
}

function renderState(
  status: V2FinalTimelineRenderStateResponse["status"],
  overrides: Partial<V2FinalTimelineRenderStateResponse> = {},
): V2FinalTimelineRenderStateResponse {
  return {
    workflow_id: "workflow-1",
    render_id: "render-1",
    slot_id: "final-slot",
    status,
    timeline_id: "timeline-1",
    timeline_version: 4,
    events_cursor: 3,
    progress_seconds: status === "completed" ? 5 : 1,
    total_seconds: 5,
    progress_percent: status === "completed" ? 100 : 20,
    asset_id: status === "completed" ? "final-asset" : null,
    version_id: status === "completed" ? "final-version" : null,
    error_code: status === "failed" ? "render_failed" : null,
    error_message: status === "failed" ? "Render failed." : null,
    created_at: "2026-07-23T00:00:00Z",
    updated_at: "2026-07-23T00:00:05Z",
    ...overrides,
  };
}

function renderStart(version = 4) {
  return {
    workflow_id: "workflow-1",
    render_id: "render-1",
    status: "queued" as const,
    timeline_id: "timeline-1",
    timeline_version: version,
    events_cursor: 2,
  };
}

function savedTimeline(
  timeline: V2FinalCompositionTimeline,
  version: number,
): V2FinalTimelineUpdateResponse {
  return {
    workflow_id: "workflow-1",
    timeline: { ...timeline, version },
    changed_clip_ids: timeline.clips.map((clip) => clip.clip_id),
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function apiError(status: number, code = "timeline_version_conflict") {
  return new V2ApiError({
    status,
    code,
    message: "Timeline precondition failed.",
    details: {},
    violations: [],
    suggestedActions: [],
    payload: null,
  });
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
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

  it("ignores stale initialization, resets the document selection, and preserves UI preferences across sessions", async () => {
    const firstLoad = deferred<ReturnType<typeof simpleTimelineResponse>>();
    const getTimeline = vi.spyOn(v2Api, "getFinalTimeline").mockImplementation((workflowId) => (
      workflowId === "workflow-1"
        ? firstLoad.promise
        : Promise.resolve(simpleTimelineResponse({
          workflowId,
          timelineId: "timeline-2",
          version: 8,
          advanced: true,
        }))
    ));
    vi.spyOn(v2Api, "workflow").mockImplementation((workflowId) => (
      Promise.resolve(workflowWithFinalVideo(`/media/${workflowId}.mp4`, workflowId))
    ));

    const { result, rerender } = renderHook(
      ({ workflowId }) => useV2FinalCompositionEditor({ workflowId, active: true }),
      { initialProps: { workflowId: "workflow-1" } },
    );

    act(() => {
      result.current.setTool("blade");
      result.current.setZoom(99);
      result.current.setSelectedClipIds(["shot-1", "shot-1"]);
    });
    rerender({ workflowId: "workflow-2" });

    await waitFor(() => expect(result.current.draft?.timeline_id).toBe("timeline-2"));
    firstLoad.resolve(simpleTimelineResponse());
    await act(async () => {
      await firstLoad.promise;
      await Promise.resolve();
    });

    expect(getTimeline).toHaveBeenCalledWith("workflow-1");
    expect(getTimeline).toHaveBeenCalledWith("workflow-2");
    expect(result.current.draft?.timeline_id).toBe("timeline-2");
    expect(result.current.selectedClipIds).toEqual([]);
    expect(result.current.tool).toBe("blade");
    expect(result.current.zoom).toBe(4);
  });

  it("keeps one timeline authority through edit, undo, and redo", async () => {
    vi.spyOn(v2Api, "getFinalTimeline").mockResolvedValue(simpleTimelineResponse({ advanced: true }));
    vi.spyOn(v2Api, "workflow").mockResolvedValue(workflowWithFinalVideo());

    const { result } = renderHook(() => useV2FinalCompositionEditor({
      workflowId: "workflow-1",
      active: true,
    }));
    await waitFor(() => expect(result.current.draft?.timeline_id).toBe("timeline-1"));

    act(() => {
      result.current.updateClip("shot-1", (clip) => ({ ...clip, duration: 3, trim_out: 3 }));
    });
    expect(result.current.draft?.clips[0].duration).toBe(3);
    expect(result.current.baseline?.clips[0].duration).toBe(5);
    expect(result.current.isDirty).toBe(true);
    expect(result.current.canUndo).toBe(true);

    act(() => result.current.undo());
    expect(result.current.draft?.clips[0].duration).toBe(5);
    expect(result.current.isDirty).toBe(false);
    expect(result.current.canRedo).toBe(true);

    act(() => result.current.redo());
    expect(result.current.draft?.clips[0].duration).toBe(3);
    expect(result.current.isDirty).toBe(true);
  });

  it("serializes saves and reconciles dirty state against each successful response", async () => {
    vi.spyOn(v2Api, "getFinalTimeline").mockResolvedValue(simpleTimelineResponse({ advanced: true }));
    vi.spyOn(v2Api, "workflow").mockResolvedValue(workflowWithFinalVideo());
    const firstSave = deferred<V2FinalTimelineUpdateResponse>();
    const secondSave = deferred<V2FinalTimelineUpdateResponse>();
    const saveTimeline = vi.spyOn(v2Api, "saveFinalTimeline")
      .mockImplementationOnce(() => firstSave.promise)
      .mockImplementationOnce(() => secondSave.promise);

    const { result } = renderHook(() => useV2FinalCompositionEditor({
      workflowId: "workflow-1",
      active: true,
    }));
    await waitFor(() => expect(result.current.draft?.timeline_id).toBe("timeline-1"));

    act(() => {
      result.current.updateClip("shot-1", (clip) => ({ ...clip, duration: 4, trim_out: 4 }));
    });
    let firstPending!: Promise<V2FinalTimelineUpdateResponse | null>;
    act(() => {
      firstPending = result.current.save();
    });
    await waitFor(() => expect(saveTimeline).toHaveBeenCalledTimes(1));

    act(() => {
      result.current.updateClip("shot-1", (clip) => ({ ...clip, duration: 3, trim_out: 3 }));
    });
    let secondPending!: Promise<V2FinalTimelineUpdateResponse | null>;
    act(() => {
      secondPending = result.current.save();
    });
    expect(saveTimeline).toHaveBeenCalledTimes(1);
    expect(result.current.saving).toBe(true);

    const firstRequest = saveTimeline.mock.calls[0][1];
    firstSave.resolve(savedTimeline(firstRequest.timeline, 5));
    await act(async () => {
      await firstPending;
    });
    await waitFor(() => expect(saveTimeline).toHaveBeenCalledTimes(2));
    expect(result.current.isDirty).toBe(true);
    expect(saveTimeline.mock.calls[1][1].expected_version).toBe(5);
    expect(saveTimeline.mock.calls[1][1].timeline.clips[0].duration).toBe(3);

    const secondRequest = saveTimeline.mock.calls[1][1];
    secondSave.resolve(savedTimeline(secondRequest.timeline, 6));
    await act(async () => {
      await secondPending;
    });
    expect(result.current.saving).toBe(false);
    expect(result.current.isDirty).toBe(false);
    expect(result.current.baseline?.version).toBe(6);
  });

  it.each([412, 428])("preserves the local draft for HTTP %s precondition conflicts", async (status) => {
    const initial = simpleTimelineResponse({ advanced: true });
    const remote = simpleTimelineResponse({ advanced: true, version: 5, duration: 9 });
    vi.spyOn(v2Api, "getFinalTimeline")
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(remote);
    vi.spyOn(v2Api, "workflow").mockResolvedValue(workflowWithFinalVideo());
    const saveTimeline = vi.spyOn(v2Api, "saveFinalTimeline").mockRejectedValue(apiError(status));

    const { result } = renderHook(() => useV2FinalCompositionEditor({
      workflowId: "workflow-1",
      active: true,
    }));
    await waitFor(() => expect(result.current.draft?.timeline_id).toBe("timeline-1"));
    act(() => {
      result.current.updateClip("shot-1", (clip) => ({ ...clip, duration: 7, trim_out: 7 }));
    });

    await act(async () => {
      await result.current.save();
    });
    expect(saveTimeline.mock.calls[0][1].expected_version).toBe(4);
    expect(result.current.conflict?.kind).toBe("version-conflict");
    expect(result.current.draft?.clips[0].duration).toBe(7);

    await act(async () => {
      await result.current.keepLocal();
    });
    expect(result.current.baseline?.version).toBe(5);
    expect(result.current.baseline?.clips[0].duration).toBe(9);
    expect(result.current.draft?.clips[0].duration).toBe(7);
    expect(result.current.isDirty).toBe(true);
    expect(result.current.conflict).toBeNull();
  });

  it("reloads the remote document only when that conflict resolution is selected", async () => {
    const initial = simpleTimelineResponse({ advanced: true });
    const remote = simpleTimelineResponse({ advanced: true, version: 5, duration: 9 });
    vi.spyOn(v2Api, "getFinalTimeline")
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(remote);
    vi.spyOn(v2Api, "workflow").mockResolvedValue(workflowWithFinalVideo());
    vi.spyOn(v2Api, "saveFinalTimeline").mockRejectedValue(apiError(412));

    const { result } = renderHook(() => useV2FinalCompositionEditor({
      workflowId: "workflow-1",
      active: true,
    }));
    await waitFor(() => expect(result.current.draft).not.toBeNull());
    act(() => {
      result.current.updateClip("shot-1", (clip) => ({ ...clip, duration: 7, trim_out: 7 }));
    });
    await act(async () => {
      await result.current.save();
      await result.current.reloadRemote();
    });

    expect(result.current.draft?.clips[0].duration).toBe(9);
    expect(result.current.baseline?.version).toBe(5);
    expect(result.current.isDirty).toBe(false);
  });

  it("flushes an advanced timeline before rendering and preserves the last successful video on failure", async () => {
    vi.spyOn(v2Api, "getFinalTimeline").mockResolvedValue(simpleTimelineResponse({ advanced: true }));
    vi.spyOn(v2Api, "workflow").mockResolvedValue(workflowWithFinalVideo("/media/previous.mp4"));
    const saveTimeline = vi.spyOn(v2Api, "saveFinalTimeline").mockImplementation(async (_workflowId, request) => (
      savedTimeline(request.timeline, 5)
    ));
    const startRender = vi.spyOn(v2Api, "renderFinalTimeline").mockResolvedValue(renderStart(5));
    vi.spyOn(v2Api, "getFinalTimelineRender").mockResolvedValue(renderState("failed", {
      timeline_version: 5,
    }));

    const { result } = renderHook(() => useV2FinalCompositionEditor({
      workflowId: "workflow-1",
      active: true,
    }));
    await waitFor(() => expect(result.current.finalVideo?.public_url).toBe("/media/previous.mp4"));
    act(() => {
      result.current.updateClip("shot-1", (clip) => ({ ...clip, duration: 4, trim_out: 4 }));
    });

    await act(async () => {
      await result.current.render();
    });
    await waitFor(() => expect(result.current.renderState?.status).toBe("failed"));

    expect(saveTimeline).toHaveBeenCalledTimes(1);
    expect(saveTimeline.mock.invocationCallOrder[0]).toBeLessThan(startRender.mock.invocationCallOrder[0]);
    expect(startRender).toHaveBeenCalledWith("workflow-1", {
      timeline_id: "timeline-1",
      timeline_version: 5,
    });
    expect(result.current.finalVideo?.public_url).toBe("/media/previous.mp4");
    expect(result.current.autoPlayFinalVideo).toBe(false);
    expect(result.current.rendering).toBe(false);
  });

  it("polls cancellation to a terminal state without replacing the last successful video", async () => {
    vi.useFakeTimers();
    vi.spyOn(v2Api, "getFinalTimeline").mockResolvedValue(simpleTimelineResponse({ advanced: true }));
    vi.spyOn(v2Api, "workflow").mockResolvedValue(workflowWithFinalVideo("/media/previous.mp4"));
    vi.spyOn(v2Api, "renderFinalTimeline").mockResolvedValue(renderStart());
    const getRender = vi.spyOn(v2Api, "getFinalTimelineRender")
      .mockResolvedValueOnce(renderState("running"))
      .mockResolvedValueOnce(renderState("cancelled"));
    vi.spyOn(v2Api, "cancelFinalTimelineRender").mockResolvedValue(renderState("cancellation_requested"));

    const { result } = renderHook(() => useV2FinalCompositionEditor({
      workflowId: "workflow-1",
      active: true,
    }));
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(result.current.finalVideo?.public_url).toBe("/media/previous.mp4");

    await act(async () => {
      await result.current.render();
      await Promise.resolve();
    });
    expect(result.current.renderState?.status).toBe("running");

    await act(async () => {
      await result.current.cancelRender();
    });
    expect(result.current.renderState?.status).toBe("cancellation_requested");
    expect(result.current.cancellingRender).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(getRender).toHaveBeenCalledTimes(2);
    expect(result.current.renderState?.status).toBe("cancelled");
    expect(result.current.rendering).toBe(false);
    expect(result.current.finalVideo?.public_url).toBe("/media/previous.mp4");
  });

  it("clears a scheduled render poll when the editor unmounts", async () => {
    vi.useFakeTimers();
    vi.spyOn(v2Api, "getFinalTimeline").mockResolvedValue(simpleTimelineResponse({ advanced: true }));
    vi.spyOn(v2Api, "workflow").mockResolvedValue(workflowWithFinalVideo());
    vi.spyOn(v2Api, "renderFinalTimeline").mockResolvedValue(renderStart());
    vi.spyOn(v2Api, "getFinalTimelineRender").mockResolvedValue(renderState("running"));
    const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout");

    const { result, unmount } = renderHook(() => useV2FinalCompositionEditor({
      workflowId: "workflow-1",
      active: true,
    }));
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    await act(async () => {
      await result.current.render();
      await Promise.resolve();
    });
    expect(result.current.renderState?.status).toBe("running");

    const callsBeforeUnmount = clearTimeoutSpy.mock.calls.length;
    unmount();
    expect(clearTimeoutSpy.mock.calls.length).toBeGreaterThan(callsBeforeUnmount);
  });
});
