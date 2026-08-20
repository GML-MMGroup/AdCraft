import type {
  ChatProposalCardV2,
  ChatTimelineItemV2,
  GuidedInteractionV1,
} from "../../../types-v2.ts";

function activeProposalId(interaction: GuidedInteractionV1 | null): string | null {
  if (
    interaction?.status !== "open"
    || interaction.content.content_kind !== "concept_choice"
  ) return null;
  return interaction.content.proposal_id;
}

export function guidedInteractionContentVersion(
  interaction: GuidedInteractionV1 | null,
): string {
  return interaction
    ? `${interaction.interaction_id}:${interaction.revision}:${interaction.status}`
    : "";
}

export function interactionForTimelineProposal(
  interaction: GuidedInteractionV1 | null,
  item: ChatProposalCardV2,
): GuidedInteractionV1 | null {
  return activeProposalId(interaction) === item.proposal.proposal_id ? interaction : null;
}

export function shouldRenderStandaloneInteraction(
  interaction: GuidedInteractionV1 | null,
  items: ChatTimelineItemV2[],
): boolean {
  if (!interaction) return false;
  const proposalId = activeProposalId(interaction);
  if (!proposalId) return true;
  return !items.some((item) => (
    item.item_type === "proposal" && item.proposal.proposal_id === proposalId
  ));
}
