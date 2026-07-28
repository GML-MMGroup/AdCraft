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
});
