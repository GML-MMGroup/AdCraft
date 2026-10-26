import type {
  AgentRoleMotionState,
  ResolveAgentRoleMotionStateInput,
} from "./types.ts";
import type { AgentCanvasChatTurnV2 } from "../../../../types-v2.ts";
import type { StageThreadStatus, StageThreadUnit } from "../stageThreadProjection.ts";

// Two visual states only. A role plays its animated artwork from the moment it
// starts working until the next role starts working; awaiting a user decision
// is still part of its working stretch. Queued work has not started yet and
// stays on the static bitmap.
export function resolveAgentRoleMotionState({
  status,
  turnId,
  turn,
}: ResolveAgentRoleMotionStateInput): AgentRoleMotionState {
  if (status === "waiting_user") return "working";
  if (status !== "working") return "idle";
  if (turn?.turn_id === turnId && turn.status !== "running") return "idle";
  return "working";
}

interface StageRoleMotionCandidate {
  sequence: number;
  status: StageThreadStatus | "queued" | null;
  turnId: string | null;
}

export function resolveStageThreadRoleMotionState(
  unit: StageThreadUnit,
  turnsById: Readonly<Record<string, AgentCanvasChatTurnV2>>,
): AgentRoleMotionState {
  if (unit.status !== "working" && unit.status !== "waiting_user") return "idle";

  const candidates: StageRoleMotionCandidate[] = [
    ...unit.activities.map((activity) => ({
      sequence: activity.sequence,
      status: activity.status,
      turnId: activity.turn_id,
    })),
    ...unit.proposals.map((card) => ({
      sequence: card.sequence,
      status: card.proposal.materialization?.status ?? null,
      turnId: card.proposal.materialization?.turn_id ?? null,
    })),
    ...unit.receipts.map((receipt) => ({
      sequence: receipt.sequence,
      status: null,
      turnId: null,
    })),
  ].sort((left, right) => right.sequence - left.sequence);
  const latest = candidates[0];
  if (!latest?.status || !latest.turnId) return "idle";
  return resolveAgentRoleMotionState({
    status: latest.status,
    turnId: latest.turnId,
    turn: turnsById[latest.turnId] ?? null,
  });
}
