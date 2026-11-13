import { useEffect, useMemo, useState } from "react";

import type { ChatActionReceiptCardV2, ChatTimelineItemV2 } from "../../../types-v2.ts";

export const EMPTY_RENDERED_CANVAS_NODE_IDS: ReadonlySet<string> = new Set();

type SuccessfulNodeCreation = ChatActionReceiptCardV2 & {
  action_receipt: ChatActionReceiptCardV2["action_receipt"] & { status: "applied" };
};

export function isSuccessfulNodeCreation(item: ChatTimelineItemV2): item is SuccessfulNodeCreation {
  return item.item_type === "action_receipt"
    && item.action_receipt.status === "applied"
    && item.action_receipt.created_node_ids.length > 0
    && !item.action_receipt.error_message
    && item.action_receipt.run_queue_errors.length === 0;
}

export function isRenderedNodeCreation(item: ChatTimelineItemV2, renderedNodeIds: ReadonlySet<string>): boolean {
  return isSuccessfulNodeCreation(item)
    && item.action_receipt.created_node_ids.every(id => renderedNodeIds.has(id));
}

/** Retain creation receipts across timeline refreshes until their cards have painted. */
export function useCanvasReceiptVisibility(
  workflowId: string,
  items: ChatTimelineItemV2[],
  renderedNodeIds: ReadonlySet<string>,
): ChatTimelineItemV2[] {
  const [pending, setPending] = useState<{ workflowId: string; receipts: ChatActionReceiptCardV2[] }>({
    workflowId, receipts: [],
  });
  const visibleItems = useMemo(() => {
    const currentReceiptIds = new Set(items.flatMap(item => item.item_type === "action_receipt"
      ? [item.action_receipt.receipt_id] : []));
    const retained = pending.workflowId === workflowId
      ? pending.receipts.filter(item => !currentReceiptIds.has(item.action_receipt.receipt_id)) : [];
    // Keep authoritative receipts available to planning and canvas-link projections.
    return [...items, ...retained].sort((left, right) => left.sequence - right.sequence);
  }, [items, pending, workflowId]);

  useEffect(() => {
    const receipts = visibleItems.filter(isSuccessfulNodeCreation)
      .filter(item => !isRenderedNodeCreation(item, renderedNodeIds));
    setPending(current => current.workflowId === workflowId
      && current.receipts.length === receipts.length
      && current.receipts.every((item, index) => item === receipts[index])
      ? current : { workflowId, receipts });
  }, [visibleItems, renderedNodeIds, workflowId]);

  return visibleItems;
}
