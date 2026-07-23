import { PlayIcon, VideoIcon } from "../../../icons.tsx";
import { DeferredVideo } from "../../../components/media/DeferredVideo.tsx";
import { usableAssetVersionUrl } from "../../../workflow-v2/selectors.ts";
import { versionedMediaPath } from "../../../workflow/mediaPreview.ts";
import type { V2StoryboardVideoPreviewTarget } from "../types.ts";
import type { V2RegionFunctionalItemView } from "../v2/region/v2RegionFunctionalModel.ts";
import { isV2FinalCompositionFunctionalSlot } from "../v2/region/v2RegionFunctionalModel.ts";
import { NodePreviewLoading } from "./NodePreviewLoading.tsx";

export function V2FinalCompositionFunctionalCard({
  item,
  onOpenVideo,
}: {
  item: V2RegionFunctionalItemView;
  onOpenVideo?: (preview: V2StoryboardVideoPreviewTarget) => void;
}) {
  const slotView = item.slots.find((slot) => isV2FinalCompositionFunctionalSlot(slot.slot));
  const asset = slotView?.selectedAsset ?? slotView?.previewAsset;
  const src = usableAssetVersionUrl(asset);
  const poster = asset?.thumbnail_path ? versionedMediaPath(asset.thumbnail_path, asset) : undefined;
  const status = slotView?.runtimeStatus ?? item.runtimeStatus;
  const isActive = status === "queued" || status === "running";
  const statusCopy = finalCompositionStatusCopy(status, slotView?.runtimeMessage);

  return (
    <article
      className={`workflow-card-preview v2-final-composition-functional-card status-${status}`}
      aria-label="Final Composition card"
      data-slot-status={status}
    >
      <header className="v2-final-composition-card-heading">
        <div>
          <strong>Final Composition</strong>
          <span>Final video</span>
        </div>
        <span className={`v2-final-composition-card-status status-${status}`}>{status}</span>
      </header>
      <div className="v2-final-composition-card-preview nodrag">
        {src ? (
          <>
            <DeferredVideo
              src={src}
              poster={poster}
              preload="metadata"
              muted
              playsInline
            />
            <button
              type="button"
              className="v2-final-composition-card-play"
              aria-label="Play final video"
              title="Play final video"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation();
                onOpenVideo?.({ src, poster, title: "Final video" });
              }}
            >
              <PlayIcon />
            </button>
          </>
        ) : (
          <div className="v2-final-composition-card-empty">
            <VideoIcon />
            <span>{isActive ? "Preparing final video" : "No final video yet"}</span>
          </div>
        )}
        {isActive ? <NodePreviewLoading type="video" /> : null}
      </div>
      <footer className={`v2-final-composition-card-message status-${status}`}>
        <span>{statusCopy}</span>
      </footer>
    </article>
  );
}

function finalCompositionStatusCopy(status: string, runtimeMessage: string | null | undefined) {
  if (status === "blocked") return "正在等待视频/BGM 生成完成";
  if (status === "skipped") return "没有可用于合成的视频片段";
  if (status === "queued") return "Queued for export";
  if (status === "running") return "Exporting final video";
  if (status === "completed") return "Final video ready";
  if (status === "failed") return runtimeMessage || "Latest export failed. The previous final video remains available.";
  if (status === "cancelled") return "Latest export was cancelled. The previous final video remains available.";
  return runtimeMessage || "Waiting for composition inputs";
}
