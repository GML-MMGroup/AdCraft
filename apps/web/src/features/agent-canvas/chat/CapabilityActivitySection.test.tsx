import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LanguageSwitcher } from "../../../components/LanguageSwitcher.tsx";
import { LocaleProvider } from "../../../i18n/locale.tsx";
import type { AgentCapabilityIdV2, ChatCapabilityActivityV2 } from "../../../types-v2.ts";
import { CapabilityActivityRow } from "./CapabilityActivitySection.tsx";

const roles: Array<[AgentCapabilityIdV2, string, string]> = [
  ["world_setting", "World Setting", "世界观设计师"],
  ["product_design", "Product Designer", "产品设计师"],
  ["prop_design", "Prop Designer", "道具设计师"],
  ["character_design", "Character Designer", "角色设计师"],
  ["scene_design", "Scene Designer", "场景设计师"],
  ["script_authoring", "Script Writer", "编剧"],
  ["storyboard_design", "Storyboard Artist", "分镜师"],
  ["video_direction", "Video Director", "视频导演"],
  ["bgm_direction", "BGM Director", "配乐指导"],
  ["quick_media", "Quick Media", "快速素材生成"],
];

function activity(id: AgentCapabilityIdV2, name: string, body: string): ChatCapabilityActivityV2 {
  return {
    item_type: "expert_activity", activity_id: "activity-1", turn_id: "turn-1",
    capability_id: id, capability_display_name: name, presentation_text: body,
    status: "working", sequence: 1, started_at: "2026-11-11T00:00:00Z",
    finished_at: null, message: null, error_code: null, elapsed_ms: null,
    attempt_stage: null, retryable: false, validation_paths: [], suggested_actions: [],
    completion_mode: null, warning_code: null,
  };
}

afterEach(() => {
  cleanup();
  localStorage.removeItem("adcraft.locale");
});

describe("capability work status", () => {
  it.each(roles)("keeps one status for %s when switching UI language", (id, english, chinese) => {
    const { container } = render(
      <LocaleProvider initialLocale="en-US">
        <LanguageSwitcher />
        <CapabilityActivityRow compact activity={activity(id, english, `${english} 正在工作。`)} />
      </LocaleProvider>,
    );

    expect(screen.getByRole("status").textContent).toBe(`${english} Working`);
    expect(container.querySelector(".agent-chat__activity-content")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "切换到中文" }));
    expect(screen.getByRole("status", { name: `${chinese} 处理中` }).textContent).toBe(`${chinese} 处理中`);
    expect(container.querySelector(".agent-chat__activity-content")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
    expect(screen.getByRole("status").textContent).toBe(`${english} Working`);
  });

  it.each([
    "Character Designer is working.",
    "Character Designer Working",
    "角色设计师正在工作。",
    "角色设计师 处理中",
    "Preparing the next response...",
  ])("deduplicates %s while keeping the character number", (body) => {
    const { container } = render(
      <LocaleProvider initialLocale="zh-CN">
        <LanguageSwitcher />
        <CapabilityActivityRow compact displayName="Character Designer 2"
          activity={activity("character_design", "Character Designer", body)} />
      </LocaleProvider>,
    );

    expect(screen.getByRole("status").textContent).toBe("角色设计师 2 处理中");
    expect(container.querySelector(".agent-chat__activity-content")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
    expect(screen.getByRole("status").textContent).toBe("Character Designer 2 Working");
  });

  it("uses the UI language even when the backend role name is Chinese", () => {
    render(<CapabilityActivityRow compact
      activity={activity("scene_design", "场景设计师", "场景设计师正在工作。")} />);

    expect(screen.getByRole("status").textContent).toBe("Scene Designer Working");
  });

  it.each(["working", "completed", "failed"] as const)("preserves substantive %s details", (status) => {
    const body = "Scene Designer is working on the lighting of scene 2.";
    render(<CapabilityActivityRow compact activity={{ ...activity("scene_design", "Scene Designer", body), status }} />);

    expect(screen.getByText(body)).toBeTruthy();
    expect(screen.queryByText("Preparing the next response...")).toBeNull();
  });
});
