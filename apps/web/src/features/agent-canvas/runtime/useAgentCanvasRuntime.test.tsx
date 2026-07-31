import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
  CanvasRuntimeSnapshotV2,
} from "../../../types-v2.ts";

const api = vi.hoisted(() => ({
  agentCanvasEvents: vi.fn(),
  agentCanvasRuntime: vi.fn(),
  agentCanvasWorkflowWithEtag: vi.fn(),
  listAgentCanvasProjectAssets: vi.fn(),
  agentCanvasNode: vi.fn(),
  openAgentCanvasEventStream: vi.fn(),
  runAgentCanvas: vi.fn(),
  cancelAgentCanvasRun: vi.fn(),
}));

vi.mock("../../../api/v2Client.ts", () => ({
  isV2ApiError: (value: unknown) => (
    typeof value === "object"
    && value !== null
    && "status" in value
    && "code" in value
  ),
  v2Api: api,
}));

import { useAgentCanvasRuntime } from "./useAgentCanvasRuntime.ts";

const workflow: AgentCanvasWorkflowV2 = {
  workflow_id: "workflow-1",
  project_id: "project-1",
  workflow_schema_version: 2,
  canvas_model: "agent_canvas_v1",
  revision: 1,
  layout_revision: 1,
  nodes: [],
  bindings: [],
  assets: [],
};

const runtime: CanvasRuntimeSnapshotV2 = {
  workflow_id: "workflow-1",
  active_execution_id: null,
  execution_status: null,
  node_runtime: {},
  queued_node_ids: [],
  working_node_ids: [],
  waiting_node_ids: [],
  ready_node_ids: [],
  failed_node_ids: [],
  events_cursor: 42,
  updated_at: "2026-07-28T00:00:00Z",
};

class EventSourceStub {
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private readonly listeners = new Map<string, Array<(event: MessageEvent<string>) => void>>();

  addEventListener(type: string, listener: EventListener) {
    const current = this.listeners.get(type) ?? [];
    current.push(listener as (event: MessageEvent<string>) => void);
    this.listeners.set(type, current);
  }

  close() {}

  emit(type: string, payload: unknown) {
    const event = { data: JSON.stringify(payload) } as MessageEvent<string>;
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }
}

describe("useAgentCanvasRuntime", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.agentCanvasEvents
      .mockRejectedValueOnce({
        status: 409,
        code: "event_cursor_expired",
      })
      .mockResolvedValue({
        workflow_id: "workflow-1",
        events: [],
        next_cursor: 42,
      });
    api.agentCanvasRuntime.mockResolvedValue(runtime);
    api.agentCanvasWorkflowWithEtag.mockResolvedValue({ value: workflow, etag: "\"workflow-r1\"" });
    api.openAgentCanvasEventStream.mockReturnValue(new EventSourceStub());
  });

  it("recovers an expired replay cursor from the canonical runtime snapshot", async () => {
    const callbacks = {
      applyWorkflow: vi.fn(),
      mergePublishedAsset: vi.fn(),
      mergeNode: vi.fn(),
    };
    const { result } = renderHook(() => useAgentCanvasRuntime(workflow, callbacks));

    await waitFor(() => {
      expect(api.agentCanvasEvents).toHaveBeenCalledWith("workflow-1", 42, 200);
    });
    expect(api.agentCanvasRuntime).toHaveBeenCalledWith("workflow-1");
    expect(api.agentCanvasWorkflowWithEtag).toHaveBeenCalledWith("workflow-1");
    expect(result.current.state.chatRevision).toBe(1);
  });

  it("performs a trailing Workflow refresh when another event arrives in flight", async () => {
    api.agentCanvasEvents.mockReset();
    api.agentCanvasEvents.mockResolvedValue({
      workflow_id: "workflow-1",
      events: [],
      next_cursor: 0,
    });
    const eventSource = new EventSourceStub();
    api.openAgentCanvasEventStream.mockReturnValue(eventSource);
    let resolveFirstRefresh!: (value: { value: AgentCanvasWorkflowV2; etag: string }) => void;
    api.agentCanvasWorkflowWithEtag
      .mockReset()
      .mockImplementationOnce(() => new Promise((resolve) => {
        resolveFirstRefresh = resolve;
      }))
      .mockResolvedValue({ value: { ...workflow, revision: 3 }, etag: "\"workflow-r3\"" });
    const callbacks = {
      applyWorkflow: vi.fn(),
      mergePublishedAsset: vi.fn(),
      mergeNode: vi.fn(),
    };
    renderHook(() => useAgentCanvasRuntime(workflow, callbacks));
    await waitFor(() => expect(api.openAgentCanvasEventStream).toHaveBeenCalledOnce());
    await waitFor(() => expect(eventSource.onmessage).not.toBeNull());

    const event = (seq: number) => ({
      sequence_no: seq,
      workflow_id: "workflow-1",
      event_type: "node_created",
      execution_id: null,
      node_id: `node-${seq}`,
      asset_id: null,
      binding_id: null,
      created_at: "2026-07-28T00:01:00Z",
      payload: {},
    });
    eventSource.onmessage?.({
      data: JSON.stringify(event(43)),
    } as MessageEvent<string>);
    await waitFor(() => expect(api.agentCanvasWorkflowWithEtag).toHaveBeenCalledOnce());
    eventSource.onmessage?.({
      data: JSON.stringify(event(44)),
    } as MessageEvent<string>);
    resolveFirstRefresh({ value: { ...workflow, revision: 2 }, etag: "\"workflow-r2\"" });

    await waitFor(() => expect(api.agentCanvasWorkflowWithEtag).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(callbacks.applyWorkflow).toHaveBeenLastCalledWith(
      expect.objectContaining({ revision: 3 }),
    ));
  });

  it("starts replay from the runtime high-water mark instead of replaying historical receipts", async () => {
    api.agentCanvasEvents.mockReset();
    api.agentCanvasEvents.mockResolvedValue({
      workflow_id: "workflow-1",
      events: [],
      next_cursor: 42,
    });
    const callbacks = {
      applyWorkflow: vi.fn(),
      mergePublishedAsset: vi.fn(),
      mergeNode: vi.fn(),
    };
    const { result } = renderHook(() => useAgentCanvasRuntime(workflow, callbacks));

    await waitFor(() => expect(api.agentCanvasEvents).toHaveBeenCalledWith("workflow-1", 42, 200));
    expect(result.current.state.chatEvents).toEqual([]);
  });

  it("retains a sanitized provider input audit without creating client-side graph state", async () => {
    api.agentCanvasEvents.mockReset();
    api.agentCanvasEvents.mockResolvedValue({
      workflow_id: "workflow-1",
      events: [],
      next_cursor: 42,
    });
    const eventSource = new EventSourceStub();
    api.openAgentCanvasEventStream.mockReturnValue(eventSource);
    const callbacks = {
      applyWorkflow: vi.fn(),
      mergePublishedAsset: vi.fn(),
      mergeNode: vi.fn(),
    };
    const { result } = renderHook(() => useAgentCanvasRuntime(workflow, callbacks));

    await waitFor(() => expect(api.openAgentCanvasEventStream).toHaveBeenCalledOnce());
    eventSource.emit("provider_inputs_resolved", {
      sequence_no: 43,
      workflow_id: "workflow-1",
      event_type: "provider_inputs_resolved",
      project_id: "project-1",
      execution_id: "execution-1",
      node_id: "node-video-1",
      asset_id: null,
      binding_id: null,
      conversation_id: null,
      turn_id: null,
      action_id: null,
      trace_id: null,
      span_id: null,
      transition_key: "node-run:node-video-1:inputs-resolved:1",
      attempt: 1,
      created_at: "2026-07-31T04:00:00Z",
      payload: {
        input_manifest_id: "manifest-1",
        media_inputs: [{
          binding_id: "binding-image-1",
          source_node_id: "node-image-1",
          asset_id: "asset-image-1",
          media_type: "image",
          input_role: "image_reference",
          required: true,
          display_order: 0,
          media_url: "https://must-not-be-stored.example/image.png",
        }],
      },
    });

    await waitFor(() => expect(result.current.state.inputManifestsByNodeId["node-video-1"]).toEqual({
      node_id: "node-video-1",
      input_manifest_id: "manifest-1",
      execution_id: "execution-1",
      node_run_id: null,
      text_inputs: [],
      media_inputs: [{
        binding_id: "binding-image-1",
        source_node_id: "node-image-1",
        asset_id: "asset-image-1",
        media_type: "image",
        input_role: "image_reference",
        source_semantic_role: null,
        transport_type: null,
        required: true,
        display_order: 0,
      }],
      omitted_optional_inputs: [],
    }));
    expect(callbacks.applyWorkflow).not.toHaveBeenCalled();
  });

  it("advances the SSE cursor but ignores duplicate continuation transitions", async () => {
    api.agentCanvasEvents.mockReset();
    api.agentCanvasEvents.mockResolvedValue({
      workflow_id: "workflow-1",
      events: [],
      next_cursor: 42,
    });
    const eventSource = new EventSourceStub();
    api.openAgentCanvasEventStream.mockReturnValue(eventSource);
    const callbacks = {
      applyWorkflow: vi.fn(),
      mergePublishedAsset: vi.fn(),
      mergeNode: vi.fn(),
    };
    const { result } = renderHook(() => useAgentCanvasRuntime(workflow, callbacks));

    await waitFor(() => expect(api.openAgentCanvasEventStream).toHaveBeenCalledOnce());
    const event = (sequence_no: number) => ({
      sequence_no,
      workflow_id: "workflow-1",
      event_type: "continuation_started",
      project_id: "project-1",
      execution_id: null,
      node_id: null,
      asset_id: null,
      binding_id: null,
      conversation_id: "conversation-1",
      turn_id: "turn-1",
      action_id: null,
      trace_id: null,
      span_id: null,
      transition_key: "continuation-1:leased:1",
      attempt: 1,
      created_at: "2026-07-31T05:00:00Z",
      payload: {},
    });

    eventSource.emit("continuation_started", event(43));
    await waitFor(() => expect(result.current.state.chatRevision).toBe(1));
    eventSource.emit("continuation_started", event(44));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(result.current.state.chatRevision).toBe(1);
    expect(api.agentCanvasEvents).toHaveBeenCalledWith("workflow-1", 42, 200);
  });

  it("persists legacy Draft video parameters before submitting a global Run", async () => {
    api.agentCanvasEvents.mockReset();
    api.agentCanvasEvents.mockResolvedValue({
      workflow_id: "workflow-1",
      events: [],
      next_cursor: 42,
    });
    const draftVideo: CanvasNodeV2 = {
      node_id: "node-video-legacy",
      workflow_id: "workflow-1",
      node_type: "video",
      creative_role: "general_video",
      role_contract_version: "ad-media-role-v1",
      title: "Legacy Video Draft",
      status: "draft",
      summary_prompt: null,
      generation_prompt: "Animate the supplied references.",
      structured_content: {},
      model_id: null,
      parameters: {
        requested_duration_seconds: 0,
        effective_duration_seconds: 15,
      },
      prompt_context_snapshot_id: null,
      output_asset_id: null,
      position: { x: 0, y: 0 },
      revision: 1,
      error: null,
      variation_draft: null,
      created_at: "2026-07-31T04:00:00Z",
      updated_at: "2026-07-31T04:00:00Z",
    };
    let resolvePatch!: () => void;
    const patchNode = vi.fn(() => new Promise<void>((resolve) => {
      resolvePatch = resolve;
    }));
    const callbacks = {
      applyWorkflow: vi.fn(),
      mergePublishedAsset: vi.fn(),
      mergeNode: vi.fn(),
      patchNode,
    };
    const { result } = renderHook(() => useAgentCanvasRuntime({
      ...workflow,
      nodes: [draftVideo],
    }, callbacks));

    await waitFor(() => expect(api.openAgentCanvasEventStream).toHaveBeenCalledOnce());
    const runPromise = result.current.actions.runAll();
    await waitFor(() => expect(patchNode).toHaveBeenCalledWith(
      draftVideo.node_id,
      { parameters: {} },
    ));
    expect(api.runAgentCanvas).not.toHaveBeenCalled();

    resolvePatch();
    await runPromise;

    expect(api.runAgentCanvas).toHaveBeenCalledWith(
      "workflow-1",
      expect.objectContaining({ scope: "all_drafts" }),
      expect.any(String),
    );
  });

  it("keeps a selected node Draft and exposes required source IDs when backend preflight rejects it", async () => {
    api.agentCanvasEvents.mockReset();
    api.agentCanvasEvents.mockResolvedValue({
      workflow_id: "workflow-1",
      events: [],
      next_cursor: 42,
    });
    const draftVideo: CanvasNodeV2 = {
      node_id: "node-video-1",
      workflow_id: "workflow-1",
      node_type: "video",
      creative_role: "general_video",
      role_contract_version: "ad-media-role-v1",
      title: "Video Draft",
      status: "draft",
      summary_prompt: null,
      generation_prompt: "A short cinematic product video.",
      structured_content: {},
      model_id: "video-model",
      parameters: {},
      prompt_context_snapshot_id: null,
      output_asset_id: null,
      position: { x: 0, y: 0 },
      revision: 1,
      error: null,
      variation_draft: null,
      created_at: "2026-07-31T04:00:00Z",
      updated_at: "2026-07-31T04:00:00Z",
    };
    api.runAgentCanvas.mockRejectedValueOnce({
      status: 409,
      code: "upstream_inputs_not_ready",
      details: { missing_required_source_node_ids: ["node-script-1", "node-image-1"] },
    });
    const callbacks = {
      applyWorkflow: vi.fn(),
      mergePublishedAsset: vi.fn(),
      mergeNode: vi.fn(),
    };
    const { result } = renderHook(() => useAgentCanvasRuntime({ ...workflow, nodes: [draftVideo] }, callbacks));

    await waitFor(() => expect(api.openAgentCanvasEventStream).toHaveBeenCalledOnce());
    await expect(result.current.actions.runNode(draftVideo)).rejects.toMatchObject({ code: "upstream_inputs_not_ready" });

    await waitFor(() => expect(result.current.state.inputReadinessIssue).toEqual({
      target_node_id: "node-video-1",
      source_node_ids: ["node-script-1", "node-image-1"],
    }));
    expect(callbacks.mergeNode).not.toHaveBeenCalled();
  });

  it("does not submit a per-node Run for Ready media", async () => {
    api.agentCanvasEvents.mockReset();
    api.agentCanvasEvents.mockResolvedValue({
      workflow_id: "workflow-1",
      events: [],
      next_cursor: 42,
    });
    const readyImage: CanvasNodeV2 = {
      node_id: "image-ready-1",
      workflow_id: "workflow-1",
      node_type: "image",
      creative_role: "product",
      role_contract_version: "ad-media-role-v1",
      title: "Product image",
      status: "ready",
      summary_prompt: null,
      generation_prompt: "Product on black acrylic",
      structured_content: {},
      model_id: "image-model",
      parameters: {},
      prompt_context_snapshot_id: null,
      output_asset_id: "asset-1",
      position: { x: 0, y: 0 },
      revision: 2,
      error: null,
      variation_draft: null,
      created_at: "2026-07-30T00:00:00Z",
      updated_at: "2026-07-30T00:00:00Z",
    };
    const callbacks = {
      applyWorkflow: vi.fn(),
      mergePublishedAsset: vi.fn(),
      mergeNode: vi.fn(),
    };
    const { result } = renderHook(() => useAgentCanvasRuntime({
      ...workflow,
      nodes: [readyImage],
    }, callbacks));

    await waitFor(() => expect(api.openAgentCanvasEventStream).toHaveBeenCalledOnce());
    await result.current.actions.runNode(readyImage);

    expect(api.runAgentCanvas).not.toHaveBeenCalled();
  });
});
