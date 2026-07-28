import type { CanvasNodeV2, CanvasRunRequestV2 } from "../../../types-v2.ts";

export function nodeRunRequest(
  node: CanvasNodeV2,
  retryFailed = false,
): CanvasRunRequestV2 {
  const retry = retryFailed || node.status === "failed";
  return {
    scope: "selected_nodes",
    node_ids: [node.node_id],
    retry_failed: retry,
    source_action: retry ? "retry_failed" : "node_run",
  };
}
