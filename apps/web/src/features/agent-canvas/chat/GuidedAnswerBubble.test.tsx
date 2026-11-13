import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LocaleProvider, type AppLocale } from "../../../i18n/locale.tsx";
import { GuidedAnswerBubble } from "./GuidedAnswerBubble.tsx";
import type { GuidedAnswerBubbleV1 } from "./guidedAnswerPresentation.ts";

afterEach(cleanup);

function renderAnswer(interactionId: string, locale: AppLocale = "zh-CN", showQuestion = true) {
  const answer: GuidedAnswerBubbleV1 = {
    bubble_id: "answer-1", interaction_id: interactionId, question_id: "choice",
    label: "请选择你想要的方案", value: "续命处方", sequence: 3,
  };
  return render(<LocaleProvider initialLocale={locale}><GuidedAnswerBubble answer={answer} showQuestion={showQuestion} /></LocaleProvider>);
}

describe("GuidedAnswerBubble stage receipts", () => {
  it.each([
    ["hypothesis", "创意假设"],
    ["adspec", "广告规格"],
    ["treatment", "创意方案"],
    ["creative-route", "创作方式"],
  ])("keeps the chosen plan inside the disclosure for %s", (stage, title) => {
    const { container } = renderAnswer(`interaction_workflow_brand_${stage}_12_choice`);
    expect(container.querySelector("summary strong")?.textContent).toBe(title);
    const details = container.querySelector("details")!;
    expect(details.open).toBe(false);
    const chosen = screen.getByText("续命处方");
    expect(chosen.closest(".agent-chat__selection-receipt-detail")).not.toBeNull();
    expect(chosen.closest("summary")).toBeNull();
    const question = screen.getByRole("article", { name: "助手提问" });
    expect(question.textContent).toContain("请选择你想要的方案");
    expect(question.closest("details")).toBeNull();
    expect(question.compareDocumentPosition(chosen) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("does not repeat a question already shown by its proposal", () => {
    renderAnswer("interaction_workflow_brand_hypothesis_12_choice", "zh-CN", false);
    expect(screen.queryByRole("article", { name: "助手提问" })).toBeNull();
    expect(screen.getByText("续命处方")).toBeTruthy();
  });

  it("localizes the stage name while preserving the selected plan's original language", () => {
    const { container } = renderAnswer("interaction_workflow_brand_hypothesis_12_choice", "en-US");
    expect(container.querySelector("summary strong")?.textContent).toBe("Creative hypothesis");
    expect(container.querySelector(".agent-chat__selection-receipt-value")?.textContent).toBe("续命处方");
  });

  it("preserves the existing title for ordinary or unrecognized interactions", () => {
    const { container } = renderAnswer("ordinary_interaction_1");
    expect(container.querySelector("summary strong")?.textContent).toBe("续命处方");
    expect(container.querySelector(".agent-chat__selection-receipt-value")).toBeNull();
    const question = screen.getByRole("article", { name: "助手提问" });
    expect(question.textContent).toContain("请选择你想要的方案");
    expect(question.closest("details")).toBeNull();
  });
});
