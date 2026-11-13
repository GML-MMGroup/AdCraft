import { useRef, useState } from "react";
import type { GuidedInteractionSubmitRequestV1, GuidedInteractionV1 } from "../../../types-v2.ts";
import { useTranslation } from "../../../i18n/useTranslation.ts";
import { DecisionDockFrame } from "./DecisionDockFrame.tsx";
import type { DecisionDockIssue } from "./decisionDockIssue.ts";
import { ProposalOptionRow } from "./ProposalOptionRow.tsx";
import { BRAND_STAGE_LABELS } from "../brand/brandStageLabels.ts";
import { guidedInteractionCopy } from "./guidedInteractionCopy.ts";

export function BrandCreativeRoute({ interaction, pending, disabled, issue, onSubmit }: {
  interaction: GuidedInteractionV1;
  pending: boolean;
  disabled?: boolean;
  issue: DecisionDockIssue | null;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
}) {
  const t = useTranslation(interaction.response_locale);
  const inFlight = useRef(false);
  const [submitting, setSubmitting] = useState(false);
  if (interaction.content.content_kind !== "concept_choice") return null;
  const locked = pending || submitting || disabled || interaction.status !== "open";
  const choose = async (optionId: string) => {
    if (locked || inFlight.current) return;
    inFlight.current = true;
    setSubmitting(true);
    try {
      await onSubmit({
        submission_kind: "concept_choice",
        action: "select", option_id: optionId,
        expected_interaction_revision: interaction.revision,
        expected_session_revision: interaction.expected_session_revision,
      });
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  };
  return <DecisionDockFrame title={guidedInteractionCopy(interaction.title, t)} eyebrow={t(BRAND_STAGE_LABELS["creative-route"])}
    pending={pending || submitting} issue={issue} showSubmitBar={false}>
    <div className="agent-chat__decision-dock-options">
      {interaction.content.options.map((option, index) => <ProposalOptionRow
        key={option.option_id} index={index} optionId={option.option_id}
        title={guidedInteractionCopy(option.title, t)} summary={guidedInteractionCopy(option.summary, t)} disabled={locked}
        onSelect={() => { void choose(option.option_id); }}
      />)}
    </div>
  </DecisionDockFrame>;
}
