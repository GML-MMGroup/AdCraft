import type {
  ChatMessageV2,
  ChatTimelineItemV2,
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
} from "../../../types-v2.ts";

export interface GuidedAnswerBubbleV1 {
  bubble_id: string;
  submission_id?: string;
  interaction_id: string;
  question_id: string;
  label: string;
  value: string;
  sequence: number;
}

export function buildGuidedAnswerBubbles(
  interaction: GuidedInteractionV1,
  request: GuidedInteractionSubmitRequestV1,
  anchorSequence: number,
): GuidedAnswerBubbleV1[] {
  if (
    interaction.content.content_kind === "concept_choice"
    && request.submission_kind === "concept_choice"
  ) {
    const selectedOption = request.option_id
      ? interaction.content.options.find((option) => option.option_id === request.option_id)
      : null;
    const customText = request.custom_text?.trim() || null;
    let value: string | null = null;
    if (request.action === "custom") {
      value = customText;
    } else if (selectedOption) {
      value = selectedOption.title;
    } else if (request.action === "defer") {
      value = "Deferred";
    } else if (request.action === "exclude") {
      value = "Excluded";
    } else if (request.action === "delegate") {
      value = "Delegated";
    }
    if (!value) return [];

    return [{
      bubble_id: `guided-answer:${interaction.interaction_id}:concept-choice`,
      interaction_id: interaction.interaction_id,
      question_id: interaction.content.action_id,
      label: interaction.title || interaction.context || "Decision",
      value,
      sequence: anchorSequence + 0.01,
    }];
  }

  if (
    interaction.content.content_kind !== "questionnaire"
    || request.submission_kind !== "questionnaire"
  ) return [];

  const answers = new Map(
    request.answers.map((answer) => [answer.question_id, answer]),
  );
  const bubbles: GuidedAnswerBubbleV1[] = [];

  interaction.content.questions.forEach((question) => {
    const answer = answers.get(question.question_id);
    if (!answer) return;

    let value: string | null = null;
    if (answer.answer_kind === "custom") {
      value = answer.value.trim() || null;
    } else if (answer.answer_kind === "option") {
      value = question.options.find((option) => option.option_id === answer.option_id)?.title ?? null;
    } else if (answer.answer_kind === "skip") {
      value = "Skipped";
    }
    if (!value) return;

    bubbles.push({
      bubble_id: `guided-answer:${interaction.interaction_id}:${question.question_id}`,
      interaction_id: interaction.interaction_id,
      question_id: question.question_id,
      label: question.prompt,
      value,
      sequence: anchorSequence + (bubbles.length + 1) / 100,
    });
  });

  return bubbles;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

/**
 * Restores accepted questionnaire answers from the authoritative timeline.
 * The answer text is never parsed; only the typed presentation metadata is used.
 */
export function parseGuidedAnswerBubbles(
  item: ChatTimelineItemV2 | ChatMessageV2,
): GuidedAnswerBubbleV1[] {
  if (item.item_type !== "message" || item.speaker !== "user") return [];

  const metadata = item.metadata;
  if (
    !isRecord(metadata)
    || metadata.presentation_kind !== "guided_answer"
    || metadata.schema_version !== 1
    || !isNonEmptyString(metadata.submission_id)
    || !isNonEmptyString(metadata.interaction_id)
    || !Array.isArray(metadata.answers)
    || metadata.answers.length === 0
  ) return [];

  const submissionId = metadata.submission_id.trim();
  const interactionId = metadata.interaction_id.trim();
  const questionIds = new Set<string>();
  const bubbles: GuidedAnswerBubbleV1[] = [];
  for (const answer of metadata.answers) {
    if (!isRecord(answer)) return [];
    if (
      !isNonEmptyString(answer.question_id)
      || !isNonEmptyString(answer.label)
      || !isNonEmptyString(answer.value)
    ) return [];
    const questionId = answer.question_id.trim();
    if (questionIds.has(questionId)) return [];
    questionIds.add(questionId);
    bubbles.push({
      bubble_id: `guided-answer:${submissionId}:${questionId}`,
      submission_id: submissionId,
      interaction_id: interactionId,
      question_id: questionId,
      label: answer.label.trim(),
      value: answer.value.trim(),
      sequence: item.sequence,
    });
  }
  return bubbles;
}

export function projectGuidedAnswerBubbles(
  items: ChatTimelineItemV2[],
): GuidedAnswerBubbleV1[] {
  const bubblesById = new Map<string, GuidedAnswerBubbleV1>();
  // Repaired Brand history is appended without renumbering server cursors.
  // Place its display bubbles at their original time among the existing messages.
  const brandHistory = items.filter((item): item is ChatMessageV2 => item.item_type === "message"
    && typeof item.metadata?.brand_decision_log_id === "string"
    && parseGuidedAnswerBubbles(item).length > 0)
    .sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at) || a.sequence - b.sequence);
  const brandItems = new Set<ChatTimelineItemV2>(brandHistory);
  const anchors = items.filter((item) => !brandItems.has(item));
  const displaySequences = new Map<ChatTimelineItemV2, number>();
  brandHistory.forEach((item, index) => {
    const next = anchors.find((anchor) => "created_at" in anchor
      && Date.parse(anchor.created_at) > Date.parse(item.created_at));
    if (!next) return;
    const previousSequence = Math.max(0, ...anchors.filter((anchor) => anchor.sequence < next.sequence).map((anchor) => anchor.sequence));
    displaySequences.set(item, previousSequence + (next.sequence - previousSequence) * (index + 1) / (brandHistory.length + 1));
  });
  items.forEach((item) => {
    parseGuidedAnswerBubbles(item).forEach((bubble) => {
      bubblesById.set(bubble.bubble_id, { ...bubble, sequence: displaySequences.get(item) ?? bubble.sequence });
    });
  });
  return [...bubblesById.values()].sort((left, right) => left.sequence - right.sequence);
}

export function isPersistedGuidedAnswerMessage(item: ChatTimelineItemV2): boolean {
  return parseGuidedAnswerBubbles(item).length > 0;
}
