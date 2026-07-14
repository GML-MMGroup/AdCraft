import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { V2ApiError, v2Api } from "../../../api/v2Client.ts";
import type {
  V2FinalCompositionTimeline,
  V2FinalTimelineClip,
  V2FinalTimelineSource,
  V2TimelineTrackType,
} from "../../../types-v2.ts";
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

type LibrarySourceSelection = {
  entityId: string;
  assetId: string;
  mediaType: "video" | "audio";
};

function timelineEquals(left: V2FinalCompositionTimeline | null, right: V2FinalCompositionTimeline | null) {
  return JSON.stringify(left) === JSON.stringify(right);
}

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
    start_time: startTime,
    duration,
    trim_in: 0,
    trim_out: duration,
    enabled: true,
    transform: source.media_type === "audio" ? undefined : { x: 0, y: 0, scale_x: 1, scale_y: 1, rotation: 0, opacity: 1, fit: "contain" },
    audio: source.media_type === "audio" || source.media_type === "video" ? { volume: 1, muted: false, fade_in: 0, fade_out: 0 } : undefined,
    color: source.media_type === "audio" ? undefined : { preset_id: "none", brightness: 0, contrast: 1, saturation: 1, exposure: 0, temperature: 0, tint: 0, hue: 0 },
  };
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
  const [draft, setDraft] = useState<V2FinalCompositionTimeline | null>(null);
  const [sources, setSources] = useState<V2FinalTimelineSource[]>([]);
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [playheadSeconds, setPlayheadSeconds] = useState(0);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [error, setError] = useState("");
  const [externalUpdate, setExternalUpdate] = useState(false);
  const currentWorkflowId = useRef<string | null>(null);
  const baselineRef = useRef<V2FinalCompositionTimeline | null>(null);

  useEffect(() => {
    baselineRef.current = baseline;
  }, [baseline]);

  const isDirty = useMemo(() => !timelineEquals(draft, baseline), [baseline, draft]);
  const selectedClip = useMemo(() => draft?.clips.find((clip) => clip.clip_id === selectedClipId) ?? null, [draft, selectedClipId]);

  const load = useCallback(async ({ preserveDraft = false }: { preserveDraft?: boolean } = {}) => {
    if (!workflowId) return null;
    currentWorkflowId.current = workflowId;
    setLoading(true);
    setError("");
    try {
      const response = await v2Api.getFinalTimeline(workflowId);
      if (currentWorkflowId.current !== workflowId) return null;
      const nextBaseline = cloneV2Timeline(response.timeline);
      setBaseline(nextBaseline);
      setSources(response.available_sources);
      setDraft((current) => {
        if (preserveDraft && current && !timelineEquals(current, baselineRef.current)) {
          setExternalUpdate(true);
          return current;
        }
        setExternalUpdate(false);
        return cloneV2Timeline(nextBaseline);
      });
      return response;
    } catch (loadError) {
      if (currentWorkflowId.current === workflowId) setError(readableError(loadError));
      return null;
    } finally {
      if (currentWorkflowId.current === workflowId) setLoading(false);
    }
  }, [workflowId]);

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

  const updateDraft = useCallback((updater: (timeline: V2FinalCompositionTimeline) => V2FinalCompositionTimeline) => {
    setDraft((current) => current ? updater(current) : current);
    setExternalUpdate(false);
  }, []);

  const save = useCallback(async () => {
    if (!workflowId || !draft || !baseline || saving) return null;
    setSaving(true);
    setError("");
    try {
      const response = await v2Api.saveFinalTimeline(workflowId, { expected_version: baseline.version, timeline: draft });
      const next = cloneV2Timeline(response.timeline);
      setBaseline(next);
      setDraft(cloneV2Timeline(next));
      setExternalUpdate(false);
      return response;
    } catch (saveError) {
      if (saveError instanceof V2ApiError && saveError.status === 409) {
        setExternalUpdate(true);
        setError("Timeline changed elsewhere. Your local draft is retained; refresh to compare before saving again.");
        void load({ preserveDraft: true });
      } else {
        setError(readableError(saveError));
      }
      return null;
    } finally {
      setSaving(false);
    }
  }, [baseline, draft, load, saving, workflowId]);

  const render = useCallback(async () => {
    if (!workflowId || !draft || !baseline || rendering) return null;
    let timeline = baseline;
    if (!timelineEquals(draft, baseline)) {
      const saved = await save();
      if (!saved) return null;
      timeline = saved.timeline;
    }
    setRendering(true);
    setError("");
    try {
      const response = await v2Api.renderFinalTimeline(workflowId, {
        timeline_id: timeline.timeline_id,
        timeline_version: timeline.version,
        render_settings: timeline.render_settings,
      });
      await onWorkflowRefresh?.(workflowId);
      return response;
    } catch (renderError) {
      if (renderError instanceof V2ApiError && renderError.status === 409) {
        setExternalUpdate(true);
        void load({ preserveDraft: true });
      }
      setError(readableError(renderError));
      return null;
    } finally {
      setRendering(false);
    }
  }, [baseline, draft, load, onWorkflowRefresh, rendering, save, workflowId]);

  const addSource = useCallback((source: V2FinalTimelineSource) => {
    updateDraft((timeline) => {
      const trackType = trackTypeForSource(source);
      const matchingTracks = timeline.tracks.filter((track) => track.track_type === trackType && !track.locked).sort((a, b) => a.order - b.order);
      const nextTimeline = matchingTracks.length ? cloneV2Timeline(timeline) : addV2TimelineTrack(timeline, trackType);
      const track = (matchingTracks[0] ?? nextTimeline.tracks.find((candidate) => candidate.track_type === trackType))!;
      const startTime = trackType === "audio" ? 0 : Math.max(0, ...nextTimeline.clips.filter((clip) => clip.track_id === track.track_id).map((clip) => clip.start_time + clip.duration));
      const clip = makeClip(source, track.track_id, Math.round(startTime * 100) / 100);
      return { ...nextTimeline, duration_seconds: Math.max(nextTimeline.duration_seconds, clip.start_time + clip.duration), clips: [...nextTimeline.clips, clip] };
    });
  }, [updateDraft]);

  const importLibrarySource = useCallback(async (selection: LibrarySourceSelection) => {
    if (!workflowId) return null;
    setError("");
    try {
      const response = await v2Api.importFinalTimelineSource(workflowId, {
        library_entity_id: selection.entityId,
        library_asset_id: selection.assetId,
        expected_media_type: selection.mediaType,
      });
      setSources((current) => [...current.filter((item) => item.version_id !== response.source.version_id), response.source]);
      addSource(response.source);
      return response.source;
    } catch (importError) {
      setError(readableError(importError));
      return null;
    }
  }, [addSource, workflowId]);

  return {
    baseline,
    draft,
    sources,
    selectedClip,
    selectedClipId,
    setSelectedClipId,
    playheadSeconds,
    setPlayheadSeconds,
    loading,
    saving,
    rendering,
    error,
    externalUpdate,
    isDirty,
    durationSeconds: draft ? v2TimelineDuration(draft) : 0,
    load,
    save,
    render,
    addSource,
    importLibrarySource,
    addTrack: (type: V2TimelineTrackType) => updateDraft((timeline) => addV2TimelineTrack(timeline, type)),
    updateTrack: (trackId: string, update: Parameters<typeof updateV2TimelineTrack>[2]) => updateDraft((timeline) => updateV2TimelineTrack(timeline, trackId, update)),
    moveClip: (clipId: string, trackId: string, startTime: number) => updateDraft((timeline) => moveV2TimelineClip(timeline, clipId, { trackId, startTime })),
    splitClip: (clipId: string, at: number) => updateDraft((timeline) => splitV2TimelineClip(timeline, clipId, at)),
    removeClip: (clipId: string) => {
      updateDraft((timeline) => removeV2TimelineClip(timeline, clipId));
      setSelectedClipId((current) => current === clipId ? null : current);
    },
    updateClip: (clipId: string, updater: (clip: V2FinalTimelineClip) => V2FinalTimelineClip) => updateDraft((timeline) => updateV2TimelineClip(timeline, clipId, updater)),
    setClipAudio: (clipId: string, update: Parameters<typeof setV2TimelineClipAudio>[2]) => updateDraft((timeline) => setV2TimelineClipAudio(timeline, clipId, update)),
    setClipColor: (clipId: string, update: Parameters<typeof setV2TimelineClipColor>[2]) => updateDraft((timeline) => setV2TimelineClipColor(timeline, clipId, update)),
    addSubtitle: () => updateDraft((timeline) => {
      const existingTrack = timeline.tracks.find((track) => track.track_type === "subtitle" && !track.locked);
      const nextTimeline = existingTrack ? cloneV2Timeline(timeline) : addV2TimelineTrack(timeline, "subtitle");
      const track = existingTrack ?? nextTimeline.tracks.find((candidate) => candidate.track_type === "subtitle")!;
      const startTime = Math.max(0, ...nextTimeline.clips.filter((clip) => clip.track_id === track.track_id).map((clip) => clip.start_time + clip.duration));
      const duration = 3;
      return {
        ...nextTimeline,
        duration_seconds: Math.max(nextTimeline.duration_seconds, startTime + duration),
        clips: [...nextTimeline.clips, { clip_id: `subtitle-${Date.now().toString(36)}`, track_id: track.track_id, clip_type: "subtitle", start_time: startTime, duration, enabled: true, text: "New subtitle", style: { font_size: 42, color: "#FFFFFF", position: "bottom_center" } }],
      };
    }),
  };
}
