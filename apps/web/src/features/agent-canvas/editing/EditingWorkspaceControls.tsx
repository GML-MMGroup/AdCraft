import { useEffect, useRef, useState, type ReactNode } from "react";
import { CloseIcon, FitIcon, PlusIcon, TrashIcon, VideoIcon } from "../../../icons.tsx";
import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import type { EditingInputs } from "./editingModel.ts";
import { useEditingText } from "./editingMessages.ts";
import { mediaAssetCanvasPosterRenditionPath } from "../../../workflow/mediaPreview.ts";

export function EditingTimelineToolbar({
  zoom, onZoom, snapping, onSnapping, onSources, onRemove, onTrim, canRemove, canTrimStart, canTrimEnd, busy,
}: {
  zoom: number; onZoom: (zoom: number) => void; snapping: boolean; onSnapping: () => void;
  onSources: () => void; onRemove: () => void; onTrim: (edge: "start" | "end") => void;
  canRemove: boolean; canTrimStart: boolean; canTrimEnd: boolean; busy: boolean;
}) {
  const t = useEditingText();
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  return <div className="editing-tools">
    <div className="editing-tools__group" role="toolbar" aria-label={t("Timeline")}>
      <button type="button" onClick={onSources}><PlusIcon/><span>{t("Sources")}</span></button>
      <button type="button" title={`${t("Trim start to playhead")} ([)`} aria-label={t("Trim start to playhead")} disabled={busy || !canTrimStart} onClick={() => onTrim("start")}><span className="editing-tools__trim-icon" aria-hidden="true">[</span></button>
      <button type="button" title={`${t("Trim end to playhead")} (])`} aria-label={t("Trim end to playhead")} disabled={busy || !canTrimEnd} onClick={() => onTrim("end")}><span className="editing-tools__trim-icon" aria-hidden="true">]</span></button>
      <button type="button" title={`${t("Remove clip")} (Delete)`} aria-label={t("Remove clip")} disabled={busy || !canRemove} onClick={onRemove}><TrashIcon/></button>
      <span className="editing-tools__separator" aria-hidden="true"/>
      <button type="button" aria-pressed={snapping} title={`${t("Snapping")} (S)`} onClick={onSnapping}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M5 4v9a7 7 0 0 0 14 0V4h-4v9a3 3 0 0 1-6 0V4Z"/><path d="M5 8h4m6 0h4"/></svg><span>{t("Snapping")}</span>
      </button>
    </div>
    <div className="editing-tools__group editing-tools__zoom" role="group" aria-label={t("Timeline zoom")}>
      <button type="button" aria-label={t("Zoom out")} title={t("Zoom out")} disabled={zoom <= 1} onClick={() => onZoom(Math.max(1, zoom / 1.5))}>−</button>
      <input aria-label={t("Timeline zoom")} type="range" min="1" max="16" step="0.25" value={zoom} onChange={event => onZoom(Number(event.currentTarget.value))}/>
      <button type="button" aria-label={t("Zoom in")} title={t("Zoom in")} disabled={zoom >= 16} onClick={() => onZoom(Math.min(16, zoom * 1.5))}><PlusIcon/></button>
      <button type="button" className="editing-tools__fit" title={t("Fit timeline")} aria-label={t("Fit timeline")} onClick={() => onZoom(1)}><FitIcon/><span>{zoom === 1 ? t("Fit timeline") : `${Math.round(zoom * 100)}%`}</span></button>
      <button type="button" aria-label={t("Shortcuts")} title={t("Shortcuts")} aria-expanded={shortcutsOpen} onClick={() => setShortcutsOpen(value => !value)}>?</button>
    </div>
    {shortcutsOpen ? <div className="editing-tools__shortcuts" role="region" aria-label={t("Shortcuts")}>
      <button type="button" aria-label={t("Close panel")} onClick={() => setShortcutsOpen(false)}><CloseIcon/></button>
      {[["Playback", "Space"], ["Step one frame", "← / →"], ["Remove selected clip", "Delete"], ["Trim to playhead", "[ / ]"], ["Snapping", "S"]].map(([label, key]) => <div key={label}><span>{t(label!)}</span><kbd>{key}</kbd></div>)}
    </div> : null}
  </div>;
}

export function EditingInspector({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const t = useEditingText();
  return <aside className="editing-inspector" aria-label={title}>
    <header><h3>{title}</h3><button type="button" aria-label={t("Close panel")} onClick={onClose}><CloseIcon/></button></header>
    <div className="editing-inspector__body">{children}</div>
  </aside>;
}

export function EditingSourceList({ inputs, assets, selected, busy, onSelect, onAdd }: {
  inputs: EditingInputs; assets: ProjectAssetSummaryV2[]; selected: string | null; busy: boolean;
  onSelect: (referenceId: string) => void; onAdd: (referenceId: string) => void;
}) {
  const t = useEditingText();
  return <div className="editing-sources">
    {assets.map(asset => {
      const input = inputs.videos.find(item => item.asset?.asset_id === asset.asset_id);
      const poster = mediaAssetCanvasPosterRenditionPath(asset);
      const onTimeline = Boolean(input?.entry.enabled);
      const available = asset.status === "ready";
      return <article className={`editing-sources__item${input?.referenceId === selected ? " is-selected" : ""}`} key={asset.asset_id}>
        <button type="button" className="editing-sources__select" disabled={!input} onClick={() => input && onSelect(input.referenceId)}>
          <span className="editing-sources__poster">{poster && !/\.(mp4|webm)(?:\?|$)/i.test(poster) ? <img src={poster} alt="" loading="lazy"/> : <VideoIcon/>}</span>
          <span className="editing-sources__copy"><strong>{input?.node?.title || asset.display_name}</strong><small>{(asset.duration_seconds ?? 0).toFixed(1)}s · {asset.width ?? "—"} × {asset.height ?? "—"}</small></span>
        </button>
        <div className="editing-sources__status"><span>{t(!available ? "Source unavailable" : onTimeline ? "On timeline" : "Not on timeline")}</span>{!onTimeline ? <button type="button" disabled={busy || !input || !available} onClick={() => input && onAdd(input.referenceId)}><PlusIcon/>{t("Restore clip")}</button> : <span aria-hidden="true">✓</span>}</div>
      </article>;
    })}
  </div>;
}

export function EditingWorkspaceDivider({ value, onChange }: { value: number; onChange: (value: number) => void }) {
  const t = useEditingText();
  const cleanupRef = useRef<(() => void) | null>(null);
  useEffect(() => () => cleanupRef.current?.(), []);
  // WAI-ARIA window splitters are focusable separators with keyboard resizing.
  // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex
  return <div className="editing-workspace-divider" role="separator" aria-label={t("Resize preview and timeline")} aria-orientation="horizontal" aria-valuemin={35} aria-valuemax={75} aria-valuenow={value} tabIndex={0}
    onKeyDown={event => {
      if (event.key === "ArrowUp" || event.key === "ArrowDown") { event.preventDefault(); onChange(Math.max(35, Math.min(75, value + (event.key === "ArrowUp" ? -5 : 5)))); }
    }}
    onPointerDown={event => {
      if (event.button !== 0) return;
      event.preventDefault();
      const bounds = event.currentTarget.parentElement!.getBoundingClientRect();
      const pointerId = event.pointerId;
      const move = (e: PointerEvent) => { if (e.pointerId === pointerId) onChange(Math.max(35, Math.min(75, (e.clientY - bounds.top) / bounds.height * 100))); };
      const cleanup = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", finish); window.removeEventListener("pointercancel", finish); cleanupRef.current = null; };
      const finish = (e: PointerEvent) => { if (e.pointerId === pointerId) cleanup(); };
      cleanupRef.current?.(); cleanupRef.current = cleanup;
      window.addEventListener("pointermove", move); window.addEventListener("pointerup", finish); window.addEventListener("pointercancel", finish);
    }}><span/></div>;
}
