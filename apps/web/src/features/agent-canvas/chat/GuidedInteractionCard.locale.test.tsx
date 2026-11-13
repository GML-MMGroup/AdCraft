import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider, useLocale } from "../../../i18n/locale.tsx";
import type { GuidedInteractionV1 } from "../../../types-v2.ts";
import { GuidedInteractionCard } from "./GuidedInteractionCard.tsx";
import { GuidedQuestionBubble } from "./GuidedQuestionBubble.tsx";

const base = {
  interaction_id: "interaction-brand", workflow_id: "workflow-1", session_id: "session-1", checkpoint_id: "checkpoint-1",
  status: "open", response_locale: "en-US", expected_session_revision: 2, revision: 1,
  title: "Brand Memory", context: "", submit_path: "/submit", allowed_actions: ["select", "custom"],
  created_at: "2026-11-10T00:00:00Z", updated_at: "2026-11-10T00:00:00Z",
} satisfies Partial<GuidedInteractionV1>;

function LanguageToggle() {
  const { toggleLocale } = useLocale();
  return <button onClick={toggleLocale}>Switch language</button>;
}
afterEach(() => { cleanup(); window.localStorage.removeItem("adcraft.locale"); });

describe("guided card interface locale", () => {
  it("localizes fixed brand form labels while retaining generated choices and a custom draft", () => {
    const interaction: GuidedInteractionV1 = { ...base, kind: "brand_form", content: {
      content_kind: "brand_form", form_id: "form", stage: "brand-memory", revision: 1,
      response_locale: "en-US", context_digest: "digest", title: "Brand Memory", instructions: "Choose one option for every row.",
      rows: [{ question_id: "tone", slot_id: "tone", prompt: "Brand tone", required: true, custom_option_id: "custom",
        options: [{ option_id: "plan", label: "Coffee in the rain", why: "A quiet moment" },
          { option_id: "custom", label: "Other (custom)", why: null }] }],
    } };
    const submit = vi.fn().mockResolvedValue(true);
    render(<LocaleProvider initialLocale="zh-CN"><LanguageToggle />
      <GuidedInteractionCard interaction={interaction} pending={false} onSubmit={submit} />
    </LocaleProvider>);
    expect(screen.getByRole("article", { name: "品牌记忆" })).toBeTruthy();
    expect(screen.getByText(/请为每一项选择一个方案/)).toBeTruthy();
    expect(screen.getByText("Coffee in the rain")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /其他（自定义）/ }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "我的广告创意" } });
    fireEvent.click(screen.getByRole("button", { name: "Switch language" }));
    expect(screen.getByRole("article", { name: "Brand Memory" })).toBeTruthy();
    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("我的广告创意");
    expect(screen.getByText("Coffee in the rain")).toBeTruthy();
    expect(submit).not.toHaveBeenCalled();
  });

  it("translates a saved Chinese route card into an English interface", () => {
    const interaction: GuidedInteractionV1 = { ...base, kind: "concept_choice", response_locale: "zh-CN",
      title: "接下来你想怎么创作？", content: {
        content_kind: "concept_choice", proposal_id: null, action_id: "route", stage: "intake", stage_revision: 1,
        occurrence_id: null, capability_id: "brand_creative-route", allow_custom: false, allow_exclusion: false,
        options: [{ option_id: "guided", title: "继续逐步完善创意方案", summary: "沿用现有流程",
          recommended: true, difference_tags: [], reference_preview: [] }],
      },
    };
    render(<LocaleProvider initialLocale="en-US">
      <GuidedInteractionCard interaction={interaction} pending={false} onSubmit={vi.fn()} />
    </LocaleProvider>);
    expect(screen.getByRole("article", { name: "How would you like to create next?" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Continue refining the creative plan step by step/ })).toBeTruthy();
  });

  it("localizes fixed concept questions and pending question bubbles without translating the creative plan", () => {
    const prompt = "Which hypothesis should lead this ad?";
    const interaction: GuidedInteractionV1 = { ...base, kind: "concept_choice", context: prompt, content: {
      content_kind: "concept_choice", proposal_id: null, action_id: "hypothesis", stage: "intake", stage_revision: 1,
      occurrence_id: null, capability_id: "brand_hypothesis", allow_custom: true, allow_exclusion: false,
      options: [{ option_id: "plan", title: "Coffee in the rain", summary: "A quiet moment",
        recommended: false, difference_tags: [], reference_preview: [] }],
    } };
    render(<LocaleProvider initialLocale="zh-CN">
      <GuidedQuestionBubble label={prompt} />
      <GuidedInteractionCard interaction={interaction} pending={false} onSubmit={vi.fn()} />
    </LocaleProvider>);
    expect(screen.getByRole("article", { name: "哪一个创意假设应该主导这次广告？" })).toBeTruthy();
    expect(screen.getByRole("article", { name: "助手提问" }).textContent).toContain("哪一个创意假设应该主导这次广告？");
    expect(screen.queryByText(prompt)).toBeNull();
    expect(screen.getByText("Coffee in the rain")).toBeTruthy();
    expect(screen.getByText("A quiet moment")).toBeTruthy();
  });
});
