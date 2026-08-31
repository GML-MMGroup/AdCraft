import type {
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
} from "../../../types-v2.ts";
import { ConceptChoiceDecisionDock } from "./ConceptChoiceDecisionDock.tsx";
import type { DecisionDockIssue } from "./decisionDockIssue.ts";
import { MediaReviewDecisionDock } from "./MediaReviewDecisionDock.tsx";
import { ProductSourceDecisionDock } from "./ProductSourceDecisionDock.tsx";
import { QuestionnaireDecisionDock } from "./QuestionnaireDecisionDock.tsx";
import { ReferenceSourceDecisionDock } from "./ReferenceSourceDecisionDock.tsx";
import type { ProductMainHandoff } from "./productSourceHandoff.ts";

export interface GuidedInteractionCardProps {
  interaction: GuidedInteractionV1;
  pending: boolean;
  issue?: DecisionDockIssue | null;
  selectedConceptOptionId?: string | null;
  referenceOccurrenceLabel?: string | null;
  onSelectConceptOption?: (optionId: string) => void;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
  pendingProductMainHandoff?: ProductMainHandoff | null;
  onClearProductMainHandoff?: () => void;
}

export function GuidedInteractionCard({
  interaction,
  pending,
  issue = null,
  selectedConceptOptionId = null,
  referenceOccurrenceLabel = null,
  onSelectConceptOption,
  onSubmit,
  pendingProductMainHandoff = null,
  onClearProductMainHandoff,
}: GuidedInteractionCardProps) {
  if (interaction.status !== "open" && interaction.status !== "submitted") return null;

  if (interaction.content.content_kind === "questionnaire") {
    return (
      <QuestionnaireDecisionDock
        key={interaction.interaction_id}
        interaction={interaction}
        pending={pending}
        issue={issue}
        onSubmit={onSubmit}
      />
    );
  }

  if (interaction.content.content_kind === "concept_choice") {
    return (
      <ConceptChoiceDecisionDock
        key={interaction.interaction_id}
        interaction={interaction}
        pending={pending}
        issue={issue}
        selectedOptionId={selectedConceptOptionId}
        onSelectOption={onSelectConceptOption ?? (() => undefined)}
      />
    );
  }

  if (interaction.content.content_kind === "product_source") {
    return (
      <ProductSourceDecisionDock
        key={`${interaction.workflow_id}:${interaction.content.question_id}:${interaction.content.input_kind}`}
        interaction={interaction}
        pending={pending}
        issue={issue}
        pendingProductMainHandoff={pendingProductMainHandoff}
        onClearProductMainHandoff={onClearProductMainHandoff}
        onSubmit={onSubmit}
      />
    );
  }

  if (interaction.content.content_kind === "reference_source") {
    return (
      <ReferenceSourceDecisionDock
        key={interaction.interaction_id}
        interaction={interaction}
        occurrenceLabel={referenceOccurrenceLabel}
        pending={pending}
        issue={issue}
        onSubmit={onSubmit}
      />
    );
  }

  return (
    <MediaReviewDecisionDock
      key={interaction.interaction_id}
      interaction={interaction}
      pending={pending}
      issue={issue}
      onSubmit={onSubmit}
    />
  );
}
