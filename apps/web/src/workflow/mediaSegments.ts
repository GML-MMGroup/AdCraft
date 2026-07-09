import type { MediaStatus, NodeRunResult, UploadedAsset, WorkflowNode } from "../types";
import { dedupeAssets } from "./assets.ts";

export const STORYBOARD_VIDEO_NODE_ID = "storyboard-video-generation";

const ACTIVE_MEDIA_STATUSES = new Set([
  "pending",
  "queued",
  "submitted",
  "running",
  "processing",
  "in_progress",
  "waiting",
  "waiting_for_segments",
  "waiting_for_remote_url",
  "downloading",
]);

const NOT_STARTED_MEDIA_STATUSES = new Set([
  "not_started",
  "idle",
  "draft",
  "planned",
  "none",
]);

const READY_MEDIA_STATUSES = new Set([
  "ready",
  "completed",
  "complete",
  "success",
  "succeeded",
  "done",
  "finished",
]);

const FAILED_MEDIA_STATUSES = new Set([
  "failed",
  "failure",
  "error",
  "errored",
  "cancelled",
  "canceled",
  "timeout",
  "timed_out",
]);

export type StoryboardMediaProgress = {
  ready: boolean | null;
  readyCount: number | null;
  totalCount: number | null;
};

export type StoryboardVideoReadiness = {
  ready: boolean;
  pending: boolean;
  reason: string | null;
  assets: UploadedAsset[];
  segments: Array<Record<string, unknown>>;
  progress: StoryboardMediaProgress;
};

export function applyStoryboardMediaStatusToWorkflowNodes(nodes: WorkflowNode[], mediaStatus: MediaStatus | null): WorkflowNode[] {
  if (!hasStoryboardMediaStatus(mediaStatus)) return nodes;
  const status = storyboardVideoStatusFromMediaStatus(mediaStatus);
  const segmentAssets = storyboardSegmentAssetsFromMediaStatus(mediaStatus);
  const rawStatus = storyboardRawMediaStatus(mediaStatus);
  const failureReason = storyboardMediaFailureReason(mediaStatus);

  return nodes.map((node) => {
    if (!isStoryboardVideoNode(node)) return node;
    const outputAssets = dedupeAssets([...segmentAssets, ...(node.output_assets ?? [])]);
    return {
      ...node,
      ...(status ? { status } : {}),
      output_assets: outputAssets,
      output: {
        ...(node.output ?? {}),
        segments: mediaStatus?.segments ?? [],
        media_status: rawStatus,
        all_segments_ready: allStoryboardSegmentsReady(mediaStatus),
      },
      stale: status === "completed" ? false : node.stale,
      stale_reason: status === "failed" ? failureReason : status === "completed" ? null : node.stale_reason,
    };
  });
}

export function storyboardSegmentAssetsFromMediaStatus(mediaStatus: MediaStatus | null): UploadedAsset[] {
  if (!Array.isArray(mediaStatus?.segments)) return [];
  return dedupeAssets(
    mediaStatus.segments
      .map((segment, index) => uploadedAssetFromStoryboardSegment(segment, index))
      .filter((asset): asset is UploadedAsset => Boolean(asset)),
  );
}

export function storyboardMediaProgressFromStatus(mediaStatus: MediaStatus | null): StoryboardMediaProgress {
  const segments = storyboardSegments(mediaStatus);
  const readyCount = numberValue(mediaStatus?.ready_segment_count) ?? numberValue(mediaStatus?.ready_segments) ?? countReadySegments(segments);
  const totalCount = numberValue(mediaStatus?.total_segment_count) ?? numberValue(mediaStatus?.total_segments) ?? (segments.length ? segments.length : null);
  const explicitReady =
    booleanValue(mediaStatus?.segments_ready) ??
    booleanValue(mediaStatus?.all_segments_ready) ??
    booleanValue(mediaStatus?.all_ready);
  const derivedReady = totalCount !== null && totalCount > 0 && readyCount !== null && readyCount >= totalCount;
  return {
    ready: explicitReady ?? (derivedReady ? true : null),
    readyCount,
    totalCount,
  };
}

export function storyboardSegmentsReadyForFinalComposition(mediaStatus: MediaStatus | null): boolean {
  const progress = storyboardMediaProgressFromStatus(mediaStatus);
  const explicitReady =
    booleanValue(mediaStatus?.segments_ready) ??
    booleanValue(mediaStatus?.all_segments_ready) ??
    booleanValue(mediaStatus?.all_ready);
  const countReady = progress.readyCount !== null && progress.totalCount !== null && progress.totalCount > 0 && progress.readyCount >= progress.totalCount;
  return explicitReady === true || countReady;
}

export function storyboardVideoReadinessFromSources({
  mediaStatus,
  nodes = [],
  nodeRuns = [],
}: {
  mediaStatus?: MediaStatus | null;
  nodes?: WorkflowNode[];
  nodeRuns?: NodeRunResult[];
}): StoryboardVideoReadiness {
  const latestMediaStatus = mediaStatus ?? null;
  const storyboardNode = nodes.find((node) => isStoryboardVideoNode(node));
  const storyboardRun = nodeRuns.find((run) => isStoryboardVideoNode({ id: run.node_id ?? run.node_type ?? "", node_type: run.node_type }));
  const nodeOutput = recordValue(storyboardNode?.output);
  const runOutput = recordValue(storyboardRun?.output);
  const mediaSegments = storyboardSegments(latestMediaStatus);
  const nodeSegments = recordSegments(nodeOutput?.segments);
  const runSegments = recordSegments(runOutput?.segments);
  const segments = firstNonEmptyRecords(mediaSegments, nodeSegments, runSegments);
  const progress = storyboardMediaProgressFromStatus(latestMediaStatus);
  const explicitReady =
    progress.ready ??
    booleanValue(nodeOutput?.segments_ready) ??
    booleanValue(nodeOutput?.all_segments_ready) ??
    booleanValue(runOutput?.segments_ready) ??
    booleanValue(runOutput?.all_segments_ready);
  const assets = dedupeAssets([
    ...storyboardSegmentAssetsFromMediaStatus(latestMediaStatus),
    ...segmentAssetsFromRecords(nodeSegments),
    ...segmentAssetsFromRecords(runSegments),
    ...readyVideoAssets(storyboardNode?.output_assets),
    ...readyVideoAssets(storyboardRun?.output_assets),
  ]);
  const candidateSegments = segments.length
    ? segments
    : assets.map((asset) => ({
        asset_id: asset.asset_id,
        status: "ready",
        download_status: "ready",
        local_path: asset.local_path,
        public_url: asset.public_url,
        url: asset.url,
        remote_url: asset.remote_url,
      }));

  if (explicitReady === false) {
    return {
      ready: false,
      pending: true,
      reason: "Storyboard video segments are still generating.",
      assets,
      segments: candidateSegments,
      progress,
    };
  }
  if (hasFailedStoryboardSegments(candidateSegments) || storyboardVideoStatusFromMediaStatus(latestMediaStatus) === "failed") {
    return {
      ready: false,
      pending: false,
      reason: storyboardMediaFailureReason(latestMediaStatus),
      assets,
      segments: candidateSegments,
      progress,
    };
  }
  if (explicitReady === true && assets.length > 0) {
    return { ready: true, pending: false, reason: null, assets, segments: candidateSegments, progress };
  }
  if (candidateSegments.length > 0 && candidateSegments.every(storyboardSegmentReady) && assets.length > 0) {
    return { ready: true, pending: false, reason: null, assets, segments: candidateSegments, progress };
  }
  if (assets.length > 0 && candidateSegments.length === assets.length) {
    return { ready: true, pending: false, reason: null, assets, segments: candidateSegments, progress };
  }

  return {
    ready: false,
    pending: true,
    reason: "Storyboard video segments are still generating.",
    assets,
    segments: candidateSegments,
    progress,
  };
}

export function storyboardVideoStatusFromMediaStatus(mediaStatus: MediaStatus | null): WorkflowNode["status"] | null {
  if (!hasStoryboardMediaStatus(mediaStatus)) return null;
  const rawStatus = normalizedStatus(storyboardRawMediaStatus(mediaStatus));
  const progress = storyboardMediaProgressFromStatus(mediaStatus);
  const segmentStatuses = storyboardSegmentStatuses(mediaStatus);
  if (isFailedStoryboardStatus(rawStatus)) return "failed";
  if (segmentStatuses.some(isFailedStoryboardStatus)) return "failed";

  const assets = storyboardSegmentAssetsFromMediaStatus(mediaStatus);
  const hasPreviewableSegments = assets.length > 0;
  if (hasPreviewableSegments && (progress.ready === true || allStoryboardSegmentsReady(mediaStatus) || isReadyStoryboardStatus(rawStatus))) {
    return "completed";
  }

  if (isNotStartedStoryboardStatus(rawStatus)) return null;
  if (isActiveStoryboardStatus(rawStatus)) return "running";
  if (segmentStatuses.some(isActiveStoryboardStatus)) return "running";
  return null;
}

export function shouldPollStoryboardVideoMedia(value: unknown): boolean {
  const record = recordValue(value);
  const output = recordValue(record?.output);
  const mediaStatus = recordValue(record?.media_status) ?? record;
  const mediaNodeStatus = storyboardVideoStatusFromMediaStatus(mediaStatus as MediaStatus | null);
  if (mediaNodeStatus === "running") return true;
  if (mediaNodeStatus === "failed" || mediaNodeStatus === "completed") return false;

  const status = normalizedStatus(output?.status ?? record?.status);
  const compositionStatus = normalizedStatus(output?.composition_status ?? record?.composition_status);
  if (isActiveStoryboardStatus(status)) return true;
  if (isActiveStoryboardStatus(compositionStatus)) return true;
  if (Array.isArray(output?.segments) && output.segments.length > 0 && !segmentsAllPreviewable(output.segments)) {
    return output.segments
      .filter((segment): segment is Record<string, unknown> => Boolean(recordValue(segment)))
      .some((segment) => storyboardSegmentStatusesFromSegment(segment).some(isActiveStoryboardStatus));
  }
  return false;
}

export function isStoryboardVideoNode(node: Pick<WorkflowNode, "id" | "type" | "node_type">) {
  return (node.node_type ?? node.type ?? node.id) === STORYBOARD_VIDEO_NODE_ID || node.id === STORYBOARD_VIDEO_NODE_ID;
}

export function isNotStartedStoryboardStatus(status: unknown) {
  const normalized = normalizedStatus(status);
  return Boolean(normalized && NOT_STARTED_MEDIA_STATUSES.has(normalized));
}

export function isActiveStoryboardStatus(status: unknown) {
  const normalized = normalizedStatus(status);
  return Boolean(normalized && ACTIVE_MEDIA_STATUSES.has(normalized));
}

function isReadyStoryboardStatus(status: unknown) {
  const normalized = normalizedStatus(status);
  return Boolean(normalized && READY_MEDIA_STATUSES.has(normalized));
}

function isFailedStoryboardStatus(status: unknown) {
  const normalized = normalizedStatus(status);
  return Boolean(normalized && FAILED_MEDIA_STATUSES.has(normalized));
}

function hasStoryboardMediaStatus(mediaStatus: MediaStatus | null): mediaStatus is MediaStatus {
  return Boolean(
    mediaStatus &&
      (Array.isArray(mediaStatus.segments) ||
        stringValue(mediaStatus.storyboard_video_status) ||
        mediaStatus.segments_ready !== undefined ||
        mediaStatus.all_segments_ready !== undefined ||
        mediaStatus.all_ready !== undefined ||
        numberValue(mediaStatus.ready_segment_count) !== undefined ||
        numberValue(mediaStatus.total_segment_count) !== undefined ||
        numberValue(mediaStatus.total_segments)),
  );
}

function uploadedAssetFromStoryboardSegment(segment: Record<string, unknown>, index: number): UploadedAsset | null {
  if (!storyboardSegmentReady(segment)) return null;
  const path = firstString(
    segment.local_path,
    segment.public_url,
    segment.url,
    segment.remote_url,
    segment.path,
    segment.intended_local_path,
  );
  if (!path) return null;
  const order = numberValue(segment.order) ?? index + 1;
  const id = firstString(segment.asset_id, segment.id, segment.segment_id) ?? `storyboard-video-segment-${order}`;
  const filename = firstString(segment.filename, segment.name) ?? filenameFromPath(path) ?? `segment-${order}.mp4`;
  return {
    ...segment,
    asset_id: id,
    asset_type: "video",
    asset_role: "reference",
    filename,
    mime_type: firstString(segment.mime_type, segment.content_type) ?? "video/mp4",
    local_path: firstString(segment.local_path, segment.path, segment.intended_local_path, segment.public_url, segment.url, segment.remote_url) ?? path,
    url: firstString(segment.url, segment.public_url),
    remote_url: firstString(segment.remote_url),
    public_url: firstString(segment.public_url),
  } as UploadedAsset;
}

function storyboardSegments(mediaStatus: MediaStatus | null): Array<Record<string, unknown>> {
  return Array.isArray(mediaStatus?.segments) ? mediaStatus.segments : [];
}

function storyboardRawMediaStatus(mediaStatus: MediaStatus | null) {
  return firstString(mediaStatus?.storyboard_video_status, mediaStatus?.status);
}

function storyboardSegmentStatuses(mediaStatus: MediaStatus | null) {
  return storyboardSegments(mediaStatus).flatMap(storyboardSegmentStatusesFromSegment);
}

function storyboardSegmentStatusesFromSegment(segment: Record<string, unknown>) {
  return [
    normalizedStatus(segment.status),
    normalizedStatus(segment.download_status),
    normalizedStatus(segment.render_status),
  ].filter(Boolean) as string[];
}

function allStoryboardSegmentsReady(mediaStatus: MediaStatus | null) {
  const explicitReady =
    booleanValue(mediaStatus?.segments_ready) ??
    booleanValue(mediaStatus?.all_segments_ready) ??
    booleanValue(mediaStatus?.all_ready);
  if (explicitReady !== undefined) return explicitReady;
  const segments = storyboardSegments(mediaStatus);
  return segments.length > 0 && segmentsAllPreviewable(segments);
}

function segmentsAllPreviewable(segments: unknown[]) {
  return segments.length > 0 && segments.every((segment, index) => Boolean(recordValue(segment) && uploadedAssetFromStoryboardSegment(segment as Record<string, unknown>, index)));
}

function storyboardSegmentReady(segment: Record<string, unknown>) {
  const hasPath = Boolean(firstString(segment.local_path, segment.public_url, segment.url, segment.remote_url, segment.path, segment.intended_local_path));
  if (!hasPath) return false;
  const statuses = [normalizedStatus(segment.status), normalizedStatus(segment.download_status), normalizedStatus(segment.render_status)].filter(Boolean) as string[];
  if (statuses.some((status) => FAILED_MEDIA_STATUSES.has(status))) return false;
  if (statuses.some((status) => ACTIVE_MEDIA_STATUSES.has(status))) return false;
  const downloadStatus = normalizedStatus(segment.download_status);
  if (downloadStatus && !READY_MEDIA_STATUSES.has(downloadStatus) && downloadStatus !== "downloaded") return false;
  return true;
}

function hasFailedStoryboardSegments(segments: Array<Record<string, unknown>>) {
  return segments.some((segment) => {
    const statuses = [normalizedStatus(segment.status), normalizedStatus(segment.download_status), normalizedStatus(segment.render_status)].filter(Boolean) as string[];
    return statuses.some((status) => FAILED_MEDIA_STATUSES.has(status));
  });
}

function countReadySegments(segments: Array<Record<string, unknown>>) {
  if (!segments.length) return null;
  return segments.filter(storyboardSegmentReady).length;
}

function segmentAssetsFromRecords(segments: Array<Record<string, unknown>>) {
  return dedupeAssets(
    segments
      .map((segment, index) => uploadedAssetFromStoryboardSegment(segment, index))
      .filter((asset): asset is UploadedAsset => Boolean(asset)),
  );
}

function readyVideoAssets(assets: UploadedAsset[] | undefined) {
  return dedupeAssets(
    (assets ?? []).filter((asset) => {
      const type = stringValue(asset.asset_type)?.toLowerCase();
      const path = firstString(asset.local_path, asset.public_url, asset.url, asset.remote_url);
      return type === "video" && Boolean(path);
    }),
  );
}

function recordSegments(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(recordValue(item))) : [];
}

function firstNonEmptyRecords(...values: Array<Array<Record<string, unknown>>>) {
  return values.find((value) => value.length > 0) ?? [];
}

export function storyboardMediaFailureReason(mediaStatus: MediaStatus | null) {
  const statusMessage = firstString((mediaStatus as Record<string, unknown> | null)?.message, (mediaStatus as Record<string, unknown> | null)?.error);
  if (statusMessage) return statusMessage;
  for (const segment of storyboardSegments(mediaStatus)) {
    const reason = firstString(segment.error, segment.download_error, segment.fail_reason, segment.message);
    if (reason) return reason;
  }
  return "Storyboard video segment failed";
}

function normalizedStatus(value: unknown) {
  return stringValue(value)?.toLowerCase();
}

function recordValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    const text = stringValue(value);
    if (text) return text;
  }
  return undefined;
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function booleanValue(value: unknown) {
  return typeof value === "boolean" ? value : undefined;
}

function filenameFromPath(path: string) {
  const clean = path.split("?")[0]?.split("#")[0] ?? "";
  return clean.match(/([^/\\]+)$/)?.[1];
}
