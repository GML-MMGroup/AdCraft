import { useEffect, useId, useLayoutEffect, useRef, useState, type PointerEvent } from "react";
import { createPortal } from "react-dom";

import { CloseIcon } from "../../../icons.tsx";
import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import {
  fitVideoDimensionsWithinStage,
  type StageDimensions,
  type VideoDimensions,
} from "./agentCanvasVideoPreviewSizing.ts";
import { useAgentCanvasVideoPoster } from "./useAgentCanvasVideoPoster.ts";
import "./AgentCanvasVideoPreviewDialog.css";

export interface AgentCanvasVideoPreviewDialogProps {
  asset: ProjectAssetSummaryV2;
  title: string;
  onClose: () => void;
}

const FALLBACK_VIDEO_DIMENSIONS: VideoDimensions = {
  width: 16,
  height: 9,
};

function readVideoDimensions(asset: ProjectAssetSummaryV2): VideoDimensions {
  if (
    typeof asset.width === "number" &&
    Number.isFinite(asset.width) &&
    asset.width > 0 &&
    typeof asset.height === "number" &&
    Number.isFinite(asset.height) &&
    asset.height > 0
  ) {
    return { width: asset.width, height: asset.height };
  }
  return FALLBACK_VIDEO_DIMENSIONS;
}

function orientationFor({ width, height }: VideoDimensions) {
  if (width === height) return "square";
  return width < height ? "portrait" : "landscape";
}

export function AgentCanvasVideoPreviewDialog({
  asset,
  title,
  onClose,
}: AgentCanvasVideoPreviewDialogProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<HTMLVideoElement>(null);
  const [intrinsicDimensions, setIntrinsicDimensions] = useState<{
    assetId: string;
    dimensions: VideoDimensions;
  } | null>(null);
  const [stageDimensions, setStageDimensions] = useState<StageDimensions>({ width: 0, height: 0 });
  const videoPosterUrl = useAgentCanvasVideoPoster(asset, playerRef);

  const declaredDimensions = readVideoDimensions(asset);
  const dimensions = intrinsicDimensions?.assetId === asset.asset_id
    ? intrinsicDimensions.dimensions
    : declaredDimensions;
  const orientation = orientationFor(dimensions);
  const playerDimensions = fitVideoDimensionsWithinStage(dimensions, stageDimensions);
  const playerStyle = playerDimensions
    ? {
      width: `${playerDimensions.width}px`,
      height: `${playerDimensions.height}px`,
    }
    : undefined;

  useLayoutEffect(() => {
    const stage = stageRef.current;
    if (!stage) return undefined;

    const updateStageDimensions = () => {
      const bounds = stage.getBoundingClientRect();
      const next = {
        width: Math.round(bounds.width),
        height: Math.round(bounds.height),
      };
      setStageDimensions((current) => (
        current.width === next.width && current.height === next.height ? current : next
      ));
    };

    updateStageDimensions();
    const observer = typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(updateStageDimensions);
    observer?.observe(stage);
    window.addEventListener("resize", updateStageDimensions);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", updateStageDimensions);
    };
  }, []);

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
      <div
        ref={stageRef}
        className="agent-canvas-video-preview__stage"
        data-orientation={orientation}
      >
        <video
          ref={playerRef}
          className="agent-canvas-video-preview__player"
          src={asset.media_url}
          poster={asset.preview_url ?? videoPosterUrl ?? undefined}
          aria-label={`${title} player`}
          controls
          autoPlay
          playsInline
          preload="auto"
          style={playerStyle}
          onLoadedMetadata={({ currentTarget }) => {
            if (currentTarget.videoWidth <= 0 || currentTarget.videoHeight <= 0) return;
            setIntrinsicDimensions({
              assetId: asset.asset_id,
              dimensions: {
                width: currentTarget.videoWidth,
                height: currentTarget.videoHeight,
              },
            });
          }}
        />
      </div>
    </dialog>,
    document.body,
  );
}
