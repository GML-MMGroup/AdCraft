import type { v2Api } from "../../../../../api/v2Client.ts";
import type {
  AssetLibraryEntitySummary,
  AssetLibraryReference,
} from "../../../../../types.ts";
import type { PromptGenerateContext } from "../../../../../components/PromptComposer.tsx";
import type {
  AssetVersionV2,
  V2ReferenceAttachRequest,
  V2RegisterReferenceResponse,
  WorkflowAssetRelationV2,
  WorkflowItemV2,
  WorkflowSlotV2,
  WorkflowV2,
} from "../../../../../types-v2.ts";
import type { V2SlotReferenceRemoval } from "../../../types.ts";
import {
  buildAddSlotReferenceRequest,
  buildSlotLibraryReferenceRegistration,
  buildSlotReferenceAssetRegistration,
  buildSlotReferenceAttachRequest,
} from "../../../../../workflow-v2/slotControls.ts";
import {
  assetPreviewUrl,
  mergeV2ReferenceArtifacts,
  objectUrlForFile,
  referenceRoleForV2SemanticType,
  relationForSourceAsset,
  v2SlotUploadAttachmentId,
} from "../../v2AssetViewModel.ts";
import {
  assetLibraryEntityTypeForV2ImageSlot,
  v2ImageSlotMatchesAssetLibraryEntity,
} from "../v2SlotAssetLibraryModel.ts";
import type {
  SlotMicroEditAttachment,
  SlotMicroEditDraft,
} from "../useSlotMicroEdit.ts";
import type { SlotMutationRunner } from "./slotMutationRunner.ts";

type ReferenceApi = Pick<
  typeof v2Api,
  | "attachReference"
  | "attachSlotReference"
  | "registerLibraryReference"
  | "registerReferenceAsset"
  | "removeReference"
  | "selectSlotVersion"
  | "uploadSlotReferenceAsset"
>;

type ReferenceMicroEdit = {
  getDraft: (slotId: string) => SlotMicroEditDraft | undefined;
  addAttachment: (
    slotId: string,
    attachment: SlotMicroEditAttachment,
    trackRevision?: boolean,
  ) => void;
  updateAttachment: (
    slotId: string,
    attachmentId: string,
    patch: Partial<SlotMicroEditAttachment>,
  ) => void;
  removeReference: (
    slotId: string,
    reference:
      | {
          source: "library_entity";
          entity_id: string;
          library_asset_id?: string | null;
          relation_id?: string | null;
        }
      | {
          source: "uploaded_asset" | "reference_asset";
          asset_id: string;
          relation_id?: string | null;
        },
  ) => void;
  setSubmitting: (slotId: string, submitting: boolean, error?: string) => void;
  markClean: (
    slotId: string,
    slot?: WorkflowSlotV2,
    promptPersisted?: boolean,
    referenceBaselineAuthoritative?: boolean,
  ) => void;
};

type SlotReferenceOperationDependencies = {
  runner: SlotMutationRunner;
  api: ReferenceApi;
  getSlot: (slotId: string) => WorkflowSlotV2 | null;
  getWorkflow: () => WorkflowV2 | null | undefined;
  microEdit: ReferenceMicroEdit;
  loadSlotVersions: (slotId: string) => Promise<unknown>;
  setStatus: (status: string) => void;
};

export function createSlotReferenceOperations(
  dependencies: SlotReferenceOperationDependencies,
) {
  const { api, microEdit, runner, setStatus } = dependencies;

  async function applyV2ReferenceArtifacts(
    workflowId: string,
    revisionCapture: ReturnType<SlotMutationRunner["capture"]>,
    nextWorkflow: WorkflowV2 | null | undefined,
    assets: AssetVersionV2[] = [],
    relations: WorkflowAssetRelationV2[] = [],
  ) {
    if (nextWorkflow) {
      return runner.requireFresh(await runner.applyReconciledWorkflow(
        workflowId,
        revisionCapture,
        nextWorkflow,
      )).workflow;
    }
    if (!assets.length && !relations.length) {
      return (await runner.requireFreshWorkflow(workflowId, revisionCapture))
        .workflow;
    }
    const freshness = await runner.requireFreshWorkflow(
      workflowId,
      revisionCapture,
    );
    const currentWorkflow = freshness.workflow ?? dependencies.getWorkflow();
    if (!currentWorkflow) return null;
    return runner.requireFresh(await runner.applyReconciledWorkflow(
      workflowId,
      revisionCapture,
      mergeV2ReferenceArtifacts(currentWorkflow, assets, relations),
    )).workflow;
  }

  async function applyRegisteredV2SlotReference(
    workflowId: string,
    slotId: string,
    semanticType: string | null | undefined,
    registered: V2RegisterReferenceResponse,
    revisionCapture: ReturnType<SlotMutationRunner["capture"]>,
  ) {
    if (registered.workflow || registered.relation) {
      const workflow = await applyV2ReferenceArtifacts(
        workflowId,
        revisionCapture,
        registered.workflow,
        [registered.asset],
        registered.relation ? [registered.relation] : [],
      );
      return { relation: registered.relation ?? null, workflow };
    }
    const sourceAssetId = registered.source_asset_id
      || registered.asset.asset_id;
    const sourceVersionId = registered.asset.version_id
      || registered.asset.asset_id
      || sourceAssetId;
    const attachCapture = runner.capture(workflowId);
    const attached = await api.attachSlotReference(
      workflowId,
      slotId,
      buildAddSlotReferenceRequest(
        { asset_id: sourceAssetId, version_id: sourceVersionId },
        referenceRoleForV2SemanticType(semanticType),
      ),
    );
    await runner.requireFreshWorkflow(workflowId, attachCapture);
    const workflow = await runner.refreshWorkflowSnapshotAndVersions(workflowId);
    return {
      relation: {
        relation_id: typeof attached.relation_id === "string"
          ? attached.relation_id
          : null,
        relation_type: "reference_for_slot",
        workflow_id: workflowId,
        slot_id: slotId,
        source_asset_id: sourceAssetId,
        asset_id: sourceAssetId,
        version_id: sourceVersionId,
        semantic_type: semanticType ?? null,
      },
      workflow,
    };
  }

  async function attachPromptReferencesToSlot(
    workflowId: string,
    slot: WorkflowSlotV2,
    context?: PromptGenerateContext,
  ) {
    for (const reference of uniqueAssetReferences(
      context?.asset_references ?? [],
    )) {
      if (
        reference.reference_source === "asset_library"
        && reference.entity_id
      ) {
        const revisionCapture = runner.capture(workflowId);
        const registered = await api.registerLibraryReference(
          workflowId,
          buildSlotLibraryReferenceRegistration(
            slot.slot_id,
            reference.entity_id,
            reference.asset_id,
            slot.slot_type,
          ),
        );
        await applyRegisteredV2SlotReference(
          workflowId,
          slot.slot_id,
          slot.slot_type,
          registered,
          revisionCapture,
        );
        continue;
      }
      if (!reference.asset_id) continue;
      const revisionCapture = runner.capture(workflowId);
      const attached = await api.attachReference(
        workflowId,
        buildSlotReferenceAttachRequest(
          slot.slot_id,
          reference.asset_id,
          slot.slot_type,
        ),
      );
      await applyV2ReferenceArtifacts(
        workflowId,
        revisionCapture,
        attached.workflow,
        [],
        attached.relation ? [attached.relation] : [],
      );
    }
  }

  async function attachPromptReferencesToItem(
    workflowId: string,
    item: WorkflowItemV2,
    context?: PromptGenerateContext,
  ) {
    for (const reference of uniqueAssetReferences(
      context?.asset_references ?? [],
    )) {
      if (!reference.asset_id) continue;
      const revisionCapture = runner.capture(workflowId);
      const response = await api.attachReference(workflowId, {
        target_type: "item",
        target_id: item.item_id,
        source_asset_id: reference.asset_id,
        reference_kind: "explicit",
        metadata: {
          semantic_type: reference.role ?? "storyboard_reference",
          reference_source: reference.reference_source,
          library_entity_id: reference.entity_id ?? null,
        },
      });
      await applyV2ReferenceArtifacts(
        workflowId,
        revisionCapture,
        response.workflow,
        [],
        response.relation ? [response.relation] : [],
      );
    }
  }

  function syncV2SlotPromptReferences(
    slotId: string,
    context?: PromptGenerateContext,
  ) {
    const slot = dependencies.getSlot(slotId);
    if (!slot) return;
    for (const reference of uniqueAssetReferences(
      context?.asset_references ?? [],
    )) {
      if (
        reference.reference_source === "asset_library"
        && reference.entity_id
      ) {
        microEdit.addAttachment(slotId, {
          id: `library:${reference.entity_id}:${reference.asset_id ?? ""}`,
          source: "asset_library",
          library_entity_id: reference.entity_id,
          library_asset_id: reference.asset_id,
          semantic_type: reference.role ?? slot.slot_type,
          status: "draft",
        });
        continue;
      }
      if (!reference.asset_id) continue;
      microEdit.addAttachment(slotId, {
        id: `${reference.reference_source ?? "reference_asset"}:${reference.asset_id}`,
        source: "reference_asset",
        source_asset_id: reference.asset_id,
        semantic_type: reference.role ?? slot.slot_type,
        status: "registered",
      });
    }
  }

  function settleSuccessfulReferenceMutation(
    slotId: string,
    workflow: WorkflowV2 | null | undefined,
    addedSourceAssetIds: string[] = [],
    removedSourceAssetIds: string[] = [],
  ) {
    const slot = workflow?.slots.find(
      (candidate) => candidate.slot_id === slotId,
    ) ?? dependencies.getSlot(slotId);
    if (!slot) return;
    const removed = new Set(removedSourceAssetIds.filter(Boolean));
    const explicitReferenceIds = Array.from(new Set([
      ...(slot.explicit_reference_ids ?? []),
      ...addedSourceAssetIds,
    ].filter((assetId) => assetId && !removed.has(assetId))));
    microEdit.markClean(slotId, {
      ...slot,
      explicit_reference_ids: explicitReferenceIds,
    }, false, true);
  }

  async function uploadV2SlotReference(
    slotId: string,
    files: FileList | File[],
  ) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    const slot = dependencies.getSlot(slotId);
    if (!slot) return;
    const fileItems = Array.from(files);
    if (!fileItems.length) return;
    const attachments = fileItems.map(
      (file, index): SlotMicroEditAttachment => ({
        id: v2SlotUploadAttachmentId(slotId, file, index),
        source: "upload",
        preview_url: objectUrlForFile(file),
        filename: file.name,
        semantic_type: slot.slot_type,
        status: "registering",
      }),
    );
    await runner.execute({
      setStatus,
      setInFlight: (submitting, error) => microEdit.setSubmitting(
        slotId,
        submitting,
        error,
      ),
      successStatus: `${slot.slot_type} reference uploaded`,
      failureMessage: "V2 slot reference upload failed",
      cleanupBeforeErrorStatus: true,
      onError: (_error, message) => {
        attachments.forEach((attachment) => {
          microEdit.updateAttachment(slotId, attachment.id, {
            status: "failed",
            error: message,
          });
        });
      },
    }, async () => {
      attachments.forEach(
        (attachment) => microEdit.addAttachment(slotId, attachment),
      );
      const formData = new FormData();
      fileItems.forEach((file) => formData.append("files[]", file));
      formData.append("semantic_type", slot.slot_type);
      formData.append("entity_type", "uploaded_reference");
      formData.append("use_as_prompt", "true");
      const revisionCapture = runner.capture(workflowId);
      const response = await api.uploadSlotReferenceAsset(
        workflowId,
        slotId,
        formData,
      );
      const appliedWorkflow = await applyV2ReferenceArtifacts(
        workflowId,
        revisionCapture,
        response.workflow,
        response.assets,
        response.relations,
      );
      response.source_asset_ids.forEach((sourceAssetId, index) => {
        const asset = response.assets.find(
          (candidate) => candidate.asset_id === sourceAssetId,
        ) ?? response.assets[index];
        const relation = relationForSourceAsset(
          response.relations,
          sourceAssetId,
          slotId,
        );
        const attachmentId = attachments[index]?.id
          ?? `upload:${slotId}:${sourceAssetId}`;
        microEdit.updateAttachment(slotId, attachmentId, {
          source_asset_id: sourceAssetId,
          relation_id: relation?.relation_id,
          preview_url: assetPreviewUrl(asset)
            ?? attachments[index]?.preview_url,
          status: relation?.relation_id ? "attached" : "registered",
          error: undefined,
        });
      });
      settleSuccessfulReferenceMutation(
        slotId,
        appliedWorkflow,
        response.source_asset_ids,
      );
    });
  }

  async function selectV2SlotLibraryReference(
    slotId: string,
    entityId: string,
  ) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    const slot = dependencies.getSlot(slotId);
    if (!slot || !entityId) return;
    const attachmentId = `library:${entityId}:`;
    await runner.execute({
      setStatus,
      setInFlight: (submitting, error) => microEdit.setSubmitting(
        slotId,
        submitting,
        error,
      ),
      successStatus: "V2 slot reference attached",
      failureMessage: "V2 slot reference registration failed",
      cleanupBeforeErrorStatus: true,
      onError: (_error, message) => {
        microEdit.updateAttachment(slotId, attachmentId, {
          status: "failed",
          error: message,
        });
      },
    }, async () => {
      microEdit.addAttachment(slotId, {
        id: attachmentId,
        source: "asset_library",
        library_entity_id: entityId,
        semantic_type: slot.slot_type,
        status: "registering",
      });
      const revisionCapture = runner.capture(workflowId);
      const registered = await api.registerLibraryReference(
        workflowId,
        buildSlotLibraryReferenceRegistration(
          slotId,
          entityId,
          null,
          slot.slot_type,
        ),
      );
      await runner.requireFreshWorkflow(workflowId, revisionCapture);
      microEdit.updateAttachment(slotId, attachmentId, {
        source_asset_id: registered.source_asset_id,
        preview_url: assetPreviewUrl(registered.asset),
        status: "registered",
        error: undefined,
      });
      const applied = await applyRegisteredV2SlotReference(
        workflowId,
        slotId,
        slot.slot_type,
        registered,
        revisionCapture,
      );
      microEdit.updateAttachment(slotId, attachmentId, {
        source_asset_id: registered.source_asset_id,
        relation_id: applied.relation?.relation_id,
        preview_url: assetPreviewUrl(registered.asset),
        status: applied.relation?.relation_id ? "attached" : "registered",
        error: undefined,
      });
      settleSuccessfulReferenceMutation(
        slotId,
        applied.workflow,
        [registered.source_asset_id],
      );
    });
  }

  async function replaceV2SlotWithLibraryEntity(
    slotId: string,
    entity: AssetLibraryEntitySummary,
  ) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    const slot = dependencies.getSlot(slotId);
    if (!slot) return;
    const expectedType = assetLibraryEntityTypeForV2ImageSlot(slot);
    if (!expectedType) {
      setStatus("Only V2 image slots can be replaced from the Asset Library.");
      return;
    }
    if (!v2ImageSlotMatchesAssetLibraryEntity(slot, entity)) {
      setStatus(`Choose a ${expectedType} resource for ${slot.slot_type}.`);
      return;
    }
    await runner.execute({
      setStatus,
      setInFlight: (submitting, error) => microEdit.setSubmitting(
        slotId,
        submitting,
        error,
      ),
      startStatus: `Replacing ${slot.slot_type} from Asset Library...`,
      successStatus: `${slot.slot_type} replaced from Asset Library.`,
      failureMessage: "V2 slot library replacement failed",
      cleanupBeforeErrorStatus: true,
    }, async () => {
      const revisionCapture = runner.capture(workflowId);
      const registered = await api.registerLibraryReference(
        workflowId,
        buildSlotLibraryReferenceRegistration(
          slotId,
          entity.entity_id,
          null,
          slot.slot_type,
        ),
      );
      await applyV2ReferenceArtifacts(
        workflowId,
        revisionCapture,
        registered.workflow,
        [registered.asset],
        registered.relation ? [registered.relation] : [],
      );
      const assetId = registered.asset.asset_id;
      const versionId = registered.asset.version_id;
      if (!assetId || !versionId) {
        throw new Error(
          "V2 library replacement needs backend to return asset.asset_id and asset.version_id.",
        );
      }
      await api.selectSlotVersion(workflowId, slotId, {
        asset_id: assetId,
        version_id: versionId,
        source_action: "slot_library_replace",
      });
      if (!runner.isWorkflowCurrent(workflowId)) return;
      await runner.refreshWorkflowSnapshotAndVersions(
        workflowId,
        () => dependencies.loadSlotVersions(slotId),
      );
    });
  }

  async function removeV2SlotReference(
    slotId: string,
    reference: V2SlotReferenceRemoval,
  ) {
    const workflowId = runner.activeWorkflowId();
    const removedSourceAssetId = reference.asset_id
      ?? microEdit.getDraft(slotId)?.attachments.find(
        (attachment) => attachment.relation_id === reference.relation_id
          || (
            reference.entity_id
            && attachment.library_entity_id === reference.entity_id
          ),
      )?.source_asset_id;
    const removeLocalReference = () => {
      if (reference.source === "library_entity" && reference.entity_id) {
        microEdit.removeReference(slotId, {
          source: "library_entity",
          entity_id: reference.entity_id,
          library_asset_id: reference.library_asset_id,
          relation_id: reference.relation_id,
        });
      } else if (reference.source === "uploaded_asset" && reference.asset_id) {
        const localAttachment = microEdit.getDraft(slotId)?.attachments.find(
          (attachment) => attachment.id === reference.asset_id
            && !attachment.source_asset_id,
        );
        if (localAttachment) {
          microEdit.updateAttachment(slotId, localAttachment.id, {
            source_asset_id: reference.asset_id,
          });
        }
        microEdit.removeReference(slotId, {
          source: "uploaded_asset",
          asset_id: reference.asset_id,
          relation_id: reference.relation_id,
        });
      } else if (reference.asset_id) {
        microEdit.removeReference(slotId, {
          source: "reference_asset",
          asset_id: reference.asset_id,
          relation_id: reference.relation_id,
        });
      }
    };
    if (!reference.relation_id || !workflowId) {
      removeLocalReference();
      return;
    }
    await runner.execute({
      setStatus,
      setInFlight: (submitting, error) => microEdit.setSubmitting(
        slotId,
        submitting,
        error,
      ),
      failureMessage: "V2 reference remove failed",
      cleanupBeforeErrorStatus: true,
    }, async () => {
      const revisionCapture = runner.capture(workflowId);
      const response = await api.removeReference(
        workflowId,
        reference.relation_id as string,
      );
      const appliedWorkflow = await applyV2ReferenceArtifacts(
        workflowId,
        revisionCapture,
        response.workflow,
        response.assets ?? [],
        [],
      );
      settleSuccessfulReferenceMutation(
        slotId,
        appliedWorkflow,
        [],
        removedSourceAssetId ? [removedSourceAssetId] : [],
      );
      await runner.syncSnapshot(workflowId);
      await dependencies.loadSlotVersions(slotId);
    });
  }

  async function ensureUploadedDraftReference(
    workflowId: string,
    slot: WorkflowSlotV2,
    draft: SlotMicroEditDraft,
    uploadAssetId: string,
  ) {
    if (draft.attachments.some(
      (attachment) => attachment.source_asset_id === uploadAssetId,
    )) return;
    const revisionCapture = runner.capture(workflowId);
    const registered = await api.registerReferenceAsset(
      workflowId,
      buildSlotReferenceAssetRegistration(
        slot.slot_id,
        { source_type: "v1_upload", upload_asset_id: uploadAssetId },
        slot.slot_type,
      ),
    );
    const { relation } = await applyRegisteredV2SlotReference(
      workflowId,
      slot.slot_id,
      slot.slot_type,
      registered,
      revisionCapture,
    );
    microEdit.addAttachment(slot.slot_id, {
      id: `registered-upload:${slot.slot_id}:${uploadAssetId}`,
      source: "reference_asset",
      source_asset_id: registered.source_asset_id,
      relation_id: relation?.relation_id,
      preview_url: assetPreviewUrl(registered.asset),
      semantic_type: slot.slot_type,
      status: relation?.relation_id ? "attached" : "registered",
    }, false);
  }

  async function registerLibraryDraftReference(
    workflowId: string,
    slot: WorkflowSlotV2,
    attachment: SlotMicroEditAttachment,
  ) {
    if (!attachment.library_entity_id) return;
    const semanticType = attachment.semantic_type || slot.slot_type;
    const revisionCapture = runner.capture(workflowId);
    const registered = await api.registerLibraryReference(
      workflowId,
      buildSlotLibraryReferenceRegistration(
        slot.slot_id,
        attachment.library_entity_id,
        attachment.library_asset_id,
        semanticType,
      ),
    );
    await runner.requireFreshWorkflow(workflowId, revisionCapture);
    microEdit.updateAttachment(slot.slot_id, attachment.id, {
      source_asset_id: registered.source_asset_id,
      preview_url: assetPreviewUrl(registered.asset) ?? attachment.preview_url,
      status: "registered",
      error: undefined,
    });
    const { relation } = await applyRegisteredV2SlotReference(
      workflowId,
      slot.slot_id,
      semanticType,
      registered,
      revisionCapture,
    );
    microEdit.updateAttachment(slot.slot_id, attachment.id, {
      source_asset_id: registered.source_asset_id,
      relation_id: relation?.relation_id,
      status: relation?.relation_id ? "attached" : "registered",
      error: undefined,
    });
  }

  async function attachDraftReference(
    workflowId: string,
    slot: WorkflowSlotV2,
    attachment: SlotMicroEditAttachment,
  ) {
    if (!attachment.source_asset_id) return;
    const revisionCapture = runner.capture(workflowId);
    const attached = await api.attachReference(
      workflowId,
      buildSlotReferenceAttachRequest(
        slot.slot_id,
        attachment.source_asset_id,
        attachment.semantic_type || slot.slot_type,
      ),
    );
    await applyV2ReferenceArtifacts(
      workflowId,
      revisionCapture,
      attached.workflow,
      attached.assets ?? [],
      attached.relation ? [attached.relation] : [],
    );
    microEdit.updateAttachment(slot.slot_id, attachment.id, {
      relation_id: attached.relation?.relation_id,
      status: attached.relation?.relation_id ? "attached" : "registered",
      error: undefined,
    });
  }

  async function ensureDraftAttachment(
    workflowId: string,
    slot: WorkflowSlotV2,
    attachment: SlotMicroEditAttachment,
  ) {
    if (attachment.status === "failed") {
      throw new Error(
        attachment.error || "V2 slot reference registration failed",
      );
    }
    if (attachment.relation_id && attachment.status === "attached") return;
    if (
      attachment.source === "asset_library"
      && !attachment.source_asset_id
      && attachment.library_entity_id
    ) {
      await registerLibraryDraftReference(workflowId, slot, attachment);
      return;
    }
    await attachDraftReference(workflowId, slot, attachment);
  }

  async function ensureV2SlotDraftReferences(
    workflowId: string,
    slotId: string,
    draft: SlotMicroEditDraft,
  ) {
    const slot = dependencies.getSlot(slotId);
    if (!slot) return;
    for (const uploadAssetId of draft.uploaded_asset_ids) {
      await ensureUploadedDraftReference(
        workflowId,
        slot,
        draft,
        uploadAssetId,
      );
    }
    for (const attachment of draft.attachments) {
      await ensureDraftAttachment(workflowId, slot, attachment);
    }
  }

  async function attachV2Reference(request: V2ReferenceAttachRequest) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    await runner.execute({
      setStatus,
      successStatus: (applied) => applied ? "V2 reference attached" : "",
      failureMessage: "V2 reference attach failed",
    }, async () => {
      const revisionCapture = runner.capture(workflowId);
      const response = await api.attachReference(workflowId, request);
      if (!runner.isWorkflowCurrent(workflowId)) return false;
      await applyV2ReferenceArtifacts(
        workflowId,
        revisionCapture,
        response.workflow,
        response.assets ?? [],
        response.relation ? [response.relation] : [],
      );
      return true;
    });
  }

  async function removeV2Reference(relationId: string) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    await runner.execute({
      setStatus,
      successStatus: (applied) => applied ? "V2 reference removed" : "",
      failureMessage: "V2 reference remove failed",
    }, async () => {
      const revisionCapture = runner.capture(workflowId);
      const response = await api.removeReference(workflowId, relationId);
      if (!runner.isWorkflowCurrent(workflowId)) return false;
      await applyV2ReferenceArtifacts(
        workflowId,
        revisionCapture,
        response.workflow,
        response.assets ?? [],
        [],
      );
      return true;
    });
  }

  return {
    syncV2SlotPromptReferences,
    uploadV2SlotReference,
    selectV2SlotLibraryReference,
    replaceV2SlotWithLibraryEntity,
    removeV2SlotReference,
    ensureV2SlotDraftReferences,
    attachPromptReferencesToSlot,
    attachPromptReferencesToItem,
    attachV2Reference,
    removeV2Reference,
  };
}

function uniqueAssetReferences(references: AssetLibraryReference[]) {
  const seen = new Set<string>();
  const result: AssetLibraryReference[] = [];
  for (const reference of references) {
    const key = [
      reference.reference_source ?? "",
      reference.entity_id ?? "",
      reference.asset_id ?? "",
      reference.target_node_id ?? "",
      reference.target_item_id ?? "",
      reference.target_slot_id ?? "",
    ].join(":");
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(reference);
  }
  return result;
}
