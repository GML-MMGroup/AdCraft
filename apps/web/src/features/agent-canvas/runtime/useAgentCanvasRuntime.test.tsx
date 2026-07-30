import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasWorkflowV2,
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
        next_after_seq: 42,
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
      next_after_seq: 0,
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
      seq,
      workflow_id: "workflow-1",
      event_type: "canvas_node_created",
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
      next_after_seq: 42,
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

  it("stores the latest redacted provider inputs by node ID", async () => {
    api.agentCanvasEvents.mockReset();
    api.agentCanvasEvents.mockResolvedValue({
      workflow_id: "workflow-1",
      events: [],
      next_after_seq: 42,
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
      seq: 43,
      workflow_id: "workflow-1",
      event_type: "provider_inputs_resolved",
      execution_id: "execution-1",
      node_id: "node-video-1",
      asset_id: null,
      binding_id: null,
      created_at: "2026-07-30T00:00:00Z",
      payload: {
        node_id: "node-video-1",
        model_id: "seedance-2",
        inputs: [{
          binding_id: "binding-storyboard",
          asset_id: "asset-storyboard",
          media_type: "image",
          input_role: "visual_reference",
          source_semantic_role: "storyboard_grid",
          reference_purpose: "storyboard_sequence",
          required: true,
          display_order: 0,
          label: "Image 1",
        }],
        requested_duration_seconds: 30,
        effective_duration_seconds: 15,
        normalizations: ["duration_clamped_to_provider_limit"],
      },
    });

    await waitFor(() => expect(
      result.current.state.resolvedInputsByNodeId["node-video-1"],
    ).toMatchObject({
      model_id: "seedance-2",
      inputs: [{
        binding_id: "binding-storyboard",
        label: "Image 1",
      }],
      effective_duration_seconds: 15,
    }));
  });
});
