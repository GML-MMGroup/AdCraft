import { describe, expect, it } from "vitest";

import type {
  CanvasNodeV2,
  CanvasRuntimeSnapshotV2,
  GuidanceAwaitingV1,
  NodeRuntimeV2,
} from "../../../types-v2.ts";
import { projectProductionFocus } from "./productionFocusProjection.ts";

function node(nodeId: string, title: string, nodeType: CanvasNodeV2["node_type"] = "video"): CanvasNodeV2 {
  return {
    node_id: nodeId,
    node_type: nodeType,
    title,
    creative_role: null,
    status: "draft",
  } as CanvasNodeV2;
}

function nodeRuntime(nodeId: string, overrides: Partial<NodeRuntimeV2> = {}): NodeRuntimeV2 {
  return {
    node_id: nodeId,
    visible_status: "working",
    phase: "running",
    execution_id: "execution-1",
    provider_task_id: null,
    run_intent_snapshot_id: null,
    parameter_compilation_snapshot_id: null,
    effective_parameters: {},
    normalizations: [],
    omitted_optional_inputs: [],
    waiting_for_node_ids: [],
    blocked_by_node_ids: [],
    attempt_no: 1,
    updated_at: "2026-08-27T00:00:00Z",
    error: null,
    ...overrides,
  };
}

function runtime(...states: NodeRuntimeV2[]): CanvasRuntimeSnapshotV2 {
  return {
    workflow_id: "workflow-1",
    active_execution_id: "execution-1",
    execution_status: "running",
    node_runtime: Object.fromEntries(states.map((state) => [state.node_id, state])),
    queued_node_ids: [],
    working_node_ids: states.filter((state) => state.visible_status === "working").map((state) => state.node_id),
    waiting_node_ids: states.filter((state) => state.phase === "waiting_for_input" || state.phase === "blocked_by_upstream").map((state) => state.node_id),
    ready_node_ids: [],
    failed_node_ids: states.filter((state) => state.visible_status === "failed").map((state) => state.node_id),
    events_cursor: 1,
    updated_at: "2026-08-27T00:00:00Z",
  };
}

function awaiting(overrides: Partial<GuidanceAwaitingV1> = {}): GuidanceAwaitingV1 {
  return {
    awaiting_id: "awaiting-1",
    workflow_id: "workflow-1",
    session_id: "session-1",
    checkpoint_id: "checkpoint-1",
    kind: "concept_selection",
    requires_user_action: true,
    resume_policy: "submit_interaction",
    interaction_id: "interaction-1",
    node_ids: [],
    stage: "world_view",
    stage_revision: 1,
    created_at: "2026-08-27T00:00:00Z",
    ...overrides,
  };
}

describe("projectProductionFocus", () => {
  const nodes = [
    node("video-1", "Video 01"),
    node("video-2", "Video 02"),
    node("storyboard-1", "Storyboard 01", "image"),
    node("script-1", "Script", "script"),
  ];

  it("prioritizes a typed guidance action over runtime failures", () => {
    const result = projectProductionFocus({
      nodes,
      runtime: runtime(nodeRuntime("video-1", { visible_status: "failed", phase: null })),
      guidanceAwaiting: awaiting(),
    });

    expect(result).toMatchObject({
      kind: "guidance",
      title: "Your creative choice is needed",
      detail: "Choose an option to continue",
      nodeIds: [],
    });
  });

  it("turns manual node run authority into a direct user action", () => {
    const result = projectProductionFocus({
      nodes,
      runtime: null,
      guidanceAwaiting: awaiting({
        kind: "manual_node_run",
        resume_policy: "node_terminal",
        interaction_id: null,
        node_ids: ["script-1"],
        stage: "narrative_direction",
      }),
    });

    expect(result).toMatchObject({
      kind: "guidance",
      title: "Script is ready to run",
      detail: "Run this node to continue",
      actionLabel: "View node",
      nodeIds: ["script-1"],
    });
  });

  it("aggregates simultaneous running nodes instead of choosing one arbitrarily", () => {
    const result = projectProductionFocus({
      nodes,
      runtime: runtime(nodeRuntime("video-1"), nodeRuntime("video-2")),
      guidanceAwaiting: null,
    });

    expect(result).toMatchObject({
      kind: "running",
      title: "2 video nodes are generating",
      detail: "Generation is in progress",
      actionLabel: "View on canvas",
      nodeIds: ["video-1", "video-2"],
    });
  });

  it("identifies structured upstream blockers and targets the blocker", () => {
    const result = projectProductionFocus({
      nodes,
      runtime: runtime(nodeRuntime("video-1", {
        phase: "blocked_by_upstream",
        visible_status: "draft",
        blocked_by_node_ids: ["storyboard-1"],
      })),
      guidanceAwaiting: null,
    });

    expect(result).toMatchObject({
      kind: "waiting",
      title: "Video 01 is waiting",
      detail: "Waiting for Storyboard 01",
      actionLabel: "View blocker",
      nodeIds: ["storyboard-1"],
    });
  });

  it("uses safe fallback copy instead of exposing an unknown waiting reason", () => {
    const result = projectProductionFocus({
      nodes,
      runtime: runtime(nodeRuntime("video-1", {
        phase: "waiting_for_input",
        visible_status: "draft",
        waiting_reason: "internal_checkpoint_4739",
      })),
      guidanceAwaiting: null,
    });

    expect(result).toMatchObject({
      title: "Video 01 is waiting",
      detail: "This step is waiting",
    });
    expect(JSON.stringify(result)).not.toContain("internal_checkpoint_4739");
  });

  it("hides when there is no active, waiting, or failed state", () => {
    expect(projectProductionFocus({ nodes, runtime: null, guidanceAwaiting: null })).toBeNull();
  });
});
