import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import { mediaAssetPosterRenditionPath } from "../../../workflow/mediaPreview.ts";
import { StableMediaPreview } from "../../../workflow/StableMediaPreview.tsx";
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
  // Canvas cards must not fetch source video just to create a thumbnail. The
  // explicit preview dialog remains responsible for loading posterless video.
  const cachedPosterUrl = useAgentCanvasVideoPoster(asset);
  const posterUrl = mediaAssetPosterRenditionPath(asset) || cachedPosterUrl;

  if (posterUrl) {
    return (
      <StableMediaPreview
        className="agent-canvas-node__media agent-canvas-node__media--cover"
        src={posterUrl}
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

  return <div className="agent-canvas-node__media-placeholder" aria-hidden="true" />;
}
