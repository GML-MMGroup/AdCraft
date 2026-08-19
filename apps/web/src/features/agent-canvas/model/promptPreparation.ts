import type { CanvasNodeV2, NodePromptPreparationV1 } from "../../../types-v2.ts";

/**
 * Older persisted Canvas nodes predate prompt preparation. Treat them as already
 * prepared so the additive contract cannot block an otherwise runnable manual node.
 */
export function promptPreparationForNode(node: CanvasNodeV2): NodePromptPreparationV1 {
  return node.prompt_preparation ?? {
    status: "ready",
    operation_id: null,
    attempt_no: 0,
    context_snapshot_id: null,
    prompt_digest: "0".repeat(64),
    error: null,
    updated_at: node.updated_at,
  };
}

export function isNodePromptReady(node: CanvasNodeV2): boolean {
  return promptPreparationForNode(node).status === "ready";
}
