import { useEffect, useMemo, useRef, useState } from "react";

import type {
  DecisionBundleActionRequestV2,
  DecisionBundleAnswerV2,
  DecisionBundleQuestionV2,
  DecisionBundleV2,
} from "../../../types-v2.ts";

type AnswerDraft = DecisionBundleAnswerV2;

function initialAnswers(bundle: DecisionBundleV2): Record<string, AnswerDraft> {
  return Object.fromEntries(bundle.answers.map((answer) => [answer.question_id, answer]));
}

function answerForQuestion(
  question: DecisionBundleQuestionV2,
  answers: Record<string, AnswerDraft>,
): AnswerDraft {
  return answers[question.question_id] ?? {
    question_id: question.question_id,
    selected_option_ids: [],
    custom_answer: null,
    skipped: false,
  };
}

function isComplete(answer: AnswerDraft) {
  return answer.skipped || answer.selected_option_ids.length > 0 || Boolean(answer.custom_answer?.trim());
}

export function DecisionBundleCard({
  bundle,
  pending,
  onApply,
}: {
  bundle: DecisionBundleV2;
  pending: boolean;
  onApply: (bundleId: string, request: DecisionBundleActionRequestV2) => Promise<void>;
}) {
  const bundleRef = useRef(bundle);
  bundleRef.current = bundle;
  const [answers, setAnswers] = useState<Record<string, AnswerDraft>>(() => initialAnswers(bundle));
  const editable = bundle.status === "open" && !pending;
  const complete = useMemo(
    () => bundle.questions.every((question) => isComplete(answerForQuestion(question, answers))),
    [answers, bundle.questions],
  );

  useEffect(() => {
    setAnswers(initialAnswers(bundleRef.current));
  }, [bundle.bundle_id, bundle.revision]);

  function updateAnswer(question: DecisionBundleQuestionV2, next: AnswerDraft) {
    setAnswers((current) => ({ ...current, [question.question_id]: next }));
  }

  function toggleOption(question: DecisionBundleQuestionV2, optionId: string) {
    const current = answerForQuestion(question, answers);
    const selected = question.selection_mode === "single"
      ? [optionId]
      : current.selected_option_ids.includes(optionId)
        ? current.selected_option_ids.filter((id) => id !== optionId)
        : [...current.selected_option_ids, optionId];
    updateAnswer(question, {
      ...current,
      selected_option_ids: selected,
      custom_answer: null,
      skipped: false,
    });
  }

  return (
    <article className={`agent-chat__decision-bundle is-${bundle.status}`}>
      <header>
        <strong>{bundle.title}</strong>
        <span>{bundle.status.replaceAll("_", " ")}</span>
      </header>
      <p>{bundle.introduction}</p>
      <div className="agent-chat__decision-questions">
        {bundle.questions.map((question) => {
          const answer = answerForQuestion(question, answers);
          return (
            <fieldset key={question.question_id} disabled={!editable}>
              <legend>{question.prompt}</legend>
              {question.options.map((option) => {
                const checked = answer.selected_option_ids.includes(option.option_id);
                return (
                  <label key={option.option_id}>
                    <input
                      type={question.selection_mode === "single" ? "radio" : "checkbox"}
                      name={question.question_id}
                      aria-label={option.label}
                      checked={checked}
                      onChange={() => toggleOption(question, option.option_id)}
                    />
                    <span>
                      <strong>{option.label}</strong>
                      <small>{option.description}</small>
                    </span>
                  </label>
                );
              })}
              {question.allow_custom_answer ? (
                <input
                  aria-label={`Custom answer: ${question.prompt}`}
                  value={answer.custom_answer ?? ""}
                  placeholder="Add a custom answer"
                  onChange={(event) => updateAnswer(question, {
                    ...answer,
                    selected_option_ids: [],
                    custom_answer: event.target.value || null,
                    skipped: false,
                  })}
                />
              ) : null}
              {question.allow_skip ? (
                <button
                  type="button"
                  className={answer.skipped ? "is-selected" : ""}
                  onClick={() => updateAnswer(question, {
                    ...answer,
                    selected_option_ids: [],
                    custom_answer: null,
                    skipped: !answer.skipped,
                  })}
                >
                  Skip this question
                </button>
              ) : null}
            </fieldset>
          );
        })}
      </div>
      {bundle.status === "open" ? (
        <div className="agent-chat__decision-actions">
          <button
            type="button"
            disabled={!editable || !complete}
            onClick={() => void onApply(bundle.bundle_id, {
              action: "submit",
              expected_revision: bundle.revision,
              answers: bundle.questions.map((question) => answerForQuestion(question, answers)),
            })}
          >
            Submit decisions
          </button>
          <button
            type="button"
            disabled={!editable}
            onClick={() => void onApply(bundle.bundle_id, {
              action: "skip_bundle",
              expected_revision: bundle.revision,
            })}
          >
            Skip these decisions
          </button>
        </div>
      ) : null}
    </article>
  );
}
