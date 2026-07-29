import { isV2ApiError } from "../../../api/v2Client.ts";
import type {
  AgentCanvasWorkflowV2,
  CanvasLayoutPatchRequestV2,
  CanvasLayoutPatchResponseV2,
  CanvasLayoutPositionV2,
} from "../../../types-v2.ts";

type LayoutPersistence = {
  workflowId: string;
  positions: CanvasLayoutPositionV2[];
  readWorkflow: () => AgentCanvasWorkflowV2 | null;
  loadWorkflow: () => Promise<AgentCanvasWorkflowV2>;
  patchLayout: (request: CanvasLayoutPatchRequestV2) => Promise<CanvasLayoutPatchResponseV2>;
  applyWorkflow: (workflow: AgentCanvasWorkflowV2) => void;
  applyLayout: (response: CanvasLayoutPatchResponseV2) => void;
};

export async function persistAgentCanvasLayout({
  workflowId,
  positions,
  readWorkflow,
  loadWorkflow,
  patchLayout,
  applyWorkflow,
  applyLayout,
}: LayoutPersistence): Promise<void> {
  const current = readWorkflow();
  if (!current || current.workflow_id !== workflowId) {
    throw new Error("The active Agent Canvas workflow changed before its layout was saved.");
  }
  const request = {
    expected_layout_revision: current.layout_revision,
    positions,
  };
  try {
    applyLayout(await patchLayout(request));
  } catch (error) {
    if (!isV2ApiError(error) || error.code !== "layout_revision_conflict") throw error;
    const latest = await loadWorkflow();
    applyWorkflow(latest);
    applyLayout(await patchLayout({
      expected_layout_revision: latest.layout_revision,
      positions,
    }));
  }
}
