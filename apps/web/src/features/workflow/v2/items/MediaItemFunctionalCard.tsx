import { useEffect, useState } from "react";
import type { AssetVersionV2, SlotFunctionalCardViewModel, WorkflowItemV2 } from "../../../../types-v2.ts";
import { formatV2AssetLocator } from "../../../../workflow-v2/assetLocators.ts";
import { usableAssetVersionUrl } from "../../../../workflow-v2/selectors.ts";
import { useV2MediaContextMenu } from "../media/useV2MediaContextMenu.ts";
import { SlotFunctionalCard } from "../slots/SlotFunctionalCard.tsx";
import type { SlotMicroEditDraft } from "../slots/useSlotMicroEdit.ts";

type MediaItemFunctionalCardProps = {
  item: WorkflowItemV2;
  slots: SlotFunctionalCardViewModel[];
  productReferences?: AssetVersionV2[];
  openSlotId?: string | null;
  draftsBySlotId?: Record<string, SlotMicroEditDraft>;
  referenceAssetsBySlotId?: Record<string, AssetVersionV2[]>;
  onOpenSlotEditor?: (slotId: string) => void;
  onChangeSlotPrompt?: (slotId: string, prompt: string) => void;
  onChangeSlotNegativePrompt?: (slotId: string, negativePrompt: string) => void;
  onUploadSlotReference?: (slotId: string, files: FileList) => void;
  onSelectSlotLibraryReference?: (slotId: string, entityId: string) => void;
  onRemoveSlotReference?: (slotId: string, reference: { source: "reference_asset" | "uploaded_asset" | "library_entity"; asset_id?: string; entity_id?: string; relation_id?: string | null; library_asset_id?: string | null }) => void;
  onSaveItemPrompt?: (itemId: string, prompt: string) => void;
  onSubmitSlot?: (slotId: string) => void;
  onSelectSlotVersion?: (slotId: string, versionId: string) => void;
  onDiscardSlotWorkingVersion?: (slotId: string) => void;
  onLoadSlotVersions?: (slotId: string) => void;
};

export function MediaItemFunctionalCard({
  item,
  slots,
  productReferences = [],
  openSlotId,
  draftsBySlotId = {},
  referenceAssetsBySlotId = {},
  onOpenSlotEditor,
  onChangeSlotPrompt,
  onChangeSlotNegativePrompt,
  onUploadSlotReference,
  onSelectSlotLibraryReference,
  onRemoveSlotReference,
  onSaveItemPrompt,
  onSubmitSlot,
  onSelectSlotVersion,
  onDiscardSlotWorkingVersion,
  onLoadSlotVersions,
}: MediaItemFunctionalCardProps) {
  const copyReference = useV2MediaContextMenu();
  const itemStatus = slots.some((slot) => slot.runtime_status === "running" || slot.runtime_status === "waiting")
    ? "running"
    : item.status;
  const [itemPromptDraft, setItemPromptDraft] = useState(item.item_prompt ?? item.shot_summary_prompt ?? "");
  useEffect(() => {
    setItemPromptDraft(item.item_prompt ?? item.shot_summary_prompt ?? "");
  }, [item.item_id, item.item_prompt, item.shot_summary_prompt]);
  return (
    <article className={`v2-media-item-functional-card status-${String(itemStatus).replace(/[^a-z0-9_-]/gi, "-").toLowerCase()}`} data-item-id={item.item_id}>
      <section className="v2-media-item-copy">
        <header>
          <strong>{item.display_name || item.item_id}</strong>
          <span>{item.item_type}</span>
        </header>
        {item.description ? <p>{item.description}</p> : null}
        <label className="v2-media-item-prompt-editor">
          <span>{item.item_type === "shot" ? "Shot summary prompt" : "Item prompt"}</span>
          <textarea value={itemPromptDraft} onChange={(event) => setItemPromptDraft(event.target.value)} />
        </label>
        <button type="button" className="small-action" disabled={!onSaveItemPrompt} onClick={() => onSaveItemPrompt?.(item.item_id, itemPromptDraft)}>
          Save prompt
        </button>
        {item.item_type === "final_composition" ? <TimelinePlanView plan={item.timeline_plan} clips={item.timeline_clips ?? []} /> : null}
        {productReferences.length ? (
          <div className="v2-product-reference-list" aria-label={`${item.display_name || item.item_id} uploaded product references`}>
            {productReferences.map((asset) => (
              <span className="product-reference-chip" key={asset.version_id || asset.asset_id} data-asset-id={asset.asset_id}>
                {asset.media_type === "image" && usableAssetVersionUrl(asset) ? <img src={usableAssetVersionUrl(asset)} alt="Uploaded product reference" loading="lazy" decoding="async" /> : null}
                <em>{asset.semantic_type || "product_reference"}</em>
                <button
                  type="button"
                  className="small-action"
                  disabled={!formatV2AssetLocator(asset)}
	                  onClick={(event) => {
	                    event.stopPropagation();
	                    void copyReference(asset.asset_id, asset.version_id);
	                  }}
                >
                  Copy reference
                </button>
              </span>
            ))}
          </div>
        ) : null}
      </section>
      <section className="v2-media-slot-grid" aria-label={`${item.display_name || item.item_id} functional slots`}>
        {slots.map((slot) => (
          <SlotFunctionalCard
            key={slot.slot_id}
            slot={slot}
            isOpen={openSlotId === slot.slot_id}
            draft={draftsBySlotId[slot.slot_id]}
            referenceAssets={referenceAssetsBySlotId[slot.slot_id] ?? []}
            onOpenSlotEditor={onOpenSlotEditor}
            onChangePrompt={onChangeSlotPrompt}
            onChangeNegativePrompt={onChangeSlotNegativePrompt}
            onUploadReference={onUploadSlotReference}
            onSelectLibraryReference={onSelectSlotLibraryReference}
            onRemoveReference={onRemoveSlotReference}
            onSubmit={onSubmitSlot}
            onSelectVersion={onSelectSlotVersion}
            onDiscardWorkingVersion={onDiscardSlotWorkingVersion}
            onLoadVersions={onLoadSlotVersions}
          />
        ))}
      </section>
    </article>
  );
}

function TimelinePlanView({ plan, clips }: { plan?: Record<string, unknown>; clips: Array<Record<string, unknown>> }) {
  return (
    <section className="v2-final-composition-region" aria-label="Final composition timeline">
      <header>
        <strong>timeline_plan</strong>
        <span>{clips.length} timeline_clips</span>
      </header>
      {plan ? <pre>{JSON.stringify(plan, null, 2)}</pre> : <span>No timeline plan yet</span>}
      {clips.length ? (
        <ol>
          {clips.map((clip, index) => (
            <li key={String(clip.clip_id ?? clip.id ?? index)}>
              {String(clip.source_asset_id ?? clip.asset_id ?? `clip-${index + 1}`)}
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
