import type { WorkflowGraph } from "../../../types.ts";

export function useFinalCompositionController(options: {
  workflow?: WorkflowGraph | null;
  selectedNodeId?: string | null;
  refreshWorkflowGraph?: (workflowId: string) => Promise<void>;
} = {}) {
  async function loadFinalCompositionTimeline() {
    return null;
  }
  async function saveFinalCompositionTimeline() {
    return null;
  }
  async function renderFinalCompositionTimeline() {
    return null;
  }
  void options;
  return {
    finalCompositionTimeline: null,
    finalCompositionTimelineDraft: null,
    loadFinalCompositionTimeline,
    saveFinalCompositionTimeline,
    renderFinalCompositionTimeline,
    moveFinalCompositionClip: () => undefined,
    toggleFinalCompositionClip: () => undefined,
    changeFinalCompositionClipNumber: () => undefined,
    changeFinalCompositionSubtitleText: () => undefined,
    selectFinalCompositionAudioSource: () => undefined,
    addFinalCompositionSourceAsImageClip: () => undefined,
    removeFinalCompositionClip: () => undefined,
  };
}
