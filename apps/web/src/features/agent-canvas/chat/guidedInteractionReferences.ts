import type {
  AgentCanvasWorkflowV2,
  ChatTimelineItemV2,
  GuidedInteractionV1,
  ProposedDraftReferenceV2,
} from "../../../types-v2.ts";
import { mediaAssetContentPath } from "../../../workflow/mediaPreview.ts";

export function guidedReferenceKey(reference: Pick<ProposedDraftReferenceV2, "source_kind" | "source_id">) {
  return `${reference.source_kind}:${reference.source_id}`;
}

export function guidedInteractionReferences(
  interaction: GuidedInteractionV1,
  items: ChatTimelineItemV2[],
): ProposedDraftReferenceV2[] | null {
  if (interaction.content.content_kind !== "concept_choice") return [];
  const proposalId = interaction.content.proposal_id;
  if (!proposalId) return [];
  const proposalItem = items.find((item) => (
    item.item_type === "proposal" && item.proposal.proposal_id === proposalId
  ));
  if (!proposalItem || proposalItem.item_type !== "proposal") return null;
  return [...proposalItem.proposal.proposed_references]
    .sort((left, right) => left.display_order - right.display_order);
}

export function guidedInteractionReferenceMediaUrls(
  references: ProposedDraftReferenceV2[],
  workflow: AgentCanvasWorkflowV2,
): Record<string, string> {
  return Object.fromEntries(references.flatMap((reference) => {
    if (reference.media_type !== "image") return [];
    const assetId = reference.source_kind === "image_asset"
      ? reference.source_id
      : workflow.nodes.find((node) => node.node_id === reference.source_id)?.output_asset_id;
    if (!assetId) return [];
    const asset = workflow.assets.find((candidate) => candidate.asset_id === assetId);
    const mediaUrl = asset ? mediaAssetContentPath(asset) : "";
    return mediaUrl ? [[guidedReferenceKey(reference), mediaUrl]] : [];
  }));
}
