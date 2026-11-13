import { EditorCore } from "../vendor/cutia/src/core";
import { storageService } from "../vendor/cutia/src/services/storage/service";
import type { MediaAsset } from "../vendor/cutia/src/types/assets";
import { CUTIA_CHANNEL, isCutiaMessage } from "../src/features/agent-canvas/editing/cutia/protocol";
import { isCutiaSnapshot, snapshotKey, type CutiaMedia, type CutiaSnapshot } from "../src/features/agent-canvas/editing/cutia/project";
import { setLanguage } from "./adapters/i18n";
import { _setGlobalTranslation } from "../vendor/cutia/src/lib/i18n";
import { t } from "./adapters/i18n";
import { downloadMedia } from "./load-media";

export const session = decodeURIComponent(window.location.hash.slice(1));
const requests = new Map<string, { resolve: (value: unknown) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>();
const sources = new Map<string, CutiaMedia>();
const uploads = new Map<string, Promise<void>>();
let editor: EditorCore | null = null;
let lastSnapshotKey = "";
let cancelled = false;
let rendering = false;
let initialized = false;
let onStatus: (status: { ready?: boolean; loading?: string; busy?: boolean; error?: string }) => void = () => undefined;

export function send(type: string, payload: Record<string, unknown> = {}, transfer: Transferable[] = []) {
  window.parent.postMessage({ channel: CUTIA_CHANNEL, session, type, ...payload }, window.location.origin, transfer);
}

function request<T>(type: string, payload: Record<string, unknown>, transfer: Transferable[] = []): Promise<T> {
  const requestId = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { requests.delete(requestId); reject(new Error("The project did not respond. Please retry.")); }, 120_000);
    requests.set(requestId, { resolve: value => resolve(value as T), reject, timer });
    send(type, { ...payload, requestId }, transfer);
  });
}

export function currentSnapshot(): CutiaSnapshot {
  if (!editor) throw new Error("Editor is not ready.");
  const project = editor.project.getActive();
  // AudioBuffer, File and object URLs belong to this browser session, never to
  // the persisted project. Media references remain backend asset IDs.
  return JSON.parse(JSON.stringify({ schemaVersion: 1, project: {
    ...project, agentMessages: undefined, scenes: editor.scenes.getScenes(),
  }, media: [...sources.values()].filter(source => editor!.media.getAssets().some(asset => asset.id === source.id)) }, (key, value) => key === "buffer" ? undefined : value));
}

function publishSnapshot() {
  if (!initialized || uploads.size) return;
  const snapshot = currentSnapshot();
  const key = snapshotKey(snapshot);
  if (key === lastSnapshotKey) return;
  lastSnapshotKey = key;
  send("snapshot", { snapshot });
}

async function persistMedia(asset: MediaAsset) {
  if (sources.has(asset.id)) return;
  const previous = uploads.get(asset.id);
  if (previous) return previous;
  const pending = (async () => {
    const result = await request<{ media: CutiaMedia }>("upload", { file: asset.file, mediaId: asset.id });
    sources.set(asset.id, { ...result.media, id: asset.id });
  })();
  uploads.set(asset.id, pending);
  try { await pending; } finally { uploads.delete(asset.id); publishSnapshot(); }
}

async function loadMedia(source: CutiaMedia, onProgress?: (loaded: number, total: number) => void, onRetry?: () => void): Promise<MediaAsset> {
  const blob = await downloadMedia(source, onProgress, onRetry);
  const file = new File([blob], source.name, { type: source.mimeType || blob.type });
  return { ...source, file, url: URL.createObjectURL(file) };
}

async function importMedia(source: CutiaMedia) {
  if (!editor || rendering) return;
  onStatus({ busy: true });
  try {
    if (!editor.media.getAssets().some(asset => asset.id === source.id)) {
      const asset = await loadMedia(source);
      sources.set(source.id, source);
      editor.media.setAssets({ assets: [...editor.media.getAssets(), asset] });
    }
    send("media-imported");
  } catch (error) { send("error", { error: error instanceof Error ? error.message : "Unable to load media." }); }
  finally { onStatus({ busy: false }); }
}

async function initialize(snapshot: CutiaSnapshot, language: string) {
  if (editor || !isCutiaSnapshot(snapshot)) return;
  setLanguage(language); _setGlobalTranslation({ t });
  editor = EditorCore.getInstance();
  editor.save.stop();
  editor.save.pause();
  // All writes are owned by AdCraft. Native Cutia features (upload, paste and
  // freeze-frame) use this same adapter; undo never deletes a project asset.
  storageService.saveMediaAsset = async ({ mediaAsset }) => persistMedia(mediaAsset);
  storageService.deleteMediaAsset = async () => undefined;
  storageService.saveProject = async () => { publishSnapshot(); };
  const project = structuredClone(snapshot.project);
  project.metadata.createdAt = new Date(project.metadata.createdAt);
  project.metadata.updatedAt = new Date(project.metadata.updatedAt);
  project.scenes.forEach((scene) => { scene.createdAt = new Date(scene.createdAt); scene.updatedAt = new Date(scene.updatedAt); });
  editor.project.setActiveProject({ project });
  editor.scenes.initializeScenes({ scenes: project.scenes, currentSceneId: project.currentSceneId });
  const assets: MediaAsset[] = [];
  let index = 0;
  for (const source of snapshot.media) {
    ++index;
    let progress = 0;
    const report = (retrying = false) => {
      const loading = `${t("Loading media")} ${index}/${snapshot.media.length} · ${source.name} ${progress}%${retrying ? ` · ${t("Connection interrupted. Retrying…")}` : ""}`;
      onStatus({ loading });
      send("loading-media", { loading });
    };
    report();
    assets.push(await loadMedia(source, (loaded, total) => {
      progress = total ? Math.round(loaded / total * 100) : 100;
      report();
    }, () => report(true)));
    sources.set(source.id, source);
  }
  editor.media.setAssets({ assets });
  editor.command.clear();
  lastSnapshotKey = snapshotKey(currentSnapshot());
  initialized = true;
  // Project notifications include track, text, transform and settings changes.
  editor.project.subscribe(publishSnapshot);
  editor.media.subscribe(publishSnapshot);
  onStatus({ ready: true, loading: "" });
  send("loaded");
}

async function flush() {
  await Promise.all(uploads.values());
  publishSnapshot();
  await request("flush", { snapshot: currentSnapshot() });
}

async function exportFilm(format: "mp4" | "webm") {
  if (!editor || rendering) return;
  rendering = true; cancelled = false;
  onStatus({ busy: true });
  editor.playback.pause();
  try {
    await flush();
    if (!window.isSecureContext || typeof VideoEncoder === "undefined") throw new Error(t("Browser export requires a current Chrome or Edge browser over HTTPS."));
    const snapshot = currentSnapshot();
    const result = await editor.renderer.exportProject({ options: {
      format, quality: "high", includeAudio: true,
      onProgress: ({ progress }) => send("progress", { progress }), onCancel: () => cancelled,
    } });
    if (cancelled || result.cancelled) { send("export-cancelled"); return; }
    if (!result.success || !result.buffer) throw new Error(result.error || "Export failed.");
    const filename = `${editor.project.getActive().metadata.name || "AdCraft"}.${format}`;
    await request("exported", { buffer: result.buffer, filename, mimeType: format === "webm" ? "video/webm" : "video/mp4", snapshotKey: snapshotKey(snapshot) }, [result.buffer]);
  } catch (error) {
    send("error", { error: error instanceof Error ? error.message : "Export failed." });
  } finally { rendering = false; onStatus({ busy: false }); }
}

export function startBridge(status: typeof onStatus) {
  onStatus = status;
  const listener = (event: MessageEvent) => {
    if (!isCutiaMessage(event, window.parent, session)) return;
    const data = event.data;
    if (data.type === "response" && data.requestId) {
      const pending = requests.get(data.requestId);
      if (!pending) return;
      clearTimeout(pending.timer); requests.delete(data.requestId);
      if (data.error) pending.reject(new Error(String(data.error))); else pending.resolve(data.value);
    } else if (data.type === "init" && !editor) {
      void initialize(data.snapshot as CutiaSnapshot, String(data.language)).catch((error) => {
        onStatus({ error: error.message, loading: "" }); send("error", { error: error.message });
      });
    } else if (data.type === "lock") {
      onStatus({ busy: Boolean(data.busy) });
    } else if (data.type === "import-media" && initialized) {
      void importMedia(data.media as CutiaMedia);
    } else if (data.type === "export") {
      void exportFilm(data.format === "webm" ? "webm" : "mp4");
    } else if (data.type === "cancel-export") { cancelled = true; }
    else if (data.type === "close" && !rendering) {
      void flush().then(() => { editor?.playback.pause(); send("closed"); }).catch((error) => send("error", { error: error.message }));
    }
  };
  window.addEventListener("message", listener);
  send("ready");
  return () => {
    window.removeEventListener("message", listener);
    editor?.playback.pause(); editor?.audio.dispose(); editor?.media.clearAllAssets();
    requests.forEach(({ reject, timer }) => { clearTimeout(timer); reject(new Error("Editor closed.")); });
    requests.clear();
  };
}
