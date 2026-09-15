import { useMemo, useState } from "react";
import type { AgentCanvasChatTurnV2 } from "../../../../types-v2.ts";
import type { StageThreadUnit } from "../stageThreadProjection.ts";
import type { AgentRoleMotionState } from "./types.ts";

type Terminal = "completed" | "failed" | "cancelled" | "superseded";
export interface RoleLifecycleProjection {
  attemptKey: string;
  sequence: number;
  revision: number;
  attempt: number;
  terminal: Terminal | null;
  motionState: AgentRoleMotionState;
}
interface Input {
  workflowId: string;
  threads: readonly StageThreadUnit[];
  turnsById: Readonly<Record<string, AgentCanvasChatTurnV2>>;
}
export function roleTerminal(status: string | null | undefined): Terminal | null {
  return status === "completed" || status === "failed" || status === "cancelled" || status === "superseded"
    ? status : null;
}

function projectThread(input: Input, unit: StageThreadUnit): RoleLifecycleProjection {
  const exactTurnTerminal = (id: string | null): Terminal | null => {
    const turn = id ? input.turnsById[id] : null;
    if (turn?.workflow_id !== input.workflowId) return null;
    // Missing, queued and waiting turns never gate entry or stop motion.
    return roleTerminal(turn.status)
      ?? (turn.operation_stage === "cancelled" ? "cancelled" : null);
  };
  const candidates: Omit<RoleLifecycleProjection, "motionState">[] = [
    ...unit.activities.map(activity => ({
      attemptKey: `activity:${activity.activity_id}:${activity.turn_id}`,
      sequence: activity.sequence,
      revision: 0,
      attempt: 0,
      terminal: roleTerminal(activity.status) ?? exactTurnTerminal(activity.turn_id),
    })),
    ...unit.proposals.filter(card => card.proposal.workflow_id === input.workflowId).map(card => {
      const proposal = card.proposal;
      const materialization = proposal.materialization;
      return {
        attemptKey: materialization
          ? `materialization:${materialization.materialization_id}:${materialization.attempt_no}`
          : `proposal:${proposal.proposal_id}`,
        sequence: card.sequence,
        revision: proposal.proposal_revision,
        attempt: materialization?.attempt_no ?? 0,
        // An open proposal is not terminal. Its completed creation turn must
        // not stop the role while the user is choosing.
        terminal: proposal.availability === "superseded" ? "superseded" as const
          : materialization ? roleTerminal(materialization.status) ?? exactTurnTerminal(materialization.turn_id)
          : proposal.availability === "applied" ? "completed" as const : null,
      };
    }),
    ...unit.planning.map(message => ({
      attemptKey: `planning:${message.message_id}`,
      sequence: message.sequence,
      revision: 0,
      attempt: 0,
      terminal: exactTurnTerminal(typeof message.metadata?.turn_id === "string" ? message.metadata.turn_id : null),
    })),
  ];
  const latest = candidates.reduce<(typeof candidates)[number] | null>((selected, candidate) =>
    !selected || candidate.sequence > selected.sequence ? candidate : selected, null);
  const value = latest ?? {
    attemptKey: unit.key, sequence: unit.sequence, revision: 0, attempt: 0, terminal: roleTerminal(unit.status),
  };
  return { ...value, motionState: value.terminal ? "idle" : "working" };
}

/** Timeline appearance starts motion; only that operation's terminal stops it.
 * No Journey/Runtime dependency and no next-role handoff rule.
 */
export function projectRoleLifecycles(input: Input): ReadonlyMap<string, RoleLifecycleProjection> {
  return new Map(input.threads.map(unit => [unit.key, projectThread(input, unit)]));
}

/** Retain terminal evidence through stale refreshes; newer operations restart.
 * Scoped to this conversation, never browser-persisted or shared globally.
 */
export function mergeRoleLifecycles(
  previous: ReadonlyMap<string, RoleLifecycleProjection>,
  next: ReadonlyMap<string, RoleLifecycleProjection>,
): ReadonlyMap<string, RoleLifecycleProjection> {
  const merged = new Map(previous);
  next.forEach((candidate, key) => {
    const old = previous.get(key);
    if (old && (candidate.sequence < old.sequence
      || (candidate.sequence === old.sequence && candidate.revision < old.revision)
      || (candidate.sequence === old.sequence && candidate.revision === old.revision && candidate.attempt < old.attempt)
      || (candidate.attemptKey === old.attemptKey && old.terminal !== null))) return;
    merged.set(key, candidate);
  });
  return merged;
}

export function useTimelineRoleLifecycles({ workflowId, threads, turnsById }: Input): ReadonlyMap<string, RoleLifecycleProjection> {
  const projected = useMemo(() => projectRoleLifecycles({ workflowId, threads, turnsById }),
    [workflowId, threads, turnsById]);
  const [history, setHistory] = useState(() => ({
    workflowId, projected, values: projected,
  }));
  if (history.workflowId !== workflowId || history.projected !== projected) {
    const values = history.workflowId === workflowId
      ? mergeRoleLifecycles(history.values, projected) : projected;
    // Guarded render-time derivation avoids committing a stale working frame.
    setHistory({ workflowId, projected, values });
    return values;
  }
  return history.values;
}
