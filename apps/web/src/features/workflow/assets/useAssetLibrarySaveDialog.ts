import { useCallback, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { api } from "../../../api/client";
import {
  assetLibraryAssetIdsForNode,
  assetLibrarySourceEntityIdForNode,
} from "../../../workflow/assetLibrarySave.ts";
import type { AssetLibraryEntityType, UploadedAsset, WorkflowNode } from "../../../types";
import {
  assetLibraryDisplayNameForNode,
  canSaveNodeToAssetLibrary,
  formatAssetLibraryError,
  inferAssetLibraryEntityType,
  splitAssetLibraryTags,
} from "./assetLibraryReferenceModel.ts";

export type AssetLibrarySaveTarget = {
  node: WorkflowNode;
  entityType: AssetLibraryEntityType;
  sourceEntityId: string | null;
  assetIds: string[];
  displayName: string;
};

type WorkflowIdentity = {
  workflow_id?: string | null;
} | null | undefined;

export type AssetLibrarySaveDialogController = {
  state: {
    assetLibrarySaveTarget: AssetLibrarySaveTarget | null;
    assetLibraryDisplayName: string;
    assetLibraryTags: string;
    assetLibrarySaveFeedback: string;
    savingAssetLibrary: boolean;
  };
  actions: {
    setAssetLibrarySaveTarget: Dispatch<SetStateAction<AssetLibrarySaveTarget | null>>;
    setAssetLibraryDisplayName: Dispatch<SetStateAction<string>>;
    setAssetLibraryTags: Dispatch<SetStateAction<string>>;
    setAssetLibrarySaveFeedback: Dispatch<SetStateAction<string>>;
    openAssetLibrarySaveDialog: () => void;
    saveAssetLibraryTarget: () => Promise<void>;
    submitAssetLibrarySave: () => Promise<void>;
    cancelAssetLibrarySave: () => void;
  };
};

export function useAssetLibrarySaveDialog({
  workflow,
  selectedPlanNode,
  selectedOutputAssets,
  setStatus,
}: {
  workflow: WorkflowIdentity;
  selectedPlanNode?: WorkflowNode | null;
  selectedOutputAssets: UploadedAsset[];
  setStatus: (message: string) => void;
}): AssetLibrarySaveDialogController {
  const [assetLibrarySaveTarget, setAssetLibrarySaveTarget] = useState<AssetLibrarySaveTarget | null>(null);
  const [assetLibraryDisplayName, setAssetLibraryDisplayName] = useState("");
  const [assetLibraryTags, setAssetLibraryTags] = useState("");
  const [assetLibrarySaveFeedback, setAssetLibrarySaveFeedback] = useState("");
  const [savingAssetLibrary, setSavingAssetLibrary] = useState(false);

  const openAssetLibrarySaveDialog = useCallback(() => {
    if (!workflow?.workflow_id || !selectedPlanNode) {
      setStatus("Generate a workflow and select an output node first.");
      return;
    }
    if (!canSaveNodeToAssetLibrary(selectedPlanNode)) {
      setStatus("This node type cannot be saved to the Asset Library in Phase 1.");
      return;
    }
    const entityType = inferAssetLibraryEntityType(selectedPlanNode);
    if (!entityType) {
      setStatus("Choose a supported Asset Library entity type first.");
      return;
    }
    const sourceEntityId = assetLibrarySourceEntityIdForNode(selectedPlanNode, selectedOutputAssets, entityType);
    if (!sourceEntityId) {
      setStatus("Current output is missing a saveable entity id. Run or refresh this node before saving it to the Asset Library.");
      return;
    }
    const assetIds = assetLibraryAssetIdsForNode(selectedOutputAssets, sourceEntityId);
    if (!assetIds.length) {
      setStatus("Current output has no active asset ids to save to the Asset Library.");
      return;
    }
    const target = {
      node: selectedPlanNode,
      entityType,
      sourceEntityId,
      assetIds,
      displayName: assetLibraryDisplayNameForNode(selectedPlanNode, selectedOutputAssets),
    };
    setAssetLibrarySaveTarget(target);
    setAssetLibraryDisplayName(target.displayName);
    setAssetLibraryTags("");
    setAssetLibrarySaveFeedback("");
  }, [selectedOutputAssets, selectedPlanNode, setStatus, workflow?.workflow_id]);

  const saveAssetLibraryTarget = useCallback(async () => {
    if (!workflow?.workflow_id || !assetLibrarySaveTarget) return;
    const displayName = assetLibraryDisplayName.trim();
    if (!displayName) {
      setAssetLibrarySaveFeedback("Enter a display name before saving.");
      return;
    }
    if (!assetLibrarySaveTarget.sourceEntityId) {
      setAssetLibrarySaveFeedback("Current output is missing a saveable entity id. Run or refresh this node before saving.");
      return;
    }
    if (!assetLibrarySaveTarget.assetIds.length) {
      setAssetLibrarySaveFeedback("Current output has no active asset ids to save.");
      return;
    }
    setSavingAssetLibrary(true);
    setAssetLibrarySaveFeedback("");
    try {
      await api.createAssetLibraryEntity({
        source_workflow_id: workflow.workflow_id,
        source_node_id: assetLibrarySaveTarget.node.id,
        source_entity_id: assetLibrarySaveTarget.sourceEntityId,
        entity_type: assetLibrarySaveTarget.entityType,
        display_name: displayName,
        asset_ids: assetLibrarySaveTarget.assetIds,
        tags: splitAssetLibraryTags(assetLibraryTags),
      });
      setAssetLibrarySaveFeedback("Saved to Asset Library.");
      setStatus(`${displayName} saved to Asset Library.`);
    } catch (error) {
      setAssetLibrarySaveFeedback(formatAssetLibraryError(error));
    } finally {
      setSavingAssetLibrary(false);
    }
  }, [assetLibraryDisplayName, assetLibrarySaveTarget, assetLibraryTags, setStatus, workflow?.workflow_id]);

  const cancelAssetLibrarySave = useCallback(() => {
    setAssetLibrarySaveTarget(null);
  }, []);

  return useMemo(
    () => ({
      state: {
        assetLibrarySaveTarget,
        assetLibraryDisplayName,
        assetLibraryTags,
        assetLibrarySaveFeedback,
        savingAssetLibrary,
      },
      actions: {
        setAssetLibrarySaveTarget,
        setAssetLibraryDisplayName,
        setAssetLibraryTags,
        setAssetLibrarySaveFeedback,
        openAssetLibrarySaveDialog,
        saveAssetLibraryTarget,
        submitAssetLibrarySave: saveAssetLibraryTarget,
        cancelAssetLibrarySave,
      },
    }),
    [
      assetLibraryDisplayName,
      assetLibrarySaveFeedback,
      assetLibrarySaveTarget,
      assetLibraryTags,
      cancelAssetLibrarySave,
      openAssetLibrarySaveDialog,
      saveAssetLibraryTarget,
      savingAssetLibrary,
    ],
  );
}
