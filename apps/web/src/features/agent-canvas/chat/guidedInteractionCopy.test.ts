import { describe, expect, it } from "vitest";
import { translateUi, type UiMessageKey } from "../../../i18n/uiMessages.ts";
import { guidedInteractionCopy } from "./guidedInteractionCopy.ts";

describe("fixed guided interaction copy", () => {
  const zh = (key: UiMessageKey, values?: Record<string, string | number>) => translateUi("zh-CN", key, values);
  const en = (key: UiMessageKey, values?: Record<string, string | number>) => translateUi("en-US", key, values);

  it.each([
    ["Choose production duration", "选择广告时长"],
    ["How many characters should appear in the advertisement?", "广告中需要几个角色？"],
    ["30 seconds", "30 秒"],
    ["2 characters", "2 个角色"],
    ["Author 1 character.", "设计 1 个角色。"],
    ["Author 2 characters.", "设计 2 个角色。"],
    ["Produce a 30-second advertisement.", "制作 30 秒的广告。"],
    ["Which hypothesis should lead this ad?", "哪一个创意假设应该主导这次广告？"],
    ["How would you like to create next?", "接下来你想怎么创作？"],
    ["Skip for now, choose later", "暂时跳过，稍后选择"],
    ["The agent could not submit this response. Try again.", "智能助手未能提交，请重试。"],
  ])("translates stored copy in either language: %s", (english, chinese) => {
    expect(guidedInteractionCopy(english, zh)).toBe(chinese);
    expect(guidedInteractionCopy(chinese, en)).toBe(english);
  });

  it("preserves generated content and custom prompts", () => {
    for (const text of ["Which cup tells your story?", "续命处方", "Coffee in the rain", "reference.png"]) {
      expect(guidedInteractionCopy(text, zh)).toBe(text);
      expect(guidedInteractionCopy(text, en)).toBe(text);
    }
  });
});
