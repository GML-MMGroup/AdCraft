import type { v2Api } from "../../../../../api/v2Client.ts";
import type { PromptGenerateContext } from "../../../../../components/PromptComposer.tsx";
import {
  effectiveSlotPrompt,
  type AssetVersionV2,
  type SlotVersionsResponseV2,
  type WorkflowItemV2,
  type WorkflowSlotV2,
  type WorkflowV2,
} from "../../../../../types-v2.ts";
import { buildSlotCandidateRegenerateRequest } from "../../../../../workflow-v2/slotControls.ts";
import { notifyFinalCompositionSourceSelection } from "../../../final-composition/finalCompositionEvents.ts";
import {
  slotDraftHasPromptChanges,
  type SlotMicroEditDraft,
} from "../useSlotMicroEdit.ts";
import type {
  SlotMutationRunner,
  SlotWorkflowMutationScope,
} from "./slotMutationRunner.ts";

type GenerationApi = Pick<
  typeof v2Api,
  | "deleteSelectedSlotAsset"
  | "discardWorkingVersion"
  | "generateItem"
  | "pollProviderTask"
  | "regenerateSlot"
  | "selectSlotVersion"
  | "updateSlotPrompt"
>;

type GenerationMicroEdit = {
  getDraft: (slotId: string) => SlotMicroEditDraft | undefined;
  updatePrompt: (slotId: string, prompt: string) => void;
  setSubmitting: (slotId: string, submitting: boolean, error?: string) => void;
  markClean: (
    slotId: string,
    slot?: WorkflowSlotV2,
    promptPersisted?: boolean,
  ) => void;
};

type SlotGenerationOperationDependencies = {
  runner: SlotMutationRunner;
  api: GenerationApi;
  readModel: {
    getSlot: (slotId: string) => WorkflowSlotV2 | null;
    getWorkflow: () => WorkflowV2 | null | undefined;
    getSelectedSlots: () => WorkflowSlotV2[];
    getSelectedItems: () => WorkflowItemV2[];
    getSelectedPlanNode: () => { id: string } | null | undefined;
    getActiveSlotId: () => string | null;
    getVersions: (
      slotId: string,
    ) => { versions?: AssetVersionV2[] } | undefined;
    getSelectedAssetVersion: (
      versionId: string,
    ) => AssetVersionV2 | undefined;
  };
  versions: {
    load: (
      slotId: string,
      scope?: SlotWorkflowMutationScope,
    ) => Promise<SlotVersionsResponseV2 | null>;
  };
  microEdit: GenerationMicroEdit;
  references: {
    ensureDraft: (
      workflowId: string,
      slotId: string,
      draft: SlotMicroEditDraft,
    ) => Promise<void>;
    attachPrompt: (
      workflowId: string,
      slot: WorkflowSlotV2,
      context?: PromptGenerateContext,
    ) => Promise<void>;
  };
  setStatus: (status: string) => void;
};

export function createSlotGenerationOperations(
  dependencies: SlotGenerationOperationDependencies,
) {
  const { api, microEdit, runner, setStatus } = dependencies;

  function defaultV2SlotForCurrentNode() {
    const selectedSlots = dependencies.readModel.getSelectedSlots();
    return selectedSlots.find(
      (slot) => !["blocked", "skipped"].includes(String(slot.status)),
    ) ?? selectedSlots[0] ?? null;
  }

  async function submitV2SlotMicroPrompt(
    slotId: string,
    sourceAction:
      | "slot_micro_prompt_send"
      | "run_current_only" = "slot_micro_prompt_send",
  ) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    const slot = dependencies.readModel.getSlot(slotId);
    if (!slot) {
      setStatus("Select a concrete V2 slot before running current only.");
      return;
    }
    const draft = dependencies.microEdit.getDraft(slotId) ?? {
      prompt: effectiveSlotPrompt(slot),
      negative_prompt: slot.negative_prompt ?? "",
      reference_asset_ids: [...(slot.explicit_reference_ids ?? [])],
      uploaded_asset_ids: [],
      library_entity_ids: [],
      attachments: [],
      dirty: false,
      promptDirty: false,
      referenceDirty: false,
      base_prompt: effectiveSlotPrompt(slot),
      base_negative_prompt: slot.negative_prompt ?? "",
      isSubmitting: false,
    };
    const request = buildSlotCandidateRegenerateRequest(
      draft,
      slot,
      sourceAction,
    );
    const promptPersisted = slotDraftHasPromptChanges(draft);
    await runner.execute({
      setStatus,
      setInFlight: (submitting, error) => microEdit.setSubmitting(
        slotId,
        submitting,
        error,
      ),
      startStatus: sourceAction === "run_current_only"
        ? "Generating working candidate for current slot..."
        : `Generating working candidate for ${slot.slot_type}...`,
      successStatus: `${slot.slot_type} working candidate generated`,
      failureMessage: "V2 slot candidate generation failed",
      cleanupBeforeErrorStatus: true,
    }, async (scope) => {
      if (!scope) return;
      let savedSlot: WorkflowSlotV2 | undefined;
      if (promptPersisted) {
        const revisionCapture = runner.capture(workflowId);
        const workflow = await api.updateSlotPrompt(workflowId, slotId, {
          slot_prompt: request.slot_prompt,
          negative_prompt: request.negative_prompt,
        });
        const reconciled = runner.requireFresh(
          await runner.applyReconciledWorkflow(
            workflowId,
            revisionCapture,
            workflow,
          ),
        );
        savedSlot = reconciled.workflow?.slots.find(
          (candidate) => candidate.slot_id === slotId,
        );
      }
      await dependencies.references.ensureDraft(workflowId, slotId, draft);
      const regenerateCapture = runner.capture(workflowId);
      const response = await api.regenerateSlot(workflowId, slotId);
      await runner.completeGeneration({
        workflowId,
        scope,
        capture: regenerateCapture,
        returnedWorkflow: response.workflow ?? null,
        refreshAssetsReason: response.workflow
          ? "slot-run-completed"
          : "slot-run-started",
        refreshSlotVersions: (refreshScope) => (
          dependencies.versions.load(slotId, refreshScope)
        ),
        afterRefresh: (workflow) => {
          microEdit.markClean(
            slotId,
            workflow?.slots.find(
              (candidate) => candidate.slot_id === slotId,
            ) ?? savedSlot,
            promptPersisted,
          );
        },
      });
    });
  }

  async function submitV2LocalSlotPrompt(
    slotId: string,
    prompt: string,
    context?: PromptGenerateContext,
  ) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    const slot = dependencies.readModel.getSlot(slotId);
    if (!slot) {
      setStatus("Select a concrete V2 slot before generating.");
      return;
    }
    if (!prompt.trim()) {
      setStatus("Prompt cannot be empty.");
      return;
    }
    const nextPrompt = prompt;
    const promptPersisted = nextPrompt !== effectiveSlotPrompt(slot);
    microEdit.updatePrompt(slotId, nextPrompt);
    await runner.execute({
      setStatus,
      setInFlight: (submitting, error) => microEdit.setSubmitting(
        slotId,
        submitting,
        error,
      ),
      startStatus: `Generating working candidate for ${slot.slot_type}...`,
      successStatus: `${slot.slot_type} working candidate generated`,
      failureMessage: "V2 slot candidate generation failed",
      cleanupBeforeErrorStatus: true,
    }, async (scope) => {
      if (!scope) return;
      let savedSlot: WorkflowSlotV2 | undefined;
      if (promptPersisted) {
        const revisionCapture = runner.capture(workflowId);
        const workflow = await api.updateSlotPrompt(workflowId, slotId, {
          slot_prompt: nextPrompt,
          negative_prompt: slot.negative_prompt,
        });
        const reconciled = runner.requireFresh(
          await runner.applyReconciledWorkflow(
            workflowId,
            revisionCapture,
            workflow,
          ),
        );
        savedSlot = reconciled.workflow?.slots.find(
          (candidate) => candidate.slot_id === slotId,
        );
      }
      await dependencies.references.attachPrompt(workflowId, slot, context);
      const regenerateCapture = runner.capture(workflowId);
      const response = await api.regenerateSlot(workflowId, slotId);
      await runner.completeGeneration({
        workflowId,
        scope,
        capture: regenerateCapture,
        returnedWorkflow: response.workflow ?? null,
        refreshAssetsReason: response.workflow
          ? "slot-run-completed"
          : "slot-run-started",
        refreshSlotVersions: (refreshScope) => (
          dependencies.versions.load(slotId, refreshScope)
        ),
        afterRefresh: (workflow) => {
          microEdit.markClean(
            slotId,
            workflow?.slots.find(
              (candidate) => candidate.slot_id === slotId,
            ) ?? savedSlot,
            promptPersisted,
          );
        },
      });
    });
  }

  async function runSelectedV2Slot(
    slotId = dependencies.readModel.getActiveSlotId()
      ?? defaultV2SlotForCurrentNode()?.slot_id
      ?? "",
  ) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    if (!slotId) {
      if (dependencies.readModel.getSelectedPlanNode()) {
        setStatus("Open a V2 image slot before running current only.");
        return;
      }
      const item = dependencies.readModel.getSelectedItems()[0];
      if (item) {
        await runner.execute({
          setStatus,
          startStatus: `Requesting V2 item generation for ${item.display_name || item.item_id}...`,
          successStatus: (completed) => completed
            ? `${item.display_name || item.item_id} updated`
            : "",
          failureMessage: "V2 item generation failed",
        }, async () => {
          const response = await api.generateItem(
            workflowId,
            item.item_id,
            { prompt_scope: "auto" },
          );
          if (!runner.isWorkflowCurrent(workflowId)) return false;
          if (response.workflow) {
            await runner.applyGuardedWorkflow(
              workflowId,
              response.workflow,
              { refreshAssetsReason: false },
            );
          }
          await runner.refreshAssets(
            workflowId,
            response.workflow ? "item-run-completed" : "item-run-started",
            response.workflow ?? null,
          );
          await runner.syncSnapshot(workflowId);
          return true;
        });
        return;
      }
      setStatus("Select a V2 item or slot before running current only.");
      return;
    }
    await submitV2SlotMicroPrompt(slotId, "run_current_only");
  }

  async function pollV2ProviderTask(taskId: string) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId || !taskId) return;
    try {
      const task = await api.pollProviderTask(workflowId, taskId);
      if (!runner.isWorkflowCurrent(workflowId)) return;
      setStatus(`Provider task ${task.status}`);
      await runner.refreshWorkflowSnapshotAndVersions(workflowId);
    } catch (error) {
      if (
        runner.isStaleWorkflowMutation(error)
        || !runner.isWorkflowCurrent(workflowId)
      ) return;
      setStatus(
        error instanceof Error ? error.message : "Provider task poll failed",
      );
    }
  }

  function v2AssetForSlotVersion(slotId: string, versionId: string) {
    const slotVersions = dependencies.readModel.getVersions(slotId)?.versions
      ?? [];
    return slotVersions.find(
      (asset) => asset.version_id === versionId
        || asset.asset_id === versionId,
    )
      ?? dependencies.readModel.getSelectedAssetVersion(versionId)
      ?? dependencies.readModel.getWorkflow()?.asset_versions.find(
        (asset) => asset.version_id === versionId
          || asset.asset_id === versionId,
      )
      ?? null;
  }

  async function selectV2SlotVersion(slotId: string, versionId: string) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    const slot = dependencies.readModel.getSlot(slotId);
    const asset = v2AssetForSlotVersion(slotId, versionId);
    if (!asset?.asset_id || !asset.version_id) {
      setStatus("V2 version selection needs both asset_id and version_id.");
      return;
    }
    await runner.execute({
      setStatus,
      successStatus: (completed) => completed
        ? `${slotId} selected version updated`
        : "",
      failureMessage: "V2 version selection failed",
    }, async (scope) => {
      if (!scope) return false;
      await api.selectSlotVersion(workflowId, slotId, {
        asset_id: asset.asset_id,
        version_id: asset.version_id,
        source_action: "slot_version_picker",
      });
      if (!runner.isWorkflowCurrent(workflowId)) return false;
      if (slot?.slot_type === "bgm_audio" && slot.media_type === "audio") {
        notifyFinalCompositionSourceSelection(workflowId, slotId);
      }
      await runner.refreshWorkflowSnapshotAndVersions(
        workflowId,
        (refreshScope) => dependencies.versions.load(slotId, refreshScope),
        scope,
      );
      return true;
    });
  }

  async function discardV2WorkingVersion(slotId: string) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    await runner.execute({
      setStatus,
      successStatus: (completed) => completed
        ? `${slotId} working version discarded`
        : "",
      failureMessage: "V2 working version discard failed",
    }, async () => {
      const revisionCapture = runner.capture(workflowId);
      const workflow = await api.discardWorkingVersion(workflowId, slotId);
      const reconciled = await runner.applyReconciledWorkflow(
        workflowId,
        revisionCapture,
        workflow,
      );
      if (reconciled.stale) {
        setStatus(`${slotId} changed while discarding; latest state loaded`);
        return false;
      }
      await dependencies.versions.load(slotId);
      return true;
    });
  }

  async function deleteV2SelectedSlotAsset(slotId: string) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    await runner.execute({
      setStatus,
      successStatus: (completed) => completed
        ? `${slotId} selected asset removed`
        : "",
      failureMessage: "V2 selected asset delete failed",
    }, async () => {
      const revisionCapture = runner.capture(workflowId);
      const workflow = await api.deleteSelectedSlotAsset(workflowId, slotId);
      const reconciled = await runner.applyReconciledWorkflow(
        workflowId,
        revisionCapture,
        workflow,
      );
      if (reconciled.stale) {
        setStatus(`${slotId} changed while deleting; latest state loaded`);
        return false;
      }
      await dependencies.versions.load(slotId);
      return true;
    });
  }

  return {
    loadV2SlotVersions: dependencies.versions.load,
    defaultV2SlotForCurrentNode,
    submitV2SlotMicroPrompt,
    submitV2LocalSlotPrompt,
    runSelectedV2Slot,
    pollV2ProviderTask,
    selectV2SlotVersion,
    discardV2WorkingVersion,
    deleteV2SelectedSlotAsset,
  };
}

type SlotVersionLoaderDependencies = {
  runner: SlotMutationRunner;
  api: Pick<typeof v2Api, "slotVersions">;
  setVersions: (slotId: string, versions: SlotVersionsResponseV2) => void;
  setStatus: (status: string) => void;
};

export function createSlotVersionLoader(
  dependencies: SlotVersionLoaderDependencies,
) {
  return async function loadV2SlotVersions(
    slotId: string,
    initiatingScope?: SlotWorkflowMutationScope,
  ) {
    const workflowId = initiatingScope?.workflowId
      ?? dependencies.runner.activeWorkflowId();
    if (!workflowId || !slotId) return null;
    const scope = initiatingScope
      ?? dependencies.runner.captureWorkflowScope(workflowId);
    if (!dependencies.runner.isWorkflowScopeCurrent(scope)) return null;
    try {
      const versions = await dependencies.api.slotVersions(workflowId, slotId);
      if (!dependencies.runner.isWorkflowScopeCurrent(scope)) return null;
      dependencies.setVersions(slotId, versions);
      return versions;
    } catch (error) {
      if (dependencies.runner.isWorkflowScopeCurrent(scope)) {
        dependencies.setStatus(
          error instanceof Error
            ? error.message
            : "V2 slot history failed to load",
        );
      }
      return null;
    }
  };
}
