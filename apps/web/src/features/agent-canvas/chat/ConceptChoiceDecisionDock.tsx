import type { GuidedInteractionV1 } from "../../../types-v2.ts";
import { DecisionDockFrame } from "./DecisionDockFrame.tsx";
import type { DecisionDockIssue } from "./decisionDockIssue.ts";
import { ProposalOptionRow } from "./ProposalOptionRow.tsx";

export interface ConceptChoiceDecisionDockProps {
  interaction: GuidedInteractionV1;
  pending: boolean;
  issue: DecisionDockIssue | null;
  selectedOptionId: string | null;
  onSelectOption: (optionId: string) => void;
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
  selectedOptionId,
  onSelectOption,
}: ConceptChoiceDecisionDockProps) {
  const content = interaction.content.content_kind === "concept_choice" ? interaction.content : null;
  if (!content) return null;

  const canCustom = content.allow_custom && allowed(interaction, "custom");

  return (
    <DecisionDockFrame
      title={interaction.title}
      context={interaction.context}
      pending={pending}
      issue={issue}
      showSubmitBar={false}
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
            selected={selectedOptionId === option.option_id}
            disabled={pending}
            onSelect={() => onSelectOption(option.option_id)}
          />
        ))}
      </div>
      <p className="agent-chat__decision-dock-composer-hint">
        {canCustom
          ? "Choose an option above, or describe your own direction below."
          : "Choose an option above, then submit it below."}
      </p>
    </DecisionDockFrame>
  );
}
