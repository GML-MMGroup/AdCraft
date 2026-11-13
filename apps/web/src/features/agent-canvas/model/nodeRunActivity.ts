import type { CanvasNodeV2 } from "../../../types-v2.ts";

/** Accepted work stays active even while authoring still reports Draft or Ready. */
export function nodeRunActivity(node: CanvasNodeV2): "queued" | "waiting" | "running" | null {
  const attempt = node.latest_attempt?.status;
  if (attempt === "queued" || attempt === "waiting" || attempt === "running") return attempt;
  return node.status === "working" ? "running" : null;
}
