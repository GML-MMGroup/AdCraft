import { useEffect, useId, useRef, type PointerEvent } from "react";
import { createPortal } from "react-dom";

import { CloseIcon } from "../../../icons.tsx";
import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import "./AgentCanvasVideoPreviewDialog.css";

export interface AgentCanvasVideoPreviewDialogProps {
  asset: ProjectAssetSummaryV2;
  title: string;
  onClose: () => void;
}

export function AgentCanvasVideoPreviewDialog({
  asset,
  title,
  onClose,
}: AgentCanvasVideoPreviewDialogProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!asset.media_url) return;
    const dialog = dialogRef.current;
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    if (dialog && !dialog.open) {
      if (typeof dialog.showModal === "function") {
        dialog.showModal();
      } else {
        dialog.setAttribute("open", "");
      }
    }
    const focusFrame = window.requestAnimationFrame(() => closeButtonRef.current?.focus());
    const closeFromKeyboard = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClose();
    };
    document.addEventListener("keydown", closeFromKeyboard);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", closeFromKeyboard);
      document.body.style.overflow = previousOverflow;
      if (dialog?.open) {
        if (typeof dialog.close === "function") dialog.close();
        else dialog.removeAttribute("open");
      }
      previousFocus?.focus({ preventScroll: true });
    };
  }, [asset.media_url, onClose]);

  if (!asset.media_url) return null;

  const dismissFromBackdrop = (event: PointerEvent<HTMLDialogElement>) => {
    if (event.target === event.currentTarget) onClose();
  };

  return createPortal(
    <dialog
      ref={dialogRef}
      className="agent-canvas-video-preview"
      aria-labelledby={titleId}
      aria-modal="true"
      onPointerDown={dismissFromBackdrop}
    >
      <h2 id={titleId} className="sr-only">{title}</h2>
      <button
        ref={closeButtonRef}
        className="agent-canvas-video-preview__close"
        type="button"
        aria-label="Close video preview"
        title="Close"
        onClick={onClose}
      >
        <CloseIcon />
      </button>
      <div className="agent-canvas-video-preview__stage">
        <video
          className="agent-canvas-video-preview__player"
          src={asset.media_url}
          poster={asset.preview_url ?? undefined}
          aria-label={`${title} player`}
          controls
          autoPlay
          playsInline
          preload="auto"
        />
      </div>
    </dialog>,
    document.body,
  );
}
