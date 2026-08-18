import { isV2ApiError } from "../../../api/agentCanvasApi.ts";
import type {
  AgentCanvasWorkflowV2,
  CanvasLayoutPatchRequestV2,
  CanvasLayoutPatchResponseV2,
  CanvasLayoutPositionV2,
} from "../../../types-v2.ts";

const MAX_LAYOUT_BATCH = 200;
const ERROR_DETAIL_LIMIT = 110;
const COMBINED_ERROR_LIMIT = 260;

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message.trim();
  return "Unknown layout persistence error";
}

function boundedDetail(error: unknown): string {
  const normalized = errorMessage(error).replace(/\s+/g, " ");
  if (normalized.length <= ERROR_DETAIL_LIMIT) return normalized;
  return `${normalized.slice(0, ERROR_DETAIL_LIMIT - 1)}…`;
}

function combinedRollbackMessage(saveError: unknown, rollbackError: unknown): string {
  const message = `${boundedDetail(saveError)}. Server rollback also failed: ${boundedDetail(rollbackError)}`;
  if (message.length <= COMBINED_ERROR_LIMIT) return message;
  return `${message.slice(0, COMBINED_ERROR_LIMIT - 1)}…`;
}

export class AgentCanvasLayoutRollbackError extends Error {
  readonly cause: unknown;
  readonly rollbackError: unknown;

  constructor(saveError: unknown, rollbackError: unknown) {
    super(combinedRollbackMessage(saveError, rollbackError));
    this.name = "AgentCanvasLayoutRollbackError";
    this.cause = saveError;
    this.rollbackError = rollbackError;
  }
}

type ScopedLayoutPreviewPersistence = {
  workflow: AgentCanvasWorkflowV2;
  targetPositions: CanvasLayoutPositionV2[];
  originalPositions: CanvasLayoutPositionV2[];
  loadWorkflow: (workflowId: string) => Promise<AgentCanvasWorkflowV2>;
  patchLayout: (
    workflowId: string,
    request: CanvasLayoutPatchRequestV2,
  ) => Promise<CanvasLayoutPatchResponseV2>;
  applyWorkflow?: (workflow: AgentCanvasWorkflowV2) => void;
  applyLayout?: (response: CanvasLayoutPatchResponseV2) => void;
};

export async function persistAgentCanvasLayoutPreview({
  workflow,
  targetPositions,
  originalPositions,
  loadWorkflow,
  patchLayout,
  applyWorkflow,
  applyLayout,
}: ScopedLayoutPreviewPersistence): Promise<void> {
  const workflowId = workflow.workflow_id;
  let transactionWorkflow = workflow;

  const patchBatch = async (positions: CanvasLayoutPositionV2[]) => {
    const patch = () => patchLayout(workflowId, {
      expected_layout_revision: transactionWorkflow.layout_revision,
      positions,
    });

    let response: CanvasLayoutPatchResponseV2;
    try {
      response = await patch();
    } catch (error) {
      if (!isV2ApiError(error) || error.code !== "layout_revision_conflict") throw error;
      const latest = await loadWorkflow(workflowId);
      if (latest.workflow_id !== workflowId) {
        throw new Error("The layout conflict response did not match the preview workflow.");
      }
      transactionWorkflow = latest;
      applyWorkflow?.(latest);
      response = await patch();
    }

    if (response.workflow_id !== workflowId) {
      throw new Error("The layout response did not match the preview workflow.");
    }
    transactionWorkflow = {
      ...transactionWorkflow,
      revision: Math.max(transactionWorkflow.revision, response.revision),
      layout_revision: response.layout_revision,
    };
    applyLayout?.(response);
  };

  const patchAll = async (positions: CanvasLayoutPositionV2[]) => {
    for (let index = 0; index < positions.length; index += MAX_LAYOUT_BATCH) {
      await patchBatch(positions.slice(index, index + MAX_LAYOUT_BATCH));
    }
  };

  try {
    await patchAll(targetPositions);
  } catch (saveError) {
    try {
      await patchAll(originalPositions);
    } catch (rollbackError) {
      throw new AgentCanvasLayoutRollbackError(saveError, rollbackError);
    }
    throw saveError;
  }
}
