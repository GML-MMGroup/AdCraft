import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  CanvasNodePatchRequestV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";

vi.mock("../../../api/v2Client.ts", () => ({
  isV2ApiError: () => false,
  v2Api: {
    exportAgentCanvasEditingNode: vi.fn(),
    cancelAgentCanvasEditingExport: vi.fn(),
  },
}));

import { useAgentCanvasEditing } from "./useAgentCanvasEditing.ts";

function editingNode(): CanvasNodeV2 {
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
        video_entries: [],
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
  it("keeps accepting manifest edits while an earlier save is pending", async () => {
    let finishFirst!: () => void;
    let finishSecond!: () => void;
    const patchNode = vi.fn((
      _nodeId: string,
      _patch: CanvasNodePatchRequestV2,
    ) => new Promise<void>((resolve) => {
      if (!finishFirst) finishFirst = resolve;
      else finishSecond = resolve;
    }));
    const { result } = renderHook(() => (
      useAgentCanvasEditing(workflow, editingNode(), patchNode)
    ));

    act(() => result.current.setBgmVolume(0.35));
    await waitFor(() => expect(result.current.saving).toBe(true));
    act(() => result.current.setBgmVolume(0.7));

    expect(result.current.content?.manifest.bgm?.volume).toBe(0.7);
    expect(patchNode).toHaveBeenCalledTimes(2);
    expect(patchNode.mock.calls[1]?.[1]).toMatchObject({
      structured_content: {
        bgm: {
          volume: 0.7,
        },
      },
    });
    expect(patchNode.mock.calls[1]?.[2]).toEqual({ coalesce: true });

    await act(async () => {
      finishFirst();
      finishSecond();
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.saving).toBe(false));
  });
});
