import { useCallback, useMemo } from "react";
import { v2Api } from "../../../../api/v2Client.ts";
import type {
  AssetVersionV2,
  SlotVersionsResponseV2,
  WorkflowItemV2,
  WorkflowSlotV2,
  WorkflowV2,
} from "../../../../types-v2.ts";
import {
  buildSlotCandidateRegenerateRequest,
  buildSlotLibraryReferenceRegistration,
  buildSlotReferenceAssetRegistration,
  buildSlotReferenceAttachRequest,
  slotReferenceUploadFormData,
} from "../../../../workflow-v2/slotControls.ts";
import { useSlotMicroEdit } from "./useSlotMicroEdit.ts";

export type V2SlotAction =
  | { type: "open"; slotId: string }
  | { type: "change_prompt"; slotId: string; prompt: string }
  | { type: "change_negative_prompt"; slotId: string; negativePrompt: string }
  | { type: "submit_micro_prompt"; slotId: string; sourceAction?: "slot_micro_prompt_send" | "run_current_only" | string }
  | { type: "generate_version"; slotId: string }
  | { type: "use_version"; slotId: string; assetId?: string | null; versionId: string }
  | { type: "discard_working"; slotId: string }
  | { type: "upload_reference"; slotId: string; files: FileList | File[] }
  | {
      type: "attach_library_reference";
      slotId: string;
      libraryEntityId: string;
      libraryAssetId?: string | null;
      semanticType?: string | null;
      referenceRole?: string | null;
    }
  | { type: "remove_reference"; slotId: string; relationId: string };

export type V2SlotCardView = {
  slot: WorkflowSlotV2;
  item: WorkflowItemV2 | null;
  selectedVersion: AssetVersionV2 | null;
  selectedAsset: AssetVersionV2 | null;
  workingVersion: AssetVersionV2 | null;
  workingAsset: AssetVersionV2 | null;
  versionHistory: AssetVersionV2[];
  runtimeStatus: string;
  hasWorkingVersion: boolean;
  needsUseCurrentVersion: boolean;
};

export type V2SlotWorkbenchModuleArgs = {
  workflowId: string | null;
  workflow: WorkflowV2 | null;
  items: WorkflowItemV2[];
  slots: WorkflowSlotV2[];
  assets: AssetVersionV2[];
  slotVersionsById: Record<string, SlotVersionsResponseV2 | undefined>;
  slotRuntimeStatusById: Record<string, string>;
  onWorkflowRefresh: () => Promise<void> | void;
  onAssetRefresh: () => Promise<void> | void;
  onSlotVersionsLoaded: (slotId: string, versions: SlotVersionsResponseV2) => void;
  onError?: (message: string) => void;
};

export type V2SlotWorkbenchModule = {
  openSlotId: string | null;
  slotCardsByNodeId: Record<string, V2SlotCardView[]>;
  dispatchSlotAction: (action: V2SlotAction) => Promise<void>;
  refreshSlot: (slotId: string) => Promise<void>;
};

function versionForAsset(assetsByAssetId: Map<string, AssetVersionV2>, assetId?: string | null) {
  return assetId ? assetsByAssetId.get(assetId) ?? null : null;
}

function versionForVersionId(assetsByVersionId: Map<string, AssetVersionV2>, versionId?: string | null) {
  return versionId ? assetsByVersionId.get(versionId) ?? null : null;
}

function assetIdForVersion(args: V2SlotWorkbenchModuleArgs, slotId: string, versionId: string, explicitAssetId?: string | null) {
  if (explicitAssetId) return explicitAssetId;
  const versions = args.slotVersionsById[slotId]?.versions ?? [];
  return versions.find((version) => version.version_id === versionId)?.asset_id ?? versionId;
}

async function ensureV2SlotDraftReferences(args: V2SlotWorkbenchModuleArgs, slot: WorkflowSlotV2) {
  const workflowId = args.workflowId;
  if (!workflowId) return;
  const draft = args.slotVersionsById[slot.slot_id]?.metadata?.draft;
  void draft;
}

export function useV2SlotWorkbenchModule(args: V2SlotWorkbenchModuleArgs): V2SlotWorkbenchModule {
  const microEdit = useSlotMicroEdit();

  const refreshSlot = useCallback(async (slotId: string) => {
    if (!args.workflowId) return;
    const versions = await v2Api.slotVersions(args.workflowId, slotId);
    args.onSlotVersionsLoaded(slotId, versions);
  }, [args]);

  const dispatchSlotAction = useCallback(async (action: V2SlotAction) => {
    if (!args.workflowId) return;
    try {
      if (action.type === "open") {
        const slot = args.slots.find((candidate) => candidate.slot_id === action.slotId);
        if (slot) microEdit.openSlot(slot);
        return;
      }
      if (action.type === "change_prompt") {
        microEdit.updatePrompt(action.slotId, action.prompt);
        return;
      }
      if (action.type === "change_negative_prompt") {
        microEdit.updateNegativePrompt(action.slotId, action.negativePrompt);
        return;
      }
      if (action.type === "submit_micro_prompt") {
        const slot = args.slots.find((candidate) => candidate.slot_id === action.slotId);
        if (!slot) return;
        const draft = microEdit.state.draftsBySlotId[action.slotId];
        const request = buildSlotCandidateRegenerateRequest(
          draft ?? {
            prompt: slot.slot_prompt ?? "",
            negative_prompt: slot.negative_prompt ?? "",
            reference_asset_ids: slot.explicit_reference_ids ?? [],
            uploaded_asset_ids: [],
            library_entity_ids: [],
          },
          slot,
          action.sourceAction ?? "slot_micro_prompt_send",
        );
        await v2Api.updateSlotPrompt(args.workflowId, action.slotId, {
          slot_prompt: request.slot_prompt,
          negative_prompt: request.negative_prompt,
        });
        await ensureV2SlotDraftReferences(args, slot);
        for (const libraryEntityId of request.library_entity_ids) {
          await v2Api.registerLibraryReference(
            args.workflowId,
            buildSlotLibraryReferenceRegistration(action.slotId, libraryEntityId, null, slot.slot_type),
          );
        }
        for (const sourceAssetId of request.reference_asset_ids) {
          await v2Api.registerReferenceAsset(
            args.workflowId,
            buildSlotReferenceAssetRegistration(action.slotId, { kind: "existing_v2_asset_version", asset_id: sourceAssetId }, slot.slot_type),
          );
          await v2Api.attachReference(args.workflowId, buildSlotReferenceAttachRequest(action.slotId, sourceAssetId, slot.slot_type));
        }
        await v2Api.regenerateSlot(args.workflowId, action.slotId);
        await refreshSlot(action.slotId);
        await args.onAssetRefresh();
        return;
      }
      if (action.type === "generate_version") {
        await v2Api.regenerateSlot(args.workflowId, action.slotId);
        await refreshSlot(action.slotId);
        await args.onAssetRefresh();
        return;
      }
      if (action.type === "use_version") {
        await v2Api.selectSlotVersion(args.workflowId, action.slotId, {
          asset_id: assetIdForVersion(args, action.slotId, action.versionId, action.assetId),
          version_id: action.versionId,
          source_action: "slot_workbench_use_version",
        });
        await refreshSlot(action.slotId);
        await args.onWorkflowRefresh();
        await args.onAssetRefresh();
        return;
      }
      if (action.type === "discard_working") {
        await v2Api.discardWorkingVersion(args.workflowId, action.slotId);
        await refreshSlot(action.slotId);
        await args.onWorkflowRefresh();
        await args.onAssetRefresh();
        return;
      }
      if (action.type === "upload_reference") {
        const formData = slotReferenceUploadFormData(Array.from(action.files), "reference");
        await v2Api.uploadSlotReferenceAsset(args.workflowId, action.slotId, formData);
        await args.onAssetRefresh();
        return;
      }
      if (action.type === "attach_library_reference") {
        await v2Api.registerLibraryReference(args.workflowId, {
          library_entity_id: action.libraryEntityId,
          library_asset_id: action.libraryAssetId ?? null,
          target: { target_type: "slot", slot_id: action.slotId },
          reference_role: action.referenceRole ?? "reference",
          semantic_type: action.semanticType ?? "reference",
          use_as_prompt: true,
        });
        await args.onAssetRefresh();
        return;
      }
      if (action.type === "remove_reference") {
        await v2Api.removeReference(args.workflowId, action.relationId);
        await args.onAssetRefresh();
      }
    } catch (error) {
      args.onError?.(error instanceof Error ? error.message : "Slot action failed");
    }
  }, [args, microEdit, refreshSlot]);

  const slotCardsByNodeId = useMemo<Record<string, V2SlotCardView[]>>(() => {
    const itemsById = new Map(args.items.map((item) => [item.item_id, item]));
    const assetsByAssetId = new Map(args.assets.map((asset) => [asset.asset_id, asset]));
    const assetsByVersionId = new Map(args.assets.map((asset) => [asset.version_id, asset]));
    const grouped: Record<string, V2SlotCardView[]> = {};

    for (const slot of args.slots) {
      const versions = args.slotVersionsById[slot.slot_id];
      const versionHistory = versions?.versions?.length ? versions.versions : args.assets.filter((asset) => asset.slot_id === slot.slot_id);
      const selectedVersion = versionForAsset(assetsByAssetId, versions?.selected_asset_id ?? slot.selected_asset_id);
      const selectedAsset = selectedVersion;
      const workingVersion =
        versionForVersionId(assetsByVersionId, versions?.current_working_version_id ?? slot.current_working_version_id) ??
        versionForAsset(assetsByAssetId, versions?.working_asset_id ?? slot.current_working_asset_id);
      const workingAsset = workingVersion;
      const runtimeStatus = args.slotRuntimeStatusById[slot.slot_id] ?? slot.status ?? "empty";
      const hasWorkingVersion = Boolean(workingVersion ?? slot.current_working_version_id ?? slot.current_working_asset_id);
      const needsUseCurrentVersion = hasWorkingVersion && workingVersion?.asset_id !== selectedVersion?.asset_id;
      const nodeId = slot.node_id || args.workflow?.nodes.find((node) => node.node_id === slot.node_id)?.node_id || "unknown";

      grouped[nodeId] ??= [];
      grouped[nodeId].push({
        slot,
        item: itemsById.get(slot.item_id) ?? null,
        selectedVersion,
        selectedAsset,
        workingVersion,
        workingAsset,
        versionHistory,
        runtimeStatus,
        hasWorkingVersion,
        needsUseCurrentVersion,
      });
    }

    return grouped;
  }, [args.assets, args.items, args.slotRuntimeStatusById, args.slotVersionsById, args.slots, args.workflow?.nodes]);

  return {
    openSlotId: microEdit.state.openSlotId,
    slotCardsByNodeId,
    dispatchSlotAction,
    refreshSlot,
  };
}
