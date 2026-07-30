import { describe, expect, it } from "vitest";

import type { CanvasRuntimeSnapshotV2 } from "../../../types-v2.ts";
import { blockedUpstreamNodeIds } from "./runtimeAttention.ts";

describe("blockedUpstreamNodeIds", () => {
  it("returns required sources blocking Draft dependents without adding a node status", () => {
    const runtime: CanvasRuntimeSnapshotV2 = {
      workflow_id: "workflow-1",
      active_execution_id: "execution-1",
      execution_status: "partial_completed",
      node_runtime: {
        "node-video": {
          node_id: "node-video",
          visible_status: "draft",
          phase: "waiting_for_input",
          execution_id: "execution-1",
          provider_task_id: null,
          waiting_for_node_ids: [],
          blocked_by_node_ids: ["node-storyboard", "node-scene"],
          requested_duration_seconds: null,
          effective_duration_seconds: null,
          normalizations: [],
          attempt_no: 0,
          updated_at: "2026-07-30T00:00:00Z",
          error: null,
        },
      },
      queued_node_ids: [],
      working_node_ids: [],
      waiting_node_ids: ["node-video"],
      ready_node_ids: [],
      failed_node_ids: [],
      events_cursor: 8,
      updated_at: "2026-07-30T00:00:00Z",
    };

    expect(blockedUpstreamNodeIds(runtime)).toEqual([
      "node-storyboard",
      "node-scene",
    ]);
  });
});
