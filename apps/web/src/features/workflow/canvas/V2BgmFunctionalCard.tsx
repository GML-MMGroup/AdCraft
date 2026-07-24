import { ConfirmIcon, TrashIcon } from "../../../icons.tsx";
import { usableAssetVersionUrl } from "../../../workflow-v2/selectors.ts";
import { isV2BgmFunctionalSlot, type V2RegionFunctionalItemView, type V2RegionFunctionalSlotView } from "../v2/region/v2RegionFunctionalModel.ts";
import { NodePreviewLoading } from "./NodePreviewLoading.tsx";
import { V2AudioPlayer } from "./V2AudioPlayer.tsx";

export interface V2BgmFunctionalCardProps {
  item: V2RegionFunctionalItemView;
  audioMode?: string | null;
  openSlotId: string | null;
  onOpenSlotEditor?: (slotId: string) => void;
  onSelectSlotVersion?: (slotId: string, versionId: string) => void | Promise<void>;
  onDiscardSlotWorkingVersion?: (slotId: string) => void | Promise<void>;
}

const BGM_PROVIDER_UNCONFIGURED = "v2_bgm_provider_unconfigured_soft_skip";
type BgmStatusCopy = {
  tone: "warning" | "muted" | "danger";
  title: string;
  detail: string | null;
};

// eslint-disable-next-line react-refresh/only-export-components -- Exported routing predicate belongs beside the component it identifies.
export function isV2BgmFunctionalItem(item: V2RegionFunctionalItemView): boolean {
  return item.item.node_id === "bgm" && item.item.item_type === "bgm" && item.slots.some((slotView) => isV2BgmFunctionalSlot(slotView.slot));
}

export function V2BgmFunctionalCard({
  item,
  audioMode,
  openSlotId,
  onOpenSlotEditor,
  onSelectSlotVersion,
  onDiscardSlotWorkingVersion,
}: V2BgmFunctionalCardProps) {
  const slotView = item.slots.find((candidate) => isV2BgmFunctionalSlot(candidate.slot));
  if (!slotView) return null;

  const slotId = slotView.slot.slot_id;
  const selectedUrl = usableAssetVersionUrl(slotView.selectedAsset) || null;
  const exactWorkingAsset = hasExactWorkingAssetIdentity(slotView) ? slotView.workingAsset : undefined;
  const workingUrl = usableAssetVersionUrl(exactWorkingAsset) || null;
  const hasSelectedIdentity = Boolean(slotView.slot.selected_asset_id);
  const hasWorkingIdentity = Boolean(slotView.slot.current_working_asset_id || slotView.slot.current_working_version_id);
  const hasWorkingCandidate = hasWorkingIdentity && isUnselectedWorkingCandidate(slotView);
  const selectedIsSyncing = hasSelectedIdentity && !selectedUrl;
  const workingIsSyncing = hasWorkingCandidate && !workingUrl;
  const isGenerating = slotView.runtimeStatus === "waiting" || slotView.runtimeStatus === "running";
  const generationDisabled = audioMode === "none";
  const status = bgmStatusCopy(slotView, generationDisabled, hasSelectedIdentity);
  const isPromptOpen = openSlotId === slotId;

  return (
    <article className={`workflow-card-preview v2-bgm-functional-card${isPromptOpen ? " is-prompt-open" : ""}${generationDisabled ? " is-audio-disabled" : ""}`} aria-label="BGM card">
      <button
        type="button"
        className="v2-bgm-prompt-trigger nodrag nopan"
        aria-label="Edit BGM prompt"
        data-slot-action-target={slotId}
        disabled={generationDisabled}
        onPointerDown={stopCanvasPropagation}
        onClick={(event) => {
          event.stopPropagation();
          onOpenSlotEditor?.(slotId);
        }}
      >
        <span className="v2-bgm-card-heading">
          <strong>{item.title || "Background music"}</strong>
          <span>{isGenerating ? "Generating" : generationDisabled ? "Disabled" : item.runtimeStatus}</span>
        </span>
        <span>{item.prompt || "Edit the soundtrack prompt"}</span>
      </button>

      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/click-events-have-key-events -- The audio surface must block canvas drag and click propagation. */}
      <section className="v2-bgm-audio-panel nodrag nopan" aria-label="BGM audio versions" onPointerDown={stopCanvasPropagation} onClick={stopCanvasPropagation}>
        {selectedUrl ? (
          <V2AudioPlayer
            src={selectedUrl}
            label="Selected soundtrack"
            durationSeconds={slotView.selectedAsset?.duration_seconds}
            playbackGroup={slotId}
            compact
          />
        ) : selectedIsSyncing ? (
          <div className="v2-bgm-syncing-state" role="status">Selected asset metadata syncing</div>
        ) : generationDisabled ? (
          <div className="v2-bgm-empty-state">
            <strong>Generation disabled</strong>
            <span>No soundtrack will be generated for this video.</span>
          </div>
        ) : (
          <div className="v2-bgm-empty-state">
            <strong>No soundtrack selected</strong>
            <span>Use the prompt to generate background music.</span>
          </div>
        )}

        {isGenerating ? <NodePreviewLoading type="audio" /> : null}

        {hasWorkingCandidate && workingUrl && exactWorkingAsset ? (
          <div className="v2-bgm-working-candidate">
            <V2AudioPlayer
              src={workingUrl}
              label="Working soundtrack candidate"
              durationSeconds={exactWorkingAsset.duration_seconds}
              playbackGroup={slotId}
              compact
            />
            <div className="v2-bgm-working-actions" aria-label="Working soundtrack actions">
              <button
                type="button"
                className="v2-bgm-action"
                aria-label="Use Working soundtrack"
                title="Use Working soundtrack"
                disabled={generationDisabled}
                onPointerDown={stopCanvasPropagation}
                onClick={(event) => {
                  event.stopPropagation();
                  void onSelectSlotVersion?.(slotId, exactWorkingAsset.version_id);
                }}
              >
                <ConfirmIcon />
              </button>
              <button
                type="button"
                className="v2-bgm-action is-discard"
                aria-label="Discard Working soundtrack"
                title="Discard Working soundtrack"
                disabled={generationDisabled}
                onPointerDown={stopCanvasPropagation}
                onClick={(event) => {
                  event.stopPropagation();
                  void onDiscardSlotWorkingVersion?.(slotId);
                }}
              >
                <TrashIcon />
              </button>
            </div>
          </div>
        ) : null}
        {workingIsSyncing ? <div className="v2-bgm-syncing-state" role="status">Working asset metadata syncing</div> : null}
      </section>

      {status ? (
        <div className={`v2-bgm-status is-${status.tone}`} aria-live="polite">
          <strong>{status.title}</strong>
          {status.detail ? <span>{status.detail}</span> : null}
        </div>
      ) : null}
    </article>
  );
}

function bgmStatusCopy(slotView: V2RegionFunctionalSlotView, generationDisabled: boolean, hasSelectedIdentity: boolean): BgmStatusCopy | null {
  if (slotView.runtimeErrorCode === BGM_PROVIDER_UNCONFIGURED) {
    return { tone: "warning", title: "BGM provider not configured", detail: "The final video can continue without music." };
  }
  if (generationDisabled) {
    return {
      tone: "muted",
      title: "Audio disabled",
      detail: hasSelectedIdentity ? "The retained soundtrack will not be used in the final video." : "No soundtrack will be generated for this video.",
    };
  }
  if (slotView.runtimeStatus === "skipped") {
    return { tone: "muted", title: "BGM generation skipped", detail: "The final video can continue without music." };
  }
  if (slotView.runtimeStatus === "failed") {
    return { tone: "danger", title: "BGM generation failed", detail: "Try generating the soundtrack again." };
  }
  return null;
}

function isUnselectedWorkingCandidate(slotView: V2RegionFunctionalSlotView) {
  if (slotView.hasUnselectedWorkingVersion) return true;
  if (slotView.slot.current_working_version_id) return slotView.slot.current_working_version_id !== slotView.selectedAsset?.version_id;
  return slotView.slot.current_working_asset_id !== slotView.slot.selected_asset_id;
}

function hasExactWorkingAssetIdentity(slotView: V2RegionFunctionalSlotView) {
  const workingAsset = slotView.workingAsset;
  if (!workingAsset) return false;
  const { current_working_asset_id: assetId, current_working_version_id: versionId } = slotView.slot;
  if (!assetId && !versionId) return false;
  return (!assetId || workingAsset.asset_id === assetId) && (!versionId || workingAsset.version_id === versionId);
}

function stopCanvasPropagation(event: { stopPropagation: () => void }) {
  event.stopPropagation();
}
