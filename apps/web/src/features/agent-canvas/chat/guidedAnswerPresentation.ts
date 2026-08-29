import type {
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
} from "../../../types-v2.ts";

export interface GuidedAnswerBubbleV1 {
  bubble_id: string;
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
