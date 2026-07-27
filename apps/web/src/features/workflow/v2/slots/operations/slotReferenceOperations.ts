import {
  createSlotReferenceArtifactOperations,
} from "./slotReferenceArtifacts.ts";
import {
  createSlotReferenceAttachmentOperations,
} from "./slotReferenceAttachmentOperations.ts";
import {
  createSlotReferenceDraftOperations,
} from "./slotReferenceDraftOperations.ts";
import {
  createSlotReferenceLibraryOperations,
} from "./slotReferenceLibraryOperations.ts";
import type {
  SlotReferenceOperationDependencies,
} from "./slotReferencePorts.ts";

export function createSlotReferenceOperations(
  dependencies: SlotReferenceOperationDependencies,
) {
  const artifacts = createSlotReferenceArtifactOperations(dependencies);
  const draftOperations = createSlotReferenceDraftOperations({
    ...dependencies,
    artifacts,
  });
  const attachmentOperations = createSlotReferenceAttachmentOperations({
    ...dependencies,
    artifacts,
  });
  const libraryOperations = createSlotReferenceLibraryOperations({
    ...dependencies,
    artifacts,
  });

  return {
    syncV2SlotPromptReferences:
      draftOperations.syncV2SlotPromptReferences,
    uploadV2SlotReference:
      attachmentOperations.uploadV2SlotReference,
    selectV2SlotLibraryReference:
      attachmentOperations.selectV2SlotLibraryReference,
    replaceV2SlotWithLibraryEntity:
      libraryOperations.replaceV2SlotWithLibraryEntity,
    removeV2SlotReference:
      libraryOperations.removeV2SlotReference,
    ensureV2SlotDraftReferences:
      draftOperations.ensureV2SlotDraftReferences,
    attachPromptReferencesToSlot:
      draftOperations.attachPromptReferencesToSlot,
    attachPromptReferencesToItem:
      draftOperations.attachPromptReferencesToItem,
    attachV2Reference:
      attachmentOperations.attachV2Reference,
    removeV2Reference:
      attachmentOperations.removeV2Reference,
  };
}
