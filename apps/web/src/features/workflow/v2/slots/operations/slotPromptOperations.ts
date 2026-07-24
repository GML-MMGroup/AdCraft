import type { v2Api } from "../../../../../api/v2Client.ts";
import type { WorkflowItemV2, WorkflowSlotV2 } from "../../../../../types-v2.ts";
import { isV2StoryboardShotItem } from "../../v2PromptModel.ts";
import { collectDirtyV2SlotDraftFlushes } from "../slotPromptFlush.ts";
import type { SlotMicroEditDraft } from "../useSlotMicroEdit.ts";
import type { SlotMutationRunner } from "./slotMutationRunner.ts";

type PromptApi = Pick<
  typeof v2Api,
  "confirmShotSummary" | "updateItemPrompt" | "updateSlotPrompt"
>;

type PromptMicroEdit = {
  getDrafts: () => Record<string, SlotMicroEditDraft | undefined>;
  openSlot: (slot: WorkflowSlotV2) => void;
  closeSlot: () => void;
  updatePrompt: (slotId: string, prompt: string) => void;
  updateNegativePrompt: (slotId: string, prompt: string) => void;
  setSubmitting: (slotId: string, submitting: boolean, error?: string) => void;
  markClean: (
    slotId: string,
    slot?: WorkflowSlotV2,
    promptPersisted?: boolean,
  ) => void;
};

type SlotPromptOperationDependencies = {
  runner: SlotMutationRunner;
  api: PromptApi;
  selection: {
    getSlot: (slotId: string) => WorkflowSlotV2 | null;
    getAllSlots: () => WorkflowSlotV2[];
    selectNode: (nodeId: string) => void;
  };
  microEdit: PromptMicroEdit;
  references: {
    ensureDraft: (
      workflowId: string,
      slotId: string,
      draft: SlotMicroEditDraft,
    ) => Promise<void>;
  };
  itemPrompts: {
    setSaving: (itemId: string, saving: boolean) => void;
    setDraft: (itemId: string, prompt: string) => void;
  };
  setStatus: (status: string) => void;
};

export function createSlotPromptOperations(
  dependencies: SlotPromptOperationDependencies,
) {
  const { api, microEdit, runner, setStatus } = dependencies;

  async function saveV2ItemPrompt(item: WorkflowItemV2, prompt: string) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    const nextPrompt = prompt.trim();
    if (!nextPrompt) {
      setStatus("Item prompt cannot be empty.");
      return;
    }
    await runner.execute({
      setStatus,
      setInFlight: (saving) => dependencies.itemPrompts.setSaving(
        item.item_id,
        saving,
      ),
      successStatus: (applied) => applied
        ? `${item.display_name || item.item_id} prompt saved`
        : "",
      failureMessage: "V2 item prompt update failed",
      cleanupBeforeErrorStatus: false,
    }, async () => {
      const workflow = isV2StoryboardShotItem(item)
        ? await api.confirmShotSummary(
            workflowId,
            item.shot_id || item.item_id,
            nextPrompt,
          )
        : await api.updateItemPrompt(workflowId, item.item_id, {
            item_prompt: nextPrompt,
          });
      if (!await runner.applyGuardedWorkflow(workflowId, workflow)) return false;
      dependencies.itemPrompts.setDraft(item.item_id, nextPrompt);
      return true;
    });
  }

  async function saveV2SlotPrompt(
    slotId: string,
    prompt: string,
    negativePrompt?: string,
  ) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return { ok: false } as const;
    const revisionCapture = runner.capture(workflowId);
    const result = await runner.execute({
      setStatus,
      successStatus: (saved) => saved.ok ? `${slotId} prompt saved` : "",
      failureMessage: "V2 slot prompt update failed",
    }, async () => {
      const workflow = await api.updateSlotPrompt(workflowId, slotId, {
        slot_prompt: prompt,
        negative_prompt: negativePrompt,
      });
      const reconciled = await runner.applyReconciledWorkflow(
        workflowId,
        revisionCapture,
        workflow,
      );
      if (reconciled.stale) {
        setStatus(
          `${slotId} changed while saving; latest state loaded. Review and retry.`,
        );
        return { ok: false } as const;
      }
      const savedSlot = reconciled.workflow?.slots.find(
        (slot) => slot.slot_id === slotId,
      );
      if (!savedSlot) {
        setStatus(`V2 slot prompt update did not return ${slotId}.`);
        return { ok: false } as const;
      }
      return { ok: true, slot: savedSlot } as const;
    });
    return result ?? { ok: false } as const;
  }

  function setActiveV2SlotId(slotId: string | null) {
    if (!slotId) {
      microEdit.closeSlot();
      return;
    }
    const slot = dependencies.selection.getSlot(slotId);
    if (slot) microEdit.openSlot(slot);
  }

  function openV2SlotEditor(slotId: string) {
    const slot = dependencies.selection.getSlot(slotId);
    if (!slot) return;
    setActiveV2SlotId(slotId);
    dependencies.selection.selectNode(slot.node_id);
  }

  function changeV2SlotPrompt(slotId: string, prompt: string) {
    microEdit.updatePrompt(slotId, prompt);
  }

  function changeV2SlotNegativePrompt(slotId: string, negativePrompt: string) {
    microEdit.updateNegativePrompt(slotId, negativePrompt);
  }

  async function flushV2SlotDrafts() {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    const flushes = collectDirtyV2SlotDraftFlushes(
      dependencies.selection.getAllSlots(),
      microEdit.getDrafts(),
    );
    if (!flushes.length) return;
    setStatus(
      `Saving ${flushes.length} V2 slot draft${flushes.length === 1 ? "" : "s"} before run...`,
    );

    for (const flush of flushes) {
      const completed = await runner.execute({
        setStatus,
        setInFlight: (submitting, error) => microEdit.setSubmitting(
          flush.slotId,
          submitting,
          error,
        ),
        failureMessage: "V2 slot draft flush failed",
        cleanupBeforeErrorStatus: true,
        propagateError: true,
      }, async () => {
        let savedSlot: WorkflowSlotV2 | undefined;
        if (flush.promptPatch) {
          const revisionCapture = runner.capture(workflowId);
          const workflow = await api.updateSlotPrompt(
            workflowId,
            flush.slotId,
            flush.promptPatch,
          );
          const reconciled = runner.requireFresh(
            await runner.applyReconciledWorkflow(
              workflowId,
              revisionCapture,
              workflow,
            ),
          );
          savedSlot = reconciled.workflow?.slots.find(
            (slot) => slot.slot_id === flush.slotId,
          );
        }
        if (flush.hasPendingReferences) {
          await dependencies.references.ensureDraft(
            workflowId,
            flush.slotId,
            flush.draft,
          );
          if (!runner.isWorkflowCurrent(workflowId)) return false;
        }
        microEdit.markClean(
          flush.slotId,
          savedSlot,
          Boolean(flush.promptPatch),
        );
        return true;
      });
      if (completed === false) return;
    }
    setStatus("V2 slot drafts saved");
  }

  return {
    saveV2ItemPrompt,
    saveV2SlotPrompt,
    setActiveV2SlotId,
    openV2SlotEditor,
    changeV2SlotPrompt,
    changeV2SlotNegativePrompt,
    flushV2SlotDrafts,
  };
}
