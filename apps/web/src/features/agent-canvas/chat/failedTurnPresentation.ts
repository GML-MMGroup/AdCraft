import type {
  AgentCanvasChatTurnV2,
  ChatTimelineItemV2,
} from "../../../types-v2.ts";

export function structuredMessageTurnId(item: ChatTimelineItemV2): string | null {
  if (item.item_type !== "message") return null;
  const turnId = item.metadata?.turn_id;
  return typeof turnId === "string" && turnId.trim() ? turnId : null;
}

function latestRetryChain(
  source: AgentCanvasChatTurnV2,
  retriesBySource: ReadonlyMap<string, AgentCanvasChatTurnV2>,
  turnCount: number,
): AgentCanvasChatTurnV2[] {
  const chain = [source];
  const seen = new Set([source.turn_id]);
  while (chain.length <= turnCount) {
    const retry = retriesBySource.get(chain[chain.length - 1]!.turn_id);
    if (!retry || seen.has(retry.turn_id)) break;
    chain.push(retry);
    seen.add(retry.turn_id);
  }
  return chain;
}

export function projectFailedMessageTurns(
  items: readonly ChatTimelineItemV2[],
  turnsById: Readonly<Record<string, AgentCanvasChatTurnV2>>,
): Map<string, AgentCanvasChatTurnV2> {
  const failedTurnsByMessageId = new Map<string, AgentCanvasChatTurnV2>();
  const turns = Object.values(turnsById);
  const retriesBySource = new Map<string, AgentCanvasChatTurnV2>();
  turns.forEach((turn) => {
    if (!turn.retry_of_turn_id) return;
    const current = retriesBySource.get(turn.retry_of_turn_id);
    if (
      !current
      || turn.retry_attempt_no > current.retry_attempt_no
      || (
        turn.retry_attempt_no === current.retry_attempt_no
        && turn.updated_at > current.updated_at
      )
    ) {
      retriesBySource.set(turn.retry_of_turn_id, turn);
    }
  });
  items.forEach((item) => {
    const turnId = structuredMessageTurnId(item);
    if (!turnId || item.item_type !== "message" || item.speaker !== "user") return;
    const source = turnsById[turnId];
    if (source?.turn_kind !== "message") return;
    const chain = latestRetryChain(source, retriesBySource, turns.length);
    const latest = chain[chain.length - 1]!;
    if (latest.status === "completed" || latest.status === "superseded") return;
    const failure = [...chain].reverse().find((turn) => turn.status === "failed");
    if (failure) failedTurnsByMessageId.set(item.message_id, failure);
  });
  return failedTurnsByMessageId;
}
