import type { ChatTimelineItemV2 } from "../../../types-v2.ts";
import type { UiMessageKey } from "../../../i18n/uiMessages.ts";
import type { BrandDecisionPanelV1, BrandSlotValueV1, BrandStageV2 } from "../brand/brandDecisions.ts";
import { isPersistedGuidedAnswerMessage, type GuidedAnswerBubbleV1 } from "./guidedAnswerPresentation.ts";

export type BrandSummaryStage = "brand-memory" | "campaign" | "skill-stack" | "skill-stack-early";

export interface BrandSummaryRow {
  key: string;
  label: UiMessageKey | null;
  fallbackLabel: string;
  value: string;
}

/**
 * Confirmed choices are rebuilt from the Brand decisions read model once their
 * stage is complete. Agent questions come from the conversation and interactions.
 */
export interface BrandSummaryExchange {
  key: string;
  stage: BrandSummaryStage;
  rows: BrandSummaryRow[];
  sequence: number;
  answer?: GuidedAnswerBubbleV1;
}

const STAGE_ORDER: BrandStageV2[] = [
  "brand-memory",
  "campaign",
  "skill-stack-early",
  "hypothesis",
  "adspec",
  "creative-route",
  "skill-stack",
  "treatment",
  "production",
];

const SLOT_LABELS: ReadonlyArray<readonly [string, UiMessageKey]> = [
  ["brand_product_identity", "Product"],
  ["brand_product_focus", "Product focus"],
  ["brand_product_visual", "Product visual"],
  ["brand_audience", "Audience"],
  ["brand_positioning", "Positioning"],
  ["brand_personality", "Brand personality"],
  ["brand_tone", "Brand tone"],
  ["brand_price_band", "Price band"],
  ["brand_required_elements", "Required elements"],
  ["brand_avoid", "Avoid"],
  ["brand_name", "Brand name"],
  ["campaign_name", "Campaign name"],
  ["campaign_goal", "Goal"],
  ["campaign_audience", "Audience"],
  ["campaign_core_message", "Core message"],
  ["campaign_platform", "Channel"],
  ["campaign_aspect_ratio", "Format"],
  ["campaign_duration", "Duration"],
  ["campaign_cta", "Call to action"],
  ["campaign_non_goals", "Non-goals"],
];
const SLOT_ORDER = new Map(SLOT_LABELS.map(([slotId], index) => [slotId, index]));
const SLOT_LABEL_BY_ID = new Map(SLOT_LABELS);

// Guided answers carry the Brand stage only inside their interaction id.
const BRAND_INTERACTION_STAGE = /_brand_([a-z-]+?)_\d+_/;

function stageIndex(stage: BrandStageV2 | string): number {
  return STAGE_ORDER.indexOf(stage as BrandStageV2);
}

function slotRows(values: readonly BrandSlotValueV1[], stage: BrandStageV2): BrandSummaryRow[] {
  return values
    .filter((slot) => slot.stage === stage && slot.value.trim())
    .sort((left, right) => (
      (SLOT_ORDER.get(left.slot_id) ?? Number.MAX_SAFE_INTEGER)
      - (SLOT_ORDER.get(right.slot_id) ?? Number.MAX_SAFE_INTEGER)
    ))
    .map((slot) => ({
      key: slot.slot_id,
      label: SLOT_LABEL_BY_ID.get(slot.slot_id) ?? null,
      fallbackLabel: slot.slot_id.replace(/^(brand|campaign)_/, "").replaceAll("_", " "),
      value: slot.value.trim(),
    }));
}

function latestConfirmation(values: readonly BrandSlotValueV1[], stage: BrandStageV2): number | null {
  const times = values
    .filter((slot) => slot.stage === stage && slot.confirmed_at)
    .map((slot) => Date.parse(slot.confirmed_at!))
    .filter((time) => Number.isFinite(time));
  return times.length ? Math.max(...times) : null;
}

function answerStage(answer: GuidedAnswerBubbleV1): number {
  const match = BRAND_INTERACTION_STAGE.exec(answer.interaction_id);
  return match ? stageIndex(match[1]!) : -1;
}

/**
 * Place a summary after the conversation that preceded its confirmation and before any
 * Brand answer from a later stage.
 */
function summarySequence(
  stage: BrandSummaryStage,
  confirmedAt: number | null,
  items: readonly ChatTimelineItemV2[],
  answers: readonly GuidedAnswerBubbleV1[],
): number {
  // Persisted answers are positioned through their display bubbles, not their raw cursor.
  const anchors = items.filter((item) => !isPersistedGuidedAnswerMessage(item));
  const ownStage = stageIndex(stage);
  const laterAnswers = answers.filter((answer) => answerStage(answer) > ownStage);
  const earlierAnswers = answers.filter((answer) => {
    const index = answerStage(answer);
    return index >= 0 && index < ownStage;
  });
  let lower = Math.max(0, ...earlierAnswers.map((answer) => answer.sequence));
  let upper = laterAnswers.length ? Math.min(...laterAnswers.map((answer) => answer.sequence)) : Number.POSITIVE_INFINITY;
  if (confirmedAt !== null) {
    const timed = anchors.flatMap((item) => {
      const time = "created_at" in item ? Date.parse(item.created_at) : Number.NaN;
      return Number.isFinite(time) ? [{ sequence: item.sequence, time }] : [];
    });
    const before = timed.filter((item) => item.time <= confirmedAt);
    const after = timed.filter((item) => item.time > confirmedAt);
    lower = Math.max(lower, ...before.map((item) => item.sequence));
    upper = Math.min(upper, ...after.map((item) => item.sequence));
  }
  if (!Number.isFinite(upper) || upper <= lower) upper = lower + 1;
  // Brand form and campaign can share one gap; keep them in stage order inside it.
  const fraction = stage === "brand-memory" ? 0.25 : 0.5;
  return lower + (upper - lower) * fraction;
}

export function projectBrandSummaries(
  decisions: BrandDecisionPanelV1 | null | undefined,
  items: readonly ChatTimelineItemV2[],
  answers: readonly GuidedAnswerBubbleV1[],
): BrandSummaryExchange[] {
  if (!decisions || decisions.mode !== "brand") return [];
  const current = stageIndex(decisions.journey.stage);
  const passed = (stage: BrandStageV2) => current > stageIndex(stage);
  const summaries: BrandSummaryExchange[] = [];

  const formStages: Array<[BrandSummaryStage, BrandSlotValueV1[]]> = [
    ["brand-memory", decisions.brand_profile?.values ?? decisions.slot_values],
    ["campaign", decisions.campaign_brief?.values ?? decisions.slot_values],
  ];
  for (const [stage, values] of formStages) {
    if (!passed(stage)) continue;
    const rows = slotRows(values, stage);
    if (!rows.length) continue;
    summaries.push({
      key: `brand-summary:${stage}`,
      stage,
      rows,
      sequence: summarySequence(stage, latestConfirmation(values, stage), items, answers),
    });
  }

  const skills = decisions.skill_stack?.entries.filter((entry) => entry.selected) ?? [];
  const skillStage = decisions.early_skills_confirmed ? "skill-stack-early" : "skill-stack";
  if (passed(skillStage) && skills.length) {
    const answer = answers
      .filter((entry) => /_brand_skill-stack(?:-early)?_\d+(?:_|$)/.test(entry.interaction_id))
      .reduce<GuidedAnswerBubbleV1 | undefined>((latest, entry) => (
        !latest || entry.sequence > latest.sequence ? entry : latest
      ), undefined);
    const campaign = summaries.find((summary) => summary.stage === "campaign");
    let sequence = answer?.sequence ?? summarySequence(skillStage, null, items, answers);
    if (!answer && campaign) {
      // Older histories without a Skill exchange use Campaign as their anchor.
      const nextSequence = Math.min(...[...items, ...answers, ...summaries]
        .map((entry) => entry.sequence).filter((value) => value > campaign.sequence));
      sequence = campaign.sequence + (Number.isFinite(nextSequence) ? nextSequence - campaign.sequence : 1) / 2;
    }
    summaries.push({
      key: "brand-summary:skill-stack",
      stage: skillStage,
      answer,
      rows: [...skills]
        .sort((left, right) => (left.skill_kind === right.skill_kind ? 0 : left.skill_kind === "creative_method" ? -1 : 1))
        .map((entry) => ({
          key: `${entry.skill_kind}:${entry.skill_id}`,
          label: entry.skill_kind === "creative_method" ? "Creative method" : "Audiovisual style",
          fallbackLabel: entry.skill_kind,
          value: entry.title,
        })),
      sequence,
    });
  }
  return summaries;
}
