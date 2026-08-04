import {
  buildAddSlotReferenceRequest,
} from "../../../../../workflow-v2/slotControls.ts";
import type {
  AssetVersionV2,
  V2RegisterReferenceResponse,
  WorkflowAssetRelationV2,
  WorkflowV2,
} from "../../../../../types-v2.ts";
import type { V2WorkflowApplicationCapture } from "../../../graph/v2WorkflowApplicationRevisionGuard.ts";
import {
  mergeV2ReferenceArtifacts,
  referenceRoleForV2SemanticType,
} from "../../v2AssetViewModel.ts";
import type {
  SlotReferenceOperationDependencies,
  SlotReferencePorts,
} from "./slotReferencePorts.ts";

type ArtifactDependencies = SlotReferencePorts<
  "attachSlotReference",
  "markClean"
> & Pick<
  SlotReferenceOperationDependencies,
  "getSlot" | "getWorkflow"
>;

export function createSlotReferenceArtifactOperations(
  dependencies: ArtifactDependencies,
) {
  const { api, microEdit, runner } = dependencies;

  async function apply(
    workflowId: string,
    revisionCapture: V2WorkflowApplicationCapture,
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

  async function applyRegistered(
    workflowId: string,
    slotId: string,
    semanticType: string | null | undefined,
    registered: V2RegisterReferenceResponse,
    revisionCapture: V2WorkflowApplicationCapture,
  ) {
    if (registered.workflow || registered.relation) {
      const workflow = await apply(
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

  function settleMutation(
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

  return { apply, applyRegistered, settleMutation };
}

export type SlotReferenceArtifactOperations = ReturnType<
  typeof createSlotReferenceArtifactOperations
>;
