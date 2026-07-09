import type { MediaStatus, UploadedAsset, WorkflowNode } from "../types";

const READY_FINAL_VIDEO_STATUSES = new Set(["ready", "completed", "complete", "success", "succeeded", "done", "finished"]);
const ACTIVE_FINAL_VIDEO_STATUSES = new Set(["pending", "queued", "submitted", "running", "processing", "in_progress", "waiting", "waiting_for_segments", "waiting_for_remote_url", "downloading"]);
const FAILED_FINAL_VIDEO_STATUSES = new Set(["failed", "failure", "error", "errored", "cancelled", "canceled", "timeout", "timed_out"]);

export type FinalVideoMediaState = {
  hasFinalVideo: boolean;
  status: WorkflowNode["status"] | null;
  asset: UploadedAsset | null;
  reason: string | null;
};

export function finalVideoAssetFromMediaStatus(mediaStatus: MediaStatus | null): UploadedAsset | null {
  return finalVideoStateFromMediaStatus(mediaStatus).asset;
}

export function finalVideoStateFromMediaStatus(mediaStatus: MediaStatus | null): FinalVideoMediaState {
  const finalVideo = finalVideoRecordFromMediaStatus(mediaStatus);
  if (!finalVideo) {
    return { hasFinalVideo: false, status: null, asset: null, reason: null };
  }

  const rawStatus = normalizedStatus(finalVideo.status) ?? normalizedStatus(mediaStatus?.final_composition_status) ?? normalizedStatus(topLevelFinalStatus(mediaStatus));
  const failureReason = finalVideoFailureReason(mediaStatus);
  if (isFailedFinalVideoStatus(rawStatus)) {
    return { hasFinalVideo: true, status: "failed", asset: null, reason: failureReason };
  }

  const path = finalVideoPlayablePath(finalVideo);
  if (isReadyFinalVideoStatus(rawStatus)) {
    if (!path) {
      return {
        hasFinalVideo: true,
        status: "running",
        asset: null,
        reason: "最终视频状态已 ready，但资源地址尚未返回。",
      };
    }
    return { hasFinalVideo: true, status: "completed", asset: uploadedFinalVideoAsset(finalVideo, path), reason: null };
  }

  if (isActiveFinalVideoStatus(rawStatus)) {
    return { hasFinalVideo: true, status: "running", asset: null, reason: "Final video is still being composed." };
  }

  return { hasFinalVideo: true, status: null, asset: null, reason: null };
}

export function applyFinalVideoMediaStatusToWorkflowNodes(nodes: WorkflowNode[], mediaStatus: MediaStatus | null): WorkflowNode[] {
  const state = finalVideoStateFromMediaStatus(mediaStatus);
  if (!state.hasFinalVideo) return nodes;

  return nodes.map((node) => {
    if (!isFinalCompositionNode(node)) return node;
    const outputAssets = state.asset ? [state.asset] : state.status === "failed" ? node.output_assets ?? [] : [];
    return {
      ...node,
      ...(state.status ? { status: state.status } : {}),
      output_assets: outputAssets,
      output: {
        ...(node.output ?? {}),
        final_video: mediaStatus?.final_video ?? null,
        media_status: mediaStatus?.status,
      },
      stale: state.status === "completed" ? false : node.stale,
      stale_reason: state.status === "completed" ? null : state.reason ?? node.stale_reason,
    };
  });
}

export function isFinalCompositionNode(node: Pick<WorkflowNode, "id" | "type" | "node_type"> | null | undefined, runType?: string) {
  const nodeType = runType ?? node?.node_type ?? node?.type ?? node?.id;
  return node?.id === "final-composition" || nodeType === "final-composition";
}

export function isReadyFinalVideoStatus(status: unknown) {
  const normalized = normalizedStatus(status);
  return Boolean(normalized && READY_FINAL_VIDEO_STATUSES.has(normalized));
}

export function isActiveFinalVideoStatus(status: unknown) {
  const normalized = normalizedStatus(status);
  return Boolean(normalized && ACTIVE_FINAL_VIDEO_STATUSES.has(normalized));
}

export function isFailedFinalVideoStatus(status: unknown) {
  const normalized = normalizedStatus(status);
  return Boolean(normalized && FAILED_FINAL_VIDEO_STATUSES.has(normalized));
}

function uploadedFinalVideoAsset(finalVideo: Record<string, unknown>, path: string): UploadedAsset {
  const id = firstString(finalVideo.asset_id, finalVideo.id) ?? "final-video";
  return {
    ...finalVideo,
    asset_id: id,
    asset_type: "video",
    asset_role: "reference",
    filename: firstString(finalVideo.filename, finalVideo.name) ?? filenameFromPath(path) ?? `${id}.mp4`,
    mime_type: firstString(finalVideo.mime_type, finalVideo.content_type) ?? "video/mp4",
    local_path: firstString(finalVideo.local_path) ?? path,
    url: firstString(finalVideo.url),
    remote_url: firstString(finalVideo.remote_url),
    public_url: firstString(finalVideo.public_url),
  } as UploadedAsset;
}

function finalVideoPlayablePath(finalVideo: Record<string, unknown>) {
  return firstString(finalVideo.public_url, finalVideo.local_path);
}

function finalVideoFailureReason(mediaStatus: MediaStatus | null) {
  const finalVideo = finalVideoRecordFromMediaStatus(mediaStatus);
  return (
    firstString(finalVideo?.error, finalVideo?.message, (mediaStatus as Record<string, unknown> | null)?.error, (mediaStatus as Record<string, unknown> | null)?.message) ??
    "Final video composition failed."
  );
}

function finalVideoRecordFromMediaStatus(mediaStatus: MediaStatus | null): Record<string, unknown> | undefined {
  const finalVideo = recordValue(mediaStatus?.final_video);
  if (finalVideo) return finalVideo;
  if (!hasTopLevelFinalVideoSignal(mediaStatus)) return undefined;
  return mediaStatus as Record<string, unknown>;
}

function hasTopLevelFinalVideoSignal(mediaStatus: MediaStatus | null) {
  const record = recordValue(mediaStatus);
  if (!record) return false;
  if (firstString(record.final_composition_status)) return true;
  if (firstString(record.public_url, record.local_path)) return true;
  if (firstString(record.error, record.message) && !firstString(record.storyboard_video_status)) return true;
  return Boolean(firstString(record.status) && !firstString(record.storyboard_video_status));
}

function topLevelFinalStatus(mediaStatus: MediaStatus | null) {
  return hasTopLevelFinalVideoSignal(mediaStatus) ? (mediaStatus as Record<string, unknown>).status : undefined;
}

function normalizedStatus(value: unknown) {
  return firstString(value)?.toLowerCase();
}

function recordValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return undefined;
}

function filenameFromPath(path: string) {
  const clean = path.split("?")[0]?.split("#")[0] ?? "";
  return clean.match(/([^/\\]+)$/)?.[1];
}
