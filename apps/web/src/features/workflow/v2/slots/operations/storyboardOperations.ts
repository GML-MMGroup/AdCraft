import type { v2Api } from "../../../../../api/v2Client.ts";
import type { PromptGenerateContext } from "../../../../../components/PromptComposer.tsx";
import type { WorkflowItemV2 } from "../../../../../types-v2.ts";
import { v2EditableItemPrompt } from "../../v2PromptModel.ts";
import type { SlotMutationRunner } from "./slotMutationRunner.ts";

type StoryboardApi = Pick<typeof v2Api, "confirmShotSummary" | "generateItem">;

type StoryboardOperationDependencies = {
  runner: SlotMutationRunner;
  api: StoryboardApi;
  getPromptDraft: (itemId: string) => string | undefined;
  setPromptDraft: (itemId: string, prompt: string) => void;
  setPromptSaving: (itemId: string, saving: boolean) => void;
  attachPromptReferences: (
    workflowId: string,
    item: WorkflowItemV2,
    context?: PromptGenerateContext,
  ) => Promise<void>;
  setStatus: (status: string) => void;
};

export function createStoryboardOperations(
  dependencies: StoryboardOperationDependencies,
) {
  const { api, runner, setStatus } = dependencies;

  async function submitV2StoryboardPrompt(
    item: WorkflowItemV2,
    prompt: string,
    context?: PromptGenerateContext,
  ) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    const nextPrompt = prompt.trim();
    if (!nextPrompt) {
      setStatus("Storyboard prompt cannot be empty.");
      return;
    }
    const shotId = item.shot_id || item.item_id;
    await runner.execute({
      setStatus,
      setInFlight: (saving) => dependencies.setPromptSaving(item.item_id, saving),
      startStatus: `Regenerating ${item.display_name || shotId}...`,
      successStatus: (completed) => completed
        ? `${item.display_name || shotId} regenerated`
        : "",
      failureMessage: "V2 storyboard prompt generation failed",
      cleanupBeforeErrorStatus: false,
    }, async () => {
      const confirmedWorkflow = await api.confirmShotSummary(
        workflowId,
        shotId,
        nextPrompt,
      );
      if (!await runner.applyGuardedWorkflow(workflowId, confirmedWorkflow)) {
        return false;
      }
      dependencies.setPromptDraft(item.item_id, nextPrompt);
      await dependencies.attachPromptReferences(workflowId, item, context);
      const response = await api.generateItem(workflowId, item.item_id, {
        prompt_scope: "auto",
      });
      if (!runner.isWorkflowCurrent(workflowId)) return false;
      if (response.workflow) {
        await runner.applyGuardedWorkflow(workflowId, response.workflow, {
          refreshAssetsReason: false,
        });
      }
      await runner.refreshAssets(
        workflowId,
        response.workflow
          ? "storyboard-shot-run-completed"
          : "storyboard-shot-run-started",
        response.workflow ?? null,
      );
      await runner.syncSnapshot(workflowId);
      return true;
    });
  }

  async function confirmV2ShotSummary(item: WorkflowItemV2) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    const shotId = item.shot_id || item.item_id;
    const summary = dependencies.getPromptDraft(item.item_id)
      ?? v2EditableItemPrompt(item);
    await runner.execute({
      setStatus,
      successStatus: (applied) => applied
        ? `${item.display_name || shotId} summary confirmed`
        : "",
      failureMessage: "V2 storyboard confirmation failed",
    }, async () => {
      const workflow = await api.confirmShotSummary(workflowId, shotId, summary);
      return runner.applyGuardedWorkflow(workflowId, workflow);
    });
  }

  return {
    submitV2StoryboardPrompt,
    confirmV2ShotSummary,
  };
}
