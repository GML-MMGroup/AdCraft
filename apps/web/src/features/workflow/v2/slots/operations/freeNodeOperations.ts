import type { v2Api } from "../../../../../api/v2Client.ts";
import { isAllowedFreeAbsorbTarget } from "../../../../../workflow-v2/agentRouting.ts";
import type { SlotMutationRunner } from "./slotMutationRunner.ts";

type FreeNodeApi = Pick<
  typeof v2Api,
  "createFreeNode" | "generateFreeNode" | "absorbFreeNode" | "deleteFreeNode"
>;

type FreeNodeOperationDependencies = {
  runner: SlotMutationRunner;
  api: FreeNodeApi;
  getSelectedMediaType: () => string | null;
  setStatus: (status: string) => void;
};

export function createFreeNodeOperations(dependencies: FreeNodeOperationDependencies) {
  const { api, runner, setStatus } = dependencies;

  async function createV2FreeNode() {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    await runner.execute({
      setStatus,
      successStatus: (applied) => applied ? "V2 free generation node created" : "",
      failureMessage: "V2 free node create failed",
    }, async () => {
      const workflow = await api.createFreeNode(workflowId, {
        slot_prompt: "New free generation",
      });
      return runner.applyGuardedWorkflow(workflowId, workflow);
    });
  }

  async function generateV2FreeNode(nodeId: string) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    await runner.execute({
      setStatus,
      successStatus: (applied) => applied ? "V2 free node generated" : "",
      failureMessage: "V2 free node generate failed",
    }, async () => {
      const response = await api.generateFreeNode(workflowId, nodeId, {
        output_media_type: "image",
      });
      if (!runner.isWorkflowCurrent(workflowId)) return false;
      if (response.workflow) await runner.applyGuardedWorkflow(workflowId, response.workflow);
      await runner.syncSnapshot(workflowId);
      return true;
    });
  }

  async function absorbV2FreeNode(
    nodeId: string,
    assetId: string,
    targetNodeId: string,
  ) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId || !assetId || !targetNodeId) return;
    const mediaType = dependencies.getSelectedMediaType();
    if (!isAllowedFreeAbsorbTarget(mediaType, targetNodeId)) {
      setStatus(`Cannot absorb ${mediaType ?? "free"} asset into ${targetNodeId}.`);
      return;
    }
    await runner.execute({
      setStatus,
      successStatus: (relationCount) => relationCount === null
        ? ""
        : `V2 free asset absorbed · ${relationCount} relations`,
      failureMessage: "V2 free node absorb failed",
    }, async () => {
      const response = await api.absorbFreeNode(workflowId, nodeId, {
        target_node_id: targetNodeId,
        asset_id: assetId,
        absorb_role: "reference",
      });
      if (!await runner.applyGuardedWorkflow(workflowId, response.workflow)) return null;
      return response.relations.length;
    });
  }

  async function deleteV2FreeNode(nodeId: string) {
    const workflowId = runner.activeWorkflowId();
    if (!workflowId) return;
    await runner.execute({
      setStatus,
      successStatus: (applied) => applied ? "V2 free node deleted" : "",
      failureMessage: "V2 free node delete failed",
    }, async () => {
      const workflow = await api.deleteFreeNode(workflowId, nodeId);
      return runner.applyGuardedWorkflow(workflowId, workflow);
    });
  }

  return {
    createV2FreeNode,
    generateV2FreeNode,
    absorbV2FreeNode,
    deleteV2FreeNode,
  };
}
