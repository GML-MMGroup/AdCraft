import type { MediaStatus, NodeRunResult, WorkflowNode } from "../../../types.ts";
import { finalVideoAssetFromMediaStatus } from "../../../workflow/finalVideo.ts";
import type { SubtitleLine } from "../types.ts";

const LOCAL_WORKFLOW_ID = "local-workflow";

export function buildVideoTimeline(
  workflowId: string | undefined,
  settings: Record<string, unknown>,
  mediaStatus: MediaStatus | null,
  nodeRuns: NodeRunResult[],
  canvasNodes: WorkflowNode[],
) {
  const clips = collectVideoClips(mediaStatus, nodeRuns, canvasNodes);
  let cursor = 0;
  const videoClips = clips.map((clip, index) => {
    const duration = clip.duration || 10;
    const start = cursor;
    cursor += duration;
    return {
      asset_id: clip.assetId || `segment-${index + 1}`,
      source_path: clip.path,
      start_time: 0,
      end_time: duration,
      timeline_start: start,
      timeline_end: cursor,
      order: index + 1,
      volume: 1,
      muted: false,
    };
  });

  return {
    workflow_id: workflowId ?? LOCAL_WORKFLOW_ID,
    resolution: settings.resolution ?? "480p",
    aspect_ratio: settings.aspect_ratio ?? "16:9",
    fps: settings.fps ?? 30,
    tracks: [
      {
        type: "video",
        clips: videoClips,
      },
      {
        type: "subtitle",
        subtitles: buildSubtitleTrack(nodeRuns),
      },
    ],
    watermarks: [],
  };
}

function collectVideoClips(mediaStatus: MediaStatus | null, nodeRuns: NodeRunResult[], canvasNodes: WorkflowNode[]) {
  const clips: Array<{ assetId?: string; path: string; duration?: number }> = [];
  const seen = new Set<string>();

  function addClip(value: unknown, fallbackId?: string) {
    const record = value && typeof value === "object" ? (value as Record<string, unknown>) : null;
    if (!record) return;
    const path = findMediaPath(record);
    if (!path || seen.has(path)) return;
    const assetType = record.asset_type ?? record.type ?? record.media_type;
    if (assetType && typeof assetType === "string" && !assetType.toLowerCase().includes("video")) return;
    seen.add(path);
    clips.push({
      assetId: typeof record.asset_id === "string" ? record.asset_id : fallbackId,
      path,
      duration: typeof record.duration_seconds === "number" ? record.duration_seconds : undefined,
    });
  }

  for (const segment of mediaStatus?.segments ?? []) addClip(segment);
  addClip(finalVideoAssetFromMediaStatus(mediaStatus), "final-video");

  for (const run of nodeRuns) {
    for (const asset of run.output_assets ?? []) addClip(asset, asset.asset_id);
    addClip(run.output, run.node_id);
  }

  for (const node of canvasNodes) {
    for (const asset of node.output_assets ?? []) addClip(asset, asset.asset_id);
    addClip(node.content, node.id);
  }

  return clips;
}

function buildSubtitleTrack(nodeRuns: NodeRunResult[]) {
  const scriptRun = nodeRuns.find((run) => run.node_type === "script" || run.node_id === "script");
  const output = scriptRun?.output;
  const lines = Array.isArray(output?.subtitle_lines)
    ? output.subtitle_lines
    : Array.isArray(output?.subtitles)
      ? output.subtitles
      : [];

  return lines
    .map((line, index) => {
      if (typeof line === "string") {
        return {
          text: line,
          start_time: index * 3,
          end_time: index * 3 + 3,
          position: "bottom",
          font_size: 32,
          color: "#FFFFFF",
          alignment: "center",
        };
      }
      if (!line || typeof line !== "object") return null;
      const record = line as Record<string, unknown>;
      return {
        text: String(record.text ?? record.content ?? ""),
        start_time: Number(record.start_time ?? record.start ?? index * 3),
        end_time: Number(record.end_time ?? record.end ?? index * 3 + 3),
        position: String(record.position ?? "bottom"),
        font_size: Number(record.font_size ?? 32),
        color: String(record.color ?? "#FFFFFF"),
        alignment: String(record.alignment ?? "center"),
      };
    })
    .filter((line): line is SubtitleLine => Boolean(line?.text));
}

export function getTimelineClipCount(timeline: Record<string, unknown>) {
  const tracks = Array.isArray(timeline.tracks) ? timeline.tracks : [];
  return tracks.reduce((count, track) => {
    if (!track || typeof track !== "object") return count;
    const clips = (track as Record<string, unknown>).clips;
    return count + (Array.isArray(clips) ? clips.length : 0);
  }, 0);
}

export function findMediaPath(value: unknown): string {
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object") return "";
  const record = value as Record<string, unknown>;
  const path = record.public_url ?? record.remote_url ?? record.url ?? record.local_path ?? record.path;
  return typeof path === "string" ? path : "";
}
