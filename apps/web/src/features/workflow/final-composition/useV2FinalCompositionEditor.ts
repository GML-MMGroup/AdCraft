import { useCallback, useMemo, useRef } from "react";

import type {
  V2FinalTimelineSource,
} from "../../../types-v2.ts";
import type { TimelineSessionToken } from "./shotTimelineHistory.ts";
import {
  moveTimelineClipToTrack,
  useTimelineDocument,
} from "./useTimelineDocument.ts";
import { useFinalRenderSession } from "./useFinalRenderSession.ts";
import {
  useTimelinePersistence,
  type V2FinalCompositionConflict,
} from "./useTimelinePersistence.ts";
import {
  useTimelineUiState,
  type V2FinalCompositionEditMode,
  type V2FinalCompositionTool,
} from "./useTimelineUiState.ts";
import { supportsAdvancedTimelineEditor } from "./v2FinalCompositionPolicy.ts";

export {
  moveTimelineClipToTrack,
  type V2FinalCompositionConflict,
  type V2FinalCompositionEditMode,
  type V2FinalCompositionTool,
};

export type CompositionEditorSession = {
  workflowId: string;
  generation: number;
  active: boolean;
};

export type ScopedTimelineSource = {
  session: CompositionEditorSession;
  source: V2FinalTimelineSource;
};

export function resolveScopedTimelineSource(
  pending: ScopedTimelineSource | null,
  currentSession: CompositionEditorSession,
  sources: V2FinalTimelineSource[],
) {
  if (!pending
    || !pending.session.active
    || !currentSession.active
    || pending.session.workflowId !== currentSession.workflowId
    || pending.session.generation !== currentSession.generation) return null;
  return sources.find((source) => source.asset_id === pending.source.asset_id
    && source.version_id === pending.source.version_id
    && source.media_type === pending.source.media_type) ?? null;
}

export function useV2FinalCompositionEditor({
  workflowId,
  active,
  onWorkflowRefresh,
}: {
  workflowId?: string | null;
  active: boolean;
  onWorkflowRefresh?: (workflowId: string) => Promise<unknown> | unknown;
}) {
  const ui = useTimelineUiState();
  const document = useTimelineDocument(ui.documentContract);
  const timelineLoadedRef = useRef<
    (session: TimelineSessionToken) => Promise<unknown>
  >(async () => null);
  const timelineReplacedRef = useRef<() => void>(() => {});
  const handleTimelineLoaded = useCallback(
    (session: TimelineSessionToken) => timelineLoadedRef.current(session),
    [],
  );
  const handleTimelineReplaced = useCallback(
    () => timelineReplacedRef.current(),
    [],
  );
  const persistence = useTimelinePersistence({
    workflowId,
    active,
    document: document.persistenceContract,
    resetUiForSession: ui.resetForSession,
    onTimelineReplaced: handleTimelineReplaced,
    onTimelineLoaded: handleTimelineLoaded,
  });
  const finalRenderDocument = useMemo(() => ({
    baselineRef: document.baselineRef,
    draftRef: document.draftRef,
    finalizeGesture: document.finalizeGesture,
  }), [document.baselineRef, document.draftRef, document.finalizeGesture]);
  const finalRender = useFinalRenderSession({
    active,
    workflowId,
    onWorkflowRefresh,
    document: finalRenderDocument,
    persistence: persistence.renderContract,
  });
  timelineLoadedRef.current = finalRender.loadFinalVideo;
  timelineReplacedRef.current = finalRender.resetRenderProgress;
  const loadTimeline = persistence.load;
  const fitTimelineUi = ui.fitTimeline;
  const draftRef = document.draftRef;

  const selectedClip = useMemo(
    () => document.draft?.clips.find(
      (clip) => clip.clip_id === ui.selectedClipId,
    ) ?? null,
    [document.draft, ui.selectedClipId],
  );
  const load = useCallback((
    options: { preserveDraft?: boolean } = {},
  ) => loadTimeline(options), [loadTimeline]);
  const fitTimeline = useCallback(
    (viewportWidth?: number) => fitTimelineUi(draftRef.current, viewportWidth),
    [draftRef, fitTimelineUi],
  );

  return {
    baseline: document.baseline,
    draft: document.draft,
    sources: persistence.sources,
    capabilities: persistence.capabilities,
    advancedEditorEnabled: supportsAdvancedTimelineEditor(persistence.capabilities),
    staleClipIds: persistence.staleClipIds,
    missingSourceClipIds: persistence.missingSourceClipIds,
    finalVideo: finalRender.finalVideo,
    autoPlayFinalVideo: finalRender.autoPlayFinalVideo,
    tool: ui.tool,
    setTool: ui.setTool,
    editMode: ui.editMode,
    setEditMode: ui.setEditMode,
    snapEnabled: ui.snapEnabled,
    setSnapEnabled: ui.setSnapEnabled,
    zoom: ui.zoom,
    setZoom: ui.setZoom,
    selectedClipIds: ui.selectedClipIds,
    setSelectedClipIds: ui.setSelectedClipIds,
    selectedClip,
    selectedClipId: ui.selectedClipId,
    setSelectedClipId: ui.setSelectedClipId,
    playheadSeconds: ui.playheadSeconds,
    setPlayheadSeconds: ui.setPlayheadSeconds,
    loading: persistence.loading,
    saving: persistence.saving,
    rendering: finalRender.rendering,
    cancellingRender: finalRender.cancellingRender,
    renderJob: finalRender.renderJob,
    renderState: finalRender.renderState,
    renderHint: finalRender.renderHint,
    renderSessionError: finalRender.renderSessionError,
    renderIssue: finalRender.renderIssue,
    error: persistence.error,
    warning: ui.warning,
    snapTarget: ui.snapTarget,
    externalUpdate: document.externalUpdate,
    conflict: persistence.conflict,
    isDirty: document.isDirty,
    canUndo: document.canUndo,
    canRedo: document.canRedo,
    durationSeconds: document.durationSeconds,
    load,
    save: persistence.save,
    render: finalRender.render,
    cancelRender: finalRender.cancelRender,
    reloadRemote: persistence.reloadRemote,
    keepLocal: persistence.keepLocal,
    undo: document.undo,
    redo: document.redo,
    finalizeGesture: document.finalizeGesture,
    moveClip: document.moveClip,
    trimClip: document.trimClip,
    splitAtPlayhead: document.splitAtPlayhead,
    deleteSelection: document.deleteSelection,
    reorderLane: document.reorderLane,
    fitTimeline,
    addSource: document.addSource,
    registerLibrarySource: persistence.registerLibrarySource,
    importLibrarySource: persistence.registerLibrarySource,
    removeImportedLane: document.removeImportedLane,
    addTrack: document.addTrack,
    updateTrack: document.updateTrack,
    splitClip: document.splitClip,
    removeClip: document.removeClip,
    updateClip: document.updateClip,
    setClipAudio: document.setClipAudio,
    setClipColor: document.setClipColor,
    addSubtitle: document.addSubtitle,
    moveClipToTrack: document.moveClipToTrack,
  };
}
