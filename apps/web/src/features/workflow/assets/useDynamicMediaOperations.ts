import { useEffect, useRef } from "react";
import { api } from "../../../api/client.ts";
import { dispatchAssetLibraryUploadEvent } from "../../../api/workflowNormalizers.ts";
import type { AssetLibraryEntitySummary, AssetLibraryReference, DynamicMediaItem, UploadedAsset, WorkflowGraph, WorkflowNode } from "../../../types.ts";
import type { WorkflowSlotV2 } from "../../../types-v2.ts";
import { buildDynamicMediaItemRegenerateRequest, dynamicMediaItemHistoryFilter } from "../../../workflow/dynamicMediaItems.ts";
import { shouldApplyWorkflowScopedResult } from "../../../workflow/sessionGuards.ts";
import { assetLibraryRefreshDetailFromItemRegenerate, dynamicItemActionAsset } from "./dynamicItemAssetModel.ts";
import {
  isWorkingVersionQualityFailed,
  workingVersionBatchText,
  workingVersionErrorMessage,
  workingVersionResultText,
} from "./dynamicMediaItemListModel.ts";

type StateSetter<T> = (value: T | ((current: T) => T)) => void;

type DynamicMediaOperationsArgs = {
  workflow: WorkflowGraph | null | undefined;
  selectedPlanNode: WorkflowNode | null | undefined;
  selectedNodeId: string;
  selectedV2Slots: WorkflowSlotV2[];
  dynamicItemPromptDrafts: Record<string, string>;
  dynamicItemLibraryEntitiesById: Record<string, AssetLibraryEntitySummary[] | undefined>;
  detailsOpen: boolean;
  activeWorkflowIdRef: React.MutableRefObject<string | null>;
  currentWorkflowIsV2: () => boolean;
  setStatus: StateSetter<string>;
  setDynamicItemPromptSavingById: StateSetter<Record<string, boolean>>;
  setDynamicItemPromptDrafts: StateSetter<Record<string, string>>;
  setDynamicItemRunningById: StateSetter<Record<string, boolean>>;
  setRevisionHistoryTarget: StateSetter<UploadedAsset | null>;
  refreshWorkflowNodes: (workflowId: string) => Promise<unknown>;
  refreshWorkflowGraph: (workflowId: string) => Promise<unknown>;
  refreshMediaStatus: (workflowId: string) => Promise<unknown>;
  refreshSelectedResolvedInputs: (nodeId: string, options?: { force?: boolean }) => Promise<unknown>;
  saveCanvas: (options?: { quiet?: boolean; requireBackend?: boolean }) => Promise<boolean>;
  dynamicItemScopedAssetReferences: (item: DynamicMediaItem) => AssetLibraryReference[];
  noteAffected: (nodes?: string[]) => void;
  submitV2SlotMicroPrompt: (slotId: string, sourceAction?: "slot_micro_prompt_send" | "run_current_only") => Promise<void>;
  selectV2SlotVersion: (slotId: string, versionId: string) => Promise<void>;
  loadFinalCompositionTimeline: (workflowId: string) => Promise<void>;
  loadLocalAssetHistory: (workflowId: string, nodeId: string, asset: UploadedAsset) => Promise<unknown>;
};

export function useDynamicMediaOperations(args: DynamicMediaOperationsArgs) {
  const argsRef = useRef(args);

  useEffect(() => {
    argsRef.current = args;
  }, [args]);

  async function refreshDynamicItemBackendState(workflowId: string, nodeId: string) {
    await argsRef.current.refreshWorkflowNodes(workflowId);
    await argsRef.current.refreshWorkflowGraph(workflowId);
    await argsRef.current.refreshMediaStatus(workflowId);
    await argsRef.current.refreshSelectedResolvedInputs(nodeId, { force: true });
  }

  async function saveDynamicItemPrompt(item: DynamicMediaItem) {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id || !current.selectedPlanNode) {
      current.setStatus("Generate a workflow and select a node before saving an item prompt.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 item prompts are saved through the item and slot workbench controls.");
      return;
    }
    const prompt = current.dynamicItemPromptDrafts[item.itemId] ?? item.prompt;
    if (!prompt.trim()) {
      current.setStatus("Item prompt cannot be empty.");
      return;
    }
    current.setDynamicItemPromptSavingById((drafts) => ({ ...drafts, [item.itemId]: true }));
    current.setStatus(`Saving ${item.displayName} prompt...`);
    try {
      const response = await api.updateNodeItemPrompt(current.workflow.workflow_id, current.selectedPlanNode.id, item.itemId, {
        prompt: prompt.trim(),
        semantic_type: item.semanticType,
        mark_stale: true,
      });
      if (!shouldApplyWorkflowScopedResult(current.workflow.workflow_id, current.activeWorkflowIdRef.current)) return;
      const record = recordFromUnknown(response) ?? {};
      const savedItem = recordFromUnknown(record.item);
      const savedPrompt =
        stringFromUnknown(record.prompt) ||
        stringFromUnknown(record.item_prompt) ||
        stringFromUnknown(savedItem?.prompt) ||
        stringFromUnknown(savedItem?.item_prompt) ||
        prompt.trim();
      current.setDynamicItemPromptDrafts((drafts) => ({ ...drafts, [item.itemId]: savedPrompt }));
      await current.refreshWorkflowNodes(current.workflow.workflow_id);
      await current.refreshSelectedResolvedInputs(current.selectedPlanNode.id, { force: true });
      current.setStatus(`${item.displayName} prompt saved`);
    } catch (error) {
      current.setStatus(error instanceof Error ? error.message : "Item prompt update failed");
    } finally {
      current.setDynamicItemPromptSavingById((drafts) => ({ ...drafts, [item.itemId]: false }));
    }
  }

  async function runDynamicMediaItem(item: DynamicMediaItem) {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id || !current.selectedPlanNode) {
      current.setStatus("Generate a workflow and select a node before regenerating an item.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      const slot = current.selectedV2Slots.find((candidate) => candidate.item_id === item.itemId);
      if (slot) {
        await current.submitV2SlotMicroPrompt(slot.slot_id, "slot_micro_prompt_send");
        return;
      }
      current.setStatus("V2 media regeneration uses slot working-version controls.");
      return;
    }
    const itemPrompt = current.dynamicItemPromptDrafts[item.itemId] ?? item.prompt;
    if (!itemPrompt.trim()) {
      current.setStatus("Item prompt cannot be empty.");
      return;
    }
    const itemForRun = { ...item, prompt: itemPrompt.trim() };
    const workflowId = current.workflow.workflow_id;
    const nodeId = current.selectedPlanNode.id;
    current.setDynamicItemRunningById((running) => ({ ...running, [item.itemId]: true }));
    current.setStatus(`Regenerating ${item.displayName}...`);
    try {
      const saved = await current.saveCanvas({ quiet: true, requireBackend: true });
      if (!saved) return;
      const payload = buildDynamicMediaItemRegenerateRequest(itemForRun, current.dynamicItemScopedAssetReferences(item));
      const libraryEntities = current.dynamicItemLibraryEntitiesById[item.itemId] ?? [];
      if (libraryEntities.length) payload.library_entity_ids = libraryEntities.map((entity) => entity.entity_id);
      if (item.referenceMode === "strict" || item.referenceMode === "best_effort") payload.reference_mode = item.referenceMode;
      const result = await api.regenerateNodeItem(workflowId, nodeId, item.itemId, payload);
      if (!shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) return;
      dispatchAssetLibraryUploadEvent(assetLibraryRefreshDetailFromItemRegenerate(workflowId, nodeId, itemForRun, result));
      await refreshDynamicItemBackendState(workflowId, nodeId);
      current.noteAffected(result.affected_downstream_node_ids ?? result.affected_downstream_nodes);
      current.setStatus(workingVersionResultText(result, `${item.displayName} current working version updated`));
    } catch (error) {
      current.setStatus(error instanceof Error ? error.message : "Item regeneration failed");
    } finally {
      current.setDynamicItemRunningById((running) => ({ ...running, [item.itemId]: false }));
    }
  }

  async function applyDynamicItemCurrentVersion(item: DynamicMediaItem, options: { forceUse?: boolean; useForComposition?: boolean } = {}) {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id || !current.selectedPlanNode) {
      current.setStatus("Generate a workflow and select a node before using a working version.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      const slot = current.selectedV2Slots.find((candidate) => candidate.item_id === item.itemId);
      const workingVersionId = slot?.current_working_version_id || slot?.current_working_asset_id || null;
      if (slot && workingVersionId) {
        await current.selectV2SlotVersion(slot.slot_id, workingVersionId);
        return;
      }
      current.setStatus("V2 working versions are selected from the slot card.");
      return;
    }
    const forceUse = Boolean(options.forceUse);
    const useForComposition = Boolean(options.useForComposition);
    current.setStatus(forceUse ? `Using ${item.displayName} despite quality warning...` : `Using current version for ${item.displayName}...`);
    try {
      const result = await api.useCurrentItemVersion(current.workflow.workflow_id, current.selectedPlanNode.id, item.itemId, {
        force_use_current_version: forceUse,
        use_for_composition: useForComposition,
      });
      if (!shouldApplyWorkflowScopedResult(current.workflow.workflow_id, current.activeWorkflowIdRef.current)) return;
      await refreshDynamicItemBackendState(current.workflow.workflow_id, current.selectedPlanNode.id);
      current.noteAffected(result.affected_downstream_node_ids ?? result.affected_downstream_nodes);
      current.setStatus(workingVersionResultText(result, "已使用 1 个"));
    } catch (error) {
      current.setStatus(workingVersionErrorMessage(error, "Use current version failed"));
    }
  }

  async function batchUseDynamicItemCurrentVersions(items: DynamicMediaItem[], options: { useForComposition?: boolean; scope?: string } = {}) {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id || !current.selectedPlanNode) {
      current.setStatus("Generate a workflow and select a node before using working versions.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      const runnableSlots = current.selectedV2Slots.filter((slot) => slot.current_working_version_id || slot.current_working_asset_id);
      for (const slot of runnableSlots) {
        await current.selectV2SlotVersion(slot.slot_id, slot.current_working_version_id || slot.current_working_asset_id || "");
      }
      current.setStatus(runnableSlots.length ? `Selected ${runnableSlots.length} V2 working version(s).` : "No V2 working versions are ready to use.");
      return;
    }
    const itemIds = items.filter((item) => item.needsApply && !isWorkingVersionQualityFailed(item.currentWorkingVersion)).map((item) => item.itemId);
    const scope = options.scope ?? (itemIds.length ? "listed_items" : "all_needs_apply_in_node");
    current.setStatus("Using current versions...");
    try {
      const result = await api.batchUseCurrentItemVersions(current.workflow.workflow_id, current.selectedPlanNode.id, {
        item_ids: itemIds,
        scope,
        use_for_composition: Boolean(options.useForComposition),
      });
      if (!shouldApplyWorkflowScopedResult(current.workflow.workflow_id, current.activeWorkflowIdRef.current)) return;
      await refreshDynamicItemBackendState(current.workflow.workflow_id, current.selectedPlanNode.id);
      current.noteAffected(result.affected_downstream_node_ids ?? result.affected_downstream_nodes);
      current.setStatus(workingVersionBatchText(result));
    } catch (error) {
      current.setStatus(workingVersionErrorMessage(error, "Batch use current versions failed"));
    }
  }

  async function generateStoryboardShotVideo(item: DynamicMediaItem) {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) {
      current.setStatus("Generate a workflow before generating shot video.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      const videoSlot = current.selectedV2Slots.find((slot) => slot.item_id === item.itemId && String(slot.slot_type).includes("video"));
      if (videoSlot) {
        await current.submitV2SlotMicroPrompt(videoSlot.slot_id, "slot_micro_prompt_send");
        return;
      }
      current.setStatus("V2 storyboard video generation uses the shot video slot.");
      return;
    }
    current.setDynamicItemRunningById((running) => ({ ...running, [`${item.itemId}:video`]: true }));
    current.setStatus(`Generating video for ${item.displayName}...`);
    try {
      const result = await api.generateStoryboardShotVideo(current.workflow.workflow_id, item.itemId, {});
      if (!shouldApplyWorkflowScopedResult(current.workflow.workflow_id, current.activeWorkflowIdRef.current)) return;
      const nodeId = current.selectedPlanNode?.id ?? "storyboard";
      await refreshDynamicItemBackendState(current.workflow.workflow_id, nodeId);
      current.noteAffected(result.affected_downstream_node_ids ?? result.affected_downstream_nodes);
      current.setStatus(result.message || `Shot video generation started for ${item.displayName}`);
    } catch (error) {
      current.setStatus(workingVersionErrorMessage(error, "Shot video generation failed"));
    } finally {
      current.setDynamicItemRunningById((running) => ({ ...running, [`${item.itemId}:video`]: false }));
    }
  }

  async function generateMissingStaleStoryboardVideos() {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) {
      current.setStatus("Generate a workflow before generating shot videos.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      const videoSlots = current.selectedV2Slots.filter((slot) => String(slot.slot_type).includes("video") && (!slot.selected_asset_id || slot.status === "ready" || slot.status === "empty"));
      for (const slot of videoSlots) await current.submitV2SlotMicroPrompt(slot.slot_id, "slot_micro_prompt_send");
      current.setStatus(videoSlots.length ? `Requested ${videoSlots.length} V2 storyboard video slot(s).` : "No V2 storyboard video slots need generation.");
      return;
    }
    current.setStatus("Generating missing or stale shot videos...");
    try {
      const result = await api.generateMissingStaleStoryboardVideos(current.workflow.workflow_id, {});
      if (!shouldApplyWorkflowScopedResult(current.workflow.workflow_id, current.activeWorkflowIdRef.current)) return;
      await refreshDynamicItemBackendState(current.workflow.workflow_id, current.selectedPlanNode?.id ?? "storyboard");
      current.noteAffected(result.affected_downstream_node_ids ?? result.affected_downstream_nodes);
      current.setStatus(workingVersionBatchText(result));
    } catch (error) {
      current.setStatus(workingVersionErrorMessage(error, "Shot video batch generation failed"));
    }
  }

  async function regenerateAllSelectedStoryboardVideos() {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) {
      current.setStatus("Generate a workflow before regenerating shot videos.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      const videoSlots = current.selectedV2Slots.filter((slot) => String(slot.slot_type).includes("video"));
      for (const slot of videoSlots) await current.submitV2SlotMicroPrompt(slot.slot_id, "slot_micro_prompt_send");
      current.setStatus(videoSlots.length ? `Requested ${videoSlots.length} V2 storyboard video slot(s).` : "No V2 storyboard video slots available.");
      return;
    }
    current.setStatus("Regenerating selected shot videos...");
    try {
      const result = await api.regenerateAllSelectedStoryboardVideos(current.workflow.workflow_id, {});
      if (!shouldApplyWorkflowScopedResult(current.workflow.workflow_id, current.activeWorkflowIdRef.current)) return;
      await refreshDynamicItemBackendState(current.workflow.workflow_id, current.selectedPlanNode?.id ?? "storyboard");
      current.noteAffected(result.affected_downstream_node_ids ?? result.affected_downstream_nodes);
      current.setStatus(workingVersionBatchText(result));
    } catch (error) {
      current.setStatus(workingVersionErrorMessage(error, "Shot video regeneration failed"));
    }
  }

  async function applyCurrentStoryboardVideosForComposition(items: DynamicMediaItem[]) {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) {
      current.setStatus("Generate a workflow before using videos for composition.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      const videoSlots = current.selectedV2Slots.filter((slot) => String(slot.slot_type).includes("video") && (slot.current_working_version_id || slot.current_working_asset_id));
      for (const slot of videoSlots) await current.selectV2SlotVersion(slot.slot_id, slot.current_working_version_id || slot.current_working_asset_id || "");
      current.setStatus(videoSlots.length ? `Selected ${videoSlots.length} V2 storyboard video version(s).` : "No V2 storyboard video working versions are ready.");
      return;
    }
    const shotIds = items.filter((item) => item.videoCurrentWorkingVersion && !isWorkingVersionQualityFailed(item.videoCurrentWorkingVersion)).map((item) => item.itemId);
    current.setStatus("Using current shot videos for composition...");
    try {
      const result = await api.useCurrentStoryboardVideosForComposition(current.workflow.workflow_id, {
        shot_ids: shotIds,
        scope: shotIds.length ? "listed_items" : "selected_shots",
      });
      if (!shouldApplyWorkflowScopedResult(current.workflow.workflow_id, current.activeWorkflowIdRef.current)) return;
      await refreshDynamicItemBackendState(current.workflow.workflow_id, current.selectedPlanNode?.id ?? "storyboard");
      if (current.detailsOpen && current.selectedNodeId === "final-composition") await current.loadFinalCompositionTimeline(current.workflow.workflow_id);
      current.noteAffected(result.affected_downstream_node_ids ?? result.affected_downstream_nodes);
      current.setStatus(workingVersionBatchText(result));
    } catch (error) {
      current.setStatus(workingVersionErrorMessage(error, "Use shot videos for composition failed"));
    }
  }

  function openDynamicItemHistory(item: DynamicMediaItem) {
    const current = argsRef.current;
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 item history is shown through slot version history.");
      return;
    }
    const historyFilter = dynamicMediaItemHistoryFilter(item);
    const targetAsset = {
      ...dynamicItemActionAsset(item),
      entity_id: historyFilter.entity_id,
      semantic_type: historyFilter.semantic_type,
    };
    current.setRevisionHistoryTarget(targetAsset);
    if (!current.workflow?.workflow_id || !current.selectedPlanNode) return;
    void current.loadLocalAssetHistory(current.workflow.workflow_id, current.selectedPlanNode.id, targetAsset);
  }

  return {
    actions: {
      saveDynamicItemPrompt,
      runDynamicMediaItem,
      refreshDynamicItemBackendState,
      applyDynamicItemCurrentVersion,
      batchUseDynamicItemCurrentVersions,
      generateStoryboardShotVideo,
      generateMissingStaleStoryboardVideos,
      regenerateAllSelectedStoryboardVideos,
      applyCurrentStoryboardVideosForComposition,
      openDynamicItemHistory,
    },
  };
}

function recordFromUnknown(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function stringFromUnknown(value: unknown): string {
  return typeof value === "string" ? value : "";
}
