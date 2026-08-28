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
  PresentationStreamRow,
  TimelineHydrationSkeleton,
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
    const loader = document.querySelector<HTMLElement>('.agent-chat__working-loader[data-variant="halo"]');
    expect(loader).toBeTruthy();
    expect(loader?.style.getPropertyValue("--il-size")).toBe("20px");
    expect(document.querySelector(".agent-chat__working-spinner")).toBeNull();
  });

  it("announces model waiting as a non-terminal Agent activity", () => {
    render(<AgentWorkingRow waitingForModel />);

    expect(screen.getByRole("status", { name: "AdCraft Video Agent is waiting for the model" })).toBeTruthy();
    expect(screen.getByText("Waiting for model")).toBeTruthy();
    expect(document.querySelector('.agent-chat__working-loader[data-variant="halo"]')).toBeTruthy();
    expect(document.querySelector(".agent-chat__working-spinner")).toBeNull();
  });
});

describe("PresentationStreamRow", () => {
  afterEach(() => cleanup());

  it("renders only the safe incremental assistant text while the stream is open", () => {
    render(<PresentationStreamRow stream={{
      stream_id: "stream-1",
      status: "open",
      text: "The next production step is ready.",
      last_sequence_no: 2,
      stream_kind: "assistant",
      turn_id: "turn-1",
      node_id: null,
      authoritative_id: null,
      error_code: null,
      protocol_error: null,
      last_event_type: "delta",
      last_event: null,
    }} />);

    expect(screen.getByRole("status", { name: "AdCraft Video Agent is generating a response" })).toBeTruthy();
    expect(screen.getByText("The next production step is ready.")).toBeTruthy();
    expect(screen.getByText("Generating response")).toBeTruthy();
  });
});

describe("TimelineHydrationSkeleton", () => {
  afterEach(() => cleanup());

  it("keeps pointer-backed decisions visible while their details load", () => {
    render(<TimelineHydrationSkeleton itemType="proposal" />);

    expect(screen.getByRole("status", { name: "Loading proposal" })).toBeTruthy();
    expect(screen.getByText("Loading proposal…")).toBeTruthy();
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
    expect(screen.queryByText("Contemporary wardrobe")).toBeNull();
    expect(screen.queryByText("Confident posture")).toBeNull();
    expect(screen.queryByRole("button", { name: "Generate now" })).toBeNull();
  });

  it("keeps the Timeline proposal as concise read-only history", () => {
    render(
      <ProposalCard
        card={proposalCard}
        pending={false}
        readOnly
      />,
    );

    expect(screen.getByText("A focused campaign hero")).toBeTruthy();
    expect(screen.queryByText("Contemporary wardrobe")).toBeNull();
    expect(screen.queryByText("Confident posture")).toBeNull();
    expect(screen.queryByRole("button", { name: "Use this direction" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Revise options" })).toBeNull();
  });

  it("renders an applied Timeline proposal as a non-interactive option preview", () => {
    render(
      <ProposalCard
        card={{
          ...proposalCard,
          proposal: {
            ...proposalCard.proposal,
            availability: "applied",
            options: [
              proposalCard.proposal.options[0]!,
              {
                option_id: "option-2",
                title: "Everyday warmth",
                public_summary: "A familiar family moment with a calm domestic tone.",
                key_decisions: [],
              },
              {
                option_id: "option-3",
                title: "Natural sanctuary",
                public_summary: "A gentle world shaped by forests and morning light.",
                key_decisions: [],
              },
            ],
            application_count: 1,
            latest_application: {
              application_id: "application-1",
              option_id: "option-3",
              action: "select_option",
              receipt_id: "receipt-1",
              created_node_ids: ["node-character-1"],
              queued_execution_ids: [],
              created_at: "2026-08-04T00:01:00Z",
            },
            materialization: {
              materialization_id: "materialization-1",
              option_id: "option-1",
              turn_id: "turn-materialization-1",
              status: "completed",
              attempt_no: 1,
              retryable: false,
              error: null,
              created_at: "2026-08-04T00:01:00Z",
              updated_at: "2026-08-04T00:01:01Z",
            },
          },
        }}
        pending={false}
        readOnly
      />,
    );

    const selectedOption = screen.getByRole("article", { name: "Selected option: Natural sanctuary" });
    expect(selectedOption).toBeTruthy();
    expect(selectedOption.textContent).not.toContain("Selected");
    expect(screen.queryByText("Selected")).toBeNull();
    expect(screen.getByText("A")).toBeTruthy();
    expect(screen.getByText("B")).toBeTruthy();
    expect(screen.getByText("C")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Natural sanctuary/ })).toBeNull();
    expect(screen.queryByText(/Applied 1 time/)).toBeNull();
    expect(screen.queryByRole("status", { name: "Proposal materialization completed" })).toBeNull();
  });

  it("shows an optimistic selection in the historical proposal card", () => {
    render(
      <ProposalCard
        card={proposalCard}
        pending
        readOnly
        optimisticSelectedOptionId="option-1"
      />,
    );

    expect(screen.getByRole("article", { name: "Selected option: Hero" })).toBeTruthy();
  });

  it("renders historical option markers without circular chrome", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const markerRule = css.match(/\.agent-chat__historical-option-marker\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(markerRule).toBeTruthy();
    expect(markerRule).not.toContain("border:");
    expect(markerRule).not.toContain("border-radius:");
    expect(markerRule).toContain("font-size: 11px");
  });

  it("defines a visible selected state for interactive proposal options", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const selectedRule = css.match(/\.agent-chat__proposal-option\.is-selected\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(selectedRule).toBeTruthy();
    expect(selectedRule).toContain("border:");
    expect(selectedRule).toContain("background:");
    expect(selectedRule).toContain("box-shadow:");
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
    const onRetryMaterialization = vi.fn().mockResolvedValue(true);
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
        onRetryMaterialization={onRetryMaterialization}
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
        onRetryMaterialization={onRetryMaterialization}
      />,
    );

    expect(screen.getByText("The selected direction could not be prepared.")).toBeTruthy();
    expect(screen.getByText("Hero reference")).toBeTruthy();
    expect((screen.getByRole("checkbox", { name: "Required" }) as HTMLInputElement).checked).toBe(false);
    expect((screen.getByRole("button", { name: "Use this direction" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Revise options" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Retry draft creation" }));
    expect(onRetryMaterialization).toHaveBeenCalledWith("turn-materialization-1");
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
    expect(screen.queryByRole("button", { name: "Retry draft creation" })).toBeNull();
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

  it("does not expose legacy custom-direction actions on Timeline history", () => {
    render(
      <ProposalCard
        card={{
          ...proposalCard,
          proposal: {
            ...proposalCard.proposal,
            actions: [
              ...proposalCard.proposal.actions,
              proposalAction(
                "custom_direction",
                "Use a custom direction",
              ),
            ],
          },
        }}
        pending={false}
        readOnly
      />,
    );

    expect(screen.queryByRole("textbox", { name: "Custom creative direction" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Use a custom direction" })).toBeNull();
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
      journey: {
        policy_version: "fixed_ad_production_v2",
        stage: "scene",
        stage_status: "waiting_user",
        stage_revision: 4,
        decisions: [{
          decision_id: "decision:scene:1",
          element_kind: "scene",
          occurrence_id: "occurrence:scene:1",
          occurrence_index: 1,
          outcome: "unresolved",
          source: "user",
          source_revision: 1,
          requirements: {},
        }],
        active_occurrence_id: "occurrence:scene:1",
        active_action: null,
        suspended_action: null,
        transition_evidence: [],
      },
      revision: 7,
      updated_at: "2026-08-04T00:00:00Z",
    };

    const { rerender } = render(<GuidanceSessionProgress session={session} />);

    expect(screen.getByText("Create a launch film.")).toBeTruthy();
    expect(screen.getByText("Scene · waiting user")).toBeTruthy();
    expect(screen.getByText("Creative 4/5")).toBeTruthy();
    expect(screen.getByText("Storyboard 0/4")).toBeTruthy();
    expect(screen.getByText("Delivery 0/3")).toBeTruthy();
    expect(screen.queryByText("Authoring: not ready")).toBeNull();
    expect(screen.queryByText("Direction: You")).toBeNull();
    expect(screen.queryByText("Current decision: scene 1 · unresolved")).toBeNull();

    rerender(<GuidanceSessionProgress session={{
      ...session,
      journey: {
        ...session.journey,
        stage: "completed",
        stage_status: "completed",
      },
    }} />);
    expect(screen.getByText("Completed")).toBeTruthy();
    expect(screen.queryByText("Completed · completed")).toBeNull();
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

    expect(screen.getByRole("status", { name: "Scene Designer is working" })).toBeTruthy();
    expect(screen.getByText("Scene Designer")).toBeTruthy();
    expect(screen.getByText("Working")).toBeTruthy();
    expect(document.querySelector<HTMLImageElement>('[data-testid="agent-capability-icon"]')?.getAttribute("src"))
      .toBe("/imgs/agent-role-icons/scene-designer.png");
    expect(screen.queryByText("AdCraft Video Agent", { exact: false })).toBeNull();
  });

  it("separates the Agent identity header from its response content", () => {
    render(<CapabilityActivityRow activity={{
      item_type: "expert_activity",
      activity_id: "activity-content-separation",
      turn_id: "turn-content-separation",
      capability_id: "product_design",
      capability_display_name: "Product Designer",
      status: "completed",
      sequence: 5,
      started_at: "2026-08-27T00:00:00Z",
      finished_at: "2026-08-27T00:01:00Z",
      presentation_text: "The product language is ready for the next stage.",
      message: null,
      error_code: null,
      elapsed_ms: 60_000,
      attempt_stage: null,
      retryable: false,
      validation_paths: [],
      suggested_actions: [],
      completion_mode: null,
      warning_code: null,
    }} />);

    const identity = document.querySelector(".agent-chat__capability-identity");
    const content = document.querySelector(".agent-chat__activity-content");
    expect(identity).toBeTruthy();
    expect(content).toBeTruthy();
    expect(identity?.textContent ?? "").toContain("Product Designer");
    expect(content?.textContent ?? "").toContain("The product language is ready for the next stage.");
    expect(identity && content?.contains(identity)).toBe(false);
  });

  it("renders nested capability activity as a compact record without its duplicate identity icon", () => {
    render(<CapabilityActivityRow
      compact
      activity={{
        item_type: "expert_activity",
        activity_id: "activity-compact",
        turn_id: "turn-compact",
        capability_id: "product_design",
        capability_display_name: "Product Designer",
        status: "completed",
        sequence: 6,
        started_at: "2026-08-27T00:00:00Z",
        finished_at: "2026-08-27T00:01:00Z",
        presentation_text: "The product direction is ready.",
        message: null,
        error_code: null,
        elapsed_ms: 60_000,
        attempt_stage: null,
        retryable: false,
        validation_paths: [],
        suggested_actions: [],
        completion_mode: null,
        warning_code: null,
      }}
    />);

    expect(document.querySelector('[data-testid="agent-capability-icon"]')).toBeNull();
    expect(document.querySelector(".agent-chat__compact-capability-heading")?.textContent)
      .toContain("Product Designer");
    expect(screen.getByText("The product direction is ready.")).toBeTruthy();
  });

  it("puts the matching role icon before an interactive capability proposal", () => {
    render(
      <ProposalCard
        card={proposalCard}
        pending={false}
        onSelect={vi.fn()}
        onRevise={vi.fn()}
        onApplyAction={vi.fn()}
      />,
    );

    expect(document.querySelector<HTMLImageElement>('[data-testid="agent-capability-icon"]')?.getAttribute("src"))
      .toBe("/imgs/agent-role-icons/character-designer.png");
  });

  it("renders nested proposal history without repeating the capability identity icon", () => {
    render(
      <ProposalCard
        card={proposalCard}
        pending={false}
        readOnly
        compact
      />,
    );

    expect(document.querySelector('[data-testid="agent-capability-icon"]')).toBeNull();
    expect(document.querySelector(".agent-chat__compact-capability-heading")?.textContent)
      .toContain("Character Designer");
  });

  it.each([
    ["World Setting", "World Setting 已完成。"],
    ["Product Designer", "Product Designer finished."],
  ])("hides the redundant completion body for %s", (_capability, redundantBody) => {
    render(<CapabilityActivityRow activity={{
      item_type: "expert_activity",
      activity_id: `activity-redundant-${_capability}`,
      turn_id: `turn-redundant-${_capability}`,
      capability_id: "world_setting",
      capability_display_name: _capability,
      status: "completed",
      sequence: 7,
      started_at: "2026-08-27T00:00:00Z",
      finished_at: "2026-08-27T00:01:00Z",
      presentation_text: redundantBody,
      message: null,
      error_code: null,
      elapsed_ms: 60_000,
      attempt_stage: null,
      retryable: false,
      validation_paths: [],
      suggested_actions: [],
      completion_mode: null,
      warning_code: null,
    }} />);

    expect(screen.getByText("Completed")).toBeTruthy();
    expect(screen.queryByText(redundantBody)).toBeNull();
  });

  it("presents backend activity duration and explanation as a compact section", () => {
    render(<CapabilityActivityRow activity={{
      item_type: "expert_activity",
      activity_id: "activity-completed",
      turn_id: "turn-completed",
      capability_id: "creative_direction",
      capability_display_name: "Creative Direction",
      status: "completed",
      sequence: 8,
      started_at: "2026-08-27T00:00:00Z",
      finished_at: "2026-08-27T00:01:04Z",
      presentation_text: "Visual language locked for the next production stage.",
      message: null,
      error_code: null,
      elapsed_ms: 64_000,
      attempt_stage: null,
      retryable: false,
      validation_paths: [],
      suggested_actions: [],
      completion_mode: null,
      warning_code: null,
    }} />);

    expect(screen.getByRole("status", { name: "Creative Direction completed" })).toBeTruthy();
    expect(screen.getByText("Completed")).toBeTruthy();
    expect(screen.getByText("for 1m 4s")).toBeTruthy();
    expect(screen.getByText("Visual language locked for the next production stage.")).toBeTruthy();
  });

  it("shows text generation feedback only while capability work is active", () => {
    const activity: ChatCapabilityActivityV2 = {
      item_type: "expert_activity",
      activity_id: "activity-loader",
      turn_id: "turn-loader",
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

    const { rerender } = render(<CapabilityActivityRow activity={activity} />);

    expect(screen.getByText("Preparing the next response...")).toBeTruthy();

    rerender(<CapabilityActivityRow activity={{
      ...activity,
      status: "completed",
      finished_at: "2026-08-04T00:01:00Z",
    }} />);

    expect(screen.queryByText("Preparing the next response...")).toBeNull();

    rerender(<CapabilityActivityRow activity={{
      ...activity,
      status: "failed",
      finished_at: "2026-08-04T00:02:00Z",
      message: "The capability request failed.",
      error_code: "agent_failed",
    }} />);

    expect(screen.queryByText("Preparing the next response...")).toBeNull();
  });

  it("shows a superseded capability as replaced progress rather than a failure", () => {
    render(<CapabilityActivityRow activity={{
      item_type: "expert_activity",
      activity_id: "activity-storyboard-1",
      turn_id: "turn-storyboard-1",
      capability_id: "storyboard_design",
      capability_display_name: "Storyboard Artist",
      status: "superseded",
      sequence: 43,
      started_at: "2026-08-21T06:17:00Z",
      finished_at: "2026-08-21T06:18:00Z",
      message: null,
      error_code: "guidance_revision_conflict",
      elapsed_ms: 60000,
      attempt_stage: "initial",
      retryable: true,
      validation_paths: [],
      suggested_actions: ["retry", "revise_request"],
      completion_mode: null,
      warning_code: null,
    }} onRetry={vi.fn()} onReviseRequest={vi.fn()} />);

    expect(screen.getByText("Storyboard Artist was superseded by later progress")).toBeTruthy();
    expect(screen.queryByText(/failed/i)).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
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

    expect(screen.queryByText("agent_deadline_exceeded")).toBeNull();
    fireEvent.click(screen.getByText("Technical details"));
    expect(screen.getByText(/agent_deadline_exceeded/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry Scene Designer activity" }));
    fireEvent.click(screen.getByRole("button", { name: "Revise Scene Designer request" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onReviseRequest).toHaveBeenCalledTimes(1);
  });

  it("disables a failed activity retry while its recovery turn is working", () => {
    render(<CapabilityActivityRow activity={{
      item_type: "expert_activity",
      activity_id: "activity-retrying",
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
      suggested_actions: ["retry"],
      completion_mode: null,
      warning_code: null,
    }} onRetry={vi.fn()} retrying />);

    expect((screen.getByRole("button", {
      name: "Retry Scene Designer activity",
    }) as HTMLButtonElement).disabled).toBe(true);
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
    expect(screen.getByRole("button", { name: "Skill" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Resize AdCraft Video Agent panel" })).toBeTruthy();
  });

  it("pins the current review outside history immediately above the composer", () => {
    const panelPath = resolve(process.cwd(), "src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx");
    const panelSource = readFileSync(panelPath, "utf8");
    const timelineItemsIndex = panelSource.indexOf("{stageTimeline.map((unit) => {");
    const timelineShellIndex = panelSource.indexOf('<div className="agent-chat__timeline-shell">');
    const pinnedInteractionIndex = panelSource.indexOf('<div className="agent-chat__current-interaction"');
    const composerIndex = panelSource.indexOf('<div className="agent-chat__composer">');

    expect(timelineItemsIndex).toBeGreaterThan(-1);
    expect(pinnedInteractionIndex).toBeGreaterThan(timelineShellIndex);
    expect(pinnedInteractionIndex).toBeGreaterThan(timelineItemsIndex);
    expect(composerIndex).toBeGreaterThan(pinnedInteractionIndex);
  });

  it("uses the approved monochrome fixed chat rail with plain Agent replies", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const panelRule = css.match(/^\.agent-chat\s*\{([\s\S]*?)\n\}/m)?.[1];
    const userMessageContainerRule = css.match(/\.agent-chat__message--user\s*\{([\s\S]*?)\n\}/m)?.[1];
    const agentMessageRule = css.match(/\.agent-chat__message--agent\s*:\s*is\(p, \.agent-chat__markdown\)\s*\{([\s\S]*?)\n\}/m)?.[1];
    const userMessageBodyRule = css.match(/\.agent-chat__message--user \.agent-chat__message-body\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(panelRule).toContain("top: 0");
    expect(panelRule).toContain("right: 0");
    expect(panelRule).toContain("bottom: 0");
    expect(panelRule).toContain("max-width: min(720px, calc(100vw - 24px));");
    expect(panelRule).toContain("--agent-chat-canvas: #0a0a0a");
    expect(panelRule).toContain("--agent-chat-panel: #151515");
    expect(panelRule).toContain("--agent-chat-raised: #202020");
    expect(panelRule).toContain("--agent-chat-border: #353535");
    expect(panelRule).toContain("--agent-chat-strong-line: #4a4a4a");
    expect(panelRule).toContain("--agent-chat-primary: #f5f5f5");
    expect(panelRule).toContain("--agent-chat-secondary: #a3a3a3");
    expect(panelRule).toContain("--agent-chat-muted: #707070");
    expect(panelRule).toContain("background: var(--agent-chat-panel)");
    expect(panelRule).toContain("backdrop-filter: none");
    expect(panelRule).toContain("border-radius: 0");
    expect(css).toMatch(/\.agent-chat__message--agent > span\s*\{\s*display: none;/);
    expect(userMessageContainerRule).toContain("width: fit-content");
    expect(userMessageContainerRule).toContain("max-width: min(86%, 520px)");
    expect(agentMessageRule).toContain("padding: 0");
    expect(agentMessageRule).toContain("background: transparent");
    expect(userMessageBodyRule).toContain("background: var(--agent-chat-raised)");
    expect(css).toContain(".agent-chat__resize-handle");
    expect(css).toContain("cursor: ew-resize");
  });

  it("aligns user message containers to the right inside conversation locations", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const userMessageContainerRule = css.match(/\.agent-chat__message--user\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(userMessageContainerRule).toContain("justify-self: end");
  });

  it("keeps historical capability names smaller than the stage thread identity", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const compactHeadingRule = css.match(/\.agent-chat__compact-capability-heading\s+strong\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(css).toMatch(/\.agent-chat__activity:not\(\.is-compact\)\s*>\s*header\s+strong\s*\{/);
    expect(compactHeadingRule).toContain("font-size: 11px");
  });

  it("styles View on canvas as a white physical action button", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const canvasActionRule = css.match(/\.agent-chat\s+\.agent-chat__node-links--result\s*>\s*button\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(canvasActionRule).toContain("background: #fff");
    expect(canvasActionRule).toContain("color: black");
    expect(canvasActionRule).toContain("font-family: inherit");
    expect(canvasActionRule).toContain("padding: 0.35em 0.8em");
    expect(canvasActionRule).toContain("font-weight: 900");
    expect(canvasActionRule).toContain("font-size: 10px");
    expect(canvasActionRule).toContain("border: 1px solid black");
    expect(canvasActionRule).toContain("box-shadow: 0.18em 0.18em;");
    expect(canvasActionRule).toContain("cursor: pointer");
    expect(css).toMatch(/\.agent-chat\s+\.agent-chat__node-links--result\s*>\s*button:hover\s*\{[\s\S]*?transform: translate\(-0\.05em, -0\.05em\);[\s\S]*?box-shadow: 0\.24em 0\.24em;/m);
    expect(canvasActionRule).toContain("transition: none");
    expect(css).toMatch(/\.agent-chat\s+\.agent-chat__node-links--result\s*>\s*button:active:not\(:disabled\):not\(\[aria-disabled="true"\]\)\s*\{[\s\S]*?transform: translate\(0\.05em, 0\.05em\);[\s\S]*?box-shadow: 0\.1em 0\.1em;/m);
  });

  it("styles Stage Threads as quiet monochrome timeline sections", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const threadRule = css.match(/\.agent-chat__stage-thread\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(threadRule).toContain("border-top: 1px solid var(--agent-chat-border)");
    expect(threadRule).toContain("background: transparent");
    expect(css).not.toContain(".agent-chat__stage-thread-summary");
    expect(css).toContain("--agent-chat-selected: #292929");
    expect(css).toMatch(/\.agent-chat__stage-thread > header span\s*\{[^}]*color: var\(--agent-chat-secondary\)/s);
    expect(css).toMatch(/\.agent-chat__progress-groups span\s*\{[^}]*color: var\(--agent-chat-secondary\)/s);
  });

  it("keeps the full capability identity only on the Stage Thread header", () => {
    const panelPath = resolve(process.cwd(), "src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx");
    const panelSource = readFileSync(panelPath, "utf8");

    expect(panelSource).toMatch(
      /unit\.activities\.map\(\(activity\) => renderTimelineItem\(\s*activity,\s*null,\s*\{\s*compactCapability:\s*true,?\s*\},?\s*\)\)\}/,
    );
    expect(panelSource).toMatch(
      /unit\.proposals\.map\(\(proposal\) => renderTimelineItem\(\s*proposal,\s*null,\s*\{\s*compactCapability:\s*true,?\s*\},?\s*\)\)\}/,
    );
    expect(panelSource).toMatch(/<StageThread\s+\n?\s+unit=\{unit\}/);
  });

  it("uses one scrolling monochrome Decision Dock surface", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const currentInteractionRule = css.match(/\.agent-chat__current-interaction\s*\{([\s\S]*?)\n\}/m)?.[1];
    const currentInteractionDockRule = css.match(/\.agent-chat__current-interaction\s*>\s*\.agent-chat__decision-dock\s*\{([\s\S]*?)\n\}/m)?.[1];
    const optionsRule = css.match(/\.agent-chat__decision-dock-options\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(css).toContain(".agent-chat__decision-dock");
    expect(css).toContain(".agent-chat__decision-dock-body");
    expect(css).toContain(".agent-chat__decision-dock-footer");
    expect(css).toContain("max-height: min(50vh, 480px)");
    expect(css).toContain("overflow-y: auto");
    expect(css).toMatch(/\.agent-chat__proposal-option:not\(\.is-selected\)[\s\S]*-webkit-line-clamp: 2/);
    expect(css).toMatch(/\.agent-chat__proposal-option\.is-selected[\s\S]*border-color: var\(--agent-chat-primary\)/);
    expect(css).toMatch(/\.agent-chat__decision-dock-header strong\s*\{[^}]*font-size: 13px/s);
    expect(css).toMatch(/\.agent-chat__decision-dock-header p\s*\{[^}]*font-size: 12px/s);
    expect(css).toMatch(/\.agent-chat__proposal-option-copy strong\s*\{[^}]*font-size: 13px/s);
    expect(css).toMatch(/\.agent-chat__proposal-option-copy > span\s*\{[^}]*font-size: 12px/s);
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*\.agent-chat__decision-dock/);
    expect(css).not.toContain(".agent-chat__guided-proposal-intro");
    expect(css).not.toContain("#e6a34a");
    expect(css).not.toContain("#77c9c2");
    expect(currentInteractionRule).toContain("overflow: hidden");
    expect(currentInteractionRule).not.toContain("overflow-y: auto");
    expect(currentInteractionRule).toContain("display: flex");
    expect(currentInteractionDockRule).toContain("max-height: 100%");
    expect(currentInteractionDockRule).toContain("flex: 1 1 auto");
    expect(optionsRule).toContain("min-height: max-content");
  });

  it("keeps recovery and message context as bounded monochrome Shell regions", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const panelRule = css.match(/^\.agent-chat\s*\{([\s\S]*?)\n\}/m)?.[1];
    const timelineRule = css.match(/\.agent-chat__timeline\s*\{([\s\S]*?)\n\}/m)?.[1];
    const recoveryRule = css.match(/\.agent-chat__recovery\s*\{([\s\S]*?)\n\}/m)?.[1];
    const trayRule = css.match(/\.agent-chat__context-tray\s*\{([\s\S]*?)\n\}/m)?.[1];
    const trayGroupsRule = css.match(/\.agent-chat__context-groups\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(panelRule).toContain("display: flex");
    expect(panelRule).toContain("flex-direction: column");
    expect(panelRule).toContain("overflow: hidden");
    expect(timelineRule).toContain("overflow-y: auto");
    expect(recoveryRule).toContain("background: var(--agent-chat-raised)");
    expect(recoveryRule).not.toMatch(/gradient|#[0-9a-f]{3,8}/i);
    expect(trayRule).toContain("max-height: min(28vh, 230px)");
    expect(trayRule).toContain("overflow: hidden");
    expect(trayGroupsRule).toContain("overflow-y: auto");
    expect(css).toMatch(/@media \(max-width: 350px\)[\s\S]*\.agent-chat__mention-menu[\s\S]*grid-template-columns: minmax\(0, 1fr\)/);
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*\.agent-chat__recovery[\s\S]*\.agent-chat__context-tray/);
  });

  it("gives natural messages readable markdown and explicit long-content controls", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const collapsedRule = css.match(/\.agent-chat__message-body\.is-collapsed\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(collapsedRule).toContain("max-height: calc(1.58em * 8)");
    expect(collapsedRule).toContain("overflow: hidden");
    expect(css).toMatch(/\.agent-chat__markdown pre\s*\{[^}]*overflow-x: auto/s);
    expect(css).toMatch(/\.agent-chat__markdown a\s*\{[^}]*overflow-wrap: anywhere/s);
    expect(css).toMatch(/\.agent-chat__message-meta time\s*\{[^}]*opacity: 0/s);
  });

  it("keeps semantic states and the Style selector inside the monochrome palette", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const errorRule = css.match(/\.agent-chat__error\s*\{([\s\S]*?)\n\}/m)?.[1];
    const noticeRule = css.match(/\.agent-chat__notice\s*\{([\s\S]*?)\n\}/m)?.[1];
    const selectedStyleRule = css.match(/\.agent-chat__style-menu \.agent-chat__style-option\.is-selected\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(errorRule).toContain("border-color: var(--agent-chat-strong-line)");
    expect(errorRule).toContain("color: var(--agent-chat-primary)");
    expect(noticeRule).toContain("color: var(--agent-chat-secondary)");
    expect(selectedStyleRule).toContain("border-color: var(--agent-chat-primary)");
    expect(css).not.toContain("#e6a34a");
    expect(css).not.toContain("#77c9c2");
  });

  it("disables chat presentation motion when reduced motion is requested", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const reducedMotion = css.match(/@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*)\}\s*$/m)?.[1];

    expect(reducedMotion).toContain(".agent-chat__message");
    expect(reducedMotion).toContain(".agent-chat__activity");
    expect(reducedMotion).toContain("animation: none !important");
  });

  it("separates the fixed header from the scrolling timeline", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const headerRule = css.match(/\.agent-chat__header\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(headerRule).toContain("border-bottom: 1px solid var(--agent-chat-border)");
  });

  it("does not include the retired React Flow Mini Map chrome", () => {
    const pagePath = resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPageSurface.tsx");
    const pageSource = readFileSync(pagePath, "utf8");
    const canvasCssPath = resolve(process.cwd(), "src/features/agent-canvas/agent-canvas-page.css");
    const canvasCss = readFileSync(canvasCssPath, "utf8");

    expect(pageSource).not.toMatch(/\bMiniMap\b/);
    expect(canvasCss).not.toContain(".react-flow__minimap");
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
