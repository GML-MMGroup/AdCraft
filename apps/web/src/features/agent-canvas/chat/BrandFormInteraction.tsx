import { useId, useMemo, useState } from "react";

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
  const content = interaction.content.content_kind === "brand_form" ? interaction.content : null;
  const [internalAnswers, setInternalAnswers] = useState<BrandFormAnswers>({});
  const drafts = controlledAnswers ?? internalAnswers;
  // Prefills are only text drafts. Overlay explicit edits (including an empty
  // string) so refreshing the same form never selects or confirms an answer.
  const answers = useMemo<BrandFormAnswers>(() => Object.fromEntries(
    content?.rows.map((row) => [row.question_id, drafts[row.question_id] ?? {
      selectedOptionId: "",
      customText: row.prefill_value ?? "",
    }]) ?? [],
  ), [content, drafts]);
  const [submitted, setSubmitted] = useState(false);
  const submittedState = submitted || interaction.status === "submitted";
  const fieldIdBase = useId();

  const answeredCount = useMemo(
    () => content?.rows.filter((row) => answerIsComplete(row, answers[row.question_id])).length ?? 0,
    [answers, content],
  );
  if (!content) return null;

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
      title={content.title}
      context={content.instructions}
      pending={pending || submittedState || disabled}
      issue={issue}
      footerSummary={`${answeredCount} of ${content.rows.length} answered`}
      submitLabel="确认整张表"
      submitDisabled={!canSubmit}
      onSubmit={() => void submit()}
    >
      <div className="agent-chat__brand-form" data-testid="brand-form">
        <div className="agent-chat__brand-form-intro">
          <span>{content.stage === "brand-memory" ? "Brand Memory" : "Campaign"}</span>
        </div>
        <div className="agent-chat__brand-form-table" role="table" aria-label={content.title ?? interaction.title}>
          {content.rows.map((row, rowIndex) => {
            const answer = answers[row.question_id];
            const rowIssue = issue?.fieldId === row.question_id ? issue : null;
            const errorId = `${fieldIdBase}-${row.question_id}-error`;
            return (
              <section className="agent-chat__brand-form-row" key={row.question_id} role="row">
                <div className="agent-chat__brand-form-prompt" role="rowheader">
                  <span className="agent-chat__brand-form-row-number">{String(rowIndex + 1).padStart(2, "0")}</span>
                  <strong>{row.prompt}</strong>
                  {row.required ? <em>必填</em> : null}
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
                  <label
                    className={`agent-chat__brand-form-option is-custom${answer?.selectedOptionId === row.custom_option_id ? " is-selected" : ""}`}
                  >
                    <input
                      type="radio"
                      name={`${interaction.interaction_id}-${row.question_id}`}
                      value={row.custom_option_id}
                      checked={answer?.selectedOptionId === row.custom_option_id}
                      disabled={pending || submittedState || disabled}
                      onChange={() => updateAnswer(row.question_id, row.custom_option_id)}
                    />
                    <span className="agent-chat__brand-form-option-mark" aria-hidden="true">✓</span>
                    <span className="agent-chat__brand-form-option-copy">
                      <strong>自定义</strong>
                      <small>写下你希望保留的方向。</small>
                    </span>
                  </label>
                </div>
                <label className="agent-chat__brand-form-custom-input">
                  <span>自定义内容</span>
                  <input
                    aria-label={`自定义内容：${row.prompt}`}
                    aria-describedby={rowIssue ? errorId : undefined}
                    aria-invalid={rowIssue ? "true" : undefined}
                    type="text"
                    value={answer?.customText ?? ""}
                    placeholder="仅在选择自定义后提交"
                    disabled={pending || submittedState || disabled || (row.prefill_value == null && answer?.selectedOptionId !== row.custom_option_id)}
                    onChange={(event) => updateCustomText(row.question_id, event.target.value)}
                  />
                  {rowIssue ? <small id={errorId} className="agent-chat__decision-dock-field-error">{rowIssue.summary}</small> : null}
                </label>
              </section>
            );
          })}
        </div>
        {submittedState ? <p className="agent-chat__brand-form-status" role="status">已确认，正在准备下一阶段。</p> : null}
      </div>
    </DecisionDockFrame>
  );
}
