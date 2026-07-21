import type { AssetVersionV2, SlotFunctionalCardViewModel } from "../../../../types-v2.ts";
import { DeferredVideo } from "../../../../components/media/DeferredVideo.tsx";
import { formatV2AssetLocator } from "../../../../workflow-v2/assetLocators.ts";
import { useV2MediaContextMenu } from "../media/useV2MediaContextMenu.ts";
import { isIdOnlyAssetVersion, usableAssetVersionUrl } from "../../../../workflow-v2/selectors.ts";
import { SlotMicroPromptComposer } from "./SlotMicroPromptComposer.tsx";
import type { SlotMicroEditDraft } from "./useSlotMicroEdit.ts";

type SlotFunctionalCardProps = {
  slot: SlotFunctionalCardViewModel;
  isOpen?: boolean;
  draft?: SlotMicroEditDraft;
  referenceAssets?: AssetVersionV2[];
  onOpenSlotEditor?: (slotId: string) => void;
  onChangePrompt?: (slotId: string, prompt: string) => void;
  onChangeNegativePrompt?: (slotId: string, negativePrompt: string) => void;
  onUploadReference?: (slotId: string, files: FileList) => void;
  onSelectLibraryReference?: (slotId: string, entityId: string) => void;
  onRemoveReference?: (slotId: string, reference: { source: "reference_asset" | "uploaded_asset" | "library_entity"; asset_id?: string; entity_id?: string; relation_id?: string | null; library_asset_id?: string | null }) => void;
  onSubmit?: (slotId: string) => void;
  onSelectVersion?: (slotId: string, versionId: string) => void;
  onDiscardWorkingVersion?: (slotId: string) => void;
  onLoadVersions?: (slotId: string) => void;
};

export function SlotFunctionalCard({
  slot,
  isOpen = false,
  draft,
  referenceAssets = [],
  onOpenSlotEditor,
  onChangePrompt,
  onChangeNegativePrompt,
  onUploadReference,
  onSelectLibraryReference,
  onRemoveReference,
  onSubmit,
  onSelectVersion,
  onDiscardWorkingVersion,
  onLoadVersions,
}: SlotFunctionalCardProps) {
  const selectedAsset = slot.selected_asset;
  const workingAsset = slot.working_asset;
  const previewAsset = selectedAsset ?? workingAsset;
  const workingIsSelected = Boolean(workingAsset && selectedAsset && (workingAsset.asset_id === selectedAsset.asset_id || workingAsset.version_id === selectedAsset.version_id));
  const submitLabel = selectedAsset || workingAsset ? "Generate another version" : "Generate a version";
  const runtimeClass = `status-${String(slot.runtime_status || "empty").replace(/[^a-z0-9_-]/gi, "-").toLowerCase()}`;
  return (
    <article className={`v2-slot-functional-card ${runtimeClass}`} data-slot-id={slot.slot_id} data-slot-type={slot.slot_type}>
      <button
        className="v2-slot-functional-preview nodrag"
        type="button"
        data-slot-action-target={slot.slot_id}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={(event) => {
          event.stopPropagation();
          onOpenSlotEditor?.(slot.slot_id);
        }}
      >
        <AssetPreview asset={previewAsset} label={slot.title || slot.slot_type} />
        {slot.runtime_status === "running" || slot.runtime_status === "waiting" ? <span className="v2-slot-runtime-sheen" aria-hidden="true" /> : null}
        <span className="v2-slot-functional-status">{slot.runtime_status}</span>
      </button>
      <div className="v2-slot-functional-meta">
        <strong>{slot.slot_type.replace(/_/g, " ")}</strong>
        <span>{slot.prompt || "No slot prompt"}</span>
        {slot.warnings.length ? <em>{slot.warnings[0].message}</em> : null}
      </div>
      <section className="v2-slot-functional-versions" aria-label={`${slot.slot_type} versions`}>
        <div className="v2-slot-functional-version is-selected">
          <strong>Selected version</strong>
          <AssetPreview asset={selectedAsset} label={`${slot.slot_type} selected`} />
          <CopyReferenceButton asset={selectedAsset} />
        </div>
        {workingAsset && !workingIsSelected ? (
          <div className="v2-slot-functional-version is-working">
            <strong>Working version</strong>
            <AssetPreview asset={workingAsset} label={`${slot.slot_type} working`} />
            <em>Not used in current workflow</em>
            <div className="v2-slot-functional-version-actions">
              <CopyReferenceButton asset={workingAsset} />
              <button
                type="button"
                className="small-action"
                onClick={(event) => {
                  event.stopPropagation();
                  onSelectVersion?.(slot.slot_id, workingAsset.version_id);
                }}
              >
                Use this version
              </button>
              <button
                type="button"
                className="small-action"
                onClick={(event) => {
                  event.stopPropagation();
                  onDiscardWorkingVersion?.(slot.slot_id);
                }}
              >
                Discard working version
              </button>
            </div>
          </div>
        ) : null}
        {slot.history_assets.length ? (
          <details className="v2-slot-functional-history">
            <summary onClick={(event) => event.stopPropagation()}>History versions</summary>
            {slot.history_assets.map((asset) => (
              <div className="v2-slot-functional-version is-history" key={`${asset.asset_id}:${asset.version_id}`}>
                <strong>History version</strong>
                <AssetPreview asset={asset} label={`${slot.slot_type} history`} />
                <CopyReferenceButton asset={asset} />
                <button
                  type="button"
                  className="small-action"
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelectVersion?.(slot.slot_id, asset.version_id);
                  }}
                >
                  Use this version
                </button>
              </div>
            ))}
          </details>
        ) : onLoadVersions ? (
          <button
            type="button"
            className="small-action"
            onClick={(event) => {
              event.stopPropagation();
              onLoadVersions(slot.slot_id);
            }}
          >
            View history
          </button>
        ) : null}
      </section>
      {isOpen && draft && onChangePrompt && onSubmit ? (
        <SlotMicroPromptComposer
          slotId={slot.slot_id}
          draft={draft}
          referenceAssets={referenceAssets}
          onChangePrompt={onChangePrompt}
          onChangeNegativePrompt={onChangeNegativePrompt}
          onUploadReference={onUploadReference}
          onSelectLibraryReference={onSelectLibraryReference}
          onRemoveReference={onRemoveReference}
          onSubmit={onSubmit}
          submitLabel={submitLabel}
        />
      ) : null}
    </article>
  );
}

function AssetPreview({ asset, label }: { asset?: AssetVersionV2 | null; label: string }) {
  if (asset && isIdOnlyAssetVersion(asset)) return <span className="v2-slot-functional-placeholder">Asset metadata syncing</span>;
  const url = usableAssetVersionUrl(asset);
  if (!asset || !url) return <span className="v2-slot-functional-placeholder">No media yet</span>;
  if (asset.media_type === "image") return <img src={url} alt={label} loading="lazy" decoding="async" />;
  if (asset.media_type === "video") return <DeferredVideo src={url} muted playsInline preload="metadata" />;
  if (asset.media_type === "audio") return <span className="v2-slot-functional-placeholder">Audio</span>;
  return <span className="v2-slot-functional-placeholder">{asset.media_type}</span>;
}

function CopyReferenceButton({ asset }: { asset?: AssetVersionV2 | null }) {
  const copyReference = useV2MediaContextMenu();
  const disabled = !asset || !formatV2AssetLocator(asset);
  return (
    <button
      type="button"
      className="small-action"
      disabled={disabled}
      onClick={(event) => {
        event.stopPropagation();
        if (!asset || disabled) return;
        void copyReference(asset.asset_id, asset.version_id);
      }}
    >
      Copy reference
    </button>
  );
}
