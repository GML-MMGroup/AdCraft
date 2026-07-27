import type { V2ReferenceAttachRequest } from "../../../../../types-v2.ts";
import {
  buildSlotLibraryReferenceRegistration,
} from "../../../../../workflow-v2/slotControls.ts";
import {
  assetPreviewUrl,
  objectUrlForFile,
  relationForSourceAsset,
  v2SlotUploadAttachmentId,
} from "../../v2AssetViewModel.ts";
import type { SlotMicroEditAttachment } from "../useSlotMicroEdit.ts";
import type {
  SlotReferenceArtifactOperations,
} from "./slotReferenceArtifacts.ts";
import type {
  SlotReferenceOperationDependencies,
  SlotReferencePorts,
} from "./slotReferencePorts.ts";

type AttachmentDependencies = SlotReferencePorts<
  | "attachReference"
  | "registerLibraryReference"
  | "removeReference"
  | "uploadSlotReferenceAsset",
  "addAttachment" | "setSubmitting" | "updateAttachment"
> & Pick<
  SlotReferenceOperationDependencies,
  "getSlot" | "setStatus"
> & {
  artifacts: SlotReferenceArtifactOperations;
};

export function createSlotReferenceAttachmentOperations(
  dependencies: AttachmentDependencies,
) {
  const { api, artifacts, microEdit, runner, setStatus } = dependencies;

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
      const appliedWorkflow = await artifacts.apply(
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
      artifacts.settleMutation(
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
      const applied = await artifacts.applyRegistered(
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
      artifacts.settleMutation(
        slotId,
        applied.workflow,
        [registered.source_asset_id],
      );
    });
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
      await artifacts.apply(
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
      await artifacts.apply(
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
    uploadV2SlotReference,
    selectV2SlotLibraryReference,
    attachV2Reference,
    removeV2Reference,
  };
}
