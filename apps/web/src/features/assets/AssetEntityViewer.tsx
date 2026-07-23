import { useEffect, useRef, useState, type RefObject } from "react";

import { ChevronDownIcon, ChevronUpIcon, CloseIcon } from "../../icons.tsx";
import { v2AssetMediaUrl, v2AssetPreviewUrl } from "./v2AssetLibraryModel.ts";
import type { V2AssetLibraryEntityDetail, V2AssetLibraryMember } from "../../types-v2.ts";

export interface AssetEntityViewerProps {
  detail: V2AssetLibraryEntityDetail | null;
  loading: boolean;
  feedback: string | null;
  onClose: () => void;
  onUpdate: (request: { display_name?: string; description?: string | null; tags?: string[]; is_favorite?: boolean }) => Promise<void>;
  onTrash: () => void;
  onRestore: () => void;
  splitTags: (value: string) => string[];
}

export default function AssetEntityViewer({
  detail,
  loading,
  feedback,
  onClose,
  onUpdate,
  onTrash,
  onRestore,
  splitTags,
}: AssetEntityViewerProps) {
  const [draft, setDraft] = useState({ displayName: "", description: "", tags: "" });
  const [activeMemberIndex, setActiveMemberIndex] = useState(0);
  const dialogRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    setDraft({ displayName: detail?.display_name ?? "", description: detail?.description ?? "", tags: detail?.tags.join(", ") ?? "" });
  }, [detail]);

  useEffect(() => {
    if (!detail) return;
    const primaryIndex = detail.members.findIndex((member) => member.is_primary);
    setActiveMemberIndex(primaryIndex >= 0 ? primaryIndex : 0);
  }, [detail]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeFromKeyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key === "Tab") trapViewerFocus(event, dialogRef.current);
    };
    document.addEventListener("keydown", closeFromKeyboard);
    const focusFrame = requestAnimationFrame(() => closeButtonRef.current?.focus());
    return () => {
      cancelAnimationFrame(focusFrame);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", closeFromKeyboard);
    };
  }, [onClose]);

  if (loading || !detail) {
    return <AssetEntityViewerLoading dialogRef={dialogRef} closeButtonRef={closeButtonRef} onClose={onClose} />;
  }

  const members = detail.members;
  const activeMember = members[activeMemberIndex] ?? null;
  const isRecommended = detail.scope === "recommended";
  const trashed = detail.status === "trashed";
  const hasMultipleMembers = members.length > 1;
  const activeMemberLabel = activeMember ? assetMemberLabel(activeMember) : "No asset media";
  const selectPreviousMember = () => setActiveMemberIndex((index) => (index - 1 + members.length) % members.length);
  const selectNextMember = () => setActiveMemberIndex((index) => (index + 1) % members.length);

  return (
    <div className="v2-asset-viewer-backdrop">
      <button className="v2-asset-viewer-dismiss" type="button" aria-label="Close asset viewer" onClick={onClose} />
      <section className="v2-asset-viewer" role="dialog" aria-modal="true" aria-labelledby="v2-asset-viewer-title" ref={dialogRef}>
        <header className="v2-asset-viewer-heading">
          <div><small>{detail.library_category}</small><h2 id="v2-asset-viewer-title">{detail.display_name}</h2></div>
          <button className="icon-btn" ref={closeButtonRef} type="button" aria-label="Close asset viewer" onClick={onClose}><CloseIcon /></button>
        </header>
        <div className="v2-asset-viewer-stage">
          {activeMember ? <AssetMedia url={v2AssetMediaUrl(activeMember)} mediaType={activeMember.media_type} label={activeMemberLabel} presentation="viewer" /> : <span className="v2-asset-viewer-empty">No media is available for this asset.</span>}
          {hasMultipleMembers ? <button className="v2-asset-viewer-nav is-previous" type="button" aria-label="Previous asset view" title="Previous asset view" onClick={selectPreviousMember}><ChevronUpIcon /></button> : null}
          {hasMultipleMembers ? <button className="v2-asset-viewer-nav is-next" type="button" aria-label="Next asset view" title="Next asset view" onClick={selectNextMember}><ChevronDownIcon /></button> : null}
        </div>
        {members.length ? <div className="v2-asset-viewer-thumbnails" aria-label="Asset views">{members.map((member, index) => {
          const label = assetMemberLabel(member);
          return <button key={member.member_id} className={`v2-asset-viewer-thumbnail ${index === activeMemberIndex ? "is-active" : ""}`} type="button" aria-label={`View ${label}`} aria-pressed={index === activeMemberIndex} onClick={() => setActiveMemberIndex(index)}><AssetMedia url={v2AssetPreviewUrl(member)} mediaType={member.media_type} label={label} presentation="thumbnail" /><span>{label}</span></button>;
        })}</div> : null}
        <div className="v2-asset-viewer-details">
          {detail.description ? <p className="v2-asset-detail-description">{detail.description}</p> : null}
          {isRecommended ? (
            <dl className="v2-asset-provenance">
              <div><dt>Source</dt><dd>{detail.catalog_source_url ?? "Catalog"}</dd></div>
              <div><dt>License</dt><dd>{detail.license_id ?? "Not specified"}</dd></div>
              <div><dt>Attribution</dt><dd>{detail.attribution ?? "Not specified"}</dd></div>
            </dl>
          ) : (
            <form className="v2-asset-detail-form" onSubmit={(event) => { event.preventDefault(); void onUpdate({ display_name: draft.displayName.trim(), description: draft.description.trim() || null, tags: splitTags(draft.tags) }); }}>
              <label><span>Name</span><input value={draft.displayName} onChange={(event) => setDraft((value) => ({ ...value, displayName: event.currentTarget.value }))} /></label>
              <label><span>Description</span><textarea value={draft.description} onChange={(event) => setDraft((value) => ({ ...value, description: event.currentTarget.value }))} /></label>
              <label><span>Tags</span><input value={draft.tags} onChange={(event) => setDraft((value) => ({ ...value, tags: event.currentTarget.value }))} /></label>
              <div className="v2-asset-detail-actions">
                <button className="small-action" type="button" aria-pressed={detail.is_favorite} onClick={() => void onUpdate({ is_favorite: !detail.is_favorite })}>{detail.is_favorite ? "Unfavorite" : "Favorite"}</button>
                <button className="small-action" type="submit">Save</button>
                {trashed ? <button className="small-action" type="button" onClick={onRestore}>Restore</button> : <button className="small-action is-danger" type="button" onClick={onTrash}>Move to Trash</button>}
              </div>
            </form>
          )}
          {feedback ? <p className="v2-asset-library-feedback">{feedback}</p> : null}
        </div>
      </section>
    </div>
  );
}

export function AssetEntityViewerLoading({
  dialogRef,
  closeButtonRef,
  onClose,
}: {
  dialogRef?: RefObject<HTMLElement | null>;
  closeButtonRef?: RefObject<HTMLButtonElement | null>;
  onClose: () => void;
}) {
  return (
    <div className="v2-asset-viewer-backdrop">
      <button className="v2-asset-viewer-dismiss" type="button" aria-label="Close asset viewer" onClick={onClose} />
      <section className="v2-asset-viewer" role="dialog" aria-modal="true" aria-label="Asset viewer" ref={dialogRef}>
        <header className="v2-asset-viewer-heading"><h2>Loading asset...</h2><button className="icon-btn" ref={closeButtonRef} type="button" aria-label="Close asset viewer" onClick={onClose}><CloseIcon /></button></header>
        <div className="v2-asset-viewer-stage is-loading">Loading asset details...</div>
      </section>
    </div>
  );
}

function assetMemberLabel(member: V2AssetLibraryMember) {
  return member.display_name || member.semantic_type.replaceAll("_", " ");
}

function trapViewerFocus(event: KeyboardEvent, viewer: HTMLElement | null) {
  if (event.key !== "Tab" || !viewer) return;
  const focusable = [...viewer.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), video[controls], audio[controls], [href]')];
  if (!focusable.length) return;
  const currentIndex = focusable.indexOf(document.activeElement as HTMLElement);
  const nextIndex = event.shiftKey ? currentIndex <= 0 ? focusable.length - 1 : currentIndex - 1 : currentIndex === focusable.length - 1 ? 0 : currentIndex + 1;
  event.preventDefault();
  focusable[nextIndex]?.focus();
}

function AssetMedia({ url, mediaType, label, presentation = "detail" }: { url: string | null; mediaType?: string | null; label: string; presentation?: "detail" | "thumbnail" | "viewer" }) {
  if (!url) return <span className="v2-asset-media is-empty">{label.slice(0, 1).toUpperCase()}</span>;
  if (mediaType === "video") return <video className="v2-asset-media" src={url} preload="metadata" muted playsInline controls={presentation === "viewer"} tabIndex={presentation === "viewer" ? 0 : undefined} />;
  if (mediaType === "audio") return presentation === "thumbnail" ? <span className="v2-asset-media is-empty">Audio</span> : <audio className="v2-asset-audio" src={url} controls preload="metadata" tabIndex={presentation === "viewer" ? 0 : undefined} />;
  return <img className="v2-asset-media" src={url} alt={presentation === "thumbnail" ? "" : label} loading={presentation === "thumbnail" ? "lazy" : "eager"} decoding="async" />;
}
