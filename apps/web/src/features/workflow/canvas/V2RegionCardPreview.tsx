import { useMemo, useState, type CSSProperties } from "react";
import { ImageIcon, PlayIcon, VideoIcon } from "../../../icons";
import type { AssetVersionV2, WorkflowItemV2, WorkflowRuntimeV2, WorkflowSlotV2 } from "../../../types-v2.ts";
import { effectiveSlotPrompt } from "../../../types-v2.ts";
import { isCompleteV2Asset } from "../../../workflow-v2/assets.ts";
import { usableAssetVersionUrl } from "../../../workflow-v2/selectors.ts";
import { versionedMediaPath } from "../../../workflow/mediaPreview.ts";
import { DeferredVideo } from "../../../components/media/DeferredVideo.tsx";
import type { SlotMicroEditDraft } from "../v2/slots/useSlotMicroEdit.ts";
import { NodePreviewLoading } from "./NodePreviewLoading.tsx";
import { storyboardVideoPreview } from "./storyboardVideoPreviewModel.ts";
import type { V2StoryboardVideoPreviewTarget } from "../types.ts";
import { isV2BgmFunctionalItem, V2BgmFunctionalCard } from "./V2BgmFunctionalCard.tsx";
import {
  buildV2RegionFunctionalModel,
  type V2RegionFunctionalItemView,
  type V2RegionFunctionalSlotView,
} from "../v2/region/v2RegionFunctionalModel.ts";

export type V2RegionCardPreviewProps = {
  items: WorkflowItemV2[];
  slots: WorkflowSlotV2[];
  assetVersions: AssetVersionV2[];
  runtime?: WorkflowRuntimeV2;
  v2SlotRuntimeStatusById?: Record<string, string>;
  title: string;
  isRunning?: boolean;
  openSlotId?: string | null;
  openStoryboardItemId?: string | null;
  slotDraftsById?: Record<string, SlotMicroEditDraft>;
  referenceAssetsBySlotId?: Record<string, AssetVersionV2[]>;
  onOpenScreenplay?: (trigger: HTMLElement) => void;
  onOpenSlotEditor?: (slotId: string) => void;
  onOpenStoryboardPrompt?: (itemId: string) => void;
  onOpenStoryboardVideoPreview?: (preview: V2StoryboardVideoPreviewTarget) => void;
  onSelectSlotVersion?: (slotId: string, versionId: string) => void;
  onDiscardSlotWorkingVersion?: (slotId: string) => void;
};

type StoryboardMediaMode = "image" | "video";

export function V2RegionCardPreview({
  items,
  slots,
  assetVersions,
  runtime,
  v2SlotRuntimeStatusById = {},
  title,
  isRunning,
  openSlotId = null,
  openStoryboardItemId = null,
  slotDraftsById = {},
  referenceAssetsBySlotId = {},
  onOpenScreenplay,
  onOpenSlotEditor,
  onOpenStoryboardPrompt,
  onOpenStoryboardVideoPreview,
  onSelectSlotVersion,
  onDiscardSlotWorkingVersion,
}: V2RegionCardPreviewProps) {
  const scriptText = scriptTextFromItems(items);
  const [storyboardMediaModeByItemId, setStoryboardMediaModeByItemId] = useState<Record<string, StoryboardMediaMode>>({});
  const region = useMemo(
    () =>
      buildV2RegionFunctionalModel({
        title,
        items,
        slots,
        assetVersions,
        runtime,
        slotRuntimeStatusById: v2SlotRuntimeStatusById,
        referenceAssetsBySlotId,
      }),
    [assetVersions, items, referenceAssetsBySlotId, runtime, slots, title, v2SlotRuntimeStatusById],
  );

  if (scriptText !== null) {
    return <V2ScriptTextCard scriptText={scriptText} onOpenScreenplay={onOpenScreenplay} />;
  }

  if (!region.items.length) {
    return (
      <div className="workflow-card-preview v2-region-card-preview is-empty">
        <strong>{title}</strong>
        <span>Waiting for V2 items</span>
        {isRunning ? <NodePreviewLoading type="generic" /> : null}
      </div>
    );
  }
  const isStoryboardRegion = region.items.some(isStoryboardShotItemView);
  const bgmItem = region.items.length === 1 ? region.items.find(isV2BgmFunctionalItem) : undefined;
  if (bgmItem) {
    return (
      <V2BgmFunctionalCard
        item={bgmItem}
        openSlotId={openSlotId}
        onOpenSlotEditor={onOpenSlotEditor}
        onSelectSlotVersion={onSelectSlotVersion}
        onDiscardSlotWorkingVersion={onDiscardSlotWorkingVersion}
      />
    );
  }
  const isMediaRegion = region.items.some((item) => item.slots.some((slot) => slot.slot.media_type === "image" || slot.slot.media_type === "video"));
  const previewClassName = `workflow-card-preview v2-region-card-preview${isStoryboardRegion ? " is-storyboard-region" : ""}${isMediaRegion ? " is-media-region" : ""}`;

  return (
    <div className={previewClassName} aria-label={`${title} V2 region`}>
      <div className="v2-region-card-header">
        <strong>{region.items.length} items</strong>
        <span>
          {region.completedSlots}/{region.totalSlots} slots ready
        </span>
      </div>
      <div className="v2-region-drag-handle" aria-hidden="true" title="Drag node" />
      <div className="v2-region-item-grid nodrag" role="list">
        {region.items.map((item) => (
          <V2RegionFunctionalItemCard
            key={item.item.item_id}
            item={item}
            openSlotId={openSlotId}
            openStoryboardItemId={openStoryboardItemId}
            storyboardMediaMode={storyboardMediaModeByItemId[item.item.item_id]}
            onChangeStoryboardMediaMode={(mode) => setStoryboardMediaModeByItemId((current) => ({ ...current, [item.item.item_id]: mode }))}
            slotDraftsById={slotDraftsById}
            onOpenSlotEditor={onOpenSlotEditor}
            onOpenStoryboardPrompt={onOpenStoryboardPrompt}
            onOpenStoryboardVideoPreview={onOpenStoryboardVideoPreview}
            onSelectSlotVersion={onSelectSlotVersion}
            onDiscardSlotWorkingVersion={onDiscardSlotWorkingVersion}
          />
        ))}
      </div>
    </div>
  );
}

function scriptTextFromItems(items: WorkflowItemV2[]): string | null {
  const scriptItem = items.find((item) => item.item_type === "script" || item.node_id === "script");
  if (!scriptItem) return null;
  const scriptText = scriptItem.metadata?.script_text;
  return typeof scriptText === "string" ? scriptText : "";
}

function V2ScriptTextCard({ scriptText, onOpenScreenplay }: { scriptText: string; onOpenScreenplay?: (trigger: HTMLElement) => void }) {
  return (
    <button
      type="button"
      className="workflow-card-preview v2-script-text-card nodrag"
      aria-label="Open screenplay editor"
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => {
        event.stopPropagation();
        onOpenScreenplay?.(event.currentTarget);
      }}
    >
      <pre>{scriptText}</pre>
    </button>
  );
}

function V2RegionFunctionalItemCard({
  item,
  openSlotId,
  openStoryboardItemId,
  storyboardMediaMode,
  onChangeStoryboardMediaMode,
  slotDraftsById,
  onOpenSlotEditor,
  onOpenStoryboardPrompt,
  onOpenStoryboardVideoPreview,
  onSelectSlotVersion,
  onDiscardSlotWorkingVersion,
}: {
  item: V2RegionFunctionalItemView;
  openSlotId: string | null;
  openStoryboardItemId: string | null;
  storyboardMediaMode?: StoryboardMediaMode;
  onChangeStoryboardMediaMode: (mode: StoryboardMediaMode) => void;
  slotDraftsById: Record<string, SlotMicroEditDraft>;
  onOpenSlotEditor?: (slotId: string) => void;
  onOpenStoryboardPrompt?: (itemId: string) => void;
  onOpenStoryboardVideoPreview?: (preview: V2StoryboardVideoPreviewTarget) => void;
  onSelectSlotVersion?: (slotId: string, versionId: string) => void;
  onDiscardSlotWorkingVersion?: (slotId: string) => void;
}) {
  if (isStoryboardShotItemView(item)) {
    return (
      <V2StoryboardFunctionalItemCard
        item={item}
        isPromptOpen={openStoryboardItemId === item.item.item_id}
        mediaMode={storyboardMediaMode}
        onChangeMediaMode={onChangeStoryboardMediaMode}
        slotDraftsById={slotDraftsById}
        onOpenSlotEditor={onOpenSlotEditor}
        onOpenStoryboardPrompt={onOpenStoryboardPrompt}
        onOpenStoryboardVideoPreview={onOpenStoryboardVideoPreview}
      />
    );
  }

  const mainSlots = item.slots.filter((slot) => slot.displayRole === "main");
  const multiViewSlots = item.slots.filter((slot) => slot.displayRole === "multi_view");
  const supplementalSlots = item.slots.filter((slot) => slot.displayRole === "supplemental");
  const itemLabel = item.title || item.item.item_id;

  return (
    <article className={`v2-region-functional-item-card status-${item.runtimeStatus}`} role="listitem" data-item-id={item.item.item_id}>
      <section className="v2-region-item-summary" aria-label={`${itemLabel} summary`}>
        <header>
          <strong>{itemLabel}</strong>
          <span>{item.runtimeStatus}</span>
        </header>
        <p>{item.summary}</p>
        <em>{item.prompt || item.item.item_type}</em>
      </section>
      <section className="v2-region-slot-main" aria-label={`${itemLabel} main image`}>
        {mainSlots.map((slot) => (
          <V2RegionSlotEditor
            key={slot.slot.slot_id}
            slotView={slot}
            isOpen={slot.slot.slot_id === openSlotId}
            draft={slotDraftsById[slot.slot.slot_id] ?? draftFromSlot(slot.slot)}
            onOpenSlotEditor={onOpenSlotEditor}
            onSelectSlotVersion={onSelectSlotVersion}
            onDiscardSlotWorkingVersion={onDiscardSlotWorkingVersion}
          />
        ))}
      </section>
      <section className="v2-region-slot-multi-view v2-region-slot-strip" aria-label={`${itemLabel} multi-view images`}>
        {[...multiViewSlots, ...supplementalSlots].map((slot) => (
          <V2RegionSlotEditor
            key={slot.slot.slot_id}
            slotView={slot}
            isOpen={slot.slot.slot_id === openSlotId}
            draft={slotDraftsById[slot.slot.slot_id] ?? draftFromSlot(slot.slot)}
            onOpenSlotEditor={onOpenSlotEditor}
            onSelectSlotVersion={onSelectSlotVersion}
            onDiscardSlotWorkingVersion={onDiscardSlotWorkingVersion}
          />
        ))}
      </section>
    </article>
  );
}

function V2StoryboardFunctionalItemCard({
  item,
  isPromptOpen,
  mediaMode,
  onChangeMediaMode,
  slotDraftsById,
  onOpenSlotEditor,
  onOpenStoryboardPrompt,
  onOpenStoryboardVideoPreview,
}: {
  item: V2RegionFunctionalItemView;
  isPromptOpen: boolean;
  mediaMode?: StoryboardMediaMode;
  onChangeMediaMode: (mode: StoryboardMediaMode) => void;
  slotDraftsById: Record<string, SlotMicroEditDraft>;
  onOpenSlotEditor?: (slotId: string) => void;
  onOpenStoryboardPrompt?: (itemId: string) => void;
  onOpenStoryboardVideoPreview?: (preview: V2StoryboardVideoPreviewTarget) => void;
}) {
  const imageSlots = item.slots.filter((slot) => slot.slot.media_type === "image");
  const videoSlots = item.slots.filter((slot) => slot.slot.media_type === "video");
  const activeMode = resolveStoryboardMediaMode(mediaMode, imageSlots.length, videoSlots.length);
  const activeSlots = activeMode === "video" ? videoSlots : imageSlots;
  const itemLabel = item.title || item.item.item_id;

  return (
    <article className={`v2-region-functional-item-card is-storyboard-item status-${item.runtimeStatus}`} role="listitem" data-item-id={item.item.item_id}>
      <section
        className={`v2-region-item-summary v2-storyboard-summary-trigger ${isPromptOpen ? "is-open" : ""}`}
        aria-label={`${itemLabel} summary prompt`}
        role="button"
        tabIndex={0}
        data-storyboard-summary-action-target={item.item.item_id}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={(event) => {
          event.stopPropagation();
          onOpenStoryboardPrompt?.(item.item.item_id);
        }}
        onKeyDown={(event) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          event.stopPropagation();
          onOpenStoryboardPrompt?.(item.item.item_id);
        }}
      >
        <header>
          <strong>{itemLabel}</strong>
          <span>{item.runtimeStatus}</span>
        </header>
        <p>{item.summary}</p>
        <em>{item.prompt || item.item.item_type}</em>
      </section>
      <section className="v2-storyboard-media-panel" aria-label={`${itemLabel} storyboard media`}>
        <div className="v2-storyboard-media-toolbar">
          <div className="v2-storyboard-media-toggle" role="group" aria-label={`${itemLabel} media type`}>
            <button
              type="button"
              className={activeMode === "image" ? "is-active" : ""}
              aria-label="Show storyboard images"
              title="Images"
              disabled={!imageSlots.length}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation();
                onChangeMediaMode("image");
              }}
            >
              <ImageIcon />
            </button>
            <button
              type="button"
              className={activeMode === "video" ? "is-active" : ""}
              aria-label="Show storyboard videos"
              title="Videos"
              disabled={!videoSlots.length}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation();
                onChangeMediaMode("video");
              }}
            >
              <VideoIcon />
            </button>
          </div>
          <span className="v2-storyboard-media-count">{activeSlots.length}/{item.slots.length}</span>
        </div>
        <div className="v2-storyboard-media-gallery" data-storyboard-media-mode={activeMode}>
          {activeSlots.length ? (
            activeSlots.map((slot) => (
              <V2RegionSlotPreview
                key={slot.slot.slot_id}
                slotView={slot}
                onOpenSlotEditor={onOpenSlotEditor}
                isSubmitting={slotDraftsById[slot.slot.slot_id]?.isSubmitting}
                isStoryboardVideoPreview={activeMode === "video"}
                previewTitle={`${itemLabel} video`}
                onOpenStoryboardVideoPreview={onOpenStoryboardVideoPreview}
              />
            ))
          ) : (
            <span className="v2-region-slot-empty">{activeMode === "video" ? "No video yet" : "No image yet"}</span>
          )}
        </div>
      </section>
    </article>
  );
}

function V2RegionSlotEditor({
  slotView,
  isOpen,
  draft,
  onOpenSlotEditor,
  onSelectSlotVersion,
  onDiscardSlotWorkingVersion,
}: {
  slotView: V2RegionFunctionalSlotView;
  isOpen: boolean;
  draft: SlotMicroEditDraft;
  onOpenSlotEditor?: (slotId: string) => void;
  onSelectSlotVersion?: (slotId: string, versionId: string) => void;
  onDiscardSlotWorkingVersion?: (slotId: string) => void;
}) {
  const slotId = slotView.slot.slot_id;
  return (
    <div className={`v2-region-slot-editor ${isOpen ? "is-open" : ""}`} data-slot-editor-id={slotId}>
      <V2RegionSlotPreview slotView={slotView} onOpenSlotEditor={onOpenSlotEditor} isSubmitting={draft.isSubmitting} />
      {isOpen && slotView.workingAsset && slotView.hasUnselectedWorkingVersion ? (
        <div className="v2-region-working-version-actions">
          <span>Working version not used in current workflow</span>
          <button type="button" className="small-action" onClick={(event) => {
            event.stopPropagation();
            onSelectSlotVersion?.(slotId, slotView.workingAsset?.version_id ?? "");
          }}>
            Use this version
          </button>
          <button type="button" className="small-action" onClick={(event) => {
            event.stopPropagation();
            onDiscardSlotWorkingVersion?.(slotId);
          }}>
            Discard working version
          </button>
        </div>
      ) : null}
    </div>
  );
}

function V2RegionSlotPreview({
  slotView,
  onOpenSlotEditor,
  isSubmitting,
  isStoryboardVideoPreview = false,
  previewTitle,
  onOpenStoryboardVideoPreview,
}: {
  slotView: V2RegionFunctionalSlotView;
  onOpenSlotEditor?: (slotId: string) => void;
  isSubmitting?: boolean;
  isStoryboardVideoPreview?: boolean;
  previewTitle?: string;
  onOpenStoryboardVideoPreview?: (preview: V2StoryboardVideoPreviewTarget) => void;
}) {
  const { slot, previewAsset, runtimeStatus, displayRole } = slotView;
  const isActive = Boolean(isSubmitting) || runtimeStatus === "running" || runtimeStatus === "waiting";
  const loading = isActive ? <NodePreviewLoading type={slot.media_type === "image" || slot.media_type === "video" || slot.media_type === "audio" ? slot.media_type : "generic"} /> : null;
  const roleClassName = displayRole === "main" ? "is-main-slot" : displayRole === "multi_view" ? "is-multi-view-slot" : "is-supplemental-slot";
  const aspectRatioStyle = slotAspectRatioStyle(slot, previewAsset);
  const videoPreview = isStoryboardVideoPreview ? storyboardVideoPreview(previewAsset, previewTitle ?? slot.slot_type) : null;
  const content = (
    <>
      <SlotAssetPreview slot={slot} asset={previewAsset} />
      {slotView.workingAsset && slotView.hasUnselectedWorkingVersion ? <span className="v2-region-working-badge">Working</span> : null}
      <span className="v2-region-slot-status">{runtimeStatus}</span>
      {loading}
    </>
  );
  if (videoPreview) {
    return (
      <div
        className={`v2-region-slot-media v2-storyboard-video-slot ${roleClassName} nodrag`}
        data-slot-status={runtimeStatus}
        data-slot-action-target={slot.slot_id}
        style={aspectRatioStyle}
      >
        <button
          type="button"
          className="v2-storyboard-video-prompt-trigger"
          aria-label={`Edit ${slot.slot_type} prompt`}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            onOpenSlotEditor?.(slot.slot_id);
          }}
        >
          {content}
        </button>
        <button
          type="button"
          className="v2-storyboard-video-play"
          aria-label={`Play ${videoPreview.title}`}
          title="Play video preview"
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            onOpenStoryboardVideoPreview?.(videoPreview);
          }}
        >
          <PlayIcon />
        </button>
      </div>
    );
  }

  return (
    <button
      type="button"
      className={`v2-region-slot-media ${roleClassName}`}
      data-slot-status={runtimeStatus}
      data-slot-action-target={slot.slot_id}
      style={aspectRatioStyle}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => {
        event.stopPropagation();
        onOpenSlotEditor?.(slot.slot_id);
      }}
    >
      {content}
    </button>
  );
}

function slotAspectRatioStyle(slot: WorkflowSlotV2, asset?: AssetVersionV2): CSSProperties | undefined {
  const width = Number(asset?.width);
  const height = Number(asset?.height);
  if (Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) {
    return { "--v2-slot-aspect-ratio": `${width} / ${height}` } as CSSProperties;
  }
  const mediaType = asset?.media_type ?? slot.media_type;
  if (mediaType === "image") return { "--v2-slot-aspect-ratio": "1 / 1" } as CSSProperties;
  if (mediaType === "video") return { "--v2-slot-aspect-ratio": "16 / 9" } as CSSProperties;
  return undefined;
}

function SlotAssetPreview({ slot, asset }: { slot: WorkflowSlotV2; asset?: AssetVersionV2 }) {
  if (!asset) return <span className="v2-region-slot-empty">{slot.slot_type}</span>;
  if (!isCompleteV2Asset(asset)) return <span className="v2-region-slot-syncing">Asset metadata syncing</span>;
  const url = usableAssetVersionUrl(asset);
  if (!url) return <span className="v2-region-slot-syncing">Asset metadata syncing</span>;
  if (asset.media_type === "image") return <img src={url} alt={slot.slot_type} loading="lazy" decoding="async" />;
  if (asset.media_type === "video") return <DeferredVideo src={url} poster={versionedMediaPath(asset.thumbnail_path, asset) || undefined} preload="metadata" muted playsInline />;
  if (asset.media_type === "audio") return <span className="v2-region-slot-empty">Audio</span>;
  return <span className="v2-region-slot-empty">{asset.media_type}</span>;
}

function draftFromSlot(slot: WorkflowSlotV2): SlotMicroEditDraft {
  return {
    prompt: effectiveSlotPrompt(slot),
    negative_prompt: slot.negative_prompt ?? "",
    reference_asset_ids: [...(slot.explicit_reference_ids ?? [])],
    uploaded_asset_ids: [],
    library_entity_ids: [],
    attachments: (slot.explicit_reference_ids ?? []).map((assetId) => ({
      id: `reference:${assetId}`,
      source: "reference_asset",
      source_asset_id: assetId,
      status: "attached",
    })),
    dirty: false,
    promptDirty: false,
    referenceDirty: false,
    base_prompt: effectiveSlotPrompt(slot),
    base_negative_prompt: slot.negative_prompt ?? "",
    isSubmitting: false,
  };
}

function isStoryboardShotItemView(item: V2RegionFunctionalItemView) {
  return item.item.node_id === "storyboard" || item.item.item_type === "shot" || Boolean(item.item.shot_id);
}

function resolveStoryboardMediaMode(mode: StoryboardMediaMode | undefined, imageCount: number, videoCount: number): StoryboardMediaMode {
  if (mode === "video" && videoCount > 0) return "video";
  if (mode === "image" && imageCount > 0) return "image";
  return imageCount > 0 ? "image" : "video";
}
