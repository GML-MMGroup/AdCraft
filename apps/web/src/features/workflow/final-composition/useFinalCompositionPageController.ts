import { useMemo, useState, type Dispatch, type SetStateAction } from "react";
import type {
  FinalCompositionAvailableSource,
  FinalCompositionTimeline,
  FinalCompositionTimelineResponse,
  FinalCompositionTimelineTrack,
  VideoEditingExportResult,
} from "../../../types";

export type FinalCompositionTimelineViewState = {
  loadedWorkflowId?: string | null;
  timeline: FinalCompositionTimeline | null;
  draft: FinalCompositionTimeline | null;
  availableSources: FinalCompositionAvailableSource[];
  staleClipIds: string[];
  missingSourceClipIds: string[];
  staleReasons: Record<string, string>;
  missingSourceReasons: Record<string, string>;
  loading: boolean;
  saving: boolean;
  rendering: boolean;
  dirty: boolean;
  eventDirty: boolean;
  conflict: string | null;
  error: string | null;
  renderError: string | null;
};

export type FinalCompositionExportSettings = {
  resolution: string;
  aspect_ratio: string;
  fps: number;
  video_codec: string;
  audio_codec: string;
  bitrate: string;
  output_format: string;
};

export type FinalCompositionPageState = {
  timelineState: FinalCompositionTimelineViewState;
  timelineBaselineVersion: number | null;
  exportId: string;
  exportResult: VideoEditingExportResult | null;
  exportSettings: FinalCompositionExportSettings;
};

export type FinalCompositionPageActions = {
  setTimelineState: Dispatch<SetStateAction<FinalCompositionTimelineViewState>>;
  setTimelineBaselineVersion: Dispatch<SetStateAction<number | null>>;
  setExportId: Dispatch<SetStateAction<string>>;
  setExportResult: Dispatch<SetStateAction<VideoEditingExportResult | null>>;
  setExportSettings: Dispatch<SetStateAction<FinalCompositionExportSettings>>;
  resetExportState: () => void;
  timelineLoadStarted: () => void;
  timelineLoadFailed: (message: string) => void;
  applyTimelineResponse: (
    workflowId: string,
    response: FinalCompositionTimelineResponse,
    options?: { preserveDraft?: boolean; eventDirty?: boolean },
  ) => void;
  setTimelineConflict: (message: string | null) => void;
  markTimelineEventDirty: () => void;
  timelineSaveStarted: () => void;
  timelineSaveFailed: (message: string) => void;
  timelineRenderStarted: () => void;
  timelineRenderFailed: (message: string) => void;
  timelineRenderFinished: () => void;
  moveClip: (trackId: string, clipId: string, direction: -1 | 1) => void;
  toggleClip: (trackId: string, clipId: string, enabled: boolean) => void;
  changeClipNumber: (
    trackId: string,
    clipId: string,
    field: "start_time" | "duration" | "trim_start" | "trim_end",
    value: number,
  ) => void;
  changeSubtitleText: (trackId: string, clipId: string, text: string) => void;
  selectAudioSource: (trackId: string, clipId: string, sourceAssetId: string) => void;
  addSourceAsImageClip: (source: FinalCompositionAvailableSource) => void;
  removeClip: (trackId: string, clipId: string) => void;
};

export type FinalCompositionPageController = {
  state: FinalCompositionPageState;
  actions: FinalCompositionPageActions;
};

export const emptyFinalCompositionTimelineState: FinalCompositionTimelineViewState = {
  loadedWorkflowId: null,
  timeline: null,
  draft: null,
  availableSources: [],
  staleClipIds: [],
  missingSourceClipIds: [],
  staleReasons: {},
  missingSourceReasons: {},
  loading: false,
  saving: false,
  rendering: false,
  dirty: false,
  eventDirty: false,
  conflict: null,
  error: null,
  renderError: null,
};

export const defaultFinalCompositionExportSettings: FinalCompositionExportSettings = {
  resolution: "480p",
  aspect_ratio: "16:9",
  fps: 30,
  video_codec: "libx264",
  audio_codec: "aac",
  bitrate: "2500k",
  output_format: "mp4",
};

export function useFinalCompositionPageController(): FinalCompositionPageController {
  const [timelineState, setTimelineState] = useState<FinalCompositionTimelineViewState>(emptyFinalCompositionTimelineState);
  const [timelineBaselineVersion, setTimelineBaselineVersion] = useState<number | null>(null);
  const [exportId, setExportId] = useState("");
  const [exportResult, setExportResult] = useState<VideoEditingExportResult | null>(null);
  const [exportSettings, setExportSettings] = useState<FinalCompositionExportSettings>(defaultFinalCompositionExportSettings);

  const actions = useMemo<FinalCompositionPageActions>(() => ({
    setTimelineState,
    setTimelineBaselineVersion,
    setExportId,
    setExportResult,
    setExportSettings,
    resetExportState() {
      setExportId("");
      setExportResult(null);
    },
    timelineLoadStarted() {
      setTimelineState((current) => ({ ...current, loading: true, error: null }));
    },
    timelineLoadFailed(message) {
      setTimelineState((current) => ({
        ...current,
        loading: false,
        error: message,
      }));
    },
    applyTimelineResponse(workflowId, response, options = {}) {
      const timeline = response.timeline;
      setTimelineBaselineVersion(timeline.version);
      setTimelineState((current) => ({
        ...current,
        loadedWorkflowId: workflowId,
        timeline,
        draft: options.preserveDraft && current.draft ? current.draft : cloneFinalCompositionTimeline(timeline),
        availableSources: response.available_sources ?? [],
        staleClipIds: response.stale_clip_ids ?? [],
        missingSourceClipIds: response.missing_source_clip_ids ?? [],
        staleReasons: response.stale_reasons ?? {},
        missingSourceReasons: response.missing_source_reasons ?? {},
        loading: false,
        saving: false,
        dirty: options.preserveDraft ? current.dirty : false,
        eventDirty: options.eventDirty ?? false,
        conflict: options.preserveDraft ? current.conflict : null,
        error: null,
      }));
    },
    setTimelineConflict(message) {
      setTimelineState((current) => ({ ...current, conflict: message }));
    },
    markTimelineEventDirty() {
      setTimelineState((current) => ({ ...current, eventDirty: true }));
    },
    timelineSaveStarted() {
      setTimelineState((current) => ({ ...current, saving: true, error: null }));
    },
    timelineSaveFailed(message) {
      setTimelineState((current) => ({
        ...current,
        saving: false,
        error: message,
      }));
    },
    timelineRenderStarted() {
      setTimelineState((current) => ({ ...current, rendering: true, renderError: null }));
    },
    timelineRenderFailed(message) {
      setTimelineState((current) => ({
        ...current,
        rendering: false,
        renderError: message,
      }));
    },
    timelineRenderFinished() {
      setTimelineState((current) => ({ ...current, rendering: false, renderError: null }));
    },
    moveClip(trackId, clipId, direction) {
      updateFinalCompositionTimelineDraft(setTimelineState, (timeline) => {
        const track = timeline.tracks.find((item) => item.track_id === trackId);
        if (!track) return;
        const index = track.clips.findIndex((clip) => clip.clip_id === clipId);
        const nextIndex = index + direction;
        if (index < 0 || nextIndex < 0 || nextIndex >= track.clips.length) return;
        const clips = [...track.clips];
        [clips[index], clips[nextIndex]] = [clips[nextIndex], clips[index]];
        track.clips = clips;
      });
    },
    toggleClip(trackId, clipId, enabled) {
      updateFinalCompositionTimelineDraft(setTimelineState, (timeline) => {
        const clip = finalCompositionDraftClip(timeline, trackId, clipId);
        if (clip) clip.enabled = enabled;
      });
    },
    changeClipNumber(trackId, clipId, field, value) {
      updateFinalCompositionTimelineDraft(setTimelineState, (timeline) => {
        const clip = finalCompositionDraftClip(timeline, trackId, clipId);
        if (clip) clip[field] = Number.isFinite(value) ? value : 0;
      });
    },
    changeSubtitleText(trackId, clipId, text) {
      updateFinalCompositionTimelineDraft(setTimelineState, (timeline) => {
        const clip = finalCompositionDraftClip(timeline, trackId, clipId);
        if (clip) clip.text = text;
      });
    },
    selectAudioSource(trackId, clipId, sourceAssetId) {
      updateFinalCompositionTimelineDraft(setTimelineState, (timeline) => {
        const clip = finalCompositionDraftClip(timeline, trackId, clipId);
        if (!clip) return;
        if (sourceAssetId) {
          clip.source_asset_id = sourceAssetId;
        } else {
          delete clip.source_asset_id;
        }
      });
    },
    addSourceAsImageClip(source) {
      updateFinalCompositionTimelineDraft(setTimelineState, (timeline) => {
        const track = ensureFinalCompositionTrack(timeline, "image_overlay", "image");
        if (track.clips.some((clip) => clip.source_asset_id === source.asset_id)) return;
        track.clips = [
          ...track.clips,
          {
            clip_id: source.source_id || source.asset_id,
            clip_type: "image",
            source_asset_id: source.asset_id,
            source_node_id: source.source_node_id ?? "product-generation",
            source_item_id: source.source_item_id ?? null,
            start_time: 0,
            duration: Math.min(3, timeline.duration_seconds || 3),
            enabled: true,
            stale: false,
            metadata: source.metadata ?? {},
          },
        ];
      });
    },
    removeClip(trackId, clipId) {
      updateFinalCompositionTimelineDraft(setTimelineState, (timeline) => {
        const track = timeline.tracks.find((item) => item.track_id === trackId);
        if (!track) return;
        track.clips = track.clips.filter((clip) => clip.clip_id !== clipId);
      });
    },
  }), []);

  return useMemo(
    () => ({
      state: {
        timelineState,
        timelineBaselineVersion,
        exportId,
        exportResult,
        exportSettings,
      },
      actions,
    }),
    [actions, exportId, exportResult, exportSettings, timelineBaselineVersion, timelineState],
  );
}

export function cloneFinalCompositionTimeline(timeline: FinalCompositionTimeline): FinalCompositionTimeline {
  return {
    ...timeline,
    tracks: timeline.tracks.map((track) => ({
      ...track,
      clips: track.clips.map((clip) => ({ ...clip })),
    })),
  };
}

export function finalCompositionRenderDisabledReason(timeline: FinalCompositionTimeline | null, state: FinalCompositionTimelineViewState) {
  if (!timeline) return "Timeline is not loaded.";
  if (state.dirty) return "Render is disabled because there are unsaved timeline changes.";
  const enabledClips = finalCompositionEnabledClips(timeline);
  const enabledVideoClips = enabledClips.filter((clip) => clip.clip_type === "video" || clip.source_node_id === "storyboard-video-generation");
  if (!enabledVideoClips.length) return "No enabled video clips are available for final render.";
  const staleEnabled = enabledClips.filter((clip) => clip.stale || state.staleClipIds.includes(clip.clip_id));
  if (staleEnabled.length) return "Render is disabled because stale enabled clips need review.";
  const missingEnabled = enabledClips.filter((clip) => clip.missing_source || state.missingSourceClipIds.includes(clip.clip_id));
  if (missingEnabled.length) return "Render is disabled because an enabled clip has a missing source.";
  return "";
}

function updateFinalCompositionTimelineDraft(
  setTimelineState: Dispatch<SetStateAction<FinalCompositionTimelineViewState>>,
  updater: (timeline: FinalCompositionTimeline) => void,
) {
  setTimelineState((current) => {
    if (!current.draft) return current;
    const draft = cloneFinalCompositionTimeline(current.draft);
    updater(draft);
    return {
      ...current,
      draft,
      dirty: true,
      conflict: null,
      renderError: null,
    };
  });
}

function finalCompositionDraftClip(timeline: FinalCompositionTimeline, trackId: string, clipId: string) {
  return timeline.tracks.find((track) => track.track_id === trackId)?.clips.find((clip) => clip.clip_id === clipId);
}

function ensureFinalCompositionTrack(timeline: FinalCompositionTimeline, trackId: FinalCompositionTimelineTrack["track_id"], trackType: FinalCompositionTimelineTrack["track_type"]) {
  let track = timeline.tracks.find((item) => item.track_id === trackId);
  if (!track) {
    track = {
      track_id: trackId,
      track_type: trackType,
      enabled: true,
      order: timeline.tracks.length,
      clips: [],
    };
    timeline.tracks = [...timeline.tracks, track];
  }
  return track;
}

function finalCompositionEnabledClips(timeline: FinalCompositionTimeline | null) {
  if (!timeline) return [];
  return timeline.tracks.flatMap((track) => (track.enabled === false ? [] : track.clips.filter((clip) => clip.enabled !== false)));
}
