import { useCallback, useMemo, useState } from "react";
import type { AssetLibraryEntitySummary } from "../../../types";
import { setUniquePrimaryReference } from "./assetLibraryReferenceModel";

export function useDynamicItemDraftState() {
  const [libraryEntitiesById, setLibraryEntitiesById] = useState<Record<string, AssetLibraryEntitySummary[]>>({});
  const [primaryReferenceIdsById, setPrimaryReferenceIdsById] = useState<Record<string, string[]>>({});
  const [referenceTargetId, setReferenceTargetId] = useState<string | null>(null);
  const [promptDrafts, setPromptDrafts] = useState<Record<string, string>>({});
  const [promptSavingById, setPromptSavingById] = useState<Record<string, boolean>>({});
  const [runningById, setRunningById] = useState<Record<string, boolean>>({});

  const resetDynamicItemState = useCallback(() => {
    setReferenceTargetId(null);
    setLibraryEntitiesById({});
    setPrimaryReferenceIdsById({});
    setPromptDrafts({});
    setRunningById({});
  }, []);

  const changeDynamicItemPrompt = useCallback((itemId: string, value: string) => {
    setPromptDrafts((current) => ({ ...current, [itemId]: value }));
  }, []);

  const removeDynamicItemLibraryEntity = useCallback((itemId: string, entityId: string) => {
    setLibraryEntitiesById((current) => ({
      ...current,
      [itemId]: (current[itemId] ?? []).filter((entity) => entity.entity_id !== entityId),
    }));
    setPrimaryReferenceIdsById((current) => ({
      ...current,
      [itemId]: (current[itemId] ?? []).filter((id) => id !== entityId),
    }));
  }, []);

  const toggleDynamicItemPrimaryReference = useCallback((itemId: string, entity: AssetLibraryEntitySummary) => {
    const selectedEntities = libraryEntitiesById[itemId] ?? [];
    setPrimaryReferenceIdsById((current) => ({
      ...current,
      [itemId]: setUniquePrimaryReference(current[itemId] ?? [], selectedEntities, entity),
    }));
  }, [libraryEntitiesById]);

  return useMemo(
    () => ({
      state: {
        libraryEntitiesById,
        primaryReferenceIdsById,
        referenceTargetId,
        promptDrafts,
        promptSavingById,
        runningById,
      },
      actions: {
        setLibraryEntitiesById,
        setPrimaryReferenceIdsById,
        setReferenceTargetId,
        setPromptDrafts,
        setPromptSavingById,
        setRunningById,
        resetDynamicItemState,
        changeDynamicItemPrompt,
        removeDynamicItemLibraryEntity,
        toggleDynamicItemPrimaryReference,
      },
    }),
    [
      changeDynamicItemPrompt,
      libraryEntitiesById,
      primaryReferenceIdsById,
      promptDrafts,
      promptSavingById,
      referenceTargetId,
      removeDynamicItemLibraryEntity,
      resetDynamicItemState,
      runningById,
      toggleDynamicItemPrimaryReference,
    ],
  );
}
