import type {
  V2FinalCompositionTimeline,
  V2FinalTimelineClip,
  V2FinalTimelineTrack,
  V2TimelineAudio,
  V2TimelineColor,
  V2TimelineTrackType,
} from "../../../types-v2.ts";

export const V2_TIMELINE_SNAP_PRECISION = 100;

export function cloneV2Timeline(timeline: V2FinalCompositionTimeline): V2FinalCompositionTimeline {
  return {
    ...timeline,
    resolution: { ...timeline.resolution },
    metadata: { ...timeline.metadata },
    tracks: timeline.tracks.map((track) => ({ ...track, metadata: { ...track.metadata } })),
    clips: timeline.clips.map((clip) => ({
      ...clip,
      transform: clip.transform ? { ...clip.transform } : undefined,
      audio: clip.audio ? { ...clip.audio } : undefined,
      color: clip.color ? { ...clip.color } : undefined,
      subtitle_style: clip.subtitle_style ? { ...clip.subtitle_style } : undefined,
      metadata: { ...clip.metadata },
    })),
  };
}

export function snapV2TimelineSeconds(value: number) {
  return Math.max(0, Math.round(value * V2_TIMELINE_SNAP_PRECISION) / V2_TIMELINE_SNAP_PRECISION);
}

export function moveV2TimelineClip(
  timeline: V2FinalCompositionTimeline,
  clipId: string,
  target: { trackId: string; startTime: number },
): V2FinalCompositionTimeline {
  if (!timeline.tracks.some((track) => track.track_id === target.trackId)) return timeline;
  return updateV2TimelineClip(timeline, clipId, (clip) => ({
    ...clip,
    track_id: target.trackId,
    start_time: snapV2TimelineSeconds(target.startTime),
  }));
}

export function splitV2TimelineClip(timeline: V2FinalCompositionTimeline, clipId: string, splitTime: number): V2FinalCompositionTimeline {
  const clip = timeline.clips.find((candidate) => candidate.clip_id === clipId);
  if (!clip) return timeline;
  const splitAt = snapV2TimelineSeconds(splitTime);
  const clipEnd = snapV2TimelineSeconds(clip.start_time + clip.duration);
  if (splitAt <= clip.start_time || splitAt >= clipEnd || clip.clip_type === "subtitle") return timeline;

  const firstDuration = snapV2TimelineSeconds(splitAt - clip.start_time);
  const secondDuration = snapV2TimelineSeconds(clip.duration - firstDuration);
  const trimIn = clip.trim_in ?? 0;
  const trimOut = clip.trim_out ?? snapV2TimelineSeconds(trimIn + clip.duration);
  const splitTrim = snapV2TimelineSeconds(trimIn + firstDuration);
  const first: V2FinalTimelineClip = {
    ...cloneV2TimelineClip(clip),
    duration: firstDuration,
    trim_out: splitTrim,
  };
  const second: V2FinalTimelineClip = {
    ...cloneV2TimelineClip(clip),
    clip_id: `${clip.clip_id}-split-${Math.round(splitAt * 100)}`,
    start_time: splitAt,
    duration: secondDuration,
    trim_in: splitTrim,
    trim_out: trimOut,
  };
  return {
    ...cloneV2Timeline(timeline),
    clips: timeline.clips.flatMap((candidate) => (candidate.clip_id === clipId ? [first, second] : [cloneV2TimelineClip(candidate)])),
  };
}

export function updateV2TimelineClip(
  timeline: V2FinalCompositionTimeline,
  clipId: string,
  updater: (clip: V2FinalTimelineClip) => V2FinalTimelineClip,
): V2FinalCompositionTimeline {
  return {
    ...cloneV2Timeline(timeline),
    clips: timeline.clips.map((clip) => (clip.clip_id === clipId ? updater(cloneV2TimelineClip(clip)) : cloneV2TimelineClip(clip))),
  };
}

export function addV2TimelineTrack(timeline: V2FinalCompositionTimeline, type: V2TimelineTrackType): V2FinalCompositionTimeline {
  const nextOrder = Math.max(0, ...timeline.tracks.map((track) => track.order)) + 1;
  const nextIndex = timeline.tracks.filter((track) => track.track_type === type).length + 1;
  const track: V2FinalTimelineTrack = {
    track_id: `${type}-${nextIndex}`,
    track_type: type,
    order: nextOrder,
    enabled: true,
    metadata: {},
  };
  return { ...cloneV2Timeline(timeline), tracks: [...timeline.tracks.map((item) => ({ ...item, metadata: { ...item.metadata } })), track] };
}

export function removeV2TimelineClip(timeline: V2FinalCompositionTimeline, clipId: string): V2FinalCompositionTimeline {
  return { ...cloneV2Timeline(timeline), clips: timeline.clips.filter((clip) => clip.clip_id !== clipId).map(cloneV2TimelineClip) };
}

export function updateV2TimelineTrack(
  timeline: V2FinalCompositionTimeline,
  trackId: string,
  update: Partial<V2FinalTimelineTrack>,
): V2FinalCompositionTimeline {
  return {
    ...cloneV2Timeline(timeline),
    tracks: timeline.tracks.map((track) => (track.track_id === trackId ? { ...track, ...update, track_id: track.track_id, track_type: track.track_type } : { ...track })),
  };
}

export function setV2TimelineClipAudio(timeline: V2FinalCompositionTimeline, clipId: string, update: Partial<V2TimelineAudio>) {
  return updateV2TimelineClip(timeline, clipId, (clip) => ({
    ...clip,
    audio: { volume: 1, muted: false, fade_in_seconds: 0, fade_out_seconds: 0, ...clip.audio, ...update },
  }));
}

export function setV2TimelineClipColor(timeline: V2FinalCompositionTimeline, clipId: string, update: Partial<V2TimelineColor>) {
  return updateV2TimelineClip(timeline, clipId, (clip) => ({
    ...clip,
    color: { preset_id: "none", brightness: 0, contrast: 1, saturation: 1, exposure: 0, temperature: 0, tint: 0, hue: 0, ...clip.color, ...update },
  }));
}

export function v2TimelineDuration(timeline: V2FinalCompositionTimeline) {
  return Math.max(timeline.duration_seconds, ...timeline.clips.map((clip) => clip.start_time + clip.duration), 0);
}

function cloneV2TimelineClip(clip: V2FinalTimelineClip): V2FinalTimelineClip {
  return {
    ...clip,
    transform: clip.transform ? { ...clip.transform } : undefined,
    audio: clip.audio ? { ...clip.audio } : undefined,
    color: clip.color ? { ...clip.color } : undefined,
    subtitle_style: clip.subtitle_style ? { ...clip.subtitle_style } : undefined,
    metadata: { ...clip.metadata },
  };
}
