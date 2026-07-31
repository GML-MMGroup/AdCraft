import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  ChatActionReceiptCardV2,
  ChatCommandPlanCardV2,
  ChatExpertActivityV2,
  ChatProposalCardV2,
} from "../../../types-v2.ts";
import {
  ActionReceiptCard,
  CommandPlanCard,
  GuidedActionsCard,
  ProductionRecipeProgress,
  ProposalCard,
  SpecialistActivityRow,
} from "./AgentCanvasChatPanel.tsx";

const card: ChatProposalCardV2 = {
  item_type: "proposal",
  proposal: {
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
    status: "pending",
    options: [{
      option_id: "option-1",
      title: "Hero",
      summary_prompt: "A focused campaign hero",
    }],
    proposed_references: [],
    selected_option_id: null,
    selection_actor: null,
    created_at: "2026-07-28T00:00:00Z",
    updated_at: "2026-07-28T00:00:00Z",
  },
  sequence: 4,
  created_at: "2026-07-28T00:00:00Z",
};

describe("ProposalCard", () => {
  afterEach(() => cleanup());

  it("requires an explicit Select step before choosing the next action", () => {
    const onSelect = vi.fn().mockResolvedValue(undefined);
    render(
      <ProposalCard
        card={card}
        pending={false}
        onSelect={onSelect}
        onRevise={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Hero/ }));
    expect(screen.getByRole("button", { name: "Select" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Generate now" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate now" }));

    expect(onSelect).toHaveBeenCalledWith("proposal-1", "option-1", "generate_now", []);
  });
});

describe("command control cards", () => {
  afterEach(() => cleanup());

  const commandCard: ChatCommandPlanCardV2 = {
    item_type: "command_plan",
    command_plan: {
      plan_id: "plan-1",
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      source_turn_id: "turn-1",
      base_workflow_revision: 3,
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
      status: "pending_confirmation",
      supersedes_plan_id: null,
      replacement_plan_id: null,
      actor: "agent",
      created_at: "2026-07-29T02:00:00Z",
      updated_at: "2026-07-29T02:00:00Z",
    },
    sequence: 5,
    created_at: "2026-07-29T02:00:00Z",
  };

  it("offers Confirm and Reject only for a pending command that requires confirmation", () => {
    const onAction = vi.fn().mockResolvedValue(undefined);
    const view = render(
      <CommandPlanCard card={commandCard} pending={false} onAction={onAction} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Confirm command" }));
    fireEvent.click(screen.getByRole("button", { name: "Reject command" }));
    expect(onAction).toHaveBeenNthCalledWith(1, "plan-1", "confirm");
    expect(onAction).toHaveBeenNthCalledWith(2, "plan-1", "reject");

    view.rerender(
      <CommandPlanCard
        card={{
          ...commandCard,
          command_plan: { ...commandCard.command_plan, status: "applied" },
        }}
        pending={false}
        onAction={onAction}
      />,
    );
    expect(screen.queryByRole("button", { name: "Confirm command" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject command" })).toBeNull();
  });

  it("renders the backend recipe order and hides not-required stages", () => {
    render(
      <ProductionRecipeProgress
        creationMode="guided_production"
        recipe={{
          recipe_id: "recipe-1",
          workflow_id: "workflow-1",
          conversation_id: "conversation-1",
          skill_run_id: null,
          revision: 2,
          creation_mode: "guided_production",
          current_topic_id: "topic-scene",
          stages: [
            {
              topic_id: "topic-product",
              topic_kind: "product",
              title: "Product design",
              objective: "Use the existing product reference.",
              applicability: "not_required",
              applicability_reason: "Already approved.",
              specialist_name: "product_designer",
              proposal_mode: "single_plan",
              candidate_count: 1,
              status: "not_required",
              related_node_ids: ["node-product-1"],
            },
            {
              topic_id: "topic-scene",
              topic_kind: "scene",
              title: "Scene design",
              objective: "Choose a setting.",
              applicability: "required",
              applicability_reason: "A setting is required.",
              specialist_name: "scene_designer",
              proposal_mode: "choice_set",
              candidate_count: 3,
              status: "working",
              related_node_ids: [],
            },
            {
              topic_id: "topic-audio",
              topic_kind: "audio",
              title: "Audio direction",
              objective: "Set the music direction.",
              applicability: "optional",
              applicability_reason: "Music can be added later.",
              specialist_name: "bgm_director",
              proposal_mode: "single_plan",
              candidate_count: 1,
              status: "pending",
              related_node_ids: [],
            },
          ],
          anchor_digest: "anchor-1",
          created_at: "2026-07-31T05:00:00Z",
          updated_at: "2026-07-31T05:01:00Z",
        }}
      />,
    );

    expect(screen.getByText("Scene design")).toBeTruthy();
    expect(screen.getByText("Audio direction")).toBeTruthy();
    expect(screen.queryByText("Product design")).toBeNull();
  });

  it("removes superseded guided actions instead of leaving stale controls clickable", () => {
    render(
      <GuidedActionsCard
        card={{
          item_type: "guided_actions",
          source_entry_id: "entry-1",
          sequence: 1,
          created_at: "2026-07-31T05:00:00Z",
          actions: [
            {
              action_id: "action-stale",
              action: "add_another_topic_node",
              state: "superseded",
              creating_turn_id: "turn-1",
              expected_semantic_revision: 2,
              label: "Add another",
              workflow_id: "workflow-1",
              proposal_id: "proposal-1",
              topic_id: "topic-1",
              node_id: null,
              ordered_node_ids: [],
              manifest_revision: null,
              confirmation_required: false,
              reason: "A newer proposal replaced this action.",
            },
            {
              action_id: "action-current",
              action: "skip_topic",
              state: "pending",
              creating_turn_id: "turn-2",
              expected_semantic_revision: 3,
              label: "Skip optional audio",
              workflow_id: "workflow-1",
              proposal_id: null,
              topic_id: "topic-audio",
              node_id: null,
              ordered_node_ids: [],
              manifest_revision: null,
              confirmation_required: false,
              reason: "Audio is optional for this production plan.",
            },
          ],
        }}
        actingActionId={null}
        onApply={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "Add another" })).toBeNull();
    expect(screen.getByRole("button", { name: "Skip optional audio" })).toBeTruthy();
  });

  it("renders durable action acknowledgements without parsing assistant prose", () => {
    const receiptCard: ChatActionReceiptCardV2 = {
      item_type: "action_receipt",
      action_receipt: {
        receipt_id: "receipt-1",
        workflow_id: "workflow-1",
        plan_id: "plan-1",
        action_id: "turn-action-1",
        status: "applied_with_run_error",
        summary: "Created the revised image Draft.",
        created_node_ids: ["node-sibling-1"],
        updated_node_ids: [],
        deleted_node_ids: [],
        created_binding_ids: [],
        deleted_binding_ids: [],
        queued_execution_ids: [],
        run_queue_errors: ["The provider queue is temporarily unavailable."],
        operation_results: [],
        workflow_revision: 4,
        placement_hints: [{
          intent: "right_sibling",
          anchor_node_id: "node-1",
          group_key: null,
        }],
        continuation_turn_id: "turn-continuation-1",
        error_code: null,
        error_message: null,
      },
      sequence: 6,
      created_at: "2026-07-29T02:01:00Z",
    };

    render(<ActionReceiptCard card={receiptCard} />);

    expect(screen.getByText("Created the revised image Draft.")).toBeTruthy();
    expect(screen.getByText("The provider queue is temporarily unavailable.")).toBeTruthy();
    expect(screen.getByText("Planning continues automatically")).toBeTruthy();
  });

  it("shows specialist work as activity status rather than a specialist chat bubble", () => {
    const activity: ChatExpertActivityV2 = {
      item_type: "expert_activity",
      activity_id: "activity-1",
      turn_id: "turn-1",
      specialist: "scene_designer",
      label: "Scene Designer",
      operation: "create_concepts",
      status: "working",
      sequence: 4,
      started_at: "2026-07-29T02:00:00Z",
      finished_at: null,
    };
    render(<SpecialistActivityRow activity={activity} />);

    expect(screen.getByText("Scene Designer is working")).toBeTruthy();
  });
});
