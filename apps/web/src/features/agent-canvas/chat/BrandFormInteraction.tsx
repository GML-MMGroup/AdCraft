import { useTranslation } from "../../../i18n/useTranslation";
import { useId, useMemo, useRef, useState } from "react";

import type {
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
} from "../../../types-v2.ts";
import { DecisionDockFrame } from "./DecisionDockFrame.tsx";
import type { DecisionDockIssue } from "./decisionDockIssue.ts";

export type BrandFormAnswer = {
  selectedOptionId: string;
  customText: string;
};

export type BrandFormAnswers = Record<string, BrandFormAnswer>;

export interface BrandFormInteractionProps {
  interaction: GuidedInteractionV1;
  pending: boolean;
  disabled?: boolean;
  issue: DecisionDockIssue | null;
  answers?: BrandFormAnswers;
  onAnswersChange?: (answers: BrandFormAnswers) => void;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
}

function answerIsComplete(
  row: Extract<GuidedInteractionV1["content"], { content_kind: "brand_form" }>["rows"][number],
  answer: BrandFormAnswer | undefined,
): boolean {
  if (!answer?.selectedOptionId || !row.options.some((option) => option.option_id === answer.selectedOptionId)) return false;
  return answer.selectedOptionId !== row.custom_option_id || Boolean(answer.customText.trim());
}

export function BrandFormInteraction({
  interaction,
  pending,
  disabled = false,
  issue,
  answers: controlledAnswers,
  onAnswersChange,
  onSubmit,
}: BrandFormInteractionProps) {
  const t = useTranslation("en-US");
  const content = interaction.content.content_kind === "brand_form" ? interaction.content : null;
  const [internalAnswers, setInternalAnswers] = useState<BrandFormAnswers>({});
  const drafts = controlledAnswers ?? internalAnswers;
  // Prefills remain editable drafts until the user explicitly selects an option.
  const answers = useMemo<BrandFormAnswers>(() => Object.fromEntries(
    content?.rows.map((row) => [row.question_id, drafts[row.question_id] ?? {
      selectedOptionId: "",
      customText: row.prefill_value ?? "",
    }]) ?? [],
  ), [content, drafts]);
  const [submitted, setSubmitted] = useState(false);
  const submittedState = submitted || interaction.status === "submitted";
  const fieldIdBase = useId();
  const rowRefs = useRef(new Map<string, HTMLElement>());

  const answeredCount = useMemo(
    () => content?.rows.filter((row) => answerIsComplete(row, answers[row.question_id])).length ?? 0,
    [answers, content],
  );
  if (!content) return null;

  const firstUnansweredIndex = content.rows.findIndex((row) => !answerIsComplete(row, answers[row.question_id]));
  const firstUnanswered = firstUnansweredIndex >= 0 ? content.rows[firstUnansweredIndex]! : null;

  // Scroll only the dock body; scrollIntoView would also scroll the clipped
  // overlay and panel ancestors and shift the whole card out of place.
  const jumpToRow = (questionId: string) => {
    const row = rowRefs.current.get(questionId);
    const body = row?.closest(".agent-chat__decision-dock-body");
    if (!row || !body) return;
    body.scrollBy?.({ top: row.getBoundingClientRect().top - body.getBoundingClientRect().top, behavior: "smooth" });
    row.querySelector<HTMLInputElement>("input[type=radio]:not(:disabled)")?.focus({ preventScroll: true });
  };

  const complete = content.rows.length > 0 && content.rows.every((row) => answerIsComplete(row, answers[row.question_id]));
  const canSubmit = complete
    && (interaction.allowed_actions.includes("select") || interaction.allowed_actions.includes("custom"))
    && !submittedState
    && !pending
    && !disabled;

  const setAnswers = (update: (current: BrandFormAnswers) => BrandFormAnswers) => {
    const next = update(answers);
    if (onAnswersChange) onAnswersChange(next);
    else setInternalAnswers(next);
  };

  const updateAnswer = (questionId: string, selectedOptionId: string) => {
    setAnswers((current) => ({
      ...current,
      [questionId]: { selectedOptionId, customText: current[questionId]?.customText ?? "" },
    }));
    setSubmitted(false);
  };

  const updateCustomText = (questionId: string, customText: string) => {
    setAnswers((current) => ({
      ...current,
      [questionId]: {
        selectedOptionId: current[questionId]?.selectedOptionId ?? "",
        customText,
      },
    }));
    setSubmitted(false);
  };

  const submit = async () => {
    if (!canSubmit) return;
    const request: Extract<GuidedInteractionSubmitRequestV1, { submission_kind: "brand_form" }> = {
      submission_kind: "brand_form",
      form_id: content.form_id,
      expected_interaction_revision: interaction.revision,
      expected_session_revision: interaction.expected_session_revision,
      confirm: true,
      answers: content.rows.map((row) => {
        const answer = answers[row.question_id]!;
        const base = {
          question_id: row.question_id,
          selected_option_id: answer.selectedOptionId,
        };
        return answer.selectedOptionId === row.custom_option_id
          ? { ...base, custom_text: answer.customText.trim() }
          : base;
      }),
    };
    const accepted = await onSubmit(request);
    if (accepted) setSubmitted(true);
  };

  return (
    <DecisionDockFrame
      className={`agent-chat__decision-dock--brand-form${content.rows.some(row => row.options.filter(option => option.option_id !== row.custom_option_id).length > 3) ? " is-expanded" : ""}`}
      title={content.title}
      context={content.instructions}
      pending={pending || submittedState || disabled}
      issue={issue}
      footerSummary={(
        <>
          {t("{count} of {total} answered", { count: answeredCount, total: content.rows.length })}
          {firstUnanswered && !submittedState ? (
            <button
              type="button"
              className="agent-chat__brand-form-jump"
              onClick={() => jumpToRow(firstUnanswered.question_id)}
            >
              {t("Go to question {number}", { number: String(firstUnansweredIndex + 1).padStart(2, "0") })}
            </button>
          ) : null}
        </>
      )}
      submitLabel={t("Confirm entire form")}
      submitDisabled={!canSubmit}
      onSubmit={() => void submit()}
    >
      <div className="agent-chat__brand-form" data-testid="brand-form">
        <div className="agent-chat__brand-form-intro">
          <span>{t(content.stage === "brand-memory" ? "Brand Memory" : "Campaign")}</span>
        </div>
        <div className="agent-chat__brand-form-table" role="table" aria-label={content.title ?? interaction.title}>
          {content.rows.map((row, rowIndex) => {
            const answer = answers[row.question_id];
            const rowIssue = issue?.fieldId === row.question_id ? issue : null;
            const errorId = `${fieldIdBase}-${row.question_id}-error`;
            const customSelected = answer?.selectedOptionId === row.custom_option_id;
            const customLabel = row.options.find((option) => option.option_id === row.custom_option_id)?.label || t("Custom");
            // Unselected prefills stay visible as editable drafts; otherwise the
            // field only appears once Custom is chosen.
            const showCustomInput = customSelected || row.prefill_value != null || Boolean(rowIssue);
            return (
              <section
                className={`agent-chat__brand-form-row${answerIsComplete(row, answer) ? " is-answered" : ""}`}
                key={row.question_id}
                role="row"
                ref={(element) => {
                  if (element) rowRefs.current.set(row.question_id, element);
                  else rowRefs.current.delete(row.question_id);
                }}
              >
                <div className="agent-chat__brand-form-prompt" role="rowheader">
                  <span className="agent-chat__brand-form-row-number">{String(rowIndex + 1).padStart(2, "0")}</span>
                  <strong>{row.prompt}</strong>
                  {row.required ? <em>{t("Required")}</em> : null}
                </div>
                <div className="agent-chat__brand-form-options" role="radiogroup" aria-label={row.prompt}>
                  {row.options.filter((option) => option.option_id !== row.custom_option_id).map((option) => {
                    const selected = answer?.selectedOptionId === option.option_id;
                    return (
                      <label
                        className={`agent-chat__brand-form-option${selected ? " is-selected" : ""}`}
                        key={option.option_id}
                      >
                        <input
                          type="radio"
                          name={`${interaction.interaction_id}-${row.question_id}`}
                          value={option.option_id}
                          checked={selected}
                          disabled={pending || submittedState || disabled}
                          onChange={() => updateAnswer(row.question_id, option.option_id)}
                        />
                        <span className="agent-chat__brand-form-option-mark" aria-hidden="true">✓</span>
                        <span className="agent-chat__brand-form-option-copy">
                          <strong>{option.label}</strong>
                          {option.why ? <small>{option.why}</small> : null}
                        </span>
                      </label>
                    );
                  })}
                  <label className={`agent-chat__brand-form-option is-custom${customSelected ? " is-selected" : ""}`}>
                    <input
                      type="radio"
                      name={`${interaction.interaction_id}-${row.question_id}`}
                      value={row.custom_option_id}
                      checked={customSelected}
                      disabled={pending || submittedState || disabled}
                      onChange={() => updateAnswer(row.question_id, row.custom_option_id)}
                    />
                    <span className="agent-chat__brand-form-option-mark" aria-hidden="true">✓</span>
                    <span className="agent-chat__brand-form-option-copy">
                      <strong>{customLabel}</strong>
                      <small>{t("Describe the direction you want to keep.")}</small>
                    </span>
                  </label>
                </div>
                {showCustomInput ? <label className="agent-chat__brand-form-custom-input">
                  <span>{t("Custom content")}</span>
                  <input
                    aria-label={t("Custom content: {prompt}", { prompt: row.prompt })}
                    aria-describedby={rowIssue ? errorId : undefined}
                    aria-invalid={rowIssue ? "true" : undefined}
                    type="text"
                    value={answer?.customText ?? ""}
                    placeholder={t("Submitted only when Custom is selected")}
                    disabled={pending || submittedState || disabled || (row.prefill_value == null && !customSelected)}
                    onChange={(event) => updateCustomText(row.question_id, event.target.value)}
                  />
                  {!customSelected && answer?.customText.trim() ? (
                    <small className="agent-chat__brand-form-custom-hint">
                      {t("Select “{option}” to submit this text.", { option: customLabel })}
                    </small>
                  ) : null}
                  {rowIssue ? <small id={errorId} className="agent-chat__decision-dock-field-error">{rowIssue.summary}</small> : null}
                </label> : null}
              </section>
            );
          })}
        </div>
        {submittedState ? <p className="agent-chat__brand-form-status" role="status">{t("Confirmed. Preparing the next stage.")}</p> : null}
      </div>
    </DecisionDockFrame>
  );
}
