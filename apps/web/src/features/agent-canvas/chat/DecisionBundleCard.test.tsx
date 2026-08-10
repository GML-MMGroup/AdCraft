import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DecisionBundleV2 } from "../../../types-v2.ts";
import { DecisionBundleCard } from "./DecisionBundleCard.tsx";

const bundle: DecisionBundleV2 = {
  bundle_id: "bundle-1",
  workflow_id: "workflow-1",
  conversation_id: "conversation-1",
  source_turn_id: "turn-1",
  replacement_bundle_id: null,
  status: "open",
  revision: 4,
  title: "Creative decisions",
  introduction: "Choose a direction before production continues.",
  questions: [{
    question_id: "question-1",
    prompt: "Choose the mood",
    selection_mode: "single",
    allow_custom_answer: true,
    allow_skip: true,
    options: [
      { option_id: "mood-calm", label: "Calm", description: "Quiet and precise." },
      { option_id: "mood-bold", label: "Bold", description: "High energy." },
    ],
  }, {
    question_id: "question-2",
    prompt: "Choose references",
    selection_mode: "multiple",
    allow_custom_answer: false,
    allow_skip: false,
    options: [
      { option_id: "reference-product", label: "Product", description: "Keep the product visible." },
      { option_id: "reference-scene", label: "Scene", description: "Use a clean studio." },
    ],
  }],
  answers: [],
  requirement_revision_no: 3,
  created_at: "2026-08-10T00:00:00Z",
  updated_at: "2026-08-10T00:00:00Z",
  closed_at: null,
};

describe("DecisionBundleCard", () => {
  afterEach(() => cleanup());

  it("submits one structured answer set instead of a synthetic chat message", () => {
    const onApply = vi.fn().mockResolvedValue(undefined);
    render(<DecisionBundleCard bundle={bundle} pending={false} onApply={onApply} />);

    fireEvent.click(screen.getByRole("radio", { name: "Calm" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Product" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Scene" }));
    fireEvent.click(screen.getByRole("button", { name: "Submit decisions" }));

    expect(onApply).toHaveBeenCalledWith("bundle-1", {
      action: "submit",
      expected_revision: 4,
      answers: [{
        question_id: "question-1",
        selected_option_ids: ["mood-calm"],
        custom_answer: null,
        skipped: false,
      }, {
        question_id: "question-2",
        selected_option_ids: ["reference-product", "reference-scene"],
        custom_answer: null,
        skipped: false,
      }],
    });
  });

  it("offers a bundle skip through the structured skip action", () => {
    const onApply = vi.fn().mockResolvedValue(undefined);
    render(<DecisionBundleCard bundle={bundle} pending={false} onApply={onApply} />);

    fireEvent.click(screen.getByRole("button", { name: "Skip these decisions" }));

    expect(onApply).toHaveBeenCalledWith("bundle-1", {
      action: "skip_bundle",
      expected_revision: 4,
    });
  });
});
