import { describe, expect, it } from "vitest";

import type { CanvasRuntimeEvent } from "../../../workflow/canvasRuntime.ts";
import type { WorkflowRuntimeEventV2 } from "../../../types-v2.ts";
import { routeCanvasRuntimeEvent, routeV2RuntimeEvents } from "./runtimeEventRouter.ts";

function event(eventType: string, overrides: Partial<WorkflowRuntimeEventV2> = {}): WorkflowRuntimeEventV2 {
  return {
    seq: 1,
    event_id: `event-${eventType}`,
    event_type: eventType,
    workflow_id: "workflow-1",
    created_at: "2026-07-24T00:00:00Z",
    payload: {},
    ...overrides,
  };
}

describe("routeV2RuntimeEvents", () => {
  it("routes execution, asset, slot-version, and provider-task effects without authoring refresh", () => {
    const effects = routeV2RuntimeEvents([
      event("execution_waiting", { payload: { execution_id: "execution-1" } }),
      event("asset_version_created", { slot_id: "slot-1" }),
      event("provider_task_completed", { slot_id: "slot-2" }),
    ]);

    expect(effects.execution).toEqual({
      executionId: "execution-1",
      pollingState: "polling",
      workflowRunning: true,
      status: "Workflow V2 run waiting for media",
    });
    expect(effects.refreshRuntime).toBe(true);
    expect(effects.refreshAssets).toBe(true);
    expect(effects.slotVersionSlotIds).toEqual(["slot-1", "slot-2"]);
    expect(effects.providerTaskSlotIds).toEqual(["slot-2"]);
    expect(effects.authoringWorkflowRevisionCreated).toBe(false);
  });

  it("routes screenplay, linked-context, and structure events as synchronization effects", () => {
    const effects = routeV2RuntimeEvents([
      event("script_version_created", { payload: { script_version_id: "script-1" } }),
      event("linked_context_updated", { payload: { refresh: ["assets", "slot_prompts", "script"] } }),
      event("workflow_structure_updated"),
    ]);

    expect(effects.synchronization.refreshScreenplayHistory).toBe(true);
    expect(effects.synchronization.refreshSelectedScreenplay).toBe(true);
    expect(effects.synchronization.refreshWorkflowStructure).toBe(true);
    expect(effects.synchronization.refreshSlotPrompts).toBe(true);
    expect(effects.synchronization.refreshAssets).toBe(true);
    expect(effects.refreshRuntime).toBe(false);
    expect(effects.refreshAssets).toBe(false);
  });

  it("keeps deferred revisions out of authoring refreshes while refreshing candidate slot versions", () => {
    const effects = routeV2RuntimeEvents([
      event("execution_result_revision_deferred", { payload: { slot_ids: ["slot-1", "slot-2"] } }),
      event("workflow_revision_created"),
    ]);

    expect(effects.authoringWorkflowRevisionCreated).toBe(true);
    expect(effects.deferredRevision).toEqual({
      candidateStatus: "New candidate results are available.",
      slotIds: ["slot-1", "slot-2"],
    });
  });

  it("routes final composition events separately from canvas refresh effects", () => {
    const effects = routeV2RuntimeEvents([
      event("final_composition_render_started"),
      event("final_timeline_updated"),
    ]);

    expect(effects.finalCompositionEvents.map((item) => item.event_type)).toEqual([
      "final_composition_render_started",
      "final_timeline_updated",
    ]);
  });
});

describe("routeCanvasRuntimeEvent", () => {
  it("classifies conversation and final-composition events without performing side effects", () => {
    const conversation: CanvasRuntimeEvent = {
      event_seq: 1,
      event_type: "chat_action_applied",
      payload: {},
    };
    const finalComposition: CanvasRuntimeEvent = {
      event_seq: 2,
      event_type: "final_render_completed",
      payload: {},
    };

    expect(routeCanvasRuntimeEvent(conversation)).toEqual({ kind: "conversation_action" });
    expect(routeCanvasRuntimeEvent(finalComposition)).toEqual({ kind: "final_composition" });
  });
});
