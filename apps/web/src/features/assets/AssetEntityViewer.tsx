import { useEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";

import { ChevronLeftIcon, ChevronRightIcon, CloseIcon } from "../../icons.tsx";
import { v2AssetMediaUrl, v2AssetPreviewUrl } from "./v2AssetLibraryModel.ts";
import type { V2AssetLibraryEntityDetail, V2AssetLibraryMember } from "../../types-v2.ts";

export interface AssetEntityViewerProps {
  detail: V2AssetLibraryEntityDetail | null;
  loading: boolean;
  hasEntityNavigation?: boolean;
  onPreviousEntity?: () => void;
  onNextEntity?: () => void;
  onClose: () => void;
}

export default function AssetEntityViewer({
  detail,
  loading,
  hasEntityNavigation = false,
  onPreviousEntity,
  onNextEntity,
  onClose,
}: AssetEntityViewerProps) {
  const [activeMemberSelection, setActiveMemberSelection] = useState<{ entityId: string; memberId: string } | null>(null);
  const dialogRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeFromKeyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (!shouldIgnoreGalleryShortcut(event.target) && hasEntityNavigation && event.key === "ArrowLeft") {
        event.preventDefault();
        onPreviousEntity?.();
        return;
      }
      if (!shouldIgnoreGalleryShortcut(event.target) && hasEntityNavigation && event.key === "ArrowRight") {
        event.preventDefault();
        onNextEntity?.();
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
  }, [hasEntityNavigation, onClose, onNextEntity, onPreviousEntity]);

  if (loading || !detail) {
    return (
      <AssetEntityViewerLoading
        dialogRef={dialogRef}
        closeButtonRef={closeButtonRef}
        hasEntityNavigation={hasEntityNavigation}
        onPreviousEntity={onPreviousEntity}
        onNextEntity={onNextEntity}
        onClose={onClose}
      />
    );
  }

  const members = detail.members;
  const primaryMemberIndex = Math.max(0, members.findIndex((member) => member.is_primary));
  const selectedMemberIndex = activeMemberSelection?.entityId === detail.entity_id
    ? members.findIndex((member) => member.member_id === activeMemberSelection.memberId)
    : -1;
  const activeMemberIndex = selectedMemberIndex >= 0 ? selectedMemberIndex : primaryMemberIndex;
  const activeMember = members[activeMemberIndex] ?? null;
  const activeMemberLabel = activeMember ? assetMemberLabel(activeMember) : "No asset media";
  const characterViews = detail.entity_type === "character"
    ? members
      .map((member, memberIndex) => ({ member, memberIndex }))
      .filter(({ member }) => member.media_type === "image")
    : [];
  const showCharacterViews = characterViews.length > 1;

  return createPortal(
    <div className="v2-asset-viewer-backdrop">
      <button className="v2-asset-viewer-dismiss" type="button" aria-label="Dismiss asset viewer" onClick={onClose} />
      <section className={`v2-asset-viewer ${showCharacterViews ? "has-thumbnails" : ""}`} role="dialog" aria-modal="true" aria-label={detail.display_name} ref={dialogRef}>
        <button className="v2-asset-viewer-close" ref={closeButtonRef} type="button" aria-label="Close asset viewer" title="Close" onClick={onClose}><CloseIcon /></button>
        <div className="v2-asset-viewer-stage">
          {activeMember ? <AssetMedia url={v2AssetMediaUrl(activeMember)} mediaType={activeMember.media_type} label={activeMemberLabel} presentation="viewer" /> : <span className="v2-asset-viewer-empty">No media is available for this asset.</span>}
          <AssetEntityNavigation
            visible={hasEntityNavigation}
            onPrevious={onPreviousEntity}
            onNext={onNextEntity}
          />
        </div>
        {showCharacterViews ? (
          <div className="v2-asset-viewer-thumbnails" role="group" aria-label="Character views">
            {characterViews.map(({ member, memberIndex }) => {
              const label = assetMemberLabel(member);
              const previewUrl = v2AssetPreviewUrl(member);
              return (
                <button
                  key={member.member_id}
                  className={memberIndex === activeMemberIndex ? "is-active" : ""}
                  type="button"
                  aria-label={`Show ${label}`}
                  aria-pressed={memberIndex === activeMemberIndex}
                  title={label}
                  onClick={() => setActiveMemberSelection({ entityId: detail.entity_id, memberId: member.member_id })}
                >
                  {previewUrl
                    ? <img src={previewUrl} alt="" loading="lazy" decoding="async" />
                    : <span>{label.slice(0, 1).toUpperCase()}</span>}
                </button>
              );
            })}
          </div>
        ) : null}
        {activeMember ? <span className="sr-only" aria-live="polite" aria-atomic="true">{activeMemberLabel}, view {activeMemberIndex + 1} of {members.length}</span> : null}
      </section>
    </div>,
    document.body,
  );
}

export function AssetEntityViewerLoading({
  dialogRef,
  closeButtonRef,
  hasEntityNavigation = false,
  onPreviousEntity,
  onNextEntity,
  onClose,
}: {
  dialogRef?: RefObject<HTMLElement | null>;
  closeButtonRef?: RefObject<HTMLButtonElement | null>;
  hasEntityNavigation?: boolean;
  onPreviousEntity?: () => void;
  onNextEntity?: () => void;
  onClose: () => void;
}) {
  return createPortal(
    <div className="v2-asset-viewer-backdrop">
      <button className="v2-asset-viewer-dismiss" type="button" aria-label="Dismiss asset viewer" onClick={onClose} />
      <section className="v2-asset-viewer" role="dialog" aria-modal="true" aria-label="Asset viewer" ref={dialogRef}>
        <button className="v2-asset-viewer-close" ref={closeButtonRef} type="button" aria-label="Close asset viewer" title="Close" onClick={onClose}><CloseIcon /></button>
        <div className="v2-asset-viewer-stage is-loading">
          Loading asset details...
          <AssetEntityNavigation
            visible={hasEntityNavigation}
            onPrevious={onPreviousEntity}
            onNext={onNextEntity}
          />
        </div>
      </section>
    </div>,
    document.body,
  );
}

function AssetEntityNavigation({
  visible,
  onPrevious,
  onNext,
}: {
  visible: boolean;
  onPrevious?: () => void;
  onNext?: () => void;
}) {
  if (!visible) return null;
  return (
    <>
      <button className="v2-asset-viewer-nav is-previous" type="button" aria-label="Previous asset" title="Previous asset" onClick={onPrevious}><ChevronLeftIcon /></button>
      <button className="v2-asset-viewer-nav is-next" type="button" aria-label="Next asset" title="Next asset" onClick={onNext}><ChevronRightIcon /></button>
    </>
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

function shouldIgnoreGalleryShortcut(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  return target.matches("input, textarea, select, video, audio, [contenteditable='true']");
}

function AssetMedia({ url, mediaType, label, presentation = "detail" }: { url: string | null; mediaType?: string | null; label: string; presentation?: "detail" | "thumbnail" | "viewer" }) {
  if (!url) return <span className="v2-asset-media is-empty">{label.slice(0, 1).toUpperCase()}</span>;
  if (mediaType === "video") return <video className="v2-asset-media" src={url} preload="metadata" muted playsInline controls={presentation === "viewer"} tabIndex={presentation === "viewer" ? 0 : undefined} />;
  if (mediaType === "audio") return presentation === "thumbnail" ? <span className="v2-asset-media is-empty">Audio</span> : <audio className="v2-asset-audio" src={url} controls preload="metadata" tabIndex={presentation === "viewer" ? 0 : undefined} />;
  return <img className="v2-asset-media" src={url} alt={presentation === "thumbnail" ? "" : label} loading={presentation === "thumbnail" ? "lazy" : "eager"} decoding="async" />;
}
