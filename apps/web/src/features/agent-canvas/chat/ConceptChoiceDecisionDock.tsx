import { useEffect, useId, useMemo, useState } from "react";

import type {
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
  ProposedDraftReferenceV2,
} from "../../../types-v2.ts";
import { DecisionDockDisclosure, DecisionDockFrame } from "./DecisionDockFrame.tsx";
import type { DecisionDockIssue } from "./decisionDockIssue.ts";
import { GuidedInteractionReferences } from "./GuidedInteractionReferences.tsx";
import { guidedReferenceKey } from "./guidedInteractionReferences.ts";
import { ProposalOptionRow } from "./ProposalOptionRow.tsx";

type ConceptMode = "select" | "custom" | "defer" | "exclude" | "delegate";

export interface ConceptChoiceDecisionDockProps {
  interaction: GuidedInteractionV1;
  pending: boolean;
  issue: DecisionDockIssue | null;
  proposalReferences: ProposedDraftReferenceV2[] | null;
  referenceMediaUrls: Record<string, string>;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
}

function optionMarker(index: number): string {
  return index < 26 ? String.fromCharCode(65 + index) : String(index + 1);
}

function allowed(interaction: GuidedInteractionV1, action: string): boolean {
  return interaction.allowed_actions.includes(action as never);
}

export function ConceptChoiceDecisionDock({
  interaction,
  pending,
  issue,
  proposalReferences,
  referenceMediaUrls,
  onSubmit,
}: ConceptChoiceDecisionDockProps) {
  const content = interaction.content.content_kind === "concept_choice" ? interaction.content : null;
  const referencesId = useId();
  const moreId = useId();
  const [optionId, setOptionId] = useState<string | null>(null);
  const [mode, setMode] = useState<ConceptMode>("select");
  const [customText, setCustomText] = useState("");
  const [referencesOpen, setReferencesOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [excludedOptionalReferenceKeys, setExcludedOptionalReferenceKeys] = useState<Set<string>>(
    () => new Set(),
  );

  const referenceSignature = useMemo(() => proposalReferences?.map((reference) => (
    `${guidedReferenceKey(reference)}:${reference.required}:${reference.display_order}`
  )).join("|") ?? "pending", [proposalReferences]);

  useEffect(() => {
    setExcludedOptionalReferenceKeys(new Set());
  }, [referenceSignature]);

  const acceptedReferences = useMemo(() => (
    proposalReferences?.filter((reference) => (
      reference.required || !excludedOptionalReferenceKeys.has(guidedReferenceKey(reference))
    )).map((reference, index) => ({ ...reference, display_order: index })) ?? []
  ), [excludedOptionalReferenceKeys, proposalReferences]);

  if (!content) return null;

  const selectedOption = content.options.find((option) => option.option_id === optionId) ?? null;
  const customReady = Boolean(customText.trim());
  const selectionReady = Boolean(selectedOption) && proposalReferences !== null;
  const confirmationMode = mode === "defer" || mode === "exclude" || mode === "delegate";
  const submitDisabled = mode === "select"
    ? !selectionReady
    : mode === "custom"
      ? !customReady
      : !confirmationMode;

  const moreActions = [
    content.allow_custom && allowed(interaction, "custom")
      ? { mode: "custom" as const, label: "Custom direction" }
      : null,
    allowed(interaction, "defer")
      ? { mode: "defer" as const, label: "Defer this stage" }
      : null,
    content.allow_exclusion && allowed(interaction, "exclude")
      ? { mode: "exclude" as const, label: "Exclude this stage" }
      : null,
    allowed(interaction, "delegate")
      ? { mode: "delegate" as const, label: "Let Agent decide" }
      : null,
  ].filter((action): action is NonNullable<typeof action> => action !== null);

  const footerSummary = mode === "select"
    ? proposalReferences === null && selectedOption
      ? "Preparing references"
      : selectedOption
        ? `Selected: ${selectedOption.title}`
        : "Choose one option"
    : mode === "custom"
      ? "Custom direction"
      : mode === "exclude"
        ? "Exclude this stage"
        : mode === "defer"
          ? "Defer this stage"
          : "Let Agent decide";

  const submitLabel = mode === "select"
    ? "Submit selection"
    : mode === "custom"
      ? "Submit direction"
      : mode === "exclude"
        ? "Confirm exclusion"
        : mode === "defer"
          ? "Confirm defer"
          : "Confirm delegation";

  const submit = () => {
    if (submitDisabled) return;
    const request: GuidedInteractionSubmitRequestV1 = {
      submission_kind: "concept_choice",
      expected_interaction_revision: interaction.revision,
      expected_session_revision: interaction.expected_session_revision,
      action: mode,
      option_id: mode === "select" ? optionId : null,
      custom_text: mode === "custom" ? customText.trim() : null,
      ...(mode === "select" && content.proposal_id
        ? { accepted_references: acceptedReferences }
        : {}),
    };
    void onSubmit(request);
  };

  return (
    <DecisionDockFrame
      title={interaction.title}
      context={interaction.context}
      pending={pending}
      issue={issue}
      footerSummary={footerSummary}
      submitLabel={submitLabel}
      submitDisabled={submitDisabled}
      onSubmit={submit}
    >
      <div className="agent-chat__decision-dock-options" role="radiogroup" aria-label="Creative direction options">
        {content.options.map((option, index) => (
          <ProposalOptionRow
            key={option.option_id}
            index={index}
            marker={optionMarker(index)}
            selectionRole="radio"
            optionId={option.option_id}
            title={option.title}
            summary={option.summary}
            recommended={option.recommended}
            selected={optionId === option.option_id}
            disabled={pending}
            onSelect={() => {
              setOptionId(option.option_id);
              setMode("select");
            }}
          />
        ))}
      </div>

      {content.proposal_id ? (
        <DecisionDockDisclosure
          id={referencesId}
          label="References"
          count={proposalReferences?.length ?? null}
          expanded={referencesOpen}
          disabled={pending}
          onExpandedChange={setReferencesOpen}
        >
          <GuidedInteractionReferences
            references={proposalReferences}
            mediaUrls={referenceMediaUrls}
            excludedOptionalReferenceKeys={excludedOptionalReferenceKeys}
            disabled={pending}
            showHeader={false}
            onOptionalReferenceChange={(referenceKey, accepted) => {
              setExcludedOptionalReferenceKeys((current) => {
                const next = new Set(current);
                if (accepted) next.delete(referenceKey);
                else next.add(referenceKey);
                return next;
              });
            }}
          />
        </DecisionDockDisclosure>
      ) : null}

      {moreActions.length ? (
        <DecisionDockDisclosure
          id={moreId}
          label="More"
          count={null}
          expanded={moreOpen}
          disabled={pending}
          onExpandedChange={setMoreOpen}
        >
          <div className="agent-chat__decision-dock-secondary-actions">
            {moreActions.map((action) => (
              <button
                key={action.mode}
                type="button"
                disabled={pending}
                aria-pressed={mode === action.mode}
                onClick={() => setMode(action.mode)}
              >
                {action.label}
              </button>
            ))}
          </div>
        </DecisionDockDisclosure>
      ) : null}

      {mode === "custom" ? (
        <div className="agent-chat__decision-dock-inline-input">
          <label htmlFor={`${moreId}-custom`}>Custom direction</label>
          <textarea
            id={`${moreId}-custom`}
            value={customText}
            disabled={pending}
            onChange={(event) => setCustomText(event.target.value)}
          />
          <button type="button" disabled={pending} onClick={() => setMode("select")}>
            Back to selection
          </button>
        </div>
      ) : null}

      {confirmationMode ? (
        <div className="agent-chat__decision-dock-confirmation">
          <span>Confirm this action before continuing.</span>
          <button type="button" disabled={pending} onClick={() => setMode("select")}>
            Cancel
          </button>
        </div>
      ) : null}
    </DecisionDockFrame>
  );
}
