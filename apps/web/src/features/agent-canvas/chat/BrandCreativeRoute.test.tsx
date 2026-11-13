import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { normalizeGuidedSessionStateV2 } from "../model/normalizers.ts";
import { GuidedInteractionCard } from "./GuidedInteractionCard.tsx";

function normalizeGuidedInteractionV1(interaction: unknown) {
  return normalizeGuidedSessionStateV2({
    session_id: "session", workflow_id: "workflow", status: "active", revision: 4,
    updated_at: "2026-11-10T00:00:00Z", goal: { requested_output: "video", delivery_scope: "generated_media", summary: "Create an ad", explicit_constraints: {} },
    journey: { policy_version: "fixed_ad_production_v2", stage: "intake", stage_status: "waiting_user", stage_revision: 1, decisions: [], active_action: null, suspended_action: null, transition_evidence: [] },
    interaction,
  }).interaction!;
}
const payload = {
  interaction_id: "route", workflow_id: "workflow", session_id: "session", checkpoint_id: "checkpoint",
  kind: "concept_choice", status: "open", response_locale: "zh-CN", expected_session_revision: 4,
  revision: 2, title: "接下来你想怎么创作？", context: "请选择创作方式",
  content: { content_kind: "concept_choice", proposal_id: null, stage: "intake", stage_revision: 8,
    action_id: "route-card", capability_id: "brand_creative-route", allow_custom: false, allow_exclusion: false,
    options: [
      { option_id: "guided", title: "继续逐步完善创意方案", summary: "沿用现有流程", recommended: true },
      { option_id: "full-script", title: "直接生成完整剧本并进入制作", summary: "生成后进入制作", recommended: false },
    ],
  },
  allowed_actions: ["select"], submit_path: "/submit", created_at: "2026-11-10T00:00:00Z", updated_at: "2026-11-10T00:00:00Z",
};

describe("Brand creative route", () => {
  it("shows exactly two ordered choices and submits the second in one click", async () => {
    const onSubmit = vi.fn().mockResolvedValue(true);
    const interaction = normalizeGuidedInteractionV1(payload);
    render(<GuidedInteractionCard interaction={interaction} pending={false} onSubmit={onSubmit} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(2);
    expect(buttons[0].textContent).toContain("继续逐步完善创意方案");
    fireEvent.click(buttons[1]);
    fireEvent.click(buttons[1]);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith({ submission_kind: "concept_choice", action: "select",
      option_id: "full-script", expected_interaction_revision: 2, expected_session_revision: 4 });
  });

  it("preserves the existing concept-card minimum and route order", () => {
    expect(() => normalizeGuidedInteractionV1({ ...payload, content: { ...payload.content, capability_id: "brand_treatment" } })).toThrow();
    expect(() => normalizeGuidedInteractionV1({ ...payload, content: { ...payload.content, options: [...payload.content.options].reverse() } })).toThrow();
  });
});
