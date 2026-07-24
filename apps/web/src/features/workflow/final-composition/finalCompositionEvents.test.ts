import { afterEach, describe, expect, it, vi } from "vitest";

import {
  notifyFinalCompositionSourceSelection,
  shouldReloadFinalCompositionTimeline,
} from "./finalCompositionEvents.ts";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("final composition source events", () => {
  it("reloads the timeline when a selected source version changes", () => {
    expect(shouldReloadFinalCompositionTimeline(["slot_selected_version_updated"])).toBe(true);
    expect(shouldReloadFinalCompositionTimeline(["slot_generation_completed"])).toBe(false);
  });

  it("dispatches a workflow-scoped source selection event", () => {
    const listener = vi.fn();
    window.addEventListener("v2-final-composition-events", listener);

    notifyFinalCompositionSourceSelection("workflow-1", "bgm-slot");

    expect(listener).toHaveBeenCalledTimes(1);
    const detail = (listener.mock.calls[0][0] as CustomEvent).detail;
    expect(detail).toEqual({
      workflowId: "workflow-1",
      eventTypes: ["slot_selected_version_updated"],
      sourceSlotId: "bgm-slot",
    });
    window.removeEventListener("v2-final-composition-events", listener);
  });
});
