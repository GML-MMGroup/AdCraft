import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

import { ChevronLeftIcon, ChevronRightIcon, CloseIcon } from "../../icons.tsx";
import type { AgentAssetBrowserItem } from "../agent-canvas/assets/assetSelection.ts";
import { mediaAssetContentPath } from "../../workflow/mediaPreview.ts";
import { StableMediaPreview } from "../../workflow/StableMediaPreview.tsx";

interface CanonicalAssetViewerProps {
  item: AgentAssetBrowserItem;
  hasAssetNavigation: boolean;
  onPreviousAsset: () => void;
  onNextAsset: () => void;
  onClose: () => void;
}

export function CanonicalAssetViewer({
  item,
  hasAssetNavigation,
  onPreviousAsset,
  onNextAsset,
  onClose,
}: CanonicalAssetViewerProps) {
  const viewerRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const source = item.projectAsset
    ? mediaAssetContentPath(item.projectAsset) || item.mediaUrl || item.previewUrl
    : item.mediaUrl ?? item.previewUrl;

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKeyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (hasAssetNavigation && event.key === "ArrowLeft") {
        event.preventDefault();
        onPreviousAsset();
        return;
      }
      if (hasAssetNavigation && event.key === "ArrowRight") {
        event.preventDefault();
        onNextAsset();
        return;
      }
      if (event.key === "Tab") trapFocus(event, viewerRef.current);
    };

    document.addEventListener("keydown", handleKeyboard);
    const focusFrame = requestAnimationFrame(() => closeButtonRef.current?.focus());
    return () => {
      cancelAnimationFrame(focusFrame);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyboard);
    };
  }, [hasAssetNavigation, onClose, onNextAsset, onPreviousAsset]);

  return createPortal(
    <div className="v2-asset-viewer-backdrop">
      <button className="v2-asset-viewer-dismiss" type="button" aria-label="Dismiss asset viewer" onClick={onClose} />
      <section className="v2-asset-viewer" role="dialog" aria-modal="true" aria-label={item.displayName} ref={viewerRef}>
        <button className="v2-asset-viewer-close" ref={closeButtonRef} type="button" aria-label="Close asset viewer" title="Close" onClick={onClose}><CloseIcon /></button>
        <div className="v2-asset-viewer-stage">
          {source
            ? <StableMediaPreview className="v2-asset-media" src={source} alt={item.displayName} loading="eager" decoding="async" />
            : <span className="v2-asset-viewer-empty">No image is available for this asset.</span>}
          {hasAssetNavigation ? (
            <>
              <button className="v2-asset-viewer-nav is-previous" type="button" aria-label="Previous asset" title="Previous asset" onClick={onPreviousAsset}><ChevronLeftIcon /></button>
              <button className="v2-asset-viewer-nav is-next" type="button" aria-label="Next asset" title="Next asset" onClick={onNextAsset}><ChevronRightIcon /></button>
            </>
          ) : null}
        </div>
      </section>
    </div>,
    document.body,
  );
}

function trapFocus(event: KeyboardEvent, viewer: HTMLElement | null) {
  if (!viewer) return;
  const focusable = [...viewer.querySelectorAll<HTMLElement>("button:not([disabled])")];
  if (!focusable.length) return;
  const currentIndex = focusable.indexOf(document.activeElement as HTMLElement);
  const nextIndex = event.shiftKey
    ? currentIndex <= 0 ? focusable.length - 1 : currentIndex - 1
    : currentIndex === focusable.length - 1 ? 0 : currentIndex + 1;
  event.preventDefault();
  focusable[nextIndex]?.focus();
}
