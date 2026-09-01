import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import { mediaAssetCanvasPosterRenditionPath } from "../../../workflow/mediaPreview.ts";
import { CanvasMediaPreview } from "./CanvasMediaPreview.tsx";
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
  const posterUrl = mediaAssetCanvasPosterRenditionPath(asset) || cachedPosterUrl;

  if (!posterUrl) {
    return <div className="agent-canvas-node__media-placeholder" aria-hidden="true" />;
  }

  return (
    <CanvasMediaPreview
      className="agent-canvas-node__media agent-canvas-node__media--cover"
      src={posterUrl}
      alt={asset.display_name || label}
      width={asset.width ?? undefined}
      height={asset.height ?? undefined}
      onLoad={(event) => {
        const { naturalWidth, naturalHeight } = event.currentTarget;
        if (naturalWidth > 0 && naturalHeight > 0) {
          onMediaDimensionsResolved?.({ width: naturalWidth, height: naturalHeight });
        }
      }}
    />
  );
}
