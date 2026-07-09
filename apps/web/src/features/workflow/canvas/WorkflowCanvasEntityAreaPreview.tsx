import { mediaUrl } from "../../../api/client";
import { PlayIcon } from "../../../icons";
import type { CanvasTargetReference, UploadedAsset } from "../../../types";
import type { CanvasEntityArea, CanvasEntityAreaItem } from "../../../workflow/canvasEntityAreas.ts";
import { mediaAssetOriginalPath, mediaAssetPosterPath, mediaAssetPreviewPath } from "../../../workflow/mediaPreview.ts";
import { NodePreviewLoading } from "./WorkflowCanvasNodePreview.tsx";

function statusClass(value: string) {
  return value.replace(/[^a-z0-9_-]/gi, "-").toLowerCase();
}

function isNodeRunning(status?: string | null) {
  const normalized = (status ?? "").toLowerCase();
  return ["running", "waiting", "processing", "in_progress"].includes(normalized);
}

function isCanvasEntityItemRunning(item: CanvasEntityAreaItem, runningById?: Record<string, boolean | undefined>) {
  if (runningById?.[item.itemId]) return true;
  if (runningById?.[`${item.itemId}:video`]) return true;
  return isNodeRunning(item.status);
}

function workingVersionNeedsApply(current?: CanvasEntityAreaItem["currentWorkingVersion"] | null, selected?: CanvasEntityAreaItem["selectedVersion"] | null) {
  const currentId = stringFromUnknown(current?.version_id) || current?.asset_ids?.[0] || current?.assets?.[0]?.asset_id || "";
  const selectedId = stringFromUnknown(selected?.version_id) || selected?.asset_ids?.[0] || selected?.assets?.[0]?.asset_id || "";
  return Boolean(currentId && selectedId && currentId !== selectedId);
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

export function CanvasEntityAreaPreview({
  area,
  onOpenMedia,
  onSelectDynamicItem,
  isRunning,
  runningById,
}: {
  area: CanvasEntityArea;
  onOpenMedia?: (asset: UploadedAsset) => void;
  onSelectDynamicItem?: (nodeId: string, itemId: string) => void;
  isRunning?: boolean;
  runningById?: Record<string, boolean | undefined>;
}) {
  return (
    <section className={`workflow-card-preview canvas-entity-area is-${area.kind} nodrag`} aria-label={area.title} data-node-id={area.nodeId}>
      <div className="canvas-entity-area-header">
        <strong>{area.title}</strong>
        <span>{area.statusSummary}</span>
      </div>
      <div className="canvas-entity-track" role="list">
        {area.items.map((item) => (
          <CanvasEntityCard
            key={item.itemId}
            nodeId={area.nodeId}
            item={item}
            onOpenMedia={onOpenMedia}
            onSelectDynamicItem={onSelectDynamicItem}
            runningById={runningById}
          />
        ))}
      </div>
      {isRunning ? <NodePreviewLoading type={area.kind === "storyboard_video" ? "video" : area.kind === "bgm" ? "audio" : "image"} /> : null}
    </section>
  );
}

function CanvasEntityCard({
  nodeId,
  item,
  onOpenMedia,
  onSelectDynamicItem,
  runningById,
}: {
  nodeId: string;
  item: CanvasEntityAreaItem;
  onOpenMedia?: (asset: UploadedAsset) => void;
  onSelectDynamicItem?: (nodeId: string, itemId: string) => void;
  runningById?: Record<string, boolean | undefined>;
}) {
  if (item.itemType === "character") {
    return (
      <CharacterItemCard
        nodeId={nodeId}
        item={item}
        onOpenMedia={onOpenMedia}
        onSelectDynamicItem={onSelectDynamicItem}
        runningById={runningById}
      />
    );
  }
  if (item.itemType === "scene") {
    return (
      <SceneItemCard
        nodeId={nodeId}
        item={item}
        onOpenMedia={onOpenMedia}
        onSelectDynamicItem={onSelectDynamicItem}
        runningById={runningById}
      />
    );
  }
  return (
    <GenericCanvasEntityCard
      nodeId={nodeId}
      item={item}
      onOpenMedia={onOpenMedia}
      onSelectDynamicItem={onSelectDynamicItem}
      runningById={runningById}
    />
  );
}

/* eslint-disable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex -- Legacy canvas item cards use the article surface for selection while nested media previews remain native buttons. */
function CharacterItemCard({
  nodeId,
  item,
  onOpenMedia,
  onSelectDynamicItem,
  runningById,
}: {
  nodeId: string;
  item: CanvasEntityAreaItem;
  onOpenMedia?: (asset: UploadedAsset) => void;
  onSelectDynamicItem?: (nodeId: string, itemId: string) => void;
  runningById?: Record<string, boolean | undefined>;
}) {
  const targetReference = item.targetReference;
  const itemRunning = isCanvasEntityItemRunning(item, runningById);
  const galleryAssets = characterGalleryAssets(item);
  const usageLabel = canvasEntityUsageLabel(item);
  return (
    <article
      className={`canvas-entity-card character-item-card status-${statusClass(item.status)} ${itemRunning ? "is-running" : ""}`}
      role="listitem"
      tabIndex={0}
      data-item-id={item.itemId}
      data-target-type={targetReference.target_type}
      onClick={() => onSelectDynamicItem?.(nodeId, item.itemId)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          event.stopPropagation();
          onSelectDynamicItem?.(nodeId, item.itemId);
        }
      }}
    >
      <div className="canvas-entity-card-heading">
        <span>
          <strong>{item.displayName}</strong>
          <em>{item.description || item.itemId}</em>
        </span>
        <b className="canvas-entity-status">{item.status}</b>
      </div>
      <div className="character-item-gallery">
        <div className="character-item-main">
          <CanvasEntityMedia
            asset={galleryAssets.main}
            label={`${item.displayName} main`}
            onOpenMedia={onOpenMedia}
            isRunning={itemRunning}
            targetReference={targetReferenceForAsset(item, galleryAssets.main) ?? targetReference}
          />
          <CharacterFaceIdBadge asset={galleryAssets.faceId} label={`${item.displayName} face id`} onOpenMedia={onOpenMedia} targetReference={targetReferenceForAsset(item, galleryAssets.faceId)} />
        </div>
        {galleryAssets.threeView ? (
          <CanvasEntityMedia
            asset={galleryAssets.threeView}
            label={`${item.displayName} three view`}
            onOpenMedia={onOpenMedia}
            compact
            targetReference={targetReferenceForAsset(item, galleryAssets.threeView)}
          />
        ) : null}
        {galleryAssets.supplemental.slice(0, 2).map((asset) => (
          <CanvasEntityMedia
            key={asset.asset_id}
            asset={asset}
            label={asset.filename ?? `${item.displayName} asset`}
            onOpenMedia={onOpenMedia}
            compact
            targetReference={targetReferenceForAsset(item, asset)}
          />
        ))}
      </div>
      {item.prompt ? <p className="canvas-entity-prompt">{item.prompt}</p> : null}
      <div className="canvas-entity-card-meta">
        <span>当前工作版本</span>
        <span>{usageLabel}</span>
      </div>
    </article>
  );
}

function SceneItemCard({
  nodeId,
  item,
  onOpenMedia,
  onSelectDynamicItem,
  runningById,
}: {
  nodeId: string;
  item: CanvasEntityAreaItem;
  onOpenMedia?: (asset: UploadedAsset) => void;
  onSelectDynamicItem?: (nodeId: string, itemId: string) => void;
  runningById?: Record<string, boolean | undefined>;
}) {
  const targetReference = item.targetReference;
  const itemRunning = isCanvasEntityItemRunning(item, runningById);
  const galleryAssets = sceneGalleryAssets(item);
  const usageLabel = canvasEntityUsageLabel(item);
  return (
    <article
      className={`canvas-entity-card scene-item-card status-${statusClass(item.status)} ${itemRunning ? "is-running" : ""}`}
      role="listitem"
      tabIndex={0}
      data-item-id={item.itemId}
      data-target-type={targetReference.target_type}
      onClick={() => onSelectDynamicItem?.(nodeId, item.itemId)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          event.stopPropagation();
          onSelectDynamicItem?.(nodeId, item.itemId);
        }
      }}
    >
      <div className="canvas-entity-card-heading">
        <span>
          <strong>{item.displayName}</strong>
          <em>{item.description || item.itemId}</em>
        </span>
        <b className="canvas-entity-status">{item.status}</b>
      </div>
      <div className="scene-item-gallery">
        <CanvasEntityMedia
          asset={galleryAssets.main}
          label={`${item.displayName} main scene`}
          onOpenMedia={onOpenMedia}
          isRunning={itemRunning}
          targetReference={targetReferenceForAsset(item, galleryAssets.main) ?? targetReference}
        />
        {galleryAssets.multiView ? (
          <CanvasEntityMedia
            asset={galleryAssets.multiView}
            label={`${item.displayName} multi view`}
            onOpenMedia={onOpenMedia}
            compact
            targetReference={targetReferenceForAsset(item, galleryAssets.multiView)}
          />
        ) : null}
        {galleryAssets.supplemental.slice(0, 2).map((asset) => (
          <CanvasEntityMedia
            key={asset.asset_id}
            asset={asset}
            label={asset.filename ?? `${item.displayName} asset`}
            onOpenMedia={onOpenMedia}
            compact
            targetReference={targetReferenceForAsset(item, asset)}
          />
        ))}
      </div>
      {item.prompt ? <p className="canvas-entity-prompt">{item.prompt}</p> : null}
      <div className="canvas-entity-card-meta">
        <span>当前工作版本</span>
        <span>{usageLabel}</span>
        {canvasEntityLibraryLabel(item) ? <span>{canvasEntityLibraryLabel(item)}</span> : null}
      </div>
    </article>
  );
}

function GenericCanvasEntityCard({
  nodeId,
  item,
  onOpenMedia,
  onSelectDynamicItem,
  runningById,
}: {
  nodeId: string;
  item: CanvasEntityAreaItem;
  onOpenMedia?: (asset: UploadedAsset) => void;
  onSelectDynamicItem?: (nodeId: string, itemId: string) => void;
  runningById?: Record<string, boolean | undefined>;
}) {
  const targetReference = item.targetReference;
  const itemRunning = isCanvasEntityItemRunning(item, runningById);
  return (
    <article
      className={`canvas-entity-card status-${statusClass(item.status)} ${itemRunning ? "is-running" : ""}`}
      role="listitem"
      tabIndex={0}
      data-item-id={item.itemId}
      data-target-type={targetReference.target_type}
      onClick={() => onSelectDynamicItem?.(nodeId, item.itemId)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          event.stopPropagation();
          onSelectDynamicItem?.(nodeId, item.itemId);
        }
      }}
    >
      <div className="canvas-entity-card-heading">
        <span>
          <strong>{item.displayName}</strong>
          <em>{item.itemId}</em>
        </span>
        <b className="canvas-entity-status">{item.status}</b>
      </div>
      <CanvasEntityMedia
        asset={item.primaryAsset}
        label={item.displayName}
        onOpenMedia={onOpenMedia}
        isRunning={itemRunning}
        targetReference={item.assetTargetReferences[0]}
      />
      {item.supplementalAssets.length ? (
        <div className="canvas-entity-supplemental" aria-label={`${item.displayName} supplemental assets`}>
          {item.supplementalAssets.map((asset, index) => {
            const assetTargetReference = item.assetTargetReferences[index + 1];
            return (
              <CanvasEntityMedia
                key={asset.asset_id}
                asset={asset}
                label={asset.filename ?? `${item.displayName} asset`}
                onOpenMedia={onOpenMedia}
                compact
                targetReference={assetTargetReference}
              />
            );
          })}
        </div>
      ) : null}
      {item.candidateCount || item.historyCount || item.candidateWarningCount ? (
        <div className="canvas-entity-card-meta">
          {item.candidateCount ? <span>candidate {item.candidateCount}</span> : null}
          {item.candidateWarningCount ? <span>review {item.candidateWarningCount}</span> : null}
          {item.historyCount ? <span>history {item.historyCount}</span> : null}
        </div>
      ) : null}
    </article>
  );
}
/* eslint-enable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex */

function CharacterFaceIdBadge({
  asset,
  label,
  onOpenMedia,
  targetReference,
}: {
  asset?: UploadedAsset | null;
  label: string;
  onOpenMedia?: (asset: UploadedAsset) => void;
  targetReference?: CanvasTargetReference;
}) {
  return (
    <div className="character-face-id-badge" aria-label={label}>
      {asset ? <CanvasEntityMedia asset={asset} label={label} onOpenMedia={onOpenMedia} compact targetReference={targetReference} /> : <span>Face ID</span>}
    </div>
  );
}

function characterGalleryAssets(item: CanvasEntityAreaItem) {
  const main = item.mainAsset ?? item.primaryAsset ?? item.outputAssets.find((asset) => asset.semantic_type === "character_main") ?? item.outputAssets[0];
  const faceId = item.faceIdAsset ?? item.outputAssets.find((asset) => asset.semantic_type === "character_face_id");
  const threeView = item.threeViewAsset ?? item.outputAssets.find((asset) => asset.semantic_type === "character_three_view");
  const used = new Set([main?.asset_id, faceId?.asset_id, threeView?.asset_id].filter(Boolean));
  const supplemental = item.outputAssets.filter((asset) => !used.has(asset.asset_id));
  return { main, faceId, threeView, supplemental };
}

function sceneGalleryAssets(item: CanvasEntityAreaItem) {
  const main = item.mainAsset ?? item.primaryAsset ?? item.outputAssets.find((asset) => asset.semantic_type === "scene_main") ?? item.outputAssets[0];
  const multiView = item.multiViewAsset ?? item.outputAssets.find((asset) => asset.semantic_type === "scene_multi_view");
  const used = new Set([main?.asset_id, multiView?.asset_id].filter(Boolean));
  const supplemental = item.outputAssets.filter((asset) => !used.has(asset.asset_id));
  return { main, multiView, supplemental };
}

function targetReferenceForAsset(item: CanvasEntityAreaItem, asset?: UploadedAsset | null) {
  if (!asset) return undefined;
  return item.assetTargetReferences.find((reference) => reference.asset_id === asset.asset_id);
}

function canvasEntityUsageLabel(item: CanvasEntityAreaItem) {
  const needsApply = item.needsApply ?? workingVersionNeedsApply(item.currentWorkingVersion, item.selectedVersion);
  return needsApply ? "未用于当前工作流" : "已用于当前工作流";
}

function canvasEntityLibraryLabel(item: CanvasEntityAreaItem) {
  if (item.libraryState === "ready" || item.libraryState === "linked" || item.libraryState === "created") return "已入资源库";
  if (item.libraryState === "pending") return "入库中";
  if (item.libraryState === "failed") return "入库失败";
  return item.libraryEntityId || item.libraryAssetId ? "已关联资源库" : "";
}

function CanvasEntityMedia({
  asset,
  label,
  onOpenMedia,
  isRunning,
  compact,
  targetReference,
}: {
  asset?: UploadedAsset;
  label: string;
  onOpenMedia?: (asset: UploadedAsset) => void;
  isRunning?: boolean;
  compact?: boolean;
  targetReference?: CanvasTargetReference;
}) {
  const previewPath = mediaAssetPreviewPath(asset);
  const originalPath = mediaAssetOriginalPath(asset) || previewPath;
  const posterPath = mediaAssetPosterPath(asset) || previewPath;
  const loadingType = asset?.asset_type === "video" ? "video" : asset?.asset_type === "audio" ? "audio" : "image";
  const className = `canvas-entity-media ${compact ? "is-compact" : "is-primary"} type-${asset?.asset_type ?? "empty"}`;
  if (!asset || !originalPath) {
    return (
      <div className={`${className} is-empty`}>
        <span>No preview</span>
        {isRunning ? <NodePreviewLoading type={loadingType} /> : null}
      </div>
    );
  }

  if (asset.asset_type === "audio") {
    return (
      <div className={className} data-asset-target-type={targetReference?.target_type}>
        <audio src={mediaUrl(originalPath)} controls preload="none" />
        {isRunning ? <NodePreviewLoading type="audio" /> : null}
      </div>
    );
  }

  if (asset.asset_type === "video") {
    return (
      <button
        className={className}
        type="button"
        aria-label={`Open ${label}`}
        data-asset-target-type={targetReference?.target_type}
        onPointerDown={(event) => {
          event.stopPropagation();
        }}
        onClick={(event) => {
          event.stopPropagation();
          onOpenMedia?.(asset);
        }}
      >
        {posterPath ? <img src={mediaUrl(posterPath)} alt={label} loading="lazy" decoding="async" /> : <span>Video</span>}
        <span className="canvas-entity-play" aria-hidden="true"><PlayIcon /></span>
        {isRunning ? <NodePreviewLoading type="video" /> : null}
      </button>
    );
  }

  return (
    <button
      className={className}
      type="button"
      aria-label={`Open ${label}`}
      data-asset-target-type={targetReference?.target_type}
      onPointerDown={(event) => {
        event.stopPropagation();
      }}
      onClick={(event) => {
        event.stopPropagation();
        onOpenMedia?.(asset);
      }}
    >
      <img src={mediaUrl(previewPath || originalPath)} alt={label} loading="lazy" decoding="async" />
      {isRunning ? <NodePreviewLoading type="image" /> : null}
    </button>
  );
}

