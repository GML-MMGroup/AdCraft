import { useEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";

import { ChevronDownIcon, ChevronUpIcon, CloseIcon } from "../../icons.tsx";
import { v2AssetMediaUrl } from "./v2AssetLibraryModel.ts";
import type { V2AssetLibraryEntityDetail, V2AssetLibraryMember } from "../../types-v2.ts";

export interface AssetEntityViewerProps {
  detail: V2AssetLibraryEntityDetail | null;
  loading: boolean;
  onClose: () => void;
}

export default function AssetEntityViewer({
  detail,
  loading,
  onClose,
}: AssetEntityViewerProps) {
  const [activeMemberIndex, setActiveMemberIndex] = useState(0);
  const dialogRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

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
  const hasMultipleMembers = members.length > 1;
  const activeMemberLabel = activeMember ? assetMemberLabel(activeMember) : "No asset media";
  const selectPreviousMember = () => setActiveMemberIndex((index) => (index - 1 + members.length) % members.length);
  const selectNextMember = () => setActiveMemberIndex((index) => (index + 1) % members.length);

  return createPortal(
    <div className="v2-asset-viewer-backdrop">
      <button className="v2-asset-viewer-dismiss" type="button" aria-label="Dismiss asset viewer" onClick={onClose} />
      <section className="v2-asset-viewer" role="dialog" aria-modal="true" aria-label={detail.display_name} ref={dialogRef}>
        <button className="v2-asset-viewer-close" ref={closeButtonRef} type="button" aria-label="Close asset viewer" title="Close" onClick={onClose}><CloseIcon /></button>
        <div className="v2-asset-viewer-stage">
          {activeMember ? <AssetMedia url={v2AssetMediaUrl(activeMember)} mediaType={activeMember.media_type} label={activeMemberLabel} presentation="viewer" /> : <span className="v2-asset-viewer-empty">No media is available for this asset.</span>}
          {hasMultipleMembers ? <button className="v2-asset-viewer-nav is-previous" type="button" aria-label="Previous asset view" title="Previous asset view" onClick={selectPreviousMember}><ChevronUpIcon /></button> : null}
          {hasMultipleMembers ? <button className="v2-asset-viewer-nav is-next" type="button" aria-label="Next asset view" title="Next asset view" onClick={selectNextMember}><ChevronDownIcon /></button> : null}
        </div>
      </section>
    </div>,
    document.body,
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
  return createPortal(
    <div className="v2-asset-viewer-backdrop">
      <button className="v2-asset-viewer-dismiss" type="button" aria-label="Dismiss asset viewer" onClick={onClose} />
      <section className="v2-asset-viewer" role="dialog" aria-modal="true" aria-label="Asset viewer" ref={dialogRef}>
        <button className="v2-asset-viewer-close" ref={closeButtonRef} type="button" aria-label="Close asset viewer" title="Close" onClick={onClose}><CloseIcon /></button>
        <div className="v2-asset-viewer-stage is-loading">Loading asset details...</div>
      </section>
    </div>,
    document.body,
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
