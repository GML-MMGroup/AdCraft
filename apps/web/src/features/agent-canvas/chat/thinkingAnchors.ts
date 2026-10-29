import type { ChatTimelineItemV2 } from "../../../types-v2.ts";
import type { PresentationStreamView } from "../runtime/useAgentCanvasPresentationStreams.ts";

type StreamLike = Pick<PresentationStreamView, "status" | "reasoning_text" | "authoritative_id" | "turn_id" | "reasoning_started_at" | "answer_started_at" | "terminal_at_ms" | "generation_id"> & {
  stream_kind?: string | null;
};

function itemIdentities(item: ChatTimelineItemV2): { authoritative: string[]; turns: string[] } {
  switch (item.item_type) {
    case "message":
      return {
        authoritative: [item.message_id],
        turns: [item.message_id, ...(typeof item.metadata?.turn_id === "string" ? [item.metadata.turn_id] : [])],
      };
    case "artifact":
      return { authoritative: [item.artifact_id], turns: item.source_turn_id ? [item.source_turn_id] : [] };
    case "proposal":
      return { authoritative: [item.proposal.proposal_id], turns: [item.proposal.turn_id] };
    case "proposal_pointer":
      return { authoritative: [item.proposal_id], turns: [] };
    case "expert_activity":
      return { authoritative: [item.activity_id], turns: [item.turn_id] };
    case "command_plan":
      return { authoritative: [item.command_plan.plan_id], turns: [item.command_plan.source_turn_id] };
    case "action_receipt":
      return { authoritative: [item.action_receipt.receipt_id], turns: [item.action_receipt.continuation_turn_id].filter((id): id is string => Boolean(id)) };
    case "agent_document":
      return { authoritative: [item.document_id], turns: [] };
    case "decision_bundle":
      return { authoritative: [item.decision_bundle.bundle_id], turns: [item.decision_bundle.source_turn_id] };
    case "decision_bundle_pointer":
      return { authoritative: [item.bundle_id], turns: [] };
  }
}

export function thinkingAnchorForItem(
  streams: readonly StreamLike[],
  item: ChatTimelineItemV2,
): StreamLike | null {
  const identities = itemIdentities(item);
  const candidates = streams.filter((stream) => Boolean(stream.reasoning_text));
  const authoritative = candidates.find((stream) => (
    stream.status === "completed" && stream.authoritative_id !== null && identities.authoritative.includes(stream.authoritative_id)
  ));
  if (authoritative) return authoritative;
  const turn = candidates.find((stream) => (
    stream.status === "completed" && stream.turn_id !== null && identities.turns.includes(stream.turn_id)
  ));
  return turn ?? null;
}

/** Find the latest completed brand generation that committed one of these UI identities. */
export function brandThinkingAnchor(
  streams: readonly StreamLike[],
  ids: readonly string[],
): StreamLike | null {
  const identities = new Set(ids);
  return streams
    .filter((stream) => (
      stream.status === "completed"
      && stream.generation_id?.startsWith("brand-gen:")
      && Boolean(stream.reasoning_text)
      && stream.authoritative_id !== null
      && identities.has(stream.authoritative_id)
    ))
    .reduce<StreamLike | null>((latest, stream) => {
      if (!latest) return stream;
      const timestamp = stream.terminal_at_ms ?? stream.answer_started_at ?? stream.reasoning_started_at ?? -Infinity;
      const latestTimestamp = latest.terminal_at_ms ?? latest.answer_started_at ?? latest.reasoning_started_at ?? -Infinity;
      return timestamp >= latestTimestamp ? stream : latest;
    }, null);
}
