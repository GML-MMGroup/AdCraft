import { useMemo, useState, type ReactNode } from "react";

import type {
  GuidedInteractionActionV1,
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
} from "../../../types-v2.ts";
import { ConceptChoiceSubmitControls } from "./ConceptChoiceSubmitControls.tsx";

const ACTION_LABELS: Record<GuidedInteractionActionV1, string> = {
  answer: "Submit answers",
  select: "Select",
  custom: "Use custom direction",
  skip: "Skip",
  revise: "Revise",
  defer: "Defer",
  exclude: "Exclude",
  delegate: "Delegate",
  accept: "Accept",
  retry: "Retry",
  replace: "Replace",
};

function isAllowed(interaction: GuidedInteractionV1, action: GuidedInteractionActionV1) {
  return interaction.allowed_actions.includes(action);
}

export function GuidedInteractionCard({
  interaction,
  pending,
  onSubmit,
}: {
  interaction: GuidedInteractionV1;
  pending: boolean;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
}) {
  if (interaction.status !== "open") return null;
  if (interaction.content.content_kind === "questionnaire") {
    return <QuestionnaireInteraction interaction={interaction} pending={pending} onSubmit={onSubmit} />;
  }
  if (interaction.content.content_kind === "concept_choice") {
    return <ConceptInteraction interaction={interaction} pending={pending} onSubmit={onSubmit} />;
  }
  return <MediaReviewInteraction interaction={interaction} pending={pending} onSubmit={onSubmit} />;
}

function InteractionFrame({
  interaction,
  children,
}: {
  interaction: GuidedInteractionV1;
  children: ReactNode;
}) {
  return (
    <article className="agent-chat__guided-interaction" aria-label={interaction.title}>
      <header>
        <strong>{interaction.title}</strong>
        <span>{interaction.response_locale}</span>
      </header>
      <p>{interaction.context}</p>
      {children}
    </article>
  );
}

function QuestionnaireInteraction({
  interaction,
  pending,
  onSubmit,
}: {
  interaction: GuidedInteractionV1;
  pending: boolean;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
}) {
  const questions = interaction.content.content_kind === "questionnaire" ? interaction.content.questions : [];
  const [answers, setAnswers] = useState<Record<string, { kind: "option" | "custom" | "skip"; value?: string }>>({});
  const complete = questions.every((question) => !question.required || answers[question.question_id]);

  return (
    <InteractionFrame interaction={interaction}>
      <div className="agent-chat__guided-questions">
        {questions.map((question) => {
          const answer = answers[question.question_id];
          return (
            <fieldset key={question.question_id} disabled={pending}>
              <legend>{question.prompt}</legend>
              {question.options.map((option) => (
                <label key={option.option_id}>
                  <input
                    type="radio"
                    name={question.question_id}
                    checked={answer?.kind === "option" && answer.value === option.option_id}
                    onChange={() => setAnswers((current) => ({
                      ...current,
                      [question.question_id]: { kind: "option", value: option.option_id },
                    }))}
                  />
                  <span><strong>{option.title}</strong><small>{option.summary}</small></span>
                </label>
              ))}
              {question.allow_custom ? (
                <label className="agent-chat__guided-custom">
                  <input
                    type="text"
                    value={answer?.kind === "custom" ? answer.value ?? "" : ""}
                    placeholder="Your direction"
                    onChange={(event) => setAnswers((current) => ({
                      ...current,
                      [question.question_id]: { kind: "custom", value: event.target.value },
                    }))}
                  />
                </label>
              ) : null}
              {question.allow_skip && isAllowed(interaction, "skip") ? (
                <button type="button" onClick={() => setAnswers((current) => ({
                  ...current,
                  [question.question_id]: { kind: "skip" },
                }))}>Skip</button>
              ) : null}
            </fieldset>
          );
        })}
      </div>
      <button
        type="button"
        disabled={pending || !complete || !isAllowed(interaction, "answer")}
        onClick={() => {
          const answersPayload: Extract<GuidedInteractionSubmitRequestV1, { submission_kind: "questionnaire" }>["answers"] = [];
          questions.forEach((question) => {
            const answer = answers[question.question_id];
            if (!answer) return;
            if (answer.kind === "skip") {
              answersPayload.push({ answer_kind: "skip", question_id: question.question_id });
              return;
            }
            if (answer.kind === "custom") {
              if (answer.value?.trim()) answersPayload.push({ answer_kind: "custom", question_id: question.question_id, value: answer.value.trim() });
              return;
            }
            answersPayload.push({ answer_kind: "option", question_id: question.question_id, option_id: answer.value! });
          });
          if (answersPayload.length) void onSubmit({
            submission_kind: "questionnaire",
            expected_interaction_revision: interaction.revision,
            expected_session_revision: interaction.expected_session_revision,
            answers: answersPayload,
          });
        }}
      >
        {pending ? "Submitting" : ACTION_LABELS.answer}
      </button>
    </InteractionFrame>
  );
}

function ConceptInteraction({ interaction, pending, onSubmit }: {
  interaction: GuidedInteractionV1;
  pending: boolean;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
}) {
  const content = interaction.content.content_kind === "concept_choice" ? interaction.content : null;
  const options = content?.options ?? [];
  const [optionId, setOptionId] = useState<string | null>(null);
  const submit = (
    action: "select" | "custom" | "defer" | "exclude" | "delegate",
    customText: string | null,
  ) => {
    if (action === "select" && !optionId) return;
    void onSubmit({
      submission_kind: "concept_choice",
      expected_interaction_revision: interaction.revision,
      expected_session_revision: interaction.expected_session_revision,
      action,
      option_id: action === "select" ? optionId : null,
      custom_text: action === "custom" ? customText : null,
    });
  };
  return (
    <InteractionFrame interaction={interaction}>
      <div className="agent-chat__guided-options">
        {options.map((option) => (
          <button type="button" key={option.option_id} disabled={pending} className={optionId === option.option_id ? "is-selected" : ""} onClick={() => setOptionId(option.option_id)}>
            <strong>{option.title}{option.recommended ? <em>Recommended</em> : null}</strong><span>{option.summary}</span>
            {option.difference_tags.length ? <small>{option.difference_tags.join(" · ")}</small> : null}
            {option.reference_preview.length ? <em>{option.reference_preview.map((reference) => reference.display_name).join(" · ")}</em> : null}
          </button>
        ))}
      </div>
      <ConceptChoiceSubmitControls
        allowedActions={interaction.allowed_actions}
        allowCustom={content?.allow_custom ?? false}
        allowExclusion={content?.allow_exclusion ?? false}
        busy={pending}
        selectedOptionId={optionId}
        onSubmit={submit}
      />
    </InteractionFrame>
  );
}

function MediaReviewInteraction({ interaction, pending, onSubmit }: {
  interaction: GuidedInteractionV1;
  pending: boolean;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
}) {
  const content = interaction.content.content_kind === "media_review" ? interaction.content : null;
  const [instruction, setInstruction] = useState("");
  const actions = useMemo(() => interaction.allowed_actions.filter((action) => ["accept", "retry", "replace", "exclude"].includes(action)), [interaction.allowed_actions]);
  return <InteractionFrame interaction={interaction}>
    {content ? <p className="agent-chat__guided-media-summary">{content.summary}</p> : null}
    {isAllowed(interaction, "replace") ? <input value={instruction} disabled={pending} placeholder="Describe the replacement" onChange={(event) => setInstruction(event.target.value)} /> : null}
    <div className="agent-chat__guided-actions">
      {actions.map((action) => (
        <button type="button" key={action} disabled={pending || (action === "replace" && !instruction.trim())} onClick={() => void onSubmit({ submission_kind: "media_review", expected_interaction_revision: interaction.revision, expected_session_revision: interaction.expected_session_revision, action: action as "accept" | "retry" | "replace" | "exclude", instruction: action === "replace" ? instruction.trim() : null })}>
          {pending ? "Submitting" : ACTION_LABELS[action]}
        </button>
      ))}
    </div>
  </InteractionFrame>;
}
