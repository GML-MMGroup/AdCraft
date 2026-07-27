import type { AssetLibraryEntitySummary } from "../../../../../types.ts";
import {
  buildSlotLibraryReferenceRegistration,
} from "../../../../../workflow-v2/slotControls.ts";
import type { V2SlotReferenceRemoval } from "../../../types.ts";
import {
  assetLibraryEntityTypeForV2ImageSlot,
  v2ImageSlotMatchesAssetLibraryEntity,
} from "../v2SlotAssetLibraryModel.ts";
import type {
  SlotReferenceArtifactOperations,
} from "./slotReferenceArtifacts.ts";
import type {
  SlotReferenceOperationDependencies,
  SlotReferencePorts,
} from "./slotReferencePorts.ts";

type LibraryDependencies = SlotReferencePorts<
  "registerLibraryReference" | "removeReference" | "selectSlotVersion",
  | "getDraft"
  | "removeReference"
  | "setSubmitting"
  | "updateAttachment"
> & Pick<
  SlotReferenceOperationDependencies,
  | "getSlot"
  | "loadSlotVersions"
  | "setStatus"
> & {
  artifacts: Pick<
    SlotReferenceArtifactOperations,
    "apply" | "settleMutation"
  >;
};

export function createSlotReferenceLibraryOperations(
  dependencies: LibraryDependencies,
) {
  const {
    api,
    artifacts,
    microEdit,
    runner,
    setStatus,
  } = dependencies;

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
      setInFlight: (submitting, error) => {
        if (!runner.isWorkflowCurrent(workflowId)) return;
        microEdit.setSubmitting(slotId, submitting, error);
      },
      startStatus: `Replacing ${slot.slot_type} from Asset Library...`,
      successStatus: (completed) => completed
        ? `${slot.slot_type} replaced from Asset Library.`
        : "",
      failureMessage: "V2 slot library replacement failed",
      cleanupBeforeErrorStatus: true,
    }, async (scope) => {
      if (!scope) return false;
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
      await artifacts.apply(
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
      if (!runner.isWorkflowCurrent(workflowId)) return false;
      await runner.refreshWorkflowSnapshotAndVersions(
        workflowId,
        (refreshScope) => dependencies.loadSlotVersions(
          slotId,
          refreshScope,
        ),
        scope,
      );
      return true;
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
      const appliedWorkflow = await artifacts.apply(
        workflowId,
        revisionCapture,
        response.workflow,
        response.assets ?? [],
        [],
      );
      artifacts.settleMutation(
        slotId,
        appliedWorkflow,
        [],
        removedSourceAssetId ? [removedSourceAssetId] : [],
      );
      await runner.syncSnapshot(workflowId);
      await dependencies.loadSlotVersions(slotId);
    });
  }

  return {
    replaceV2SlotWithLibraryEntity,
    removeV2SlotReference,
  };
}
