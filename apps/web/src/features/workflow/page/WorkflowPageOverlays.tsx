import { AssetLibraryPicker, AssetLibrarySaveModal } from "../assets/AssetLibraryPanels.tsx";
import { assetLibraryEntityTypeForV2ImageSlot } from "../v2/slots/v2SlotAssetLibraryModel.ts";
import { V2FinalCompositionPanel } from "../final-composition/V2FinalCompositionPanel.tsx";
import { MediaLightbox } from "../panels/WorkflowDebugSections.tsx";
import type { WorkflowPageOverlaysArgs } from "./workflowPageContracts.ts";
import {
  selectWorkflowPickerEntity,
  workflowPageSurfaceVisibility,
} from "./workflowPageSurfaceBuilders.ts";

export function WorkflowPageOverlays(args: WorkflowPageOverlaysArgs) {
  const pickerTarget = args.picker.target;

  return (
    <>
      {args.mediaLightbox ? (
        <MediaLightbox
          item={args.mediaLightbox}
          onClose={args.closeMediaLightbox}
        />
      ) : null}

      {args.assetLibrarySave.isV2 && args.assetLibrarySave.target ? (
        <div className="asset-library-save-floating nodrag">
          <AssetLibrarySaveModal
            target={args.assetLibrarySave.target}
            displayName={args.assetLibrarySave.displayName}
            tags={args.assetLibrarySave.tags}
            feedback={args.assetLibrarySave.feedback}
            saving={args.assetLibrarySave.saving}
            onChangeDisplayName={args.assetLibrarySave.setDisplayName}
            onChangeTags={args.assetLibrarySave.setTags}
            onCancel={args.assetLibrarySave.close}
            onSubmit={(category) => void args.assetLibrarySave.submit(category)}
          />
        </div>
      ) : null}

      {pickerTarget ? (
        <AssetLibraryPicker
          selectedEntities={args.picker.selectedEntitiesForTarget(pickerTarget)}
          lockedEntityType={
            pickerTarget === "v2-slot-replace"
              ? assetLibraryEntityTypeForV2ImageSlot(args.picker.activeV2Slot)
              : null
          }
          selectionMode={
            pickerTarget === "v2-slot-replace" ? "single" : "multi"
          }
          onToggle={(entity) =>
            selectWorkflowPickerEntity({
              pickerTarget,
              activeV2SlotId: args.picker.activeV2SlotId,
              entity,
              replaceV2SlotWithLibraryEntity:
                args.picker.replaceV2SlotWithLibraryEntity,
              toggleLibraryEntityForTarget:
                args.picker.toggleLibraryEntityForTarget,
              closePicker: args.picker.close,
            })
          }
          onClose={args.picker.close}
        />
      ) : null}
    </>
  );
}

export function WorkflowPageFinalPanel({
  finalComposition,
}: Pick<WorkflowPageOverlaysArgs, "finalComposition">) {
  const visibility = workflowPageSurfaceVisibility({
    isV2: finalComposition.isV2,
    detailsOpen: finalComposition.detailsOpen,
    selectedNodeId: finalComposition.selectedNodeId,
    workflowId: finalComposition.workflowId,
  });

  return visibility.showV2FinalComposition && finalComposition.workflowId ? (
    <V2FinalCompositionPanel
      workflowId={finalComposition.workflowId}
      offset={finalComposition.offset}
      onOffsetCommit={finalComposition.onOffsetCommit}
      onClose={finalComposition.onClose}
      onWorkflowRefresh={finalComposition.onWorkflowRefresh}
    />
  ) : null;
}
