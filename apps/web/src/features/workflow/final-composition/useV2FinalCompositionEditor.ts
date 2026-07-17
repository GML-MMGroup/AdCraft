import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { V2ApiError, v2Api } from "../../../api/v2Client.ts";
import type {
  V2FinalCompositionTimeline,
  V2FinalTimelineClip,
  V2FinalTimelineRenderStartResponse,
  V2FinalTimelineSource,
  V2FinalTimelineUpdateResponse,
  V2TimelineTrackType,
} from "../../../types-v2.ts";
import {
  deleteShotClips,
  moveShotClip,
  reorderShotLane,
  splitShotClip,
  trimShotClip,
  validateShotTimeline,
  type ShotTimelineMutation,
  type ShotTimelineSnapTarget,
} from "./shotTimelineDomain.ts";
import {
  commitShotTimelineHistory,
  createLatestSaveQueue,
  createLoadedShotTimelineSession,
  createRemoteStateEpoch,
  createShotTimelineHistory,
  createTimelineSessionGuard,
  finalizeShotTimelineHistory,
  reconcileReloadedTimeline,
  reconcileSavedTimeline,
  redoShotTimelineHistory,
  shotTimelineEquals,
  undoShotTimelineHistory,
  type ShotTimelineHistory,
  type TimelineSessionToken,
} from "./shotTimelineHistory.ts";
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
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 4;

export type V2FinalCompositionTool = "select" | "blade";
export type V2FinalCompositionEditMode = "normal" | "ripple";
export type V2FinalCompositionConflict = {
  kind: "version-conflict";
  message: string;
};

type LibrarySourceSelection = {
  entityId: string;
  assetId: string;
  mediaType: "video" | "audio";
};

type TimelineSaveSnapshot = {
  session: TimelineSessionToken;
  baseline: V2FinalCompositionTimeline;
  draft: V2FinalCompositionTimeline;
};

type TimelineSaveQueue = {
  request: (session: TimelineSessionToken) => Promise<V2FinalTimelineUpdateResponse | null>;
  isRunning: () => boolean;
};

function readableError(error: unknown) {
  if (error instanceof V2ApiError) return error.message || error.code || "Timeline request failed.";
  return error instanceof Error ? error.message : "Timeline request failed.";
}

function defaultDurationFor(source: V2FinalTimelineSource) {
  if (typeof source.duration_seconds === "number" && source.duration_seconds > 0) return Math.round(source.duration_seconds * 100) / 100;
  return source.media_type === "audio" ? 12 : 5;
}

function trackTypeForSource(source: V2FinalTimelineSource): V2TimelineTrackType {
  return source.media_type === "audio" ? "audio" : source.media_type === "image" ? "image" : "video";
}

function makeClip(source: V2FinalTimelineSource, trackId: string, startTime: number): V2FinalTimelineClip {
  const duration = defaultDurationFor(source);
  return {
    clip_id: `clip-${source.asset_id}-${source.version_id}-${Date.now().toString(36)}`,
    track_id: trackId,
    clip_type: trackTypeForSource(source),
    source_asset_id: source.asset_id,
    source_version_id: source.version_id,
    source_slot_id: null,
    start_time: startTime,
    duration,
    trim_in: 0,
    trim_out: duration,
    volume: 1,
    muted: false,
    enabled: true,
    transform: { x: 0, y: 0, scale_x: 1, scale_y: 1, rotation_degrees: 0, opacity: 1, fit: "contain" },
    audio: { volume: 1, muted: false, fade_in_seconds: 0, fade_out_seconds: 0 },
    color: { preset_id: "none", brightness: 0, contrast: 1, saturation: 1, exposure: 0, temperature: 0, tint: 0, hue: 0 },
    text: null,
    subtitle_style: { font_size: 42, color: "#FFFFFF", position: "bottom_center" },
    metadata: {},
  };
}

function clampZoom(value: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

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

export function useV2FinalCompositionEditor({
  workflowId,
  active,
  onWorkflowRefresh,
}: {
  workflowId?: string | null;
  active: boolean;
  onWorkflowRefresh?: (workflowId: string) => Promise<unknown> | unknown;
}) {
  const [baseline, setBaseline] = useState<V2FinalCompositionTimeline | null>(null);
  const [history, setHistory] = useState<ShotTimelineHistory | null>(null);
  const [sources, setSources] = useState<V2FinalTimelineSource[]>([]);
  const [selectedClipIdsState, setSelectedClipIdsState] = useState<string[]>([]);
  const [playheadSeconds, setPlayheadSecondsState] = useState(0);
  const [tool, setToolState] = useState<V2FinalCompositionTool>("select");
  const [editMode, setEditModeState] = useState<V2FinalCompositionEditMode>("normal");
  const [snapEnabled, setSnapEnabledState] = useState(true);
  const [zoom, setZoomState] = useState(1);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [renderJob, setRenderJob] = useState<V2FinalTimelineRenderStartResponse | null>(null);
  const [error, setError] = useState("");
  const [warning, setWarning] = useState("");
  const [snapTarget, setSnapTarget] = useState<ShotTimelineSnapTarget | null>(null);
  const [externalUpdate, setExternalUpdate] = useState(false);
  const [conflict, setConflict] = useState<V2FinalCompositionConflict | null>(null);

  const draft = history?.present ?? null;
  const baselineRef = useRef(baseline);
  const historyRef = useRef(history);
  const draftRef = useRef(draft);
  const selectedClipIdsRef = useRef(selectedClipIdsState);
  const playheadRef = useRef(playheadSeconds);
  const editModeRef = useRef(editMode);
  const snapEnabledRef = useRef(snapEnabled);
  const zoomRef = useRef(zoom);
  const conflictRef = useRef(conflict);
  const renderingRef = useRef(rendering);
  const onWorkflowRefreshRef = useRef(onWorkflowRefresh);
  const loadRequestRef = useRef(0);
  const editRevisionRef = useRef(0);
  const sessionGuardRef = useRef(createTimelineSessionGuard());
  const remoteStateEpochRef = useRef(createRemoteStateEpoch());
  const performSaveRef = useRef<(snapshot: TimelineSaveSnapshot) => Promise<V2FinalTimelineUpdateResponse | null>>(async () => null);
  const saveQueueRef = useRef<TimelineSaveQueue | null>(null);

  const sessionTransition = sessionGuardRef.current.update(workflowId ?? null);
  if (sessionTransition.changed) {
    remoteStateEpochRef.current.invalidate();
    loadRequestRef.current += 1;
    editRevisionRef.current += 1;
    baselineRef.current = null;
    historyRef.current = null;
    draftRef.current = null;
    conflictRef.current = null;
    renderingRef.current = false;
  } else {
    baselineRef.current = baseline;
    historyRef.current = history;
    draftRef.current = draft;
    conflictRef.current = conflict;
    renderingRef.current = rendering;
  }
  selectedClipIdsRef.current = selectedClipIdsState;
  playheadRef.current = playheadSeconds;
  editModeRef.current = editMode;
  snapEnabledRef.current = snapEnabled;
  zoomRef.current = zoom;
  onWorkflowRefreshRef.current = onWorkflowRefresh;

  const assignBaseline = useCallback((next: V2FinalCompositionTimeline | null) => {
    baselineRef.current = next;
    setBaseline(next);
  }, []);

  const assignHistory = useCallback((next: ShotTimelineHistory | null) => {
    historyRef.current = next;
    draftRef.current = next?.present ?? null;
    setHistory(next);
  }, []);

  const assignConflict = useCallback((next: V2FinalCompositionConflict | null) => {
    conflictRef.current = next;
    setConflict(next);
  }, []);

  const assignSelectedClipIds = useCallback((ids: string[]) => {
    const next = [...new Set(ids)];
    selectedClipIdsRef.current = next;
    setSelectedClipIdsState(next);
  }, []);

  const replaceHistoryPresent = useCallback((timeline: V2FinalCompositionTimeline) => {
    const current = historyRef.current;
    assignHistory(current
      ? { ...current, present: timeline, coalesceKey: null }
      : createShotTimelineHistory(timeline));
  }, [assignHistory]);

  const load = useCallback(async ({ preserveDraft = false }: { preserveDraft?: boolean } = {}) => {
    const session = sessionGuardRef.current.capture();
    const requestedWorkflowId = session.workflowId;
    if (!requestedWorkflowId) return null;
    const requestId = ++loadRequestRef.current;
    const remoteEpoch = remoteStateEpochRef.current.claim();
    setLoading(true);
    setError("");
    try {
      const response = await v2Api.getFinalTimeline(requestedWorkflowId);
      if (requestId !== loadRequestRef.current
        || !sessionGuardRef.current.isCurrent(session)
        || !remoteStateEpochRef.current.isCurrent(remoteEpoch)) return null;
      const loaded = createLoadedShotTimelineSession(response.timeline);
      const currentDraft = draftRef.current;
      const previousBaseline = baselineRef.current;
      const keepDraft = preserveDraft
        && currentDraft !== null
        && previousBaseline !== null
        && !shotTimelineEquals(currentDraft, previousBaseline);
      assignBaseline(loaded.baseline);
      setSources(response.available_sources);
      if (keepDraft) {
        setExternalUpdate(true);
      } else {
        assignHistory(loaded.history);
        assignSelectedClipIds([]);
        setRenderJob(null);
        setExternalUpdate(false);
        assignConflict(null);
      }
      return response;
    } catch (loadError) {
      if (requestId === loadRequestRef.current && sessionGuardRef.current.isCurrent(session)) {
        setError(readableError(loadError));
      }
      return null;
    } finally {
      if (requestId === loadRequestRef.current && sessionGuardRef.current.isCurrent(session)) setLoading(false);
    }
  }, [assignBaseline, assignConflict, assignHistory, assignSelectedClipIds]);

  useEffect(() => {
    assignBaseline(null);
    assignHistory(null);
    assignSelectedClipIds([]);
    assignConflict(null);
    setSources([]);
    setRenderJob(null);
    setExternalUpdate(false);
    setLoading(false);
    setSaving(false);
    setRendering(false);
    setError("");
    setWarning("");
    setSnapTarget(null);
  }, [assignBaseline, assignConflict, assignHistory, assignSelectedClipIds, workflowId]);

  useEffect(() => {
    if (!active || !workflowId) return;
    void load();
  }, [active, load, workflowId]);

  useEffect(() => {
    const handleTimelineEvent = (event: Event) => {
      const detail = (event as CustomEvent<{ workflowId?: string; eventTypes?: string[] }>).detail;
      if (detail?.workflowId !== workflowId) return;
      const eventTypes = detail.eventTypes ?? [];
      if (eventTypes.some((eventType) => eventType === "final_timeline_created" || eventType === "final_timeline_updated" || eventType === "final_composition_render_completed")) {
        void load({ preserveDraft: true });
      }
    };
    window.addEventListener("v2-final-composition-events", handleTimelineEvent);
    return () => window.removeEventListener("v2-final-composition-events", handleTimelineEvent);
  }, [load, workflowId]);

  const commitTimeline = useCallback((timeline: V2FinalCompositionTimeline, coalesceKey: string | null = null) => {
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
    if (!current) return;
    assignHistory(finalizeShotTimelineHistory(current));
  }, [assignHistory]);

  const applyMutation = useCallback((mutation: ShotTimelineMutation, coalesceKey: string | null = null) => {
    setWarning(mutation.warning ?? "");
    setSnapTarget(mutation.snapTarget);
    if (mutation.timeline !== draftRef.current) commitTimeline(mutation.timeline, coalesceKey);
    return mutation;
  }, [commitTimeline]);

  const editOptions = useCallback(() => {
    const current = draftRef.current;
    return {
      ripple: editModeRef.current === "ripple",
      fps: current?.fps ?? 24,
      snap: {
        enabled: snapEnabledRef.current,
        thresholdSeconds: 8 / (BASE_PIXELS_PER_SECOND * zoomRef.current),
        playhead: playheadRef.current,
      },
    };
  }, []);

  const updateDraft = useCallback((updater: (timeline: V2FinalCompositionTimeline) => V2FinalCompositionTimeline, coalesceKey: string | null = null) => {
    const current = draftRef.current;
    if (!current) return;
    commitTimeline(updater(current), coalesceKey);
  }, [commitTimeline]);

  const undo = useCallback(() => {
    const current = historyRef.current;
    if (!current) return;
    const next = undoShotTimelineHistory(current);
    if (next === current) return;
    editRevisionRef.current += 1;
    assignHistory(next);
    assignSelectedClipIds(selectedClipIdsRef.current.filter((clipId) => next.present.clips.some((clip) => clip.clip_id === clipId)));
    setWarning("");
    setSnapTarget(null);
  }, [assignHistory, assignSelectedClipIds]);

  const redo = useCallback(() => {
    const current = historyRef.current;
    if (!current) return;
    const next = redoShotTimelineHistory(current);
    if (next === current) return;
    editRevisionRef.current += 1;
    assignHistory(next);
    assignSelectedClipIds(selectedClipIdsRef.current.filter((clipId) => next.present.clips.some((clip) => clip.clip_id === clipId)));
    setWarning("");
    setSnapTarget(null);
  }, [assignHistory, assignSelectedClipIds]);

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
    if (typeof trackIdOrStartTime === "string") {
      return applyMutation(moveTimelineClipToTrack(current, clipId, trackIdOrStartTime, startTime), key);
    }
    return applyMutation(moveShotClip(current, clipId, startTime, editOptions()), key);
  }, [applyMutation, editOptions]);

  const trimClip = useCallback((clipId: string, edge: "left" | "right", sourceTime: number, coalesceKey: string | null = null) => {
    const current = draftRef.current;
    if (!current) return null;
    return applyMutation(trimShotClip(current, clipId, edge, sourceTime, editOptions()), coalesceKey);
  }, [applyMutation, editOptions]);

  const splitAtPlayhead = useCallback((clipId = selectedClipIdsRef.current[0]) => {
    const current = draftRef.current;
    if (!current || !clipId) return null;
    return applyMutation(splitShotClip(current, clipId, playheadRef.current, editOptions()));
  }, [applyMutation, editOptions]);

  const deleteSelection = useCallback(() => {
    const current = draftRef.current;
    if (!current) return null;
    const mutation = applyMutation(deleteShotClips(current, selectedClipIdsRef.current, editOptions()));
    if (mutation.timeline !== current) assignSelectedClipIds([]);
    return mutation;
  }, [applyMutation, assignSelectedClipIds, editOptions]);

  const reorderLane = useCallback((trackId: string, targetIndex: number) => {
    const current = draftRef.current;
    if (!current) return null;
    return applyMutation(reorderShotLane(current, trackId, targetIndex));
  }, [applyMutation]);

  const setTool = useCallback((next: V2FinalCompositionTool) => setToolState(next), []);
  const setEditMode = useCallback((next: V2FinalCompositionEditMode) => {
    editModeRef.current = next;
    setEditModeState(next);
  }, []);
  const setSnapEnabled = useCallback((next: boolean) => {
    snapEnabledRef.current = next;
    setSnapEnabledState(next);
  }, []);
  const setZoom = useCallback((next: number) => {
    const clamped = clampZoom(next);
    zoomRef.current = clamped;
    setZoomState(clamped);
  }, []);
  const fitTimeline = useCallback((viewportWidth?: number) => {
    const duration = draftRef.current ? v2TimelineDuration(draftRef.current) : 0;
    const next = viewportWidth && duration > 0
      ? clampZoom(viewportWidth / (duration * BASE_PIXELS_PER_SECOND))
      : 1;
    zoomRef.current = next;
    setZoomState(next);
    return next;
  }, []);
  const setSelectedClipIds = useCallback((ids: string[]) => assignSelectedClipIds(ids), [assignSelectedClipIds]);
  const setSelectedClipId = useCallback((clipId: string | null) => assignSelectedClipIds(clipId ? [clipId] : []), [assignSelectedClipIds]);
  const setPlayheadSeconds = useCallback((seconds: number) => {
    const next = Math.max(0, seconds);
    playheadRef.current = next;
    setPlayheadSecondsState(next);
  }, []);

  if (!saveQueueRef.current) {
    saveQueueRef.current = createLatestSaveQueue<TimelineSaveSnapshot, V2FinalTimelineUpdateResponse | null, TimelineSessionToken>(
      (session) => {
        if (!sessionGuardRef.current.isCurrent(session)) return null;
        const currentBaseline = baselineRef.current;
        const currentDraft = draftRef.current;
        if (!session.workflowId || !currentBaseline || !currentDraft || conflictRef.current) return null;
        if (shotTimelineEquals(currentDraft, currentBaseline)) return null;
        return { session, baseline: currentBaseline, draft: currentDraft };
      },
      (snapshot) => performSaveRef.current(snapshot),
    );
  }

  performSaveRef.current = async (snapshot) => {
    const workflowId = snapshot.session.workflowId;
    if (!workflowId || !sessionGuardRef.current.isCurrent(snapshot.session)) return null;
    remoteStateEpochRef.current.claim();
    setError("");
    try {
      const response = await v2Api.saveFinalTimeline(workflowId, {
        expected_version: snapshot.baseline.version,
        timeline: snapshot.draft,
      });
      if (!sessionGuardRef.current.isCurrent(snapshot.session)) return null;
      remoteStateEpochRef.current.invalidate();
      const responseTimeline = cloneV2Timeline(response.timeline);
      const currentDraft = draftRef.current;
      if (!currentDraft) return response;
      const reconciled = reconcileSavedTimeline({
        requestDraft: snapshot.draft,
        responseTimeline,
        currentDraft,
      });
      assignBaseline(reconciled.baseline);
      if (reconciled.draft !== currentDraft) replaceHistoryPresent(reconciled.draft);
      setExternalUpdate(false);
      assignConflict(null);
      return response;
    } catch (saveError) {
      if (!sessionGuardRef.current.isCurrent(snapshot.session)) return null;
      if (saveError instanceof V2ApiError && saveError.status === 409) {
        const message = "Timeline changed elsewhere. Choose Keep local to rebase your draft or Reload remote to discard it.";
        assignConflict({ kind: "version-conflict", message });
        setExternalUpdate(true);
        setError(message);
      } else {
        setError(readableError(saveError));
      }
      return null;
    }
  };

  const save = useCallback(() => {
    const session = sessionGuardRef.current.capture();
    const queue = saveQueueRef.current!;
    const pending = queue.request(session);
    setSaving(true);
    void pending.then(
      () => {
        if (sessionGuardRef.current.isCurrent(session) && !queue.isRunning()) setSaving(false);
      },
      (saveError) => {
        if (sessionGuardRef.current.isCurrent(session)) {
          if (!queue.isRunning()) setSaving(false);
          setError(readableError(saveError));
        }
      },
    );
    return pending;
  }, []);

  const resolveConflictWithRemote = useCallback(async (resolution: "keep-local" | "reload-remote") => {
    const session = sessionGuardRef.current.capture();
    const requestedWorkflowId = session.workflowId;
    const requestDraft = draftRef.current;
    if (!requestedWorkflowId || !requestDraft || !conflictRef.current) return null;
    const requestId = ++loadRequestRef.current;
    const remoteEpoch = remoteStateEpochRef.current.claim();
    const requestEditRevision = editRevisionRef.current;
    setLoading(true);
    setError("");
    try {
      const response = await v2Api.getFinalTimeline(requestedWorkflowId);
      if (requestId !== loadRequestRef.current
        || !sessionGuardRef.current.isCurrent(session)
        || !remoteStateEpochRef.current.isCurrent(remoteEpoch)) return null;
      const loaded = createLoadedShotTimelineSession(response.timeline);
      const currentDraft = draftRef.current;
      if (!currentDraft) return null;
      assignBaseline(loaded.baseline);
      setSources(response.available_sources);
      if (resolution === "reload-remote") {
        const reconciled = reconcileReloadedTimeline({
          requestDraft,
          currentDraft,
          remoteTimeline: loaded.draft,
        });
        assignHistory(editRevisionRef.current === requestEditRevision
          ? loaded.history
          : createShotTimelineHistory(reconciled.draft));
        assignSelectedClipIds([]);
      }
      setExternalUpdate(false);
      assignConflict(null);
      return response;
    } catch (loadError) {
      if (requestId === loadRequestRef.current && sessionGuardRef.current.isCurrent(session)) {
        setError(readableError(loadError));
      }
      return null;
    } finally {
      if (requestId === loadRequestRef.current && sessionGuardRef.current.isCurrent(session)) setLoading(false);
    }
  }, [assignBaseline, assignConflict, assignHistory, assignSelectedClipIds]);

  const keepLocal = useCallback(() => resolveConflictWithRemote("keep-local"), [resolveConflictWithRemote]);
  const reloadRemote = useCallback(() => resolveConflictWithRemote("reload-remote"), [resolveConflictWithRemote]);

  const render = useCallback(async () => {
    const session = sessionGuardRef.current.capture();
    const requestedWorkflowId = session.workflowId;
    if (!requestedWorkflowId || !draftRef.current || !baselineRef.current || renderingRef.current) return null;
    if (!shotTimelineEquals(draftRef.current, baselineRef.current)) {
      await save();
      if (!sessionGuardRef.current.isCurrent(session)) return null;
      if (!draftRef.current || !baselineRef.current || !shotTimelineEquals(draftRef.current, baselineRef.current)) return null;
    }
    const timeline = baselineRef.current;
    renderingRef.current = true;
    setRendering(true);
    setError("");
    try {
      const response = await v2Api.renderFinalTimeline(requestedWorkflowId, {
        timeline_id: timeline.timeline_id,
        timeline_version: timeline.version,
      });
      if (!sessionGuardRef.current.isCurrent(session)) return null;
      setRenderJob(response);
      await onWorkflowRefreshRef.current?.(requestedWorkflowId);
      return response;
    } catch (renderError) {
      if (sessionGuardRef.current.isCurrent(session)) {
        if (renderError instanceof V2ApiError && renderError.status === 409) {
          const message = "Timeline changed elsewhere. Resolve the version conflict before rendering.";
          assignConflict({ kind: "version-conflict", message });
          setExternalUpdate(true);
        }
        setError(readableError(renderError));
      }
      return null;
    } finally {
      if (sessionGuardRef.current.isCurrent(session)) {
        renderingRef.current = false;
        setRendering(false);
      }
    }
  }, [assignConflict, save]);

  const addSource = useCallback((source: V2FinalTimelineSource) => {
    updateDraft((timeline) => {
      const trackType = trackTypeForSource(source);
      const matchingTracks = timeline.tracks.filter((track) => track.track_type === trackType).sort((a, b) => a.order - b.order);
      const nextTimeline = matchingTracks.length ? cloneV2Timeline(timeline) : addV2TimelineTrack(timeline, trackType);
      const track = (matchingTracks[0] ?? nextTimeline.tracks.find((candidate) => candidate.track_type === trackType))!;
      const startTime = trackType === "audio" ? 0 : Math.max(0, ...nextTimeline.clips.filter((clip) => clip.track_id === track.track_id).map((clip) => clip.start_time + clip.duration));
      const clip = makeClip(source, track.track_id, Math.round(startTime * 100) / 100);
      return { ...nextTimeline, duration_seconds: Math.max(nextTimeline.duration_seconds, clip.start_time + clip.duration), clips: [...nextTimeline.clips, clip] };
    });
  }, [updateDraft]);

  const importLibrarySource = useCallback(async (selection: LibrarySourceSelection) => {
    const session = sessionGuardRef.current.capture();
    const currentWorkflowId = session.workflowId;
    if (!currentWorkflowId) return null;
    setError("");
    try {
      const response = await v2Api.importFinalTimelineSource(currentWorkflowId, {
        library_entity_id: selection.entityId,
        library_asset_id: selection.assetId,
        expected_media_type: selection.mediaType,
      });
      if (!sessionGuardRef.current.isCurrent(session)) return null;
      setSources((current) => [...current.filter((item) => item.version_id !== response.source.version_id), response.source]);
      addSource(response.source);
      return response.source;
    } catch (importError) {
      if (sessionGuardRef.current.isCurrent(session)) setError(readableError(importError));
      return null;
    }
  }, [addSource]);

  const selectedClipIds = selectedClipIdsState;
  const selectedClipId = selectedClipIds[0] ?? null;
  const selectedClip = useMemo(() => draft?.clips.find((clip) => clip.clip_id === selectedClipId) ?? null, [draft, selectedClipId]);
  const isDirty = useMemo(() => !shotTimelineEquals(draft, baseline), [baseline, draft]);

  return {
    baseline,
    draft,
    sources,
    tool,
    setTool,
    editMode,
    setEditMode,
    snapEnabled,
    setSnapEnabled,
    zoom,
    setZoom,
    selectedClipIds,
    setSelectedClipIds,
    selectedClip,
    selectedClipId,
    setSelectedClipId,
    playheadSeconds,
    setPlayheadSeconds,
    loading,
    saving,
    rendering,
    renderJob,
    renderState: null,
    error,
    warning,
    snapTarget,
    externalUpdate,
    conflict,
    isDirty,
    canUndo: (history?.past.length ?? 0) > 0,
    canRedo: (history?.future.length ?? 0) > 0,
    durationSeconds: draft ? v2TimelineDuration(draft) : 0,
    load,
    save,
    render,
    reloadRemote,
    keepLocal,
    undo,
    redo,
    finalizeGesture,
    moveClip,
    trimClip,
    splitAtPlayhead,
    deleteSelection,
    reorderLane,
    fitTimeline,
    addSource,
    importLibrarySource,
    addTrack: (type: V2TimelineTrackType) => updateDraft((timeline) => addV2TimelineTrack(timeline, type)),
    updateTrack: (trackId: string, update: Parameters<typeof updateV2TimelineTrack>[2]) => updateDraft((timeline) => updateV2TimelineTrack(timeline, trackId, update)),
    splitClip: (clipId: string, at: number) => {
      const current = draftRef.current;
      if (!current) return;
      const clip = current.clips.find((candidate) => candidate.clip_id === clipId);
      if (clip?.clip_type === "video") applyMutation(splitShotClip(current, clipId, at, editOptions()));
      else updateDraft((timeline) => splitV2TimelineClip(timeline, clipId, at));
    },
    removeClip: (clipId: string) => {
      const current = draftRef.current;
      const clip = current?.clips.find((candidate) => candidate.clip_id === clipId);
      if (current && clip?.clip_type === "video") {
        applyMutation(deleteShotClips(current, [clipId], editOptions()));
      } else {
        updateDraft((timeline) => removeV2TimelineClip(timeline, clipId));
      }
      assignSelectedClipIds(selectedClipIdsRef.current.filter((currentId) => currentId !== clipId));
    },
    updateClip: (clipId: string, updater: (clip: V2FinalTimelineClip) => V2FinalTimelineClip) => updateDraft((timeline) => updateV2TimelineClip(timeline, clipId, updater)),
    setClipAudio: (clipId: string, update: Parameters<typeof setV2TimelineClipAudio>[2]) => updateDraft((timeline) => setV2TimelineClipAudio(timeline, clipId, update)),
    setClipColor: (clipId: string, update: Parameters<typeof setV2TimelineClipColor>[2]) => updateDraft((timeline) => setV2TimelineClipColor(timeline, clipId, update)),
    addSubtitle: () => updateDraft((timeline) => {
      const existingTrack = timeline.tracks.find((track) => track.track_type === "subtitle");
      const nextTimeline = existingTrack ? cloneV2Timeline(timeline) : addV2TimelineTrack(timeline, "subtitle");
      const track = existingTrack ?? nextTimeline.tracks.find((candidate) => candidate.track_type === "subtitle")!;
      const startTime = Math.max(0, ...nextTimeline.clips.filter((clip) => clip.track_id === track.track_id).map((clip) => clip.start_time + clip.duration));
      const duration = 3;
      return {
        ...nextTimeline,
        duration_seconds: Math.max(nextTimeline.duration_seconds, startTime + duration),
        clips: [...nextTimeline.clips, { clip_id: `subtitle-${Date.now().toString(36)}`, track_id: track.track_id, clip_type: "subtitle", source_asset_id: null, source_version_id: null, source_slot_id: null, start_time: startTime, duration, trim_in: 0, trim_out: null, volume: 1, muted: false, enabled: true, transform: { x: 0, y: 0, scale_x: 1, scale_y: 1, rotation_degrees: 0, opacity: 1, fit: "contain" }, audio: { volume: 1, muted: false, fade_in_seconds: 0, fade_out_seconds: 0 }, color: { preset_id: "none", brightness: 0, contrast: 1, saturation: 1, exposure: 0, temperature: 0, tint: 0, hue: 0 }, text: "New subtitle", subtitle_style: { font_size: 42, color: "#FFFFFF", position: "bottom_center" }, metadata: {} }],
      };
    }),
    moveClipToTrack: (clipId: string, trackId: string, startTime: number) => {
      const current = draftRef.current;
      return current ? applyMutation(moveTimelineClipToTrack(current, clipId, trackId, startTime)) : null;
    },
  };
}
