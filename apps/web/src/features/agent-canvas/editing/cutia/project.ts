import type { TProject } from "../../../../../vendor/cutia/src/types/project";
import type { TimelineTrack, VideoElement, UploadAudioElement } from "../../../../../vendor/cutia/src/types/timeline";
import type { AgentCanvasWorkflowV2, CanvasNodeV2, ProjectAssetSummaryV2 } from "../../../../types-v2.ts";
import { mediaAssetContentPath, mediaAssetPosterPath } from "../../../../workflow/mediaPreview.ts";
import { canvasNodeDisplayName } from "../../canvas/canvasNodeDisplayName.ts";
import { normalizeEditingNodeContentV2 } from "../../model/normalizers.ts";
import { buildEditingInputs } from "../editingModel.ts";
import { buildPlayableEditingSequence } from "../editingPlayableSequence.ts";

export type CutiaProject = TProject;
export interface CutiaMedia {
  id: string;
  assetId: string;
  name: string;
  type: "video" | "audio" | "image";
  url: string;
  mimeType: string;
  duration?: number;
  width?: number;
  height?: number;
  thumbnailUrl?: string;
}

export interface CutiaSnapshot {
  schemaVersion: 1;
  project: CutiaProject;
  media: CutiaMedia[];
}

export interface CutiaSavedState {
  snapshot: CutiaSnapshot;
  export?: { assetId: string; filename: string; snapshotKey: string };
}

export const CUTIA_PROJECT_KEY = "cutia_editor_v1";

interface CutiaMediaOptions {
  id?: string;
  nodes?: readonly CanvasNodeV2[];
  translate?: Parameters<typeof canvasNodeDisplayName>[1];
}

export function cutiaMediaFromAsset(asset: ProjectAssetSummaryV2, options: CutiaMediaOptions = {}): CutiaMedia {
  const node = options.nodes?.find(candidate => candidate.node_id === asset.source_node_id)
    ?? options.nodes?.find(candidate => candidate.output_asset_id === asset.asset_id);
  return {
    id: options.id ?? asset.asset_id, assetId: asset.asset_id,
    name: node ? canvasNodeDisplayName(node, options.translate) : asset.display_name, type: asset.media_type,
    url: asset.version_id ? mediaAssetContentPath(asset) : `/api/v2/assets/${encodeURIComponent(asset.asset_id)}/content`, mimeType: asset.mime_type,
    duration: asset.duration_seconds ?? undefined,
    width: asset.width ?? undefined, height: asset.height ?? undefined,
    thumbnailUrl: asset.media_type === "video" || asset.media_type === "image"
      ? mediaAssetPosterPath(asset) || undefined : undefined,
  };
}

export function snapshotKey(snapshot: CutiaSnapshot): string {
  // Metadata timestamps and viewport movements do not invalidate a rendered film.
  return JSON.stringify({
    scenes: snapshot.project.scenes.map(({ id, tracks }) => ({ id, tracks })),
    currentSceneId: snapshot.project.currentSceneId,
    settings: snapshot.project.settings,
    media: snapshot.media.map(({ id, assetId }) => ({ id, assetId })),
  });
}

export function isCutiaSnapshot(value: unknown): value is CutiaSnapshot {
  if (!value || typeof value !== "object") return false;
  const snapshot = value as CutiaSnapshot;
  return snapshot.schemaVersion === 1 && Array.isArray(snapshot.media)
    && snapshot.media.every((item) => item && typeof item.id === "string"
      && typeof item.assetId === "string" && typeof item.url === "string"
      && ["video", "audio", "image"].includes(item.type))
    && Boolean(snapshot.project?.metadata?.id)
    && Number.isFinite(snapshot.project?.settings?.fps)
    && Number.isFinite(snapshot.project?.settings?.canvasSize?.width)
    && Number.isFinite(snapshot.project?.settings?.canvasSize?.height)
    && Array.isArray(snapshot.project.scenes)
    && snapshot.project.scenes.some((scene) => scene.id === snapshot.project.currentSceneId)
    && snapshot.project.scenes.every((scene) => Array.isArray(scene.tracks)
      && scene.tracks.every((track) => Array.isArray(track.elements)
        && track.elements.every((element) => typeof element.id === "string"
          && Number.isFinite(element.startTime) && element.startTime >= 0
          && Number.isFinite(element.duration) && element.duration >= 0)));
}

export function savedCutiaState(node: CanvasNodeV2): CutiaSavedState | null {
  const value = node.parameters?.[CUTIA_PROJECT_KEY];
  if (value == null) return null;
  const state = value as CutiaSavedState;
  if (!isCutiaSnapshot(state.snapshot)) throw new Error("The saved editing project could not be read.");
  return state;
}

export function initialCutiaSnapshot(workflow: AgentCanvasWorkflowV2, node: CanvasNodeV2, translate?: CutiaMediaOptions["translate"]): CutiaSnapshot {
  const mediaOptions = { nodes: workflow.nodes, translate };
  const saved = savedCutiaState(node);
  if (saved) {
    return {
      ...saved.snapshot,
      media: saved.snapshot.media.map((media) => {
        const asset = workflow.assets.find((candidate) => candidate.asset_id === media.assetId);
        return asset ? cutiaMediaFromAsset(asset, { ...mediaOptions, id: media.id }) : media;
      }),
    };
  }
  if (node.structured_content?.manifest === undefined) throw new Error("This Editing node does not yet contain a composition manifest.");
  const content = normalizeEditingNodeContentV2(node.structured_content);
  const inputs = buildEditingInputs(workflow, node.node_id, content);
  const sequence = buildPlayableEditingSequence(inputs.videos, content.manifest.timeline_duration_seconds);
  const sourceIds = new Set([...inputs.videos.map((input) => input.asset?.asset_id), inputs.bgm?.asset?.asset_id]);
  const media = workflow.assets.filter((asset) => sourceIds.has(asset.asset_id) && asset.status === "ready" && asset.media_url).map((asset) => cutiaMediaFromAsset(asset, mediaOptions));
  const first = sequence.videos[0]?.asset;
  const resolution = content.manifest.output.resolution?.match(/^(\d+)x(\d+)$/);
  const ratio = content.manifest.output.aspect_ratio?.split(":").map(Number);
  const height = resolution ? Number(resolution[2]) : first?.height || 1080;
  const width = resolution ? Number(resolution[1]) : ratio?.length === 2 && ratio.every(n => n > 0)
    ? Math.round(height * ratio[0] / ratio[1] / 2) * 2 : first?.width || 1920;
  const tracks: TimelineTrack[] = [{ id: "main-video", name: "Video", type: "video", isMain: true, muted: false, hidden: false, elements: [] }];
  const videoTrack = tracks[0];
  if (videoTrack.type !== "video") throw new Error("Missing video track.");
  const nativeAudio: UploadAudioElement[] = [];
  sequence.segments.forEach((segment) => {
    const input = sequence.videos.find((candidate) => candidate.referenceId === segment.referenceId);
    if (!input?.asset) return;
    const asset = input.asset;
    const duration = segment.sourceEnd - segment.sourceStart;
    const separateAudio = input.entry.preserve_native_audio && input.entry.volume !== 1;
    const scale = input.entry.fit_mode === "fill" && asset.width && asset.height
      ? Math.max(width / asset.width, height / asset.height) / Math.min(width / asset.width, height / asset.height) : 1;
    const element: VideoElement = {
      id: `video:${input.referenceId}`, type: "video", name: input.node?.title || asset.display_name,
      mediaId: asset.asset_id, startTime: segment.timelineStart, duration,
      trimStart: segment.sourceStart, trimEnd: Math.max(0, (asset.duration_seconds || segment.sourceEnd) - segment.sourceEnd),
      muted: !input.entry.preserve_native_audio || separateAudio,
      transform: { scale, position: { x: 0, y: 0 }, rotate: 0 }, opacity: 1,
    };
    videoTrack.elements.push(element);
    if (separateAudio) nativeAudio.push({
      id: `audio:${input.referenceId}`, type: "audio", sourceType: "upload", name: element.name,
      mediaId: asset.asset_id, startTime: element.startTime, duration, trimStart: element.trimStart,
      trimEnd: element.trimEnd, volume: input.entry.volume,
    });
  });
  if (nativeAudio.length) tracks.push({ id: "native-audio", name: "Original audio", type: "audio", muted: false, elements: nativeAudio });
  const bgm = inputs.bgm;
  if (bgm?.entry.enabled && bgm.asset?.status === "ready" && bgm.asset.media_url) {
    const sourceDuration = bgm.asset.duration_seconds || sequence.duration;
    const elements: UploadAudioElement[] = [];
    let time = 0;
    let sourceStart = bgm.entry.trim_start_seconds;
    const sourceEnd = bgm.entry.trim_end_seconds ?? sourceDuration;
    while (time < sequence.duration && sourceEnd > sourceStart && elements.length < 1000) {
      const duration = Math.min(sourceEnd - sourceStart, sequence.duration - time);
      elements.push({ id: `bgm:${elements.length}`, name: bgm.asset.display_name, type: "audio", sourceType: "upload",
        mediaId: bgm.asset.asset_id, startTime: time, duration, trimStart: sourceStart,
        trimEnd: Math.max(0, sourceDuration - sourceStart - duration), volume: bgm.entry.volume });
      time += duration;
      if (bgm.entry.trim_end_seconds !== null) break;
      sourceStart = 0;
    }
    tracks.push({ id: "bgm", name: "BGM", type: "audio", muted: false, elements });
  }
  // Cutia derives duration from its elements. Preserve an existing empty tail as
  // an editable, transparent spacer instead of silently shortening the film.
  const lastEnd = Math.max(0, ...tracks.flatMap(track => track.elements.map(element => element.startTime + element.duration)));
  if (sequence.duration > lastEnd + 0.001) tracks.push({ id: "timeline-duration", type: "text", name: "Timeline duration", hidden: true,
    elements: [{ type: "text", fontSize: 15, fontFamily: "Arial", color: "#ffffff", backgroundColor: "transparent", textAlign: "center", fontWeight: "normal", fontStyle: "normal", textDecoration: "none", trimStart: 0, trimEnd: 0, transform: { scale: 1, position: { x: 0, y: 0 }, rotate: 0 }, id: "timeline-tail", name: "Empty tail", content: "", startTime: lastEnd, duration: sequence.duration - lastEnd, opacity: 0 }] });
  const now = new Date(node.created_at);
  const scene = { id: "main-scene", name: "Main scene", isMain: true, tracks, bookmarks: [], createdAt: now, updatedAt: now };
  return { schemaVersion: 1, media, project: {
    metadata: { id: `${workflow.workflow_id}:${node.node_id}`, name: node.title || "Composition", duration: sequence.duration, createdAt: now, updatedAt: now },
    scenes: [scene], currentSceneId: scene.id, version: 3,
    settings: { fps: content.manifest.output.fps || 30, canvasSize: { width, height }, originalCanvasSize: { width, height }, background: { type: "color", color: "#000000" } },
  } };
}

/** Report unavailable source videos when importing a legacy edit. */
export function legacyMigrationNotes(workflow: AgentCanvasWorkflowV2, node: CanvasNodeV2): string[] {
  if (savedCutiaState(node)) return [];
  const content = normalizeEditingNodeContentV2(node.structured_content);
  const inputs = buildEditingInputs(workflow, node.node_id, content);
  const notes: string[] = [];
  if (inputs.videos.some(input => input.entry.enabled && (input.asset?.status !== "ready" || !input.asset?.media_url))) {
    notes.push("Some source videos are not ready and have not been added to this timeline.");
  }
  return notes;
}
