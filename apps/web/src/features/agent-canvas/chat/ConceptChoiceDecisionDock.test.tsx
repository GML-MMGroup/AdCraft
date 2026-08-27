import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GuidedInteractionV1, ProposedDraftReferenceV2 } from "../../../types-v2.ts";
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
    proposal_id: null,
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

const proposalReferences: ProposedDraftReferenceV2[] = [
  {
    source_kind: "node",
    source_id: "node-character",
    binding_kind: "image_reference",
    input_role: "visual_reference",
    required: true,
    display_order: 0,
    semantic_reference_role: "subject_reference",
    display_name: "Character turnaround",
    media_type: "image",
  },
  {
    source_kind: "node",
    source_id: "node-scene",
    binding_kind: "image_reference",
    input_role: "visual_reference",
    required: false,
    display_order: 1,
    semantic_reference_role: "environment_reference",
    display_name: "Scene board",
    media_type: "image",
  },
];

afterEach(cleanup);

describe("ConceptChoiceDecisionDock", () => {
  it("shows options directly, expands selection, and submits the existing payload", () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(
      <ConceptChoiceDecisionDock
        interaction={interaction}
        pending={false}
        issue={null}
        proposalReferences={[]}
        referenceMediaUrls={{}}
        onSubmit={submit}
      />,
    );

    expect(screen.getAllByRole("radio")).toHaveLength(3);
    expect(screen.queryByText("zh-CN")).toBeNull();
    expect(screen.queryByText("3 options")).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: /Warm/i }));
    expect(screen.getByText("Selected: Warm")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Submit selection" }));

    expect(submit).toHaveBeenCalledWith({
      submission_kind: "concept_choice",
      expected_interaction_revision: 2,
      expected_session_revision: 4,
      action: "select",
      option_id: "option-a",
      custom_text: null,
    });
  });

  it("keeps references collapsed and submits accepted references in canonical order", () => {
    const submit = vi.fn().mockResolvedValue(true);
    const withProposal: GuidedInteractionV1 = {
      ...interaction,
      content: interaction.content.content_kind === "concept_choice"
        ? { ...interaction.content, proposal_id: "proposal-1" }
        : interaction.content,
    };
    render(
      <ConceptChoiceDecisionDock
        interaction={withProposal}
        pending={false}
        issue={null}
        proposalReferences={proposalReferences}
        referenceMediaUrls={{}}
        onSubmit={submit}
      />,
    );

    expect(screen.queryByText("Character turnaround")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "References · 2" }));
    expect(screen.getByText("Character turnaround")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /Warm/i }));
    fireEvent.click(screen.getByRole("button", { name: "Submit selection" }));

    expect(submit).toHaveBeenCalledWith(expect.objectContaining({
      action: "select",
      accepted_references: proposalReferences,
    }));
  });

  it("preserves the selected option while submitting a custom direction", () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(
      <ConceptChoiceDecisionDock
        interaction={interaction}
        pending={false}
        issue={null}
        proposalReferences={[]}
        referenceMediaUrls={{}}
        onSubmit={submit}
      />,
    );

    const warm = screen.getByRole("radio", { name: /Warm/i });
    fireEvent.click(warm);
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.click(screen.getByRole("button", { name: "Custom direction" }));
    expect(warm.getAttribute("aria-checked")).toBe("true");
    fireEvent.change(screen.getByRole("textbox", { name: "Custom direction" }), {
      target: { value: "  Restrained monochrome movement  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit direction" }));

    expect(submit).toHaveBeenCalledWith({
      submission_kind: "concept_choice",
      expected_interaction_revision: 2,
      expected_session_revision: 4,
      action: "custom",
      option_id: null,
      custom_text: "Restrained monochrome movement",
    });
  });

  it.each([
    ["Exclude this stage", "Confirm exclusion", "exclude"],
    ["Defer this stage", "Confirm defer", "defer"],
    ["Let Agent decide", "Confirm delegation", "delegate"],
  ] as const)("requires confirmation for %s", (actionLabel, confirmLabel, action) => {
    const submit = vi.fn().mockResolvedValue(true);
    render(
      <ConceptChoiceDecisionDock
        interaction={interaction}
        pending={false}
        issue={null}
        proposalReferences={[]}
        referenceMediaUrls={{}}
        onSubmit={submit}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.click(screen.getByRole("button", { name: actionLabel }));
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: confirmLabel }));
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ action }));
  });

  it("does not expose unsupported revise and waits for proposal references", () => {
    render(
      <ConceptChoiceDecisionDock
        interaction={interaction}
        pending={false}
        issue={null}
        proposalReferences={null}
        referenceMediaUrls={{}}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );

    fireEvent.click(screen.getByRole("radio", { name: /Warm/i }));
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    expect(screen.queryByRole("button", { name: /Revise/i })).toBeNull();
    expect(screen.getByText("Preparing references")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Submit selection" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("locks every control while pending and retains the selection and issue", () => {
    const { rerender } = render(
      <ConceptChoiceDecisionDock
        interaction={interaction}
        pending={false}
        issue={null}
        proposalReferences={[]}
        referenceMediaUrls={{}}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );
    fireEvent.click(screen.getByRole("radio", { name: /Warm/i }));

    rerender(
      <ConceptChoiceDecisionDock
        interaction={interaction}
        pending
        issue={{ summary: "Try again.", detail: null, fieldId: null, retryable: true }}
        proposalReferences={[]}
        referenceMediaUrls={{}}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );

    expect(screen.getByRole("radio", { name: /Warm/i }).getAttribute("aria-checked")).toBe("true");
    expect((screen.getByRole("radio", { name: /Warm/i }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "More" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("alert").textContent).toContain("Try again.");
    expect((screen.getByRole("button", { name: "Submitting" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
