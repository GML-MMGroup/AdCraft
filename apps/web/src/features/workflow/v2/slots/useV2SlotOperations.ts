import { useEffect, useRef } from "react";
import { v2Api } from "../../../../api/v2Client.ts";
import type { AssetLibraryEntitySummary, AssetLibraryReference } from "../../../../types.ts";
import type { PromptGenerateContext } from "../../../../components/PromptComposer.tsx";
import { effectiveSlotPrompt } from "../../../../types-v2.ts";
import type {
  AssetVersionV2,
  V2ReferenceAttachRequest,
  V2RegisterReferenceResponse,
  SlotVersionsResponseV2,
  WorkflowAssetRelationV2,
  WorkflowItemV2,
  WorkflowSlotV2,
  WorkflowV2,
} from "../../../../types-v2.ts";
import type { V2SlotReferenceRemoval } from "../../types.ts";
import { shouldApplyWorkflowScopedResult } from "../../../../workflow/sessionGuards.ts";
import { isAllowedFreeAbsorbTarget } from "../../../../workflow-v2/agentRouting.ts";
import {
  buildAddSlotReferenceRequest,
  buildSlotCandidateRegenerateRequest,
  buildSlotLibraryReferenceRegistration,
  buildSlotReferenceAssetRegistration,
  buildSlotReferenceAttachRequest,
} from "../../../../workflow-v2/slotControls.ts";
import {
  assetPreviewUrl,
  mergeV2ReferenceArtifacts,
  objectUrlForFile,
  referenceRoleForV2SemanticType,
  relationForSourceAsset,
  v2SlotUploadAttachmentId,
} from "../v2AssetViewModel.ts";
import {
  isV2StoryboardShotItem,
  v2EditableItemPrompt,
} from "../v2PromptModel.ts";
import type { SlotMicroEditAttachment, SlotMicroEditDraft, useSlotMicroEdit } from "./useSlotMicroEdit.ts";
import { collectDirtyV2SlotDraftFlushes } from "./slotPromptFlush.ts";
import {
  assetLibraryEntityTypeForV2ImageSlot,
  v2ImageSlotMatchesAssetLibraryEntity,
} from "./v2SlotAssetLibraryModel.ts";

type StateSetter<T> = (value: T | ((current: T) => T)) => void;

type V2SlotOperationsArgs = {
  workflowId: string | null | undefined;
  workflowV2: WorkflowV2 | null | undefined;
  currentWorkflowIsV2: () => boolean;
  activeWorkflowIdRef: React.MutableRefObject<string | null>;
  selectedPlanNode: { id: string } | null | undefined;
  selectedV2Items: WorkflowItemV2[];
  selectedV2Slots: WorkflowSlotV2[];
  allV2Slots: WorkflowSlotV2[];
  selectedV2AssetVersions: Map<string, AssetVersionV2>;
  selectedAssets: Array<{ asset_id: string }>;
  activeV2SlotId: string | null;
  selectedFreeGenerationMediaType: string | null;
  dynamicItemPromptDrafts: Record<string, string>;
  v2SlotVersionsById: Record<string, { versions?: AssetVersionV2[] } | undefined>;
  v2SlotMicroEdit: ReturnType<typeof useSlotMicroEdit>;
  setStatus: StateSetter<string>;
  setSelectedNodeId: StateSetter<string>;
  setDynamicItemPromptSavingById: StateSetter<Record<string, boolean>>;
  setDynamicItemPromptDrafts: StateSetter<Record<string, string>>;
  setV2SlotVersionsById: StateSetter<Record<string, SlotVersionsResponseV2 | undefined>>;
  applyWorkflowV2: (workflow: WorkflowV2, options?: { refreshAssetsReason?: string | false }) => Promise<void>;
  refreshV2WorkflowGraph: (workflowId: string) => Promise<WorkflowV2 | null>;
  syncV2Snapshot: (workflowId: string) => Promise<unknown>;
  refreshV2AssetsAndRetryMissing: (workflowId: string, reason: string, workflow?: WorkflowV2 | null) => Promise<unknown>;
  selectedNodeIdRef: React.MutableRefObject<string>;
};

export function useV2SlotOperations(args: V2SlotOperationsArgs) {
  const argsRef = useRef(args);

  useEffect(() => {
    argsRef.current = args;
  }, [args]);

  function activeWorkflowId() {
    const workflowId = argsRef.current.workflowId;
    return workflowId && argsRef.current.currentWorkflowIsV2() ? workflowId : null;
  }

  async function saveV2ItemPrompt(item: WorkflowItemV2, prompt: string) {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    const nextPrompt = prompt.trim();
    if (!nextPrompt) {
      argsRef.current.setStatus("Item prompt cannot be empty.");
      return;
    }
    argsRef.current.setDynamicItemPromptSavingById((current) => ({ ...current, [item.item_id]: true }));
    try {
      const nextWorkflow = isV2StoryboardShotItem(item)
        ? await v2Api.confirmShotSummary(workflowId, item.shot_id || item.item_id, nextPrompt)
        : await v2Api.updateItemPrompt(workflowId, item.item_id, { item_prompt: nextPrompt });
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await argsRef.current.applyWorkflowV2(nextWorkflow);
      argsRef.current.setDynamicItemPromptDrafts((current) => ({ ...current, [item.item_id]: nextPrompt }));
      argsRef.current.setStatus(`${item.display_name || item.item_id} prompt saved`);
    } catch (error) {
      argsRef.current.setStatus(error instanceof Error ? error.message : "V2 item prompt update failed");
    } finally {
      argsRef.current.setDynamicItemPromptSavingById((current) => ({ ...current, [item.item_id]: false }));
    }
  }

  async function saveV2SlotPrompt(slotId: string, prompt: string, negativePrompt?: string) {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    try {
      const nextWorkflow = await v2Api.updateSlotPrompt(workflowId, slotId, {
        slot_prompt: prompt,
        negative_prompt: negativePrompt || undefined,
      });
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await argsRef.current.applyWorkflowV2(nextWorkflow);
      argsRef.current.v2SlotMicroEdit.markClean(slotId, nextWorkflow.slots.find((slot) => slot.slot_id === slotId));
      argsRef.current.setStatus(`${slotId} prompt saved`);
    } catch (error) {
      argsRef.current.setStatus(error instanceof Error ? error.message : "V2 slot prompt update failed");
    }
  }

  function v2SlotById(slotId: string) {
    const current = argsRef.current;
    return (
      current.workflowV2?.slots.find((slot) => slot.slot_id === slotId) ??
      current.allV2Slots.find((slot) => slot.slot_id === slotId) ??
      current.selectedV2Slots.find((slot) => slot.slot_id === slotId) ??
      null
    );
  }

  function setActiveV2SlotId(slotId: string | null) {
    const current = argsRef.current;
    if (!slotId) {
      current.v2SlotMicroEdit.closeSlot();
      return;
    }
    const slot = v2SlotById(slotId);
    if (!slot) return;
    current.v2SlotMicroEdit.openSlot(slot);
  }

  function openV2SlotEditor(slotId: string) {
    const slot = v2SlotById(slotId);
    if (!slot) return;
    setActiveV2SlotId(slotId);
    argsRef.current.setSelectedNodeId(slot.node_id);
    argsRef.current.selectedNodeIdRef.current = slot.node_id;
  }

  function changeV2SlotPrompt(slotId: string, prompt: string) {
    argsRef.current.v2SlotMicroEdit.updatePrompt(slotId, prompt);
  }

  function changeV2SlotNegativePrompt(slotId: string, negativePrompt: string) {
    argsRef.current.v2SlotMicroEdit.updateNegativePrompt(slotId, negativePrompt);
  }

  function syncV2SlotPromptReferences(slotId: string, context?: PromptGenerateContext) {
    const slot = v2SlotById(slotId);
    if (!slot) return;
    for (const reference of uniqueAssetReferences(context?.asset_references ?? [])) {
      if (reference.reference_source === "asset_library" && reference.entity_id) {
        argsRef.current.v2SlotMicroEdit.addAttachment(slotId, {
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
      argsRef.current.v2SlotMicroEdit.addAttachment(slotId, {
        id: `${reference.reference_source ?? "reference_asset"}:${reference.asset_id}`,
        source: "reference_asset",
        source_asset_id: reference.asset_id,
        semantic_type: reference.role ?? slot.slot_type,
        status: "registered",
      });
    }
  }

  async function applyV2ReferenceArtifacts(
    nextWorkflow: WorkflowV2 | null | undefined,
    assets: AssetVersionV2[] = [],
    relations: WorkflowAssetRelationV2[] = [],
  ) {
    if (nextWorkflow) {
      await argsRef.current.applyWorkflowV2(nextWorkflow);
      return;
    }
    if (!assets.length && !relations.length) return;
    const currentWorkflow = argsRef.current.workflowV2;
    if (!currentWorkflow) return;
    await argsRef.current.applyWorkflowV2(mergeV2ReferenceArtifacts(currentWorkflow, assets, relations));
  }

  async function applyRegisteredV2SlotReference(
    workflowId: string,
    slotId: string,
    semanticType: string | null | undefined,
    registered: V2RegisterReferenceResponse,
  ) {
    if (registered.workflow || registered.relation) {
      await applyV2ReferenceArtifacts(registered.workflow, [registered.asset], registered.relation ? [registered.relation] : []);
      return registered.relation ?? null;
    }
    const sourceAssetId = registered.source_asset_id || registered.asset.asset_id;
    const sourceVersionId = registered.asset.version_id || registered.asset.asset_id || sourceAssetId;
    const attached = await v2Api.attachSlotReference(
      workflowId,
      slotId,
      buildAddSlotReferenceRequest(
        { asset_id: sourceAssetId, version_id: sourceVersionId },
        referenceRoleForV2SemanticType(semanticType),
      ),
    );
    if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return null;
    await argsRef.current.refreshV2WorkflowGraph(workflowId);
    await argsRef.current.syncV2Snapshot(workflowId);
    return {
      relation_id: typeof attached.relation_id === "string" ? attached.relation_id : null,
      relation_type: "reference_for_slot",
      workflow_id: workflowId,
      slot_id: slotId,
      source_asset_id: sourceAssetId,
      asset_id: sourceAssetId,
      version_id: sourceVersionId,
      semantic_type: semanticType ?? null,
    };
  }

  async function attachPromptReferencesToSlot(
    workflowId: string,
    slot: WorkflowSlotV2,
    context?: PromptGenerateContext,
  ) {
    const references = uniqueAssetReferences(context?.asset_references ?? []);
    for (const reference of references) {
      if (reference.reference_source === "asset_library" && reference.entity_id) {
        const registered = await v2Api.registerLibraryReference(
          workflowId,
          buildSlotLibraryReferenceRegistration(slot.slot_id, reference.entity_id, reference.asset_id, slot.slot_type),
        );
        if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
        await applyRegisteredV2SlotReference(workflowId, slot.slot_id, slot.slot_type, registered);
        continue;
      }
      if (!reference.asset_id) continue;
      const attached = await v2Api.attachReference(
        workflowId,
        buildSlotReferenceAttachRequest(slot.slot_id, reference.asset_id, slot.slot_type),
      );
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await applyV2ReferenceArtifacts(attached.workflow, [], attached.relation ? [attached.relation] : []);
    }
  }

  async function attachPromptReferencesToItem(
    workflowId: string,
    item: WorkflowItemV2,
    context?: PromptGenerateContext,
  ) {
    const references = uniqueAssetReferences(context?.asset_references ?? []);
    for (const reference of references) {
      if (!reference.asset_id) continue;
      const response = await v2Api.attachReference(workflowId, {
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
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await applyV2ReferenceArtifacts(response.workflow, [], response.relation ? [response.relation] : []);
    }
  }

  async function uploadV2SlotReference(slotId: string, files: FileList) {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    const slot = v2SlotById(slotId);
    if (!slot) return;
    const fileItems = Array.from(files);
    if (!fileItems.length) return;
    const attachments = fileItems.map((file, index): SlotMicroEditAttachment => ({
      id: v2SlotUploadAttachmentId(slotId, file, index),
      source: "upload",
      preview_url: objectUrlForFile(file),
      filename: file.name,
      semantic_type: slot.slot_type,
      status: "registering",
    }));
    attachments.forEach((attachment) => argsRef.current.v2SlotMicroEdit.addAttachment(slotId, attachment));
    argsRef.current.v2SlotMicroEdit.setSubmitting(slotId, true);
    try {
      const formData = new FormData();
      fileItems.forEach((file) => formData.append("files[]", file));
      formData.append("semantic_type", slot.slot_type);
      formData.append("entity_type", "uploaded_reference");
      formData.append("use_as_prompt", "true");
      const response = await v2Api.uploadSlotReferenceAsset(workflowId, slotId, formData);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await applyV2ReferenceArtifacts(response.workflow, response.assets, response.relations);
      response.source_asset_ids.forEach((sourceAssetId, index) => {
        const asset = response.assets.find((candidate) => candidate.asset_id === sourceAssetId) ?? response.assets[index];
        const relation = relationForSourceAsset(response.relations, sourceAssetId, slotId);
        const attachmentId = attachments[index]?.id ?? `upload:${slotId}:${sourceAssetId}`;
        argsRef.current.v2SlotMicroEdit.updateAttachment(slotId, attachmentId, {
          source_asset_id: sourceAssetId,
          relation_id: relation?.relation_id,
          preview_url: assetPreviewUrl(asset) ?? attachments[index]?.preview_url,
          status: relation?.relation_id ? "attached" : "registered",
          error: undefined,
        });
      });
      argsRef.current.setStatus(`${slot.slot_type} reference uploaded`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "V2 slot reference upload failed";
      attachments.forEach((attachment) => argsRef.current.v2SlotMicroEdit.updateAttachment(slotId, attachment.id, { status: "failed", error: message }));
      argsRef.current.v2SlotMicroEdit.setSubmitting(slotId, false, message);
      argsRef.current.setStatus(message);
      return;
    }
    argsRef.current.v2SlotMicroEdit.setSubmitting(slotId, false);
  }

  async function selectV2SlotLibraryReference(slotId: string, entityId: string) {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    const slot = v2SlotById(slotId);
    if (!slot || !entityId) return;
    const attachmentId = `library:${entityId}:`;
    argsRef.current.v2SlotMicroEdit.addAttachment(slotId, {
      id: attachmentId,
      source: "asset_library",
      library_entity_id: entityId,
      semantic_type: slot.slot_type,
      status: "registering",
    });
    try {
      const registered = await v2Api.registerLibraryReference(
        workflowId,
        buildSlotLibraryReferenceRegistration(slotId, entityId, null, slot.slot_type),
      );
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      argsRef.current.v2SlotMicroEdit.updateAttachment(slotId, attachmentId, {
        source_asset_id: registered.source_asset_id,
        preview_url: assetPreviewUrl(registered.asset),
        status: "registered",
        error: undefined,
      });
      const relation = await applyRegisteredV2SlotReference(workflowId, slotId, slot.slot_type, registered);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      argsRef.current.v2SlotMicroEdit.updateAttachment(slotId, attachmentId, {
        source_asset_id: registered.source_asset_id,
        relation_id: relation?.relation_id,
        preview_url: assetPreviewUrl(registered.asset),
        status: relation?.relation_id ? "attached" : "registered",
        error: undefined,
      });
      argsRef.current.setStatus("V2 slot reference attached");
    } catch (error) {
      const message = error instanceof Error ? error.message : "V2 slot reference registration failed";
      argsRef.current.v2SlotMicroEdit.updateAttachment(slotId, attachmentId, { status: "failed", error: message });
      argsRef.current.v2SlotMicroEdit.setSubmitting(slotId, false, message);
      argsRef.current.setStatus(message);
    }
  }

  async function replaceV2SlotWithLibraryEntity(slotId: string, entity: AssetLibraryEntitySummary) {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    const slot = v2SlotById(slotId);
    if (!slot) return;
    const expectedType = assetLibraryEntityTypeForV2ImageSlot(slot);
    if (!expectedType) {
      argsRef.current.setStatus("Only V2 image slots can be replaced from the Asset Library.");
      return;
    }
    if (!v2ImageSlotMatchesAssetLibraryEntity(slot, entity)) {
      argsRef.current.setStatus(`Choose a ${expectedType} resource for ${slot.slot_type}.`);
      return;
    }
    argsRef.current.v2SlotMicroEdit.setSubmitting(slotId, true);
    argsRef.current.setStatus(`Replacing ${slot.slot_type} from Asset Library...`);
    try {
      const registered = await v2Api.registerLibraryReference(
        workflowId,
        buildSlotLibraryReferenceRegistration(slotId, entity.entity_id, null, slot.slot_type),
      );
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await applyV2ReferenceArtifacts(registered.workflow, [registered.asset], registered.relation ? [registered.relation] : []);
      const assetId = registered.asset.asset_id;
      const versionId = registered.asset.version_id;
      if (!assetId || !versionId) {
        throw new Error("V2 library replacement needs backend to return asset.asset_id and asset.version_id.");
      }
      await v2Api.selectSlotVersion(workflowId, slotId, {
        asset_id: assetId,
        version_id: versionId,
        source_action: "slot_library_replace",
      });
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await argsRef.current.refreshV2WorkflowGraph(workflowId);
      await argsRef.current.syncV2Snapshot(workflowId);
      await loadV2SlotVersions(slotId);
      argsRef.current.setStatus(`${slot.slot_type} replaced from Asset Library.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "V2 slot library replacement failed";
      argsRef.current.v2SlotMicroEdit.setSubmitting(slotId, false, message);
      argsRef.current.setStatus(message);
      return;
    }
    argsRef.current.v2SlotMicroEdit.setSubmitting(slotId, false);
  }

  async function removeV2SlotReference(slotId: string, reference: V2SlotReferenceRemoval) {
    const workflowId = activeWorkflowId();
    if (reference.relation_id && workflowId) {
      try {
        const response = await v2Api.removeReference(workflowId, reference.relation_id);
        if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
        await applyV2ReferenceArtifacts(response.workflow, response.assets ?? [], []);
        await argsRef.current.syncV2Snapshot(workflowId);
        await loadV2SlotVersions(slotId);
      } catch (error) {
        const message = error instanceof Error ? error.message : "V2 reference remove failed";
        argsRef.current.v2SlotMicroEdit.setSubmitting(slotId, false, message);
        argsRef.current.setStatus(message);
        return;
      }
    }
    if (reference.source === "library_entity" && reference.entity_id) {
      argsRef.current.v2SlotMicroEdit.removeReference(slotId, { source: "library_entity", entity_id: reference.entity_id, library_asset_id: reference.library_asset_id, relation_id: reference.relation_id });
      return;
    }
    if (reference.source === "uploaded_asset" && reference.asset_id) {
      argsRef.current.v2SlotMicroEdit.removeReference(slotId, { source: "uploaded_asset", asset_id: reference.asset_id, relation_id: reference.relation_id });
      return;
    }
    if (reference.asset_id) {
      argsRef.current.v2SlotMicroEdit.removeReference(slotId, { source: "reference_asset", asset_id: reference.asset_id, relation_id: reference.relation_id });
    }
  }

  async function ensureV2SlotDraftReferences(workflowId: string, slotId: string, draft: SlotMicroEditDraft) {
    const slot = v2SlotById(slotId);
    if (!slot) return;
    for (const uploadAssetId of draft.uploaded_asset_ids) {
      if (draft.attachments.some((attachment) => attachment.source_asset_id === uploadAssetId)) continue;
      const registered = await v2Api.registerReferenceAsset(
        workflowId,
        buildSlotReferenceAssetRegistration(slotId, { source_type: "v1_upload", upload_asset_id: uploadAssetId }, slot.slot_type),
      );
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      const relation = await applyRegisteredV2SlotReference(workflowId, slotId, slot.slot_type, registered);
      argsRef.current.v2SlotMicroEdit.addAttachment(slotId, {
        id: `registered-upload:${slotId}:${uploadAssetId}`,
        source: "reference_asset",
        source_asset_id: registered.source_asset_id,
        relation_id: relation?.relation_id,
        preview_url: assetPreviewUrl(registered.asset),
        semantic_type: slot.slot_type,
        status: relation?.relation_id ? "attached" : "registered",
      });
    }
    for (const attachment of draft.attachments) {
      if (attachment.status === "failed") throw new Error(attachment.error || "V2 slot reference registration failed");
      if (attachment.relation_id && attachment.status === "attached") continue;
      if (attachment.source === "asset_library" && !attachment.source_asset_id && attachment.library_entity_id) {
        const registered = await v2Api.registerLibraryReference(
          workflowId,
          buildSlotLibraryReferenceRegistration(slotId, attachment.library_entity_id, attachment.library_asset_id, attachment.semantic_type || slot.slot_type),
        );
        if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
        argsRef.current.v2SlotMicroEdit.updateAttachment(slotId, attachment.id, {
          source_asset_id: registered.source_asset_id,
          preview_url: assetPreviewUrl(registered.asset) ?? attachment.preview_url,
          status: "registered",
          error: undefined,
        });
        const relation = await applyRegisteredV2SlotReference(workflowId, slotId, attachment.semantic_type || slot.slot_type, registered);
        if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
        argsRef.current.v2SlotMicroEdit.updateAttachment(slotId, attachment.id, {
          source_asset_id: registered.source_asset_id,
          relation_id: relation?.relation_id,
          status: relation?.relation_id ? "attached" : "registered",
          error: undefined,
        });
        continue;
      }
      if (!attachment.source_asset_id) continue;
      const attached = await v2Api.attachReference(workflowId, buildSlotReferenceAttachRequest(slotId, attachment.source_asset_id, attachment.semantic_type || slot.slot_type));
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await applyV2ReferenceArtifacts(attached.workflow, attached.assets ?? [], attached.relation ? [attached.relation] : []);
      argsRef.current.v2SlotMicroEdit.updateAttachment(slotId, attachment.id, {
        relation_id: attached.relation?.relation_id,
        status: attached.relation?.relation_id ? "attached" : "registered",
        error: undefined,
      });
    }
  }

  async function loadV2SlotVersions(slotId: string) {
    const workflowId = activeWorkflowId();
    if (!workflowId || !slotId) return null;
    try {
      const versions = await v2Api.slotVersions(workflowId, slotId);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return null;
      argsRef.current.setV2SlotVersionsById((current) => ({ ...current, [slotId]: versions }));
      return versions;
    } catch (error) {
      if (shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) {
        argsRef.current.setStatus(error instanceof Error ? error.message : "V2 slot history failed to load");
      }
      return null;
    }
  }

  async function flushV2SlotDrafts() {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    const current = argsRef.current;
    const flushes = collectDirtyV2SlotDraftFlushes(current.allV2Slots, current.v2SlotMicroEdit.state.draftsBySlotId);
    if (!flushes.length) return;
    current.setStatus(`Saving ${flushes.length} V2 slot draft${flushes.length === 1 ? "" : "s"} before run...`);

    for (const flush of flushes) {
      let savedSlot: WorkflowSlotV2 | undefined;
      current.v2SlotMicroEdit.setSubmitting(flush.slotId, true);
      try {
        if (flush.promptPatch) {
          const nextWorkflow = await v2Api.updateSlotPrompt(workflowId, flush.slotId, flush.promptPatch);
          if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
          await argsRef.current.applyWorkflowV2(nextWorkflow);
          savedSlot = nextWorkflow.slots.find((slot) => slot.slot_id === flush.slotId);
        }
        if (flush.hasPendingReferences) {
          await ensureV2SlotDraftReferences(workflowId, flush.slotId, flush.draft);
          if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
        }
        argsRef.current.v2SlotMicroEdit.markClean(flush.slotId, savedSlot);
      } catch (error) {
        const message = error instanceof Error ? error.message : "V2 slot draft flush failed";
        argsRef.current.v2SlotMicroEdit.setSubmitting(flush.slotId, false, message);
        argsRef.current.setStatus(message);
        throw error;
      }
      argsRef.current.v2SlotMicroEdit.setSubmitting(flush.slotId, false);
    }
    argsRef.current.setStatus("V2 slot drafts saved");
  }

  function defaultV2SlotForCurrentNode() {
    return (
      argsRef.current.selectedV2Slots.find((slot) => !["blocked", "skipped"].includes(String(slot.status))) ??
      argsRef.current.selectedV2Slots[0] ??
      null
    );
  }

  async function submitV2SlotMicroPrompt(slotId: string, sourceAction: "slot_micro_prompt_send" | "run_current_only" = "slot_micro_prompt_send") {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    const slot = v2SlotById(slotId);
    if (!slot) {
      argsRef.current.setStatus("Select a concrete V2 slot before running current only.");
      return;
    }
    const draft = argsRef.current.v2SlotMicroEdit.state.draftsBySlotId[slotId] ?? {
      prompt: effectiveSlotPrompt(slot),
      negative_prompt: slot.negative_prompt ?? "",
      reference_asset_ids: [...(slot.explicit_reference_ids ?? [])],
      uploaded_asset_ids: [],
      library_entity_ids: [],
      dirty: false,
      isSubmitting: false,
    };
    const request = buildSlotCandidateRegenerateRequest(draft, slot, sourceAction);
    let savedSlot: WorkflowSlotV2 | undefined;
    argsRef.current.v2SlotMicroEdit.setSubmitting(slotId, true);
    argsRef.current.setStatus(sourceAction === "run_current_only" ? "Generating working candidate for current slot..." : `Generating working candidate for ${slot.slot_type}...`);
    try {
      if (draft.dirty) {
        const nextWorkflow = await v2Api.updateSlotPrompt(workflowId, slotId, {
          slot_prompt: request.slot_prompt,
          negative_prompt: request.negative_prompt || undefined,
        });
        if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
        await argsRef.current.applyWorkflowV2(nextWorkflow);
        savedSlot = nextWorkflow.slots.find((candidate) => candidate.slot_id === slotId);
      }
      await ensureV2SlotDraftReferences(workflowId, slotId, draft);
      const response = await v2Api.regenerateSlot(workflowId, slotId);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      if (response.workflow) {
        await argsRef.current.applyWorkflowV2(response.workflow, { refreshAssetsReason: false });
      }
      await argsRef.current.refreshV2AssetsAndRetryMissing(workflowId, response.workflow ? "slot-run-completed" : "slot-run-started", response.workflow ?? null);
      await argsRef.current.syncV2Snapshot(workflowId);
      await loadV2SlotVersions(slotId);
      argsRef.current.v2SlotMicroEdit.markClean(slotId, response.workflow?.slots.find((candidate) => candidate.slot_id === slotId) ?? savedSlot);
      argsRef.current.setStatus(`${slot.slot_type} working candidate generated`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "V2 slot candidate generation failed";
      argsRef.current.v2SlotMicroEdit.setSubmitting(slotId, false, message);
      argsRef.current.setStatus(message);
      return;
    }
    argsRef.current.v2SlotMicroEdit.setSubmitting(slotId, false);
  }

  async function submitV2LocalSlotPrompt(slotId: string, prompt: string, context?: PromptGenerateContext) {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    const slot = v2SlotById(slotId);
    if (!slot) {
      argsRef.current.setStatus("Select a concrete V2 slot before generating.");
      return;
    }
    if (!prompt.trim()) {
      argsRef.current.setStatus("Prompt cannot be empty.");
      return;
    }
    const nextPrompt = prompt;
    argsRef.current.v2SlotMicroEdit.updatePrompt(slotId, nextPrompt);
    argsRef.current.v2SlotMicroEdit.setSubmitting(slotId, true);
    argsRef.current.setStatus(`Generating working candidate for ${slot.slot_type}...`);
    try {
      const nextWorkflow = await v2Api.updateSlotPrompt(workflowId, slotId, {
        slot_prompt: nextPrompt,
        negative_prompt: slot.negative_prompt ?? undefined,
      });
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await argsRef.current.applyWorkflowV2(nextWorkflow);
      const savedSlot = nextWorkflow.slots.find((candidate) => candidate.slot_id === slotId);
      await attachPromptReferencesToSlot(workflowId, slot, context);
      const response = await v2Api.regenerateSlot(workflowId, slotId);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      if (response.workflow) {
        await argsRef.current.applyWorkflowV2(response.workflow, { refreshAssetsReason: false });
      }
      await argsRef.current.refreshV2AssetsAndRetryMissing(workflowId, response.workflow ? "slot-run-completed" : "slot-run-started", response.workflow ?? null);
      await argsRef.current.syncV2Snapshot(workflowId);
      await loadV2SlotVersions(slotId);
      argsRef.current.v2SlotMicroEdit.markClean(slotId, response.workflow?.slots.find((candidate) => candidate.slot_id === slotId) ?? savedSlot);
      argsRef.current.setStatus(`${slot.slot_type} working candidate generated`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "V2 slot candidate generation failed";
      argsRef.current.v2SlotMicroEdit.setSubmitting(slotId, false, message);
      argsRef.current.setStatus(message);
      return;
    }
    argsRef.current.v2SlotMicroEdit.setSubmitting(slotId, false);
  }

  async function submitV2StoryboardPrompt(item: WorkflowItemV2, prompt: string, context?: PromptGenerateContext) {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    const nextPrompt = prompt.trim();
    if (!nextPrompt) {
      argsRef.current.setStatus("Storyboard prompt cannot be empty.");
      return;
    }
    const shotId = item.shot_id || item.item_id;
    argsRef.current.setDynamicItemPromptSavingById((current) => ({ ...current, [item.item_id]: true }));
    argsRef.current.setStatus(`Regenerating ${item.display_name || shotId}...`);
    try {
      const nextWorkflow = await v2Api.confirmShotSummary(workflowId, shotId, nextPrompt);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await argsRef.current.applyWorkflowV2(nextWorkflow);
      argsRef.current.setDynamicItemPromptDrafts((current) => ({ ...current, [item.item_id]: nextPrompt }));
      await attachPromptReferencesToItem(workflowId, item, context);
      const response = await v2Api.generateItem(workflowId, item.item_id, { prompt_scope: "auto" });
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      if (response.workflow) {
        await argsRef.current.applyWorkflowV2(response.workflow, { refreshAssetsReason: false });
      }
      await argsRef.current.refreshV2AssetsAndRetryMissing(workflowId, response.workflow ? "storyboard-shot-run-completed" : "storyboard-shot-run-started", response.workflow ?? null);
      await argsRef.current.syncV2Snapshot(workflowId);
      argsRef.current.setStatus(`${item.display_name || shotId} regenerated`);
    } catch (error) {
      argsRef.current.setStatus(error instanceof Error ? error.message : "V2 storyboard prompt generation failed");
    } finally {
      argsRef.current.setDynamicItemPromptSavingById((current) => ({ ...current, [item.item_id]: false }));
    }
  }

  async function runSelectedV2Slot(slotId = argsRef.current.activeV2SlotId ?? defaultV2SlotForCurrentNode()?.slot_id ?? "") {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    if (!slotId) {
      const current = argsRef.current;
      if (current.selectedPlanNode) {
        current.setStatus("Open a V2 image slot before running current only.");
        return;
      }
      const item = current.selectedV2Items[0];
      if (item) {
        current.setStatus(`Requesting V2 item generation for ${item.display_name || item.item_id}...`);
        try {
          const response = await v2Api.generateItem(workflowId, item.item_id, { prompt_scope: "auto" });
          if (!shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) return;
          if (response.workflow) {
            await current.applyWorkflowV2(response.workflow, { refreshAssetsReason: false });
          }
          await current.refreshV2AssetsAndRetryMissing(workflowId, response.workflow ? "item-run-completed" : "item-run-started", response.workflow ?? null);
          await current.syncV2Snapshot(workflowId);
          current.setStatus(`${item.display_name || item.item_id} updated`);
        } catch (error) {
          current.setStatus(error instanceof Error ? error.message : "V2 item generation failed");
        }
        return;
      }
      current.setStatus("Select a V2 item or slot before running current only.");
      return;
    }
    await submitV2SlotMicroPrompt(slotId, "run_current_only");
  }

  async function pollV2ProviderTask(taskId: string) {
    const workflowId = activeWorkflowId();
    if (!workflowId || !taskId) return;
    try {
      const task = await v2Api.pollProviderTask(workflowId, taskId);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      argsRef.current.setStatus(`Provider task ${task.status}`);
      await argsRef.current.refreshV2WorkflowGraph(workflowId);
      await argsRef.current.syncV2Snapshot(workflowId);
    } catch (error) {
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      argsRef.current.setStatus(error instanceof Error ? error.message : "Provider task poll failed");
    }
  }

  function v2AssetForSlotVersion(slotId: string, versionId: string) {
    const current = argsRef.current;
    const slotVersions = current.v2SlotVersionsById[slotId]?.versions ?? [];
    return (
      slotVersions.find((asset) => asset.version_id === versionId || asset.asset_id === versionId) ??
      current.selectedV2AssetVersions.get(versionId) ??
      current.workflowV2?.asset_versions.find((asset) => asset.version_id === versionId || asset.asset_id === versionId) ??
      null
    );
  }

  async function selectV2SlotVersion(slotId: string, versionId: string) {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    const asset = v2AssetForSlotVersion(slotId, versionId);
    if (!asset?.asset_id || !asset.version_id) {
      argsRef.current.setStatus("V2 version selection needs both asset_id and version_id.");
      return;
    }
    try {
      await v2Api.selectSlotVersion(workflowId, slotId, {
        asset_id: asset.asset_id,
        version_id: asset.version_id,
        source_action: "slot_version_picker",
      });
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await argsRef.current.refreshV2WorkflowGraph(workflowId);
      await argsRef.current.syncV2Snapshot(workflowId);
      await loadV2SlotVersions(slotId);
      argsRef.current.setStatus(`${slotId} selected version updated`);
    } catch (error) {
      argsRef.current.setStatus(error instanceof Error ? error.message : "V2 version selection failed");
    }
  }

  async function discardV2WorkingVersion(slotId: string) {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    try {
      const nextWorkflow = await v2Api.discardWorkingVersion(workflowId, slotId);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await argsRef.current.applyWorkflowV2(nextWorkflow);
      await loadV2SlotVersions(slotId);
      argsRef.current.setStatus(`${slotId} working version discarded`);
    } catch (error) {
      argsRef.current.setStatus(error instanceof Error ? error.message : "V2 working version discard failed");
    }
  }

  async function deleteV2SelectedSlotAsset(slotId: string) {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    try {
      const nextWorkflow = await v2Api.deleteSelectedSlotAsset(workflowId, slotId);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await argsRef.current.applyWorkflowV2(nextWorkflow);
      await loadV2SlotVersions(slotId);
      argsRef.current.setStatus(`${slotId} selected asset removed`);
    } catch (error) {
      argsRef.current.setStatus(error instanceof Error ? error.message : "V2 selected asset delete failed");
    }
  }

  async function attachV2Reference(request: V2ReferenceAttachRequest) {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    try {
      const response = await v2Api.attachReference(workflowId, request);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await applyV2ReferenceArtifacts(response.workflow, response.assets ?? [], response.relation ? [response.relation] : []);
      argsRef.current.setStatus("V2 reference attached");
    } catch (error) {
      argsRef.current.setStatus(error instanceof Error ? error.message : "V2 reference attach failed");
    }
  }

  async function removeV2Reference(relationId: string) {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    try {
      const response = await v2Api.removeReference(workflowId, relationId);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await applyV2ReferenceArtifacts(response.workflow, response.assets ?? [], []);
      argsRef.current.setStatus("V2 reference removed");
    } catch (error) {
      argsRef.current.setStatus(error instanceof Error ? error.message : "V2 reference remove failed");
    }
  }

  async function confirmV2ShotSummary(item: WorkflowItemV2) {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    const shotId = item.shot_id || item.item_id;
    const summary = argsRef.current.dynamicItemPromptDrafts[item.item_id] ?? v2EditableItemPrompt(item);
    try {
      const nextWorkflow = await v2Api.confirmShotSummary(workflowId, shotId, summary);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await argsRef.current.applyWorkflowV2(nextWorkflow);
      argsRef.current.setStatus(`${item.display_name || shotId} summary confirmed`);
    } catch (error) {
      argsRef.current.setStatus(error instanceof Error ? error.message : "V2 storyboard confirmation failed");
    }
  }

  async function createV2FinalTimelineClip(sourceAssetId: string) {
    const workflowId = activeWorkflowId();
    if (!workflowId || !sourceAssetId) return;
    try {
      const response = await v2Api.createTimelineClip(workflowId, {
        source_asset_id: sourceAssetId,
        clip_type: "video",
        duration: 3,
      });
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await argsRef.current.applyWorkflowV2(response.workflow);
      argsRef.current.setStatus("V2 timeline clip added");
    } catch (error) {
      argsRef.current.setStatus(error instanceof Error ? error.message : "V2 timeline clip create failed");
    }
  }

  async function deleteV2FinalTimelineClip(clipId: string) {
    const workflowId = activeWorkflowId();
    if (!workflowId || !clipId) return;
    try {
      const response = await v2Api.deleteTimelineClip(workflowId, clipId);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await argsRef.current.applyWorkflowV2(response.workflow);
      argsRef.current.setStatus("V2 timeline clip removed");
    } catch (error) {
      argsRef.current.setStatus(error instanceof Error ? error.message : "V2 timeline clip delete failed");
    }
  }

  async function createV2FreeNode() {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    try {
      const nextWorkflow = await v2Api.createFreeNode(workflowId, { slot_prompt: "New free generation" });
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await argsRef.current.applyWorkflowV2(nextWorkflow);
      argsRef.current.setStatus("V2 free generation node created");
    } catch (error) {
      argsRef.current.setStatus(error instanceof Error ? error.message : "V2 free node create failed");
    }
  }

  async function generateV2FreeNode(nodeId: string) {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    try {
      const response = await v2Api.generateFreeNode(workflowId, nodeId, { output_media_type: "image" });
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      if (response.workflow) {
        await argsRef.current.applyWorkflowV2(response.workflow);
      }
      await argsRef.current.syncV2Snapshot(workflowId);
      argsRef.current.setStatus("V2 free node generated");
    } catch (error) {
      argsRef.current.setStatus(error instanceof Error ? error.message : "V2 free node generate failed");
    }
  }

  async function absorbV2FreeNode(nodeId: string, assetId: string, targetNodeId: string) {
    const workflowId = activeWorkflowId();
    if (!workflowId || !assetId || !targetNodeId) return;
    const selectedFreeGenerationMediaType = argsRef.current.selectedFreeGenerationMediaType;
    if (!isAllowedFreeAbsorbTarget(selectedFreeGenerationMediaType, targetNodeId)) {
      argsRef.current.setStatus(`Cannot absorb ${selectedFreeGenerationMediaType ?? "free"} asset into ${targetNodeId}.`);
      return;
    }
    try {
      const response = await v2Api.absorbFreeNode(workflowId, nodeId, {
        target_node_id: targetNodeId,
        asset_id: assetId,
        absorb_role: "reference",
      });
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await argsRef.current.applyWorkflowV2(response.workflow);
      argsRef.current.setStatus(`V2 free asset absorbed · ${response.relations.length} relations`);
    } catch (error) {
      argsRef.current.setStatus(error instanceof Error ? error.message : "V2 free node absorb failed");
    }
  }

  async function deleteV2FreeNode(nodeId: string) {
    const workflowId = activeWorkflowId();
    if (!workflowId) return;
    try {
      const nextWorkflow = await v2Api.deleteFreeNode(workflowId, nodeId);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      await argsRef.current.applyWorkflowV2(nextWorkflow);
      argsRef.current.setStatus("V2 free node deleted");
    } catch (error) {
      argsRef.current.setStatus(error instanceof Error ? error.message : "V2 free node delete failed");
    }
  }

  return {
    actions: {
      saveV2ItemPrompt,
      saveV2SlotPrompt,
      v2SlotById,
      setActiveV2SlotId,
      openV2SlotEditor,
      changeV2SlotPrompt,
      changeV2SlotNegativePrompt,
      syncV2SlotPromptReferences,
      uploadV2SlotReference,
      selectV2SlotLibraryReference,
      replaceV2SlotWithLibraryEntity,
      removeV2SlotReference,
      loadV2SlotVersions,
      defaultV2SlotForCurrentNode,
      submitV2SlotMicroPrompt,
      flushV2SlotDrafts,
      submitV2LocalSlotPrompt,
      submitV2StoryboardPrompt,
      runSelectedV2Slot,
      pollV2ProviderTask,
      selectV2SlotVersion,
      discardV2WorkingVersion,
      deleteV2SelectedSlotAsset,
      attachV2Reference,
      removeV2Reference,
      confirmV2ShotSummary,
      createV2FinalTimelineClip,
      deleteV2FinalTimelineClip,
      createV2FreeNode,
      generateV2FreeNode,
      absorbV2FreeNode,
      deleteV2FreeNode,
    },
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
