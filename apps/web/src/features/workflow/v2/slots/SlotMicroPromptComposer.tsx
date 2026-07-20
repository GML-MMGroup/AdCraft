import { AssetsIcon, CloseIcon, SaveIcon, SendIcon, UploadIcon } from "../../../../icons";
import type { AssetVersionV2 } from "../../../../types-v2.ts";
import { versionedMediaPath } from "../../../../workflow/mediaPreview.ts";
import { usableAssetVersionUrl } from "../../../../workflow-v2/selectors.ts";
import type { SlotMicroEditDraft } from "./useSlotMicroEdit.ts";

type SlotMicroPromptComposerProps = {
  slotId: string;
  draft: SlotMicroEditDraft;
  referenceAssets?: AssetVersionV2[];
  libraryOptions?: Array<{ entity_id: string; display_name?: string }>;
  onChangePrompt: (slotId: string, prompt: string) => void;
  onChangeNegativePrompt?: (slotId: string, negativePrompt: string) => void;
  onUploadReference?: (slotId: string, files: FileList) => void;
  onSelectLibraryReference?: (slotId: string, entityId: string) => void;
  onRemoveReference?: (slotId: string, reference: { source: "reference_asset" | "uploaded_asset" | "library_entity"; asset_id?: string; entity_id?: string; relation_id?: string | null; library_asset_id?: string | null }) => void;
  onOpenReplaceLibrary?: (slotId: string) => void;
  onOpenSaveToLibrary?: (slotId: string) => void;
  onSubmit: (slotId: string) => void;
  submitLabel?: string;
};

export function SlotMicroPromptComposer({
  slotId,
  draft,
  referenceAssets = [],
  libraryOptions = [],
  onChangePrompt,
  onChangeNegativePrompt,
  onUploadReference,
  onSelectLibraryReference,
  onRemoveReference,
  onOpenReplaceLibrary,
  onOpenSaveToLibrary,
  onSubmit,
  submitLabel = "Generate a version",
}: SlotMicroPromptComposerProps) {
  const attachmentAssetIds = new Set(draft.attachments.map((attachment) => attachment.source_asset_id).filter(Boolean));
  const referenceAssetById = new Map(referenceAssets.map((asset) => [asset.asset_id, asset]));
  const legacyReferenceAssets = referenceAssets.filter((asset) => !attachmentAssetIds.has(asset.asset_id));
  return (
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events -- The composer stops canvas drag propagation; controls inside remain native form elements.
    <section
      className="slot-micro-prompt-composer nodrag"
      data-slot-micro-composer={slotId}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => event.stopPropagation()}
    >
      <label>
        <span>Prompt</span>
        <textarea
          value={draft.prompt}
          style={{ resize: "vertical" }}
          onChange={(event) => onChangePrompt(slotId, event.target.value)}
        />
      </label>
      <label>
        <span>Negative prompt</span>
        <textarea
          value={draft.negative_prompt ?? ""}
          style={{ resize: "vertical" }}
          onChange={(event) => onChangeNegativePrompt?.(slotId, event.target.value)}
        />
      </label>
      <div className="slot-micro-attachment-actions">
        <label className="small-action icon-only slot-upload-trigger" aria-label="Upload reference" title="Upload reference">
          <UploadIcon />
          <input
            type="file"
            accept="image/*,video/*,audio/*"
            hidden
            multiple
            onChange={(event) => {
              if (event.currentTarget.files?.length) onUploadReference?.(slotId, event.currentTarget.files);
              event.currentTarget.value = "";
            }}
          />
        </label>
        {libraryOptions.length ? (
          <select value="" aria-label="Select library reference" onChange={(event) => {
            if (event.target.value) onSelectLibraryReference?.(slotId, event.target.value);
          }}>
            <option value="">Library reference</option>
            {libraryOptions.map((option) => (
              <option key={option.entity_id} value={option.entity_id}>
                {option.display_name || option.entity_id}
              </option>
            ))}
          </select>
        ) : null}
      </div>
      <div className="slot-micro-attachment-preview-strip" aria-label="Slot scoped attachment previews">
        {draft.attachments.map((attachment) => {
          const asset = attachment.source_asset_id ? referenceAssetById.get(attachment.source_asset_id) : undefined;
          const previewUrl = asset
            ? versionedMediaPath(attachment.preview_url ?? asset.public_url ?? asset.thumbnail_path, asset)
            : attachment.preview_url ?? null;
          const label = attachment.filename ?? asset?.semantic_type ?? attachment.library_entity_id ?? attachment.source_asset_id ?? attachment.source;
          return (
            <span className={`attachment-preview status-${attachment.status}`} key={attachment.id} data-asset-id={attachment.source_asset_id ?? undefined} data-relation-id={attachment.relation_id ?? undefined}>
              {previewUrl ? <img src={previewUrl} alt={label} loading="lazy" decoding="async" /> : <i>{attachment.source}</i>}
              <span className="attachment-status">{attachment.status}</span>
              {attachment.error ? <span className="attachment-error">{attachment.error}</span> : null}
              <button
                type="button"
                aria-label="Remove attachment"
                title="Remove attachment"
                onClick={() =>
                  onRemoveReference?.(slotId, {
                    source: attachment.source === "asset_library" ? "library_entity" : attachment.source === "upload" ? "uploaded_asset" : "reference_asset",
                    asset_id: attachment.source_asset_id ?? undefined,
                    entity_id: attachment.library_entity_id ?? undefined,
                    relation_id: attachment.relation_id,
                    library_asset_id: attachment.library_asset_id,
                  })
                }
              >
                <CloseIcon />
              </button>
            </span>
          );
        })}
        {legacyReferenceAssets.map((asset) => (
          <span className="attachment-preview" key={asset.asset_id} data-asset-id={asset.asset_id}>
            {asset.media_type === "image" && usableAssetVersionUrl(asset) ? <img src={usableAssetVersionUrl(asset)} alt={asset.semantic_type || asset.asset_id} loading="lazy" decoding="async" /> : <i>{asset.media_type}</i>}
            <button type="button" aria-label="Remove attachment" title="Remove attachment" onClick={() => onRemoveReference?.(slotId, { source: "reference_asset", asset_id: asset.asset_id })}>
              <CloseIcon />
            </button>
          </span>
        ))}
        {draft.uploaded_asset_ids.filter((assetId) => !attachmentAssetIds.has(assetId)).map((assetId) => (
          <span className="attachment-preview" key={assetId} data-asset-id={assetId}>
            <i>uploaded</i>
            <button type="button" aria-label="Remove uploaded attachment" title="Remove uploaded attachment" onClick={() => onRemoveReference?.(slotId, { source: "uploaded_asset", asset_id: assetId })}>
              <CloseIcon />
            </button>
          </span>
        ))}
        {draft.library_entity_ids.filter((entityId) => !draft.attachments.some((attachment) => attachment.library_entity_id === entityId)).map((entityId) => (
          <span className="attachment-preview" key={entityId} data-entity-id={entityId}>
            <i>library</i>
            <button type="button" aria-label="Remove library attachment" title="Remove library attachment" onClick={() => onRemoveReference?.(slotId, { source: "library_entity", entity_id: entityId })}>
              <CloseIcon />
            </button>
          </span>
        ))}
      </div>
      <div className="slot-micro-footer">
        {draft.error ? <span className="slot-micro-error">{draft.error}</span> : null}
        <div className="slot-micro-secondary-actions">
          <button type="button" className="small-action icon-only" aria-label="Replace from asset library" title="Replace from asset library" onClick={() => onOpenReplaceLibrary?.(slotId)}>
            <AssetsIcon />
          </button>
          <button type="button" className="small-action icon-only" aria-label="Save as resource" title="Save as resource" onClick={() => onOpenSaveToLibrary?.(slotId)}>
            <SaveIcon />
          </button>
        </div>
        <button type="button" className="small-action icon-only slot-micro-submit" aria-label={draft.isSubmitting ? "Generating" : submitLabel} title={draft.isSubmitting ? "Generating" : submitLabel} data-source-action="slot_micro_prompt_send" disabled={draft.isSubmitting} onClick={() => onSubmit(slotId)}>
          <SendIcon />
        </button>
      </div>
    </section>
  );
}
