import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GuidedInteractionV1 } from "../../../types-v2.ts";
import { QuestionnaireDecisionDock } from "./QuestionnaireDecisionDock.tsx";

const interaction: GuidedInteractionV1 = {
  interaction_id: "questionnaire-1",
  workflow_id: "workflow-1",
  session_id: "session-1",
  checkpoint_id: "checkpoint-1",
  kind: "clarification_questionnaire",
  status: "open",
  response_locale: "en-US",
  expected_session_revision: 8,
  revision: 3,
  title: "Set production details",
  context: "Answer the questions to continue.",
  content: {
    content_kind: "questionnaire",
    questions: [
      {
        question_id: "production_duration_seconds",
        prompt: "How long should the final ad be?",
        input_kind: "single_select",
        options: [
          { option_id: "duration_seconds_15", title: "15 seconds", summary: "A concise cut.", difference_tags: [], recommended: false, reference_preview: [] },
          { option_id: "duration_seconds_30", title: "30 seconds", summary: "A balanced cut.", difference_tags: [], recommended: true, reference_preview: [] },
        ],
        allow_custom: true,
        allow_skip: false,
        required: true,
      },
      {
        question_id: "tone",
        prompt: "Which tone should lead?",
        input_kind: "single_select",
        options: [
          { option_id: "tone_warm", title: "Warm", summary: "Soft and human.", difference_tags: [], recommended: false, reference_preview: [] },
        ],
        allow_custom: true,
        allow_skip: true,
        required: false,
      },
    ],
  },
  allowed_actions: ["answer", "skip"],
  submit_path: "/api/v2/workflows/workflow-1/chat/interactions/questionnaire-1/submit",
  created_at: "2026-08-27T10:00:00Z",
  updated_at: "2026-08-27T10:00:00Z",
};

afterEach(cleanup);

describe("QuestionnaireDecisionDock", () => {
  it("tracks answered progress and submits the canonical answer union", () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(<QuestionnaireDecisionDock interaction={interaction} pending={false} issue={null} onSubmit={submit} />);

    expect(screen.getByText("0 of 2 answered")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /30 seconds/i }));
    const skip = screen.getByRole("button", { name: /Skip Which tone should lead/i });
    fireEvent.click(skip);
    expect(skip.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("2 of 2 answered")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Submit answers" }));

    expect(submit).toHaveBeenCalledWith({
      submission_kind: "questionnaire",
      expected_interaction_revision: 3,
      expected_session_revision: 8,
      answers: [
        { answer_kind: "option", question_id: "production_duration_seconds", option_id: "duration_seconds_30" },
        { answer_kind: "skip", question_id: "tone" },
      ],
    });
  });

  it("shows a recommendation without selecting it", () => {
    render(<QuestionnaireDecisionDock interaction={interaction} pending={false} issue={null} onSubmit={vi.fn().mockResolvedValue(true)} />);

    expect(screen.getByText("Recommended")).toBeTruthy();
    expect(screen.getAllByRole("radio").every((radio) => !(radio as HTMLInputElement).checked)).toBe(true);
    expect((screen.getByRole("button", { name: "Submit answers" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("does not submit an empty answer list when every question is optional", () => {
    const optionalQuestion = interaction.content.content_kind === "questionnaire"
      ? interaction.content.questions[1]
      : undefined;
    if (!optionalQuestion) throw new Error("Expected an optional questionnaire item.");
    const optionalInteraction: GuidedInteractionV1 = {
      ...interaction,
      content: {
        content_kind: "questionnaire",
        questions: [optionalQuestion],
      },
    };
    render(
      <QuestionnaireDecisionDock
        interaction={optionalInteraction}
        pending={false}
        issue={null}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );

    const submit = screen.getByRole("button", { name: "Submit answers" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /Skip Which tone should lead/i }));
    expect(submit.disabled).toBe(false);
  });

  it("uses a numeric custom duration and trims its submitted value", () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(<QuestionnaireDecisionDock interaction={interaction} pending={false} issue={null} onSubmit={submit} />);

    const input = screen.getByRole("spinbutton", { name: "Custom duration in seconds" }) as HTMLInputElement;
    expect(input.type).toBe("number");
    fireEvent.change(input, { target: { value: "45" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit answers" }));

    expect(submit).toHaveBeenCalledWith(expect.objectContaining({
      answers: [{ answer_kind: "custom", question_id: "production_duration_seconds", value: "45" }],
    }));
  });

  it("places duration validation beside the field without a second frame alert", () => {
    render(
      <QuestionnaireDecisionDock
        interaction={interaction}
        pending={false}
        issue={{
          summary: "Choose one of the supported duration values.",
          detail: "guided_duration_value_invalid",
          fieldId: "production_duration_seconds",
          retryable: true,
        }}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );

    const input = screen.getByRole("spinbutton", { name: "Custom duration in seconds" });
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.getAttribute("aria-describedby")).toBeTruthy();
    expect(screen.getByText("Choose one of the supported duration values.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps a general issue in the shared frame", () => {
    render(
      <QuestionnaireDecisionDock
        interaction={interaction}
        pending={false}
        issue={{ summary: "Review this response and try again.", detail: null, fieldId: null, retryable: true }}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );

    expect(screen.getByRole("alert").textContent).toContain("Review this response and try again.");
  });

  it("retains answers and disables controls while pending", () => {
    const { rerender } = render(
      <QuestionnaireDecisionDock interaction={interaction} pending={false} issue={null} onSubmit={vi.fn().mockResolvedValue(true)} />,
    );
    fireEvent.click(screen.getByRole("radio", { name: /30 seconds/i }));

    rerender(
      <QuestionnaireDecisionDock interaction={interaction} pending issue={null} onSubmit={vi.fn().mockResolvedValue(true)} />,
    );

    expect((screen.getByRole("radio", { name: /30 seconds/i }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("radio", { name: /30 seconds/i }) as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "Submitting" }).getAttribute("aria-disabled")).toBe("true");
  });

  it("shows Skip only when both question and interaction allow it", () => {
    const { rerender } = render(
      <QuestionnaireDecisionDock interaction={interaction} pending={false} issue={null} onSubmit={vi.fn().mockResolvedValue(true)} />,
    );
    expect(screen.getByRole("button", { name: /Skip Which tone should lead/i })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Skip How long/i })).toBeNull();

    rerender(
      <QuestionnaireDecisionDock
        interaction={{ ...interaction, allowed_actions: ["answer"] }}
        pending={false}
        issue={null}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );
    expect(screen.queryByRole("button", { name: /Skip Which tone should lead/i })).toBeNull();
  });
});
