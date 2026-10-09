import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { agentCanvasApi } from "../../../api/agentCanvasApi";
import type { GuidedSessionStateV2 } from "../../../types-v2";
import type { BrandDecisionPanelV1 } from "../brand/brandDecisions";

export type BrandCardRecoveryState = {
  interactionId: string;
  phase: "stale" | "refreshing" | "error" | "review";
  needsQuestion: boolean;
  error: string | null;
};

type Options = {
  workflowId: string | null;
  busy: boolean;
  refreshTimeline: () => Promise<void>;
  onDecisions?: (panel: BrandDecisionPanelV1) => void;
  onSession: (session: GuidedSessionStateV2) => void;
};

/** Recovery never submits a choice. Only an explicit user action can generate a replacement. */
export function useBrandCardRecovery(options: Options) {
  const { workflowId } = options;
  const latest = useRef(options);
  latest.current = options;
  const scope = useMemo(() => ({
    workflowId, active: true, inFlight: false, blockedIds: new Set<string>(),
    recovery: null as BrandCardRecoveryState | null,
  }), [workflowId]);
  const [snapshot, setSnapshot] = useState({ scope, value: scope.recovery });
  const state = snapshot.scope === scope ? snapshot.value : null;
  useEffect(() => {
    scope.active = true;
    return () => { scope.active = false; };
  }, [scope]);
  const publish = useCallback((value: BrandCardRecoveryState | null) => {
    scope.recovery = value;
    setSnapshot({ scope, value });
  }, [scope]);

  const markStale = useCallback((interactionId: string, needsQuestion: boolean) => {
    scope.blockedIds.add(interactionId);
    publish({ interactionId, needsQuestion, phase: "stale", error: null });
  }, [publish, scope]);

  const refresh = useCallback(async () => {
    const recovery = scope.recovery;
    if (!workflowId || !scope.active || !recovery || recovery.phase === "review"
      || scope.inFlight || latest.current.busy) return;
    scope.inFlight = true;
    let next = { ...recovery, phase: "refreshing" as const, error: null };
    publish(next);
    const current = () => scope.active && latest.current.workflowId === workflowId;
    try {
      if (next.needsQuestion) {
        await agentCanvasApi.brandNextQuestion(workflowId);
        if (!current()) return;
        // Once generation succeeds (including 204), a failed read retries GETs only.
        next = { ...next, needsQuestion: false };
        publish(next);
      }
      const [panel, session] = await Promise.all([
        agentCanvasApi.brandDecisions(workflowId),
        agentCanvasApi.agentCanvasCreativeSession(workflowId),
        latest.current.refreshTimeline(),
      ]);
      if (!current()) return;
      if (panel.workflow_id !== workflowId || (session && session.workflow_id !== workflowId)) {
        throw new Error("Current Brand state could not be verified. Reload the question.");
      }
      latest.current.onDecisions?.(panel);
      if (session) latest.current.onSession(session);
      if (latest.current.busy) throw new Error("Wait for the current conversation turn to finish, then refresh again.");
      const interaction = session?.interaction;
      if (panel.journey.stage === "production") {
        publish(null);
      } else if (interaction?.status === "open" && !scope.blockedIds.has(interaction.interaction_id)
        && interaction.content.content_kind === "concept_choice"
        && interaction.content.capability_id.startsWith("brand_")) {
        publish(null);
      } else if (!panel.open_card && panel.journey.stage === "treatment"
        && (!interaction || interaction.status !== "open")) {
        publish({ ...next, phase: "review" });
      } else {
        throw new Error("The current question is not ready yet. Reload the latest state before choosing.");
      }
    } catch (error) {
      if (current()) publish({ ...next, phase: "error", error: error instanceof Error
        ? error.message.slice(0, 500) : "The question could not be refreshed. Please try again." });
    } finally {
      scope.inFlight = false;
    }
  }, [publish, scope, workflowId]);

  const blocksSubmission = useCallback((interactionId: string) => scope.recovery !== null
    || scope.blockedIds.has(interactionId), [scope]);
  const blocksAutomaticQuestion = useCallback(() => scope.recovery !== null, [scope]);
  const clear = useCallback(() => publish(null), [publish]);
  return {
    state, markStale, refresh, clear,
    pending: state?.phase === "refreshing",
    locked: state !== null,
    blocksSubmission,
    blocksAutomaticQuestion,
  };
}
