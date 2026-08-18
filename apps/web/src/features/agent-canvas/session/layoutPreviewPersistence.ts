import type { CanvasLayoutPositionV2 } from "../../../types-v2.ts";

const ROLLBACK_DETAIL_LIMIT = 160;

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message.trim();
  return "Unknown layout persistence error";
}

function boundedRollbackDetail(error: unknown): string {
  const normalized = errorMessage(error).replace(/\s+/g, " ");
  if (normalized.length <= ROLLBACK_DETAIL_LIMIT) return normalized;
  return `${normalized.slice(0, ROLLBACK_DETAIL_LIMIT - 1)}…`;
}

export class AgentCanvasLayoutRollbackError extends Error {
  readonly cause: unknown;
  readonly rollbackError: unknown;

  constructor(saveError: unknown, rollbackError: unknown) {
    super(
      `${errorMessage(saveError)}. Server rollback also failed: ${boundedRollbackDetail(rollbackError)}`,
    );
    this.name = "AgentCanvasLayoutRollbackError";
    this.cause = saveError;
    this.rollbackError = rollbackError;
  }
}

export async function persistAgentCanvasLayoutPreview({
  targetPositions,
  originalPositions,
  persistPositions,
}: {
  targetPositions: CanvasLayoutPositionV2[];
  originalPositions: CanvasLayoutPositionV2[];
  persistPositions: (positions: CanvasLayoutPositionV2[]) => Promise<void>;
}): Promise<void> {
  try {
    await persistPositions(targetPositions);
  } catch (saveError) {
    try {
      await persistPositions(originalPositions);
    } catch (rollbackError) {
      throw new AgentCanvasLayoutRollbackError(saveError, rollbackError);
    }
    throw saveError;
  }
}
