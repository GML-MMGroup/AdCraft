import type { PromptGenerateContext } from "../../../../../components/PromptComposer.tsx";
import type { AssetLibraryReference } from "../../../../../types.ts";
import type {
  WorkflowItemV2,
  WorkflowSlotV2,
} from "../../../../../types-v2.ts";
import {
  buildSlotLibraryReferenceRegistration,
  buildSlotReferenceAssetRegistration,
  buildSlotReferenceAttachRequest,
} from "../../../../../workflow-v2/slotControls.ts";
import { assetPreviewUrl } from "../../v2AssetViewModel.ts";
import type {
  SlotMicroEditAttachment,
  SlotMicroEditDraft,
} from "../useSlotMicroEdit.ts";
import type {
  SlotReferenceArtifactOperations,
} from "./slotReferenceArtifacts.ts";
import type {
  SlotReferenceOperationDependencies,
  SlotReferencePorts,
} from "./slotReferencePorts.ts";

type DraftReferenceDependencies = SlotReferencePorts<
  | "attachReference"
  | "registerLibraryReference"
  | "registerReferenceAsset",
  "addAttachment" | "updateAttachment"
> & Pick<
  SlotReferenceOperationDependencies,
  "getSlot"
> & {
  artifacts: Pick<
    SlotReferenceArtifactOperations,
    "apply" | "applyRegistered"
  >;
};

export function createSlotReferenceDraftOperations(
  dependencies: DraftReferenceDependencies,
) {
  const { api, artifacts, microEdit, runner } = dependencies;

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
        await artifacts.applyRegistered(
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
      await artifacts.apply(
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
      await artifacts.apply(
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
    const { relation } = await artifacts.applyRegistered(
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
    const { relation } = await artifacts.applyRegistered(
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
    await artifacts.apply(
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

  return {
    attachPromptReferencesToSlot,
    attachPromptReferencesToItem,
    syncV2SlotPromptReferences,
    ensureV2SlotDraftReferences,
  };
}

function uniqueAssetReferences(references: AssetLibraryReference[]) {
  const seen = new Set<string>();
  return references.filter((reference) => {
    const key = [
      reference.reference_source ?? "",
      reference.entity_id ?? "",
      reference.asset_id ?? "",
      reference.target_node_id ?? "",
      reference.target_item_id ?? "",
      reference.target_slot_id ?? "",
    ].join(":");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
