import type { CanvasNodeV2, CanvasRunRequestV2 } from "../../../types-v2.ts";
import { assertGenerativeNode } from "../model/nodeExecutionMode.ts";

export function nodeRunRequest(
  node: CanvasNodeV2,
  retryFailed = false,
): CanvasRunRequestV2 {
  assertGenerativeNode(node);
  const retry = retryFailed || node.status === "failed";
  return {
    scope: "selected_nodes",
    node_ids: [node.node_id],
    expected_node_revisions: { [node.node_id]: node.revision },
    retry_failed: retry,
    source_action: retry ? "retry_failed" : "node_run",
  };
}
