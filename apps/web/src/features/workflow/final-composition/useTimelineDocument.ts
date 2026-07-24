import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
} from "react";

import type {
  V2FinalCompositionTimeline,
  V2FinalTimelineClip,
  V2FinalTimelineSource,
  V2TimelineTrackType,
} from "../../../types-v2.ts";
import {
  addImportedVideoLane,
  addOrReplaceBgm,
  deleteShotClips,
  moveShotClip,
  removeImportedVideoLane,
  reorderShotLane,
  splitShotClip,
  trimTimelineMediaClip,
  validateShotTimeline,
  type ShotTimelineMutation,
} from "./shotTimelineDomain.ts";
import {
  commitShotTimelineHistory,
  createLoadedShotTimelineSession,
  createShotTimelineHistory,
  finalizeShotTimelineHistory,
  rebaseReloadedShotTimelineHistory,
  reconcileSavedTimeline,
  redoShotTimelineHistory,
  shotTimelineEquals,
  undoShotTimelineHistory,
  type ShotTimelineHistory,
} from "./shotTimelineHistory.ts";
import type { TimelineDocumentUiContract } from "./useTimelineUiState.ts";
import {
  addV2TimelineTrack,
  cloneV2Timeline,
  moveV2TimelineClip,
  removeV2TimelineClip,
  setV2TimelineClipAudio,
  setV2TimelineClipColor,
  splitV2TimelineClip,
  updateV2TimelineClip,
  updateV2TimelineTrack,
  v2TimelineDuration,
} from "./v2TimelineModel.ts";

const BASE_PIXELS_PER_SECOND = 52;

export type TimelinePersistenceDocumentContract = {
  baselineRef: MutableRefObject<V2FinalCompositionTimeline | null>;
  draftRef: MutableRefObject<V2FinalCompositionTimeline | null>;
  historyRef: MutableRefObject<ShotTimelineHistory | null>;
  editRevisionRef: MutableRefObject<number>;
  reset: () => void;
  loadRemote: (
    timeline: V2FinalCompositionTimeline,
    preserveDraft: boolean,
  ) => { keptDraft: boolean };
  reconcileSave: (
    requestDraft: V2FinalCompositionTimeline,
    responseTimeline: V2FinalCompositionTimeline,
  ) => void;
  resolveRemoteConflict: (
    remoteTimeline: V2FinalCompositionTimeline,
    resolution: "keep-local" | "reload-remote",
    requestDraft: V2FinalCompositionTimeline,
    requestEditRevision: number,
  ) => void;
  markExternalUpdate: () => void;
};

export function moveTimelineClipToTrack(
  timeline: V2FinalCompositionTimeline,
  clipId: string,
  trackId: string,
  startTime: number,
): ShotTimelineMutation {
  const clip = timeline.clips.find((candidate) => candidate.clip_id === clipId);
  if (!clip) return rejectedTrackMove(timeline, `Clip ${clipId} does not exist.`);
  const sourceTrack = timeline.tracks.find((candidate) => candidate.track_id === clip.track_id);
  const targetTrack = timeline.tracks.find((candidate) => candidate.track_id === trackId);
  if (!sourceTrack || !targetTrack) return rejectedTrackMove(timeline, `Track ${trackId} does not exist.`);
  if (clip.clip_type !== targetTrack.track_type) {
    return rejectedTrackMove(timeline, "Clip type must match the target track type.");
  }
  if (trackLocked(sourceTrack) || trackLocked(targetTrack)) {
    return rejectedTrackMove(timeline, "Locked tracks cannot accept clip moves.");
  }
  if (!Number.isFinite(startTime) || startTime < 0) {
    return rejectedTrackMove(timeline, "Clip start time is invalid.");
  }
  const moved = moveV2TimelineClip(timeline, clipId, { trackId, startTime });
  const candidate = { ...moved, duration_seconds: v2TimelineDuration(moved) };
  const validation = validateShotTimeline(candidate);
  if (!validation.valid) return rejectedTrackMove(timeline, validation.warnings.join(" "));
  return {
    timeline: candidate,
    changedClipIds: shotTimelineEquals(candidate, timeline) ? [] : [clipId],
    snapTarget: null,
    warning: null,
  };
}

function rejectedTrackMove(timeline: V2FinalCompositionTimeline, warning: string): ShotTimelineMutation {
  return { timeline, changedClipIds: [], snapTarget: null, warning };
}

function trackLocked(track: V2FinalCompositionTimeline["tracks"][number]) {
  const editor = track.metadata.editor;
  return typeof editor === "object" && editor !== null && !Array.isArray(editor)
    && (editor as Record<string, unknown>).locked === true;
}

export function useTimelineDocument(ui: TimelineDocumentUiContract) {
  const [baseline, setBaseline] = useState<V2FinalCompositionTimeline | null>(null);
  const [history, setHistory] = useState<ShotTimelineHistory | null>(null);
  const [externalUpdate, setExternalUpdate] = useState(false);
  const draft = history?.present ?? null;

  const baselineRef = useRef(baseline);
  const historyRef = useRef(history);
  const draftRef = useRef(draft);
  const editRevisionRef = useRef(0);

  const assignBaseline = useCallback((next: V2FinalCompositionTimeline | null) => {
    baselineRef.current = next;
    setBaseline(next);
  }, []);
  const assignHistory = useCallback((next: ShotTimelineHistory | null) => {
    historyRef.current = next;
    draftRef.current = next?.present ?? null;
    setHistory(next);
  }, []);
  const reset = useCallback(() => {
    editRevisionRef.current += 1;
    assignBaseline(null);
    assignHistory(null);
    setExternalUpdate(false);
  }, [assignBaseline, assignHistory]);
  const replaceHistoryPresent = useCallback((timeline: V2FinalCompositionTimeline) => {
    const current = historyRef.current;
    assignHistory(current
      ? { ...current, present: timeline, coalesceKey: null }
      : createShotTimelineHistory(timeline));
  }, [assignHistory]);
  const loadRemote = useCallback((
    timeline: V2FinalCompositionTimeline,
    preserveDraft: boolean,
  ) => {
    const loaded = createLoadedShotTimelineSession(timeline);
    const currentDraft = draftRef.current;
    const previousBaseline = baselineRef.current;
    const keptDraft = preserveDraft
      && currentDraft !== null
      && previousBaseline !== null
      && !shotTimelineEquals(currentDraft, previousBaseline);
    assignBaseline(loaded.baseline);
    if (keptDraft) {
      setExternalUpdate(true);
    } else {
      assignHistory(loaded.history);
      ui.assignSelectedClipIds([]);
      setExternalUpdate(false);
    }
    return { keptDraft };
  }, [assignBaseline, assignHistory, ui]);
  const reconcileSave = useCallback((
    requestDraft: V2FinalCompositionTimeline,
    responseTimeline: V2FinalCompositionTimeline,
  ) => {
    const currentDraft = draftRef.current;
    if (!currentDraft) return;
    const reconciled = reconcileSavedTimeline({
      requestDraft,
      responseTimeline: cloneV2Timeline(responseTimeline),
      currentDraft,
    });
    assignBaseline(reconciled.baseline);
    if (reconciled.draft !== currentDraft) replaceHistoryPresent(reconciled.draft);
    setExternalUpdate(false);
  }, [assignBaseline, replaceHistoryPresent]);
  const resolveRemoteConflict = useCallback((
    remoteTimeline: V2FinalCompositionTimeline,
    resolution: "keep-local" | "reload-remote",
    requestDraft: V2FinalCompositionTimeline,
    requestEditRevision: number,
  ) => {
    const loaded = createLoadedShotTimelineSession(remoteTimeline);
    assignBaseline(loaded.baseline);
    if (resolution === "reload-remote") {
      assignHistory(editRevisionRef.current === requestEditRevision
        ? loaded.history
        : rebaseReloadedShotTimelineHistory({
          history: historyRef.current ?? createShotTimelineHistory(requestDraft),
          requestDraft,
          remoteTimeline: loaded.draft,
        }));
      ui.assignSelectedClipIds([]);
    }
    setExternalUpdate(false);
  }, [assignBaseline, assignHistory, ui]);
  const markExternalUpdate = useCallback(() => setExternalUpdate(true), []);

  const commitTimeline = useCallback((
    timeline: V2FinalCompositionTimeline,
    coalesceKey: string | null = null,
  ) => {
    const current = historyRef.current;
    if (!current) return;
    const next = commitShotTimelineHistory(current, timeline, coalesceKey);
    if (next === current) return;
    editRevisionRef.current += 1;
    assignHistory(next);
    setExternalUpdate(false);
  }, [assignHistory]);
  const finalizeGesture = useCallback(() => {
    const current = historyRef.current;
    if (current) assignHistory(finalizeShotTimelineHistory(current));
  }, [assignHistory]);
  const applyMutation = useCallback((
    mutation: ShotTimelineMutation,
    coalesceKey: string | null = null,
  ) => {
    ui.applyMutationFeedback(mutation);
    if (mutation.timeline !== draftRef.current) commitTimeline(mutation.timeline, coalesceKey);
    return mutation;
  }, [commitTimeline, ui]);
  const editOptions = useCallback(() => {
    const current = draftRef.current;
    return {
      ripple: ui.editModeRef.current === "ripple",
      fps: current?.fps ?? 24,
      snap: {
        enabled: ui.snapEnabledRef.current,
        thresholdSeconds: 8 / (BASE_PIXELS_PER_SECOND * ui.zoomRef.current),
        playhead: ui.playheadRef.current,
      },
    };
  }, [ui]);
  const updateDraft = useCallback((
    updater: (timeline: V2FinalCompositionTimeline) => V2FinalCompositionTimeline,
    coalesceKey: string | null = null,
  ) => {
    const current = draftRef.current;
    if (current) commitTimeline(updater(current), coalesceKey);
  }, [commitTimeline]);
  const undo = useCallback(() => {
    const current = historyRef.current;
    if (!current) return;
    const next = undoShotTimelineHistory(current);
    if (next === current) return;
    editRevisionRef.current += 1;
    assignHistory(next);
    ui.assignSelectedClipIds(ui.selectedClipIdsRef.current.filter(
      (clipId) => next.present.clips.some((clip) => clip.clip_id === clipId),
    ));
    ui.clearMutationFeedback();
  }, [assignHistory, ui]);
  const redo = useCallback(() => {
    const current = historyRef.current;
    if (!current) return;
    const next = redoShotTimelineHistory(current);
    if (next === current) return;
    editRevisionRef.current += 1;
    assignHistory(next);
    ui.assignSelectedClipIds(ui.selectedClipIdsRef.current.filter(
      (clipId) => next.present.clips.some((clip) => clip.clip_id === clipId),
    ));
    ui.clearMutationFeedback();
  }, [assignHistory, ui]);

  const moveClip = useCallback((
    clipId: string,
    trackIdOrStartTime: string | number,
    startTimeOrCoalesceKey?: number | string,
    coalesceKey: string | null = null,
  ) => {
    const current = draftRef.current;
    if (!current) return null;
    const startTime = typeof trackIdOrStartTime === "number" ? trackIdOrStartTime : startTimeOrCoalesceKey;
    const key = typeof trackIdOrStartTime === "number" && typeof startTimeOrCoalesceKey === "string"
      ? startTimeOrCoalesceKey
      : coalesceKey;
    if (typeof startTime !== "number") return null;
    return typeof trackIdOrStartTime === "string"
      ? applyMutation(moveTimelineClipToTrack(current, clipId, trackIdOrStartTime, startTime), key)
      : applyMutation(moveShotClip(current, clipId, startTime, editOptions()), key);
  }, [applyMutation, editOptions]);
  const trimClip = useCallback((
    clipId: string,
    edge: "left" | "right",
    sourceTime: number,
    coalesceKey: string | null = null,
  ) => {
    const current = draftRef.current;
    return current
      ? applyMutation(trimTimelineMediaClip(current, clipId, edge, sourceTime, editOptions()), coalesceKey)
      : null;
  }, [applyMutation, editOptions]);
  const splitAtPlayhead = useCallback((clipId = ui.selectedClipIdsRef.current[0]) => {
    const current = draftRef.current;
    return current && clipId
      ? applyMutation(splitShotClip(current, clipId, ui.playheadRef.current, editOptions()))
      : null;
  }, [applyMutation, editOptions, ui]);
  const deleteSelection = useCallback(() => {
    const current = draftRef.current;
    if (!current) return null;
    const mutation = applyMutation(deleteShotClips(current, ui.selectedClipIdsRef.current, editOptions()));
    if (mutation.timeline !== current) ui.assignSelectedClipIds([]);
    return mutation;
  }, [applyMutation, editOptions, ui]);
  const reorderLane = useCallback((trackId: string, targetIndex: number) => {
    const current = draftRef.current;
    return current ? applyMutation(reorderShotLane(current, trackId, targetIndex)) : null;
  }, [applyMutation]);
  const addSource = useCallback((source: V2FinalTimelineSource) => {
    const current = draftRef.current;
    if (!current) return null;
    const mutation = source.media_type === "video"
      ? addImportedVideoLane(current, source, ui.playheadRef.current)
      : source.media_type === "audio"
        ? addOrReplaceBgm(current, source)
        : null;
    if (!mutation) {
      ui.applyMutationFeedback({
        timeline: current,
        changedClipIds: [],
        snapTarget: null,
        warning: "Only video and audio sources can be added to Final Composition.",
      });
      return null;
    }
    const result = applyMutation(mutation);
    if (result.timeline !== current) {
      const selected = result.changedClipIds.find(
        (clipId) => result.timeline.clips.some((clip) => clip.clip_id === clipId),
      );
      if (selected) ui.assignSelectedClipIds([selected]);
    }
    return result;
  }, [applyMutation, ui]);
  const removeImportedLane = useCallback((trackId: string) => {
    const current = draftRef.current;
    if (!current) return null;
    const mutation = applyMutation(removeImportedVideoLane(current, trackId));
    if (mutation.timeline !== current) {
      ui.assignSelectedClipIds(ui.selectedClipIdsRef.current.filter(
        (clipId) => mutation.timeline.clips.some((clip) => clip.clip_id === clipId),
      ));
    }
    return mutation;
  }, [applyMutation, ui]);
  const removeClip = useCallback((clipId: string) => {
    const current = draftRef.current;
    const clip = current?.clips.find((candidate) => candidate.clip_id === clipId);
    if (current && clip?.clip_type === "video") {
      applyMutation(deleteShotClips(current, [clipId], editOptions()));
    } else {
      updateDraft((timeline) => removeV2TimelineClip(timeline, clipId));
    }
    ui.assignSelectedClipIds(ui.selectedClipIdsRef.current.filter((currentId) => currentId !== clipId));
  }, [applyMutation, editOptions, ui, updateDraft]);

  const persistenceContract = useMemo<TimelinePersistenceDocumentContract>(() => ({
    baselineRef,
    draftRef,
    historyRef,
    editRevisionRef,
    reset,
    loadRemote,
    reconcileSave,
    resolveRemoteConflict,
    markExternalUpdate,
  }), [
    loadRemote,
    markExternalUpdate,
    reconcileSave,
    reset,
    resolveRemoteConflict,
  ]);

  return {
    baseline,
    draft,
    externalUpdate,
    isDirty: useMemo(() => !shotTimelineEquals(draft, baseline), [baseline, draft]),
    canUndo: (history?.past.length ?? 0) > 0,
    canRedo: (history?.future.length ?? 0) > 0,
    durationSeconds: draft ? v2TimelineDuration(draft) : 0,
    baselineRef,
    draftRef,
    reset,
    updateDraft,
    applyMutation,
    editOptions,
    undo,
    redo,
    finalizeGesture,
    moveClip,
    trimClip,
    splitAtPlayhead,
    deleteSelection,
    reorderLane,
    addSource,
    removeImportedLane,
    addTrack: (type: V2TimelineTrackType) => updateDraft(
      (timeline) => addV2TimelineTrack(timeline, type),
    ),
    updateTrack: (
      trackId: string,
      update: Parameters<typeof updateV2TimelineTrack>[2],
    ) => updateDraft((timeline) => updateV2TimelineTrack(timeline, trackId, update)),
    splitClip: (clipId: string, at: number) => {
      const current = draftRef.current;
      if (!current) return;
      const clip = current.clips.find((candidate) => candidate.clip_id === clipId);
      if (clip?.clip_type === "video") applyMutation(splitShotClip(current, clipId, at, editOptions()));
      else updateDraft((timeline) => splitV2TimelineClip(timeline, clipId, at));
    },
    removeClip,
    updateClip: (
      clipId: string,
      updater: (clip: V2FinalTimelineClip) => V2FinalTimelineClip,
    ) => updateDraft((timeline) => updateV2TimelineClip(timeline, clipId, updater)),
    setClipAudio: (
      clipId: string,
      update: Parameters<typeof setV2TimelineClipAudio>[2],
    ) => updateDraft((timeline) => setV2TimelineClipAudio(timeline, clipId, update)),
    setClipColor: (
      clipId: string,
      update: Parameters<typeof setV2TimelineClipColor>[2],
    ) => updateDraft((timeline) => setV2TimelineClipColor(timeline, clipId, update)),
    addSubtitle: () => updateDraft((timeline) => {
      const existingTrack = timeline.tracks.find((track) => track.track_type === "subtitle");
      const nextTimeline = existingTrack ? cloneV2Timeline(timeline) : addV2TimelineTrack(timeline, "subtitle");
      const track = existingTrack ?? nextTimeline.tracks.find(
        (candidate) => candidate.track_type === "subtitle",
      )!;
      const startTime = Math.max(
        0,
        ...nextTimeline.clips
          .filter((clip) => clip.track_id === track.track_id)
          .map((clip) => clip.start_time + clip.duration),
      );
      const duration = 3;
      return {
        ...nextTimeline,
        duration_seconds: Math.max(nextTimeline.duration_seconds, startTime + duration),
        clips: [...nextTimeline.clips, {
          clip_id: `subtitle-${Date.now().toString(36)}`,
          track_id: track.track_id,
          clip_type: "subtitle" as const,
          source_asset_id: null,
          source_version_id: null,
          source_slot_id: null,
          start_time: startTime,
          duration,
          trim_in: 0,
          trim_out: null,
          volume: 1,
          muted: false,
          enabled: true,
          transform: {
            x: 0,
            y: 0,
            scale_x: 1,
            scale_y: 1,
            rotation_degrees: 0,
            opacity: 1,
            fit: "contain" as const,
          },
          audio: { volume: 1, muted: false, fade_in_seconds: 0, fade_out_seconds: 0 },
          color: {
            preset_id: "none",
            brightness: 0,
            contrast: 1,
            saturation: 1,
            exposure: 0,
            temperature: 0,
            tint: 0,
            hue: 0,
          },
          text: "New subtitle",
          subtitle_style: { font_size: 42, color: "#FFFFFF", position: "bottom_center" as const },
          metadata: {},
        }],
      };
    }),
    moveClipToTrack: (clipId: string, trackId: string, startTime: number) => {
      const current = draftRef.current;
      return current
        ? applyMutation(moveTimelineClipToTrack(current, clipId, trackId, startTime))
        : null;
    },
    persistenceContract,
  };
}
