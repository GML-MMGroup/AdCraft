import type { ChatProposalCardV2 } from "../../../types-v2.ts";

/** The option the user chose for a proposal, shown as their reply right after the proposal. */
export interface ProposalReply {
  letter: string;
  title: string;
}

export function proposalReply(
  card: ChatProposalCardV2,
  optimisticOptionId: string | null = null,
): ProposalReply | null {
  const { proposal } = card;
  const optionId = proposal.latest_application?.option_id
    ?? proposal.materialization?.option_id
    ?? optimisticOptionId;
  const index = optionId ? proposal.options.findIndex((option) => option.option_id === optionId) : -1;
  return index >= 0
    ? { letter: String.fromCharCode(65 + index), title: proposal.options[index]!.title }
    : null;
}
