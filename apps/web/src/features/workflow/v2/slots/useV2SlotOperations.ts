import { useEffect, useRef } from "react";

import { v2Api } from "../../../../api/v2Client.ts";
import type {
  AssetVersionV2,
  SlotVersionsResponseV2,
  WorkflowItemV2,
  WorkflowSlotV2,
  WorkflowV2,
} from "../../../../types-v2.ts";
import { shouldApplyWorkflowScopedResult } from "../../../../workflow/sessionGuards.ts";
import type { V2WorkflowApplicationCapture } from "../../graph/v2WorkflowApplicationRevisionGuard.ts";
import { createFreeNodeOperations } from "./operations/freeNodeOperations.ts";
import {
  createSlotGenerationOperations,
  createSlotVersionLoader,
} from "./operations/slotGenerationOperations.ts";
import { createSlotMutationRunner } from "./operations/slotMutationRunner.ts";
import { createSlotPromptOperations } from "./operations/slotPromptOperations.ts";
import { createSlotReferenceOperations } from "./operations/slotReferenceOperations.ts";
import { createStoryboardOperations } from "./operations/storyboardOperations.ts";
import type { useSlotMicroEdit } from "./useSlotMicroEdit.ts";

type StateSetter<T> = (value: T | ((current: T) => T)) => void;

type V2SlotOperationsArgs = {
  workflowId: string | null | undefined;
  workflowV2: WorkflowV2 | null | undefined;
  currentWorkflowIsV2: () => boolean;
  activeWorkflowIdRef: React.MutableRefObject<string | null>;
  selectedPlanNode: { id: string } | null | undefined;
  selectedV2Items: WorkflowItemV2[];
  selectedV2Slots: WorkflowSlotV2[];
  allV2Slots: WorkflowSlotV2[];
  selectedV2AssetVersions: Map<string, AssetVersionV2>;
  selectedAssets: Array<{ asset_id: string }>;
  activeV2SlotId: string | null;
  selectedFreeGenerationMediaType: string | null;
  dynamicItemPromptDrafts: Record<string, string>;
  v2SlotVersionsById: Record<
    string,
    { versions?: AssetVersionV2[] } | undefined
  >;
  v2SlotMicroEdit: ReturnType<typeof useSlotMicroEdit>;
  setStatus: StateSetter<string>;
  setSelectedNodeId: StateSetter<string>;
  setDynamicItemPromptSavingById: StateSetter<Record<string, boolean>>;
  setDynamicItemPromptDrafts: StateSetter<Record<string, string>>;
  setV2SlotVersionsById: StateSetter<
    Record<string, SlotVersionsResponseV2 | undefined>
  >;
  applyWorkflowV2: (
    workflow: WorkflowV2,
    options?: { refreshAssetsReason?: string | false },
  ) => Promise<void>;
  refreshV2WorkflowGraph: (workflowId: string) => Promise<WorkflowV2 | null>;
  syncV2Snapshot: (workflowId: string) => Promise<unknown>;
  refreshV2AssetsAndRetryMissing: (
    workflowId: string,
    reason: string,
    workflow?: WorkflowV2 | null,
  ) => Promise<unknown>;
  captureV2WorkflowApplicationRevision: (
    workflowId: string,
  ) => V2WorkflowApplicationCapture;
  isCurrentV2WorkflowApplicationRevision: (
    capture: V2WorkflowApplicationCapture,
    currentActiveWorkflowId: string | null,
  ) => boolean;
  selectedNodeIdRef: React.MutableRefObject<string>;
};

export function useV2SlotOperations(args: V2SlotOperationsArgs) {
  const argsRef = useRef(args);

  useEffect(() => {
    argsRef.current = args;
  }, [args]);

  function v2SlotById(slotId: string) {
    const current = argsRef.current;
    return current.workflowV2?.slots.find((slot) => slot.slot_id === slotId)
      ?? current.allV2Slots.find((slot) => slot.slot_id === slotId)
      ?? current.selectedV2Slots.find((slot) => slot.slot_id === slotId)
      ?? null;
  }

  function setMicroEditSubmitting(
    slotId: string,
    submitting: boolean,
    error?: string,
  ) {
    if (error === undefined) {
      argsRef.current.v2SlotMicroEdit.setSubmitting(slotId, submitting);
      return;
    }
    argsRef.current.v2SlotMicroEdit.setSubmitting(slotId, submitting, error);
  }

  const runner = createSlotMutationRunner({
    getWorkflowId: () => argsRef.current.workflowId,
    currentWorkflowIsV2: () => argsRef.current.currentWorkflowIsV2(),
    getActiveWorkflowId: () => argsRef.current.activeWorkflowIdRef.current,
    captureRevision: (workflowId) => (
      argsRef.current.captureV2WorkflowApplicationRevision(workflowId)
    ),
    isCurrentRevision: (capture, activeWorkflowId) => (
      argsRef.current.isCurrentV2WorkflowApplicationRevision(
        capture,
        activeWorkflowId,
      )
    ),
    applyWorkflow: (workflow, options) => (
      argsRef.current.applyWorkflowV2(workflow, options)
    ),
    refreshWorkflow: (workflowId) => (
      argsRef.current.refreshV2WorkflowGraph(workflowId)
    ),
    refreshAssets: (workflowId, reason, workflow) => (
      argsRef.current.refreshV2AssetsAndRetryMissing(
        workflowId,
        reason,
        workflow,
      )
    ),
    syncSnapshot: (workflowId) => argsRef.current.syncV2Snapshot(workflowId),
  });

  const loadV2SlotVersions = createSlotVersionLoader({
    runner,
    api: v2Api,
    setVersions: (slotId, versions) => {
      argsRef.current.setV2SlotVersionsById((current) => ({
        ...current,
        [slotId]: versions,
      }));
    },
    setStatus: (status) => argsRef.current.setStatus(status),
  });

  const referenceOperations = createSlotReferenceOperations({
    runner,
    api: v2Api,
    getSlot: v2SlotById,
    getWorkflow: () => argsRef.current.workflowV2,
    microEdit: {
      getDraft: (slotId) => (
        argsRef.current.v2SlotMicroEdit.state.draftsBySlotId[slotId]
      ),
      addAttachment: (slotId, attachment, trackRevision) => {
        if (trackRevision === undefined) {
          argsRef.current.v2SlotMicroEdit.addAttachment(slotId, attachment);
          return;
        }
        argsRef.current.v2SlotMicroEdit.addAttachment(
          slotId,
          attachment,
          trackRevision,
        );
      },
      updateAttachment: (slotId, attachmentId, patch) => (
        argsRef.current.v2SlotMicroEdit.updateAttachment(
          slotId,
          attachmentId,
          patch,
        )
      ),
      removeReference: (slotId, reference) => (
        argsRef.current.v2SlotMicroEdit.removeReference(slotId, reference)
      ),
      setSubmitting: setMicroEditSubmitting,
      markClean: (
        slotId,
        slot,
        promptPersisted,
        referenceBaselineAuthoritative,
      ) => argsRef.current.v2SlotMicroEdit.markClean(
        slotId,
        slot,
        promptPersisted,
        referenceBaselineAuthoritative,
      ),
    },
    loadSlotVersions: loadV2SlotVersions,
    setStatus: (status) => argsRef.current.setStatus(status),
  });

  const promptOperations = createSlotPromptOperations({
    runner,
    api: v2Api,
    selection: {
      getSlot: v2SlotById,
      getAllSlots: () => argsRef.current.allV2Slots,
      getSelectedSlots: () => argsRef.current.selectedV2Slots,
      selectNode: (nodeId) => {
        argsRef.current.setSelectedNodeId(nodeId);
        argsRef.current.selectedNodeIdRef.current = nodeId;
      },
    },
    microEdit: {
      getDrafts: () => (
        argsRef.current.v2SlotMicroEdit.state.draftsBySlotId
      ),
      openSlot: (slot) => argsRef.current.v2SlotMicroEdit.openSlot(slot),
      closeSlot: () => argsRef.current.v2SlotMicroEdit.closeSlot(),
      updatePrompt: (slotId, prompt) => (
        argsRef.current.v2SlotMicroEdit.updatePrompt(slotId, prompt)
      ),
      updateNegativePrompt: (slotId, prompt) => (
        argsRef.current.v2SlotMicroEdit.updateNegativePrompt(slotId, prompt)
      ),
      setSubmitting: setMicroEditSubmitting,
      markClean: (slotId, slot, promptPersisted) => (
        argsRef.current.v2SlotMicroEdit.markClean(
          slotId,
          slot,
          promptPersisted,
        )
      ),
    },
    references: {
      ensureDraft: referenceOperations.ensureV2SlotDraftReferences,
    },
    itemPrompts: {
      setSaving: (itemId, saving) => {
        argsRef.current.setDynamicItemPromptSavingById((current) => ({
          ...current,
          [itemId]: saving,
        }));
      },
      setDraft: (itemId, prompt) => {
        argsRef.current.setDynamicItemPromptDrafts((current) => ({
          ...current,
          [itemId]: prompt,
        }));
      },
    },
    setStatus: (status) => argsRef.current.setStatus(status),
  });

  const generationOperations = createSlotGenerationOperations({
    runner,
    api: v2Api,
    readModel: {
      getSlot: v2SlotById,
      getWorkflow: () => argsRef.current.workflowV2,
      getSelectedSlots: () => argsRef.current.selectedV2Slots,
      getSelectedItems: () => argsRef.current.selectedV2Items,
      getSelectedPlanNode: () => argsRef.current.selectedPlanNode,
      getActiveSlotId: () => argsRef.current.activeV2SlotId,
      getVersions: (slotId) => argsRef.current.v2SlotVersionsById[slotId],
      getSelectedAssetVersion: (versionId) => (
        argsRef.current.selectedV2AssetVersions.get(versionId)
      ),
    },
    versions: {
      load: loadV2SlotVersions,
    },
    microEdit: {
      getDraft: (slotId) => (
        argsRef.current.v2SlotMicroEdit.state.draftsBySlotId[slotId]
      ),
      updatePrompt: (slotId, prompt) => (
        argsRef.current.v2SlotMicroEdit.updatePrompt(slotId, prompt)
      ),
      setSubmitting: setMicroEditSubmitting,
      markClean: (slotId, slot, promptPersisted) => (
        argsRef.current.v2SlotMicroEdit.markClean(
          slotId,
          slot,
          promptPersisted,
        )
      ),
    },
    references: {
      ensureDraft: referenceOperations.ensureV2SlotDraftReferences,
      attachPrompt: referenceOperations.attachPromptReferencesToSlot,
    },
    setStatus: (status) => argsRef.current.setStatus(status),
  });

  const storyboardOperations = createStoryboardOperations({
    runner,
    api: v2Api,
    getPromptDraft: (itemId) => (
      argsRef.current.dynamicItemPromptDrafts[itemId]
    ),
    setPromptDraft: (itemId, prompt) => {
      argsRef.current.setDynamicItemPromptDrafts((current) => ({
        ...current,
        [itemId]: prompt,
      }));
    },
    setPromptSaving: (itemId, saving) => {
      argsRef.current.setDynamicItemPromptSavingById((current) => ({
        ...current,
        [itemId]: saving,
      }));
    },
    attachPromptReferences: referenceOperations.attachPromptReferencesToItem,
    setStatus: (status) => argsRef.current.setStatus(status),
  });

  const freeNodeOperations = createFreeNodeOperations({
    runner,
    api: v2Api,
    getSelectedMediaType: () => (
      argsRef.current.selectedFreeGenerationMediaType
    ),
    setStatus: (status) => argsRef.current.setStatus(status),
  });

  async function createV2FinalTimelineClip(sourceAssetId: string) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId || !sourceAssetId) return;
    try {
      const response = await v2Api.createTimelineClip(workflowId, {
        source_asset_id: sourceAssetId,
        clip_type: "video",
        duration: 3,
      });
      if (!shouldApplyWorkflowScopedResult(
        workflowId,
        argsRef.current.activeWorkflowIdRef.current,
      )) return;
      await argsRef.current.applyWorkflowV2(response.workflow);
      argsRef.current.setStatus("V2 timeline clip added");
    } catch (error) {
      argsRef.current.setStatus(
        error instanceof Error ? error.message : "V2 timeline clip create failed",
      );
    }
  }

  async function deleteV2FinalTimelineClip(clipId: string) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId || !clipId) return;
    try {
      const response = await v2Api.deleteTimelineClip(workflowId, clipId);
      if (!shouldApplyWorkflowScopedResult(
        workflowId,
        argsRef.current.activeWorkflowIdRef.current,
      )) return;
      await argsRef.current.applyWorkflowV2(response.workflow);
      argsRef.current.setStatus("V2 timeline clip removed");
    } catch (error) {
      argsRef.current.setStatus(
        error instanceof Error ? error.message : "V2 timeline clip delete failed",
      );
    }
  }

  return {
    actions: {
      saveV2ItemPrompt: promptOperations.saveV2ItemPrompt,
      saveV2SlotPrompt: promptOperations.saveV2SlotPrompt,
      v2SlotById,
      setActiveV2SlotId: promptOperations.setActiveV2SlotId,
      openV2SlotEditor: promptOperations.openV2SlotEditor,
      changeV2SlotPrompt: promptOperations.changeV2SlotPrompt,
      changeV2SlotNegativePrompt: promptOperations.changeV2SlotNegativePrompt,
      syncV2SlotPromptReferences:
        referenceOperations.syncV2SlotPromptReferences,
      uploadV2SlotReference: referenceOperations.uploadV2SlotReference,
      selectV2SlotLibraryReference:
        referenceOperations.selectV2SlotLibraryReference,
      replaceV2SlotWithLibraryEntity:
        referenceOperations.replaceV2SlotWithLibraryEntity,
      removeV2SlotReference: referenceOperations.removeV2SlotReference,
      loadV2SlotVersions,
      defaultV2SlotForCurrentNode:
        generationOperations.defaultV2SlotForCurrentNode,
      submitV2SlotMicroPrompt:
        generationOperations.submitV2SlotMicroPrompt,
      flushV2SlotDrafts: promptOperations.flushV2SlotDrafts,
      submitV2LocalSlotPrompt:
        generationOperations.submitV2LocalSlotPrompt,
      submitV2StoryboardPrompt:
        storyboardOperations.submitV2StoryboardPrompt,
      runSelectedV2Slot: generationOperations.runSelectedV2Slot,
      pollV2ProviderTask: generationOperations.pollV2ProviderTask,
      selectV2SlotVersion: generationOperations.selectV2SlotVersion,
      discardV2WorkingVersion:
        generationOperations.discardV2WorkingVersion,
      deleteV2SelectedSlotAsset:
        generationOperations.deleteV2SelectedSlotAsset,
      attachV2Reference: referenceOperations.attachV2Reference,
      removeV2Reference: referenceOperations.removeV2Reference,
      confirmV2ShotSummary: storyboardOperations.confirmV2ShotSummary,
      createV2FinalTimelineClip,
      deleteV2FinalTimelineClip,
      createV2FreeNode: freeNodeOperations.createV2FreeNode,
      generateV2FreeNode: freeNodeOperations.generateV2FreeNode,
      absorbV2FreeNode: freeNodeOperations.absorbV2FreeNode,
      deleteV2FreeNode: freeNodeOperations.deleteV2FreeNode,
    },
  };
}
