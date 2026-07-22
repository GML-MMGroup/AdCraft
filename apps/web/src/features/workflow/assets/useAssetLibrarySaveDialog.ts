import { useCallback, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { v2Api } from "../../../api/v2Client.ts";
import {
  assetLibrarySourceEntityIdForNode,
} from "../../../workflow/assetLibrarySave.ts";
import type { UploadedAsset, WorkflowNode } from "../../../types";
import type { V2AssetLibraryCategory } from "../../../types-v2.ts";
import {
  assetLibraryDisplayNameForNode,
  splitAssetLibraryTags,
} from "./assetLibraryReferenceModel.ts";

export type AssetLibrarySaveTarget = {
  node: WorkflowNode;
  entityType: "character" | "scene" | "product";
  libraryCategory: V2AssetLibraryCategory | null;
  sourceEntityId: string | null;
  members: Array<{ asset_id: string; version_id: string; semantic_type: string; is_primary: boolean; is_default_reference: boolean; sort_order: number }>;
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
    saveAssetLibraryTarget: (category?: V2AssetLibraryCategory) => Promise<void>;
    submitAssetLibrarySave: (category?: V2AssetLibraryCategory) => Promise<void>;
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
    const shape = v2AssetLibrarySaveShape(selectedPlanNode);
    if (!shape) {
      setStatus("Choose a supported Asset Library entity type first.");
      return;
    }
    const sourceEntityId = assetLibrarySourceEntityIdForNode(selectedPlanNode, selectedOutputAssets, shape.entityType);
    const members = v2MembersForSave(selectedOutputAssets, sourceEntityId);
    if (!members.length) {
      setStatus("Current output needs V2 asset and version ids before it can be saved.");
      return;
    }
    const target = {
      node: selectedPlanNode,
      entityType: shape.entityType,
      libraryCategory: shape.libraryCategory,
      sourceEntityId,
      members,
      displayName: assetLibraryDisplayNameForNode(selectedPlanNode, selectedOutputAssets),
    };
    setAssetLibrarySaveTarget(target);
    setAssetLibraryDisplayName(target.displayName);
    setAssetLibraryTags("");
    setAssetLibrarySaveFeedback("");
  }, [selectedOutputAssets, selectedPlanNode, setStatus, workflow?.workflow_id]);

  const saveAssetLibraryTarget = useCallback(async (category?: V2AssetLibraryCategory) => {
    if (!workflow?.workflow_id || !assetLibrarySaveTarget) return;
    const displayName = assetLibraryDisplayName.trim();
    if (!displayName) {
      setAssetLibrarySaveFeedback("Enter a display name before saving.");
      return;
    }
    const libraryCategory = assetLibrarySaveTarget.libraryCategory ?? category;
    if (!libraryCategory) {
      setAssetLibrarySaveFeedback("Choose a category before saving this free image.");
      return;
    }
    if (!assetLibrarySaveTarget.members.length) {
      setAssetLibrarySaveFeedback("Current output needs V2 asset and version ids before saving.");
      return;
    }
    setSavingAssetLibrary(true);
    setAssetLibrarySaveFeedback("");
    try {
      await v2Api.createAssetLibraryEntity({
        entity_type: assetLibrarySaveTarget.entityType,
        library_category: libraryCategory,
        display_name: displayName,
        description: null,
        tags: splitAssetLibraryTags(assetLibraryTags),
        source: { type: "members", members: assetLibrarySaveTarget.members },
      });
      setAssetLibrarySaveFeedback("Saved to Asset Library.");
      setStatus(`${displayName} saved to Asset Library.`);
    } catch (error) {
      setAssetLibrarySaveFeedback(error instanceof Error ? error.message : "Saving to My Assets failed.");
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

function v2AssetLibrarySaveShape(node: WorkflowNode): { entityType: "character" | "scene" | "product"; libraryCategory: V2AssetLibraryCategory | null } | null {
  const nodeType = String(node.node_type ?? node.type ?? node.id ?? "").toLowerCase();
  if (nodeType.includes("character")) return { entityType: "character", libraryCategory: "characters" };
  if (nodeType.includes("scene")) return { entityType: "scene", libraryCategory: "scenes" };
  if (nodeType.includes("product")) return { entityType: "product", libraryCategory: "props" };
  if (nodeType.includes("free-generation") || nodeType.includes("free_generation")) return { entityType: "product", libraryCategory: null };
  return null;
}

function v2MembersForSave(assets: UploadedAsset[], sourceEntityId: string | null) {
  const scoped = sourceEntityId
    ? assets.filter((asset) => asset.entity_id === sourceEntityId || asset.metadata?.entity_id === sourceEntityId || asset.metadata?.source_entity_id === sourceEntityId)
    : assets;
  const candidates = scoped.length ? scoped : assets;
  const seen = new Set<string>();
  return candidates.flatMap((asset, index) => {
    const rawVersionId = asset.version_id ?? asset.version;
    const versionId = typeof rawVersionId === "string" ? rawVersionId : "";
    if (!asset.asset_id || !versionId) return [];
    const key = `${asset.asset_id}:${versionId}`;
    if (seen.has(key)) return [];
    seen.add(key);
    return [{
      asset_id: asset.asset_id,
      version_id: versionId,
      semantic_type: asset.semantic_type || (asset.asset_type === "video" ? "video" : "image"),
      is_primary: index === 0,
      is_default_reference: true,
      sort_order: index,
    }];
  });
}
