import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GuidedInteractionV1 } from "../../../types-v2.ts";
import { ConceptChoiceDecisionDock } from "./ConceptChoiceDecisionDock.tsx";

const interaction: GuidedInteractionV1 = {
  interaction_id: "interaction-1",
  workflow_id: "workflow-1",
  session_id: "session-1",
  checkpoint_id: "checkpoint-1",
  kind: "concept_choice",
  status: "open",
  response_locale: "zh-CN",
  expected_session_revision: 4,
  revision: 2,
  title: "Choose a creative direction",
  context: "Pick the visual approach.",
  content: {
    content_kind: "concept_choice",
    proposal_id: "proposal-1",
    stage: "world_view",
    stage_revision: 4,
    action_id: "action-world-view-1",
    occurrence_id: "occurrence:world_view:1",
    capability_id: "world_setting",
    allow_custom: true,
    allow_exclusion: true,
    options: [
      { option_id: "option-a", title: "Warm", summary: "Warm and intimate.", difference_tags: [], recommended: true, reference_preview: [] },
      { option_id: "option-b", title: "Precise", summary: "Clean product precision.", difference_tags: [], recommended: false, reference_preview: [] },
      { option_id: "option-c", title: "Playful", summary: "Bright and energetic.", difference_tags: [], recommended: false, reference_preview: [] },
    ],
  },
  allowed_actions: ["select", "custom", "revise", "defer", "exclude", "delegate"],
  submit_path: "/api/v2/workflows/workflow-1/chat/interactions/interaction-1/submit",
  created_at: "2026-08-15T10:00:00Z",
  updated_at: "2026-08-15T10:00:00Z",
};

afterEach(cleanup);

describe("ConceptChoiceDecisionDock", () => {
  it("uses the task context as the single card title and omits the composer hint", () => {
    const interactionWithProposalTitle = {
      ...interaction,
      title: "Warm · Precise · Playful",
    };
    render(
      <ConceptChoiceDecisionDock
        interaction={interactionWithProposalTitle}
        pending={false}
        issue={null}
        selectedOptionId={null}
        onSelectOption={vi.fn()}
      />,
    );

    expect(screen.getAllByRole("radio")).toHaveLength(3);
    expect(screen.getByRole("article", { name: interaction.context })).toBeTruthy();
    expect(screen.getByText(interaction.context)).toBeTruthy();
    expect(screen.queryByText(interactionWithProposalTitle.title)).toBeNull();
    expect(screen.queryByText("Choose an option above, or describe your own direction below.")).toBeNull();
    expect(screen.queryByRole("button", { name: "References" })).toBeNull();
    expect(screen.queryByRole("button", { name: "More" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Submit/i })).toBeNull();
    expect(screen.queryByText("zh-CN")).toBeNull();
  });

  it("reports option selection without submitting", () => {
    const onSelectOption = vi.fn();
    render(
      <ConceptChoiceDecisionDock
        interaction={interaction}
        pending={false}
        issue={null}
        selectedOptionId={null}
        onSelectOption={onSelectOption}
      />,
    );

    fireEvent.click(screen.getByRole("radio", { name: /Warm/i }));
    expect(onSelectOption).toHaveBeenCalledWith("option-a");
  });

  it("renders the controlled selected state", () => {
    render(
      <ConceptChoiceDecisionDock
        interaction={interaction}
        pending={false}
        issue={null}
        selectedOptionId="option-b"
        onSelectOption={vi.fn()}
      />,
    );

    expect(screen.getByRole("radio", { name: /Precise/i }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radio", { name: /Warm/i }).getAttribute("aria-checked")).toBe("false");
  });

  it("locks options and keeps the issue visible while pending", () => {
    render(
      <ConceptChoiceDecisionDock
        interaction={interaction}
        pending
        issue={{ summary: "Try again.", detail: null, fieldId: null, retryable: true }}
        selectedOptionId="option-a"
        onSelectOption={vi.fn()}
      />,
    );

    expect(screen.getAllByRole("radio").every((control) => (control as HTMLButtonElement).disabled)).toBe(true);
    expect(screen.getByRole("alert").textContent).toContain("Try again.");
  });
});
