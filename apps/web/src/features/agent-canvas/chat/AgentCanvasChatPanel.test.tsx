import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  ChatActionReceiptCardV2,
  AgentCanvasWorkflowV2,
  ChatCapabilityActivityV2,
  ChatCommandPlanCardV2,
  ChatProposalCardV2,
  GuidedSessionStateV2,
  ProposalActionDescriptorV2,
} from "../../../types-v2.ts";
import {
  ActionReceiptCard,
  AgentCanvasChatPanel,
  AgentWorkingRow,
  CapabilityActivityRow,
  CommandPlanCard,
  GuidanceSessionProgress,
  GuidedActionsCard,
  ProposalCard,
} from "./AgentCanvasChatPanel.tsx";
import {
  resizeChatComposerTextarea,
  snapChatComposerScroll,
} from "./chatComposerTextarea.ts";

describe("chat composer textarea", () => {
  it("grows with its content and only scrolls after reaching its height limit", () => {
    const textarea = document.createElement("textarea");
    let scrollHeight = 86;
    let clientHeight = 86;
    Object.defineProperty(textarea, "scrollHeight", { configurable: true, get: () => scrollHeight });
    Object.defineProperty(textarea, "clientHeight", { configurable: true, get: () => clientHeight });

    resizeChatComposerTextarea(textarea);
    expect(textarea.style.height).toBe("86px");
    expect(textarea.style.overflowY).toBe("hidden");

    scrollHeight = 220;
    clientHeight = 120;
    resizeChatComposerTextarea(textarea);
    expect(textarea.style.height).toBe("220px");
    expect(textarea.style.overflowY).toBe("auto");
  });

  it("snaps native textarea scrolling to complete line boundaries", () => {
    const textarea = document.createElement("textarea");
    textarea.style.lineHeight = "20px";
    Object.defineProperty(textarea, "scrollHeight", { configurable: true, value: 200 });
    Object.defineProperty(textarea, "clientHeight", { configurable: true, value: 120 });

    textarea.scrollTop = 29;
    snapChatComposerScroll(textarea);
    expect(textarea.scrollTop).toBe(20);
  });
});

describe("AgentWorkingRow", () => {
  afterEach(() => cleanup());

  it("announces that the Agent is working and renders a loading indicator", () => {
    render(<AgentWorkingRow />);

    expect(screen.getByRole("status", { name: "AdCraft Video Agent is working" })).toBeTruthy();
    expect(screen.getByText("Working")).toBeTruthy();
    expect(document.querySelector(".agent-chat__working-spinner")).toBeTruthy();
  });
});

function proposalAction(
  action: ProposalActionDescriptorV2["action"],
  label: string,
  optionId: string | null = null,
): ProposalActionDescriptorV2 {
  return {
    action_id: `action-${action}`,
    action,
    label,
    proposal_id: "proposal-1",
    expected_session_revision: 7,
    confirmation_required: false,
    reason: `${label} for the active topic.`,
    option_id: optionId,
    enabled: true,
    disabled_reason: null,
  };
}

const proposalCard: ChatProposalCardV2 = {
  item_type: "proposal",
  proposal: {
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
      public_summary: "A focused campaign hero",
      key_decisions: ["Contemporary wardrobe", "Confident posture"],
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
    actions: [
      proposalAction("select_option", "Use this direction"),
      proposalAction("revise_options", "Revise options"),
      proposalAction("defer_topic", "Decide later"),
      proposalAction("exclude_element", "Exclude character"),
      proposalAction("delegate_choice", "Let AdCraft choose"),
    ],
    created_at: "2026-08-04T00:00:00Z",
    updated_at: "2026-08-04T00:00:00Z",
  },
  sequence: 4,
  created_at: "2026-08-04T00:00:00Z",
};

describe("ProposalCard", () => {
  afterEach(() => cleanup());

  it("uses the select descriptor and creates a Draft without a second generation choice", () => {
    const onSelect = vi.fn().mockResolvedValue(undefined);
    render(
      <ProposalCard
        card={proposalCard}
        pending={false}
        onSelect={onSelect}
        onRevise={vi.fn()}
        onApplyAction={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("Hero").closest("button")!);
    fireEvent.click(screen.getByRole("button", { name: "Use this direction" }));

    expect(onSelect).toHaveBeenCalledWith(
      "proposal-1",
      expect.objectContaining({ action_id: "action-select_option", action: "select_option" }),
      "option-1",
      [],
    );
    expect(screen.getByText("Contemporary wardrobe")).toBeTruthy();
    expect(screen.getByText("Confident posture")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Generate now" })).toBeNull();
  });

  it.each(["queued", "working"] as const)(
    "keeps the selected direction visible and disables every action while materialization is %s",
    (status) => {
      render(
        <ProposalCard
          card={{
            ...proposalCard,
            proposal: {
              ...proposalCard.proposal,
              materialization: {
                materialization_id: "materialization-1",
                option_id: "option-1",
                turn_id: "turn-materialization-1",
                status,
                attempt_no: 1,
                retryable: false,
                error: null,
                created_at: "2026-08-08T00:00:00Z",
                updated_at: "2026-08-08T00:00:01Z",
              },
            },
          }}
          pending={false}
          onSelect={vi.fn()}
          onRevise={vi.fn()}
          onApplyAction={vi.fn()}
        />,
      );

      expect(screen.getByRole("status", { name: `Proposal materialization ${status}` })).toBeTruthy();
      expect((screen.getByRole("button", { name: "Use this direction" }) as HTMLButtonElement).disabled).toBe(true);
      expect((screen.getByRole("button", { name: "Revise options" }) as HTMLButtonElement).disabled).toBe(true);
      expect((screen.getByRole("button", { name: "Decide later" }) as HTMLButtonElement).disabled).toBe(true);
    },
  );

  it("preserves the selected option and references after a retryable failure", () => {
    const proposedReference = {
      source_kind: "image_asset" as const,
      source_id: "asset-hero-1",
      binding_kind: "image_reference" as const,
      input_role: "visual_reference" as const,
      required: true,
      display_order: 0,
      display_name: "Hero reference",
      media_type: "image" as const,
    };
    const { rerender } = render(
      <ProposalCard
        card={{
          ...proposalCard,
          proposal: {
            ...proposalCard.proposal,
            proposed_references: [proposedReference],
          },
        }}
        pending={false}
        onSelect={vi.fn()}
        onRevise={vi.fn()}
        onApplyAction={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("Hero").closest("button")!);
    fireEvent.click(screen.getByRole("checkbox", { name: "Required" }));
    expect((screen.getByRole("checkbox", { name: "Required" }) as HTMLInputElement).checked).toBe(false);

    rerender(
      <ProposalCard
        card={{
          ...proposalCard,
          proposal: {
            ...proposalCard.proposal,
            proposal_revision: 2,
            proposed_references: [proposedReference],
            materialization: {
              materialization_id: "materialization-1",
              option_id: "option-1",
              turn_id: "turn-materialization-1",
              status: "failed",
              attempt_no: 1,
              retryable: true,
              error: {
                code: "capability_materialization_failed",
                message: "The selected direction could not be prepared.",
              },
              created_at: "2026-08-08T00:00:00Z",
              updated_at: "2026-08-08T00:00:01Z",
            },
          },
        }}
        pending={false}
        onSelect={vi.fn()}
        onRevise={vi.fn()}
        onApplyAction={vi.fn()}
      />,
    );

    expect(screen.getByText("The selected direction could not be prepared.")).toBeTruthy();
    expect(screen.getByText("Hero reference")).toBeTruthy();
    expect((screen.getByRole("checkbox", { name: "Required" }) as HTMLInputElement).checked).toBe(false);
    expect((screen.getByRole("button", { name: "Use this direction" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("does not offer a failed materialization retry when the backend marks it non-retryable", () => {
    render(
      <ProposalCard
        card={{
          ...proposalCard,
          proposal: {
            ...proposalCard.proposal,
            materialization: {
              materialization_id: "materialization-1",
              option_id: "option-1",
              turn_id: "turn-materialization-1",
              status: "failed",
              attempt_no: 1,
              retryable: false,
              error: {
                code: "proposal_reference_unavailable",
                message: "A required reference is no longer available.",
              },
              created_at: "2026-08-08T00:00:00Z",
              updated_at: "2026-08-08T00:00:01Z",
            },
          },
        }}
        pending={false}
        onSelect={vi.fn()}
        onRevise={vi.fn()}
        onApplyAction={vi.fn()}
      />,
    );

    expect(screen.getByText("A required reference is no longer available.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Use this direction" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("dispatches revise, defer, exclude, and delegate through their structured descriptors", () => {
    const onRevise = vi.fn().mockResolvedValue(undefined);
    const onApplyAction = vi.fn().mockResolvedValue(undefined);
    render(
      <ProposalCard
        card={proposalCard}
        pending={false}
        onSelect={vi.fn()}
        onRevise={onRevise}
        onApplyAction={onApplyAction}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Revise options" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Proposal revision" }), {
      target: { value: "Make the character warmer." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit proposal revision" }));
    expect(onRevise).toHaveBeenCalledWith(
      "proposal-1",
      expect.objectContaining({ action: "revise_options" }),
      "Make the character warmer.",
    );

    for (const [label, action] of [
      ["Decide later", "defer_topic"],
      ["Exclude character", "exclude_element"],
      ["Let AdCraft choose", "delegate_choice"],
    ] as const) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(onApplyAction).toHaveBeenCalledWith(
        "proposal-1",
        expect.objectContaining({ action }),
      );
    }
  });

  it("keeps applied proposal content visible but disables all stale actions", () => {
    render(
      <ProposalCard
        card={{
          ...proposalCard,
          proposal: {
            ...proposalCard.proposal,
            availability: "applied",
            application_count: 1,
            latest_application: {
              application_id: "application-1",
              option_id: "option-1",
              action: "select_option",
              receipt_id: "receipt-1",
              created_node_ids: ["node-character-1"],
              queued_execution_ids: [],
              created_at: "2026-08-04T00:01:00Z",
            },
          },
        }}
        pending={false}
        onSelect={vi.fn()}
        onRevise={vi.fn()}
        onApplyAction={vi.fn()}
      />,
    );

    expect(screen.getByText("Hero")).toBeTruthy();
    expect(screen.getByText(/Applied 1 time/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Use this direction" })).toBeNull();
  });

  it("renders enabled historical actions on a superseded proposal option", () => {
    const onApplyAction = vi.fn().mockResolvedValue(undefined);
    render(
      <ProposalCard
        card={{
          ...proposalCard,
          proposal: {
            ...proposalCard.proposal,
            availability: "superseded",
            actions: [
              proposalAction("reuse_direction", "Use this direction", "option-1"),
              proposalAction("revise_direction", "Revise this direction", "option-1"),
            ],
          },
        }}
        pending={false}
        onSelect={vi.fn()}
        onRevise={vi.fn()}
        onApplyAction={onApplyAction}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Use this direction" }));
    expect(onApplyAction).toHaveBeenCalledWith(
      "proposal-1",
      expect.objectContaining({ action: "reuse_direction", option_id: "option-1" }),
    );
    expect(screen.getByRole("button", { name: "Revise this direction" })).toBeTruthy();
  });

  it("renders only the World Setting actions returned by the backend", () => {
    render(
      <ProposalCard
        card={{
          ...proposalCard,
          proposal: {
            ...proposalCard.proposal,
            proposal_kind: "world_setting",
            capability_id: "world_setting",
            capability_display_name: "World Setting Designer",
            options: [
              { option_id: "world-1", title: "Quiet future", public_summary: "A calm near-future city.", key_decisions: ["Quiet technology"] },
              { option_id: "world-2", title: "Living heritage", public_summary: "Modern craft rooted in tradition.", key_decisions: ["Visible craft heritage"] },
            ],
            actions: [
              proposalAction("select_option", "Use this world"),
              proposalAction("revise_options", "Revise worlds"),
              proposalAction("delegate_choice", "Let AdCraft choose"),
            ],
          },
        }}
        pending={false}
        onSelect={vi.fn()}
        onRevise={vi.fn()}
        onApplyAction={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Quiet future/ }));
    expect(screen.getByRole("button", { name: "Use this world" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Revise worlds" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Let AdCraft choose" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Decide later" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Exclude character" })).toBeNull();
  });
});

describe("progress and action cards", () => {
  afterEach(() => cleanup());

  it("renders progressive guidance state without a fixed production recipe", () => {
    const session: GuidedSessionStateV2 = {
      session_id: "guidance-1",
      workflow_id: "workflow-1",
      status: "active",
      goal: {
        requested_output: "video",
        delivery_scope: "generated_media",
        summary: "Create a launch film.",
        explicit_constraints: {},
      },
      creative_authority: {
        authority: "user",
        source: "explicit_user",
        decided_at_turn_id: "turn-authority-1",
        revision: 1,
      },
      current_checkpoint: {
        checkpoint_id: "checkpoint-1",
        workflow_id: "workflow-1",
        session_revision: 7,
        stage_kind: "scene",
        status: "waiting_user",
        trigger: "proposal_action",
        action_id: null,
      },
      narrative_direction: null,
      element_decisions: [],
      current_topic_id: "topic-scene",
      topics: [
        {
          topic_id: "topic-character",
          topic_kind: "character",
          title: "Lead character",
          status: "selected",
          capability_id: "character_design",
          capability_display_name: "Character Designer",
          related_node_ids: ["node-character-1"],
          source_proposal_id: "proposal-character",
          revision: 1,
        },
        {
          topic_id: "topic-scene",
          topic_kind: "scene",
          title: "Scene direction",
          status: "proposed",
          capability_id: "scene_design",
          capability_display_name: "Scene Designer",
          related_node_ids: [],
          source_proposal_id: "proposal-scene",
          revision: 1,
        },
      ],
      active_proposal_id: "proposal-scene",
      active_style_skill_run_id: null,
      completion: {
        authoring: "not_ready",
        delivery: "not_ready",
        editing_preparation: "not_ready",
        editing_node_id: null,
        matching_node_ids: ["node-character-1"],
        matching_asset_ids: [],
      },
      revision: 7,
      updated_at: "2026-08-04T00:00:00Z",
    };

    render(<GuidanceSessionProgress session={session} />);

    expect(screen.getByText("Create a launch film.")).toBeTruthy();
    expect(screen.getByText("Lead character")).toBeTruthy();
    expect(screen.getByText("Scene direction")).toBeTruthy();
    expect(screen.getByText("Authoring: not ready")).toBeTruthy();
    expect(screen.getByText("Delivery: not ready")).toBeTruthy();
    expect(screen.getByText("Direction: You")).toBeTruthy();
    expect(screen.getByText("Checkpoint: scene · waiting user")).toBeTruthy();
  });

  it("renders only current stop or resume guidance actions", () => {
    const onApply = vi.fn().mockResolvedValue(undefined);
    render(
      <GuidedActionsCard
        actions={[
          {
            action_id: "action-stale",
            logical_key: "stop:old",
            action: "stop_guidance",
            state: "superseded",
            creating_turn_id: "turn-1",
            expected_session_revision: 6,
            label: "Old stop action",
            workflow_id: "workflow-1",
            confirmation_required: true,
            reason: "A newer session revision exists.",
            authority: null,
          },
          {
            action_id: "action-stop",
            logical_key: "stop:current",
            action: "stop_guidance",
            state: "pending",
            creating_turn_id: "turn-2",
            expected_session_revision: 7,
            label: "Stop guidance",
            workflow_id: "workflow-1",
            confirmation_required: true,
            reason: "Keep the current drafts.",
            authority: null,
          },
        ]}
        actingActionId={null}
        onApply={onApply}
      />,
    );

    expect(screen.queryByRole("button", { name: "Old stop action" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Stop guidance" }));
    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({
      action_id: "action-stop",
      action: "stop_guidance",
    }));
  });
});

describe("command and receipt cards", () => {
  afterEach(() => cleanup());

  it("offers Confirm and Reject for a pending command", () => {
    const card: ChatCommandPlanCardV2 = {
      item_type: "command_plan",
      command_plan: {
        plan_id: "plan-1",
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        source_turn_id: "turn-1",
        context_snapshot_id: "snapshot-1",
        base_workflow_revision: 3,
        expires_at: "2026-08-04T01:00:00Z",
        operations: [{
          operation_type: "delete_node",
          operation_id: "delete-1",
          node: { kind: "node_id", node_id: "node-1" },
        }],
        continuation_requested: false,
        risk: "destructive_authoring",
        confirmation_required: true,
        target_summary: "Delete the failed image draft.",
        operation_fingerprint: "fingerprint-1",
        idempotency_key: "command-1",
        status: "pending_confirmation",
        supersedes_plan_id: null,
        replacement_plan_id: null,
        actor: "agent",
        created_at: "2026-08-04T00:00:00Z",
        updated_at: "2026-08-04T00:00:00Z",
      },
      sequence: 5,
      created_at: "2026-08-04T00:00:00Z",
    };
    const onAction = vi.fn().mockResolvedValue(undefined);
    render(<CommandPlanCard card={card} pending={false} onAction={onAction} />);

    expect(screen.getByText("1 canvas change will be applied.")).toBeTruthy();
    expect(screen.queryByText("Delete Node")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Confirm command" }));
    fireEvent.click(screen.getByRole("button", { name: "Reject command" }));
    expect(onAction).toHaveBeenNthCalledWith(1, "plan-1", "confirm");
    expect(onAction).toHaveBeenNthCalledWith(2, "plan-1", "reject");
  });

  it("renders structured receipt errors and continuation state", () => {
    const card: ChatActionReceiptCardV2 = {
      item_type: "action_receipt",
      action_receipt: {
        receipt_id: "receipt-1",
        workflow_id: "workflow-1",
        plan_id: null,
        action_id: "action-select_option",
        proposal_id: "proposal-1",
        proposal_option_id: "option-1",
        proposal_action: "select_option",
        actor_kind: "user",
        idempotency_key: "proposal-select-1",
        status: "applied_with_run_error",
        summary: "Created the selected Draft.",
        created_node_ids: ["node-1"],
        updated_node_ids: [],
        deleted_node_ids: [],
        created_binding_ids: [],
        deleted_binding_ids: [],
        queued_execution_ids: [],
        run_queue_errors: ["The provider queue is temporarily unavailable."],
        operation_results: [],
        workflow_revision: 4,
        before_workflow_revision: 3,
        placement_hints: [],
        continuation_turn_id: "turn-next",
        superseded_by: null,
        error_code: "agent_runtime_unavailable",
        error_message: "Generation can be retried later.",
        created_at: "2026-08-04T00:00:00Z",
      },
      sequence: 6,
      created_at: "2026-08-04T00:00:00Z",
    };

    render(<ActionReceiptCard card={card} />);

    expect(screen.getByText("Created the selected Draft.")).toBeTruthy();
    expect(screen.getByText("Generation can be retried later.")).toBeTruthy();
    expect(screen.getByText("Planning continues automatically")).toBeTruthy();
  });

  it("shows capability work as status rather than another chat speaker", () => {
    const activity: ChatCapabilityActivityV2 = {
      item_type: "expert_activity",
      activity_id: "activity-1",
      turn_id: "turn-1",
      capability_id: "scene_design",
      capability_display_name: "Scene Designer",
      status: "working",
      sequence: 4,
      started_at: "2026-08-04T00:00:00Z",
      finished_at: null,
      message: null,
      error_code: null,
      elapsed_ms: null,
      attempt_stage: null,
      retryable: false,
      validation_paths: [],
      suggested_actions: [],
      completion_mode: null,
      warning_code: null,
    };
    render(<CapabilityActivityRow activity={activity} />);

    expect(screen.getByText("Scene Designer is working")).toBeTruthy();
    expect(screen.queryByText("AdCraft Video Agent", { exact: false })).toBeNull();
  });

  it("shows bounded recovery actions for a backend-owned capability failure", () => {
    const onRetry = vi.fn();
    const onReviseRequest = vi.fn();
    render(<CapabilityActivityRow activity={{
      item_type: "expert_activity",
      activity_id: "activity-failed",
      turn_id: "turn-failed",
      capability_id: "scene_design",
      capability_display_name: "Scene Designer",
      status: "failed",
      sequence: 5,
      started_at: "2026-08-07T01:00:00Z",
      finished_at: "2026-08-07T01:07:00Z",
      message: "The capability request timed out.",
      error_code: "agent_deadline_exceeded",
      elapsed_ms: 420000,
      attempt_stage: "transport_retry",
      retryable: true,
      validation_paths: [],
      suggested_actions: ["retry", "revise_request"],
      completion_mode: null,
      warning_code: null,
    }} onRetry={onRetry} onReviseRequest={onReviseRequest} />);

    expect(screen.getByText("agent_deadline_exceeded")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry Scene Designer activity" }));
    fireEvent.click(screen.getByRole("button", { name: "Revise Scene Designer request" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onReviseRequest).toHaveBeenCalledTimes(1);
  });

  it("treats deterministic fallback as completed with a warning", () => {
    render(<CapabilityActivityRow activity={{
      item_type: "expert_activity",
      activity_id: "activity-fallback",
      turn_id: "turn-fallback",
      capability_id: "product_design",
      capability_display_name: "Product Designer",
      status: "completed",
      sequence: 6,
      started_at: "2026-08-07T01:00:00Z",
      finished_at: "2026-08-07T01:01:00Z",
      message: null,
      error_code: null,
      elapsed_ms: null,
      attempt_stage: null,
      retryable: false,
      validation_paths: [],
      suggested_actions: [],
      completion_mode: "deterministic_fallback",
      warning_code: "specialist_materialization_fallback",
    }} />);

    expect(screen.getByText("Draft created with a simplified fallback.")).toBeTruthy();
    expect(screen.queryByText(/failed/i)).toBeNull();
  });
});

describe("AgentCanvasChatPanel Style integration", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("places the persistent Workflow Style control beside composer tools", () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      workflow_id: "workflow-1",
      conversation_id: null,
      items: [],
      next_cursor: 0,
    }), { headers: { "Content-Type": "application/json" } })));
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
      active_style_skill: {
        skill_run_id: "style-run-1",
        skill_id: "platform-default",
        skill_version: "1.0.0",
        title: "Platform Default",
        summary: "Balanced commercial video direction.",
        category: "commercial-craft",
        creative_direction_snapshot_id: "direction-1",
      },
    };

    render(
      <AgentCanvasChatPanel
        workflow={workflow}
        chatRevision={0}
        chatEvents={[]}
        onFocusNode={vi.fn()}
        onWorkflowRefresh={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Mention node or image asset" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Style: Platform Default" })).toBeTruthy();
  });

  it("uses an opaque edge-aligned chat rail with plain Agent replies", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const panelRule = css.match(/^\.agent-chat\s*\{([\s\S]*?)\n\}/m)?.[1];
    const agentMessageRule = css.match(/\.agent-chat__message--agent\s*:\s*is\(p, \.agent-chat__markdown\)\s*\{([\s\S]*?)\n\}/m)?.[1];
    const userMessageRule = css.match(/\.agent-chat__message--user\s*:\s*is\(p, \.agent-chat__markdown\)\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(panelRule).toContain("top: 0");
    expect(panelRule).toContain("right: 0");
    expect(panelRule).toContain("bottom: 0");
    expect(panelRule).toContain("background: #282828");
    expect(panelRule).toContain("backdrop-filter: none");
    expect(panelRule).toContain("border-radius: 0");
    expect(css).toMatch(/\.agent-chat__message--agent > span\s*\{\s*display: none;/);
    expect(agentMessageRule).toContain("padding: 0");
    expect(agentMessageRule).toContain("background: transparent");
    expect(userMessageRule).toContain("background: #343434");
  });

  it("uses a legible AdCraft Bot icon in the collapsed trigger", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const triggerRule = css.match(/\.agent-chat__collapsed-trigger\s*\{([\s\S]*?)\n\}/m)?.[1];
    const iconRule = css.match(/\.agent-chat__collapsed-trigger img\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(triggerRule).toContain("height: 42px");
    expect(iconRule).toContain("width: 28px");
    expect(iconRule).toContain("height: 28px");
  });

  it("collapses to an AdCraft Bot trigger without discarding the message draft", () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      workflow_id: "workflow-1",
      conversation_id: null,
      items: [],
      next_cursor: 0,
    }), { headers: { "Content-Type": "application/json" } })));
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
    const { container } = render(
      <AgentCanvasChatPanel
        workflow={workflow}
        chatRevision={0}
        chatEvents={[]}
        onFocusNode={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByRole("textbox", { name: "Message AdCraft Video Agent" }), {
      target: { value: "Keep this draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Collapse AdCraft Bot panel" }));

    expect(screen.queryByRole("complementary", { name: "AdCraft Video Agent" })).toBeNull();
    expect(screen.getByRole("button", { name: "Open AdCraft Bot panel" })).toBeTruthy();
    expect(container.querySelector('img[src="/imgs/logo.png"]')).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Open AdCraft Bot panel" }));

    expect(screen.getByRole("complementary", { name: "AdCraft Video Agent" })).toBeTruthy();
    expect((screen.getByRole("textbox", { name: "Message AdCraft Video Agent" }) as HTMLTextAreaElement).value).toBe("Keep this draft");
  });
});
