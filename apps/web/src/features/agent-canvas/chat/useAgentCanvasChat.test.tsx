import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  ChatTimelineListResponseV2,
} from "../../../types-v2.ts";

const api = vi.hoisted(() => ({
  agentCanvasChatTimeline: vi.fn(),
  submitAgentCanvasChatMessage: vi.fn(),
  actOnAgentCanvasProposal: vi.fn(),
  actOnAgentCanvasCommandPlan: vi.fn(),
}));

vi.mock("../../../api/v2Client.ts", () => ({
  v2Api: api,
}));

import { useAgentCanvasChat } from "./useAgentCanvasChat.ts";

function workflow(workflowId: string): AgentCanvasWorkflowV2 {
  return {
    workflow_id: workflowId,
    project_id: `project-${workflowId}`,
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: 1,
    layout_revision: 1,
    nodes: [],
    bindings: [],
    assets: [],
  };
}

describe("useAgentCanvasChat", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    cleanup();
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("ignores a previous project's timeline response after the workflow changes", async () => {
    let finishOldRequest!: (value: ChatTimelineListResponseV2) => void;
    api.agentCanvasChatTimeline.mockImplementation((workflowId: string) => {
      if (workflowId === "workflow-old") {
        return new Promise((resolve) => {
          finishOldRequest = resolve;
        });
      }
      return new Promise(() => {});
    });
    const { result, rerender } = renderHook(
      ({ activeWorkflow }) => useAgentCanvasChat({
        workflow: activeWorkflow,
        chatRevision: 0,
        chatEvents: [],
        proposalPosition: { x: 0, y: 0 },
      }),
      { initialProps: { activeWorkflow: workflow("workflow-old") } },
    );

    await act(async () => {
      vi.advanceTimersByTime(80);
      await Promise.resolve();
    });
    expect(api.agentCanvasChatTimeline).toHaveBeenCalledWith("workflow-old", 0, 200);

    rerender({ activeWorkflow: workflow("workflow-new") });
    await act(async () => {
      finishOldRequest({
        workflow_id: "workflow-old",
        conversation_id: "conversation-old",
        items: [{
          item_type: "message",
          message_id: "message-old",
          conversation_id: "conversation-old",
          speaker: "adcraft_video_agent",
          text: "Old project response",
          linked_node_ids: [],
          script_node_id: null,
          proposal_id: null,
          sequence: 1,
          created_at: "2026-07-28T10:00:00Z",
        }],
        next_after_seq: 1,
      });
      await Promise.resolve();
    });

    expect(result.current.state.items).toEqual([]);
  });

  it("ignores a previous project's failed message submission after the workflow changes", async () => {
    let failOldRequest!: (error: Error) => void;
    api.agentCanvasChatTimeline.mockImplementation(() => new Promise(() => {}));
    api.submitAgentCanvasChatMessage.mockImplementation(() => new Promise((_resolve, reject) => {
      failOldRequest = reject;
    }));
    const { result, rerender } = renderHook(
      ({ activeWorkflow }) => useAgentCanvasChat({
        workflow: activeWorkflow,
        chatRevision: 0,
        chatEvents: [],
        proposalPosition: { x: 0, y: 0 },
      }),
      { initialProps: { activeWorkflow: workflow("workflow-old") } },
    );

    let submission!: Promise<boolean>;
    act(() => {
      submission = result.current.actions.submit({
        text: "Old project request",
        mentionedNodeIds: [],
        mentionedImageAssetIds: [],
      });
    });
    expect(result.current.state.sending).toBe(true);

    rerender({ activeWorkflow: workflow("workflow-new") });
    await act(async () => {
      failOldRequest(new Error("old request failed"));
      await submission;
    });

    expect(result.current.state.sending).toBe(false);
    expect(result.current.state.failedDraft).toBeNull();
    expect(result.current.state.error).toBeNull();
  });

  it("ignores a previous project's failed proposal action after the workflow changes", async () => {
    let failOldRequest!: (error: Error) => void;
    api.agentCanvasChatTimeline.mockImplementation(() => new Promise(() => {}));
    api.actOnAgentCanvasProposal.mockImplementation(() => new Promise((_resolve, reject) => {
      failOldRequest = reject;
    }));
    const { result, rerender } = renderHook(
      ({ activeWorkflow }) => useAgentCanvasChat({
        workflow: activeWorkflow,
        chatRevision: 0,
        chatEvents: [],
        proposalPosition: { x: 0, y: 0 },
      }),
      { initialProps: { activeWorkflow: workflow("workflow-old") } },
    );

    let action!: Promise<void>;
    act(() => {
      action = result.current.actions.selectProposal(
        "proposal-old",
        "option-old",
        "continue_planning",
      );
    });
    expect(result.current.state.actingProposalId).toBe("proposal-old");

    rerender({ activeWorkflow: workflow("workflow-new") });
    await act(async () => {
      failOldRequest(new Error("old action failed"));
      await action;
    });

    expect(result.current.state.actingProposalId).toBeNull();
    expect(result.current.state.error).toBeNull();
  });

  it("submits structured node and image mentions without embedding locators in prose", async () => {
    api.agentCanvasChatTimeline.mockImplementation(() => new Promise(() => {}));
    api.submitAgentCanvasChatMessage.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: "message-1",
      turn_id: "turn-1",
      status: "queued",
      events_cursor: 4,
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow("workflow-1"),
      chatRevision: 0,
      chatEvents: [],
      proposalPosition: { x: 0, y: 0 },
    }));

    await act(async () => {
      await result.current.actions.submit({
        text: "Use these references.",
        mentionedNodeIds: ["node-script-1", "node-video-1"],
        mentionedImageAssetIds: ["asset-image-1"],
      });
    });

    expect(api.submitAgentCanvasChatMessage).toHaveBeenCalledWith(
      "workflow-1",
      {
        text: "Use these references.",
        mentioned_node_ids: ["node-script-1", "node-video-1"],
        mentioned_image_asset_ids: ["asset-image-1"],
        video_skill_run_id: null,
        auto_continue: false,
      },
      expect.any(String),
    );
  });

  it("confirms and rejects command plans through stable structured actions", async () => {
    api.agentCanvasChatTimeline.mockImplementation(() => new Promise(() => {}));
    api.actOnAgentCanvasCommandPlan.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: null,
      turn_id: "turn-command-1",
      status: "queued",
      events_cursor: 8,
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow("workflow-1"),
      chatRevision: 0,
      chatEvents: [],
      proposalPosition: { x: 0, y: 0 },
    }));

    await act(async () => {
      await result.current.actions.actOnCommandPlan("plan-1", "confirm");
    });
    await act(async () => {
      await result.current.actions.actOnCommandPlan("plan-2", "reject");
    });

    expect(api.actOnAgentCanvasCommandPlan).toHaveBeenNthCalledWith(
      1,
      "workflow-1",
      "plan-1",
      { action: "confirm" },
      expect.stringContaining("command-confirm"),
    );
    expect(api.actOnAgentCanvasCommandPlan).toHaveBeenNthCalledWith(
      2,
      "workflow-1",
      "plan-2",
      { action: "reject" },
      expect.stringContaining("command-reject"),
    );
  });

  it("delivers a structured action receipt once for the accepted action turn", async () => {
    const onActionReceipt = vi.fn();
    api.agentCanvasChatTimeline.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      items: [{
        item_type: "action_receipt",
        action_receipt: {
          receipt_id: "receipt-1",
          workflow_id: "workflow-1",
          plan_id: "plan-1",
          action_id: null,
          status: "applied",
          summary: "Created one image node.",
          created_node_ids: ["node-image-1"],
          updated_node_ids: [],
          deleted_node_ids: [],
          created_binding_ids: [],
          deleted_binding_ids: [],
          queued_execution_ids: [],
          run_queue_errors: [],
          operation_results: [],
          workflow_revision: 2,
          placement_hints: [{
            intent: "right_sibling",
            anchor_node_id: "node-script-1",
            group_key: null,
          }],
          continuation_turn_id: "turn-next-1",
          error_code: null,
          error_message: null,
        },
        sequence: 9,
        created_at: "2026-07-28T10:00:00Z",
      }],
      next_after_seq: 9,
    });
    api.actOnAgentCanvasCommandPlan.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: null,
      turn_id: "turn-command-1",
      status: "queued",
      events_cursor: 8,
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow("workflow-1"),
      chatRevision: 0,
      chatEvents: [],
      proposalPosition: { x: 0, y: 0 },
      onActionReceipt,
    }));

    await act(async () => {
      await result.current.actions.actOnCommandPlan("plan-1", "confirm");
      await result.current.actions.refresh();
    });
    expect(onActionReceipt).toHaveBeenCalledTimes(1);
    expect(onActionReceipt).toHaveBeenCalledWith(expect.objectContaining({
      receipt_id: "receipt-1",
      created_node_ids: ["node-image-1"],
    }));

    await act(async () => {
      await result.current.actions.refresh();
    });
    expect(onActionReceipt).toHaveBeenCalledTimes(1);
  });

  it("delivers an automatically applied command receipt identified by its SSE receipt id", async () => {
    const onActionReceipt = vi.fn();
    api.agentCanvasChatTimeline.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      items: [{
        item_type: "action_receipt",
        action_receipt: {
          receipt_id: "receipt-auto-1",
          workflow_id: "workflow-1",
          plan_id: "plan-auto-1",
          action_id: null,
          status: "applied",
          summary: "Created one scene node.",
          created_node_ids: ["node-scene-1"],
          updated_node_ids: [],
          deleted_node_ids: [],
          created_binding_ids: [],
          deleted_binding_ids: [],
          queued_execution_ids: [],
          run_queue_errors: [],
          operation_results: [],
          workflow_revision: 3,
          placement_hints: [{
            intent: "append_flow",
            anchor_node_id: null,
            group_key: "scene",
          }],
          continuation_turn_id: null,
          error_code: null,
          error_message: null,
        },
        sequence: 10,
        created_at: "2026-07-28T10:00:01Z",
      }],
      next_after_seq: 10,
    });
    renderHook(() => useAgentCanvasChat({
      workflow: workflow("workflow-1"),
      chatRevision: 1,
      chatEvents: [{
        seq: 10,
        workflow_id: "workflow-1",
        event_type: "agent_action_receipt_created",
        execution_id: null,
        node_id: null,
        asset_id: null,
        binding_id: null,
        created_at: "2026-07-28T10:00:01Z",
        payload: { receipt_id: "receipt-auto-1", plan_id: "plan-auto-1" },
      }],
      proposalPosition: { x: 0, y: 0 },
      onActionReceipt,
    }));

    await act(async () => {
      vi.advanceTimersByTime(80);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(onActionReceipt).toHaveBeenCalledOnce();
    expect(onActionReceipt).toHaveBeenCalledWith(expect.objectContaining({
      receipt_id: "receipt-auto-1",
    }));
  });
});
