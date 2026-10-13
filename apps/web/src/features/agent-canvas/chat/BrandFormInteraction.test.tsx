import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GuidedInteractionV1 } from "../../../types-v2.ts";
import { BrandFormInteraction } from "./BrandFormInteraction.tsx";

const interaction: GuidedInteractionV1 = {
  interaction_id: "interaction-brand-form",
  workflow_id: "workflow-1",
  session_id: "session-1",
  checkpoint_id: "checkpoint-1",
  kind: "brand_form",
  status: "open",
  response_locale: "en-US",
  expected_session_revision: 7,
  revision: 3,
  title: "Brand Memory",
  context: "Complete the foundation form.",
  content: {
    content_kind: "brand_form",
    form_id: "brand_form_brand-memory_3",
    stage: "brand-memory",
    revision: 3,
    response_locale: "en-US",
    context_digest: "a".repeat(64),
    title: "Brand Memory",
    instructions: "Choose one option for every row.",
    rows: [
      {
        question_id: "tone",
        slot_id: "tone",
        prompt: "What tone should lead?",
        options: [
          { option_id: "warm", label: "Warm", why: "Human and close." },
          { option_id: "precise", label: "Precise", why: "Clear and focused." },
          { option_id: "bold", label: "Bold", why: "High contrast." },
          { option_id: "custom", label: "Other (custom)", why: null },
        ],
        custom_option_id: "custom",
        required: true,
      },
      {
        question_id: "audience",
        slot_id: "audience",
        prompt: "Who is this for?",
        options: [
          { option_id: "makers", label: "Makers", why: "Hands-on audience." },
          { option_id: "teams", label: "Teams", why: "Collaborative audience." },
          { option_id: "leaders", label: "Leaders", why: "Decision makers." },
          { option_id: "custom", label: "Other (custom)", why: null },
        ],
        custom_option_id: "custom",
        required: true,
      },
    ],
  },
  allowed_actions: ["select", "custom"],
  submit_path: "/api/v2/workflows/workflow-1/chat/interactions/interaction-brand-form/submit",
  created_at: "2026-10-12T00:00:00Z",
  updated_at: "2026-10-12T00:00:00Z",
};

afterEach(cleanup);

describe("BrandFormInteraction", () => {
  it("requires every row and omits custom text when a recommendation is selected", async () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(<BrandFormInteraction interaction={interaction} pending={false} issue={null} onSubmit={submit} />);

    expect(screen.getByText("0 of 2 answered")).toBeTruthy();
    const confirm = screen.getByRole("button", { name: "确认整张表" });
    expect(confirm.hasAttribute("disabled")).toBe(true);

    fireEvent.click(screen.getByRole("radio", { name: /Warm/ }));
    fireEvent.click(screen.getAllByRole("radio", { name: /自定义/ })[1]!);
    fireEvent.change(screen.getByRole("textbox", { name: "自定义内容：Who is this for?" }), { target: { value: "Independent artists" } });
    expect(screen.getByText("2 of 2 answered")).toBeTruthy();

    fireEvent.click(screen.getByRole("radio", { name: /Teams/ }));
    fireEvent.click(confirm);

    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
    expect(submit).toHaveBeenCalledWith({
      submission_kind: "brand_form",
      form_id: "brand_form_brand-memory_3",
      expected_interaction_revision: 3,
      expected_session_revision: 7,
      confirm: true,
      answers: [
        { question_id: "tone", selected_option_id: "warm" },
        { question_id: "audience", selected_option_id: "teams" },
      ],
    });
  });

  it("submits custom text only for the selected custom option and locks during submission", async () => {
    let finish!: (accepted: boolean) => void;
    const submit = vi.fn(() => new Promise<boolean>((resolve) => { finish = resolve; }));
    const { rerender } = render(<BrandFormInteraction interaction={interaction} pending={false} issue={null} onSubmit={submit} />);
    fireEvent.click(screen.getByRole("radio", { name: /Warm/ }));
    fireEvent.click(screen.getAllByRole("radio", { name: /自定义/ })[1]!);
    fireEvent.change(screen.getByRole("textbox", { name: "自定义内容：Who is this for?" }), { target: { value: "  Independent artists  " } });
    fireEvent.click(screen.getByRole("button", { name: "确认整张表" }));

    expect(submit).toHaveBeenCalledWith(expect.objectContaining({
      answers: [
        { question_id: "tone", selected_option_id: "warm" },
        { question_id: "audience", selected_option_id: "custom", custom_text: "Independent artists" },
      ],
    }));
    rerender(<BrandFormInteraction interaction={interaction} pending issue={null} onSubmit={submit} />);
    expect(screen.getByRole("button", { name: "Submitting" }).hasAttribute("disabled")).toBe(true);
    finish(true);
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("正在准备下一阶段"));
  });
});
