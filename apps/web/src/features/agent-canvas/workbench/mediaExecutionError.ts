import type { CanvasNodeV2, NodeRuntimeV2 } from "../../../types-v2.ts";

export function mediaExecutionError(node: CanvasNodeV2, runtime: NodeRuntimeV2 | null) {
  const attempt = node.latest_attempt;
  if (runtime) {
    // New queued work can retain the node's old timestamp and error. Hide that
    // inherited failure until the independent projections align.
    const inheritedError = !runtime.error || (
      runtime.error.code === attempt?.error?.code
      && runtime.error.message === attempt?.error?.message
    );
    if (attempt?.status === "failed"
      && runtime.execution_id
      && runtime.execution_id !== attempt.execution_id
      && runtime.phase
      && inheritedError) return null;
    // Runtime and Workflow refresh independently. A newer attempt can already
    // be running while the other projection still contains the previous error.
    const newerNode = Date.parse(node.updated_at) > Date.parse(runtime.updated_at);
    const newerAttempt = attempt
      && Date.parse(attempt.updated_at) > Date.parse(runtime.updated_at);
    if (!newerNode && !newerAttempt) {
      if (runtime.visible_status === "working") return null;
      if (runtime.error) return runtime.error;
      if (!attempt || attempt.execution_id !== runtime.execution_id) return null;
    }
  }
  // Failed regenerations can retain a Ready node and its previous output.
  if (attempt) return attempt.status === "failed" ? attempt.error : null;
  return node.status === "failed" ? node.error : null;
}
