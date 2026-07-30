import type { CanvasRuntimeSnapshotV2 } from "../../../types-v2.ts";

export function blockedUpstreamNodeIds(
  runtime: CanvasRuntimeSnapshotV2 | null,
): string[] {
  if (!runtime) return [];
  return Array.from(new Set(
    Object.values(runtime.node_runtime).flatMap((node) => node.blocked_by_node_ids),
  ));
}
