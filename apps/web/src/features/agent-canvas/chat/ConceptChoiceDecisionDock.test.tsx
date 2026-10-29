import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "../../../i18n/locale.tsx";
import type { GuidedInteractionV1 } from "../../../types-v2.ts";
import { isBrandCustomInputCard } from "../model/brandCustomInput.ts";
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

function brandInteraction(optionCount = 3): GuidedInteractionV1 {
  const options = interaction.content.content_kind === "concept_choice" ? interaction.content.options : [];
  return {
    ...interaction,
    content: {
      ...interaction.content,
      content_kind: "concept_choice",
      capability_id: "brand_hypothesis",
      options: [...options, ...Array.from({ length: Math.max(0, optionCount - options.length) }, (_, index) => ({
        option_id: `option-new-${index + 1}`,
        title: `New direction ${index + 1}`,
        summary: "A fresh direction.",
        difference_tags: [],
        recommended: false,
        reference_preview: [],
      }))],
    },
  };
}

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

  it("shows a custom input only for Brand hypothesis and Treatment cards", () => {
    const brand = brandInteraction();
    render(
      <ConceptChoiceDecisionDock
        interaction={brand}
        pending={false}
        issue={null}
        selectedOptionId={null}
        onSelectOption={vi.fn()}
        onSubmitCustom={vi.fn(async () => true)}
      />,
    );
    expect(screen.getByRole("radio", { name: /Other \(custom\)/i })).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(isBrandCustomInputCard(brand)).toBe(true);
    expect(isBrandCustomInputCard({ ...brand, content: { ...brand.content, capability_id: "brand_treatment_step" } })).toBe(true);
    expect(isBrandCustomInputCard({ ...brand, content: { ...brand.content, capability_id: "brand_adspec" } })).toBe(false);
    expect(isBrandCustomInputCard({ ...brand, content: { ...brand.content, capability_id: "brand_skill-stack" } })).toBe(false);
    expect(isBrandCustomInputCard({ ...brand, content: { ...brand.content, capability_id: "scene_treatment" } })).toBe(false);
  });

  it("reveals and submits trimmed custom text", async () => {
    const onSubmitCustom = vi.fn(async () => true);
    render(
      <ConceptChoiceDecisionDock
        interaction={brandInteraction()}
        pending={false}
        issue={null}
        selectedOptionId={null}
        onSelectOption={vi.fn()}
        onSubmitCustom={onSubmitCustom}
      />,
    );

    fireEvent.click(screen.getByRole("radio", { name: /Other \(custom\)/i }));
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "  再来几个方案  " } });
    expect((screen.getByRole("button", { name: "Submit" }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(onSubmitCustom).toHaveBeenCalledWith("再来几个方案"));
  });

  it("uses translated custom labels", () => {
    render(
      <LocaleProvider initialLocale="zh-CN">
        <ConceptChoiceDecisionDock
          interaction={brandInteraction()}
          pending={false}
          issue={null}
          selectedOptionId={null}
          onSelectOption={vi.fn()}
          onSubmitCustom={vi.fn(async () => true)}
        />
      </LocaleProvider>,
    );
    fireEvent.click(screen.getByRole("radio", { name: /其他（自定义）/ }));
    expect(screen.getByPlaceholderText("写下你的想法，或输入「再来几个方案」")).toBeTruthy();
    expect(screen.getByRole("button", { name: "提交" })).toBeTruthy();
  });

  it("tags appended options until a choice is made and resets on a new revision", () => {
    const first = brandInteraction();
    const { rerender } = render(
      <ConceptChoiceDecisionDock
        interaction={first}
        pending={false}
        issue={null}
        selectedOptionId={null}
        onSelectOption={vi.fn()}
        onSubmitCustom={vi.fn(async () => true)}
      />,
    );
    const republished = { ...brandInteraction(6), revision: first.revision + 1 };
    rerender(
      <ConceptChoiceDecisionDock
        interaction={republished}
        pending={false}
        issue={null}
        selectedOptionId={null}
        onSelectOption={vi.fn()}
        onSubmitCustom={vi.fn(async () => true)}
      />,
    );
    expect(screen.getAllByText("New")).toHaveLength(3);
    fireEvent.click(screen.getByRole("radio", { name: /Other \(custom\)/i }));
    expect(screen.getByRole("textbox")).toBeTruthy();
    rerender(
      <ConceptChoiceDecisionDock
        interaction={{ ...republished, revision: republished.revision + 1 }}
        pending={false}
        issue={null}
        selectedOptionId={null}
        onSelectOption={vi.fn()}
        onSubmitCustom={vi.fn(async () => true)}
      />,
    );
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});
