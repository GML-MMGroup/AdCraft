import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasChatViewTimelineV2,
  AgentCanvasWorkflowV2,
  CanvasRuntimeEventV2,
  GuidedSessionStateV2,
  GuidedInteractionV1,
  GuidanceSessionActionV2,
  ProposalActionDescriptorV2,
} from "../../../types-v2.ts";

const api = vi.hoisted(() => ({
  agentCanvasChatTimeline: vi.fn(),
  agentCanvasCreativeSession: vi.fn(),
  agentCanvasChatTurn: vi.fn(),
  agentCanvasProposal: vi.fn(),
  agentCanvasDecisionBundle: vi.fn(),
  advanceAgentCanvasGuidance: vi.fn(),
  agentCanvasPostReadyCheckpoint: vi.fn(),
  submitAgentCanvasChatMessage: vi.fn(),
  retryAgentCanvasChatTurn: vi.fn(),
  actOnAgentCanvasProposal: vi.fn(),
  actOnAgentCanvasDecisionBundle: vi.fn(),
  actOnAgentCanvasCommandPlan: vi.fn(),
  applyAgentCanvasGuidedAction: vi.fn(),
  submitAgentCanvasGuidedInteraction: vi.fn(),
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
    guidanceAdvancePrecondition: null,
    continuations: [],
    current_session_actions: [],
    items: [],
    presentationItems: null,
    next_cursor: 0,
    ...overrides,
  };
}

function guidanceAdvancePrecondition(authorityDigest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
  return {
    schema_version: "1",
    workflow_id: "workflow-1",
    workflow_revision: 9,
    session_id: "guidance-1",
    session_revision: 8,
    session_status: "active",
    journey_stage: "scene",
    journey_stage_status: "working",
    journey_stage_revision: 4,
    source_id: "stage:scene:4",
    requirement_revision_id: "requirement-1",
    requirement_digest: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    active_action_digest: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    owner_state_digest: "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    authority_digest: authorityDigest,
  };
}

function timelineWithGuidanceAdvance(
  authorityDigest?: string,
): AgentCanvasChatViewTimelineV2 {
  return {
    ...emptyTimeline({ guidanceSession: guidedSession() }),
    guidanceAdvancePrecondition: guidanceAdvancePrecondition(authorityDigest),
  };
}

function postReadyCheckpoint(status: "pending" | "completed" | "failed") {
  return {
    checkpoint_id: "checkpoint-1",
    workflow_id: "workflow-1",
    execution_id: "execution-1",
    execution_status: status === "completed" ? "completed" : "waiting",
    status,
    counts: {
      total: 1,
      queued: 0,
      running: status === "pending" ? 1 : 0,
      completed: status === "completed" ? 1 : 0,
      failed: status === "failed" ? 1 : 0,
    },
    effects: [],
    error: status === "failed"
      ? { code: "post_ready_progression_failed", message: "Script persistence failed.", retryable: false }
      : null,
    updated_at: "2026-08-17T10:00:00Z",
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
      policy_version: "fixed_ad_production_v2",
      stage: "scene",
      stage_status: "waiting_user",
      stage_revision: stageRevision,
      decisions: [],
      active_occurrence_id: null,
      active_action: null,
      suspended_action: null,
      transition_evidence: [],
    },
    revision,
    updated_at: "2026-08-10T00:00:00Z",
  };
}

function guidedQuestionnaireInteraction(): GuidedInteractionV1 {
  return {
    interaction_id: "interaction-duration-1",
    workflow_id: "workflow-1",
    session_id: "guidance-1",
    checkpoint_id: "checkpoint-duration-1",
    kind: "clarification_questionnaire",
    status: "open",
    response_locale: "en-US",
    expected_session_revision: 8,
    revision: 3,
    title: "Set duration",
    context: "Choose a target duration.",
    content: {
      content_kind: "questionnaire",
      questions: [{
        question_id: "production_duration_seconds",
        prompt: "How long should the ad be?",
        input_kind: "single_select",
        options: [{
          option_id: "duration_seconds_30",
          title: "30 seconds",
          summary: "Balanced.",
          difference_tags: [],
          recommended: true,
          reference_preview: [],
        }],
        allow_custom: true,
        allow_skip: false,
        required: true,
      }],
    },
    allowed_actions: ["answer"],
    submit_path: "/api/v2/workflows/workflow-1/chat/interactions/interaction-duration-1/submit",
    created_at: "2026-08-23T10:00:00Z",
    updated_at: "2026-08-23T10:00:00Z",
  };
}

function guidedConceptInteraction(): GuidedInteractionV1 {
  return {
    interaction_id: "interaction-concept-1",
    workflow_id: "workflow-1",
    session_id: "guidance-1",
    checkpoint_id: "checkpoint-concept-1",
    kind: "concept_choice",
    status: "open",
    response_locale: "en-US",
    expected_session_revision: 8,
    revision: 3,
    title: "Choose a scene direction",
    context: "Select one direction to create the Draft.",
    content: {
      content_kind: "concept_choice",
      proposal_id: "proposal-1",
      stage: "scene",
      stage_revision: 4,
      action_id: "action-select-1",
      occurrence_id: "scene-1",
      capability_id: "scene_design",
      options: [{
        option_id: "option-1",
        title: "Morning forest",
        summary: "Soft light through the trees.",
        difference_tags: [],
        recommended: true,
        reference_preview: [],
      }],
      allow_custom: true,
      allow_exclusion: true,
    },
    allowed_actions: ["select", "custom", "defer", "exclude", "delegate"],
    submit_path: "/api/v2/workflows/workflow-1/chat/interactions/interaction-concept-1/submit",
    created_at: "2026-08-24T10:00:00Z",
    updated_at: "2026-08-24T10:00:00Z",
  };
}

function guidedProductInteraction(): GuidedInteractionV1 {
  return {
    interaction_id: "interaction-product-main-1",
    workflow_id: "workflow-1",
    session_id: "guidance-1",
    checkpoint_id: "checkpoint-product-main-1",
    kind: "product_source",
    status: "open",
    response_locale: "en-US",
    expected_session_revision: 8,
    revision: 3,
    title: "Choose a Product source",
    context: "Upload the main Product image or ask the Agent to generate it.",
    content: {
      content_kind: "product_source",
      input_kind: "main",
      question_id: "product_main_source",
      prompt: "Choose the main Product source.",
      expected_guidance_revision: 8,
      min_asset_count: 1,
      max_asset_count: 1,
    },
    allowed_actions: ["select_source"],
    submit_path: "/api/v2/workflows/workflow-1/chat/interactions/interaction-product-main-1/submit",
    created_at: "2026-08-27T10:00:00Z",
    updated_at: "2026-08-27T10:00:00Z",
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
    api.advanceAgentCanvasGuidance.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: null,
      turn_id: "turn-guidance-advance",
      status: "queued",
      events_cursor: 2,
      retry_of_turn_id: null,
      retry_attempt_no: 1,
      replayed: false,
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

  it("routes timeline refresh failures to the Timeline recovery owner", async () => {
    api.agentCanvasChatTimeline.mockRejectedValue(new Error(
      "Invalid chatTimeline.presentation_items[0]",
    ));
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.refresh();
    });

    expect(result.current.state.timelineRecovery).toMatchObject({
      scope: "timeline",
      title: "Conversation could not be refreshed",
      technicalDetail: "Invalid chatTimeline.presentation_items[0]",
      action: "refresh",
    });
    expect(result.current.state.composerRecovery).toBeNull();
    expect(result.current.state.workflowRecovery).toBeNull();
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

  it("advances only with the complete authority snapshot supplied by Timeline", async () => {
    const precondition = guidanceAdvancePrecondition();
    api.agentCanvasChatTimeline.mockResolvedValue(timelineWithGuidanceAdvance());

    renderHook(() => useAgentCanvasChat({
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

    expect(api.advanceAgentCanvasGuidance).toHaveBeenCalledWith(
      "workflow-1",
      { precondition },
      expect.stringContaining(precondition.authority_digest),
    );
    expect(api.submitAgentCanvasChatMessage).not.toHaveBeenCalled();
    expect(api.retryAgentCanvasChatTurn).not.toHaveBeenCalled();
  });

  it("does not synthesize a Guidance Advance when Timeline reports no authority snapshot", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      guidanceSession: guidedSession(),
      guidanceAdvancePrecondition: null,
    }));

    renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      vi.advanceTimersByTime(80);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.advanceAgentCanvasGuidance).not.toHaveBeenCalled();
    expect(api.submitAgentCanvasChatMessage).not.toHaveBeenCalled();
    expect(api.retryAgentCanvasChatTurn).not.toHaveBeenCalled();
  });

  it.each(["media_review", "manual_node_run"] as const)(
    "does not Advance while typed awaiting is %s",
    async (kind) => {
      api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
        guidanceSession: {
          ...guidedSession(),
          interaction: null,
          awaiting: {
            awaiting_id: `awaiting-${kind}`,
            workflow_id: "workflow-1",
            session_id: "guidance-1",
            checkpoint_id: "checkpoint-1",
            kind,
            requires_user_action: kind === "media_review",
            resume_policy: kind === "media_review" ? "submit_interaction" : "node_terminal",
            interaction_id: kind === "media_review" ? "interaction-1" : null,
            node_ids: ["node-1"],
            stage: "videos",
            stage_revision: 6,
            created_at: "2026-08-20T00:00:00Z",
          },
        },
        guidanceAdvancePrecondition: guidanceAdvancePrecondition(),
      }));

      renderHook(() => useAgentCanvasChat({
        workflow: workflow(),
        chatRevision: 0,
        chatEvents: [],
      }));

      await act(async () => {
        vi.advanceTimersByTime(80);
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(api.advanceAgentCanvasGuidance).not.toHaveBeenCalled();
    },
  );

  it("does not Advance while a Product source interaction is awaiting submission", async () => {
    const interaction = guidedProductInteraction();
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      guidanceSession: {
        ...guidedSession(),
        interaction,
        awaiting: {
          awaiting_id: "awaiting-product-source-1",
          workflow_id: "workflow-1",
          session_id: "guidance-1",
          checkpoint_id: interaction.checkpoint_id,
          kind: "product_source",
          requires_user_action: true,
          resume_policy: "submit_interaction",
          interaction_id: interaction.interaction_id,
          node_ids: [],
          stage: "product",
          stage_revision: 8,
          created_at: "2026-08-27T10:00:00Z",
        },
      },
      guidanceAdvancePrecondition: guidanceAdvancePrecondition(),
    }));

    renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(80);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.advanceAgentCanvasGuidance).not.toHaveBeenCalled();
  });

  it("waits for post-ready completion then retries the exact same guidance command once", async () => {
    const precondition = guidanceAdvancePrecondition();
    api.agentCanvasChatTimeline.mockResolvedValue(timelineWithGuidanceAdvance());
    api.advanceAgentCanvasGuidance
      .mockRejectedValueOnce({
        code: "guidance_post_ready_pending",
        message: "Document persistence is still running.",
        status: 409,
        details: {
          checkpoint_id: "checkpoint-1",
          execution_id: "execution-1",
          retry_after_seconds: 1,
        },
      })
      .mockResolvedValueOnce({
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        message_id: null,
        turn_id: "turn-guidance-accepted",
        status: "queued",
        events_cursor: 3,
        retry_of_turn_id: null,
        retry_attempt_no: 1,
        replayed: false,
      });
    api.agentCanvasPostReadyCheckpoint
      .mockResolvedValueOnce(postReadyCheckpoint("pending"))
      .mockResolvedValueOnce(postReadyCheckpoint("completed"));

    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(80);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.advanceAgentCanvasGuidance).toHaveBeenCalledTimes(1);
    expect(api.agentCanvasPostReadyCheckpoint).toHaveBeenCalledWith("workflow-1", "execution-1");
    expect(result.current.state.agentWorking).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.agentCanvasPostReadyCheckpoint).toHaveBeenCalledTimes(2);
    expect(api.advanceAgentCanvasGuidance).toHaveBeenCalledTimes(2);
    expect(api.advanceAgentCanvasGuidance).toHaveBeenNthCalledWith(
      1,
      "workflow-1",
      { precondition },
      expect.any(String),
    );
    expect(api.advanceAgentCanvasGuidance).toHaveBeenNthCalledWith(
      2,
      "workflow-1",
      { precondition },
      api.advanceAgentCanvasGuidance.mock.calls[0]?.[2],
    );
    expect(api.submitAgentCanvasChatMessage).not.toHaveBeenCalled();
  });

  it("does not replay a completed post-ready Advance after typed media review becomes authoritative", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue(timelineWithGuidanceAdvance());
    api.advanceAgentCanvasGuidance.mockRejectedValueOnce({
      code: "guidance_post_ready_pending",
      message: "Document persistence is still running.",
      status: 409,
      details: {
        checkpoint_id: "checkpoint-1",
        execution_id: "execution-1",
        retry_after_seconds: 1,
      },
    });
    api.agentCanvasPostReadyCheckpoint
      .mockResolvedValueOnce(postReadyCheckpoint("pending"))
      .mockResolvedValueOnce(postReadyCheckpoint("completed"));

    const { rerender } = renderHook(
      ({ chatRevision }) => useAgentCanvasChat({
        workflow: workflow(),
        chatRevision,
        chatEvents: [],
      }),
      { initialProps: { chatRevision: 0 } },
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(80);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(api.advanceAgentCanvasGuidance).toHaveBeenCalledTimes(1);

    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      guidanceSession: {
        ...guidedSession(),
        awaiting: {
          awaiting_id: "awaiting-media-review",
          workflow_id: "workflow-1",
          session_id: "guidance-1",
          checkpoint_id: "checkpoint-media-review",
          kind: "media_review",
          requires_user_action: true,
          resume_policy: "submit_interaction",
          interaction_id: "interaction-media-review",
          node_ids: ["node-video-1"],
          stage: "videos",
          stage_revision: 6,
          created_at: "2026-08-20T00:00:00Z",
        },
      },
      guidanceAdvancePrecondition: null,
    }));
    rerender({ chatRevision: 1 });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(80);
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.agentCanvasPostReadyCheckpoint).toHaveBeenCalledTimes(2);
    expect(api.advanceAgentCanvasGuidance).toHaveBeenCalledTimes(1);
  });

  it("keeps the guidance checkpoint visible and does not retry when post-ready work fails", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue(timelineWithGuidanceAdvance());
    api.advanceAgentCanvasGuidance.mockRejectedValueOnce({
      code: "guidance_post_ready_pending",
      message: "Document persistence is still running.",
      status: 409,
      details: { checkpoint_id: "checkpoint-1", execution_id: "execution-1", retry_after_seconds: 1 },
    });
    api.agentCanvasPostReadyCheckpoint.mockResolvedValueOnce(postReadyCheckpoint("failed"));

    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(80);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.advanceAgentCanvasGuidance).toHaveBeenCalledTimes(1);
    expect(result.current.state.workflowRecovery).toMatchObject({
      scope: "workflow",
      technicalDetail: "post_ready_progression_failed: Script persistence failed.",
      action: "refresh",
    });
    expect(result.current.state.agentWorking).toBe(false);
  });

  it("refreshes one stale snapshot and submits only one changed replacement", async () => {
    const first = guidanceAdvancePrecondition(
      "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    );
    const replacement = guidanceAdvancePrecondition(
      "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    );
    api.agentCanvasChatTimeline
      .mockResolvedValueOnce(timelineWithGuidanceAdvance(first.authority_digest))
      .mockResolvedValue(timelineWithGuidanceAdvance(replacement.authority_digest));
    api.advanceAgentCanvasGuidance
      .mockRejectedValueOnce({
        code: "guidance_advance_stale",
        message: "The authoritative guidance state changed.",
        status: 409,
        details: { refresh_required: true, stale_components: ["workflow"] },
      })
      .mockResolvedValueOnce({
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        message_id: null,
        turn_id: "turn-guidance-rebased",
        status: "queued",
        events_cursor: 3,
        retry_of_turn_id: null,
        retry_attempt_no: 1,
        replayed: false,
      });

    renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      vi.advanceTimersByTime(80);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.advanceAgentCanvasGuidance).toHaveBeenCalledTimes(2);
    expect(api.advanceAgentCanvasGuidance).toHaveBeenNthCalledWith(
      1,
      "workflow-1",
      { precondition: first },
      expect.stringContaining(first.authority_digest),
    );
    expect(api.advanceAgentCanvasGuidance).toHaveBeenNthCalledWith(
      2,
      "workflow-1",
      { precondition: replacement },
      expect.stringContaining(replacement.authority_digest),
    );
    expect(api.submitAgentCanvasChatMessage).not.toHaveBeenCalled();
    expect(api.retryAgentCanvasChatTurn).not.toHaveBeenCalled();
  });

  it("stops after a second stale snapshot without a third advance request", async () => {
    const first = guidanceAdvancePrecondition(
      "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    );
    const replacement = guidanceAdvancePrecondition(
      "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    );
    api.agentCanvasChatTimeline
      .mockResolvedValueOnce(timelineWithGuidanceAdvance(first.authority_digest))
      .mockResolvedValue(timelineWithGuidanceAdvance(replacement.authority_digest));
    api.advanceAgentCanvasGuidance
      .mockRejectedValueOnce({ code: "guidance_advance_stale", message: "stale", status: 409, details: {} })
      .mockRejectedValueOnce({ code: "guidance_advance_stale", message: "still stale", status: 409, details: {} });

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
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.advanceAgentCanvasGuidance).toHaveBeenCalledTimes(2);
    expect(result.current.state.workflowRecovery).toMatchObject({
      title: "Conversation state changed",
      action: "review",
    });
    expect(result.current.state.workflowRecovery?.technicalDetail).toContain("guidance_advance_stale");
    expect(result.current.state.workflowRecovery?.technicalDetail).toContain("still stale");
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

  it("shows Timeline before proposal hydration and loads Creative Session in parallel", async () => {
    let resolveProposal!: (value: ConceptProposalV2) => void;
    let resolveSession!: (value: GuidedSessionStateV2) => void;
    api.agentCanvasProposal.mockImplementation(() => new Promise((resolve) => {
      resolveProposal = resolve;
    }));
    api.agentCanvasCreativeSession.mockImplementation(() => new Promise((resolve) => {
      resolveSession = resolve;
    }));
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      items: [
        {
          item_type: "message",
          message_id: "message-first-paint",
          conversation_id: "conversation-1",
          speaker: "adcraft_video_agent",
          text: "The creative plan is being prepared.",
          linked_node_ids: [],
          script_node_id: null,
          proposal_id: null,
          sequence: 1,
          created_at: "2026-08-27T10:00:00Z",
        },
        {
          item_type: "proposal_pointer",
          proposal_id: "proposal-late-hydration",
          sequence: 2,
          created_at: "2026-08-27T10:00:01Z",
        },
      ],
      next_cursor: 2,
    }));
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.refresh();
    });

    expect(api.agentCanvasCreativeSession).toHaveBeenCalledOnce();
    expect(result.current.state.loading).toBe(false);
    expect(result.current.state.items).toMatchObject([
      { item_type: "message", message_id: "message-first-paint" },
      { item_type: "proposal_pointer", proposal_id: "proposal-late-hydration" },
    ]);

    resolveProposal({ proposal_id: "proposal-late-hydration" } as ConceptProposalV2);
    resolveSession(guidedSession(5, 9));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.state.items).toMatchObject([
      { item_type: "message", message_id: "message-first-paint" },
      { item_type: "proposal", proposal: { proposal_id: "proposal-late-hydration" } },
    ]);
    expect(result.current.state.guidanceSession).toMatchObject({ revision: 9 });
  });

  it("refreshes Timeline, Session, Graph, and Runtime in order after a typed submit", async () => {
    const order: string[] = [];
    api.agentCanvasChatTimeline.mockImplementation(async () => {
      order.push("timeline");
      return emptyTimeline();
    });
    api.agentCanvasCreativeSession.mockImplementation(async () => {
      order.push("session");
      return null;
    });
    api.submitAgentCanvasGuidedInteraction.mockImplementation(async () => {
      order.push("submit");
      return {
        workflow_id: "workflow-1",
        interaction_id: "interaction-review-1",
        submission_id: "submission-review-1",
        receipt_id: "receipt-review-1",
        created_node_ids: ["node-video-1"],
        created_binding_ids: [],
        document_revisions: {},
        continuation_id: "continuation-review-1",
        automatic_run_command_ids: [],
        resulting_session_revision: 9,
        events_cursor: 21,
        replayed: false,
      };
    });
    const onWorkflowRefresh = vi.fn(async () => { order.push("graph"); });
    const onRuntimeRefresh = vi.fn(async () => { order.push("runtime"); });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
      onWorkflowRefresh,
      onRuntimeRefresh,
    }));

    await act(async () => {
      vi.advanceTimersByTime(80);
      await Promise.resolve();
      await Promise.resolve();
    });
    order.length = 0;
    api.agentCanvasChatTimeline.mockClear();
    api.agentCanvasCreativeSession.mockClear();

    await act(async () => {
      await result.current.actions.submitGuidedInteraction({
        interaction_id: "interaction-review-1",
        workflow_id: "workflow-1",
        session_id: "guidance-1",
        checkpoint_id: "checkpoint-review-1",
        kind: "media_review",
        status: "open",
        response_locale: "en-US",
        expected_session_revision: 8,
        revision: 3,
        title: "Review Storyboard Grid 1",
        context: "Choose how to continue.",
        content: {
          content_kind: "media_review",
          node_id: "node-storyboard-1",
          node_revision: 4,
          asset_id: "asset-grid-1",
          asset_version_id: "version-grid-1",
          summary: "Review the generated grid.",
        },
        allowed_actions: ["accept", "retry", "replace"],
        submit_path: "/api/v2/workflows/workflow-1/chat/interactions/interaction-review-1/submit",
        created_at: "2026-08-20T10:00:00Z",
        updated_at: "2026-08-20T10:00:00Z",
      }, {
        submission_kind: "media_review",
        expected_interaction_revision: 3,
        expected_session_revision: 8,
        action: "accept",
        instruction: null,
      });
    });

    expect(order[0]).toBe("submit");
    expect(new Set(order.slice(1, 3))).toEqual(new Set(["timeline", "session"]));
    expect(order.slice(3)).toEqual(["graph", "runtime"]);
    expect(api.advanceAgentCanvasGuidance).not.toHaveBeenCalled();
  });

  it("keeps a guided choice pending until the authoritative interaction closes", async () => {
    const interaction = guidedConceptInteraction();
    const openSession = {
      ...guidedSession(),
      interaction,
      awaiting: null,
    };
    const submittedSession = {
      ...guidedSession(4, 9),
      interaction: { ...interaction, status: "submitted" as const },
      awaiting: null,
    };
    const closedSession = {
      ...guidedSession(5, 9),
      interaction: null,
      awaiting: null,
    };
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      guidanceSession: openSession,
    }));
    api.agentCanvasCreativeSession.mockResolvedValue(openSession);
    api.submitAgentCanvasGuidedInteraction.mockResolvedValue({
      workflow_id: "workflow-1",
      interaction_id: interaction.interaction_id,
      submission_id: "submission-concept-1",
      receipt_id: "receipt-concept-1",
      created_node_ids: [],
      created_binding_ids: [],
      document_revisions: {},
      continuation_id: "continuation-concept-1",
      automatic_run_command_ids: [],
      resulting_session_revision: 9,
      events_cursor: 21,
      replayed: false,
    });
    const { result, rerender } = renderHook(
      ({ chatRevision, chatEvents }) => useAgentCanvasChat({
        workflow: workflow(),
        chatRevision,
        chatEvents,
      }),
      { initialProps: { chatRevision: 0, chatEvents: [] as CanvasRuntimeEventV2[] } },
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(80);
    });
    await act(async () => {
      await result.current.actions.submitGuidedInteraction(interaction, {
        submission_kind: "concept_choice",
        expected_interaction_revision: interaction.revision,
        expected_session_revision: interaction.expected_session_revision,
        action: "select",
        option_id: "option-1",
        custom_text: null,
        accepted_references: [],
      });
    });

    expect(result.current.state.actingInteractionId).toBe(interaction.interaction_id);

    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      guidanceSession: submittedSession,
    }));
    api.agentCanvasCreativeSession.mockResolvedValue(submittedSession);
    rerender({ chatRevision: 1, chatEvents: [] });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(80);
      await Promise.resolve();
    });

    expect(result.current.state.guidedInteraction?.status).toBe("submitted");
    expect(result.current.state.actingInteractionId).toBe(interaction.interaction_id);

    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      guidanceSession: closedSession,
    }));
    api.agentCanvasCreativeSession.mockResolvedValue(closedSession);
    const completedEvent: CanvasRuntimeEventV2 = {
      ...turnEvent("agent_turn_completed", "turn-materialization-1", 22),
      event_type: "proposal_materialization_completed",
      action_id: interaction.interaction_id,
      payload: {
        proposal_id: "proposal-1",
        materialization_id: "materialization-1",
        option_id: "option-1",
        turn_id: "turn-materialization-1",
        node_ids: ["node-scene-1"],
        binding_ids: [],
      },
    };
    rerender({ chatRevision: 2, chatEvents: [completedEvent] });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(80);
      await Promise.resolve();
    });

    expect(result.current.state.guidedInteraction).toBeNull();
    expect(result.current.state.actingInteractionId).toBeNull();
  });

  it("adds structured questionnaire answers as local bubbles before later timeline content", async () => {
    const interaction = guidedQuestionnaireInteraction();
    const openSession = { ...guidedSession(), interaction, awaiting: null };
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      guidanceSession: openSession,
      items: [{
        item_type: "message",
        message_id: "message-follow-up",
        conversation_id: "conversation-1",
        speaker: "adcraft_video_agent",
        text: "The next production step is ready.",
        linked_node_ids: [],
        script_node_id: null,
        proposal_id: null,
        capability_id: null,
        sequence: 4,
        created_at: "2026-08-29T00:00:04Z",
      }],
    }));
    api.agentCanvasCreativeSession.mockResolvedValue(openSession);
    api.submitAgentCanvasGuidedInteraction.mockResolvedValue({
      workflow_id: "workflow-1",
      interaction_id: interaction.interaction_id,
      submission_id: "submission-duration-1",
      receipt_id: "receipt-duration-1",
      created_node_ids: [],
      created_binding_ids: [],
      document_revisions: {},
      continuation_id: null,
      automatic_run_command_ids: [],
      resulting_session_revision: 9,
      events_cursor: 5,
      replayed: false,
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(80);
    });
    await act(async () => {
      await result.current.actions.submitGuidedInteraction(interaction, {
        submission_kind: "questionnaire",
        expected_interaction_revision: interaction.revision,
        expected_session_revision: interaction.expected_session_revision,
        answers: [{
          answer_kind: "option",
          question_id: "production_duration_seconds",
          option_id: "duration_seconds_30",
        }],
      });
    });

    expect(result.current.state.guidedAnswerBubbles).toEqual([{
      bubble_id: "guided-answer:interaction-duration-1:production_duration_seconds",
      interaction_id: "interaction-duration-1",
      question_id: "production_duration_seconds",
      label: "How long should the ad be?",
      value: "30 seconds",
      sequence: 4.01,
    }]);
    expect(result.current.state.items[0]?.sequence).toBe(4);
  });

  it("removes a local guided answer bubble when the structured submission fails", async () => {
    const interaction = guidedQuestionnaireInteraction();
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      items: [{
        item_type: "message",
        message_id: "message-before-failure",
        conversation_id: "conversation-1",
        speaker: "adcraft_video_agent",
        text: "Choose a duration.",
        linked_node_ids: [],
        script_node_id: null,
        proposal_id: null,
        capability_id: null,
        sequence: 2,
        created_at: "2026-08-29T00:00:02Z",
      }],
    }));
    api.submitAgentCanvasGuidedInteraction.mockRejectedValue({
      status: 409,
      code: "guided_interaction_stale",
      message: "The interaction is no longer current.",
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(80);
      await result.current.actions.submitGuidedInteraction(interaction, {
        submission_kind: "questionnaire",
        expected_interaction_revision: interaction.revision,
        expected_session_revision: interaction.expected_session_revision,
        answers: [{
          answer_kind: "custom",
          question_id: "production_duration_seconds",
          value: "45",
        }],
      });
    });

    expect(result.current.state.guidedAnswerBubbles).toEqual([]);
  });

  it("releases the guided choice lock when its materialization fails", async () => {
    const interaction = guidedConceptInteraction();
    const openSession = { ...guidedSession(), interaction, awaiting: null };
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({ guidanceSession: openSession }));
    api.agentCanvasCreativeSession.mockResolvedValue(openSession);
    api.submitAgentCanvasGuidedInteraction.mockResolvedValue({
      workflow_id: "workflow-1",
      interaction_id: interaction.interaction_id,
      submission_id: "submission-concept-failed-1",
      receipt_id: "receipt-concept-failed-1",
      created_node_ids: [],
      created_binding_ids: [],
      document_revisions: {},
      continuation_id: "continuation-concept-failed-1",
      automatic_run_command_ids: [],
      resulting_session_revision: 9,
      events_cursor: 21,
      replayed: false,
    });
    const { result, rerender } = renderHook(
      ({ chatRevision, chatEvents }) => useAgentCanvasChat({
        workflow: workflow(),
        chatRevision,
        chatEvents,
      }),
      { initialProps: { chatRevision: 0, chatEvents: [] as CanvasRuntimeEventV2[] } },
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(80);
      await result.current.actions.submitGuidedInteraction(interaction, {
        submission_kind: "concept_choice",
        expected_interaction_revision: interaction.revision,
        expected_session_revision: interaction.expected_session_revision,
        action: "select",
        option_id: "option-1",
        custom_text: null,
        accepted_references: [],
      });
    });
    expect(result.current.state.actingInteractionId).toBe(interaction.interaction_id);

    const failedEvent: CanvasRuntimeEventV2 = {
      ...turnEvent("agent_turn_failed", "turn-materialization-failed-1", 22),
      event_type: "proposal_materialization_failed",
      action_id: interaction.interaction_id,
      payload: {
        proposal_id: "proposal-1",
        materialization_id: "materialization-failed-1",
        option_id: "option-1",
        turn_id: "turn-materialization-failed-1",
        error_code: "capability_materialization_failed",
        retryable: true,
      },
    };
    rerender({ chatRevision: 1, chatEvents: [failedEvent] });
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.state.actingInteractionId).toBeNull();
  });

  it("releases a Product source submission after the typed failure event without resending", async () => {
    const interaction = guidedProductInteraction();
    const openSession = { ...guidedSession(), interaction, awaiting: null };
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({ guidanceSession: openSession }));
    api.agentCanvasCreativeSession.mockResolvedValue(openSession);
    api.submitAgentCanvasGuidedInteraction.mockResolvedValue({
      workflow_id: "workflow-1",
      interaction_id: interaction.interaction_id,
      submission_id: "submission-product-failed-1",
      receipt_id: "receipt-product-failed-1",
      created_node_ids: [],
      created_binding_ids: [],
      document_revisions: {},
      continuation_id: null,
      automatic_run_command_ids: [],
      resulting_session_revision: 9,
      events_cursor: 21,
      replayed: false,
    });
    const { result, rerender } = renderHook(
      ({ chatRevision, chatEvents }) => useAgentCanvasChat({
        workflow: workflow(),
        chatRevision,
        chatEvents,
      }),
      { initialProps: { chatRevision: 0, chatEvents: [] as CanvasRuntimeEventV2[] } },
    );

    const request = {
      submission_kind: "product_source" as const,
      expected_interaction_revision: interaction.revision,
      expected_session_revision: interaction.expected_session_revision,
      action: {
        input_kind: "main" as const,
        choice: "upload" as const,
        handoff_mode: "apply" as const,
        asset_versions: [{ asset_id: "asset-product", version_id: "version-product" }],
        pending_handoff_id: "handoff-product",
        expected_guidance_revision: 8,
        question_id: "product_main_source",
      },
    };
    await act(async () => {
      await vi.advanceTimersByTimeAsync(80);
      await result.current.actions.submitGuidedInteraction(interaction, request);
    });
    expect(result.current.state.actingInteractionId).toBe(interaction.interaction_id);

    rerender({
      chatRevision: 1,
      chatEvents: [{
        ...turnEvent("agent_turn_failed", "turn-product-failed-1", 22),
        event_type: "guided_product_source_failed",
        action_id: interaction.interaction_id,
        payload: {
          input_kind: "main",
          request_digest: "sha256:product",
          asset_versions: [{ asset_id: "asset-product", version_id: "version-product" }],
          error_code: "guided_product_source_materialization_failed",
        },
      }],
    });
    await act(async () => Promise.resolve());

    expect(result.current.state.actingInteractionId).toBeNull();
    expect(result.current.state.guidedInteractionIssue?.detail).toContain(
      "guided_product_source_materialization_failed",
    );
    expect(api.submitAgentCanvasGuidedInteraction).toHaveBeenCalledTimes(1);

    const firstIdempotencyKey = api.submitAgentCanvasGuidedInteraction.mock.calls[0]?.[3];
    await act(async () => {
      await result.current.actions.submitGuidedInteraction(interaction, request);
    });

    expect(api.submitAgentCanvasGuidedInteraction).toHaveBeenCalledTimes(2);
    expect(api.submitAgentCanvasGuidedInteraction.mock.calls[1]?.[3]).not.toBe(firstIdempotencyKey);
  });

  it("refreshes authority after a stale guided interaction without resubmitting it", async () => {
    const interaction = guidedQuestionnaireInteraction();
    const session = { ...guidedSession(), interaction, awaiting: null };
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({ guidanceSession: session }));
    api.agentCanvasCreativeSession.mockResolvedValue(session);
    api.submitAgentCanvasGuidedInteraction.mockRejectedValue({
      status: 409,
      code: "guided_interaction_stale",
      message: "The interaction is no longer current.",
    });
    const onWorkflowRefresh = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
      onWorkflowRefresh,
    }));

    await act(async () => {
      vi.advanceTimersByTime(80);
      await Promise.resolve();
      await Promise.resolve();
    });
    api.agentCanvasChatTimeline.mockClear();

    await act(async () => {
      await result.current.actions.submitGuidedInteraction(interaction, {
        submission_kind: "questionnaire",
        expected_interaction_revision: 3,
        expected_session_revision: 8,
        answers: [{ answer_kind: "custom", question_id: "production_duration_seconds", value: "45" }],
      });
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.submitAgentCanvasGuidedInteraction).toHaveBeenCalledTimes(1);
    expect(api.agentCanvasChatTimeline).toHaveBeenCalledTimes(1);
    expect(onWorkflowRefresh).toHaveBeenCalledTimes(1);
    expect(result.current.state.guidedInteractionIssue).toMatchObject({
      summary: "The workflow changed before this response was saved. Review the latest options and try again.",
      retryable: true,
    });
    expect(result.current.state.actingInteractionId).toBeNull();
    expect(result.current.state.workflowRecovery).toBeNull();
  });

  it("reuses one idempotency key when the same guided submission is retried", async () => {
    const interaction = guidedQuestionnaireInteraction();
    const request = {
      submission_kind: "questionnaire" as const,
      expected_interaction_revision: interaction.revision,
      expected_session_revision: interaction.expected_session_revision,
      answers: [{
        answer_kind: "custom" as const,
        question_id: "production_duration_seconds",
        value: "45",
      }],
    };
    api.submitAgentCanvasGuidedInteraction.mockRejectedValue({
      status: 503,
      code: "guided_product_persistence_unavailable",
      message: "Retry the accepted operation.",
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.submitGuidedInteraction(interaction, request);
    });
    await act(async () => {
      await result.current.actions.submitGuidedInteraction(interaction, request);
    });

    expect(api.submitAgentCanvasGuidedInteraction).toHaveBeenCalledTimes(2);
    const firstKey = api.submitAgentCanvasGuidedInteraction.mock.calls[0]?.[3];
    const secondKey = api.submitAgentCanvasGuidedInteraction.mock.calls[1]?.[3];
    expect(firstKey).toBeTruthy();
    expect(secondKey).toBe(firstKey);
  });

  it("keeps an invalid duration in the guided interaction field instead of replacing it with a global error", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline());
    api.submitAgentCanvasGuidedInteraction.mockRejectedValue({
      status: 422,
      code: "guided_duration_value_invalid",
      message: "Use one of the supported duration values.",
    });
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

    await act(async () => {
      await result.current.actions.submitGuidedInteraction(guidedQuestionnaireInteraction(), {
        submission_kind: "questionnaire",
        expected_interaction_revision: 3,
        expected_session_revision: 8,
        answers: [{ answer_kind: "custom", question_id: "production_duration_seconds", value: "12" }],
      });
    });

    expect(result.current.state.guidedInteractionIssue).toMatchObject({
      summary: "Choose one of the supported duration values.",
      fieldId: "production_duration_seconds",
    });
    expect(result.current.state.workflowRecovery).toBeNull();
  });

  it("routes a Guided Interaction server failure into the Decision Dock", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline());
    api.submitAgentCanvasGuidedInteraction.mockRejectedValue({
      status: 500,
      code: "agent_runtime_unavailable",
      message: "Request failed with status 500",
    });
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
    await act(async () => {
      await result.current.actions.submitGuidedInteraction(guidedQuestionnaireInteraction(), {
        submission_kind: "questionnaire",
        expected_interaction_revision: 3,
        expected_session_revision: 8,
        answers: [{ answer_kind: "custom", question_id: "production_duration_seconds", value: "45" }],
      });
    });

    expect(result.current.state.guidedInteractionIssue).toMatchObject({
      summary: "The agent could not submit this response. Try again.",
      retryable: true,
    });
    expect(result.current.state.workflowRecovery).toBeNull();
  });

  it("clears a Decision Dock issue when backend authority replaces the interaction", async () => {
    const interactionA = guidedQuestionnaireInteraction();
    const interactionB = { ...interactionA, interaction_id: "interaction-duration-2" };
    const sessionA = { ...guidedSession(), interaction: interactionA, awaiting: null };
    const sessionB = { ...guidedSession(5, 9), interaction: interactionB, awaiting: null };
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({ guidanceSession: sessionA }));
    api.agentCanvasCreativeSession.mockResolvedValue(sessionA);
    api.submitAgentCanvasGuidedInteraction.mockRejectedValue({
      status: 422,
      code: "guided_duration_value_invalid",
      message: "Invalid duration",
    });
    const { result, rerender } = renderHook(
      ({ chatRevision }) => useAgentCanvasChat({
        workflow: workflow(),
        chatRevision,
        chatEvents: [],
      }),
      { initialProps: { chatRevision: 0 } },
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(80);
    });
    await act(async () => {
      await result.current.actions.submitGuidedInteraction(interactionA, {
        submission_kind: "questionnaire",
        expected_interaction_revision: 3,
        expected_session_revision: 8,
        answers: [{ answer_kind: "custom", question_id: "production_duration_seconds", value: "12" }],
      });
    });
    expect(result.current.state.guidedInteractionIssue).not.toBeNull();

    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({ guidanceSession: sessionB }));
    api.agentCanvasCreativeSession.mockResolvedValue(sessionB);
    rerender({ chatRevision: 1 });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(80);
    });

    expect(result.current.state.guidedInteraction?.interaction_id).toBe("interaction-duration-2");
    expect(result.current.state.guidedInteractionIssue).toBeNull();
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

  it("keeps the selected Skill in frontend-only message presentation metadata", async () => {
    api.submitAgentCanvasChatMessage.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: "message-with-skill",
      turn_id: "turn-with-skill",
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
        text: "Use this visual language.",
        mentionedNodeIds: [],
        mentionedImageAssetIds: [],
        skillTitle: "Cinematic Poetic Realism",
      });
    });

    expect(api.submitAgentCanvasChatMessage).toHaveBeenCalledWith(
      "workflow-1",
      {
        text: "Use this visual language.",
        mentioned_node_ids: [],
        mentioned_image_asset_ids: [],
        video_skill_run_id: null,
      },
      expect.any(String),
    );
    expect(result.current.state.messageSkillTitles).toEqual({
      "message-with-skill": "Cinematic Poetic Realism",
    });
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

    expect(result.current.state.composerRecovery).toMatchObject({
      scope: "composer",
      title: "Response could not be submitted",
      action: "retry",
    });
    expect(result.current.state.composerRecovery?.technicalDetail).toContain("proposal_persistence_failed");
    expect(result.current.state.composerRecovery?.technicalDetail).toContain(
      "The proposal could not be persisted.",
    );
    expect(result.current.state.timelineRecovery).toBeNull();
    expect(result.current.state.workflowRecovery).toBeNull();
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

  it("removes a superseded turn from the pending working state", async () => {
    api.agentCanvasChatTurn.mockResolvedValue({
      turn_id: "turn-superseded-1",
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      status: "superseded",
      turn_kind: "message",
      request: {},
      error_code: null,
      error_message: null,
      creation_mode: null,
      guidance_session_revision: null,
      continuation: null,
      retry_of_turn_id: null,
      retry_attempt_no: 1,
      retryable: false,
      operation_stage: null,
      operation_failure: null,
      created_at: "2026-08-12T00:00:00Z",
      updated_at: "2026-08-12T00:00:01Z",
    });
    const { result, rerender } = renderHook(
      ({ chatEvents }) => useAgentCanvasChat({
        workflow: workflow(),
        chatRevision: 0,
        chatEvents,
      }),
      { initialProps: { chatEvents: [] as CanvasRuntimeEventV2[] } },
    );

    rerender({ chatEvents: [turnEvent("agent_turn_waiting", "turn-superseded-1")] });

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.state.turnsById["turn-superseded-1"]?.status).toBe("superseded");
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

  it("retries a failed message with the Style Skill Run frozen by the original request", async () => {
    const originalWorkflow = workflow();
    originalWorkflow.active_style_skill = {
      skill_run_id: "style-run-original",
      skill_id: "cinematic-poetic-realism",
      skill_version: "1.0.0",
      title: "Cinematic Poetic Realism",
      summary: "A restrained cinematic treatment.",
      category: "cinematic-narrative",
      creative_direction_snapshot_id: "direction-original",
    };
    const changedWorkflow = workflow();
    changedWorkflow.active_style_skill = {
      ...originalWorkflow.active_style_skill,
      skill_run_id: "style-run-new",
      creative_direction_snapshot_id: "direction-new",
    };
    api.submitAgentCanvasChatMessage
      .mockRejectedValueOnce({ code: "agent_runtime_unavailable", message: "Try again." })
      .mockResolvedValueOnce({
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        message_id: "message-retry",
        turn_id: "turn-retry",
        status: "queued",
        events_cursor: 6,
      });
    const { result, rerender } = renderHook(
      ({ currentWorkflow }) => useAgentCanvasChat({
        workflow: currentWorkflow,
        chatRevision: 0,
        chatEvents: [],
      }),
      { initialProps: { currentWorkflow: originalWorkflow } },
    );

    await act(async () => {
      await result.current.actions.submit({
        text: "Keep this exact treatment.",
        mentionedNodeIds: [],
        mentionedImageAssetIds: [],
      });
    });
    const failedDraft = result.current.state.failedDraft;
    expect(failedDraft).toMatchObject({ videoSkillRunId: "style-run-original" });

    rerender({ currentWorkflow: changedWorkflow });
    await act(async () => {
      await result.current.actions.submit(failedDraft!);
    });

    const firstCall = api.submitAgentCanvasChatMessage.mock.calls[0];
    const retryCall = api.submitAgentCanvasChatMessage.mock.calls[1];
    expect(retryCall[1]).toMatchObject({ video_skill_run_id: "style-run-original" });
    expect(retryCall[2]).toBe(firstCall[2]);
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
          policy_version: "fixed_ad_production_v2",
          stage: "scene",
          stage_status: "waiting_user",
          stage_revision: 4,
          decisions: [],
          active_occurrence_id: null,
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

  it("reuses pointer hydration while refreshing the same timeline twice", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      items: [
        {
          item_type: "proposal_pointer",
          proposal_id: "proposal-cache-1",
          sequence: 1,
          created_at: "2026-08-20T00:00:00Z",
        },
        {
          item_type: "decision_bundle_pointer",
          bundle_id: "bundle-cache-1",
          sequence: 2,
          created_at: "2026-08-20T00:00:01Z",
        },
        {
          item_type: "expert_activity",
          activity_id: "activity-cache-1",
          turn_id: "turn-cache-1",
          capability_id: "scene_design",
          capability_display_name: "Scene Designer",
          status: "completed",
          sequence: 3,
          started_at: "2026-08-20T00:00:02Z",
          finished_at: "2026-08-20T00:00:03Z",
          message: null,
          error_code: null,
          elapsed_ms: 1_000,
          attempt_stage: "initial",
          retryable: false,
          validation_paths: [],
          suggested_actions: [],
          completion_mode: null,
          warning_code: null,
        },
        {
          item_type: "expert_activity",
          activity_id: "activity-cache-failed-1",
          turn_id: "turn-cache-failed-1",
          capability_id: "storyboard_design",
          capability_display_name: "Storyboard Artist",
          status: "failed",
          sequence: 4,
          started_at: "2026-08-20T00:00:04Z",
          finished_at: "2026-08-20T00:00:05Z",
          message: null,
          error_code: "provider_error",
          elapsed_ms: 1_000,
          attempt_stage: "initial",
          retryable: true,
          validation_paths: [],
          suggested_actions: [],
          completion_mode: null,
          warning_code: null,
        },
      ],
      next_cursor: 4,
    }));
    api.agentCanvasProposal.mockResolvedValue({ proposal_id: "proposal-cache-1" });
    api.agentCanvasDecisionBundle.mockResolvedValue({ bundle_id: "bundle-cache-1" });
    api.agentCanvasChatTurn.mockImplementation((_workflowId: string, turnId: string) => Promise.resolve({
      turn_id: turnId,
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      status: turnId === "turn-cache-failed-1" ? "failed" : "completed",
      turn_kind: "capability",
      request: {},
      error_code: turnId === "turn-cache-failed-1" ? "provider_error" : null,
      error_message: turnId === "turn-cache-failed-1" ? "Provider request failed." : null,
      creation_mode: null,
      guidance_session_revision: null,
      continuation: null,
      created_at: "2026-08-20T00:00:02Z",
      updated_at: "2026-08-20T00:00:03Z",
    }));
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.refresh();
      await Promise.resolve();
      await result.current.actions.refresh();
      await Promise.resolve();
    });

    expect(api.agentCanvasProposal).toHaveBeenCalledOnce();
    expect(api.agentCanvasDecisionBundle).toHaveBeenCalledOnce();
    expect(api.agentCanvasChatTurn).toHaveBeenCalledTimes(2);
    expect(api.agentCanvasChatTurn).toHaveBeenCalledWith("workflow-1", "turn-cache-1");
    expect(api.agentCanvasChatTurn).toHaveBeenCalledWith("workflow-1", "turn-cache-failed-1");
    expect(result.current.state.timelineRecovery).toBeNull();
  });

  it("coalesces refreshes that arrive while the timeline request is in flight", async () => {
    const resolvers: Array<(timeline: AgentCanvasChatViewTimelineV2) => void> = [];
    api.agentCanvasChatTimeline.mockImplementation(() => new Promise((resolve) => {
      resolvers.push(resolve);
    }));
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    let first: Promise<void> | undefined;
    let second: Promise<void> | undefined;
    let third: Promise<void> | undefined;
    await act(async () => {
      first = result.current.actions.refresh();
      second = result.current.actions.refresh();
      third = result.current.actions.refresh();
      expect(api.agentCanvasChatTimeline).toHaveBeenCalledTimes(1);
      resolvers[0]?.(emptyTimeline());
      for (let attempt = 0; attempt < 5 && resolvers.length < 2; attempt += 1) {
        await Promise.resolve();
      }
      expect(api.agentCanvasChatTimeline).toHaveBeenCalledTimes(2);
      resolvers[1]?.(emptyTimeline());
      await Promise.all([first, second, third]);
    });

    expect(api.agentCanvasChatTimeline).toHaveBeenCalledTimes(2);
  });

  it("keeps successful capability hydration when a sibling turn lookup fails", async () => {
    const activity = (turnId: string, sequence: number) => ({
      item_type: "expert_activity" as const,
      activity_id: `activity-${turnId}`,
      turn_id: turnId,
      capability_id: "scene_design",
      capability_display_name: "Scene Designer",
      status: "completed" as const,
      sequence,
      started_at: "2026-08-20T00:00:02Z",
      finished_at: "2026-08-20T00:00:03Z",
      message: null,
      error_code: null,
      elapsed_ms: 1_000,
      attempt_stage: "initial" as const,
      retryable: false,
      validation_paths: [],
      suggested_actions: [],
      completion_mode: null,
      warning_code: null,
    });
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      items: [activity("turn-success-1", 1), activity("turn-retry-1", 2)],
      next_cursor: 2,
    }));
    let retryAttempts = 0;
    api.agentCanvasChatTurn.mockImplementation((_workflowId: string, turnId: string) => {
      if (turnId === "turn-retry-1" && retryAttempts++ === 0) {
        return Promise.reject(new Error("temporary turn lookup failure"));
      }
      return Promise.resolve({
        turn_id: turnId,
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        status: "completed",
        turn_kind: "capability",
        request: {},
        error_code: null,
        error_message: null,
        creation_mode: null,
        guidance_session_revision: null,
        continuation: null,
        created_at: "2026-08-20T00:00:02Z",
        updated_at: "2026-08-20T00:00:03Z",
      });
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.refresh();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.state.turnsById["turn-success-1"]?.status).toBe("completed");
    expect(result.current.state.turnsById["turn-retry-1"]).toBeUndefined();

    await act(async () => {
      await result.current.actions.refresh();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(api.agentCanvasChatTurn).toHaveBeenCalledTimes(3);
    expect(result.current.state.turnsById["turn-retry-1"]?.status).toBe("completed");
  });

  it("reuses proposal data without retaining stale pointer placement metadata", async () => {
    let pointerSequence = 1;
    api.agentCanvasChatTimeline.mockImplementation(() => Promise.resolve(emptyTimeline({
      items: [{
          item_type: "proposal_pointer",
          proposal_id: "proposal-moving-1",
          sequence: pointerSequence,
          created_at: pointerSequence === 1
            ? "2026-08-20T00:00:00Z"
            : "2026-08-20T00:05:00Z",
      }],
      next_cursor: pointerSequence,
    })));
    api.agentCanvasProposal.mockResolvedValue({ proposal_id: "proposal-moving-1" });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.refresh();
    });
    expect(result.current.state.items[0]?.sequence).toBe(1);
    pointerSequence = 8;
    await act(async () => {
      await result.current.actions.refresh();
    });

    expect(api.agentCanvasProposal).toHaveBeenCalledOnce();
    expect(result.current.state.items[0]).toMatchObject({
      item_type: "proposal",
      sequence: 8,
      created_at: "2026-08-20T00:05:00Z",
    });
  });

  it("invalidates mutable pointer payloads when the chat revision advances", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline({
      items: [{
        item_type: "proposal_pointer",
        proposal_id: "proposal-revision-1",
        sequence: 1,
        created_at: "2026-08-20T00:00:00Z",
      }],
      next_cursor: 1,
    }));
    api.agentCanvasProposal
      .mockResolvedValueOnce({ proposal_id: "proposal-revision-1", proposal_revision: 1 })
      .mockResolvedValue({ proposal_id: "proposal-revision-1", proposal_revision: 2 });
    const { result, rerender } = renderHook(
      ({ chatRevision }) => useAgentCanvasChat({
        workflow: workflow(),
        chatRevision,
        chatEvents: [],
      }),
      { initialProps: { chatRevision: 0 } },
    );

    await act(async () => {
      await result.current.actions.refresh();
    });
    expect(api.agentCanvasProposal).toHaveBeenCalledOnce();

    rerender({ chatRevision: 1 });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(80);
    });

    expect(api.agentCanvasProposal).toHaveBeenCalledTimes(2);
    expect(result.current.state.items[0]).toMatchObject({
      item_type: "proposal",
      proposal: { proposal_revision: 2 },
    });
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

  it("hydrates the executable turn identified by guidance advance acceptance", async () => {
    api.agentCanvasChatTimeline.mockResolvedValue(emptyTimeline());
    const { rerender } = renderHook(({ chatEvents }) => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: chatEvents.length,
      chatEvents,
    }), { initialProps: { chatEvents: [] as CanvasRuntimeEventV2[] } });
    const acceptedEvent: CanvasRuntimeEventV2 = {
      ...turnEvent("agent_turn_started", "turn-guidance-executable-1", 9),
      event_type: "guidance_advance_accepted",
      payload: {
        command_turn_id: "turn-guidance-command-1",
        executable_turn_id: "turn-guidance-executable-1",
      },
    };

    rerender({ chatEvents: [acceptedEvent] });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.agentCanvasChatTurn).toHaveBeenCalledWith(
      "workflow-1",
      "turn-guidance-executable-1",
    );
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

  it("retries a failed Proposal materialization through its authoritative child Turn", async () => {
    api.retryAgentCanvasChatTurn.mockResolvedValue({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      turn_id: "turn-materialization-retry-1",
      status: "queued",
      events_cursor: 9,
      retry_of_turn_id: "turn-materialization-1",
      retry_attempt_no: 2,
      replayed: false,
    });
    const { result } = renderHook(() => useAgentCanvasChat({
      workflow: workflow(),
      chatRevision: 0,
      chatEvents: [],
    }));

    await act(async () => {
      await result.current.actions.retryProposalMaterialization({
        materialization_id: "materialization-1",
        option_id: "option-1",
        turn_id: "turn-materialization-1",
        status: "failed",
        attempt_no: 1,
        retryable: true,
        error: {
          code: "capability_materialization_failed",
          message: "Draft creation failed.",
        },
        created_at: "2026-08-18T00:00:00Z",
        updated_at: "2026-08-18T00:00:01Z",
      });
    });

    expect(api.retryAgentCanvasChatTurn).toHaveBeenCalledWith(
      "workflow-1",
      "turn-materialization-1",
      {
        expected_session_revision: 0,
        expected_workflow_revision: 1,
      },
      expect.stringContaining("chat-turn-retry-turn-materialization-1"),
    );
    expect(api.submitAgentCanvasChatMessage).not.toHaveBeenCalled();
    expect(api.actOnAgentCanvasProposal).not.toHaveBeenCalled();
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

    expect(result.current.state.timelineRecovery).toMatchObject({
      technicalDetail: "agent_runtime_unavailable: The configured agent runtime is unavailable.",
      action: "retry",
    });
    expect(result.current.state.failedDraft).toBeNull();
    expect(result.current.state.retryableFailedTurn?.turn_id).toBe("turn-1");
  });
});
