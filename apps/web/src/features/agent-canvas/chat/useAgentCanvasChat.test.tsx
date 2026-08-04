import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasChatViewTimelineV2,
  AgentCanvasWorkflowV2,
} from "../../../types-v2.ts";

const api = vi.hoisted(() => ({
  agentCanvasChatTimeline: vi.fn(),
  agentCanvasProposal: vi.fn(),
  submitAgentCanvasChatMessage: vi.fn(),
  actOnAgentCanvasProposal: vi.fn(),
  actOnAgentCanvasCommandPlan: vi.fn(),
  applyAgentCanvasGuidedAction: vi.fn(),
}));

vi.mock("../../../api/v2Client.ts", () => ({
  v2Api: api,
  isV2ApiError: (value: unknown) => Boolean(
    value
    && typeof value === "object"
    && typeof (value as { code?: unknown }).code === "string",
  ),
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
    let finishOldRequest!: (value: AgentCanvasChatViewTimelineV2) => void;
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
        creative_session: {
          skill_run_id: "skill-run-old",
          workflow_id: "workflow-old",
          skill_id: "video-ad",
          skill_version: "1",
          status: "active",
          creation_mode: null,
          active_recipe: null,
          readiness: null,
          creative_direction_snapshot_id: null,
          current_topic_id: null,
          topics: [],
          deferred_topic_ids: [],
          memory_revision: 1,
          updated_at: "2026-07-28T10:00:00Z",
        },
        creation_mode: null,
        recipe: null,
        continuations: [],
        current_session_actions: [],
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
        next_cursor: 1,
      });
      await Promise.resolve();
    });

    expect(result.current.state.items).toEqual([]);
    expect(result.current.state.creativeSession).toBeNull();
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
        "draft_only",
        [],
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
      },
      expect.any(String),
    );
  });

  it("reuses the chat idempotency key when retrying an uncertain submission", async () => {
    api.agentCanvasChatTimeline.mockImplementation(() => new Promise(() => {}));
    api.submitAgentCanvasChatMessage
      .mockRejectedValueOnce(new Error("response lost"))
      .mockResolvedValueOnce({
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
        text: "Keep this request idempotent.",
        mentionedNodeIds: [],
        mentionedImageAssetIds: [],
      });
    });
    expect(result.current.state.failedDraft).not.toBeNull();

    await act(async () => {
      await result.current.actions.submit(result.current.state.failedDraft!);
    });

    const firstKey = api.submitAgentCanvasChatMessage.mock.calls[0]?.[2];
    const retryKey = api.submitAgentCanvasChatMessage.mock.calls[1]?.[2];
    expect(firstKey).toBe(retryKey);
  });

  it("hydrates durable proposal pointers after refresh", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      creative_session: {
        skill_run_id: "session-1",
        workflow_id: "workflow-1",
        skill_id: "video-ad",
        skill_version: "1",
        status: "active",
        creation_mode: {
          mode: "ordinary_conversation",
          reason: "The user is continuing an ordinary conversation.",
          target_node_id: null,
          target_asset_id: null,
        },
        active_recipe: null,
        readiness: null,
        creative_direction_snapshot_id: null,
        current_topic_id: "characters",
        topics: [{
          topic_id: "characters",
          topic_kind: "character",
          display_order: 0,
          required: true,
          specialist_name: "character_designer",
          status: "in_review",
          outcome: null,
          related_node_ids: [],
        }],
        deferred_topic_ids: [],
        memory_revision: 2,
        updated_at: "2026-07-30T08:00:00Z",
      },
      current_session_actions: [{
        action_id: "action-add-character",
        logical_key: "add-another:characters",
        action: "add_another_topic_node",
        state: "pending",
        creating_turn_id: "turn-1",
        expected_semantic_revision: 3,
        label: "Add another",
        workflow_id: "workflow-1",
        proposal_id: "proposal-1",
        topic_id: "characters",
        node_id: null,
        ordered_node_ids: [],
        manifest_revision: null,
        recipe_id: null,
        recipe_revision: null,
        confirmation_required: false,
        reason: "Create another character direction.",
      }],
      items: [{
        item_type: "proposal_pointer",
        proposal_id: "proposal-1",
        sequence: 3,
        created_at: "2026-07-30T08:00:00Z",
      }],
      next_cursor: 3,
    });
    api.agentCanvasProposal.mockResolvedValue({
      proposal_id: "proposal-1",
      workflow_id: "workflow-1",
      turn_id: "turn-1",
      video_skill_run_id: "session-1",
      topic_id: "characters",
      creative_direction_snapshot_id: null,
      proposal_revision: 1,
      source_proposal_id: null,
      proposal_kind: "character",
      specialist_name: "character_designer",
      options: [{ option_id: "option-1", title: "Hero", summary_prompt: "Editorial lead" }],
      proposed_references: [],
      target_node_id: null,
      target_node_revision: null,
      proposal_purpose: null,
      availability: "open",
      application_count: 0,
      latest_application: null,
      available_actions: ["select", "revise", "archive"],
      created_at: "2026-07-30T08:00:00Z",
      updated_at: "2026-07-30T08:00:00Z",
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow("workflow-1"),
      chatRevision: 0,
      chatEvents: [],
      proposalPosition: { x: 0, y: 0 },
    }));

    await act(async () => {
      await result.current.actions.refresh();
    });

    expect(api.agentCanvasProposal).toHaveBeenCalledWith("workflow-1", "proposal-1");
    expect(result.current.state.items[0]).toMatchObject({
      item_type: "proposal",
      proposal: { proposal_id: "proposal-1" },
    });
    expect(result.current.state.creativeSession).toMatchObject({
      current_topic_id: "characters",
      memory_revision: 2,
    });
    expect(result.current.state.creationMode).toBe("ordinary_conversation");
    expect(result.current.state.recipe).toBeNull();
    expect(result.current.state.currentSessionActions).toEqual([
      expect.objectContaining({ action_id: "action-add-character" }),
    ]);
  });

  it("validates proposal cardinality against the nested active recipe", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      creative_session: {
        skill_run_id: "session-1",
        workflow_id: "workflow-1",
        skill_id: "video-ad",
        skill_version: "1",
        status: "active",
        creation_mode: {
          mode: "guided_production",
          reason: "The user requested guided production.",
          target_node_id: null,
          target_asset_id: null,
        },
        active_recipe: {
          recipe_id: "recipe-1",
          workflow_id: "workflow-1",
          conversation_id: "conversation-1",
          skill_run_id: "session-1",
          revision: 1,
          creation_mode: "guided_production",
          goal: "Create a complete short advertisement.",
          current_topic_id: "characters",
          stages: [{
            topic_id: "characters",
            topic_kind: "character",
            title: "Character design",
            objective: "Choose the campaign lead.",
            applicability: "required",
            applicability_reason: "The campaign needs a lead character.",
            specialist_name: "character_designer",
            proposal_mode: "choice_set",
            candidate_count: 2,
            status: "working",
            related_node_ids: [],
          }],
          anchor_digest: "anchor-1",
          deliverables: [],
          dependencies: [],
          recommended_next_topic_ids: ["characters"],
          completion_criteria: {
            required_deliverable_ids: [],
            accepted_omission_deliverable_ids: [],
          },
          created_at: "2026-07-31T05:00:00Z",
          updated_at: "2026-07-31T05:01:00Z",
        },
        readiness: null,
        creative_direction_snapshot_id: null,
        current_topic_id: "characters",
        topics: [],
        deferred_topic_ids: [],
        memory_revision: 2,
        updated_at: "2026-07-31T05:01:00Z",
      },
      items: [{
        item_type: "proposal_pointer",
        proposal_id: "proposal-1",
        sequence: 3,
        created_at: "2026-07-31T05:01:00Z",
      }],
      next_cursor: 3,
    });
    api.agentCanvasProposal.mockResolvedValue({
      proposal_id: "proposal-1",
      workflow_id: "workflow-1",
      turn_id: "turn-1",
      video_skill_run_id: "session-1",
      topic_id: "characters",
      creative_direction_snapshot_id: null,
      proposal_revision: 1,
      source_proposal_id: null,
      proposal_kind: "character",
      specialist_name: "character_designer",
      options: [{ option_id: "option-1", title: "Hero", summary_prompt: "Editorial lead" }],
      proposed_references: [],
      target_node_id: null,
      target_node_revision: null,
      proposal_purpose: null,
      availability: "open",
      application_count: 0,
      latest_application: null,
      available_actions: ["select", "revise", "archive"],
      created_at: "2026-07-31T05:01:00Z",
      updated_at: "2026-07-31T05:01:00Z",
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow("workflow-1"),
      chatRevision: 0,
      chatEvents: [],
      proposalPosition: { x: 0, y: 0 },
    }));

    await act(async () => {
      await result.current.actions.refresh();
    });

    expect(result.current.state.recipe).toMatchObject({ recipe_id: "recipe-1" });
    expect(result.current.state.items[0]).toMatchObject({
      item_type: "proposal_pointer",
      proposal_id: "proposal-1",
    });
    expect(result.current.state.error).toBe(
      "The current proposal is incomplete and needs to be regenerated.",
    );
  });

  it("restores a backend continuation as Agent work in progress after refresh", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      creative_session: null,
      continuations: [{
        continuation_id: "continuation-1",
        delivery_status: "retry_wait",
        attempt_count: 2,
        next_attempt_at: "2026-07-31T05:00:00Z",
        source_turn_id: "turn-1",
        continuation_turn_id: "turn-2",
        max_attempts: 3,
        last_error_code: null,
        last_error_message: null,
      }],
      items: [],
      next_cursor: 0,
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow("workflow-1"),
      chatRevision: 0,
      chatEvents: [],
      proposalPosition: { x: 0, y: 0 },
    }));

    await act(async () => {
      await result.current.actions.refresh();
    });

    expect(result.current.state.continuations).toEqual([
      expect.objectContaining({
        continuation_id: "continuation-1",
        delivery_status: "retry_wait",
        attempt_count: 2,
      }),
    ]);
    expect(result.current.state.error).toBeNull();
  });

  it("does not treat a not-applied guided receipt as a canvas mutation", async () => {
    const onActionReceipt = vi.fn();
    api.agentCanvasChatTimeline.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      creative_session: null,
      continuations: [],
      items: [{
        item_type: "action_receipt",
        action_receipt: {
          receipt_id: "receipt-noop-1",
          workflow_id: "workflow-1",
          plan_id: null,
          action_id: "action-1",
          status: "not_applied",
          summary: "No additional node was needed.",
          created_node_ids: [],
          updated_node_ids: [],
          deleted_node_ids: [],
          created_binding_ids: [],
          deleted_binding_ids: [],
          queued_execution_ids: [],
          run_queue_errors: [],
          operation_results: [],
          workflow_revision: 2,
          before_workflow_revision: 2,
          placement_hints: [],
          continuation_turn_id: null,
          continuation_id: null,
          superseded_by: null,
          error: null,
          error_code: null,
          error_message: null,
        },
        sequence: 1,
        created_at: "2026-07-31T05:00:00Z",
      }],
      next_cursor: 1,
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow("workflow-1"),
      chatRevision: 0,
      chatEvents: [{
        seq: 1,
        workflow_id: "workflow-1",
        event_type: "action_receipt_created",
        project_id: "project-workflow-1",
        execution_id: null,
        node_id: null,
        asset_id: null,
        binding_id: null,
        conversation_id: "conversation-1",
        turn_id: "turn-1",
        action_id: "action-1",
        trace_id: null,
        span_id: null,
        created_at: "2026-07-31T05:00:00Z",
        payload: { receipt_id: "receipt-noop-1" },
      }],
      proposalPosition: { x: 0, y: 0 },
      onActionReceipt,
    }));

    await act(async () => {
      await result.current.actions.refresh();
    });

    expect(onActionReceipt).not.toHaveBeenCalled();
    expect(result.current.state.notice).toBe("No additional node was needed.");
  });

  it("uses a new idempotency key for every deliberate proposal application", async () => {
    api.agentCanvasChatTimeline.mockImplementation(() => new Promise(() => {}));
    api.actOnAgentCanvasProposal.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: null,
      turn_id: "turn-select-1",
      status: "queued",
      events_cursor: 4,
    });
    const reference = {
      source_kind: "image_asset" as const,
      source_id: "asset-1",
      binding_kind: "image_reference" as const,
      input_role: "image_reference" as const,
      required: true,
      display_order: 0,
      display_name: "Hero reference",
      media_type: "image" as const,
    };
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow("workflow-1"),
      chatRevision: 0,
      chatEvents: [],
      proposalPosition: { x: 120, y: 240 },
    }));

    await act(async () => {
      await result.current.actions.selectProposal(
        "proposal-1",
        "option-1",
        "draft_only",
        [reference],
      );
    });
    await act(async () => {
      await result.current.actions.selectProposal(
        "proposal-1",
        "option-1",
        "draft_only",
        [reference],
      );
    });

    expect(api.actOnAgentCanvasProposal).toHaveBeenCalledWith(
      "workflow-1",
      "proposal-1",
      {
        action: "select",
        option_id: "option-1",
        generation_action: "draft_only",
        accepted_references: [reference],
        position: { x: 120, y: 240 },
      },
      expect.stringContaining("proposal-select"),
    );
    const firstKey = api.actOnAgentCanvasProposal.mock.calls[0]?.[3];
    const secondKey = api.actOnAgentCanvasProposal.mock.calls[1]?.[3];
    expect(firstKey).not.toBe(secondKey);
  });

  it("archives and reopens proposal cards through structured proposal actions", async () => {
    api.agentCanvasChatTimeline.mockImplementation(() => new Promise(() => {}));
    api.actOnAgentCanvasProposal.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: null,
      turn_id: "turn-proposal-state-1",
      status: "queued",
      events_cursor: 7,
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow("workflow-1"),
      chatRevision: 0,
      chatEvents: [],
      proposalPosition: { x: 0, y: 0 },
    }));

    await act(async () => {
      await result.current.actions.setProposalAvailability("proposal-1", "archive");
    });
    await act(async () => {
      await result.current.actions.setProposalAvailability("proposal-1", "reopen");
    });

    expect(api.actOnAgentCanvasProposal).toHaveBeenNthCalledWith(
      1,
      "workflow-1",
      "proposal-1",
      { action: "archive" },
      expect.stringContaining("proposal-archive"),
    );
    expect(api.actOnAgentCanvasProposal).toHaveBeenNthCalledWith(
      2,
      "workflow-1",
      "proposal-1",
      { action: "reopen" },
      expect.stringContaining("proposal-reopen"),
    );
  });

  it("keeps an unavailable proposal visible with its structured backend reason", async () => {
    api.agentCanvasChatTimeline.mockImplementation(() => new Promise(() => {}));
    api.actOnAgentCanvasProposal.mockRejectedValue({
      code: "proposal_reference_unavailable",
      message: "The selected reference is no longer available.",
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow("workflow-1"),
      chatRevision: 0,
      chatEvents: [],
      proposalPosition: { x: 0, y: 0 },
    }));

    await act(async () => {
      await result.current.actions.selectProposal(
        "proposal-1",
        "option-1",
        "draft_only",
        [],
      );
    });

    expect(result.current.state.proposalIssues["proposal-1"]).toBe(
      "The selected reference is no longer available.",
    );
    expect(result.current.state.error).toBeNull();
  });

  it("applies guided actions by stable id rather than resubmitting the label", async () => {
    api.agentCanvasChatTimeline.mockImplementation(() => new Promise(() => {}));
    api.applyAgentCanvasGuidedAction.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: null,
      turn_id: "turn-guided-1",
      status: "queued",
      events_cursor: 5,
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow("workflow-1"),
      chatRevision: 0,
      chatEvents: [],
      proposalPosition: { x: 0, y: 0 },
    }));

    await act(async () => {
      await result.current.actions.applyGuidedAction("action-1");
    });

    expect(api.applyAgentCanvasGuidedAction).toHaveBeenCalledWith(
      "workflow-1",
      "action-1",
      { confirmed: true },
      expect.stringContaining("guided-action"),
    );
  });

  it("delivers a guided action receipt by its stable action id after SSE recovery", async () => {
    const onActionReceipt = vi.fn();
    api.agentCanvasChatTimeline.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      creative_session: null,
      items: [{
        item_type: "action_receipt",
        action_receipt: {
          receipt_id: "receipt-guided-1",
          workflow_id: "workflow-1",
          plan_id: null,
          action_id: "action-1",
          status: "applied",
          summary: "Created another draft.",
          created_node_ids: ["node-image-1"],
          updated_node_ids: [],
          deleted_node_ids: [],
          created_binding_ids: [],
          deleted_binding_ids: [],
          queued_execution_ids: [],
          run_queue_errors: [],
          operation_results: [],
          workflow_revision: 2,
          placement_hints: [],
          continuation_turn_id: null,
          error_code: null,
          error_message: null,
        },
        sequence: 6,
        created_at: "2026-07-30T08:00:00Z",
      }],
      next_cursor: 6,
    });
    api.applyAgentCanvasGuidedAction.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: null,
      turn_id: "turn-guided-1",
      status: "queued",
      events_cursor: 5,
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow("workflow-1"),
      chatRevision: 0,
      chatEvents: [],
      proposalPosition: { x: 0, y: 0 },
      onActionReceipt,
    }));

    await act(async () => {
      await result.current.actions.applyGuidedAction("action-1");
      await result.current.actions.refresh();
    });

    expect(onActionReceipt).toHaveBeenCalledOnce();
    expect(onActionReceipt).toHaveBeenCalledWith(expect.objectContaining({
      receipt_id: "receipt-guided-1",
      action_id: "action-1",
    }));
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
      creative_session: null,
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
      next_cursor: 9,
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
      creative_session: null,
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
      next_cursor: 10,
    });
    renderHook(() => useAgentCanvasChat({
      workflow: workflow("workflow-1"),
      chatRevision: 1,
      chatEvents: [{
        seq: 10,
        workflow_id: "workflow-1",
        event_type: "action_receipt_created",
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
