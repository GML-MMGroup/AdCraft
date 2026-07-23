export const FINAL_COMPOSITION_EVENT_NAME = "v2-final-composition-events";
export const FINAL_COMPOSITION_SOURCE_SELECTION_EVENT = "slot_selected_version_updated";

const TIMELINE_RELOAD_EVENT_TYPES = new Set([
  "final_timeline_created",
  "final_timeline_updated",
  FINAL_COMPOSITION_SOURCE_SELECTION_EVENT,
]);

export function shouldReloadFinalCompositionTimeline(eventTypes: string[]) {
  return eventTypes.some((eventType) => TIMELINE_RELOAD_EVENT_TYPES.has(eventType));
}

export function notifyFinalCompositionSourceSelection(workflowId: string, sourceSlotId: string) {
  window.dispatchEvent(new CustomEvent(FINAL_COMPOSITION_EVENT_NAME, {
    detail: {
      workflowId,
      eventTypes: [FINAL_COMPOSITION_SOURCE_SELECTION_EVENT],
      sourceSlotId,
    },
  }));
}
