import "@xzdarcy/react-timeline-editor/dist/react-timeline-editor.css";
/* eslint-disable react-refresh/only-export-components */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { mediaUrl } from "../../../api/client.ts";
import { AssetsIcon, PlusIcon, VideoIcon } from "../../../icons.tsx";
import type { V2FinalCompositionTimeline, V2FinalTimelineSource } from "../../../types-v2.ts";
import { versionedMediaPath } from "../../../workflow/mediaPreview.ts";
import { AssetLibraryPicker } from "../assets/AssetLibraryPanels.tsx";
import { V2CompositionInspector } from "./V2CompositionInspector.tsx";
import {
  V2CompositionPreview,
  type V2CompositionPreviewHandle,
} from "./V2CompositionPreview.tsx";
import { fitShotTimelineZoom, V2ShotTimeline } from "./V2ShotTimeline.tsx";
import { V2TimelineToolbar } from "./V2TimelineToolbar.tsx";
import {
  resolveScopedTimelineSource,
  useV2FinalCompositionEditor,
  type CompositionEditorSession,
  type ScopedTimelineSource,
} from "./useV2FinalCompositionEditor.ts";

export function isTimelineKeyboardTarget(target: EventTarget | null) {
  const element = target as HTMLElement | null;
  if (!element || typeof element.tagName !== "string") return false;
  const tagName = element.tagName.toUpperCase();
  if (["INPUT", "TEXTAREA", "SELECT", "BUTTON", "A"].includes(tagName)) return true;
  if (element.isContentEditable) return true;
  return typeof element.closest === "function" && element.closest("[contenteditable='true']") !== null;
}

export function V2FinalCompositionEditor({
  workflowId,
  active,
  onWorkflowRefresh,
}: {
  workflowId: string;
  active: boolean;
  onWorkflowRefresh: (workflowId: string) => Promise<unknown> | unknown;
}) {
  const editor = useV2FinalCompositionEditor({ workflowId, active, onWorkflowRefresh });
  const editorRef = useRef(editor);
  const previewRef = useRef<V2CompositionPreviewHandle>(null);
  const mainRef = useRef<HTMLDivElement>(null);
  const [libraryType, setLibraryType] = useState<"video" | "audio" | null>(null);
  const [playing, setPlaying] = useState(false);
  const editorSessionRef = useRef<CompositionEditorSession>({ workflowId, generation: 0, active });
  const [pendingBgmSource, setPendingBgmSource] = useState<ScopedTimelineSource | null>(null);
  const [pendingRegisteredSource, setPendingRegisteredSource] = useState<ScopedTimelineSource | null>(null);
  const sources = useMemo(
    () => editor.sources.filter((source) => source.media_type === "video" || source.media_type === "audio"),
    [editor.sources],
  );

  useLayoutEffect(() => {
    const previousSession = editorSessionRef.current;
    const changed = previousSession.workflowId !== workflowId || previousSession.active !== active;
    editorSessionRef.current = {
      workflowId,
      active,
      generation: changed ? previousSession.generation + 1 : previousSession.generation,
    };
    editorRef.current = editor;
  }, [active, editor, workflowId]);

  useEffect(() => {
    if (!active) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (isTimelineKeyboardTarget(event.target)) return;
      const current = editorRef.current;
      const key = event.key.toLowerCase();
      const command = event.metaKey || event.ctrlKey;

      if (event.code === "Space") {
        event.preventDefault();
        if (!event.repeat) previewRef.current?.togglePlayback();
        return;
      }
      if (command && key === "b") {
        event.preventDefault();
        current.splitAtPlayhead();
        return;
      }
      if (command && key === "z") {
        event.preventDefault();
        if (event.shiftKey) current.redo();
        else current.undo();
        return;
      }
      if (event.ctrlKey && key === "y") {
        event.preventDefault();
        current.redo();
        return;
      }
      if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        current.deleteSelection();
        return;
      }
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        previewRef.current?.pause();
        const direction = event.key === "ArrowLeft" ? -1 : 1;
        const step = event.shiftKey ? 1 : 1 / Math.max(1, current.draft?.fps ?? 24);
        current.setPlayheadSeconds(Math.min(
          current.durationSeconds,
          Math.max(0, current.playheadSeconds + direction * step),
        ));
        return;
      }
      if (!command && key === "v") {
        event.preventDefault();
        current.setTool("select");
        return;
      }
      if (!command && key === "b") {
        event.preventDefault();
        current.setTool("blade");
        return;
      }
      if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        current.setZoom(current.zoom * 1.25);
        return;
      }
      if (event.key === "-" || event.key === "_") {
        event.preventDefault();
        current.setZoom(current.zoom / 1.25);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [active]);

  useEffect(() => {
    setPendingBgmSource(null);
    setPendingRegisteredSource(null);
    setLibraryType(null);
    if (!active) {
      previewRef.current?.pause();
      setPlaying(false);
    }
  }, [active, workflowId]);

  useEffect(() => {
    if (!pendingBgmSource) return;
    const cancelOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPendingBgmSource(null);
    };
    window.addEventListener("keydown", cancelOnEscape);
    return () => window.removeEventListener("keydown", cancelOnEscape);
  }, [pendingBgmSource]);

  const routeScopedSourceAdd = useCallback((scopedSource: ScopedTimelineSource) => {
    const currentEditor = editorRef.current;
    const source = resolveScopedTimelineSource(
      scopedSource,
      editorSessionRef.current,
      currentEditor.sources,
    );
    if (!source) return false;
    const currentScopedSource = { ...scopedSource, source };
    if (source.media_type === "audio" && currentEditor.draft && hasMarkedBgm(currentEditor.draft)) {
      setPendingBgmSource(currentScopedSource);
      return true;
    }
    currentEditor.addSource(source);
    return true;
  }, []);

  const requestSourceAdd = (source: V2FinalTimelineSource) => {
    routeScopedSourceAdd({ session: editorSessionRef.current, source });
  };

  useEffect(() => {
    if (!pendingRegisteredSource) return;
    const currentSession = editorSessionRef.current;
    if (pendingRegisteredSource.session.workflowId !== currentSession.workflowId
      || pendingRegisteredSource.session.generation !== currentSession.generation
      || !currentSession.active) {
      setPendingRegisteredSource(null);
      return;
    }
    if (routeScopedSourceAdd(pendingRegisteredSource)) setPendingRegisteredSource(null);
  }, [editor.sources, pendingRegisteredSource, routeScopedSourceAdd]);

  if (!active) return null;
  return (
    <section className="v2-composition-editor" aria-label="Final Composition editor">
      <header className="v2-composition-editor-toolbar">
        <div>
          <strong>Final Composition</strong>
          <span>
            {editor.draft
              ? `${editor.draft.aspect_ratio} · ${editor.draft.resolution.width}x${editor.draft.resolution.height} · ${editor.draft.fps} fps`
              : "Loading timeline"}
          </span>
        </div>
      </header>
      <V2TimelineToolbar
        tool={editor.tool}
        editMode={editor.editMode}
        snapEnabled={editor.snapEnabled}
        zoom={editor.zoom}
        playing={playing}
        canUndo={editor.canUndo}
        canRedo={editor.canRedo}
        canSave={editor.isDirty && !editor.saving && !editor.conflict}
        canRender={Boolean(editor.draft) && !editor.saving && !editor.rendering && !editor.conflict}
        loading={editor.loading}
        saving={editor.saving}
        rendering={editor.rendering}
        onSetTool={editor.setTool}
        onSetEditMode={editor.setEditMode}
        onToggleSnap={() => editor.setSnapEnabled(!editor.snapEnabled)}
        onUndo={editor.undo}
        onRedo={editor.redo}
        onZoomOut={() => editor.setZoom(editor.zoom / 1.25)}
        onZoomIn={() => editor.setZoom(editor.zoom * 1.25)}
        onFitTimeline={() => editor.setZoom(editor.draft
          ? fitShotTimelineZoom(editor.draft, Math.max(160, (mainRef.current?.clientWidth ?? 0) - 132))
          : 1)}
        onTogglePlaying={() => previewRef.current?.togglePlayback()}
        onRefresh={() => void editor.load({ preserveDraft: true })}
        onSave={() => void editor.save()}
        onRender={() => void editor.render()}
      />
      {editor.error ? <p className="v2-composition-feedback is-error">{editor.error}</p> : null}
      {editor.warning ? <p className="v2-composition-feedback">{editor.warning}</p> : null}
      {editor.conflict ? (
        <div className="v2-composition-feedback is-error">
          <span>{editor.conflict.message}</span>
          <button type="button" onClick={() => void editor.keepLocal()}>Keep local</button>
          <button type="button" onClick={() => void editor.reloadRemote()}>Reload remote</button>
        </div>
      ) : editor.externalUpdate ? (
        <p className="v2-composition-feedback">
          A newer saved timeline is available. Your local edits remain unchanged until you refresh or save.
        </p>
      ) : null}
      {editor.renderJob ? (
        <p className="v2-composition-feedback">Render {editor.renderJob.status}: {editor.renderJob.render_id}</p>
      ) : null}
      {editor.loading && !editor.draft ? (
        <p className="v2-composition-feedback">Loading Final Composition timeline...</p>
      ) : null}
      {editor.draft ? (
        <div className="v2-composition-editor-layout">
          <aside className="v2-composition-source-panel" aria-label="Timeline media">
            <div className="v2-composition-panel-heading"><strong>Media</strong><span>{sources.length}</span></div>
            <div className="v2-composition-source-actions">
              <IconButton label="Import a video from Asset Library" onClick={() => setLibraryType("video")}>
                <VideoIcon />
              </IconButton>
              <IconButton label="Import BGM from Asset Library" onClick={() => setLibraryType("audio")}>
                <AssetsIcon />
              </IconButton>
            </div>
            <div className="v2-composition-source-list">
              {sources.map((source) => (
                <SourceCard
                  key={`${source.asset_id}-${source.version_id}`}
                  source={source}
                  onAdd={() => requestSourceAdd(source)}
                />
              ))}
              {!sources.length ? <span className="v2-composition-empty">No timeline-ready media yet.</span> : null}
            </div>
          </aside>
          <div ref={mainRef} className="v2-composition-editor-main">
            <V2CompositionPreview
              ref={previewRef}
              timeline={editor.draft}
              sources={editor.sources}
              playheadSeconds={editor.playheadSeconds}
              playing={playing}
              onPlayingChange={setPlaying}
              onPlayheadChange={editor.setPlayheadSeconds}
              selectedClipId={editor.selectedClipId}
              onSelectClip={editor.setSelectedClipId}
            />
            <V2ShotTimeline
              workflowId={workflowId}
              timeline={editor.draft}
              sources={editor.sources}
              selectedClipIds={editor.selectedClipIds}
              playheadSeconds={editor.playheadSeconds}
              zoom={editor.zoom}
              snapEnabled={editor.snapEnabled}
              tool={editor.tool}
              onSetSnapEnabled={editor.setSnapEnabled}
              onSetSelectedClipIds={editor.setSelectedClipIds}
              onSetPlayheadSeconds={editor.setPlayheadSeconds}
              onSplitAtPlayhead={editor.splitAtPlayhead}
              onUpdateTrack={editor.updateTrack}
              onSetClipAudio={editor.setClipAudio}
              onReorderLane={editor.reorderLane}
              onRemoveImportedLane={editor.removeImportedLane}
              mediaUrl={mediaUrl}
              moveClip={editor.moveClip}
              trimClip={editor.trimClip}
              finalizeGesture={editor.finalizeGesture}
            />
          </div>
          <V2CompositionInspector
            clip={editor.selectedClip?.clip_type === "video" || editor.selectedClip?.clip_type === "audio"
              ? editor.selectedClip
              : null}
            onMoveClip={editor.moveClip}
            onTrimClip={editor.trimClip}
            onFinalizeGesture={editor.finalizeGesture}
            onUpdateClip={editor.updateClip}
            onSetAudio={editor.setClipAudio}
            onSetColor={editor.setClipColor}
            onSplitAtPlayhead={editor.splitAtPlayhead}
            onRemove={editor.removeClip}
          />
        </div>
      ) : null}
      {libraryType ? (
        <AssetLibraryPicker
          selectedEntities={[]}
          lockedEntityType={libraryType === "audio" ? "bgm" : "video_clip"}
          selectionMode="single"
          onClose={() => setLibraryType(null)}
          onToggle={(entity) => {
            const assetId = entity.asset_ids?.[0] ?? entity.assets?.[0]?.asset_id;
            if (!assetId) return;
            const registrationSession = editorSessionRef.current;
            const registrationMediaType = libraryType;
            void editor.registerLibrarySource({
              entityId: entity.entity_id,
              assetId,
              mediaType: registrationMediaType,
            }).then((source) => {
              if (!source) return;
              const scopedSource = { session: registrationSession, source };
              if (!resolveScopedTimelineSource(scopedSource, editorSessionRef.current, [source])) return;
              setLibraryType(null);
              setPendingRegisteredSource(scopedSource);
            });
          }}
        />
      ) : null}
      {pendingBgmSource ? (
        <div
          className="v2-composition-bgm-confirmation"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="v2-bgm-confirmation-title"
          aria-describedby="v2-bgm-confirmation-description"
        >
          <div className="v2-composition-bgm-confirmation-content">
            <strong id="v2-bgm-confirmation-title">Replace current BGM?</strong>
            <p id="v2-bgm-confirmation-description">
              Replace the current BGM with {pendingBgmSource.source.display_name}. Existing BGM timing is updated only after confirmation.
            </p>
            <div className="v2-composition-bgm-confirmation-actions">
              <button type="button" onClick={() => setPendingBgmSource(null)}>Cancel</button>
              <button
                type="button"
                autoFocus
                onClick={() => {
                  const pending = pendingBgmSource;
                  setPendingBgmSource(null);
                  const source = resolveScopedTimelineSource(
                    pending,
                    editorSessionRef.current,
                    editorRef.current.sources,
                  );
                  if (source?.media_type === "audio") editorRef.current.addSource(source);
                }}
              >
                Replace BGM
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function SourceCard({ source, onAdd }: { source: V2FinalTimelineSource; onAdd: () => void }) {
  return (
    <button className="v2-composition-source" type="button" onClick={onAdd}>
      <span className="v2-composition-source-thumb">
        {source.thumbnail_url || (source.media_type !== "audio" && source.public_url) ? (
          <img
            src={mediaUrl(versionedMediaPath(source.thumbnail_url ?? source.public_url, source))}
            alt=""
            loading="lazy"
            decoding="async"
          />
        ) : source.media_type === "audio" ? <AssetsIcon /> : <VideoIcon />}
      </span>
      <span>
        <strong>{source.display_name}</strong>
        <em>{source.media_type === "audio" ? "BGM" : "video"}{source.duration_seconds ? ` · ${formatTime(source.duration_seconds)}` : ""}</em>
      </span>
      <PlusIcon />
    </button>
  );
}

function IconButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      className="v2-composition-icon-button"
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

function hasMarkedBgm(timeline: V2FinalCompositionTimeline) {
  return timeline.tracks.some((track) => {
    if (track.track_type !== "audio") return false;
    const editor = recordValue(track.metadata.editor);
    if (editor.bgm === true || editor.role === "bgm" || track.metadata.role === "bgm") return true;
    return timeline.clips.some((clip) => clip.track_id === track.track_id
      && (clip.metadata.role === "bgm" || recordValue(clip.metadata.editor).bgm === true));
  });
}

function recordValue(value: unknown) {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function formatTime(value: number) {
  const minutes = Math.floor(Math.max(0, value) / 60);
  const seconds = Math.floor(Math.max(0, value) % 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}
