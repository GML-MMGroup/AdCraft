import { useCallback, useEffect, useRef, useState } from "react";
import { agentCanvasApi, isV2ApiError } from "../../../../api/agentCanvasApi.ts";
import { createOperationKey } from "../../../../api/operationKey.ts";
import { useLocale } from "../../../../i18n/locale.tsx";
import { useTranslation } from "../../../../i18n/useTranslation.ts";
import type { AgentCanvasWorkflowV2, CanvasNodePatchRequestV2, CanvasNodeV2, ProjectAssetSummaryV2 } from "../../../../types-v2.ts";
import { useEditingText } from "../editingMessages.ts";
import { CUTIA_PROJECT_KEY, cutiaMediaFromAsset, initialCutiaSnapshot, legacyMigrationNotes, isCutiaSnapshot, savedCutiaState, snapshotKey, type CutiaSavedState, type CutiaSnapshot } from "./project.ts";
import { CUTIA_CHANNEL, isCutiaMessage } from "./protocol.ts";
import { CutiaSaveQueue } from "./saveQueue.ts";
import "./cutia-editor.css";

export interface AgentCanvasEditingPanelProps {
  workflow: AgentCanvasWorkflowV2;
  node: CanvasNodeV2;
  omittedNodeIds?: string[];
  patchNode: (nodeId: string, patch: CanvasNodePatchRequestV2, options?: { coalesce?: boolean; optimistic?: boolean }) => Promise<void>;
  onClose: () => void;
  onRevisionConflict?: () => Promise<unknown> | unknown;
  onAddRenderedAssetToCanvas?: (asset: ProjectAssetSummaryV2) => Promise<void> | void;
  onAssetsChanged?: () => Promise<unknown> | unknown;
}

export function CutiaEditingPanel(props: AgentCanvasEditingPanelProps) {
  const [attempt, setAttempt] = useState(0);
  // A new iframe also creates a fresh Cutia singleton, undo history and media cache.
  return <CutiaSession key={`${props.workflow.workflow_id}:${props.node.node_id}:${attempt}`} {...props} onRetryLoading={() => setAttempt(value => value + 1)} />;
}

function CutiaSession(props: AgentCanvasEditingPanelProps & { onRetryLoading: () => void }) {
  const t = useEditingText();
  const translateNodeName = useTranslation();
  const { locale } = useLocale();
  const callbacks = useRef(props); callbacks.current = props;
  const iframe = useRef<HTMLIFrameElement>(null);
  const panel = useRef<HTMLElement>(null);
  const [session] = useState(() => createOperationKey("cutia-session"));
  const [initial] = useState(() => {
    try { return { snapshot: initialCutiaSnapshot(props.workflow, props.node, translateNodeName), notes: legacyMigrationNotes(props.workflow, props.node), error: null }; }
    catch (error) { return { snapshot: null, notes: [], error: error instanceof Error ? error.message : "Unable to open the editing project." }; }
  });
  const [loaded, setLoaded] = useState(false);
  const [loadingMedia, setLoadingMedia] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(initial.error);
  const [busy, setBusy] = useState(false);
  const [importingMedia, setImportingMedia] = useState(false);
  const [uploadingExport, setUploadingExport] = useState(false);
  const [closing, setClosing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [format, setFormat] = useState<"mp4" | "webm">("mp4");
  const [adding, setAdding] = useState(false);
  const [exportAsset, setExportAsset] = useState<ProjectAssetSummaryV2 | null>(() => {
    try { const id = savedCutiaState(props.node)?.export?.assetId; return props.workflow.assets.find((asset) => asset.asset_id === id) || null; } catch { return null; }
  });
  const [exportStale, setExportStale] = useState(() => {
    try { const previous = savedCutiaState(props.node)?.export; return Boolean(previous && initial.snapshot && previous.snapshotKey !== snapshotKey(initial.snapshot)); } catch { return false; }
  });
  const snapshot = useRef(initial.snapshot);
  const savedState = useRef<CutiaSavedState | null>(null);
  if (savedState.current === null && initial.snapshot) {
    savedState.current = { snapshot: initial.snapshot };
    try { savedState.current = savedCutiaState(props.node) || savedState.current; } catch { /* Reported by initialization. */ }
  }
  const renderedFile = useRef<File | null>(null);
  const pendingExport = useRef<{ file: File; key: string; operationKey: string; asset?: ProjectAssetSummaryV2 } | null>(null);
  const busyRef = useRef(false); busyRef.current = busy || importingMedia;
  const pendingUploads = useRef(0);
  const mounted = useRef(true);
  const queue = useRef<CutiaSaveQueue | null>(null);
  if (!queue.current && initial.snapshot) queue.current = new CutiaSaveQueue(initial.snapshot, async (next) => {
    const { node, patchNode, onRevisionConflict } = callbacks.current;
    const state = { ...savedState.current, snapshot: next };
    try {
      await patchNode(node.node_id, { parameters: { ...node.parameters, [CUTIA_PROJECT_KEY]: state } }, { coalesce: true, optimistic: false });
      savedState.current = state;
    } catch (failure) {
      if (isV2ApiError(failure) && failure.status === 409) void onRevisionConflict?.();
      throw failure;
    }
  }, (state, failure) => {
    if (!mounted.current) return;
    setSaving(state === "saving");
    if (failure) setError(failure.message);
  });

  const post = useCallback((type: string, data: Record<string, unknown> = {}) => {
    iframe.current?.contentWindow?.postMessage({ channel: CUTIA_CHANNEL, session, type, ...data }, window.location.origin);
  }, [session]);

  const saveRenderedFile = useCallback(async () => {
    const pending = pendingExport.current;
    if (!pending || !snapshot.current) return;
    setUploadingExport(true);
    await queue.current?.flush();
    if (!pending.asset) {
      const form = new FormData(); form.append("file", pending.file);
      form.append("metadata", JSON.stringify({ media_type: "video", title: pending.file.name, metadata: { editing_node_id: props.node.node_id, editor: "cutia" } }));
      pending.asset = (await agentCanvasApi.uploadAgentCanvasAsset(props.workflow.workflow_id, form, pending.operationKey)).asset;
    }
    if (!mounted.current) return;
    const state: CutiaSavedState = { snapshot: snapshot.current, export: { assetId: pending.asset.asset_id, filename: pending.file.name, snapshotKey: pending.key } };
    await callbacks.current.patchNode(props.node.node_id, { parameters: { ...callbacks.current.node.parameters, [CUTIA_PROJECT_KEY]: state } }, { optimistic: false });
    if (!mounted.current) return;
    savedState.current = state;
    setExportAsset(pending.asset); setExportStale(pending.key !== snapshotKey(snapshot.current)); setBusy(false); setUploadingExport(false); setProgress(1);
    pendingExport.current = null;
    void Promise.resolve(callbacks.current.onAssetsChanged?.()).catch(() => undefined);
  }, [props.node.node_id, props.workflow.workflow_id]);

  useEffect(() => {
    mounted.current = true;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const element = panel.current;
    const containKeys = (event: KeyboardEvent) => event.stopPropagation();
    const containFocus = (event: FocusEvent) => {
      if (event.target instanceof Node && !element?.contains(event.target)) element?.querySelector<HTMLElement>("button:not(:disabled), a, select, iframe")?.focus();
    };
    element?.addEventListener("keydown", containKeys);
    document.addEventListener("focusin", containFocus);
    element?.focus();
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!queue.current?.dirty && !busyRef.current && !pendingUploads.current) return;
      event.preventDefault(); event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => {
      mounted.current = false;
      queue.current?.dispose();
      document.body.style.overflow = previousOverflow;
      element?.removeEventListener("keydown", containKeys);
      document.removeEventListener("focusin", containFocus);
      window.removeEventListener("beforeunload", beforeUnload);
      previousFocus?.focus();
    };
  }, []);

  useEffect(() => {
    if (!initial.snapshot) return;
    let timer: ReturnType<typeof setTimeout>;
    const resetLoadingTimeout = () => {
      clearTimeout(timer);
      if (!iframe.current?.dataset.loaded) timer = setTimeout(() => setError("The editor could not load. Reopen it to retry."), 120_000);
    };
    resetLoadingTimeout();
    const listener = async (event: MessageEvent) => {
      if (!isCutiaMessage(event, iframe.current?.contentWindow ?? null, session)) return;
      const data = event.data;
      const respond = (value?: unknown, failure?: string) => { if (mounted.current) post("response", { requestId: data.requestId, value, error: failure }); };
      try {
        if (data.type === "ready") post("init", { snapshot: initial.snapshot, language: locale.startsWith("zh") ? "zh" : "en" });
        else if (data.type === "loaded") { clearTimeout(timer); setLoaded(true); if (iframe.current) iframe.current.dataset.loaded = "true"; }
        else if (data.type === "loading-media" && typeof data.loading === "string") { resetLoadingTimeout(); setLoadingMedia(data.loading); }
        else if (data.type === "snapshot" || data.type === "flush") {
          if (!isCutiaSnapshot(data.snapshot) || data.snapshot.project.metadata.id !== initial.snapshot!.project.metadata.id) throw new Error("Invalid editing project.");
          snapshot.current = data.snapshot;
          queue.current?.enqueue(data.snapshot);
          setExportStale(Boolean(savedState.current?.export && savedState.current.export.snapshotKey !== snapshotKey(data.snapshot)));
          if (data.type === "flush") { await queue.current?.flush(); respond(); }
        } else if (data.type === "upload") {
          if (!(data.file instanceof Blob) || typeof data.mediaId !== "string") throw new Error("Invalid media upload.");
          const file = data.file as File;
          const mediaType = file.type.split("/")[0];
          if (!["video", "audio", "image"].includes(mediaType)) throw new Error("Choose a video, audio or image file.");
          const form = new FormData(); form.append("file", file);
          form.append("metadata", JSON.stringify({ media_type: mediaType, title: file.name, metadata: { editing_node_id: props.node.node_id } }));
          pendingUploads.current++;
          let result;
          try { result = await agentCanvasApi.uploadAgentCanvasAsset(props.workflow.workflow_id, form, createOperationKey("cutia-media")); }
          finally { pendingUploads.current--; }
          if (!mounted.current) return;
          respond({ media: cutiaMediaFromAsset(result.asset, { id: data.mediaId, nodes: callbacks.current.workflow.nodes, translate: translateNodeName }) });
          void Promise.resolve(callbacks.current.onAssetsChanged?.()).catch(() => undefined);
        } else if (data.type === "media-imported") setImportingMedia(false);
        else if (data.type === "progress") setProgress(Math.max(0, Math.min(1, Number(data.progress) || 0)));
        else if (data.type === "exported") {
          if (!(data.buffer instanceof ArrayBuffer) || !snapshot.current) throw new Error("The exported video is invalid.");
          if (data.snapshotKey !== snapshotKey(snapshot.current)) throw new Error("The edit changed during export. Please export again.");
          const file = new File([data.buffer], String(data.filename || "AdCraft.mp4"), { type: String(data.mimeType || "video/mp4") });
          renderedFile.current = file;
          pendingExport.current = { file, key: String(data.snapshotKey), operationKey: createOperationKey("cutia-export") };
          setExportAsset(null);
          await saveRenderedFile();
          respond();
        } else if (data.type === "export-cancelled") { setBusy(false); setProgress(0); }
        else if (data.type === "closed") callbacks.current.onClose();
        else if (data.type === "error") { clearTimeout(timer); setError(String(data.error)); setBusy(false); setClosing(false); setImportingMedia(false); }
      } catch (failure) {
        if (!mounted.current) return;
        const message = failure instanceof Error ? failure.message : "The editing operation failed.";
        setError(message); setBusy(false); setUploadingExport(false); setClosing(false);
        if (data.requestId) respond(undefined, message);
      }
    };
    window.addEventListener("message", listener);
    return () => { clearTimeout(timer); window.removeEventListener("message", listener); };
  }, [initial, locale, props.node.node_id, props.workflow.workflow_id, session, post, saveRenderedFile, translateNodeName]);

  async function download() {
    try {
      let blob: Blob | null = renderedFile.current;
      let filename = renderedFile.current?.name || savedState.current?.export?.filename || "AdCraft.mp4";
      if (!blob && exportAsset) {
        const response = await agentCanvasApi.downloadAgentCanvasAsset(exportAsset.asset_id);
        blob = response.blob; filename = response.filename || filename;
      }
      if (!blob) return;
      const url = URL.createObjectURL(blob); const link = document.createElement("a");
      link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Download failed."); }
  }

  const availableMedia = props.workflow.assets
    .filter(asset => asset.status === "ready" && !snapshot.current?.media.some(media => media.assetId === asset.asset_id))
    .map(asset => cutiaMediaFromAsset(asset, { nodes: props.workflow.nodes, translate: translateNodeName }));
  return <section className="cutia-editor-panel" role="dialog" aria-modal="true" aria-label={t("Editing studio")} ref={panel} tabIndex={-1}>
    <header className="cutia-editor-header">
      <div className="cutia-editor-title"><strong>{props.node.title || t("Editing studio")}</strong><span role="status">{error ? t("Action needed") : saving ? t("Saving changes") : loaded ? t("Saved") : loadingMedia || t("Loading editor")}</span></div>
      <div className="cutia-editor-actions">
        {availableMedia.length ? <select aria-label={t("Add project media")} value="" disabled={!loaded || busy || importingMedia || closing} onChange={event => {
          const media = availableMedia.find(media => media.assetId === event.currentTarget.value);
          if (media) { setImportingMedia(true); post("import-media", { media }); }
        }}><option value="">{t(importingMedia ? "Loading media" : "Add project media")}</option>{availableMedia.map(media => <option key={media.assetId} value={media.assetId}>{media.name}</option>)}</select> : null}
        {exportStale ? <span>{t("Changes not exported")}</span> : null}
        {exportAsset || renderedFile.current ? <button type="button" aria-label={t("Download exported video")} onClick={() => void download()}>{t("Download")}</button> : null}
        {exportAsset && props.onAddRenderedAssetToCanvas ? <button type="button" disabled={adding || busy || importingMedia || closing || exportStale || saving || Boolean(error)} onClick={async () => { setAdding(true); try { await props.onAddRenderedAssetToCanvas?.(exportAsset); } catch (failure) { setError(String(failure)); } finally { setAdding(false); } }}>{t(adding ? "Adding" : "Add to Canvas")}</button> : null}
        <select aria-label={t("Format")} value={format} disabled={busy} onChange={(event) => setFormat(event.currentTarget.value as "mp4" | "webm")}><option value="mp4">MP4</option><option value="webm">WebM</option></select>
        {busy ? <button type="button" disabled={uploadingExport} onClick={() => post("cancel-export")}>{t(uploadingExport ? "Uploading video" : "Cancel")} {Math.round(progress * 100)}%</button> : <button className="cutia-export-button" type="button" disabled={!loaded || closing || importingMedia || Boolean(error)} onClick={() => { setBusy(true); setProgress(0); setError(null); post("export", { format }); }}>{t("Export")}</button>}
        <button type="button" className="cutia-close-button" aria-label={t("Close editor")} disabled={busy || closing || importingMedia} onClick={() => { if (!loaded) { props.onClose(); return; } setClosing(true); post("close"); }}>×</button>
      </div>
    </header>
    {initial.notes.map(note => <p className="cutia-editor-notice" key={note}>{t(note)}</p>)}
    {props.omittedNodeIds?.length ? <p className="cutia-editor-notice">{t("Some source videos are not ready and have not been added to this timeline.")}</p> : null}
    {error ? <div className="cutia-editor-error" role="alert"><span>{error}</span>{loaded ? <><button type="button" disabled={busy} onClick={async () => {
      setError(null);
      try {
        await queue.current?.retry();
        if (pendingExport.current) { setBusy(true); post("lock", { busy: true }); await saveRenderedFile(); }
      } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
      finally { setBusy(false); setUploadingExport(false); post("lock", { busy: false }); }
    }}>{t(pendingExport.current ? "Retry upload" : queue.current?.dirty ? "Retry saving" : "Dismiss")}</button><button type="button" onClick={props.onClose}>{t("Close without saving")}</button></> : initial.snapshot ? <button type="button" onClick={props.onRetryLoading}>{t("Retry loading")}</button> : null}</div> : null}
    {initial.snapshot ? <iframe ref={iframe} title={t("Editing studio")} className="cutia-editor-frame" src={`${import.meta.env.BASE_URL}cutia-editor.html#${encodeURIComponent(session)}`} allow="fullscreen; autoplay; clipboard-read; clipboard-write" /> : null}
  </section>;
}
