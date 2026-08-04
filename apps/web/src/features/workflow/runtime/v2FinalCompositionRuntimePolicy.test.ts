import { describe, expect, it } from "vitest";

import type { WorkflowRuntimeEventV2 } from "../../../types-v2.ts";
import { createV2AuthoringRuntimeEventPolicy } from "./v2AuthoringRuntimeEventPolicy.ts";
import { v2EventShouldRefreshAssets, v2EventShouldRefreshRuntime } from "./v2RuntimeEventModel.ts";

function event(eventType: string): WorkflowRuntimeEventV2 {
  return {
    seq: 1,
    event_id: `event-${eventType}`,
    event_type: eventType,
    workflow_id: "workflow-1",
    created_at: "2026-07-23T00:00:00Z",
    payload: {},
  };
}

describe("V2 Final Composition runtime refresh policy", () => {
  it.each([
    "final_composition_render_queued",
    "final_composition_render_started",
    "final_composition_render_progress",
    "final_composition_render_completed",
    "final_composition_render_failed",
    "final_composition_render_cancelled",
  ])("refreshes runtime for %s", (eventType) => {
    expect(v2EventShouldRefreshRuntime(event(eventType))).toBe(true);
  });

  it("refreshes the workflow graph and assets when a final render completes", () => {
    const completed = event("final_composition_render_completed");

    expect(createV2AuthoringRuntimeEventPolicy([completed]).shouldRefreshRuntimeWorkflow).toBe(true);
    expect(v2EventShouldRefreshAssets(completed)).toBe(true);
  });

  it("does not replace the workflow graph for an in-progress or failed export", () => {
    expect(createV2AuthoringRuntimeEventPolicy([
      event("final_composition_render_started"),
    ]).shouldRefreshRuntimeWorkflow).toBe(false);
    expect(createV2AuthoringRuntimeEventPolicy([
      event("final_composition_render_failed"),
    ]).shouldRefreshRuntimeWorkflow).toBe(false);
  });
});
