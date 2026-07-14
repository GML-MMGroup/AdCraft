import { useEffect, useMemo, useState } from "react";
import { mediaUrl } from "../../../api/client";
import { PlayIcon } from "../../../icons";
import type { UploadedAsset } from "../../../types";
import { buildCanvasEntityArea } from "../../../workflow/canvasEntityAreas.ts";
import { mediaAssetOriginalPath, mediaAssetPosterPath, mediaAssetPreviewPath, usesDerivedMediaPreview } from "../../../workflow/mediaPreview.ts";
import { buildSemanticAssetGallery, type SemanticAssetGallery, type SemanticGalleryItem } from "../../../workflow/semanticGallery.ts";
import { ensureVideoPoster, videoNeedsLocalPoster } from "../../../workflow/videoPosterCache.ts";
import type { PreviewLoadingType, WorkflowNodeData } from "../types";
import { V2RegionCardPreview } from "./V2RegionCardPreview.tsx";
import { CanvasEntityAreaPreview } from "./WorkflowCanvasEntityAreaPreview.tsx";

const SEMANTIC_GALLERY_PREVIEW_LIMIT = 4;

function scheduleIdleTask(task: () => void) {
  const idleWindow = window as Window & {
    requestIdleCallback?: (callback: () => void, options?: { timeout?: number }) => number;
    cancelIdleCallback?: (handle: number) => void;
  };
  if (idleWindow.requestIdleCallback) {
    const handle = idleWindow.requestIdleCallback(task, { timeout: 1200 });
    return () => idleWindow.cancelIdleCallback?.(handle);
  }
  const handle = window.setTimeout(task, 220);
  return () => window.clearTimeout(handle);
}

function previewLoadingType(data: WorkflowNodeData, asset?: UploadedAsset): PreviewLoadingType {
  if (asset?.asset_type === "image") {
    return "image";
  }
  if (asset?.asset_type === "audio") {
    return "audio";
  }
  if (asset?.asset_type === "video") {
    return "video";
  }
  if (data.family === "Text") {
    return "text";
  }
  if (data.family === "Image") {
    return "image";
  }
  if (data.family === "Audio") {
    return "audio";
  }
  if (data.family === "Video" || data.family === "Preview") {
    return "video";
  }
  return "generic";
}

export function NodeCardPreview({
  data,
  onOpenMedia,
  onSelectDynamicItem,
  isRunning,
  runningById,
}: {
  data: WorkflowNodeData;
  onOpenMedia?: (asset: UploadedAsset) => void;
  onSelectDynamicItem?: (nodeId: string, itemId: string) => void;
  isRunning?: boolean;
  runningById?: Record<string, boolean | undefined>;
}) {
  const entityArea = useMemo(
    () =>
      buildCanvasEntityArea(
        {
          id: data.nodeId ?? data.nodeType ?? data.kind,
          node_type: data.kind,
          type: data.kind,
          title: data.title,
          description: data.description,
          status: data.status,
          output: data.output ?? undefined,
          output_assets: data.previewAssets,
        },
        { outputAssets: data.previewAssets },
      ),
    [data.nodeId, data.nodeType, data.kind, data.title, data.description, data.status, data.output, data.previewAssets],
  );
  const semanticGallery = useMemo(() => buildSemanticAssetGallery({ nodeType: data.kind, output: data.output, assets: data.previewAssets }), [data.kind, data.output, data.previewAssets]);
  const assets = useMemo(() => data.previewAssets.filter((item) => mediaAssetPreviewPath(item)), [data.previewAssets]);
  const asset = assets[0];
  const loadingType = previewLoadingType(data, asset);
  const previewPath = mediaAssetPreviewPath(asset);
  const originalPath = mediaAssetOriginalPath(asset) || previewPath;
  const posterPath = mediaAssetPosterPath(asset);
  const videoPosterPath = posterPath || (asset && usesDerivedMediaPreview(asset) ? previewPath : "");
  const [localVideoPosterUrl, setLocalVideoPosterUrl] = useState("");

  useEffect(() => {
    if (!asset || !videoNeedsLocalPoster(asset) || !originalPath) {
      setLocalVideoPosterUrl("");
      return;
    }
    const projectId = data.projectId || data.workflowId || "local-project";
    const workflowId = data.workflowId || "local-workflow";
    let objectUrl = "";
    let cancelled = false;
    const cancelIdleTask = scheduleIdleTask(() => {
      void ensureVideoPoster({
        projectId,
        workflowId,
        asset,
        videoUrl: mediaUrl(originalPath),
      }).then((record) => {
        if (cancelled || !record?.poster_blob) return;
        objectUrl = URL.createObjectURL(record.poster_blob);
        setLocalVideoPosterUrl(objectUrl);
      });
    });
    return () => {
      cancelled = true;
      cancelIdleTask();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [
    asset,
    originalPath,
    data.projectId,
    data.workflowId,
  ]);

  if (data.isV2Region) {
    return (
      <V2RegionCardPreview
        items={data.v2Items ?? []}
        slots={data.v2Slots ?? []}
        assetVersions={data.v2AssetVersions ?? []}
        runtime={data.v2Runtime}
        v2SlotRuntimeStatusById={data.v2SlotRuntimeStatusById}
        title={data.title}
        isRunning={isRunning}
        openSlotId={data.v2OpenSlotId}
        slotDraftsById={data.v2SlotDraftsById}
        referenceAssetsBySlotId={data.v2ReferenceAssetsBySlotId}
        workflowId={data.workflowId}
        onOpenScreenplay={data.onOpenScreenplay}
        onOpenSlotEditor={data.onOpenV2SlotEditor}
        onSelectSlotVersion={data.onSelectV2SlotVersion}
        onDiscardSlotWorkingVersion={data.onDiscardV2SlotWorkingVersion}
      />
    );
  }

  if (entityArea) {
    return (
      <CanvasEntityAreaPreview
        area={entityArea}
        onOpenMedia={onOpenMedia}
        onSelectDynamicItem={onSelectDynamicItem}
        isRunning={isRunning}
        runningById={runningById}
      />
    );
  }

  if (semanticGallery) {
    return <SemanticAssetGalleryPreview gallery={semanticGallery} onOpenMedia={onOpenMedia} isRunning={isRunning} />;
  }

  if (asset && previewPath) {
    if (asset.asset_type === "video" || data.family === "Video" || data.family === "Preview") {
      const posterSrc = videoPosterPath ? mediaUrl(videoPosterPath) : localVideoPosterUrl;
      return (
        <div className="workflow-card-preview media video-preview nodrag">
          {posterSrc ? (
            <img src={posterSrc} alt={asset.filename ?? data.title} loading="lazy" decoding="async" />
          ) : (
            <div className="workflow-card-preview-placeholder">Video</div>
          )}
          {isRunning ? <NodePreviewLoading type={loadingType} /> : null}
          <button
            className="video-preview-play nodrag"
            type="button"
            aria-label="Play video preview"
            title="Play video preview"
            onPointerDown={(event) => {
              event.stopPropagation();
            }}
            onClick={(event) => {
              event.stopPropagation();
              onOpenMedia?.(asset);
            }}
          >
            <PlayIcon />
          </button>
        </div>
      );
    }
    if (asset.asset_type === "audio") {
      return (
        <div className="workflow-card-preview audio-player nodrag">
          <audio src={mediaUrl(originalPath)} controls preload="none" />
          {isRunning ? <NodePreviewLoading type={loadingType} /> : null}
          <NodePreviewMeta asset={asset} assetPath={originalPath} count={assets.length} />
        </div>
      );
    }
    if (asset.asset_type === "image" || data.family === "Image") {
      return (
        <button
          className="workflow-card-preview media image-preview nodrag"
          type="button"
          aria-label={`Open ${asset.filename ?? data.title}`}
          onClick={(event) => {
            event.stopPropagation();
            onOpenMedia?.(asset);
          }}
        >
          <img src={mediaUrl(previewPath)} alt={asset.filename ?? data.title} loading="lazy" decoding="async" />
          {isRunning ? <NodePreviewLoading type={loadingType} /> : null}
          <NodePreviewMeta asset={asset} assetPath={originalPath} count={assets.length} />
        </button>
      );
    }
  }

  if (data.family === "Audio") {
    return (
      <div className="workflow-card-preview waveform">
        <i />
        <i />
        <i />
        <i />
        <span>{data.contentPreview || data.description || "Audio input or generated track"}</span>
        {isRunning ? <NodePreviewLoading type={loadingType} /> : null}
      </div>
    );
  }

  if (data.family === "Comment") {
    return (
      <p className="workflow-card-note">
        {data.contentPreview || data.description || "Comment"}
        {isRunning ? <NodePreviewLoading type={loadingType} /> : null}
      </p>
    );
  }

  if (data.contentPreview) {
    return (
      <p className="workflow-card-note">
        {data.contentPreview}
        {isRunning ? <NodePreviewLoading type={loadingType} /> : null}
      </p>
    );
  }

  return (
    <div className="workflow-card-preview empty">
      {data.description || data.family + " node"}
      {isRunning ? <NodePreviewLoading type={loadingType} /> : null}
    </div>
  );
}

function SemanticAssetGalleryPreview({ gallery, onOpenMedia, isRunning }: { gallery: SemanticAssetGallery; onOpenMedia?: (asset: UploadedAsset) => void; isRunning?: boolean }) {
  const label = gallery.kind === "character" ? "Character gallery" : "Scene gallery";
  const visibleItems = gallery.items.slice(0, SEMANTIC_GALLERY_PREVIEW_LIMIT);
  const hiddenCount = gallery.items.length - visibleItems.length;

  return (
    <div className={`workflow-card-preview semantic-gallery is-${gallery.kind} nodrag`} aria-label={label}>
      <div className="semantic-gallery-track" role="list">
        {visibleItems.map((item, index) => (
          <SemanticGalleryCard key={[gallery.kind, item.id, index].join("-")} kind={gallery.kind} item={item} index={index} onOpenMedia={onOpenMedia} />
        ))}
        {hiddenCount > 0 ? <span className="semantic-gallery-more" role="listitem">+{hiddenCount}</span> : null}
      </div>
      {isRunning ? <NodePreviewLoading type="image" /> : null}
    </div>
  );
}

function SemanticGalleryCard({ kind, item, index, onOpenMedia }: { kind: SemanticAssetGallery["kind"]; item: SemanticGalleryItem; index: number; onOpenMedia?: (asset: UploadedAsset) => void }) {
  const title = item.title || (kind === "character" ? `Character ${index + 1}` : `Scene ${index + 1}`);

  if (kind === "character") {
    const mainAsset = item.main ?? item.threeView ?? item.face;
    const secondaryAsset = item.main ? item.threeView : undefined;
    return (
      <article className="semantic-gallery-item is-character" role="listitem" aria-label={title}>
        <div className="semantic-gallery-main-wrap">
          <SemanticGalleryImage asset={mainAsset} label={`${title} main`} className="semantic-gallery-frame is-main" onOpenMedia={onOpenMedia} />
          {item.face && mainAsset && item.face !== mainAsset ? <SemanticGalleryImage asset={item.face} label={`${title} face id`} className="semantic-gallery-face" onOpenMedia={onOpenMedia} /> : null}
        </div>
        {secondaryAsset ? <SemanticGalleryImage asset={secondaryAsset} label={`${title} three view`} className="semantic-gallery-frame is-secondary" onOpenMedia={onOpenMedia} /> : null}
      </article>
    );
  }

  const mainAsset = item.main ?? item.multiView;
  const secondaryAsset = item.main ? item.multiView : undefined;
  return (
    <article className="semantic-gallery-item is-scene" role="listitem" aria-label={title}>
      <SemanticGalleryImage asset={mainAsset} label={`${title} main scene`} className="semantic-gallery-frame is-main" onOpenMedia={onOpenMedia} />
      {secondaryAsset ? <SemanticGalleryImage asset={secondaryAsset} label={`${title} multi view`} className="semantic-gallery-frame is-secondary" onOpenMedia={onOpenMedia} /> : null}
    </article>
  );
}

function SemanticGalleryImage({ asset, label, className, onOpenMedia }: { asset?: UploadedAsset; label: string; className: string; onOpenMedia?: (asset: UploadedAsset) => void }) {
  const previewPath = mediaAssetPreviewPath(asset) || mediaAssetOriginalPath(asset);
  if (!asset || !previewPath) return null;

  return (
    <button
      className={`${className} nodrag`}
      type="button"
      aria-label={`Open ${label}`}
      title={label}
      onPointerDown={(event) => {
        event.stopPropagation();
      }}
      onClick={(event) => {
        event.stopPropagation();
        onOpenMedia?.(asset);
      }}
    >
      <img src={mediaUrl(previewPath)} alt={label} loading="lazy" decoding="async" />
    </button>
  );
}

const loadingLabelByType: Record<PreviewLoadingType, string> = {
  text: "Text preview loading",
  image: "Image preview loading",
  audio: "Audio preview loading",
  video: "Video preview loading",
  generic: "Node preview loading",
};

export function NodePreviewLoading({ type = "generic" }: { type?: PreviewLoadingType }) {
  return (
    <span className={`workflow-card-preview-loading is-${type}`} role="status" aria-label={loadingLabelByType[type]}>
      <span className="workflow-card-preview-loading-core" aria-hidden="true">
        {type === "text" ? (
          <>
            <i />
            <i />
            <i />
          </>
        ) : null}
        {type === "image" ? (
          <>
            <i />
            <i />
            <i />
            <i />
          </>
        ) : null}
        {type === "audio" ? (
          <>
            <i />
            <i />
            <i />
            <i />
            <i />
          </>
        ) : null}
        {type === "video" ? (
          <>
            <i />
            <i />
            <i />
          </>
        ) : null}
      </span>
    </span>
  );
}

function NodePreviewMeta({ asset, assetPath, count }: { asset: UploadedAsset; assetPath: string; count: number }) {
  return (
    <div className="workflow-card-preview-meta">
      <span>{asset.filename ?? "Generated result"}</span>
      <span className="preview-open-label" data-asset-path={mediaUrl(assetPath)}>
        View{count > 1 ? ` ${count}` : ""}
      </span>
    </div>
  );
}
