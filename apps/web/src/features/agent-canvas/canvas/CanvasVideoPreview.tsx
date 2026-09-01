import { useEffect, useRef, useState } from "react";

import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import { mediaAssetContentPath, mediaAssetPosterRenditionPath } from "../../../workflow/mediaPreview.ts";
import { StableMediaPreview } from "../../../workflow/StableMediaPreview.tsx";
import { acquireCanvasVideoPreviewLoad } from "./canvasVideoPreviewScheduler.ts";
import { requestNativeVideoFirstFrame } from "./nativeVideoFirstFrame.ts";
import { useAgentCanvasVideoPoster } from "./useAgentCanvasVideoPoster.ts";

interface CanvasVideoPreviewProps {
  asset: ProjectAssetSummaryV2;
  label: string;
  onMediaDimensionsResolved?: (dimensions: { width: number; height: number }) => void;
}

export function CanvasVideoPreview({
  asset,
  label,
  onMediaDimensionsResolved,
}: CanvasVideoPreviewProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const releaseLoadRef = useRef<(() => void) | null>(null);
  const [eligible, setEligible] = useState(false);
  const [activated, setActivated] = useState(false);
  const posterUrl = useAgentCanvasVideoPoster(asset, videoRef);
  const backendPosterUrl = mediaAssetPosterRenditionPath(asset);
  const mediaUrl = mediaAssetContentPath(asset);

  useEffect(() => {
    const element = videoRef.current;
    if (!element || eligible) return;

    if (typeof IntersectionObserver === "undefined") {
      setEligible(true);
      return;
    }

    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setEligible(true);
        observer.disconnect();
      }
    }, { rootMargin: "240px" });
    observer.observe(element);
    return () => observer.disconnect();
  }, [eligible]);

  useEffect(() => {
    if (!eligible) return;
    let cancelled = false;
    void acquireCanvasVideoPreviewLoad().then((release) => {
      if (cancelled) {
        release();
        return;
      }
      releaseLoadRef.current = release;
      setActivated(true);
    });
    return () => {
      cancelled = true;
      releaseLoadRef.current?.();
      releaseLoadRef.current = null;
    };
  }, [eligible]);

  useEffect(() => {
    if (!activated) return;
    const timeoutId = window.setTimeout(() => {
      releaseLoadRef.current?.();
      releaseLoadRef.current = null;
    }, 8_000);
    return () => window.clearTimeout(timeoutId);
  }, [activated]);

  useEffect(() => () => {
    releaseLoadRef.current?.();
    releaseLoadRef.current = null;
  }, []);

  if (backendPosterUrl) {
    return (
      <StableMediaPreview
        className="agent-canvas-node__media agent-canvas-node__media--cover"
        src={backendPosterUrl}
        alt={asset.display_name || label}
        draggable={false}
        loading="lazy"
        decoding="async"
        deferMs={500}
        onLoad={(event) => {
          const { naturalWidth, naturalHeight } = event.currentTarget;
          if (naturalWidth > 0 && naturalHeight > 0) {
            onMediaDimensionsResolved?.({ width: naturalWidth, height: naturalHeight });
          }
        }}
      />
    );
  }

  return (
    <video
      ref={videoRef}
      className="agent-canvas-node__media agent-canvas-node__media--cover"
      aria-label={asset.display_name || label}
      src={activated && mediaUrl ? mediaUrl : undefined}
      poster={posterUrl || undefined}
      preload={activated ? "metadata" : "none"}
      muted
      playsInline
      controls={false}
      disablePictureInPicture
      onLoadedMetadata={(event) => {
        const video = event.currentTarget;
        const width = video.videoWidth;
        const height = video.videoHeight;
        if (width > 0 && height > 0) {
          onMediaDimensionsResolved?.({ width, height });
        }
        void requestNativeVideoFirstFrame(video);
      }}
      onLoadedData={(event) => {
        const video = event.currentTarget;
        releaseLoadRef.current?.();
        releaseLoadRef.current = null;
        if (video.videoWidth > 0 && video.videoHeight > 0) {
          onMediaDimensionsResolved?.({ width: video.videoWidth, height: video.videoHeight });
        }
      }}
      onError={() => {
        releaseLoadRef.current?.();
        releaseLoadRef.current = null;
      }}
    />
  );
}
