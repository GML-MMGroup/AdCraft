import { useState } from "react";
import { v2Api } from "../../../api/v2Client.ts";
import type { AssetVersionV2, V2ReferenceAttachRequest, WorkflowV2 } from "../../../types-v2.ts";
import type { V2SlotReferenceRemoval } from "../types.ts";
import type { SlotMicroEditDraft } from "./slots/useSlotMicroEdit.ts";

export function useV2SlotActions(options: {
  workflow?: WorkflowV2 | null;
  workflowId?: string | null;
  activeSlotId?: string | null;
  setActiveSlotId?: (slotId: string | null) => void;
  refreshWorkflow?: (workflowId?: string) => Promise<void>;
  refreshRuntime?: (workflowId?: string) => Promise<void>;
  refreshSlotVersions?: (slotId: string) => Promise<void>;
  applyWorkflow?: (workflow: WorkflowV2) => Promise<void>;
} = {}) {
  const [activeSlotId, setActiveSlotId] = useState<string | null>(options.activeSlotId ?? null);
  const [draftsBySlotId] = useState<Record<string, SlotMicroEditDraft>>({});
  const [referenceAssetsBySlotId] = useState<Record<string, AssetVersionV2[]>>({});
  function openV2SlotEditor(slotId: string) {
    setActiveSlotId(slotId);
    options.setActiveSlotId?.(slotId);
  }
  function changeV2SlotPrompt(slotId: string, prompt: string) {
    void slotId;
    void prompt;
  }
  function changeV2SlotNegativePrompt(slotId: string, negativePrompt: string) {
    void slotId;
    void negativePrompt;
  }
  async function uploadV2SlotReference(slotId: string, files: FileList) {
    void slotId;
    void files;
  }
  async function selectV2SlotLibraryReference(slotId: string, entityId: string) {
    void slotId;
    void entityId;
  }
  async function removeV2SlotReference(slotId: string, reference: V2SlotReferenceRemoval) {
    void slotId;
    void reference;
  }
  async function submitV2SlotMicroPrompt(slotId: string) {
    await regenerateSlot(slotId);
  }
  async function runSelectedV2Slot(slotId = activeSlotId ?? "") {
    await regenerateSlot(slotId);
  }
  async function pollV2ProviderTask(taskId: string) {
    const workflowId = currentWorkflowId();
    if (!workflowId || !taskId) return;
    await v2Api.pollProviderTask(workflowId, taskId);
    await options.refreshRuntime?.(workflowId);
  }
  async function selectV2SlotVersion(slotId: string, versionId: string) {
    const workflowId = currentWorkflowId();
    const assetId = assetIdForVersion(versionId);
    if (!workflowId || !slotId || !assetId) return;
    await v2Api.selectSlotVersion(workflowId, slotId, { asset_id: assetId, version_id: versionId });
    await options.refreshWorkflow?.(workflowId);
    await options.refreshRuntime?.(workflowId);
    await options.refreshSlotVersions?.(slotId);
  }
  async function discardV2WorkingVersion(slotId: string) {
    const workflowId = currentWorkflowId();
    if (!workflowId || !slotId) return;
    const nextWorkflow = await v2Api.discardWorkingVersion(workflowId, slotId);
    await options.applyWorkflow?.(nextWorkflow);
    await options.refreshWorkflow?.(workflowId);
    await options.refreshSlotVersions?.(slotId);
  }
  async function deleteV2SelectedSlotAsset(slotId: string) {
    void slotId;
  }
  async function attachV2Reference(request: V2ReferenceAttachRequest) {
    void request;
  }
  async function removeV2Reference(relationId: string) {
    void relationId;
  }
  async function regenerateSlot(slotId: string) {
    const workflowId = currentWorkflowId();
    if (!workflowId || !slotId) return;
    await v2Api.regenerateSlot(workflowId, slotId);
    await options.refreshRuntime?.(workflowId);
    await options.refreshSlotVersions?.(slotId);
  }
  async function saveSlotPrompt(slotId: string, slotPrompt: string, negativePrompt?: string) {
    const workflowId = currentWorkflowId();
    if (!workflowId || !slotId) return;
    const nextWorkflow = await v2Api.updateSlotPrompt(workflowId, slotId, {
      slot_prompt: slotPrompt,
      negative_prompt: negativePrompt,
    });
    await options.applyWorkflow?.(nextWorkflow);
    await options.refreshWorkflow?.(workflowId);
  }
  function currentWorkflowId() {
    return options.workflowId ?? options.workflow?.workflow_id ?? null;
  }
  function assetIdForVersion(versionId: string) {
    return options.workflow?.asset_versions.find((asset) => asset.version_id === versionId || asset.asset_id === versionId)?.asset_id ?? versionId;
  }
  return {
    activeSlotId,
    draftsBySlotId,
    referenceAssetsBySlotId,
    openV2SlotEditor,
    changeV2SlotPrompt,
    changeV2SlotNegativePrompt,
    uploadV2SlotReference,
    selectV2SlotLibraryReference,
    removeV2SlotReference,
    submitV2SlotMicroPrompt,
    runSelectedV2Slot,
    saveSlotPrompt,
    regenerateSlot,
    pollV2ProviderTask,
    selectV2SlotVersion,
    discardV2WorkingVersion,
    deleteV2SelectedSlotAsset,
    attachV2Reference,
    removeV2Reference,
  };
}
