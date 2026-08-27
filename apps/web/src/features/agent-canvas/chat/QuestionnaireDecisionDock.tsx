import { useId, useState } from "react";

import type {
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
} from "../../../types-v2.ts";
import { DecisionDockFrame } from "./DecisionDockFrame.tsx";
import type { DecisionDockIssue } from "./decisionDockIssue.ts";

type QuestionnaireAnswer = {
  kind: "option" | "custom" | "skip";
  value?: string;
};

export interface QuestionnaireDecisionDockProps {
  interaction: GuidedInteractionV1;
  pending: boolean;
  issue: DecisionDockIssue | null;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
}

function answerIsValid(answer: QuestionnaireAnswer | undefined): boolean {
  return Boolean(answer) && (answer?.kind !== "custom" || Boolean(answer.value?.trim()));
}

export function QuestionnaireDecisionDock({
  interaction,
  pending,
  issue,
  onSubmit,
}: QuestionnaireDecisionDockProps) {
  const questions = interaction.content.content_kind === "questionnaire"
    ? interaction.content.questions
    : null;
  const fieldIdBase = useId();
  const [answers, setAnswers] = useState<Record<string, QuestionnaireAnswer>>({});

  if (!questions) return null;

  const answeredCount = questions.filter((question) => (
    answerIsValid(answers[question.question_id])
  )).length;
  const complete = answeredCount > 0 && questions.every((question) => (
    !question.required || answerIsValid(answers[question.question_id])
  ));
  const canSubmit = complete && interaction.allowed_actions.includes("answer");

  const submit = () => {
    if (!canSubmit) return;
    const answersPayload: Extract<
      GuidedInteractionSubmitRequestV1,
      { submission_kind: "questionnaire" }
    >["answers"] = [];

    questions.forEach((question) => {
      const answer = answers[question.question_id];
      if (!answerIsValid(answer) || !answer) return;
      if (answer.kind === "skip") {
        answersPayload.push({ answer_kind: "skip", question_id: question.question_id });
        return;
      }
      if (answer.kind === "custom") {
        answersPayload.push({
          answer_kind: "custom",
          question_id: question.question_id,
          value: answer.value!.trim(),
        });
        return;
      }
      answersPayload.push({
        answer_kind: "option",
        question_id: question.question_id,
        option_id: answer.value!,
      });
    });

    void onSubmit({
      submission_kind: "questionnaire",
      expected_interaction_revision: interaction.revision,
      expected_session_revision: interaction.expected_session_revision,
      answers: answersPayload,
    });
  };

  return (
    <DecisionDockFrame
      title={interaction.title}
      context={interaction.context}
      pending={pending}
      issue={issue}
      footerSummary={`${answeredCount} of ${questions.length} answered`}
      submitLabel="Submit answers"
      submitDisabled={!canSubmit}
      onSubmit={submit}
    >
      <div className="agent-chat__decision-dock-questions">
        {questions.map((question) => {
          const answer = answers[question.question_id];
          const fieldIssue = issue?.fieldId === question.question_id ? issue : null;
          const errorId = `${fieldIdBase}-${question.question_id}-error`;
          const isDuration = question.question_id === "production_duration_seconds";

          return (
            <fieldset key={question.question_id} disabled={pending}>
              <legend>{question.prompt}</legend>
              <div className="agent-chat__decision-dock-question-options">
                {question.options.map((option) => (
                  <label key={option.option_id}>
                    <input
                      type="radio"
                      name={question.question_id}
                      disabled={pending}
                      checked={answer?.kind === "option" && answer.value === option.option_id}
                      onChange={() => setAnswers((current) => ({
                        ...current,
                        [question.question_id]: { kind: "option", value: option.option_id },
                      }))}
                    />
                    <span>
                      <strong>
                        {option.title}
                        {option.recommended ? <em>Recommended</em> : null}
                      </strong>
                      <small>{option.summary}</small>
                    </span>
                  </label>
                ))}
              </div>

              {question.allow_custom ? (
                <label className="agent-chat__decision-dock-question-custom">
                  <span>{isDuration ? "Custom duration in seconds" : "Custom answer"}</span>
                  <input
                    aria-label={isDuration ? "Custom duration in seconds" : `Custom answer for ${question.prompt}`}
                    aria-invalid={fieldIssue ? "true" : undefined}
                    aria-describedby={fieldIssue ? errorId : undefined}
                    type={isDuration ? "number" : "text"}
                    disabled={pending}
                    inputMode={isDuration ? "numeric" : undefined}
                    value={answer?.kind === "custom" ? answer.value ?? "" : ""}
                    placeholder={isDuration ? "Duration in seconds" : "Type your answer"}
                    onChange={(event) => setAnswers((current) => ({
                      ...current,
                      [question.question_id]: { kind: "custom", value: event.target.value },
                    }))}
                  />
                  {fieldIssue ? (
                    <small id={errorId} className="agent-chat__decision-dock-field-error">
                      {fieldIssue.summary}
                    </small>
                  ) : null}
                </label>
              ) : null}

              {question.allow_skip && interaction.allowed_actions.includes("skip") ? (
                <button
                  type="button"
                  disabled={pending}
                  aria-pressed={answer?.kind === "skip"}
                  className={answer?.kind === "skip" ? "is-selected" : undefined}
                  onClick={() => setAnswers((current) => ({
                    ...current,
                    [question.question_id]: { kind: "skip" },
                  }))}
                >
                  Skip {question.prompt}
                </button>
              ) : null}
            </fieldset>
          );
        })}
      </div>
    </DecisionDockFrame>
  );
}
