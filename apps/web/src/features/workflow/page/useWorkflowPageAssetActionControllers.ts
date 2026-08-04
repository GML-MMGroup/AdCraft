import { useEffect, useMemo } from "react";
import { buildVideoTimeline } from "../final-composition/finalCompositionTimelineModel.ts";
import { useV2SlotOperations } from "../v2/slots/useV2SlotOperations.ts";
import { useLocalRevisionOperations } from "../assets/useLocalRevisionOperations.ts";
import { useFinalCompositionOperations } from "../final-composition/useFinalCompositionOperations.ts";
import { useDynamicMediaOperations } from "../assets/useDynamicMediaOperations.ts";
import { canShowLocalRevisionActions } from "./workflowPageNodeGuards.ts";
import { getWorkflowNodeType } from "../canvas/workflowNodeModel.ts";
import { useWorkflowV2DerivedState } from "../v2/useWorkflowV2DerivedState.ts";
import { deriveV2SlotRebaseSnapshot } from "../v2/slots/v2SlotRebaseSnapshot.ts";
import type { WorkflowPageAssetActionControllersArgs } from "./workflowPageContracts.ts";

export function useWorkflowPageAssetActionControllers(args: WorkflowPageAssetActionControllersArgs) {
  const videoTimeline = useMemo(
    () => buildVideoTimeline(
      args.timeline.workflowId,
      args.timeline.exportSettings,
      args.timeline.mediaStatus,
      args.timeline.nodeRuns,
      args.timeline.canvasNodes,
    ),
    [
      args.timeline.canvasNodes,
      args.timeline.exportSettings,
      args.timeline.mediaStatus,
      args.timeline.nodeRuns,
      args.timeline.workflowId,
    ],
  );
  const activeV2SlotId = args.slotMicroEdit.state.openSlotId;
  const v2DerivedState = useWorkflowV2DerivedState(args.derived);
  const {
    selectedV2Items,
    selectedV2Slots,
    allV2Slots,
    selectedV2SlotsByItemId,
    slotVersionAssets,
    selectedV2AssetVersions,
    v2ReferenceAssetsBySlotId,
    selectedV2ReferenceAssets,
    v2LibraryReferenceOptions,
    selectedFreeGenerationMediaType,
    selectedFreeAbsorbTargetNodes,
  } = v2DerivedState;
  const rebaseV2SlotDrafts = args.slotMicroEdit.rebaseSlots;
  const slotRebaseSnapshot = useMemo(
    () => deriveV2SlotRebaseSnapshot(args.slotRebaseWorkflow, allV2Slots),
    [allV2Slots, args.slotRebaseWorkflow],
  );

  useEffect(() => {
    rebaseV2SlotDrafts(slotRebaseSnapshot.slots, slotRebaseSnapshot);
  }, [rebaseV2SlotDrafts, slotRebaseSnapshot]);

  const v2SlotOperations = useV2SlotOperations({
    ...args.slotOperations,
    selectedV2Items,
    selectedV2Slots,
    allV2Slots,
    selectedV2AssetVersions,
    activeV2SlotId,
    selectedFreeGenerationMediaType,
    v2SlotMicroEdit: args.slotMicroEdit,
    syncV2Snapshot: args.syncV2Snapshot,
  });
  args.refs.v2SlotOperations.current = v2SlotOperations;

  const localRevisionOperations = useLocalRevisionOperations({
    ...args.localRevisions,
    canShowLocalRevisionActions,
    getWorkflowNodeType,
  });
  args.refs.localRevisionOperations.current = localRevisionOperations;

  const finalCompositionOperations = useFinalCompositionOperations({
    ...args.finalComposition,
    videoTimeline,
    syncV2Snapshot: args.syncV2Snapshot,
    updateLocalRevisionCardState: localRevisionOperations.actions.updateLocalRevisionCardState,
    applyLocalRevisionState: localRevisionOperations.actions.applyLocalRevisionState,
    loadLocalAssetHistory: localRevisionOperations.actions.loadLocalAssetHistory,
  });
  args.refs.finalCompositionOperations.current = finalCompositionOperations;

  const dynamicMediaOperations = useDynamicMediaOperations({
    ...args.dynamicMedia,
    selectedV2Slots,
    submitV2SlotMicroPrompt: v2SlotOperations.actions.submitV2SlotMicroPrompt,
    selectV2SlotVersion: v2SlotOperations.actions.selectV2SlotVersion,
    loadFinalCompositionTimeline: finalCompositionOperations.actions.loadFinalCompositionTimeline,
    loadLocalAssetHistory: localRevisionOperations.actions.loadLocalAssetHistory,
  });

  return {
    videoTimeline,
    activeV2SlotId,
    ...v2DerivedState,
    v2SlotOperations,
    localRevisionOperations,
    finalCompositionOperations,
    dynamicMediaOperations,
  };
}
