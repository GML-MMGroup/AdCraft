import type {
  V2FinalCompositionTimeline,
  V2FinalTimelineClip,
  V2FinalTimelineTrack,
} from "../../../types-v2.ts";
import {
  cloneV2Timeline,
  cloneV2TimelineClip,
  snapV2TimelineToFrame,
  v2TimelineDuration,
  withV2TimelineDuration,
} from "./v2TimelineModel.ts";

const EPSILON = 1e-9;
const TRACK_TYPES = ["video", "audio", "image", "subtitle"] as const;
const COLOR_PRESETS = ["none", "warm", "cool", "high_contrast", "muted"] as const;
const SUBTITLE_POSITIONS = ["top_center", "center", "bottom_center"] as const;

export type ShotTimelineEditOptions = {
  ripple: boolean;
  fps: number;
  snap?: { enabled: boolean; thresholdSeconds: number; playhead: number };
};

export type ShotTimelineSnapTarget = {
  type: "zero" | "playhead" | "clip-start" | "clip-end";
  time: number;
  clipId?: string;
};

export type ShotTimelineValidation = {
  valid: boolean;
  warnings: string[];
};

export type ShotTimelineMutation = {
  timeline: V2FinalCompositionTimeline;
  changedClipIds: string[];
  snapTarget: ShotTimelineSnapTarget | null;
  warning: string | null;
};

type TrimEdge = "left" | "right";

export function projectDefaultTimelineToShotLanes(
  timeline: V2FinalCompositionTimeline,
): V2FinalCompositionTimeline {
  const videoTracks = canonicalTrackOrder(timeline.tracks.filter((track) => track.track_type === "video"));
  if (videoTracks.length !== 1) return cloneV2Timeline(timeline);

  const sourceTrack = videoTracks[0];
  const shotClips = timeline.clips
    .filter((clip) => clip.track_id === sourceTrack.track_id && clip.clip_type === "video")
    .sort((left, right) => left.start_time - right.start_time || left.clip_id.localeCompare(right.clip_id));
  if (shotClips.length < 2) return cloneV2Timeline(timeline);

  const projected = cloneV2Timeline(timeline);
  const sourceEditor = editorMetadata(sourceTrack);
  const laneByClipId = new Map<string, string>();
  const reservedTrackIds = new Set(
    projected.tracks.filter((track) => track.track_type !== "video").map((track) => track.track_id),
  );
  const lanes = shotClips.map((clip, index): V2FinalTimelineTrack => {
    const shotNumber = index + 1;
    const trackId = uniqueTrackId(`shot-${String(shotNumber).padStart(2, "0")}`, reservedTrackIds);
    reservedTrackIds.add(trackId);
    laneByClipId.set(clip.clip_id, trackId);
    return {
      ...sourceTrack,
      track_id: trackId,
      order: shotNumber,
      metadata: {
        ...cloneRecord(sourceTrack.metadata),
        editor: {
          ...cloneRecord(sourceEditor),
          name: `Shot ${String(shotNumber).padStart(2, "0")}`,
          locked: sourceEditor.locked === true,
          hidden: sourceEditor.hidden === true,
        },
      },
    };
  });
  const retainedTracks = canonicalTrackOrder(projected.tracks.filter((track) => track.track_type !== "video"));
  const nonVideoTracks = retainedTracks
    .map((track, index): V2FinalTimelineTrack => {
      const editor = editorMetadata(track);
      return {
        ...track,
        order: lanes.length + retainedTracks.length - index,
        metadata: {
          ...track.metadata,
          editor: {
            ...editor,
            name: typeof editor.name === "string" && editor.name ? editor.name : track.track_id,
            locked: editor.locked === true,
            hidden: editor.hidden === true,
          },
        },
      };
    });

  projected.tracks = nonVideoTracks.concat([...lanes].reverse());
  projected.clips = projected.clips.map((clip) => {
    const trackId = laneByClipId.get(clip.clip_id);
    return trackId ? { ...clip, track_id: trackId } : clip;
  });
  const candidate = withV2TimelineDuration(projected);
  return validateShotTimeline(candidate).valid ? candidate : cloneV2Timeline(timeline);
}

export function moveShotClip(
  timeline: V2FinalCompositionTimeline,
  clipId: string,
  targetStartTime: number,
  options: ShotTimelineEditOptions,
): ShotTimelineMutation {
  const setup = editableVideoClip(timeline, clipId, options);
  if (typeof setup === "string") return unchanged(timeline, setup);
  if (!Number.isFinite(targetStartTime) || targetStartTime < 0) return unchanged(timeline, "Shot start time is invalid.");

  const snapped = snapMoveStart(timeline, setup.clip, targetStartTime, options);
  if (snapped.startTime < 0) return unchanged(timeline, "Shot start time cannot be negative.");
  if (nearlyEqual(snapped.startTime, setup.clip.start_time)) {
    return { timeline, changedClipIds: [], snapTarget: snapped.target, warning: null };
  }

  const next = cloneV2Timeline(timeline);
  findClip(next, clipId)!.start_time = snapped.startTime;
  return finishMutation(timeline, next, [clipId], snapped.target, null);
}

export function trimShotClip(
  timeline: V2FinalCompositionTimeline,
  clipId: string,
  edge: TrimEdge,
  sourceTime: number,
  options: ShotTimelineEditOptions,
): ShotTimelineMutation {
  const setup = editableVideoClip(timeline, clipId, options);
  if (typeof setup === "string") return unchanged(timeline, setup);
  if (!Number.isFinite(sourceTime)) return unchanged(timeline, "Trim time is invalid.");

  const fps = options.fps;
  const frame = 1 / fps;
  const clip = setup.clip;
  const trimIn = snapV2TimelineToFrame(clip.trim_in, fps);
  const trimOut = snapV2TimelineToFrame(clip.trim_out ?? clip.trim_in + clip.duration, fps);
  const nextTrim = snapV2TimelineToFrame(sourceTime, fps);
  if (nextTrim < 0 || (edge === "left" ? nextTrim >= trimOut - EPSILON : nextTrim <= trimIn + EPSILON)) {
    return unchanged(timeline, "Trim must leave at least one frame of source media.");
  }
  if ((edge === "left" ? trimOut - nextTrim : nextTrim - trimIn) < frame - EPSILON) {
    return unchanged(timeline, "Trim must leave at least one frame of source media.");
  }

  if (edge === "right") {
    const sourceDuration = knownSourceDuration(clip);
    if (nextTrim > trimOut + EPSILON && sourceDuration === null) {
      return unchanged(timeline, "Source duration is required before extending this trim.");
    }
    if (sourceDuration !== null && nextTrim > nonExpandingFrameBound(sourceDuration, fps) + EPSILON) {
      return unchanged(timeline, "Trim exceeds the source duration.");
    }
  }

  const next = cloneV2Timeline(timeline);
  const edited = findClip(next, clipId)!;
  const originalEnd = clip.start_time + clip.duration;
  if (edge === "left") {
    const startDelta = snapV2TimelineToFrame(nextTrim - trimIn, fps);
    const nextStart = snapV2TimelineToFrame(clip.start_time + startDelta, fps);
    if (nextStart < 0) return unchanged(timeline, "Left trim cannot move before timeline zero.");
    edited.start_time = nextStart;
    edited.trim_in = nextTrim;
    edited.trim_out = trimOut;
  } else {
    edited.trim_in = trimIn;
    edited.trim_out = nextTrim;
  }
  edited.duration = snapV2TimelineToFrame((edited.trim_out ?? trimOut) - edited.trim_in, fps);

  const changed = new Set<string>([clipId]);
  let warning: string | null = null;
  const durationDelta = snapV2TimelineToFrame(edited.duration - clip.duration, fps);
  if (options.ripple && !nearlyEqual(durationDelta, 0)) {
    warning = shiftLaterVideoClips(next, timeline, originalEnd, durationDelta, new Set([clipId]), changed, fps);
  }
  return finishMutation(timeline, next, orderedClipIds(timeline, changed), null, warning);
}

export function splitShotClip(
  timeline: V2FinalCompositionTimeline,
  clipId: string,
  splitTime: number,
  options: ShotTimelineEditOptions,
): ShotTimelineMutation {
  const setup = editableVideoClip(timeline, clipId, options);
  if (typeof setup === "string") return unchanged(timeline, setup);
  if (!Number.isFinite(splitTime)) return unchanged(timeline, "Split time is invalid.");

  const clip = setup.clip;
  const frame = 1 / options.fps;
  const splitAt = snapV2TimelineToFrame(splitTime, options.fps);
  const clipEnd = clip.start_time + clip.duration;
  if (splitAt - clip.start_time <= frame + EPSILON || clipEnd - splitAt <= frame + EPSILON) {
    return unchanged(timeline, "Split must be more than one frame from either clip boundary.");
  }

  const leftDuration = splitAt - clip.start_time;
  const rightDuration = clip.duration - leftDuration;
  const trimIn = clip.trim_in;
  const trimOut = clip.trim_out ?? trimIn + clip.duration;
  const splitTrim = trimIn + leftDuration;
  const newClipId = uniqueSplitId(timeline, clipId, splitAt, options.fps);
  const first: V2FinalTimelineClip = {
    ...cloneV2TimelineClip(clip),
    duration: leftDuration,
    trim_out: splitTrim,
    audio: splitAudio(clip, leftDuration, true),
  };
  const second: V2FinalTimelineClip = {
    ...cloneV2TimelineClip(clip),
    clip_id: newClipId,
    start_time: splitAt,
    duration: rightDuration,
    trim_in: splitTrim,
    trim_out: trimOut,
    audio: splitAudio(clip, rightDuration, false),
  };
  const next = cloneV2Timeline(timeline);
  next.clips = next.clips.flatMap((candidate) => candidate.clip_id === clipId ? [first, second] : [candidate]);
  return finishMutation(timeline, next, [clipId, newClipId], null, null);
}

export function deleteShotClips(
  timeline: V2FinalCompositionTimeline,
  clipIds: string[],
  options: ShotTimelineEditOptions,
): ShotTimelineMutation {
  const uniqueIds = [...new Set(clipIds)];
  if (!uniqueIds.length) return unchanged(timeline, "Select at least one shot to delete.");
  const optionWarning = validateOptions(options);
  if (optionWarning) return unchanged(timeline, optionWarning);
  const preflightWarning = canonicalPreflightWarning(timeline);
  if (preflightWarning) return unchanged(timeline, preflightWarning);

  const selected: V2FinalTimelineClip[] = [];
  for (const clipId of uniqueIds) {
    const clip = findClip(timeline, clipId);
    if (!clip) return unchanged(timeline, `Shot clip ${clipId} does not exist.`);
    if (clip.clip_type !== "video") return unchanged(timeline, "Only video shot clips can be deleted by this command.");
    const track = findTrack(timeline, clip.track_id);
    if (!track) return unchanged(timeline, `Shot clip ${clipId} references a missing track.`);
    if (isTrackLocked(track)) return unchanged(timeline, `Shot lane ${displayTrackName(track)} is locked.`);
    selected.push(clip);
  }

  const selectedIds = new Set(uniqueIds);
  const next = cloneV2Timeline(timeline);
  next.clips = next.clips.filter((clip) => !selectedIds.has(clip.clip_id));
  const changed = new Set(uniqueIds);
  let warning: string | null = null;
  if (options.ripple) {
    const intervals = mergeIntervals(selected.map((clip) => ({
      start: clip.start_time,
      end: clip.start_time + clip.duration,
    })));
    let skippedLocked = false;
    for (const candidate of next.clips) {
      if (candidate.clip_type !== "video") continue;
      const original = findClip(timeline, candidate.clip_id)!;
      const shift = intervals
        .filter((interval) => original.start_time >= interval.end - EPSILON)
        .reduce((total, interval) => total + interval.end - interval.start, 0);
      if (nearlyEqual(shift, 0)) continue;
      const track = findTrack(next, candidate.track_id)!;
      if (isTrackLocked(track)) {
        skippedLocked = true;
        continue;
      }
      candidate.start_time = snapV2TimelineToFrame(candidate.start_time - shift, options.fps);
      changed.add(candidate.clip_id);
    }
    if (skippedLocked) warning = "Locked Shot lanes were not shifted by Ripple delete.";
  }
  return finishMutation(timeline, next, orderedClipIds(timeline, changed), null, warning);
}

export function reorderShotLane(
  timeline: V2FinalCompositionTimeline,
  trackId: string,
  targetIndex: number,
): ShotTimelineMutation {
  const preflightWarning = canonicalPreflightWarning(timeline);
  if (preflightWarning) return unchanged(timeline, preflightWarning);
  const track = findTrack(timeline, trackId);
  if (!track || track.track_type !== "video") return unchanged(timeline, "Shot lane does not exist.");
  if (isTrackLocked(track)) return unchanged(timeline, `Shot lane ${displayTrackName(track)} is locked.`);
  const videoTracks = canonicalTrackOrder(timeline.tracks.filter((candidate) => candidate.track_type === "video"));
  if (!Number.isInteger(targetIndex) || targetIndex < 0 || targetIndex >= videoTracks.length) {
    return unchanged(timeline, "Shot lane position is invalid.");
  }
  const sourceIndex = videoTracks.findIndex((candidate) => candidate.track_id === trackId);
  if (sourceIndex === targetIndex) return { timeline, changedClipIds: [], snapTarget: null, warning: null };

  const next = cloneV2Timeline(timeline);
  const nextTracks = new Map(next.tracks.map((candidate) => [candidate.track_id, candidate]));
  const reordered = videoTracks.map((candidate) => nextTracks.get(candidate.track_id)!);
  const videoOrders = videoTracks.map((candidate) => candidate.order);
  const [moved] = reordered.splice(sourceIndex, 1);
  reordered.splice(targetIndex, 0, moved);
  reordered.forEach((candidate, index) => {
    candidate.order = videoOrders[index];
  });
  next.tracks = canonicalTrackOrder(next.tracks);
  return finishMutation(timeline, next, [], null, null);
}

export function shotTimelineDuration(timeline: V2FinalCompositionTimeline) {
  return v2TimelineDuration(timeline);
}

export function validateShotTimeline(timeline: V2FinalCompositionTimeline): ShotTimelineValidation {
  const warnings: string[] = [];
  if (!isNonEmptyString(timeline.timeline_id)) warnings.push("Timeline timeline_id must be non-empty.");
  validateNumber(warnings, timeline.version, "Timeline version", { integer: true, min: 1 });
  validateNumber(warnings, timeline.duration_seconds, "Timeline duration_seconds", { min: 0 });
  if (!isNonEmptyString(timeline.aspect_ratio)) warnings.push("Timeline aspect_ratio must be non-empty.");
  if (!isRecord(timeline.resolution)) {
    warnings.push("Timeline resolution must be an object.");
  } else if (!Object.values(timeline.resolution).every(isFiniteInteger)) {
    warnings.push("Timeline resolution values must be finite integers.");
  }
  validateNumber(warnings, timeline.fps, "Timeline fps", { integer: true, min: 1, max: 120 });
  if (!isRecord(timeline.metadata)) warnings.push("Timeline metadata must be an object.");

  const timelineTracks = Array.isArray(timeline.tracks) ? timeline.tracks : [];
  const timelineClips = Array.isArray(timeline.clips) ? timeline.clips : [];
  if (!Array.isArray(timeline.tracks)) warnings.push("Timeline tracks must be an array.");
  if (!Array.isArray(timeline.clips)) warnings.push("Timeline clips must be an array.");
  const trackIds = new Set<string>();
  const trackOrders = new Set<number>();
  const tracks = new Map<string, V2FinalTimelineTrack>();
  for (const track of timelineTracks) {
    if (!isNonEmptyString(track.track_id) || trackIds.has(track.track_id)) {
      warnings.push("Timeline track ids must be unique and non-empty.");
    }
    if (isNonEmptyString(track.track_id)) trackIds.add(track.track_id);
    if (!isOneOf(track.track_type, TRACK_TYPES)) warnings.push(`Track ${track.track_id} has an invalid track_type.`);
    if (!Number.isInteger(track.order) || track.order < 1 || trackOrders.has(track.order)) {
      warnings.push("Timeline track order values must be unique integers greater than or equal to 1.");
    }
    if (Number.isInteger(track.order)) trackOrders.add(track.order);
    if (typeof track.enabled !== "boolean") warnings.push(`Track ${track.track_id} enabled must be boolean.`);
    if (!isRecord(track.metadata)) warnings.push(`Track ${track.track_id} metadata must be an object.`);
    if (isNonEmptyString(track.track_id) && !tracks.has(track.track_id)) tracks.set(track.track_id, track);
  }

  const clipIds = new Set<string>();
  for (const clip of timelineClips) {
    if (!isNonEmptyString(clip.clip_id) || clipIds.has(clip.clip_id)) {
      warnings.push("Timeline clip ids must be unique and non-empty.");
    }
    if (isNonEmptyString(clip.clip_id)) clipIds.add(clip.clip_id);
    if (!isNonEmptyString(clip.track_id)) warnings.push(`Clip ${clip.clip_id} track_id must be non-empty.`);
    if (!isOneOf(clip.clip_type, TRACK_TYPES)) warnings.push(`Clip ${clip.clip_id} has an invalid clip_type.`);
    const track = tracks.get(clip.track_id);
    if (!track) {
      warnings.push(`Clip ${clip.clip_id} references a missing track.`);
    } else if (clip.clip_type !== track.track_type) {
      warnings.push(`Clip ${clip.clip_id} type must match its track type.`);
    }

    validateNumber(warnings, clip.start_time, `Clip ${clip.clip_id} start_time`, { min: 0 });
    validateNumber(warnings, clip.duration, `Clip ${clip.clip_id} duration`, { exclusiveMin: 0 });
    validateNumber(warnings, clip.trim_in, `Clip ${clip.clip_id} trim_in`, { min: 0 });
    if (clip.trim_out !== null) {
      validateNumber(warnings, clip.trim_out, `Clip ${clip.clip_id} trim_out`, { exclusiveMin: 0 });
      if (isFiniteNumber(clip.trim_in) && isFiniteNumber(clip.trim_out) && clip.trim_out <= clip.trim_in) {
        warnings.push(`Clip ${clip.clip_id} trim_out must be greater than trim_in.`);
      }
    }
    validateNumber(warnings, clip.volume, `Clip ${clip.clip_id} volume`, { min: 0 });
    if (typeof clip.muted !== "boolean") warnings.push(`Clip ${clip.clip_id} muted must be boolean.`);
    if (typeof clip.enabled !== "boolean") warnings.push(`Clip ${clip.clip_id} enabled must be boolean.`);
    if (!isRecord(clip.metadata)) warnings.push(`Clip ${clip.clip_id} metadata must be an object.`);

    if (isOneOf(clip.clip_type, ["video", "audio", "image"] as const)
      && (!isNonEmptyString(clip.source_asset_id) || !isNonEmptyString(clip.source_version_id))) {
      warnings.push(`Clip ${clip.clip_id} is missing its media source pin.`);
    }
    if (clip.clip_type === "subtitle" && clip.enabled && !isNonEmptyString(clip.text)) {
      warnings.push(`Clip ${clip.clip_id} enabled subtitle text must be non-empty.`);
    }
    if (clip.clip_type === "video" || clip.clip_type === "audio") {
      if (clip.trim_out === null
        || !isFiniteNumber(clip.duration)
        || !isFiniteNumber(clip.trim_in)
        || !isFiniteNumber(clip.trim_out)
        || !nearlyEqual(clip.duration, clip.trim_out - clip.trim_in, 0.01)) {
        warnings.push(`Clip ${clip.clip_id} duration must equal trim_out - trim_in.`);
      }
    }

    const transform = requiredRecord(warnings, clip.transform, `Clip ${clip.clip_id} transform`);
    validateNumber(warnings, transform.x, `Clip ${clip.clip_id} transform.x`, { min: -1, max: 1 });
    validateNumber(warnings, transform.y, `Clip ${clip.clip_id} transform.y`, { min: -1, max: 1 });
    validateNumber(warnings, transform.scale_x, `Clip ${clip.clip_id} transform.scale_x`, { exclusiveMin: 0, max: 4 });
    validateNumber(warnings, transform.scale_y, `Clip ${clip.clip_id} transform.scale_y`, { exclusiveMin: 0, max: 4 });
    validateNumber(warnings, transform.rotation_degrees, `Clip ${clip.clip_id} transform.rotation_degrees`, { min: -360, max: 360 });
    validateNumber(warnings, transform.opacity, `Clip ${clip.clip_id} transform.opacity`, { min: 0, max: 1 });
    if (!isOneOf(transform.fit, ["cover", "contain"] as const)) {
      warnings.push(`Clip ${clip.clip_id} transform.fit is invalid.`);
    }

    const audio = requiredRecord(warnings, clip.audio, `Clip ${clip.clip_id} audio`);
    validateNumber(warnings, audio.volume, `Clip ${clip.clip_id} audio.volume`, { min: 0, max: 4 });
    if (typeof audio.muted !== "boolean") warnings.push(`Clip ${clip.clip_id} audio.muted must be boolean.`);
    validateNumber(warnings, audio.fade_in_seconds, `Clip ${clip.clip_id} audio.fade_in_seconds`, { min: 0 });
    validateNumber(warnings, audio.fade_out_seconds, `Clip ${clip.clip_id} audio.fade_out_seconds`, { min: 0 });
    if (isFiniteNumber(audio.fade_in_seconds)
      && isFiniteNumber(audio.fade_out_seconds)
      && isFiniteNumber(clip.duration)
      && audio.fade_in_seconds + audio.fade_out_seconds > clip.duration + 0.01) {
      warnings.push(`Clip ${clip.clip_id} audio fades cannot exceed clip duration.`);
    }

    const color = requiredRecord(warnings, clip.color, `Clip ${clip.clip_id} color`);
    if (!isOneOf(color.preset_id, COLOR_PRESETS)) warnings.push(`Clip ${clip.clip_id} color.preset_id is invalid.`);
    validateNumber(warnings, color.brightness, `Clip ${clip.clip_id} color.brightness`, { min: -1, max: 1 });
    validateNumber(warnings, color.contrast, `Clip ${clip.clip_id} color.contrast`, { min: 0, max: 3 });
    validateNumber(warnings, color.saturation, `Clip ${clip.clip_id} color.saturation`, { min: 0, max: 3 });
    validateNumber(warnings, color.exposure, `Clip ${clip.clip_id} color.exposure`, { min: -4, max: 4 });
    validateNumber(warnings, color.temperature, `Clip ${clip.clip_id} color.temperature`, { min: -100, max: 100 });
    validateNumber(warnings, color.tint, `Clip ${clip.clip_id} color.tint`, { min: -100, max: 100 });
    validateNumber(warnings, color.hue, `Clip ${clip.clip_id} color.hue`, { min: -180, max: 180 });

    const subtitleStyle = requiredRecord(warnings, clip.subtitle_style, `Clip ${clip.clip_id} subtitle_style`);
    validateNumber(warnings, subtitleStyle.font_size, `Clip ${clip.clip_id} subtitle_style.font_size`, { integer: true, min: 12, max: 96 });
    if (typeof subtitleStyle.color !== "string" || !/^#[0-9A-Fa-f]{6}$/.test(subtitleStyle.color)) {
      warnings.push(`Clip ${clip.clip_id} subtitle_style.color must be #RRGGBB.`);
    }
    if (!isOneOf(subtitleStyle.position, SUBTITLE_POSITIONS)) {
      warnings.push(`Clip ${clip.clip_id} subtitle_style.position is invalid.`);
    }
  }

  for (const track of timelineTracks) {
    if (track.track_type === "audio" || track.enabled !== true) continue;
    const intervals = timelineClips
      .filter((clip) => clip.track_id === track.track_id
        && clip.enabled === true
        && isFiniteNumber(clip.start_time)
        && isFiniteNumber(clip.duration))
      .map((clip) => ({ id: clip.clip_id, start: clip.start_time, end: clip.start_time + clip.duration }))
      .sort((left, right) => left.start - right.start || left.id.localeCompare(right.id));
    for (let index = 1; index < intervals.length; index += 1) {
      if (intervals[index].start < intervals[index - 1].end - 0.01) {
        warnings.push(`Enabled non-audio clips overlap on track ${track.track_id}.`);
      }
    }
  }

  const computedDuration = Array.isArray(timeline.tracks) && Array.isArray(timeline.clips)
    ? shotTimelineDuration(timeline)
    : Number.NaN;
  if (!isFiniteNumber(timeline.duration_seconds)
    || !isFiniteNumber(computedDuration)
    || !nearlyEqual(timeline.duration_seconds, computedDuration, 0.01)) {
    warnings.push("Timeline duration_seconds must match enabled clip duration.");
  }
  return { valid: warnings.length === 0, warnings };
}

function editableVideoClip(
  timeline: V2FinalCompositionTimeline,
  clipId: string,
  options: ShotTimelineEditOptions,
): { clip: V2FinalTimelineClip; track: V2FinalTimelineTrack } | string {
  const optionWarning = validateOptions(options);
  if (optionWarning) return optionWarning;
  const preflightWarning = canonicalPreflightWarning(timeline);
  if (preflightWarning) return preflightWarning;
  const clip = findClip(timeline, clipId);
  if (!clip) return `Shot clip ${clipId} does not exist.`;
  if (clip.clip_type !== "video") return "Only video shot clips can be edited by this command.";
  const track = findTrack(timeline, clip.track_id);
  if (!track) return `Shot clip ${clipId} references a missing track.`;
  if (track.track_type !== "video") return `Shot clip ${clipId} does not belong to a video track.`;
  if (isTrackLocked(track)) return `Shot lane ${displayTrackName(track)} is locked.`;
  return { clip, track };
}

function validateOptions(options: ShotTimelineEditOptions) {
  if (!Number.isInteger(options.fps) || options.fps < 1 || options.fps > 120) return "Timeline fps must be an integer from 1 to 120.";
  if (options.snap && (!Number.isFinite(options.snap.thresholdSeconds) || options.snap.thresholdSeconds < 0)) {
    return "Snap threshold is invalid.";
  }
  return null;
}

function snapMoveStart(
  timeline: V2FinalCompositionTimeline,
  clip: V2FinalTimelineClip,
  requestedStart: number,
  options: ShotTimelineEditOptions,
): { startTime: number; target: ShotTimelineSnapTarget | null } {
  const frameStart = snapV2TimelineToFrame(requestedStart, options.fps);
  if (!options.snap?.enabled) return { startTime: frameStart, target: null };

  const candidates: Array<{ startTime: number; target: ShotTimelineSnapTarget }> = [
    { startTime: 0, target: { type: "zero", time: 0 } },
  ];
  if (Number.isFinite(options.snap.playhead)) {
    candidates.push({
      startTime: options.snap.playhead,
      target: { type: "playhead", time: options.snap.playhead },
    });
  }
  for (const candidate of timeline.clips) {
    if (candidate.clip_id === clip.clip_id || !candidate.enabled) continue;
    const start = candidate.start_time;
    const end = candidate.start_time + candidate.duration;
    candidates.push(
      { startTime: start, target: { type: "clip-start", time: start, clipId: candidate.clip_id } },
      { startTime: end, target: { type: "clip-end", time: end, clipId: candidate.clip_id } },
      { startTime: start - clip.duration, target: { type: "clip-start", time: start, clipId: candidate.clip_id } },
      { startTime: end - clip.duration, target: { type: "clip-end", time: end, clipId: candidate.clip_id } },
    );
  }
  const closest = candidates
    .map((candidate, index) => ({ ...candidate, index, distance: Math.abs(candidate.startTime - requestedStart) }))
    .filter((candidate) => candidate.startTime >= 0 && candidate.distance <= options.snap!.thresholdSeconds + EPSILON)
    .sort((left, right) => left.distance - right.distance || left.index - right.index)[0];
  if (!closest) return { startTime: frameStart, target: null };
  return {
    startTime: snapV2TimelineToFrame(closest.startTime, options.fps),
    target: { ...closest.target, time: snapV2TimelineToFrame(closest.target.time, options.fps) },
  };
}

function shiftLaterVideoClips(
  next: V2FinalCompositionTimeline,
  original: V2FinalCompositionTimeline,
  editPoint: number,
  delta: number,
  excluded: Set<string>,
  changed: Set<string>,
  fps: number,
) {
  let skippedLocked = false;
  for (const candidate of next.clips) {
    if (candidate.clip_type !== "video" || excluded.has(candidate.clip_id)) continue;
    const originalClip = findClip(original, candidate.clip_id);
    if (!originalClip) return `Timeline is invalid: clip ${candidate.clip_id} is missing from the canonical input.`;
    if (originalClip.start_time < editPoint - EPSILON) continue;
    const track = findTrack(next, candidate.track_id);
    if (!track) return `Timeline is invalid: clip ${candidate.clip_id} references a missing track.`;
    if (isTrackLocked(track)) {
      skippedLocked = true;
      continue;
    }
    candidate.start_time = snapV2TimelineToFrame(candidate.start_time + delta, fps);
    changed.add(candidate.clip_id);
  }
  return skippedLocked ? "Locked Shot lanes were not shifted by Ripple edit." : null;
}

function finishMutation(
  original: V2FinalCompositionTimeline,
  candidate: V2FinalCompositionTimeline,
  changedClipIds: string[],
  snapTarget: ShotTimelineSnapTarget | null,
  warning: string | null,
): ShotTimelineMutation {
  const next = withV2TimelineDuration(candidate);
  const validation = validateShotTimeline(next);
  if (!validation.valid) return unchanged(original, validation.warnings.join(" "));
  return { timeline: next, changedClipIds, snapTarget, warning };
}

function unchanged(timeline: V2FinalCompositionTimeline, warning: string): ShotTimelineMutation {
  return { timeline, changedClipIds: [], snapTarget: null, warning };
}

function orderedClipIds(timeline: V2FinalCompositionTimeline, ids: Set<string>) {
  const ordered = timeline.clips.filter((clip) => ids.has(clip.clip_id)).map((clip) => clip.clip_id);
  for (const id of ids) if (!ordered.includes(id)) ordered.push(id);
  return ordered;
}

function mergeIntervals(intervals: Array<{ start: number; end: number }>) {
  const sorted = [...intervals].sort((left, right) => left.start - right.start || left.end - right.end);
  const merged: Array<{ start: number; end: number }> = [];
  for (const interval of sorted) {
    const previous = merged.at(-1);
    if (!previous || interval.start > previous.end + EPSILON) {
      merged.push({ ...interval });
    } else {
      previous.end = Math.max(previous.end, interval.end);
    }
  }
  return merged;
}

function uniqueSplitId(timeline: V2FinalCompositionTimeline, clipId: string, splitAt: number, fps: number) {
  const base = `${clipId}-split-${Math.round(splitAt * fps)}`;
  const existing = new Set(timeline.clips.map((clip) => clip.clip_id));
  if (!existing.has(base)) return base;
  let suffix = 2;
  while (existing.has(`${base}-${suffix}`)) suffix += 1;
  return `${base}-${suffix}`;
}

function splitAudio(clip: V2FinalTimelineClip, duration: number, first: boolean) {
  return {
    ...clip.audio,
    fade_in_seconds: first ? Math.min(clip.audio.fade_in_seconds, duration) : 0,
    fade_out_seconds: first ? 0 : Math.min(clip.audio.fade_out_seconds, duration),
  };
}

function knownSourceDuration(clip: V2FinalTimelineClip): number | null {
  const editor = recordValue(clip.metadata.editor);
  const candidates = [
    clip.metadata.source_duration_seconds,
    clip.metadata.sourceDurationSeconds,
    editor.source_duration_seconds,
    editor.sourceDurationSeconds,
  ];
  const duration = candidates.find((value): value is number => typeof value === "number" && Number.isFinite(value) && value > 0);
  return duration ?? null;
}

function nonExpandingFrameBound(value: number, fps: number) {
  return Math.floor((value + EPSILON) * fps) / fps;
}

function canonicalPreflightWarning(timeline: V2FinalCompositionTimeline) {
  const validation = validateShotTimeline(timeline);
  return validation.valid ? null : `Timeline is invalid: ${validation.warnings.join(" ")}`;
}

function canonicalTrackOrder(tracks: V2FinalTimelineTrack[]) {
  return [...tracks].sort((left, right) => right.order - left.order || left.track_id.localeCompare(right.track_id));
}

function uniqueTrackId(base: string, reserved: Set<string>) {
  if (!reserved.has(base)) return base;
  let suffix = 2;
  while (reserved.has(`${base}-${suffix}`)) suffix += 1;
  return `${base}-${suffix}`;
}

function isTrackLocked(track: V2FinalTimelineTrack) {
  return editorMetadata(track).locked === true;
}

function displayTrackName(track: V2FinalTimelineTrack) {
  const name = editorMetadata(track).name;
  return typeof name === "string" && name ? name : track.track_id;
}

function editorMetadata(track: V2FinalTimelineTrack) {
  return recordValue(track.metadata.editor);
}

function recordValue(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

type NumberConstraints = {
  integer?: boolean;
  min?: number;
  exclusiveMin?: number;
  max?: number;
};

function validateNumber(
  warnings: string[],
  value: unknown,
  label: string,
  constraints: NumberConstraints,
) {
  const valid = isFiniteNumber(value)
    && (!constraints.integer || Number.isInteger(value))
    && (constraints.min === undefined || value >= constraints.min)
    && (constraints.exclusiveMin === undefined || value > constraints.exclusiveMin)
    && (constraints.max === undefined || value <= constraints.max);
  if (!valid) warnings.push(`${label} is invalid.`);
}

function requiredRecord(warnings: string[], value: unknown, label: string) {
  if (isRecord(value)) return value;
  warnings.push(`${label} must be an object.`);
  return {};
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isFiniteInteger(value: unknown): value is number {
  return isFiniteNumber(value) && Number.isInteger(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isOneOf<T extends string>(value: unknown, values: readonly T[]): value is T {
  return typeof value === "string" && values.includes(value as T);
}

function cloneRecord(value: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, cloneUnknown(item)]));
}

function cloneUnknown(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(cloneUnknown);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, cloneUnknown(item)]));
  return value;
}

function findClip(timeline: V2FinalCompositionTimeline, clipId: string) {
  return timeline.clips.find((clip) => clip.clip_id === clipId);
}

function findTrack(timeline: V2FinalCompositionTimeline, trackId: string) {
  return timeline.tracks.find((track) => track.track_id === trackId);
}

function nearlyEqual(left: number, right: number, tolerance = EPSILON) {
  return Math.abs(left - right) <= tolerance;
}
