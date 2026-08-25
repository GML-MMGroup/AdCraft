import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  CanvasNodePatchRequestV2,
  CanvasNodeV2,
  EditingVideoEntryV2,
} from "../../../types-v2.ts";

vi.mock("../../../api/v2Client.ts", () => ({
  isV2ApiError: () => false,
  v2Api: {
    exportAgentCanvasEditingNode: vi.fn(),
    cancelAgentCanvasEditingExport: vi.fn(),
  },
}));

import { useAgentCanvasEditing } from "./useAgentCanvasEditing.ts";

function editingNode(videoEntries: EditingVideoEntryV2[] = []): CanvasNodeV2 {
  return {
    node_id: "editing-1",
    workflow_id: "workflow-1",
    node_type: "editing",
    creative_role: "editing",
    role_contract_version: "ad-media-role-v1",
    title: "Final composition",
    status: "ready",
    summary_prompt: null,
    generation_prompt: null,
    structured_content: {
      manifest: {
        video_entries: videoEntries,
        bgm: {
          binding_id: "binding-bgm",
          asset_id: null,
          enabled: true,
          trim_start_seconds: 0,
          trim_end_seconds: null,
          volume: 0.2,
          fade_in_seconds: 0,
          fade_out_seconds: 0,
        },
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
        bgm_binding_id: null,
        bgm_node_id: null,
        bgm_asset_id: null,
        estimated_duration_seconds: 0,
        warnings: [],
      },
      last_successful_export: null,
      active_export: null,
    },
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    position: { x: 0, y: 0 },
    revision: 2,
    error: null,
    variation_draft: null,
    created_at: "2026-07-28T10:00:00Z",
    updated_at: "2026-07-28T10:00:00Z",
  };
}

function videoEntry(): EditingVideoEntryV2 {
  return {
    binding_id: "binding-video",
    asset_id: null,
    enabled: true,
    trim_start_seconds: 0,
    trim_end_seconds: null,
    volume: 1,
    preserve_native_audio: true,
    transition: "cut",
    transition_duration_seconds: 0,
    fit_mode: "fill",
  };
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

const workflow: AgentCanvasWorkflowV2 = {
  workflow_id: "workflow-1",
  project_id: "project-1",
  workflow_schema_version: 2,
  canvas_model: "agent_canvas_v1",
  revision: 4,
  layout_revision: 1,
  nodes: [],
  bindings: [],
  assets: [],
};

describe("useAgentCanvasEditing", () => {
  it("stages a video change locally until it is committed", async () => {
    const patchNode = vi.fn(() => Promise.resolve());
    const { result } = renderHook(() => (
      useAgentCanvasEditing(workflow, editingNode([videoEntry()]), patchNode)
    ));

    act(() => result.current.stageVideoUpdate("binding-video", {
      trim_start_seconds: 1.25,
    }));

    expect(result.current.inputs.videos[0]?.entry.trim_start_seconds).toBe(1.25);
    expect(patchNode).not.toHaveBeenCalled();

    await act(async () => result.current.commitStagedManifest());

    expect(patchNode).toHaveBeenCalledTimes(1);
    expect(patchNode.mock.calls[0]?.[1]).toMatchObject({
      structured_content: {
        video_entries: [{ trim_start_seconds: 1.25 }],
      },
    });
    expect(patchNode.mock.calls[0]?.[2]).toEqual({ coalesce: true });
  });

  it("commits the first and newest staged values without overlapping writes", async () => {
    const first = deferred<void>();
    const second = deferred<void>();
    const patchNode = vi.fn()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const { result } = renderHook(() => (
      useAgentCanvasEditing(workflow, editingNode([videoEntry()]), patchNode)
    ));

    act(() => {
      result.current.stageVideoUpdate("binding-video", { trim_start_seconds: 1 });
      void result.current.commitStagedManifest();
    });
    await waitFor(() => expect(patchNode).toHaveBeenCalledTimes(1));

    act(() => {
      result.current.stageVideoUpdate("binding-video", { trim_start_seconds: 2 });
      void result.current.commitStagedManifest();
      result.current.stageVideoUpdate("binding-video", { trim_start_seconds: 3 });
      void result.current.commitStagedManifest();
    });

    expect(patchNode).toHaveBeenCalledTimes(1);

    await act(async () => {
      first.resolve();
      await Promise.resolve();
    });
    await waitFor(() => expect(patchNode).toHaveBeenCalledTimes(2));

    expect(patchNode.mock.calls.map(([, patch]) => (
      (patch as CanvasNodePatchRequestV2).structured_content?.video_entries
    ))).toEqual([
      [expect.objectContaining({ trim_start_seconds: 1 })],
      [expect.objectContaining({ trim_start_seconds: 3 })],
    ]);

    await act(async () => {
      second.resolve();
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.hasPendingManifestCommit).toBe(false));
  });

  it("serializes immediate property updates through the manifest commit queue", async () => {
    const first = deferred<void>();
    const second = deferred<void>();
    const patchNode = vi.fn()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const { result } = renderHook(() => (
      useAgentCanvasEditing(workflow, editingNode(), patchNode)
    ));

    act(() => result.current.setBgmVolume(0.35));
    await waitFor(() => expect(patchNode).toHaveBeenCalledTimes(1));

    act(() => result.current.setBgmVolume(0.7));
    expect(patchNode).toHaveBeenCalledTimes(1);

    await act(async () => {
      first.resolve();
      await Promise.resolve();
    });
    await waitFor(() => expect(patchNode).toHaveBeenCalledTimes(2));
    expect(patchNode.mock.calls.map(([, patch]) => (
      (patch as CanvasNodePatchRequestV2).structured_content?.bgm?.volume
    ))).toEqual([0.35, 0.7]);

    await act(async () => {
      second.resolve();
      await Promise.resolve();
    });
  });

  it("restores the last confirmed manifest after rejection only when no newer draft exists", async () => {
    const failedCommit = deferred<void>();
    const patchNode = vi.fn(() => failedCommit.promise);
    const { result } = renderHook(() => (
      useAgentCanvasEditing(workflow, editingNode([videoEntry()]), patchNode)
    ));

    act(() => {
      result.current.stageVideoUpdate("binding-video", { trim_start_seconds: 1 });
      void result.current.commitStagedManifest();
    });
    await waitFor(() => expect(patchNode).toHaveBeenCalledTimes(1));

    act(() => result.current.stageVideoUpdate("binding-video", { trim_start_seconds: 2 }));

    await act(async () => {
      failedCommit.reject(new Error("network failure"));
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.error).toBe("network failure"));
    expect(result.current.inputs.videos[0]?.entry.trim_start_seconds).toBe(2);
    expect(result.current.hasPendingManifestCommit).toBe(false);
  });

  it("restores the last confirmed manifest after a rejected staged commit", async () => {
    const failedCommit = deferred<void>();
    const patchNode = vi.fn(() => failedCommit.promise);
    const { result } = renderHook(() => (
      useAgentCanvasEditing(workflow, editingNode([videoEntry()]), patchNode)
    ));

    act(() => {
      result.current.stageVideoUpdate("binding-video", { trim_start_seconds: 1 });
      void result.current.commitStagedManifest();
    });
    await waitFor(() => expect(patchNode).toHaveBeenCalledTimes(1));

    await act(async () => {
      failedCommit.reject(new Error("network failure"));
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.error).toBe("network failure"));
    expect(result.current.inputs.videos[0]?.entry.trim_start_seconds).toBe(0);
  });

  it("retains a successfully confirmed manifest as the rejection baseline", async () => {
    const first = deferred<void>();
    const second = deferred<void>();
    const patchNode = vi.fn()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const { result } = renderHook(() => (
      useAgentCanvasEditing(workflow, editingNode([videoEntry()]), patchNode)
    ));

    act(() => {
      result.current.stageVideoUpdate("binding-video", { trim_start_seconds: 1 });
      void result.current.commitStagedManifest();
    });
    await waitFor(() => expect(patchNode).toHaveBeenCalledTimes(1));

    await act(async () => {
      first.resolve();
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.hasPendingManifestCommit).toBe(false));

    act(() => {
      result.current.stageVideoUpdate("binding-video", { trim_start_seconds: 2 });
      void result.current.commitStagedManifest();
    });
    await waitFor(() => expect(patchNode).toHaveBeenCalledTimes(2));

    await act(async () => {
      second.reject(new Error("network failure"));
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.error).toBe("network failure"));
    expect(result.current.inputs.videos[0]?.entry.trim_start_seconds).toBe(1);
  });
});
