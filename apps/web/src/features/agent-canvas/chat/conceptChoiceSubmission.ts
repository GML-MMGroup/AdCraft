import type {
  GuidedAcceptedReferenceV1,
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
  ProposedDraftReferenceV2,
} from "../../../types-v2.ts";

function toAcceptedReference(reference: ProposedDraftReferenceV2): GuidedAcceptedReferenceV1 {
  return {
    source_kind: reference.source_kind,
    source_id: reference.source_id,
    display_name: reference.display_name,
    media_type: reference.media_type,
    binding_kind: reference.binding_kind,
    input_role: reference.input_role,
    required: reference.required,
    display_order: reference.display_order,
    semantic_reference_role: reference.semantic_reference_role,
    occurrence_id: reference.occurrence_id,
    character_phase: reference.character_phase,
  };
}

export function buildConceptChoiceSubmitRequest({
  interaction,
  selectedOptionId,
  customText,
  proposalReferences,
}: {
  interaction: GuidedInteractionV1;
  selectedOptionId: string | null;
  customText: string;
  proposalReferences: ProposedDraftReferenceV2[] | null;
}): GuidedInteractionSubmitRequestV1 | null {
  if (interaction.content.content_kind !== "concept_choice") return null;
  const text = customText.trim();
  const selectedOption = interaction.content.options.find((option) => option.option_id === selectedOptionId);
  const isCustom = !selectedOptionId;

  if (isCustom) {
    if (!text || !interaction.content.allow_custom || !interaction.allowed_actions.includes("custom")) return null;
  } else if (!selectedOption) {
    return null;
  }

  const acceptedReferences = !isCustom && interaction.content.proposal_id
    ? proposalReferences?.map(toAcceptedReference)
    : undefined;
  if (!isCustom && interaction.content.proposal_id && !acceptedReferences) return null;

  return {
    submission_kind: "concept_choice",
    expected_interaction_revision: interaction.revision,
    expected_session_revision: interaction.expected_session_revision,
    action: isCustom ? "custom" : "select",
    option_id: isCustom ? null : selectedOptionId,
    custom_text: isCustom ? text : null,
    ...(acceptedReferences ? { accepted_references: acceptedReferences } : {}),
  };
}
