import type {
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
  ProposedDraftReferenceV2,
} from "../../../types-v2.ts";
import { ConceptChoiceSubmitControls } from "./ConceptChoiceSubmitControls.tsx";

export function TimelineProposalInteractionActions({
  acceptedReferences,
  interaction,
  materializationBusy,
  onSubmit,
  pending,
  selectedOptionId,
}: {
  acceptedReferences: ProposedDraftReferenceV2[];
  interaction: GuidedInteractionV1;
  materializationBusy: boolean;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
  pending: boolean;
  selectedOptionId: string | null;
}) {
  const concept = interaction.content.content_kind === "concept_choice" ? interaction.content : null;

  function submit(
    action: "select" | "custom" | "defer" | "exclude" | "delegate",
    customValue: string | null = null,
  ) {
    void onSubmit({
      submission_kind: "concept_choice",
      expected_interaction_revision: interaction.revision,
      expected_session_revision: interaction.expected_session_revision,
      action,
      option_id: action === "select" ? selectedOptionId : null,
      custom_text: action === "custom" ? customValue : null,
      accepted_references: action === "select"
        ? acceptedReferences.map((reference, index) => ({
          source_kind: reference.source_kind,
          source_id: reference.source_id,
          display_name: reference.display_name,
          media_type: reference.media_type,
          binding_kind: reference.binding_kind,
          input_role: reference.input_role,
          required: reference.required,
          display_order: index,
          semantic_reference_role: reference.semantic_reference_role ?? null,
        }))
        : undefined,
    });
  }

  return (
    <ConceptChoiceSubmitControls
      allowedActions={interaction.allowed_actions}
      allowCustom={concept?.allow_custom ?? false}
      allowExclusion={concept?.allow_exclusion ?? false}
      busy={pending || materializationBusy}
      selectedOptionId={selectedOptionId}
      onSubmit={submit}
    />
  );
}
