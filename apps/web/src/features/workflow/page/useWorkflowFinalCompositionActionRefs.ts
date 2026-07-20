import { useCallback, type RefObject } from "react";
import type { MediaStatus, WorkflowNode } from "../../../types.ts";
import type { useFinalCompositionOperations } from "../final-composition/useFinalCompositionOperations.ts";

type FinalCompositionOperationsRef = RefObject<ReturnType<typeof useFinalCompositionOperations> | null>;

export function useWorkflowFinalCompositionActionRefs(finalCompositionOperationsRef: FinalCompositionOperationsRef) {
  const prepareFinalCompositionRun = useCallback((finalNode: WorkflowNode) => (
    finalCompositionOperationsRef.current?.actions.prepareFinalCompositionRun(finalNode) ?? Promise.resolve(null)
  ), [finalCompositionOperationsRef]);

  const pollStoryboardVideoMedia = useCallback((workflowId: string) => (
    finalCompositionOperationsRef.current?.actions.pollStoryboardVideoMedia(workflowId) ?? Promise.resolve(null)
  ), [finalCompositionOperationsRef]);

  const refreshMediaStatus = useCallback((requestWorkflowId?: string) => (
    finalCompositionOperationsRef.current?.actions.refreshMediaStatus(requestWorkflowId) ?? Promise.resolve(null)
  ), [finalCompositionOperationsRef]);

  const refreshSelectedNodeRun = useCallback(() => (
    finalCompositionOperationsRef.current?.actions.refreshSelectedNodeRun() ?? Promise.resolve()
  ), [finalCompositionOperationsRef]);

  const reviewSelectedNodeQuality = useCallback(() => (
    finalCompositionOperationsRef.current?.actions.reviewSelectedNodeQuality() ?? Promise.resolve()
  ), [finalCompositionOperationsRef]);

  const exportEditedVideo = useCallback(() => (
    finalCompositionOperationsRef.current?.actions.exportEditedVideo() ?? Promise.resolve()
  ), [finalCompositionOperationsRef]);

  const refreshVideoExport = useCallback(() => (
    finalCompositionOperationsRef.current?.actions.refreshVideoExport() ?? Promise.resolve()
  ), [finalCompositionOperationsRef]);

  const loadFinalCompositionTimeline = useCallback((requestWorkflowId: string, options?: { preserveDraft?: boolean; eventDirty?: boolean }) => (
    finalCompositionOperationsRef.current?.actions.loadFinalCompositionTimeline(requestWorkflowId, options) ?? Promise.resolve()
  ), [finalCompositionOperationsRef]);

  const loadFinalCompositionCandidateHistory = useCallback((requestWorkflowId: string) => (
    finalCompositionOperationsRef.current?.actions.loadFinalCompositionCandidateHistory(requestWorkflowId) ?? Promise.resolve()
  ), [finalCompositionOperationsRef]);

  const saveFinalCompositionTimeline = useCallback(() => (
    finalCompositionOperationsRef.current?.actions.saveFinalCompositionTimeline() ?? Promise.resolve()
  ), [finalCompositionOperationsRef]);

  const renderFinalCompositionTimeline = useCallback(() => (
    finalCompositionOperationsRef.current?.actions.renderFinalCompositionTimeline() ?? Promise.resolve()
  ), [finalCompositionOperationsRef]);

  const applyMediaStatusToCanvas = useCallback((nextMediaStatus: MediaStatus | null) => {
    finalCompositionOperationsRef.current?.actions.applyMediaStatusToCanvas(nextMediaStatus);
  }, [finalCompositionOperationsRef]);

  return {
    prepareFinalCompositionRun,
    pollStoryboardVideoMedia,
    refreshMediaStatus,
    refreshSelectedNodeRun,
    reviewSelectedNodeQuality,
    exportEditedVideo,
    refreshVideoExport,
    loadFinalCompositionTimeline,
    loadFinalCompositionCandidateHistory,
    saveFinalCompositionTimeline,
    renderFinalCompositionTimeline,
    applyMediaStatusToCanvas,
  };
}
