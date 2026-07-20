import type { UploadedAsset } from "../types";
import {
  deleteHybridRecordSync,
  deleteHybridRecordsWhereSync,
  loadHybridRecordSync,
  saveHybridRecordSync,
} from "../storage/hybridStorage.ts";

type VideoPosterMime = "image/webp" | "image/jpeg";

export type VideoPosterRecord = {
  id: string;
  project_id: string;
  workflow_id: string;
  asset_key: string;
  asset_id?: string;
  source_url: string;
  source_local_path?: string;
  source_public_url?: string;
  node_run_id?: string;
  version_key?: string;
  poster_blob: Blob;
  poster_mime: VideoPosterMime;
  width: number;
  height: number;
  created_at: string;
  updated_at: string;
  last_accessed_at: string;
};

type BuildVideoPosterRecordOptions = {
  projectId: string;
  workflowId: string;
  asset: Partial<UploadedAsset>;
  sourceUrl: string;
  posterBlob: Blob;
  posterMime: VideoPosterMime;
  width: number;
  height: number;
  now?: string;
};

type EnsureVideoPosterOptions = {
  projectId?: string | null;
  workflowId?: string | null;
  asset?: Partial<UploadedAsset> | null;
  videoUrl: string;
};

const VIDEO_POSTER_FAILURE_COOLDOWN_MS = 5 * 60 * 1000;
const VIDEO_POSTER_MAX_CONCURRENCY = 2;
const failedPosterAttempts = new Map<string, number>();
const pendingPosterTasks = new Map<string, Promise<VideoPosterRecord | null>>();
const posterQueue: Array<() => void> = [];
let activePosterTasks = 0;

export function videoPosterAssetKey(workflowId: string, asset: Partial<UploadedAsset>) {
  return [
    workflowId || "local-workflow",
    stringValue(asset.asset_id) || "asset",
    firstString(asset.local_path, asset.public_url, asset.remote_url, asset.url) || stringValue(asset.filename) || "video",
    firstString(
      asset.node_run_id,
      stringValue(asset.version),
      asset.content_hash,
      asset.file_hash,
      asset.output_hash,
      asset.hash,
      asset.updated_at,
      asset.etag,
    ) || "unversioned",
  ]
    .map((part) => encodeURIComponent(part))
    .join("|");
}

export function videoNeedsLocalPoster(asset?: Partial<UploadedAsset> | null) {
  return Boolean(asset?.asset_type === "video" && !backendPosterPath(asset));
}

export function buildVideoPosterRecord({
  projectId,
  workflowId,
  asset,
  sourceUrl,
  posterBlob,
  posterMime,
  width,
  height,
  now = new Date().toISOString(),
}: BuildVideoPosterRecordOptions): VideoPosterRecord {
  const assetKey = videoPosterAssetKey(workflowId, asset);
  return {
    id: videoPosterRecordId(projectId, workflowId, assetKey),
    project_id: projectId,
    workflow_id: workflowId,
    asset_key: assetKey,
    asset_id: stringValue(asset.asset_id) || undefined,
    source_url: sourceUrl,
    source_local_path: stringValue(asset.local_path) || undefined,
    source_public_url: firstString(asset.public_url, asset.remote_url, asset.url) || undefined,
    node_run_id: stringValue(asset.node_run_id) || undefined,
    version_key: firstString(
      asset.node_run_id,
      stringValue(asset.version),
      asset.content_hash,
      asset.file_hash,
      asset.output_hash,
      asset.hash,
      asset.updated_at,
      asset.etag,
    ) || undefined,
    poster_blob: posterBlob,
    poster_mime: posterMime,
    width,
    height,
    created_at: now,
    updated_at: now,
    last_accessed_at: now,
  };
}

export function saveVideoPosterRecord(record: VideoPosterRecord) {
  saveHybridRecordSync("videoPosterCache", record.id, record);
  return record;
}

export function loadVideoPosterRecord(recordId: string) {
  const record = loadHybridRecordSync<VideoPosterRecord>("videoPosterCache", recordId);
  if (!isVideoPosterRecord(record)) return undefined;
  const touched = { ...record, last_accessed_at: new Date().toISOString() };
  saveVideoPosterRecord(touched);
  return touched;
}

export function loadVideoPosterRecordForAsset(projectId: string, workflowId: string, asset: Partial<UploadedAsset>) {
  return loadVideoPosterRecord(videoPosterRecordId(projectId, workflowId, videoPosterAssetKey(workflowId, asset)));
}

export function deleteVideoPosterRecord(recordId: string) {
  deleteHybridRecordSync("videoPosterCache", recordId);
}

export function deleteVideoPosterCacheForProject(projectId: string) {
  deleteHybridRecordsWhereSync("videoPosterCache", (value) => isVideoPosterRecord(value) && value.project_id === projectId);
}

export function deleteVideoPosterCacheForWorkflow(workflowId: string) {
  deleteHybridRecordsWhereSync("videoPosterCache", (value) => isVideoPosterRecord(value) && value.workflow_id === workflowId);
}

export function cleanupOrphanedVideoPosterCache(savedProjectIds: Iterable<string>, trashedProjectIds: Iterable<string>) {
  const liveProjectIds = new Set([...savedProjectIds, ...trashedProjectIds].filter(Boolean));
  deleteHybridRecordsWhereSync("videoPosterCache", (value) => isVideoPosterRecord(value) && !liveProjectIds.has(value.project_id));
}

export async function ensureVideoPoster(options: EnsureVideoPosterOptions) {
  const { asset, videoUrl } = options;
  if (!asset || !videoUrl || !videoNeedsLocalPoster(asset)) return null;
  const workflowId = options.workflowId || "local-workflow";
  const projectId = options.projectId || workflowId;
  const recordId = videoPosterRecordId(projectId, workflowId, videoPosterAssetKey(workflowId, asset));
  const cached = loadVideoPosterRecord(recordId);
  if (cached) return cached;
  if (recentlyFailed(recordId)) return null;
  const pendingTask = pendingPosterTasks.get(recordId);
  if (pendingTask) return pendingTask;

  const task = enqueuePosterTask(async () => {
    try {
      const poster = await generateVideoPoster(videoUrl);
      if (!poster) return null;
      return saveVideoPosterRecord(
        buildVideoPosterRecord({
          projectId,
          workflowId,
          asset,
          sourceUrl: videoUrl,
          posterBlob: poster.blob,
          posterMime: poster.mime,
          width: poster.width,
          height: poster.height,
        }),
      );
    } catch {
      failedPosterAttempts.set(recordId, Date.now());
      return null;
    } finally {
      pendingPosterTasks.delete(recordId);
    }
  });
  pendingPosterTasks.set(recordId, task);
  return task;
}

function videoPosterRecordId(projectId: string, workflowId: string, assetKey: string) {
  return [projectId || "local-project", workflowId || "local-workflow", assetKey].map((part) => encodeURIComponent(part)).join("|");
}

function enqueuePosterTask<T>(task: () => Promise<T>) {
  return new Promise<T>((resolve) => {
    const run = () => {
      activePosterTasks += 1;
      void task()
        .then(resolve)
        .finally(() => {
          activePosterTasks -= 1;
          posterQueue.shift()?.();
        });
    };
    if (activePosterTasks < VIDEO_POSTER_MAX_CONCURRENCY) {
      run();
      return;
    }
    posterQueue.push(run);
  });
}

async function generateVideoPoster(videoUrl: string) {
  if (typeof document === "undefined") return null;
  const video = document.createElement("video");
  video.preload = "metadata";
  video.muted = true;
  video.playsInline = true;
  if (shouldUseAnonymousCors(videoUrl)) video.crossOrigin = "anonymous";

  try {
    await loadVideoFrame(video, videoUrl);
    const width = video.videoWidth || 640;
    const height = video.videoHeight || 360;
    const scale = Math.min(1, 640 / width);
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const context = canvas.getContext("2d");
    if (!context) return null;
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const webp = await canvasToBlob(canvas, "image/webp", 0.78);
    if (webp) return { blob: webp, mime: "image/webp" as const, width: canvas.width, height: canvas.height };
    const jpeg = await canvasToBlob(canvas, "image/jpeg", 0.82);
    return jpeg ? { blob: jpeg, mime: "image/jpeg" as const, width: canvas.width, height: canvas.height } : null;
  } finally {
    video.removeAttribute("src");
    video.load();
  }
}

function loadVideoFrame(video: HTMLVideoElement, videoUrl: string) {
  return new Promise<void>((resolve, reject) => {
    let settled = false;
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      video.removeEventListener("loadedmetadata", handleMetadata);
      video.removeEventListener("loadeddata", handleLoadedData);
      video.removeEventListener("seeked", handleSeeked);
      video.removeEventListener("error", handleError);
      window.clearTimeout(timeoutId);
      callback();
    };
    const handleError = () => finish(() => reject(new Error("Video poster source failed to load.")));
    const handleLoadedData = () => {
      if (video.readyState >= 2 && (!Number.isFinite(video.duration) || video.duration <= 0)) finish(resolve);
    };
    const handleSeeked = () => finish(resolve);
    const handleMetadata = () => {
      const duration = Number.isFinite(video.duration) ? video.duration : 0;
      const targetTime = duration > 0 ? Math.min(0.5, duration * 0.1) : 0;
      if (!targetTime) {
        if (video.readyState >= 2) finish(resolve);
        return;
      }
      try {
        video.currentTime = targetTime;
      } catch {
        if (video.readyState >= 2) finish(resolve);
      }
    };
    const timeoutId = window.setTimeout(() => finish(() => reject(new Error("Video poster generation timed out."))), 15_000);
    video.addEventListener("loadedmetadata", handleMetadata);
    video.addEventListener("loadeddata", handleLoadedData);
    video.addEventListener("seeked", handleSeeked);
    video.addEventListener("error", handleError);
    video.src = videoUrl;
    video.load();
  });
}

function canvasToBlob(canvas: HTMLCanvasElement, type: VideoPosterMime, quality: number) {
  return new Promise<Blob | null>((resolve) => {
    try {
      canvas.toBlob(resolve, type, quality);
    } catch {
      resolve(null);
    }
  });
}

function shouldUseAnonymousCors(url: string) {
  if (!/^https?:\/\//i.test(url)) return false;
  if (typeof window === "undefined") return false;
  try {
    return new URL(url, window.location.href).origin !== window.location.origin;
  } catch {
    return true;
  }
}

function recentlyFailed(key: string) {
  const failedAt = failedPosterAttempts.get(key);
  return Boolean(failedAt && Date.now() - failedAt < VIDEO_POSTER_FAILURE_COOLDOWN_MS);
}

function backendPosterPath(asset?: Partial<UploadedAsset> | null) {
  return firstString(asset?.poster_path, asset?.poster_url, asset?.thumbnail_path, asset?.thumbnail_url, asset?.preview_path, asset?.preview_url);
}

function isVideoPosterRecord(value: unknown): value is VideoPosterRecord {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<VideoPosterRecord>;
  return (
    typeof record.id === "string" &&
    typeof record.project_id === "string" &&
    typeof record.workflow_id === "string" &&
    typeof record.asset_key === "string" &&
    typeof record.source_url === "string" &&
    typeof record.width === "number" &&
    typeof record.height === "number" &&
    record.poster_blob instanceof Blob &&
    (record.poster_mime === "image/webp" || record.poster_mime === "image/jpeg")
  );
}

function firstString(...values: Array<unknown>) {
  for (const value of values) {
    const text = stringValue(value);
    if (text) return text;
  }
  return "";
}

function stringValue(value: unknown) {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return "";
}
