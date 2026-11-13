import { describe, expect, it } from "vitest";

import type { AgentCanvasChatTurnV2, GuidedJourneyStageV2 } from "../../../types-v2.ts";
import { translateUi } from "../../../i18n/uiMessages.ts";
import { agentWorkingMessage } from "./agentWorkingMessage.ts";

const context = { workflowId: "workflow-1", items: [], turnsById: {} };
function turn(capability: string, overrides: Partial<AgentCanvasChatTurnV2> = {}): AgentCanvasChatTurnV2 {
  return {
    turn_id: "turn-1", workflow_id: "workflow-1", conversation_id: "conversation-1",
    status: "running", turn_kind: "capability", request: { capability_id: capability },
    error_code: null, error_message: null, creation_mode: null, guidance_session_revision: null,
    continuation: null, retry_of_turn_id: null, retry_attempt_no: 0, retryable: false,
    operation_stage: null, operation_failure: null,
    created_at: "2026-11-13T00:00:00Z", updated_at: "2026-11-13T00:00:00Z", ...overrides,
  };
}

describe("stage-specific working messages", () => {
  it.each([
    ["world_view", "世界观设计师正在工作..."],
    ["product", "产品设计师正在工作..."],
    ["props", "道具设计师正在工作..."],
    ["character", "角色设计师正在工作..."],
    ["scene", "场景设计师正在工作..."],
    ["narrative_direction", "编剧正在工作..."],
    ["storyboard_plan", "分镜设计师正在工作..."],
    ["storyboard_grids", "分镜设计师正在工作..."],
    ["videos", "视频导演正在工作..."],
    ["bgm", "配乐师正在工作..."],
    ["editing", "剪辑师正在工作..."],
  ] as const)("describes %s while the next role is loading", (stage, expected) => {
    const key = agentWorkingMessage({ ...context, journey: { stage, active_action: null } });
    expect(translateUi("zh-CN", key)).toBe(expected);
  });

  it("uses the active execution rather than an earlier journey stage", () => {
    expect(agentWorkingMessage({ ...context, turnsById: { "turn-1": turn("script_authoring") },
      journey: { stage: "scene", active_action: null } })).toBe("Script Writer is working...");
  });

  it("selects the newest active turn and ignores late updates to the old role", () => {
    expect(agentWorkingMessage({ ...context, turnsById: {
      old: turn("character_design", { updated_at: "2026-11-13T00:02:00Z" }),
      next: turn("scene_design", { turn_id: "turn-2", created_at: "2026-11-13T00:01:00Z" }),
    } })).toBe("Scene Designer is working...");
  });

  it.each(["completed", "failed", "superseded"] as const)("ignores a %s role when advancing", status => {
    expect(agentWorkingMessage({ ...context, turnsById: { "turn-1": turn("character_design", { status }) },
      journey: { stage: "narrative_direction", active_action: null } })).toBe("Script Writer is working...");
  });

  it("ignores turns from another workflow", () => {
    expect(agentWorkingMessage({ ...context, turnsById: { "turn-1": turn("character_design", { workflow_id: "other" }) } }))
      .toBe("Agent is working...");
  });

  it.each([
    ["brand-memory", "正在整理品牌信息..."], ["campaign", "正在梳理广告目标..."],
    ["hypothesis", "正在构思创意方向..."], ["adspec", "正在制定广告策略..."],
    ["creative-route", "正在规划创作方式..."], ["skill-stack", "正在匹配创作技能..."],
    ["skill-stack-early", "正在匹配创作技能..."], ["treatment", "正在设计创意方案..."],
  ] as const)("describes the Brand %s stage", (brandStage, expected) => {
    expect(translateUi("zh-CN", agentWorkingMessage({ ...context, brandStage }))).toBe(expected);
  });

  it("uses production roles after Brand preparation finishes", () => {
    expect(agentWorkingMessage({ ...context, brandStage: "production",
      journey: { stage: "character", active_action: null } })).toBe("Character Designer is working...");
  });

  it("uses the reserved action's stage during a handoff", () => {
    expect(agentWorkingMessage({ ...context, journey: { stage: "scene", active_action: {
      action_id: "action-next", action_kind: "proposal", stage: "narrative_direction" as GuidedJourneyStageV2,
      stage_revision: 4, status: "reserved", turn_id: null, occurrence_id: null, character_phase: null,
    } } })).toBe("Script Writer is working...");
  });
});
