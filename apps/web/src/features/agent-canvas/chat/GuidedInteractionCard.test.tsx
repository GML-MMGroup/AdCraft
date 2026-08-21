import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GuidedInteractionV1, ProposedDraftReferenceV2 } from "../../../types-v2.ts";
import { GuidedInteractionCard } from "./GuidedInteractionCard.tsx";

const interaction: GuidedInteractionV1 = {
  interaction_id: "interaction-1", workflow_id: "workflow-1", session_id: "session-1", checkpoint_id: "checkpoint-1",
  kind: "concept_choice", status: "open", response_locale: "zh-CN", expected_session_revision: 4, revision: 2,
  title: "Choose a direction", context: "Pick the visual approach.",
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
    { option_id: "option-a", title: "Warm", summary: "Warm and intimate.", difference_tags: ["warm"], recommended: true, reference_preview: [] },
    { option_id: "option-b", title: "Precise", summary: "Clean product precision.", difference_tags: ["clean"], recommended: false, reference_preview: [] },
    { option_id: "option-c", title: "Playful", summary: "Bright and energetic.", difference_tags: ["bright"], recommended: false, reference_preview: [] },
  ] },
  allowed_actions: ["select", "custom", "exclude", "delegate"], submit_path: "/api/v2/workflows/workflow-1/chat/interactions/interaction-1/submit",
  created_at: "2026-08-15T10:00:00Z", updated_at: "2026-08-15T10:00:00Z",
};

const proposalReferences: ProposedDraftReferenceV2[] = [{
  source_kind: "node",
  source_id: "node-character-turnaround",
  binding_kind: "image_reference",
  input_role: "visual_reference",
  required: true,
  display_order: 0,
  semantic_reference_role: "subject_reference",
  display_name: "Soft Guardian Mother - Three-view",
  media_type: "image",
}, {
  source_kind: "node",
  source_id: "node-scene-board",
  binding_kind: "image_reference",
  input_role: "visual_reference",
  required: true,
  display_order: 1,
  semantic_reference_role: "environment_reference",
  display_name: "Dawn Forest Edge Reference Board",
  media_type: "image",
}];

afterEach(cleanup);

describe("GuidedInteractionCard", () => {
  it("keeps a selection local until explicit Submit and sends revision-bound structured input", async () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(<GuidedInteractionCard interaction={interaction} pending={false} onSubmit={submit} />);
    fireEvent.click(screen.getByRole("button", { name: /Warm/i }));
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(submit).toHaveBeenCalledWith({
      submission_kind: "concept_choice",
      expected_interaction_revision: 2,
      expected_session_revision: 4,
      action: "select",
      option_id: "option-a",
      custom_text: null,
    });
  });

  it("shows required Proposal references and submits them with the selected option", () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(
      <GuidedInteractionCard
        interaction={{
          ...interaction,
          content: interaction.content.content_kind === "concept_choice"
            ? { ...interaction.content, proposal_id: "proposal-storyboard-1" }
            : interaction.content,
        }}
        pending={false}
        proposalReferences={proposalReferences}
        referenceMediaUrls={{
          "node:node-character-turnaround": "/api/v2/assets/asset-character/content",
          "node:node-scene-board": "/api/v2/assets/asset-scene/content",
        }}
        onSubmit={submit}
      />,
    );

    expect(screen.getByText("Soft Guardian Mother - Three-view")).toBeTruthy();
    expect(screen.getByText("Dawn Forest Edge Reference Board")).toBeTruthy();
    expect(screen.getAllByText("Required")).toHaveLength(2);
    expect(screen.getByRole("img", {
      name: "Soft Guardian Mother - Three-view",
    }).getAttribute("src")).toBe("/api/v2/assets/asset-character/content");

    fireEvent.click(screen.getByRole("button", { name: /Warm/i }));
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(submit).toHaveBeenCalledWith({
      submission_kind: "concept_choice",
      expected_interaction_revision: 2,
      expected_session_revision: 4,
      action: "select",
      option_id: "option-a",
      custom_text: null,
      accepted_references: proposalReferences,
    });
  });

  it("does not submit a selected option before its Proposal references are available", () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(
      <GuidedInteractionCard
        interaction={{
          ...interaction,
          content: interaction.content.content_kind === "concept_choice"
            ? { ...interaction.content, proposal_id: "proposal-storyboard-1" }
            : interaction.content,
        }}
        pending={false}
        proposalReferences={null}
        onSubmit={submit}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Warm/i }));

    expect(screen.getByRole("status", { name: "Loading proposal references" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "Submit" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(submit).not.toHaveBeenCalled();
  });

  it("shows the backend recommendation and submits a custom choice only from the shared Submit", () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(<GuidedInteractionCard interaction={interaction} pending={false} onSubmit={submit} />);

    expect(screen.getByText("Recommended")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Warm/i }));
    fireEvent.change(screen.getByPlaceholderText("Describe your direction"), {
      target: { value: "A restrained monochrome world" },
    });
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({
      action: "custom",
      custom_text: "A restrained monochrome world",
    }));
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it("keeps exclusion local until the shared Submit", () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(<GuidedInteractionCard interaction={interaction} pending={false} onSubmit={submit} />);

    fireEvent.click(screen.getByRole("button", { name: "Exclude this stage" }));
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ action: "exclude" }));
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it("shows only concise public option content", () => {
    render(<GuidedInteractionCard
      interaction={{
        ...interaction,
        content: interaction.content.content_kind === "concept_choice"
          ? {
              ...interaction.content,
              options: interaction.content.options.map((option, index) => ({
                ...option,
                difference_tags: [`internal-decision-${index + 1}`],
                reference_preview: [{
                  source_kind: "image_asset" as const,
                  source_id: `asset-${index + 1}`,
                  display_name: `Internal reference ${index + 1}`,
                  media_type: "image" as const,
                }],
              })),
            }
          : interaction.content,
      }}
      pending={false}
      onSubmit={vi.fn().mockResolvedValue(true)}
    />);

    expect(screen.getAllByRole("button", { name: /Warm|Precise|Playful/ })).toHaveLength(3);
    expect(screen.queryByText("internal-decision-1")).toBeNull();
    expect(screen.queryByText("Internal reference 1")).toBeNull();
  });
});
