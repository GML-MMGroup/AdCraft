import { describe, expect, it } from "vitest";

import type {
  CanvasRuntimeEventV2,
  CanvasRuntimeSnapshotV2,
} from "../../../types-v2.ts";
import {
  runtimeRefreshIdentity,
  sameRuntimePresentation,
} from "./runtimeRefreshIdentity.ts";

function event(
  event_type: string,
  seq: number,
  overrides: Partial<CanvasRuntimeEventV2> = {},
): CanvasRuntimeEventV2 {
  return {
    seq,
    workflow_id: "workflow-1",
    event_type,
    project_id: "project-1",
    execution_id: "execution-1",
    node_id: "node-1",
    asset_id: null,
    binding_id: null,
    conversation_id: null,
    turn_id: null,
    action_id: null,
    trace_id: null,
    span_id: null,
    transition_key: null,
    attempt: 1,
    created_at: "2026-08-21T00:00:00Z",
    payload: {},
    ...overrides,
  };
}

function runtime(overrides: Partial<CanvasRuntimeSnapshotV2> = {}): CanvasRuntimeSnapshotV2 {
  return {
    workflow_id: "workflow-1",
    active_execution_id: "execution-1",
    execution_status: "running",
    node_runtime: {},
    queued_node_ids: [],
    working_node_ids: ["node-1"],
    waiting_node_ids: [],
    ready_node_ids: [],
    failed_node_ids: [],
    events_cursor: 12,
    updated_at: "2026-08-21T00:00:00Z",
    ...overrides,
  };
}

describe("runtimeRefreshIdentity", () => {
  it("shares identities for duplicate waiting and started events", () => {
    expect(runtimeRefreshIdentity(event("node_generation_waiting", 12))).toBe(
      runtimeRefreshIdentity(event("node_generation_waiting", 13, {
        created_at: "2026-08-21T00:01:00Z",
      })),
    );
    expect(runtimeRefreshIdentity(event("node_generation_started", 14))).toBe(
      runtimeRefreshIdentity(event("node_generation_started", 15, {
        created_at: "2026-08-21T00:01:00Z",
      })),
    );
  });

  it("keeps progress and terminal runtime events distinct", () => {
    expect(runtimeRefreshIdentity(event("provider_task_polled", 12, {
      payload: { progress: 25 },
    }))).not.toBe(runtimeRefreshIdentity(event("provider_task_polled", 13, {
      payload: { progress: 50 },
    })));
    expect(runtimeRefreshIdentity(event("node_ready", 14))).not.toBe(
      runtimeRefreshIdentity(event("node_ready", 15)),
    );
  });
});

describe("sameRuntimePresentation", () => {
  it("ignores timestamp-only runtime snapshot changes", () => {
    const current = runtime();

    expect(sameRuntimePresentation(current, runtime({
      events_cursor: 13,
      updated_at: "2026-08-21T00:01:00Z",
    }))).toBe(true);
  });

  it("detects visible runtime changes", () => {
    expect(sameRuntimePresentation(runtime(), runtime({
      working_node_ids: [],
      ready_node_ids: ["node-1"],
    }))).toBe(false);
  });
});
