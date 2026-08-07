import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasChatViewTimelineV2,
  AgentCanvasWorkflowV2,
  CanvasRuntimeEventV2,
  GuidanceSessionActionV2,
  ProposalActionDescriptorV2,
} from "../../../types-v2.ts";

const api = vi.hoisted(() => ({
  agentCanvasChatTimeline: vi.fn(),
  agentCanvasChatTurn: vi.fn(),
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

function workflow(workflowId = "workflow-1"): AgentCanvasWorkflowV2 {
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
    active_style_skill: null,
  };
}

function emptyTimeline(overrides: Partial<AgentCanvasChatViewTimelineV2> = {}): AgentCanvasChatViewTimelineV2 {
  return {
    workflow_id: "workflow-1",
    conversation_id: "conversation-1",
    guidanceSession: null,
    continuations: [],
    current_session_actions: [],
    items: [],
    next_cursor: 0,
    ...overrides,
  };
}

function descriptor(
  action: ProposalActionDescriptorV2["action"],
  actionId = `action-${action}`,
): ProposalActionDescriptorV2 {
  return {
    action_id: actionId,
    action,
    label: action.replaceAll("_", " "),
    proposal_id: "proposal-1",
    expected_session_revision: 7,
    confirmation_required: false,
    reason: "Continue the guided authoring session.",
    option_id: null,
    enabled: true,
    disabled_reason: null,
  };
}

function turnEvent(
  eventType: "agent_turn_queued" | "agent_turn_started" | "agent_turn_completed" | "agent_turn_failed",
  turnId = "turn-1",
  seq = 1,
): CanvasRuntimeEventV2 {
  return {
    seq,
    workflow_id: "workflow-1",
    event_type: eventType,
    project_id: null,
    execution_id: null,
    node_id: null,
    asset_id: null,
    binding_id: null,
    conversation_id: "conversation-1",
    turn_id: turnId,
    action_id: null,
    trace_id: null,
    span_id: null,
    created_at: "2026-08-04T10:00:00Z",
    payload: null,
  };
}

describe("useAgentCanvasChat", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    api.agentCanvasChatTimeline.mockImplementation(() => new Promise(() => {}));
    api.agentCanvasChatTurn.mockResolvedValue({
      turn_id: "turn-1",
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      status: "queued",
      turn_kind: "proposal_action",
      request: {},
      error_code: null,
      error_message: null,
      creation_mode: null,
      guidance_session_revision: null,
      continuation: null,
      created_at: "2026-08-04T10:00:00Z",
      updated_at: "2026-08-04T10:00:00Z",
    });
    api.actOnAgentCanvasProposal.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: null,
      turn_id: "turn-1",
      status: "queued",
      events_cursor: 1,
    });
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
      }),
      { initialProps: { activeWorkflow: workflow("workflow-old") } },
    );

    await act(async () => {
      vi.advanceTimersByTime(80);
      await Promise.resolve();
    });
    rerender({ activeWorkflow: workflow("workflow-new") });
    await act(async () => {
      finishOldRequest(emptyTimeline({
        workflow_id: "workflow-old",
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
          created_at: "2026-08-04T10:00:00Z",
        }],
      }));
      await Promise.resolve();
    });

    expect(result.current.state.items).toEqual([]);
    expect(result.current.state.guidanceSession).toBeNull();
  });

  it("submits explicit node and image mentions without requiring an inline continuation", async () => {
    api.submitAgentCanvasChatMessage.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: "message-1",
      turn_id: "turn-1",
      status: "queued",
      events_cursor: 4,
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
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
    expect(api.agentCanvasChatTurn).toHaveBeenCalledWith("workflow-1", "turn-1");
  });

  it("preserves an exact backend code when message submission is rejected", async () => {
    api.submitAgentCanvasChatMessage.mockRejectedValue({
      code: "proposal_persistence_failed",
      message: "The proposal could not be persisted.",
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.submit({
        text: "Create a calm product film.",
        mentionedNodeIds: [],
        mentionedImageAssetIds: [],
      });
    });

    expect(result.current.state.error).toBe(
      "proposal_persistence_failed: The proposal could not be persisted.",
    );
    expect(result.current.state.failedDraft).toMatchObject({
      text: "Create a calm product film.",
    });
  });

  it("keeps the Agent working after message acceptance until the turn becomes terminal", async () => {
    api.submitAgentCanvasChatMessage.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: "message-1",
      turn_id: "turn-1",
      status: "queued",
      events_cursor: 4,
    });
    const { result, rerender } = renderHook(
      ({ chatEvents }) => useAgentCanvasChat({
        workflow: workflow(),
        chatRevision: 0,
        chatEvents,
      }),
      { initialProps: { chatEvents: [] as CanvasRuntimeEventV2[] } },
    );

    await act(async () => {
      await result.current.actions.submit({
        text: "Create a calm product film.",
        mentionedNodeIds: [],
        mentionedImageAssetIds: [],
      });
    });

    expect(result.current.state.agentWorking).toBe(true);

    rerender({ chatEvents: [turnEvent("agent_turn_started")] });
    expect(result.current.state.agentWorking).toBe(true);

    rerender({
      chatEvents: [
        turnEvent("agent_turn_started"),
        turnEvent("agent_turn_completed", "turn-1", 2),
      ],
    });
    expect(result.current.state.agentWorking).toBe(false);
  });

  it("sends the active Workflow Style Skill Run with Director messages", async () => {
    api.submitAgentCanvasChatMessage.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: "message-2",
      turn_id: "turn-2",
      status: "queued",
      events_cursor: 5,
    });
    const activeWorkflow = workflow();
    activeWorkflow.active_style_skill = {
      skill_run_id: "style-run-2",
      skill_id: "cinematic-poetic-realism",
      skill_version: "1.0.0",
      title: "Cinematic Poetic Realism",
      summary: "A restrained cinematic treatment.",
      category: "cinematic-narrative",
      creative_direction_snapshot_id: "direction-2",
    };
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: activeWorkflow,
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.submit({
        text: "Create the next treatment.",
        mentionedNodeIds: [],
        mentionedImageAssetIds: [],
      });
    });

    expect(api.submitAgentCanvasChatMessage).toHaveBeenCalledWith(
      "workflow-1",
      expect.objectContaining({ video_skill_run_id: "style-run-2" }),
      expect.any(String),
    );
  });

  it("hydrates the durable guidance session, actions, and proposal card", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      guidanceSession: {
        session_id: "guidance-1",
        workflow_id: "workflow-1",
        status: "active",
        goal: {
          requested_output: "video",
          delivery_scope: "generated_media",
          summary: "Create a product film.",
          explicit_constraints: {},
        },
        creative_authority: {
          authority: "user",
          source: "explicit_user",
          decided_at_turn_id: "turn-authority-1",
          revision: 1,
        },
        current_checkpoint: null,
        narrative_direction: null,
        element_decisions: [],
        current_topic_id: "topic-character",
        topics: [{
          topic_id: "topic-character",
          topic_kind: "character",
          title: "Lead character",
          status: "proposed",
          capability_id: "character_design",
          capability_display_name: "Character Designer",
          related_node_ids: [],
          source_proposal_id: "proposal-1",
          revision: 1,
        }],
        active_proposal_id: "proposal-1",
        active_style_skill_run_id: null,
        completion: {
          authoring: "not_ready",
          delivery: "not_ready",
          editing_preparation: "not_ready",
          editing_node_id: null,
          matching_node_ids: [],
          matching_asset_ids: [],
        },
        revision: 7,
        updated_at: "2026-08-04T10:00:00Z",
      },
      current_session_actions: [{
        action_id: "action-stop",
        logical_key: "stop:guidance-1:7",
        action: "stop_guidance",
        state: "pending",
        creating_turn_id: "turn-1",
        expected_session_revision: 7,
        label: "Stop guidance",
        workflow_id: "workflow-1",
        confirmation_required: true,
        reason: "Keep the current drafts and stop planning.",
      }],
      items: [{
        item_type: "proposal_pointer",
        proposal_id: "proposal-1",
        sequence: 3,
        created_at: "2026-08-04T10:00:00Z",
      }],
      next_cursor: 3,
    }));
    api.agentCanvasProposal.mockResolvedValue({
      proposal_id: "proposal-1",
      workflow_id: "workflow-1",
      turn_id: "turn-1",
      video_skill_run_id: null,
      topic_id: "topic-character",
      creative_direction_snapshot_id: null,
      proposal_revision: 1,
      source_proposal_id: null,
      proposal_kind: "character",
      capability_id: "character_design",
      capability_display_name: "Character Designer",
      options: [{ option_id: "option-1", title: "Hero", public_summary: "Editorial lead" }],
      proposed_references: [],
      target_node_id: null,
      target_node_revision: null,
      proposal_purpose: null,
      availability: "open",
      application_count: 0,
      latest_application: null,
      guidance_session_id: "guidance-1",
      guidance_session_revision: 7,
      actions: [descriptor("select_option")],
      created_at: "2026-08-04T10:00:00Z",
      updated_at: "2026-08-04T10:00:00Z",
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.refresh();
    });

    expect(result.current.state.guidanceSession).toMatchObject({
      session_id: "guidance-1",
      revision: 7,
    });
    expect(result.current.state.currentSessionActions).toEqual([
      expect.objectContaining({ action: "stop_guidance" }),
    ]);
    expect(result.current.state.items[0]).toMatchObject({
      item_type: "proposal",
      proposal: { proposal_id: "proposal-1" },
    });
  });

  it("keeps durable Agent Document references in the restored timeline", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      items: [{
        item_type: "agent_document",
        document_id: "document-storyboard-1",
        document_kind: "storyboard_production_plan",
        revision: 2,
        content_digest: "sha256:storyboard-plan",
        title: "Storyboard production plan",
        sequence: 4,
        created_at: "2026-08-04T10:00:00Z",
      }],
      next_cursor: 4,
    }));
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.refresh();
    });

    expect(result.current.state.items).toEqual([
      expect.objectContaining({
        item_type: "agent_document",
        document_id: "document-storyboard-1",
        revision: 2,
      }),
    ]);
  });

  it("selects a proposal with the backend action descriptor and creates a draft only", async () => {
    const select = descriptor("select_option", "action-select-1");
    const reference = {
      source_kind: "image_asset" as const,
      source_id: "asset-1",
      binding_kind: "image_reference" as const,
      input_role: "visual_reference" as const,
      required: true,
      display_order: 0,
      display_name: "Hero reference",
      media_type: "image" as const,
    };
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.selectProposal(
        "proposal-1",
        select,
        "option-1",
        [reference],
      );
    });

    expect(api.actOnAgentCanvasProposal).toHaveBeenCalledWith(
      "workflow-1",
      "proposal-1",
      {
        action_id: "action-select-1",
        expected_session_revision: 7,
        action: "select_option",
        option_id: "option-1",
        accepted_references: [reference],
      },
      expect.stringContaining("proposal-select-option"),
    );
    expect(api.actOnAgentCanvasProposal.mock.calls[0]?.[2]).not.toHaveProperty("generation_action");
    expect(api.actOnAgentCanvasProposal.mock.calls[0]?.[2]).not.toHaveProperty("position");
    expect(api.actOnAgentCanvasProposal).toHaveBeenCalledTimes(1);
    expect(api.submitAgentCanvasChatMessage).not.toHaveBeenCalled();
  });

  it("revises options with the backend action id and expected session revision", async () => {
    const revise = descriptor("revise_options", "action-revise-1");
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.reviseProposal("proposal-1", revise, "Make it warmer.");
    });

    expect(api.actOnAgentCanvasProposal).toHaveBeenCalledWith(
      "workflow-1",
      "proposal-1",
      {
        action_id: "action-revise-1",
        expected_session_revision: 7,
        action: "revise_options",
        instruction: "Make it warmer.",
      },
      expect.stringContaining("proposal-revise-options"),
    );
  });

  it.each(["defer_topic", "exclude_element", "delegate_choice"] as const)(
    "applies the %s descriptor without turning its label into chat text",
    async (action) => {
      const proposalAction = descriptor(action);
      const { result } = renderHook(() => useAgentCanvasChat({
        workflow: workflow(),
        chatRevision: 0,
        chatEvents: [],
      }));

      await act(async () => {
        await result.current.actions.applyProposalAction("proposal-1", proposalAction);
      });

      expect(api.actOnAgentCanvasProposal).toHaveBeenCalledWith(
        "workflow-1",
        "proposal-1",
        {
          action_id: proposalAction.action_id,
          expected_session_revision: 7,
          action,
        },
        expect.stringContaining(`proposal-${action.replaceAll("_", "-")}`),
      );
      expect(api.submitAgentCanvasChatMessage).not.toHaveBeenCalled();
    },
  );

  it("reuses a superseded direction with the descriptor's stable option and session revision", async () => {
    const reuse = {
      ...descriptor("reuse_direction", "action-reuse-direction-1"),
      option_id: "option-superseded-1",
    };
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.applyProposalAction("proposal-1", reuse);
    });

    expect(api.actOnAgentCanvasProposal).toHaveBeenCalledWith(
      "workflow-1",
      "proposal-1",
      {
        action_id: "action-reuse-direction-1",
        expected_session_revision: 7,
        action: "reuse_direction",
        option_id: "option-superseded-1",
      },
      expect.stringContaining("proposal-reuse-direction"),
    );
    expect(api.submitAgentCanvasChatMessage).not.toHaveBeenCalled();
  });

  it("revises a superseded direction with its stable option identity", async () => {
    const revise = {
      ...descriptor("revise_direction", "action-revise-direction-1"),
      option_id: "option-superseded-1",
    };
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.reviseProposal(
        "proposal-1",
        revise,
        "Keep the same direction but simplify the setting.",
      );
    });

    expect(api.actOnAgentCanvasProposal).toHaveBeenCalledWith(
      "workflow-1",
      "proposal-1",
      {
        action_id: "action-revise-direction-1",
        expected_session_revision: 7,
        action: "revise_direction",
        option_id: "option-superseded-1",
        instruction: "Keep the same direction but simplify the setting.",
      },
      expect.stringContaining("proposal-revise-direction"),
    );
  });

  it("starts a new idempotent user attempt when retrying a failed specialist activity", async () => {
    api.submitAgentCanvasChatMessage.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: "message-retry-1",
      turn_id: "turn-retry-1",
      status: "queued",
      events_cursor: 8,
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.retrySpecialistActivity({
        item_type: "expert_activity",
        activity_id: "activity-failed-1",
        turn_id: "turn-failed-1",
        capability_id: "scene_design",
        capability_display_name: "Scene Designer",
        operation: "materialize_draft",
        status: "failed",
        sequence: 4,
        started_at: "2026-08-07T01:00:00Z",
        finished_at: "2026-08-07T01:07:00Z",
        message: "The request timed out.",
        error_code: "agent_deadline_exceeded",
        elapsed_ms: 420000,
        attempt_stage: "transport_retry",
        retryable: true,
        validation_paths: [],
        operation_policy_id: "agent.materialization.v1",
        suggested_actions: ["retry", "revise_request"],
        completion_mode: null,
        warning_code: null,
      });
    });

    expect(api.submitAgentCanvasChatMessage).toHaveBeenCalledWith(
      "workflow-1",
      expect.objectContaining({
        text: "Retry the failed Scene Designer materialize draft operation.",
      }),
      expect.stringContaining("expert-retry-activity-failed-1"),
    );
  });

  it("keeps a durable terminal specialist state when an older live event is still buffered", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      items: [{
        item_type: "expert_activity",
        activity_id: "activity-scene-1",
        turn_id: "turn-scene-1",
        capability_id: "scene_design",
        capability_display_name: "Scene Designer",
        operation: "materialize_draft",
        status: "completed",
        sequence: 12,
        started_at: "2026-08-07T01:00:00Z",
        finished_at: "2026-08-07T01:01:00Z",
        message: null,
        error_code: null,
        elapsed_ms: 60_000,
        attempt_stage: "initial",
        retryable: false,
        validation_paths: [],
        operation_policy_id: "agent.materialization.v1",
        suggested_actions: [],
        completion_mode: null,
        warning_code: null,
      }],
    }));
    const staleWorkingEvent: CanvasRuntimeEventV2 = {
      ...turnEvent("agent_turn_started", "turn-scene-1", 2),
      event_type: "expert_activity_started",
      payload: {
        activity_id: "activity-scene-1",
        capability_id: "scene_design",
        capability_display_name: "Scene Designer",
        operation: "materialize_draft",
      },
    };
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [staleWorkingEvent],
    }));

    await act(async () => {
      vi.advanceTimersByTime(80);
      await Promise.resolve();
    });

    expect(result.current.state.items).toEqual([
      expect.objectContaining({
        item_type: "expert_activity",
        activity_id: "activity-scene-1",
        status: "completed",
      }),
    ]);
  });

  it("preserves the proposal card and refreshes guidance after a revision conflict", async () => {
    api.actOnAgentCanvasProposal.mockRejectedValue({
      code: "guidance_revision_conflict",
      message: "The guidance session changed.",
    });
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline());
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.selectProposal(
        "proposal-1",
        descriptor("select_option"),
        "option-1",
        [],
      );
    });

    expect(result.current.state.proposalIssues["proposal-1"]).toBe(
      "guidance_revision_conflict: The guidance session changed.",
    );
    expect(result.current.state.notice).toContain("latest guidance state");
    expect(api.agentCanvasChatTimeline).toHaveBeenCalled();
  });

  it("applies stop and resume guidance by stable action id", async () => {
    api.applyAgentCanvasGuidedAction.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: null,
      turn_id: "turn-guidance-action",
      status: "queued",
      events_cursor: 5,
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));
    const stopAction: GuidanceSessionActionV2 = {
      action_id: "action-stop",
      logical_key: "guidance:stop:7",
      action: "stop_guidance",
      state: "pending",
      creating_turn_id: "turn-guidance-1",
      expected_session_revision: 7,
      label: "Stop guidance",
      workflow_id: "workflow-1",
      confirmation_required: false,
      reason: "Pause guided production.",
      authority: null,
    };

    await act(async () => {
      await result.current.actions.applyGuidedAction(stopAction);
    });

    expect(api.applyAgentCanvasGuidedAction).toHaveBeenCalledWith(
      "workflow-1",
      "action-stop",
      { confirmed: true },
      expect.stringContaining("guided-action"),
    );
  });

  it("resolves creative authority with the structured guided action contract", async () => {
    api.applyAgentCanvasGuidedAction.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: null,
      turn_id: "turn-authority-action",
      status: "queued",
      events_cursor: 6,
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));
    const authorityAction: GuidanceSessionActionV2 = {
      action_id: "action-authority-director",
      logical_key: "authority:director:8",
      action: "set_creative_authority",
      state: "pending",
      creating_turn_id: "turn-guidance-2",
      expected_session_revision: 8,
      label: "Take the lead",
      workflow_id: "workflow-1",
      confirmation_required: false,
      reason: "Let the Director choose the creative direction.",
      authority: "director",
    };

    await act(async () => {
      await result.current.actions.applyGuidedAction(authorityAction);
    });

    expect(api.applyAgentCanvasGuidedAction).toHaveBeenCalledWith(
      "workflow-1",
      "action-authority-director",
      {
        confirmed: true,
        action: "set_creative_authority",
        authority: "director",
        expected_session_revision: 8,
      },
      expect.stringContaining("guided-action"),
    );
  });

  it("preserves a submitted message when an asynchronous agent turn fails", async () => {
    api.submitAgentCanvasChatMessage.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: "message-1",
      turn_id: "turn-1",
      status: "queued",
      events_cursor: 4,
    });
    api.agentCanvasChatTurn.mockResolvedValue({
      turn_id: "turn-1",
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      status: "failed",
      turn_kind: "message",
      request: {},
      error_code: "agent_runtime_unavailable",
      error_message: "The configured agent runtime is unavailable.",
      creation_mode: null,
      guidance_session_revision: null,
      continuation: null,
      created_at: "2026-08-04T10:00:00Z",
      updated_at: "2026-08-04T10:00:01Z",
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.submit({
        text: "Create a calm product film.",
        mentionedNodeIds: [],
        mentionedImageAssetIds: [],
      });
      await Promise.resolve();
    });

    expect(result.current.state.error).toBe(
      "agent_runtime_unavailable: The configured agent runtime is unavailable.",
    );
    expect(result.current.state.failedDraft).toMatchObject({
      text: "Create a calm product film.",
      idempotencyKey: undefined,
    });
  });
});
