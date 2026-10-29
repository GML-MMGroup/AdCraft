import type { ChatMessageV2, ChatTimelineItemV2 } from "../../../types-v2.ts";
import type { UiMessageKey } from "../../../i18n/uiMessages.ts";

export type PromptPreparationStatus = "queued" | "working" | "ready" | "superseded" | "waiting_user" | "failed";

export interface PromptPreparationView {
  nodeTitle: string;
  status: PromptPreparationStatus | string;
  errorCode: string | null;
}

function metadataString(message: ChatMessageV2, key: string): string | null {
  const value = message.metadata?.[key];
  // Presentation projections stringify absent values.
  return typeof value === "string" && value && value !== "None" ? value : null;
}

function isPlanning(item: ChatTimelineItemV2): item is ChatMessageV2 {
  return item.item_type === "message" && item.message_kind === "planning_progress";
}

function promptNodeId(message: ChatMessageV2): string | null {
  return metadataString(message, "type") === "prompt_preparation" ? metadataString(message, "node_id") : null;
}

export function promptPreparationView(message: ChatMessageV2): PromptPreparationView | null {
  if (!promptNodeId(message)) return null;
  return {
    nodeTitle: metadataString(message, "node_title") ?? "",
    status: metadataString(message, "status") ?? "",
    errorCode: metadataString(message, "error_code"),
  };
}

function isPlanningRound(message: ChatMessageV2): boolean {
  return metadataString(message, "operation") === "next_action"
    && Boolean(metadataString(message, "envelope_id"))
    && !metadataString(message, "materialization_id");
}

/**
 * Collapse execution bookkeeping that the backend records once per attempt:
 * - prompt preparation is redispatched under a new id for the same node, so keep one row per
 *   node at its first position showing the latest attempt, and drop nodes whose latest attempt
 *   was superseded without a replacement;
 * - a planning round says only "planning the next action" and is followed by its outcome, so it
 *   shows only while it is the newest row and the Agent is still working;
 * - a Draft materialization row never leaves "queued", so it goes once its receipt arrives.
 */
export function reducePlanningNoise(
  items: readonly ChatTimelineItemV2[],
  { agentWorking }: { agentWorking: boolean },
): ChatTimelineItemV2[] {
  const latestPromptByNode = new Map<string, ChatMessageV2>();
  const receiptSequenceByProposal = new Map<string, number>();
  let newestSequence = Number.NEGATIVE_INFINITY;
  for (const item of items) {
    newestSequence = Math.max(newestSequence, item.sequence);
    if (item.item_type === "action_receipt" && item.action_receipt.proposal_id) {
      const proposalId = item.action_receipt.proposal_id;
      receiptSequenceByProposal.set(proposalId, Math.max(receiptSequenceByProposal.get(proposalId) ?? -Infinity, item.sequence));
    }
    if (!isPlanning(item)) continue;
    const nodeId = promptNodeId(item);
    if (!nodeId) continue;
    const latest = latestPromptByNode.get(nodeId);
    if (!latest || item.sequence > latest.sequence) latestPromptByNode.set(nodeId, item);
  }

  const emittedNodes = new Set<string>();
  return items.flatMap((item): ChatTimelineItemV2[] => {
    if (!isPlanning(item)) return [item];
    const nodeId = promptNodeId(item);
    if (nodeId) {
      if (emittedNodes.has(nodeId)) return [];
      emittedNodes.add(nodeId);
      const latest = latestPromptByNode.get(nodeId)!;
      if (metadataString(latest, "status") === "superseded") return [];
      // Keep the first row's identity and place so the row updates in place as attempts advance.
      return [{ ...latest, message_id: item.message_id, sequence: item.sequence }];
    }
    if (isPlanningRound(item)) {
      return agentWorking && item.sequence === newestSequence ? [item] : [];
    }
    const proposalId = metadataString(item, "materialization_id") ? metadataString(item, "proposal_id") : null;
    if (proposalId && (receiptSequenceByProposal.get(proposalId) ?? -Infinity) > item.sequence) return [];
    return [item];
  });
}

const PROMPT_STATUS_LABELS: Record<PromptPreparationStatus, UiMessageKey> = {
  queued: "Prompt queued",
  working: "Writing prompt",
  ready: "Prompt ready",
  superseded: "Prompt replaced",
  waiting_user: "Waiting for your choice",
  failed: "Prompt preparation failed",
};

/** Render prompt preparation from its structured status instead of the English template text. */
export function localizePromptPreparation(
  message: ChatMessageV2,
  t: (key: UiMessageKey) => string,
): ChatMessageV2 {
  const view = promptPreparationView(message);
  const label = view ? PROMPT_STATUS_LABELS[view.status as PromptPreparationStatus] : undefined;
  if (!view || !label || !view.nodeTitle) return message;
  const detail = view.status === "failed" && view.errorCode ? ` (${view.errorCode})` : "";
  return { ...message, text: `${view.nodeTitle} · ${t(label)}${detail}` };
}
