import { describe, expect, it } from "vitest";

import type { ChatMessageV2 } from "../../../types-v2.ts";
import type { BrandDecisionPanelV1, BrandSlotValueV1, BrandStageV2 } from "../brand/brandDecisions.ts";
import type { GuidedAnswerBubbleV1 } from "./guidedAnswerPresentation.ts";
import { projectBrandSummaries } from "./brandFormSummary.ts";

function slot(slotId: string, stage: BrandStageV2, value: string, confirmedAt: string): BrandSlotValueV1 {
  return { slot_id: slotId, stage, value, kind: "fact", provenance: "user_confirmed", confirmed_at: confirmedAt };
}

function decisions(stage: BrandStageV2): BrandDecisionPanelV1 {
  const brand = [
    slot("brand_name", "brand-memory", "Volt", "2026-10-19T09:32:05Z"),
    slot("brand_product_identity", "brand-memory", "E-scooter", "2026-10-19T09:32:04Z"),
  ];
  const campaign = [slot("campaign_goal", "campaign", "Launch", "2026-10-19T09:35:49Z")];
  return {
    project_id: "project-1",
    workflow_id: "workflow-1",
    mode: "brand",
    journey: {
      policy_version: "brand_professional_v1",
      stage,
      treatment_substep: null,
      stage_revision: 1,
      stage_status: "ready",
    },
    brand_name: "Volt",
    slot_values: [...brand, ...campaign],
    brand_profile: { values: brand, inherited_values: [], unresolved_fields: [] },
    campaign_brief: { values: campaign, inherited_values: [], unresolved_fields: [] },
    open_card: null,
    hypotheses: [],
    selected_hypothesis_id: null,
    adspec: null,
    skill_stack: {
      entries: [
        { skill_kind: "audiovisual_style", skill_id: "tvc", title: "Product TVC", selected: true, version: "1", reason: null },
        { skill_kind: "creative_method", skill_id: "ritual", title: "Private Ritual", selected: true, version: "1", reason: null },
        { skill_kind: "creative_method", skill_id: "unused", title: "Unused", selected: false, version: "1", reason: null },
      ],
    },
    treatment_steps: [],
    treatment_locked: false,
  };
}

function message(sequence: number, createdAt: string): ChatMessageV2 {
  return {
    item_type: "message",
    message_kind: "conversation",
    message_id: `message-${sequence}`,
    conversation_id: "conversation-1",
    speaker: "adcraft_video_agent",
    text: "Message",
    linked_node_ids: [],
    script_node_id: null,
    proposal_id: null,
    capability_id: null,
    sequence,
    created_at: createdAt,
  };
}

function answer(stage: string, sequence: number): GuidedAnswerBubbleV1 {
  return {
    bubble_id: `answer-${stage}-${sequence}`,
    interaction_id: `interaction_abc_brand_${stage}_${sequence}_def`,
    question_id: `question-${sequence}`,
    label: "Question",
    value: "Answer",
    sequence,
  };
}

describe("projectBrandSummaries", () => {
  const items = [message(6, "2026-10-19T09:28:00Z"), message(17, "2026-10-19T10:02:00Z")];
  const answers = [answer("hypothesis", 7), answer("adspec", 8), answer("treatment", 9)];

  it("restores completed cards without opening a new guided question", () => {
    expect(projectBrandSummaries(decisions("brand-memory"), items, answers)).toEqual([]);
    expect(projectBrandSummaries(decisions("campaign"), items, answers).map((summary) => summary.stage))
      .toEqual(["brand-memory"]);
    expect(projectBrandSummaries({ ...decisions("production"), mode: "creation" }, items, answers)).toEqual([]);
  });

  it("lists each selected value without option details, in form order", () => {
    const [brand, campaign, skills] = projectBrandSummaries(decisions("production"), items, answers);

    expect(brand!.rows.map((row) => [row.label, row.value])).toEqual([
      ["Product", "E-scooter"],
      ["Brand name", "Volt"],
    ]);
    expect(campaign!.rows.map((row) => row.value)).toEqual(["Launch"]);
    expect(skills!.rows.map((row) => [row.label, row.value])).toEqual([
      ["Creative method", "Private Ritual"],
      ["Audiovisual style", "Product TVC"],
    ]);
  });

  it.each([true, false])("places skills immediately after Campaign when early confirmation is %s", (earlyConfirmed) => {
    const [brand, campaign, skills] = projectBrandSummaries(
      { ...decisions("production"), early_skills_confirmed: earlyConfirmed }, items, answers,
    );

    expect(brand!.sequence).toBeGreaterThan(6);
    expect(campaign!.sequence).toBeGreaterThan(brand!.sequence);
    expect(campaign!.sequence).toBeLessThan(7);
    expect(skills!.sequence).toBeGreaterThan(campaign!.sequence);
    expect(skills!.sequence).toBeLessThan(7);
  });

  it("pairs the skill summary with the latest recorded question at its original position", () => {
    const earlier = { ...answer("skill-stack-early", 3), sequence: 6.5 };
    const latest = { ...answer("skill-stack", 6), sequence: 8.5 };
    const skills = projectBrandSummaries(decisions("production"), items, [latest, ...answers, earlier])
      .find(summary => summary.stage === "skill-stack")!;
    expect(skills.answer).toBe(latest);
    expect(skills.sequence).toBe(latest.sequence);
  });
});


it("shows an early confirmed combination with directions, but never treats recommendations as confirmed", () => {
  const panel = decisions("hypothesis");
  expect(projectBrandSummaries(panel, [], []).some(item => item.stage === "skill-stack-early")).toBe(false);
  const selected = projectBrandSummaries({ ...panel, early_skills_confirmed: true }, [], []);
  expect(selected.find(item => item.stage === "skill-stack-early")?.rows.map(row => row.value).join(" ")).toContain("Private Ritual");
});
