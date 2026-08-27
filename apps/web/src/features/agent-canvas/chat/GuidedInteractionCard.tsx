import type {
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
  ProposedDraftReferenceV2,
} from "../../../types-v2.ts";
import { ConceptChoiceDecisionDock } from "./ConceptChoiceDecisionDock.tsx";
import type { DecisionDockIssue } from "./decisionDockIssue.ts";
import { MediaReviewDecisionDock } from "./MediaReviewDecisionDock.tsx";
import { ProductSourceDecisionDock } from "./ProductSourceDecisionDock.tsx";
import { QuestionnaireDecisionDock } from "./QuestionnaireDecisionDock.tsx";

export interface GuidedInteractionCardProps {
  interaction: GuidedInteractionV1;
  pending: boolean;
  issue?: DecisionDockIssue | null;
  proposalReferences?: ProposedDraftReferenceV2[] | null;
  referenceMediaUrls?: Record<string, string>;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
}

export function GuidedInteractionCard({
  interaction,
  pending,
  issue = null,
  proposalReferences,
  referenceMediaUrls = {},
  onSubmit,
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
    const references = proposalReferences === undefined
      ? interaction.content.proposal_id ? null : []
      : proposalReferences;
    return (
      <ConceptChoiceDecisionDock
        key={interaction.interaction_id}
        interaction={interaction}
        pending={pending}
        issue={issue}
        proposalReferences={references}
        referenceMediaUrls={referenceMediaUrls}
        onSubmit={onSubmit}
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
