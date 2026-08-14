import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasChatViewTimelineV2,
  AgentCanvasWorkflowV2,
  CanvasRuntimeEventV2,
  GuidedSessionStateV2,
  GuidanceSessionActionV2,
  ProposalActionDescriptorV2,
} from "../../../types-v2.ts";

const api = vi.hoisted(() => ({
  agentCanvasChatTimeline: vi.fn(),
  agentCanvasCreativeSession: vi.fn(),
  agentCanvasChatTurn: vi.fn(),
  agentCanvasProposal: vi.fn(),
  agentCanvasDecisionBundle: vi.fn(),
  submitAgentCanvasChatMessage: vi.fn(),
  retryAgentCanvasChatTurn: vi.fn(),
  actOnAgentCanvasProposal: vi.fn(),
  actOnAgentCanvasDecisionBundle: vi.fn(),
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
    presentationItems: null,
    next_cursor: 0,
    ...overrides,
  };
}

function guidedSession(stageRevision = 4, revision = 8): GuidedSessionStateV2 {
  return {
    session_id: "guidance-1",
    workflow_id: "workflow-1",
    status: "active",
    response_locale: "und",
    goal: {
      requested_output: "video",
      delivery_scope: "generated_media",
      summary: "Create a product film.",
      explicit_constraints: {},
    },
    creative_authority: null,
    current_checkpoint: null,
    narrative_direction: null,
    element_decisions: [],
    current_topic_id: null,
    topics: [],
    active_proposal_id: null,
    active_style_skill_run_id: null,
    completion: {
      authoring: "not_ready",
      delivery: "not_ready",
      editing_preparation: "not_ready",
      editing_node_id: null,
      matching_node_ids: [],
      matching_asset_ids: [],
    },
    journey: {
      policy_version: "fixed_ad_production_v1",
      stage: "foundation_design",
      stage_status: "waiting_user",
      stage_revision: stageRevision,
      foundation_queue: [],
      foundation_cursor: null,
      active_action: null,
      suspended_action: null,
      transition_evidence: [],
    },
    revision,
    updated_at: "2026-08-10T00:00:00Z",
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
  eventType: "agent_turn_queued" | "agent_turn_waiting" | "agent_turn_started" | "agent_turn_completed" | "agent_turn_failed",
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
    api.agentCanvasCreativeSession.mockResolvedValue(null);
    api.agentCanvasDecisionBundle.mockResolvedValue(null);
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

  it("keeps the newer persisted journey when the timeline response is stale", async () => {
    const direct = guidedSession(6, 12);
    const staleTimelineSession = guidedSession(5, 11);
    api.agentCanvasCreativeSession.mockResolvedValue(direct);
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      guidanceSession: staleTimelineSession,
    }));

    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      vi.advanceTimersByTime(80);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.state.guidanceSession).toBe(direct);
  });

  it("uses the latest localized presentation item instead of raw or stale timeline rows", async () => {
    api.agentCanvasChatTimeline
      .mockResolvedValueOnce(emptyTimeline({
        items: [{
          item_type: "message",
          message_id: "entry-1",
          conversation_id: "conversation-1",
          speaker: "adcraft_video_agent",
          text: "Raw fallback content",
          linked_node_ids: [],
          script_node_id: null,
          proposal_id: null,
          sequence: 7,
          created_at: "2026-08-13T10:10:00Z",
        }],
        presentationItems: [{
          presentation_key: "planning:next-action-1",
          presentation_revision: 2,
          source_entry_ids: ["entry-1"],
          message_key: "planning_progress.next_action",
          message_args: {},
          response_locale: "zh-CN",
          item: {
            item_type: "message",
            message_id: "entry-1",
            conversation_id: "conversation-1",
            speaker: "adcraft_video_agent",
            text: "Planning the next creative action.",
            linked_node_ids: [],
            script_node_id: null,
            proposal_id: null,
            sequence: 7,
            created_at: "2026-08-13T10:10:00Z",
          },
        }],
      }))
      .mockResolvedValueOnce(emptyTimeline({
        items: [{
          item_type: "message",
          message_id: "entry-1",
          conversation_id: "conversation-1",
          speaker: "adcraft_video_agent",
          text: "Stale raw content",
          linked_node_ids: [],
          script_node_id: null,
          proposal_id: null,
          sequence: 7,
          created_at: "2026-08-13T10:10:00Z",
        }],
        presentationItems: [{
          presentation_key: "planning:next-action-1",
          presentation_revision: 1,
          source_entry_ids: ["entry-1"],
          message_key: "planning_progress.next_action",
          message_args: {},
          response_locale: "en-US",
          item: {
            item_type: "message",
            message_id: "entry-1",
            conversation_id: "conversation-1",
            speaker: "adcraft_video_agent",
            text: "Stale presentation content",
            linked_node_ids: [],
            script_node_id: null,
            proposal_id: null,
            sequence: 7,
            created_at: "2026-08-13T10:10:00Z",
          },
        }],
      }));

    const { result, rerender } = renderHook(
      ({ chatRevision }) => useAgentCanvasChat({
        workflow: workflow(),
        chatRevision,
        chatEvents: [],
      }),
      { initialProps: { chatRevision: 0 } },
    );

    await act(async () => {
      vi.advanceTimersByTime(80);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.state.items).toMatchObject([{
      item_type: "message",
      text: "正在规划下一项创作操作。",
    }]);

    rerender({ chatRevision: 1 });
    await act(async () => {
      vi.advanceTimersByTime(80);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.state.items).toMatchObject([{
      item_type: "message",
      text: "正在规划下一项创作操作。",
    }]);
  });

  it("uses backend content when a presentation message key or locale is unsupported", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      items: [],
      presentationItems: [{
        presentation_key: "entry:unknown-message",
        presentation_revision: 1,
        source_entry_ids: ["entry-unknown-message"],
        message_key: "future.message.key",
        message_args: { unsupported: true },
        response_locale: "fr-CA",
        item: {
          item_type: "message",
          message_id: "entry-unknown-message",
          conversation_id: "conversation-1",
          speaker: "adcraft_video_agent",
          text: "Backend fallback content",
          linked_node_ids: [],
          script_node_id: null,
          proposal_id: null,
          sequence: 8,
          created_at: "2026-08-13T10:11:00Z",
        },
      }],
    }));

    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      vi.advanceTimersByTime(80);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.state.items).toMatchObject([{
      item_type: "message",
      text: "Backend fallback content",
    }]);
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

    rerender({ chatEvents: [turnEvent("agent_turn_waiting", "turn-1", 2)] });
    expect(result.current.state.agentWorking).toBe(true);
    expect(result.current.state.retryableFailedTurn).toBeNull();

    await act(async () => {
      vi.advanceTimersByTime(300_000);
      await Promise.resolve();
    });
    expect(result.current.state.agentWorking).toBe(true);
    expect(result.current.state.retryableFailedTurn).toBeNull();

    rerender({
      chatEvents: [
        turnEvent("agent_turn_waiting"),
        turnEvent("agent_turn_completed", "turn-1", 2),
      ],
    });
    expect(result.current.state.agentWorking).toBe(false);
  });

  it("refreshes a provider-waiting turn without adding a duplicate chat message", async () => {
    api.agentCanvasChatTurn.mockResolvedValue({
      turn_id: "turn-waiting-1",
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      status: "running",
      turn_kind: "message",
      request: {},
      error_code: null,
      error_message: null,
      creation_mode: null,
      guidance_session_revision: null,
      continuation: null,
      retry_of_turn_id: null,
      retry_attempt_no: 0,
      replayed: false,
      retryable: false,
      operation_stage: "provider_waiting",
      operation_failure: null,
      created_at: "2026-08-12T00:00:00Z",
      updated_at: "2026-08-12T00:00:00Z",
    });
    const { result, rerender } = renderHook(
      ({ chatEvents }) => useAgentCanvasChat({
        workflow: workflow(),
        chatRevision: 0,
        chatEvents,
      }),
      { initialProps: { chatEvents: [] as CanvasRuntimeEventV2[] } },
    );

    api.agentCanvasChatTurn.mockClear();
    rerender({ chatEvents: [turnEvent("agent_turn_waiting", "turn-waiting-1")] });

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(api.agentCanvasChatTurn).toHaveBeenCalledWith("workflow-1", "turn-waiting-1");
    expect(result.current.state.agentWorking).toBe(true);
    expect(result.current.state.agentWaitingForModel).toBe(true);
    expect(result.current.state.items).toEqual([]);
    expect(result.current.state.retryableFailedTurn).toBeNull();
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
        journey: {
          policy_version: "fixed_ad_production_v1",
          stage: "foundation_design",
          stage_status: "waiting_user",
          stage_revision: 4,
          foundation_queue: [],
          foundation_cursor: null,
          active_action: null,
          suspended_action: null,
          transition_evidence: [],
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
      options: [{
        option_id: "option-1",
        title: "Hero",
        public_summary: "Editorial lead",
        key_decisions: ["Confident posture"],
      }],
      proposed_references: [],
      target_node_id: null,
      target_node_revision: null,
      proposal_purpose: null,
      availability: "open",
      application_count: 0,
      latest_application: null,
      materialization: null,
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

  it("hydrates and submits a decision bundle with its backend revision", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      items: [{
        item_type: "decision_bundle_pointer",
        bundle_id: "bundle-1",
        sequence: 4,
        created_at: "2026-08-10T00:00:00Z",
      }],
      next_cursor: 4,
    }));
    api.agentCanvasDecisionBundle.mockResolvedValue({
      bundle_id: "bundle-1",
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      source_turn_id: "turn-1",
      replacement_bundle_id: null,
      status: "open",
      revision: 4,
      title: "Creative decisions",
      introduction: "Choose a mood.",
      questions: [],
      answers: [],
      requirement_revision_no: null,
      created_at: "2026-08-10T00:00:00Z",
      updated_at: "2026-08-10T00:00:00Z",
      closed_at: null,
    });
    api.actOnAgentCanvasDecisionBundle.mockResolvedValue({
      workflow_id: "workflow-1",
      bundle_id: "bundle-1",
      status: "skipped",
      revision: 5,
      requirement_revision_no: 3,
      turn_id: "turn-bundle-1",
      events_cursor: 8,
      replayed: false,
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.refresh();
    });

    expect(result.current.state.items[0]).toMatchObject({
      item_type: "decision_bundle",
      decision_bundle: { bundle_id: "bundle-1", revision: 4 },
    });

    await act(async () => {
      await result.current.actions.actOnDecisionBundle("bundle-1", {
        action: "skip_bundle",
        expected_revision: 4,
      });
    });

    expect(api.actOnAgentCanvasDecisionBundle).toHaveBeenCalledWith(
      "workflow-1",
      "bundle-1",
      { action: "skip_bundle", expected_revision: 4 },
      expect.stringContaining("decision-bundle-skip_bundle"),
    );
    expect(api.submitAgentCanvasChatMessage).not.toHaveBeenCalled();
  });

  it("accepts a queued proposal materialization turn without assuming a synchronous node", async () => {
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
    expect(result.current.state.agentWorking).toBe(true);
  });

  it("refreshes the action turn when a proposal materialization event arrives", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline());
    const { rerender } = renderHook(({ chatEvents }) => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: chatEvents.length,
      chatEvents,
    }), { initialProps: { chatEvents: [] as CanvasRuntimeEventV2[] } });
    const event: CanvasRuntimeEventV2 = {
      ...turnEvent("agent_turn_started", "turn-materialization-1", 8),
      event_type: "proposal_materialization_started",
      payload: {
        proposal_id: "proposal-1",
        materialization_id: "materialization-1",
        option_id: "option-1",
      },
    };

    rerender({ chatEvents: [event] });
    await act(async () => {
      vi.advanceTimersByTime(80);
      await Promise.resolve();
    });

    expect(api.agentCanvasChatTurn).toHaveBeenCalledWith("workflow-1", "turn-materialization-1");
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

  it("retries an accepted failed turn without creating a duplicate user message", async () => {
    api.retryAgentCanvasChatTurn.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      turn_id: "turn-retry-1",
      status: "queued",
      events_cursor: 8,
      retry_of_turn_id: "turn-failed-1",
      retry_attempt_no: 2,
      replayed: false,
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.retryCapabilityActivity({
        item_type: "expert_activity",
        activity_id: "activity-failed-1",
        turn_id: "turn-failed-1",
        capability_id: "scene_design",
        capability_display_name: "Scene Designer",
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
        suggested_actions: ["retry", "revise_request"],
        completion_mode: null,
        warning_code: null,
      });
    });

    expect(api.retryAgentCanvasChatTurn).toHaveBeenCalledWith(
      "workflow-1",
      "turn-failed-1",
      {
        expected_session_revision: 0,
        expected_workflow_revision: 1,
      },
      expect.stringContaining("chat-turn-retry-turn-failed-1"),
    );
    expect(api.submitAgentCanvasChatMessage).not.toHaveBeenCalled();
  });

  it("refreshes the canonical workflow and session after a stale turn retry", async () => {
    api.retryAgentCanvasChatTurn.mockRejectedValue({
      code: "chat_turn_retry_stale",
      message: "The failed turn snapshot is stale.",
    });
    const onWorkflowRefresh = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
      onWorkflowRefresh,
    }));

    await act(async () => {
      await result.current.actions.retryCapabilityActivity({
        item_type: "expert_activity",
        activity_id: "activity-failed-2",
        turn_id: "turn-failed-2",
        capability_id: "scene_design",
        capability_display_name: "Scene Designer",
        status: "failed",
        sequence: 5,
        started_at: "2026-08-07T01:00:00Z",
        finished_at: "2026-08-07T01:07:00Z",
        message: "The request timed out.",
        error_code: "agent_deadline_exceeded",
        elapsed_ms: 420000,
        attempt_stage: "transport_retry",
        retryable: true,
        validation_paths: [],
        suggested_actions: ["retry"],
        completion_mode: null,
        warning_code: null,
      });
    });

    expect(onWorkflowRefresh).toHaveBeenCalledOnce();
    expect(result.current.state.notice).toContain("latest state");
  });

  it("restores an in-progress retry relationship from persisted capability turns", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      items: [
        {
          item_type: "expert_activity",
          activity_id: "activity-original",
          turn_id: "turn-original",
          capability_id: "scene_design",
          capability_display_name: "Scene Designer",
          status: "failed",
          sequence: 1,
          started_at: "2026-08-11T10:00:00Z",
          finished_at: "2026-08-11T10:00:03Z",
          message: "The provider timed out.",
          error_code: "agent_deadline_exceeded",
          elapsed_ms: 3000,
          attempt_stage: "initial",
          retryable: true,
          validation_paths: [],
          suggested_actions: ["retry"],
          completion_mode: null,
          warning_code: null,
        },
        {
          item_type: "expert_activity",
          activity_id: "activity-retry",
          turn_id: "turn-retry",
          capability_id: "scene_design",
          capability_display_name: "Scene Designer",
          status: "working",
          sequence: 2,
          started_at: "2026-08-11T10:01:00Z",
          finished_at: null,
          message: null,
          error_code: null,
          elapsed_ms: null,
          attempt_stage: "transport_retry",
          retryable: false,
          validation_paths: [],
          suggested_actions: [],
          completion_mode: null,
          warning_code: null,
        },
      ],
    }));
    api.agentCanvasChatTurn.mockImplementation((_workflowId: string, turnId: string) => Promise.resolve({
      turn_id: turnId,
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      status: turnId === "turn-retry" ? "running" : "failed",
      turn_kind: "capability",
      request: {},
      error_code: turnId === "turn-retry" ? null : "agent_deadline_exceeded",
      error_message: turnId === "turn-retry" ? null : "The provider timed out.",
      creation_mode: null,
      guidance_session_revision: 8,
      continuation: null,
      retry_of_turn_id: turnId === "turn-retry" ? "turn-original" : null,
      retry_attempt_no: turnId === "turn-retry" ? 2 : 1,
      retryable: turnId !== "turn-retry",
      operation_stage: turnId === "turn-retry" ? "validating" : "failed",
      operation_failure: null,
      created_at: "2026-08-11T10:00:00Z",
      updated_at: "2026-08-11T10:01:00Z",
    }));
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      vi.advanceTimersByTime(80);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.state.retryingSourceTurnIds).toEqual({
      "turn-original": "turn-retry",
    });
    expect(result.current.state.turnsById["turn-retry"]?.operation_stage).toBe("validating");
  });

  it("keeps a durable terminal capability state when an older live event is still buffered", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      items: [{
        item_type: "expert_activity",
        activity_id: "activity-scene-1",
        turn_id: "turn-scene-1",
        capability_id: "scene_design",
        capability_display_name: "Scene Designer",
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

  it("offers Turn Retry instead of raw message resubmission after an accepted turn fails", async () => {
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
      retry_of_turn_id: null,
      retry_attempt_no: 1,
      retryable: true,
      operation_stage: "failed",
      operation_failure: {
        code: "agent_runtime_unavailable",
        message: "The configured agent runtime is unavailable.",
        operation: "director_message",
        capability_id: null,
        attempt_stage: "initial",
        failure_stage: "provider",
        elapsed_ms: 1000,
        retryable: true,
        validation_paths: [],
        occurred_at: "2026-08-04T10:00:01Z",
      },
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
    expect(result.current.state.failedDraft).toBeNull();
    expect(result.current.state.retryableFailedTurn?.turn_id).toBe("turn-1");
  });
});
