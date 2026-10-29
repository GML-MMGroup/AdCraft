import type { ChatTimelineItemV2 } from "../../../types-v2.ts";
import type { UiMessageKey } from "../../../i18n/uiMessages.ts";
import type { BrandDecisionPanelV1, BrandSlotValueV1, BrandStageV2 } from "../brand/brandDecisions.ts";
import { isPersistedGuidedAnswerMessage, type GuidedAnswerBubbleV1 } from "./guidedAnswerPresentation.ts";

export type BrandSummaryStage = "brand-memory" | "campaign" | "skill-stack";

export interface BrandSummaryRow {
  key: string;
  label: UiMessageKey | null;
  fallbackLabel: string;
  value: string;
}

/**
 * Foundation questions appear when their guided stage starts, before the form loads.
 * Confirmed choices are rebuilt from the Brand decisions read model and appended
 * to the same exchange once that stage is complete. Pending questions have no rows.
 */
export interface BrandSummaryExchange {
  key: string;
  stage: BrandSummaryStage;
  question: UiMessageKey;
  rows: BrandSummaryRow[];
  sequence: number;
}

const STAGE_ORDER: BrandStageV2[] = [
  "brand-memory",
  "campaign",
  "hypothesis",
  "adspec",
  "skill-stack",
  "treatment",
  "production",
];

const QUESTIONS: Record<BrandSummaryStage, UiMessageKey> = {
  "brand-memory": "Let's start with the brand basics. Which brand settings should this ad follow?",
  campaign: "Now the campaign brief: what should this ad achieve, and where will it run?",
  "skill-stack": "Which creative methods and audiovisual style should drive this ad?",
};

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
  { showCurrentQuestion = false }: { showCurrentQuestion?: boolean } = {},
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
    const awaitingAnswer = showCurrentQuestion && decisions.journey.stage === stage;
    if (!passed(stage) && !awaitingAnswer) continue;
    const rows = awaitingAnswer ? [] : slotRows(values, stage);
    if (!awaitingAnswer && !rows.length) continue;
    summaries.push({
      key: `brand-summary:${stage}`,
      stage,
      question: QUESTIONS[stage],
      rows,
      sequence: awaitingAnswer
        ? Math.max(0, ...items.map((item) => item.sequence), ...answers.map((answer) => answer.sequence)) + 1
        : summarySequence(stage, latestConfirmation(values, stage), items, answers),
    });
  }

  const skills = decisions.skill_stack?.entries.filter((entry) => entry.selected) ?? [];
  if (passed("skill-stack") && skills.length) {
    summaries.push({
      key: "brand-summary:skill-stack",
      stage: "skill-stack",
      question: QUESTIONS["skill-stack"],
      rows: [...skills]
        .sort((left, right) => (left.skill_kind === right.skill_kind ? 0 : left.skill_kind === "creative_method" ? -1 : 1))
        .map((entry) => ({
          key: `${entry.skill_kind}:${entry.skill_id}`,
          label: entry.skill_kind === "creative_method" ? "Creative method" : "Audiovisual style",
          fallbackLabel: entry.skill_kind,
          value: entry.title,
        })),
      sequence: summarySequence("skill-stack", null, items, answers),
    });
  }
  return summaries;
}
