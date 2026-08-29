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
  items.forEach((item) => {
    parseGuidedAnswerBubbles(item).forEach((bubble) => {
      bubblesById.set(bubble.bubble_id, bubble);
    });
  });
  return [...bubblesById.values()].sort((left, right) => left.sequence - right.sequence);
}

export function isPersistedGuidedAnswerMessage(item: ChatTimelineItemV2): boolean {
  return parseGuidedAnswerBubbles(item).length > 0;
}
