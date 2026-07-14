import type {
  V2FinalCompositionTimeline,
  V2FinalCompositionTimelineClip,
} from "../../../types-v2.ts";

export type { V2FinalCompositionTimeline } from "../../../types-v2.ts";

export function canRenderV2Timeline(timeline: V2FinalCompositionTimeline | null | undefined) {
  return Boolean(timeline?.clips.some((clip) => clip.clip_type === "video"));
}

export function orderedV2TimelineClips(timeline: V2FinalCompositionTimeline) {
  const trackOrder = new Map(timeline.tracks.map((track) => [track.track_id, track.order]));
  return [...timeline.clips].sort((left, right) => (
    (trackOrder.get(left.track_id) ?? Number.MAX_SAFE_INTEGER) - (trackOrder.get(right.track_id) ?? Number.MAX_SAFE_INTEGER) ||
    left.start_time - right.start_time ||
    left.clip_id.localeCompare(right.clip_id)
  ));
}

export function moveV2TimelineClip(
  timeline: V2FinalCompositionTimeline,
  clipId: string,
  direction: -1 | 1,
): V2FinalCompositionTimeline {
  const target = timeline.clips.find((clip) => clip.clip_id === clipId);
  if (!target) return timeline;

  const clipsOnTrack = timeline.clips
    .filter((clip) => clip.track_id === target.track_id)
    .sort((left, right) => left.start_time - right.start_time || left.clip_id.localeCompare(right.clip_id));
  const currentIndex = clipsOnTrack.findIndex((clip) => clip.clip_id === clipId);
  const nextIndex = currentIndex + direction;
  if (currentIndex < 0 || nextIndex < 0 || nextIndex >= clipsOnTrack.length) return timeline;

  const orderedTrackClips = [...clipsOnTrack];
  const [moved] = orderedTrackClips.splice(currentIndex, 1);
  orderedTrackClips.splice(nextIndex, 0, moved);
  const normalizedTrackClips = normalizeTrackStartTimes(orderedTrackClips);
  const retainedClips = timeline.clips.filter((clip) => clip.track_id !== target.track_id);
  const clips = [...normalizedTrackClips, ...retainedClips];

  return {
    ...timeline,
    clips,
    duration_seconds: timelineDuration(clips),
  };
}

function normalizeTrackStartTimes(clips: V2FinalCompositionTimelineClip[]) {
  let cursor = 0;
  return clips.map((clip) => {
    const normalized = { ...clip, start_time: cursor };
    cursor += clip.duration;
    return normalized;
  });
}

function timelineDuration(clips: V2FinalCompositionTimelineClip[]) {
  return clips.reduce((duration, clip) => Math.max(duration, clip.start_time + clip.duration), 0);
}
