import { useState } from "react";
import type {
  AssetLibraryEntitySummary,
  AssetLibraryReference,
  DynamicMediaItem,
  UploadedAsset,
  WorkflowNode,
} from "../../../types";
import { mergeAssetReferences, sanitizeGlobalAssetReferences } from "../../../workflow/assetMentions";
import { workflowNodeIdentity } from "../../../workflow/nodeRunContext";
import type { AssetLibraryPickerTarget } from "../types";
import { libraryEntitiesToReferences, setUniquePrimaryReference } from "./assetLibraryReferenceModel";

type StateSetter<T> = (value: T | ((current: T) => T)) => void;

type WorkflowReferenceStateArgs = {
  selectedPlanNode: WorkflowNode | null | undefined;
  selectedAssets: UploadedAsset[];
  promptLibraryEntities: AssetLibraryEntitySummary[];
  setPromptLibraryEntities: StateSetter<AssetLibraryEntitySummary[]>;
  dynamicItemLibraryEntitiesById: Record<string, AssetLibraryEntitySummary[]>;
  setDynamicItemLibraryEntitiesById: StateSetter<Record<string, AssetLibraryEntitySummary[]>>;
  dynamicItemPrimaryReferenceIdsById: Record<string, string[]>;
  setDynamicItemPrimaryReferenceIdsById: StateSetter<Record<string, string[]>>;
  dynamicItemReferenceTargetId: string | null;
  setDynamicItemReferenceTargetId: StateSetter<string | null>;
};

export function useWorkflowReferenceState(args: WorkflowReferenceStateArgs) {
  const {
    selectedPlanNode,
    selectedAssets,
    promptLibraryEntities,
    setPromptLibraryEntities,
    dynamicItemLibraryEntitiesById,
    setDynamicItemLibraryEntitiesById,
    dynamicItemPrimaryReferenceIdsById,
    setDynamicItemPrimaryReferenceIdsById,
    dynamicItemReferenceTargetId,
    setDynamicItemReferenceTargetId,
  } = args;
  const [nodeRunLibraryEntities, setNodeRunLibraryEntities] = useState<AssetLibraryEntitySummary[]>([]);
  const [revisionLibraryEntities, setRevisionLibraryEntities] = useState<AssetLibraryEntitySummary[]>([]);
  const [pickerTarget, setPickerTarget] = useState<AssetLibraryPickerTarget | null>(null);
  const [promptPrimaryReferenceIds, setPromptPrimaryReferenceIds] = useState<string[]>([]);
  const [nodeRunPrimaryReferenceIds, setNodeRunPrimaryReferenceIds] = useState<string[]>([]);
  const [revisionPrimaryReferenceIds, setRevisionPrimaryReferenceIds] = useState<string[]>([]);
  const [promptMentionReferences, setPromptMentionReferences] = useState<AssetLibraryReference[]>([]);
  const [workflowPromptMentionReferences, setWorkflowPromptMentionReferences] = useState<AssetLibraryReference[]>([]);
  const [nodePromptMentionReferences, setNodePromptMentionReferences] = useState<AssetLibraryReference[]>([]);
  const [overrideMentionReferences, setOverrideMentionReferences] = useState<AssetLibraryReference[]>([]);

  function mergedPromptAssetReferences(extraReferences: AssetLibraryReference[] = promptMentionReferences) {
    return mergeAssetReferences(
      libraryEntitiesToReferences(promptLibraryEntities, {}, { primaryReferenceIds: new Set(promptPrimaryReferenceIds) }),
      extraReferences,
    );
  }

  function mergedWorkflowPromptAssetReferences(extraReferences: AssetLibraryReference[] = workflowPromptMentionReferences) {
    return mergeAssetReferences(
      libraryEntitiesToReferences(promptLibraryEntities, {}, { primaryReferenceIds: new Set(promptPrimaryReferenceIds) }),
      extraReferences,
    );
  }

  function chatAssetReferences(extraReferences: AssetLibraryReference[] = promptMentionReferences) {
    return sanitizeGlobalAssetReferences(mergedPromptAssetReferences(extraReferences), selectedAssets);
  }

  function workflowPromptAssetReferences(extraReferences: AssetLibraryReference[] = workflowPromptMentionReferences) {
    return sanitizeGlobalAssetReferences(mergedWorkflowPromptAssetReferences(extraReferences), selectedAssets);
  }

  function nodeScopedAssetReferences() {
    if (!selectedPlanNode) return [];
    const identity = workflowNodeIdentity(selectedPlanNode);
    return mergeAssetReferences(
      libraryEntitiesToReferences(nodeRunLibraryEntities, { target_node_id: identity.node_id, target_node_type: identity.node_type }, { primaryReferenceIds: new Set(nodeRunPrimaryReferenceIds) }),
      nodePromptMentionReferences,
      overrideMentionReferences,
    ).map((reference) => ({
      ...reference,
      target_node_id: identity.node_id,
      target_node_type: identity.node_type,
      target_node_ids: [identity.node_id],
    }));
  }

  function dynamicItemScopedAssetReferences(item: DynamicMediaItem) {
    if (!selectedPlanNode) return [];
    const identity = workflowNodeIdentity(selectedPlanNode);
    const libraryEntities = dynamicItemLibraryEntitiesById[item.itemId] ?? [];
    const primaryReferenceIds = new Set(dynamicItemPrimaryReferenceIdsById[item.itemId] ?? []);
    return libraryEntitiesToReferences(
      libraryEntities,
      {
        target_node_id: identity.node_id,
        target_node_type: identity.node_type,
        target_node_ids: [identity.node_id],
        target_entity_id: item.itemId,
        item_id: item.itemId,
      },
      { primaryReferenceIds },
    );
  }

  function openDynamicItemLibraryReference(itemId: string) {
    setDynamicItemReferenceTargetId(itemId);
    setPickerTarget("dynamic-item");
  }

  function selectedLibraryEntitiesForTarget(target: AssetLibraryPickerTarget | null) {
    if (target === "prompt") return promptLibraryEntities;
    if (target === "node") return nodeRunLibraryEntities;
    if (target === "revision") return revisionLibraryEntities;
    if (target === "dynamic-item" && dynamicItemReferenceTargetId) return dynamicItemLibraryEntitiesById[dynamicItemReferenceTargetId] ?? [];
    return [];
  }

  function clearReferenceConstraintsForTarget(target: AssetLibraryPickerTarget, entityId: string) {
    if (target === "prompt") setPromptPrimaryReferenceIds((current) => current.filter((id) => id !== entityId));
    if (target === "node") setNodeRunPrimaryReferenceIds((current) => current.filter((id) => id !== entityId));
    if (target === "revision") setRevisionPrimaryReferenceIds((current) => current.filter((id) => id !== entityId));
    if (target === "dynamic-item" && dynamicItemReferenceTargetId) {
      setDynamicItemPrimaryReferenceIdsById((current) => ({
        ...current,
        [dynamicItemReferenceTargetId]: (current[dynamicItemReferenceTargetId] ?? []).filter((id) => id !== entityId),
      }));
    }
  }

  function removeLibraryEntityForTarget(target: AssetLibraryPickerTarget, entityId: string) {
    if (target === "prompt") setPromptLibraryEntities((current) => current.filter((entity) => entity.entity_id !== entityId));
    if (target === "node") setNodeRunLibraryEntities((current) => current.filter((entity) => entity.entity_id !== entityId));
    if (target === "revision") setRevisionLibraryEntities((current) => current.filter((entity) => entity.entity_id !== entityId));
    if (target === "dynamic-item" && dynamicItemReferenceTargetId) {
      setDynamicItemLibraryEntitiesById((current) => ({
        ...current,
        [dynamicItemReferenceTargetId]: (current[dynamicItemReferenceTargetId] ?? []).filter((entity) => entity.entity_id !== entityId),
      }));
    }
    clearReferenceConstraintsForTarget(target, entityId);
  }

  function togglePrimaryReferenceForTarget(target: AssetLibraryPickerTarget, entity: AssetLibraryEntitySummary) {
    const selectedEntities = selectedLibraryEntitiesForTarget(target);
    const update = (current: string[]) => setUniquePrimaryReference(current, selectedEntities, entity);
    if (target === "prompt") setPromptPrimaryReferenceIds(update);
    if (target === "node") setNodeRunPrimaryReferenceIds(update);
    if (target === "revision") setRevisionPrimaryReferenceIds(update);
    if (target === "dynamic-item" && dynamicItemReferenceTargetId) {
      setDynamicItemPrimaryReferenceIdsById((current) => ({
        ...current,
        [dynamicItemReferenceTargetId]: update(current[dynamicItemReferenceTargetId] ?? []),
      }));
    }
  }

  function toggleLibraryEntityForTarget(target: AssetLibraryPickerTarget, entity: AssetLibraryEntitySummary) {
    const removing = selectedLibraryEntitiesForTarget(target).some((item) => item.entity_id === entity.entity_id);
    if (removing) clearReferenceConstraintsForTarget(target, entity.entity_id);
    const update = (current: AssetLibraryEntitySummary[]) => {
      const exists = current.some((item) => item.entity_id === entity.entity_id);
      return exists ? current.filter((item) => item.entity_id !== entity.entity_id) : [...current, entity];
    };
    if (target === "prompt") setPromptLibraryEntities(update);
    if (target === "node") setNodeRunLibraryEntities(update);
    if (target === "revision") setRevisionLibraryEntities(update);
    if (target === "dynamic-item" && dynamicItemReferenceTargetId) {
      setDynamicItemLibraryEntitiesById((current) => ({
        ...current,
        [dynamicItemReferenceTargetId]: update(current[dynamicItemReferenceTargetId] ?? []),
      }));
    }
  }

  return {
    state: {
      pickerTarget,
      promptLibraryEntities,
      nodeRunLibraryEntities,
      revisionLibraryEntities,
      dynamicItemLibraryEntitiesById,
      promptPrimaryReferenceIds,
      nodeRunPrimaryReferenceIds,
      revisionPrimaryReferenceIds,
      promptMentionReferences,
      workflowPromptMentionReferences,
      nodePromptMentionReferences,
      overrideMentionReferences,
    },
    actions: {
      setPickerTarget,
      setPromptLibraryEntities,
      setNodeRunLibraryEntities,
      setRevisionLibraryEntities,
      setPromptPrimaryReferenceIds,
      setNodeRunPrimaryReferenceIds,
      setRevisionPrimaryReferenceIds,
      setPromptMentionReferences,
      setWorkflowPromptMentionReferences,
      setNodePromptMentionReferences,
      setOverrideMentionReferences,
      chatAssetReferences,
      workflowPromptAssetReferences,
      nodeScopedAssetReferences,
      dynamicItemScopedAssetReferences,
      openDynamicItemLibraryReference,
      selectedLibraryEntitiesForTarget,
      toggleLibraryEntityForTarget,
      removeLibraryEntityForTarget,
      togglePrimaryReferenceForTarget,
    },
  };
}
