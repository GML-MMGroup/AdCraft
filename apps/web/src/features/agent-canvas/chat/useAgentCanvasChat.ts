import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import { agentCanvasApi, isV2ApiError } from "../../../api/agentCanvasApi.ts";
import { createOperationKey } from "../../../api/operationKey.ts";
import type {
  AgentCanvasWorkflowV2,
  AgentCanvasChatTurnV2,
  AgentCanvasContinuationV2,
  AgentActionReceiptV2,
  CanvasPostReadyCheckpointV2,
  CanvasRuntimeEventV2,
  ChatCapabilityActivityV2,
  ChatMessageV2,
  ChatTimelineItemV2,
  ChatTimelinePresentationViewItemV2,
  DecisionBundleActionRequestV2,
  GuidanceSessionActionV2,
  GuidanceAdvancePreconditionV1,
  GuidedSessionStateV2,
  GuidedInteractionV1,
  GuidedInteractionSubmitRequestV1,
  ProposalActionDescriptorV2,
  ProposalMaterializationProjectionV2,
  ProposedDraftReferenceV2,
} from "../../../types-v2.ts";
import { projectChatEvents } from "./projectChatEvents.ts";
import { agentCanvasChatErrorMessage } from "./chatErrorMessage.ts";
import {
  mergeTimelinePresentationItems,
  visibleTimelinePresentationItems,
} from "./timelinePresentation.ts";
import { mergeGuidedSessionState } from "../session/journeyState.ts";
import {
  guidanceAdvanceIdempotencyKey,
  mayRebaseGuidanceAdvance,
} from "./guidanceAdvance.ts";

type SubmitDraft = {
  text: string;
  mentionedNodeIds: string[];
  mentionedImageAssetIds: string[];
  idempotencyKey?: string;
};

type PendingPostReadyBarrier = {
  checkpointId: string | null;
  executionId: string;
  precondition: GuidanceAdvancePreconditionV1;
  idempotencyKey: string;
  retryAfterMs: number;
};

type GuidanceAdvanceAttemptOptions = {
  idempotencyKey?: string;
  allowAuthorityReplay?: boolean;
};

const PROPOSAL_ACTION_ERROR_CODES = new Set([
  "proposal_reference_unavailable",
  "proposal_snapshot_unavailable",
  "proposal_action_stale",
  "proposal_action_invalid",
  "draft_reference_not_allowed",
  "idempotency_conflict",
]);

const GUIDANCE_CONFLICT_ERROR_CODES = new Set([
  "guidance_revision_conflict",
  "journey_revision_conflict",
  "proposal_action_stale",
]);

function chatRequestErrorMessage(error: unknown, fallback: string): string {
  if (isV2ApiError(error) && error.code) {
    return agentCanvasChatErrorMessage(error.code, error.message);
  }
  return error instanceof Error ? error.message : fallback;
}

function postReadyRetryAfterMs(details: Record<string, unknown>): number {
  const seconds = details.retry_after_seconds;
  if (typeof seconds !== "number" || !Number.isFinite(seconds)) return 1_000;
  return Math.max(250, Math.min(5_000, Math.round(seconds * 1_000)));
}

function pendingPostReadyBarrier(
  error: { details: Record<string, unknown> },
  precondition: GuidanceAdvancePreconditionV1,
  idempotencyKey: string,
): PendingPostReadyBarrier | null {
  const executionId = error.details.execution_id;
  if (typeof executionId !== "string" || !executionId.trim()) return null;
  const checkpointId = error.details.checkpoint_id;
  return {
    checkpointId: typeof checkpointId === "string" && checkpointId.trim() ? checkpointId : null,
    executionId,
    precondition,
    idempotencyKey,
    retryAfterMs: postReadyRetryAfterMs(error.details),
  };
}

function postReadyFailureMessage(checkpoint: CanvasPostReadyCheckpointV2): string {
  const failure = checkpoint.error ?? checkpoint.effects.find((effect) => effect.error)?.error;
  return failure
    ? agentCanvasChatErrorMessage(failure.code, failure.message)
    : "post_ready_progression_failed: The current production step could not be prepared.";
}

function handleProposalActionError(
  proposalId: string,
  error: unknown,
  setIssues: Dispatch<SetStateAction<Record<string, string>>>,
) {
  if (
    !isV2ApiError(error)
    || !error.code
    || !PROPOSAL_ACTION_ERROR_CODES.has(error.code)
  ) return false;
  setIssues((current) => ({
    ...current,
    [proposalId]: agentCanvasChatErrorMessage(error.code!, error.message),
  }));
  return true;
}

function mergeTimelineItems(
  persisted: ChatTimelineItemV2[],
  projected: ChatTimelineItemV2[],
  optimistic: ChatTimelineItemV2[],
) {
  const keys = new Map<string, ChatTimelineItemV2>();
  const keyFor = (item: ChatTimelineItemV2) => {
    if (item.item_type === "message") return `message:${item.message_id}`;
    if (item.item_type === "artifact") return `artifact:${item.artifact_id}`;
    if (item.item_type === "proposal") return `proposal:${item.proposal.proposal_id}`;
    if (item.item_type === "expert_activity") return `activity:${item.activity_id}`;
    if (item.item_type === "command_plan") return `command:${item.command_plan.plan_id}`;
    if (item.item_type === "action_receipt") return `receipt:${item.action_receipt.receipt_id}`;
    if (item.item_type === "agent_document") return `document:${item.document_id}:${item.revision}`;
    if (item.item_type === "proposal_pointer") return `proposal:${item.proposal_id}`;
    if (item.item_type === "decision_bundle") return `decision-bundle:${item.decision_bundle.bundle_id}`;
    if (item.item_type === "decision_bundle_pointer") return `decision-bundle:${item.bundle_id}`;
    const exhaustiveItem: never = item;
    return exhaustiveItem;
  };
  [...persisted, ...projected, ...optimistic].forEach((item) => {
    const key = keyFor(item);
    const current = keys.get(key);
    if (current?.item_type === "expert_activity" && item.item_type === "expert_activity") {
      const currentTerminal = current.status !== "working";
      const nextTerminal = item.status !== "working";
      if (currentTerminal && !nextTerminal) return;
      if (currentTerminal === nextTerminal && current.sequence >= item.sequence) return;
    }
    keys.set(key, item);
  });
  return [...keys.values()].sort((left, right) => left.sequence - right.sequence);
}

export function useAgentCanvasChat({
  workflow,
  chatRevision,
  chatEvents,
  onActionReceipt,
  onWorkflowRefresh,
  onRuntimeRefresh,
}: {
  workflow: AgentCanvasWorkflowV2 | null;
  chatRevision: number;
  chatEvents: CanvasRuntimeEventV2[];
  onActionReceipt?: (receipt: AgentActionReceiptV2) => void;
  onWorkflowRefresh?: () => Promise<void> | void;
  onRuntimeRefresh?: () => Promise<void> | void;
}) {
  const [persistedItems, setPersistedItems] = useState<ChatTimelineItemV2[]>([]);
  const [optimisticItems, setOptimisticItems] = useState<ChatTimelineItemV2[]>([]);
  const [pendingAgentTurnIds, setPendingAgentTurnIds] = useState<string[]>([]);
  const [turnsById, setTurnsById] = useState<Record<string, AgentCanvasChatTurnV2>>({});
  const [retryingSourceTurnIds, setRetryingSourceTurnIds] = useState<Record<string, string>>({});
  const [guidanceSession, setGuidanceSession] = useState<GuidedSessionStateV2 | null>(null);
  const [guidanceAdvancePrecondition, setGuidanceAdvancePrecondition] = useState<GuidanceAdvancePreconditionV1 | null>(null);
  const [currentSessionActions, setCurrentSessionActions] = useState<GuidanceSessionActionV2[]>([]);
  const [continuationsById, setContinuationsById] = useState<Record<string, AgentCanvasContinuationV2>>({});
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [actingProposalId, setActingProposalId] = useState<string | null>(null);
  const [actingDecisionBundleId, setActingDecisionBundleId] = useState<string | null>(null);
  const [actingCommandPlanId, setActingCommandPlanId] = useState<string | null>(null);
  const [actingGuidedActionId, setActingGuidedActionId] = useState<string | null>(null);
  const [actingInteractionId, setActingInteractionId] = useState<string | null>(null);
  const [advancingGuidance, setAdvancingGuidance] = useState(false);
  const [postReadyBarrier, setPostReadyBarrier] = useState<PendingPostReadyBarrier | null>(null);
  const [postReadyCheckpoint, setPostReadyCheckpoint] = useState<CanvasPostReadyCheckpointV2 | null>(null);
  const [postReadyPollRevision, setPostReadyPollRevision] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [proposalIssues, setProposalIssues] = useState<Record<string, string>>({});
  const [failedDraft, setFailedDraft] = useState<SubmitDraft | null>(null);
  const refreshGenerationRef = useRef(0);
  const workflowGenerationRef = useRef(0);
  const pendingActionTurnIdsRef = useRef(new Set<string>());
  const pendingCommandPlanIdsRef = useRef(new Set<string>());
  const expectedReceiptIdsRef = useRef(new Set<string>());
  const deliveredReceiptIdsRef = useRef(new Set<string>());
  const retryingSourceTurnIdsRef = useRef(new Set<string>());
  const presentationItemsByKeyRef = useRef(new Map<string, ChatTimelinePresentationViewItemV2>());
  const proposalPointerHydrationsRef = useRef(new Map<string, Promise<ChatTimelineItemV2>>());
  const decisionBundlePointerHydrationsRef = useRef(new Map<string, Promise<ChatTimelineItemV2>>());
  const capabilityTurnHydrationsRef = useRef(new Map<string, Promise<AgentCanvasChatTurnV2>>());
  const completedCapabilityTurnIdsRef = useRef(new Set<string>());
  const submittedGuidanceAuthorityDigestsRef = useRef(new Set<string>());
  const guidanceAdvanceInFlightRef = useRef<string | null>(null);
  const postReadyBarrierRef = useRef<PendingPostReadyBarrier | null>(null);
  const guidanceAdvanceRebaseRef = useRef<{
    stalePrecondition: GuidanceAdvancePreconditionV1;
    replacementAttempted: boolean;
  } | null>(null);
  const workflowId = workflow?.workflow_id ?? null;
  const workflowRevision = workflow?.revision ?? null;
  const activeVideoSkillRunId = workflow?.active_style_skill?.skill_run_id ?? null;

  const upsertContinuation = useCallback((continuation: AgentCanvasContinuationV2) => {
    setContinuationsById((current) => ({
      ...current,
      [continuation.continuation_id]: continuation,
    }));
  }, []);

  const applyTurnProjection = useCallback((turn: AgentCanvasChatTurnV2) => {
    setTurnsById((current) => ({ ...current, [turn.turn_id]: turn }));
    const terminal = turn.status === "completed" || turn.status === "failed";
    setPendingAgentTurnIds((current) => {
      const next = new Set(current);
      if (terminal) next.delete(turn.turn_id);
      else next.add(turn.turn_id);
      return [...next];
    });
    if (turn.retry_of_turn_id) {
      if (terminal) {
        retryingSourceTurnIdsRef.current.delete(turn.retry_of_turn_id);
        setRetryingSourceTurnIds((current) => {
          if (!(turn.retry_of_turn_id! in current)) return current;
          const next = { ...current };
          delete next[turn.retry_of_turn_id!];
          return next;
        });
      } else {
        retryingSourceTurnIdsRef.current.add(turn.retry_of_turn_id);
        setRetryingSourceTurnIds((current) => ({
          ...current,
          [turn.retry_of_turn_id!]: turn.turn_id,
        }));
      }
    }
  }, []);

  const refreshTurn = useCallback(async (turnId: string) => {
    if (!workflowId) return;
    try {
      const turn = await agentCanvasApi.agentCanvasChatTurn(workflowId, turnId);
      applyTurnProjection(turn);
      if (turn.continuation) upsertContinuation(turn.continuation);
      const terminalErrorCode = turn.continuation?.last_error_code ?? turn.error_code;
      const terminalErrorMessage = turn.continuation?.last_error_message ?? turn.error_message;
      const continuationFailed = turn.continuation?.delivery_status === "failed";
      if ((continuationFailed || turn.status === "failed") && terminalErrorCode) {
        setError(agentCanvasChatErrorMessage(terminalErrorCode, terminalErrorMessage));
      }
    } catch {
      // A later timeline refresh remains authoritative after a transient turn lookup failure.
    }
  }, [applyTurnProjection, upsertContinuation, workflowId]);

  const trackAcceptedTurn = useCallback((
    accepted: {
      turn_id: string;
      retry_of_turn_id?: string | null;
    },
  ) => {
    setPendingAgentTurnIds((current) => (
      current.includes(accepted.turn_id) ? current : [...current, accepted.turn_id]
    ));
    if (accepted.retry_of_turn_id) {
      retryingSourceTurnIdsRef.current.add(accepted.retry_of_turn_id);
      setRetryingSourceTurnIds((current) => ({
        ...current,
        [accepted.retry_of_turn_id!]: accepted.turn_id,
      }));
    }
    void refreshTurn(accepted.turn_id);
  }, [refreshTurn]);

  const hydrateCapabilityTurns = useCallback((
    items: ChatTimelineItemV2[],
    generation: number,
  ) => {
    if (!workflowId) return;
    const turnIds = [...new Set(items.flatMap((item) => (
      item.item_type === "expert_activity" && !completedCapabilityTurnIdsRef.current.has(item.turn_id)
        ? [item.turn_id]
        : []
    )))];
    if (!turnIds.length) return;
    const hydrateTurn = (turnId: string) => {
      const cached = capabilityTurnHydrationsRef.current.get(turnId);
      if (cached) return cached;
      const hydration = agentCanvasApi.agentCanvasChatTurn(workflowId, turnId).then((turn) => {
        if (turn.status === "completed") completedCapabilityTurnIdsRef.current.add(turnId);
        return turn;
      });
      capabilityTurnHydrationsRef.current.set(turnId, hydration);
      void hydration.finally(() => {
        if (capabilityTurnHydrationsRef.current.get(turnId) === hydration) {
          capabilityTurnHydrationsRef.current.delete(turnId);
        }
      }).catch(() => {
        // Failed turn hydration must be retried by the next timeline refresh.
      });
      return hydration;
    };
    void Promise.all(turnIds.map(hydrateTurn)).then((turns) => {
      if (generation !== refreshGenerationRef.current) return;
      turns.forEach((turn) => {
        applyTurnProjection(turn);
      });
    }).catch(() => {
      // Failed turn hydration is deliberately not cached and retries on the next refresh.
    });
  }, [applyTurnProjection, workflowId]);

  const refresh = useCallback(async () => {
    if (!workflowId) return;
    const generation = refreshGenerationRef.current + 1;
    refreshGenerationRef.current = generation;
    setLoading(true);
    try {
      const rawItems: ChatTimelineItemV2[] = [];
      let presentationItems = new Map(presentationItemsByKeyRef.current);
      let usingPresentationProjection = false;
      let nextGuidanceSession: GuidedSessionStateV2 | null = null;
      let nextGuidanceAdvancePrecondition: GuidanceAdvancePreconditionV1 | null = null;
      let nextCurrentSessionActions: GuidanceSessionActionV2[] = [];
      const nextContinuations = new Map<string, AgentCanvasContinuationV2>();
      let cursor = 0;
      for (;;) {
        const timeline = await agentCanvasApi.agentCanvasChatTimeline(workflowId, cursor, 200);
        nextGuidanceSession = mergeGuidedSessionState(nextGuidanceSession, timeline.guidanceSession);
        nextGuidanceAdvancePrecondition = timeline.guidanceAdvancePrecondition;
        nextCurrentSessionActions = timeline.current_session_actions ?? [];
        (timeline.continuations ?? []).forEach((continuation) => {
          nextContinuations.set(continuation.continuation_id, continuation);
        });
        const hydrateTimelineItem = async (item: ChatTimelineItemV2): Promise<ChatTimelineItemV2> => {
          if (item.item_type === "proposal_pointer") {
            const cached = proposalPointerHydrationsRef.current.get(item.proposal_id);
            if (cached) return cached;
            const hydration = agentCanvasApi.agentCanvasProposal(workflowId, item.proposal_id).then((proposal) => ({
              item_type: "proposal" as const,
              proposal,
              sequence: item.sequence,
              created_at: item.created_at,
            }));
            proposalPointerHydrationsRef.current.set(item.proposal_id, hydration);
            void hydration.catch(() => {
              if (proposalPointerHydrationsRef.current.get(item.proposal_id) === hydration) {
                proposalPointerHydrationsRef.current.delete(item.proposal_id);
              }
            });
            return hydration;
          }
          if (item.item_type === "decision_bundle_pointer") {
            const cached = decisionBundlePointerHydrationsRef.current.get(item.bundle_id);
            if (cached) return cached;
            const hydration = agentCanvasApi.agentCanvasDecisionBundle(workflowId, item.bundle_id).then((decisionBundle) => ({
              item_type: "decision_bundle" as const,
              decision_bundle: decisionBundle,
              sequence: item.sequence,
              created_at: item.created_at,
            }));
            decisionBundlePointerHydrationsRef.current.set(item.bundle_id, hydration);
            void hydration.catch(() => {
              if (decisionBundlePointerHydrationsRef.current.get(item.bundle_id) === hydration) {
                decisionBundlePointerHydrationsRef.current.delete(item.bundle_id);
              }
            });
            return hydration;
          }
          return item;
        };
        if (timeline.presentationItems !== null) {
          usingPresentationProjection = true;
          const hydratedPresentationItems = await Promise.all(
            timeline.presentationItems.map(async (presentation) => ({
              ...presentation,
              item: await hydrateTimelineItem(presentation.item),
            })),
          );
          presentationItems = mergeTimelinePresentationItems(
            presentationItems,
            hydratedPresentationItems,
          );
        } else {
          rawItems.push(...await Promise.all(timeline.items.map(hydrateTimelineItem)));
        }
        if (timeline.items.length < 200 || timeline.next_cursor <= cursor) break;
        cursor = timeline.next_cursor;
      }
      try {
        nextGuidanceSession = mergeGuidedSessionState(
          nextGuidanceSession,
          await agentCanvasApi.agentCanvasCreativeSession(workflowId),
        );
      } catch {
        // The timeline remains a compatible read model while a direct session read is unavailable.
      }
      if (generation !== refreshGenerationRef.current) return;
      setGuidanceSession((current) => mergeGuidedSessionState(current, nextGuidanceSession));
      setGuidanceAdvancePrecondition(nextGuidanceAdvancePrecondition);
      setCurrentSessionActions(nextCurrentSessionActions);
      setContinuationsById(Object.fromEntries(nextContinuations));
      const items = usingPresentationProjection
        ? visibleTimelinePresentationItems(presentationItems)
        : rawItems;
      if (usingPresentationProjection) {
        presentationItemsByKeyRef.current = presentationItems;
      } else {
        presentationItemsByKeyRef.current.clear();
      }
      setPersistedItems(items);
      hydrateCapabilityTurns(items, generation);
      items.forEach((item) => {
        if (item.item_type !== "action_receipt") return;
        const receipt = item.action_receipt;
        const expectedByEvent = expectedReceiptIdsRef.current.has(receipt.receipt_id);
        const expectedByTurn = Boolean(
          receipt.action_id
          && pendingActionTurnIdsRef.current.has(receipt.action_id),
        );
        const expectedByPlan = Boolean(
          receipt.plan_id
          && pendingCommandPlanIdsRef.current.has(receipt.plan_id),
        );
        if (
          (!expectedByEvent && !expectedByTurn && !expectedByPlan)
          || deliveredReceiptIdsRef.current.has(receipt.receipt_id)
        ) return;
        if (receipt.action_id) pendingActionTurnIdsRef.current.delete(receipt.action_id);
        if (receipt.plan_id) pendingCommandPlanIdsRef.current.delete(receipt.plan_id);
        expectedReceiptIdsRef.current.delete(receipt.receipt_id);
        deliveredReceiptIdsRef.current.add(receipt.receipt_id);
        if (receipt.status === "applied" || receipt.status === "applied_with_run_error") {
          onActionReceipt?.(receipt);
        } else if (receipt.status === "not_applied") {
          setNotice(receipt.summary || "No canvas change was needed.");
        }
      });
      const persistedMessageIds = new Set(
        items
          .filter((item): item is ChatMessageV2 => item.item_type === "message")
          .map((item) => item.message_id),
      );
      setOptimisticItems((current) => current.filter((item) => (
        item.item_type !== "message"
        || !persistedMessageIds.has(item.message_id)
      )));
      setError(null);
    } catch (refreshError) {
      if (generation !== refreshGenerationRef.current) return;
      setError(chatRequestErrorMessage(refreshError, "Conversation could not be loaded."));
    } finally {
      if (generation === refreshGenerationRef.current) setLoading(false);
    }
  }, [hydrateCapabilityTurns, onActionReceipt, workflowId]);

  const handleStructuredActionError = useCallback((actionError: unknown): boolean => {
    if (!isV2ApiError(actionError)) return false;
    if (
      actionError.code === "guided_action_stale"
      || actionError.code === "guided_action_superseded"
    ) {
      setNotice("This action is no longer current. The conversation was refreshed.");
      void refresh();
      return true;
    }
    if (actionError.code === "guided_action_no_effect") {
      setNotice("No canvas change was needed.");
      void refresh();
      return true;
    }
    if (
      actionError.code === "guidance_revision_conflict"
      || actionError.code === "journey_revision_conflict"
      || actionError.code === "proposal_action_stale"
    ) {
      setNotice("The guidance session changed. Review the latest guidance state before trying again.");
      void refresh();
      void onWorkflowRefresh?.();
      return true;
    }
    if (actionError.code) {
      setError(agentCanvasChatErrorMessage(actionError.code, actionError.message));
      return true;
    }
    return false;
  }, [onWorkflowRefresh, refresh]);

  const handleProposalFailure = useCallback(async (
    proposalId: string,
    actionError: unknown,
    fallbackMessage: string,
  ) => {
    if (
      isV2ApiError(actionError)
      && actionError.code
      && GUIDANCE_CONFLICT_ERROR_CODES.has(actionError.code)
    ) {
      setProposalIssues((current) => ({
        ...current,
        [proposalId]: agentCanvasChatErrorMessage(actionError.code!, actionError.message),
      }));
      setNotice("The guidance session changed. Review the latest guidance state before trying again.");
      await refresh();
      await onWorkflowRefresh?.();
      return;
    }
    if (handleProposalActionError(proposalId, actionError, setProposalIssues)) return;
    if (!handleStructuredActionError(actionError)) {
      setError(chatRequestErrorMessage(actionError, fallbackMessage));
    }
  }, [handleStructuredActionError, onWorkflowRefresh, refresh]);

  useEffect(() => {
    refreshGenerationRef.current += 1;
    workflowGenerationRef.current += 1;
    setPersistedItems([]);
    setOptimisticItems([]);
    setPendingAgentTurnIds([]);
    setTurnsById({});
    setRetryingSourceTurnIds({});
    setGuidanceSession(null);
    setGuidanceAdvancePrecondition(null);
    setCurrentSessionActions([]);
    setContinuationsById({});
    setLoading(false);
    setSending(false);
    setFailedDraft(null);
    setActingProposalId(null);
    setActingDecisionBundleId(null);
    setActingCommandPlanId(null);
    setActingGuidedActionId(null);
    setActingInteractionId(null);
    setAdvancingGuidance(false);
    setPostReadyBarrier(null);
    setPostReadyCheckpoint(null);
    setPostReadyPollRevision(0);
    pendingActionTurnIdsRef.current.clear();
    pendingCommandPlanIdsRef.current.clear();
    expectedReceiptIdsRef.current.clear();
    deliveredReceiptIdsRef.current.clear();
    retryingSourceTurnIdsRef.current.clear();
    presentationItemsByKeyRef.current.clear();
    proposalPointerHydrationsRef.current.clear();
    decisionBundlePointerHydrationsRef.current.clear();
    capabilityTurnHydrationsRef.current.clear();
    completedCapabilityTurnIdsRef.current.clear();
    submittedGuidanceAuthorityDigestsRef.current.clear();
    guidanceAdvanceInFlightRef.current = null;
    postReadyBarrierRef.current = null;
    guidanceAdvanceRebaseRef.current = null;
    setError(null);
    setNotice(null);
    setProposalIssues({});
  }, [workflowId]);

  useEffect(() => {
    setPendingAgentTurnIds((current) => {
      const next = new Set(current);
      chatEvents.forEach((event) => {
        if (event.workflow_id !== workflowId || !event.turn_id) return;
        if (
          event.event_type === "agent_turn_queued"
          || event.event_type === "agent_turn_waiting"
          || event.event_type === "agent_turn_started"
        ) {
          next.add(event.turn_id);
        }
        if (event.event_type === "agent_turn_completed" || event.event_type === "agent_turn_failed") {
          next.delete(event.turn_id);
        }
      });
      const reconciled = [...next];
      return reconciled.length === current.length
        && reconciled.every((turnId, index) => turnId === current[index])
        ? current
        : reconciled;
    });
    chatEvents.forEach((event) => {
      if (event.workflow_id !== workflowId) return;
      if (event.event_type === "action_receipt_created") {
        const receiptId = event.payload?.receipt_id;
        if (typeof receiptId === "string" && !deliveredReceiptIdsRef.current.has(receiptId)) {
          expectedReceiptIdsRef.current.add(receiptId);
        }
      }
      if (
        event.event_type === "agent_turn_waiting"
        ||
        event.event_type.startsWith("continuation_")
        || event.event_type.startsWith("proposal_materialization_")
        || event.event_type.startsWith("agent_operation_")
        || event.event_type === "chat_turn_retry_accepted"
        || event.event_type === "guidance_advance_accepted"
        || event.event_type === "journey_stage_recovered"
      ) {
        const turnId = event.turn_id
          ?? (typeof event.payload?.turn_id === "string" ? event.payload.turn_id : null);
        if (turnId) void refreshTurn(turnId);
      }
    });
  }, [chatEvents, refreshTurn, workflowId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 80);
    return () => window.clearTimeout(timer);
  }, [chatRevision, refresh]);

  const submitGuidanceAdvance = useCallback(async (
    precondition: GuidanceAdvancePreconditionV1,
    isReplacement: boolean,
    options: GuidanceAdvanceAttemptOptions = {},
  ) => {
    if (!workflowId || guidanceAdvanceInFlightRef.current) return;
    if (
      submittedGuidanceAuthorityDigestsRef.current.has(precondition.authority_digest)
      && !options.allowAuthorityReplay
    ) return;
    const workflowGeneration = workflowGenerationRef.current;
    const idempotencyKey = options.idempotencyKey
      ?? guidanceAdvanceIdempotencyKey(workflowId, precondition.authority_digest);
    submittedGuidanceAuthorityDigestsRef.current.add(precondition.authority_digest);
    guidanceAdvanceInFlightRef.current = precondition.authority_digest;
    setAdvancingGuidance(true);
    setError(null);
    try {
      const accepted = await agentCanvasApi.advanceAgentCanvasGuidance(
        workflowId,
        { precondition },
        idempotencyKey,
      );
      if (workflowGeneration !== workflowGenerationRef.current) return;
      guidanceAdvanceRebaseRef.current = null;
      trackAcceptedTurn(accepted);
      void refresh();
    } catch (advanceError) {
      if (workflowGeneration !== workflowGenerationRef.current) return;
      if (isV2ApiError(advanceError) && advanceError.code === "guidance_post_ready_pending") {
        const barrier = pendingPostReadyBarrier(advanceError, precondition, idempotencyKey);
        if (!barrier) {
          setError(agentCanvasChatErrorMessage(
            "post_ready_checkpoint_unavailable",
            advanceError.message,
          ));
          void refresh();
          void onWorkflowRefresh?.();
          return;
        }
        postReadyBarrierRef.current = barrier;
        setPostReadyCheckpoint(null);
        setPostReadyBarrier(barrier);
        setNotice("Preparing the current production step before continuing.");
        return;
      }
      if (isV2ApiError(advanceError) && advanceError.code === "guidance_advance_stale") {
        if (isReplacement) {
          guidanceAdvanceRebaseRef.current = null;
          setError(agentCanvasChatErrorMessage(advanceError.code, advanceError.message));
          return;
        }
        guidanceAdvanceRebaseRef.current = {
          stalePrecondition: precondition,
          replacementAttempted: false,
        };
        setNotice("The guidance state changed. Refreshing the current production step.");
        await refresh();
        return;
      }
      setError(chatRequestErrorMessage(advanceError, "The guidance step could not be continued."));
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        guidanceAdvanceInFlightRef.current = null;
        setAdvancingGuidance(false);
      }
    }
  }, [onWorkflowRefresh, refresh, trackAcceptedTurn, workflowId]);

  useEffect(() => {
    if (!workflowId || !postReadyBarrier) return;
    let disposed = false;
    let timer: number | null = null;
    const isCurrentBarrier = () => postReadyBarrierRef.current === postReadyBarrier;
    const clearBarrier = () => {
      if (!isCurrentBarrier()) return;
      postReadyBarrierRef.current = null;
      setPostReadyBarrier(null);
    };
    const scheduleNextPoll = () => {
      timer = window.setTimeout(() => {
        if (!disposed && isCurrentBarrier()) {
          setPostReadyPollRevision((revision) => revision + 1);
        }
      }, postReadyBarrier.retryAfterMs);
    };
    const poll = async () => {
      try {
        const checkpoint = await agentCanvasApi.agentCanvasPostReadyCheckpoint(
          workflowId,
          postReadyBarrier.executionId,
        );
        if (disposed || !isCurrentBarrier()) return;
        if (
          checkpoint.workflow_id !== workflowId
          || checkpoint.execution_id !== postReadyBarrier.executionId
        ) {
          clearBarrier();
          setError("post_ready_checkpoint_unavailable: The production checkpoint no longer matches this workflow.");
          void refresh();
          void onWorkflowRefresh?.();
          return;
        }
        setPostReadyCheckpoint(checkpoint);
        if (checkpoint.status === "pending") {
          scheduleNextPoll();
          return;
        }
        if (checkpoint.status === "failed") {
          clearBarrier();
          setError(postReadyFailureMessage(checkpoint));
          return;
        }
        if (guidanceSession?.awaiting) {
          clearBarrier();
          setNotice("The current guided action must finish before production can continue.");
          void refresh();
          return;
        }
        clearBarrier();
        setNotice("Production work is ready. Continuing the guided step.");
        void submitGuidanceAdvance(postReadyBarrier.precondition, false, {
          idempotencyKey: postReadyBarrier.idempotencyKey,
          allowAuthorityReplay: true,
        });
      } catch (checkpointError) {
        if (disposed || !isCurrentBarrier()) return;
        if (isV2ApiError(checkpointError) && checkpointError.code === "post_ready_checkpoint_unavailable") {
          clearBarrier();
          setError(chatRequestErrorMessage(
            checkpointError,
            "The production checkpoint could not be loaded.",
          ));
          void refresh();
          void onWorkflowRefresh?.();
          return;
        }
        if (isV2ApiError(checkpointError)) {
          clearBarrier();
          setError(chatRequestErrorMessage(
            checkpointError,
            "The production checkpoint could not be loaded.",
          ));
          return;
        }
        setNotice("Waiting for the current production step to settle.");
        scheduleNextPoll();
      }
    };
    void poll();
    return () => {
      disposed = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [
    onWorkflowRefresh,
    postReadyBarrier,
    postReadyPollRevision,
    refresh,
    submitGuidanceAdvance,
    guidanceSession?.awaiting,
    workflowId,
  ]);

  useEffect(() => {
    const rebase = guidanceAdvanceRebaseRef.current;
    if (guidanceSession?.awaiting) {
      if (rebase) guidanceAdvanceRebaseRef.current = null;
      return;
    }
    if (!guidanceAdvancePrecondition) {
      if (rebase) guidanceAdvanceRebaseRef.current = null;
      return;
    }
    if (rebase) {
      if (rebase.replacementAttempted || !mayRebaseGuidanceAdvance(
        rebase.stalePrecondition,
        guidanceAdvancePrecondition,
      )) {
        guidanceAdvanceRebaseRef.current = null;
        setNotice("The guidance state changed. The latest projected state now controls the next step.");
        return;
      }
      rebase.replacementAttempted = true;
      void submitGuidanceAdvance(guidanceAdvancePrecondition, true);
      return;
    }
    void submitGuidanceAdvance(guidanceAdvancePrecondition, false);
  }, [guidanceAdvancePrecondition, guidanceSession?.awaiting, submitGuidanceAdvance]);

  const submit = useCallback(async (draft: SubmitDraft) => {
    if (!workflowId || !draft.text.trim()) return false;
    const workflowGeneration = workflowGenerationRef.current;
    const optimisticId = createOperationKey("optimistic");
    const idempotencyKey = draft.idempotencyKey ?? createOperationKey("chat");
    setOptimisticItems((current) => [...current, {
      item_type: "message",
      message_id: optimisticId,
      conversation_id: "pending",
      speaker: "user",
      text: draft.text.trim(),
      linked_node_ids: draft.mentionedNodeIds,
      script_node_id: null,
      proposal_id: null,
      sequence: Date.now(),
      created_at: new Date().toISOString(),
    }]);
    setSending(true);
    setFailedDraft(null);
    try {
      const accepted = await agentCanvasApi.submitAgentCanvasChatMessage(workflowId, {
        text: draft.text.trim(),
        mentioned_node_ids: draft.mentionedNodeIds,
        mentioned_image_asset_ids: draft.mentionedImageAssetIds,
        video_skill_run_id: activeVideoSkillRunId,
      }, idempotencyKey);
      if (workflowGeneration !== workflowGenerationRef.current) return false;
      if (accepted.message_id) {
        setOptimisticItems((current) => current.map((item) => (
          item.item_type === "message" && item.message_id === optimisticId
            ? {
                ...item,
                message_id: accepted.message_id!,
                conversation_id: accepted.conversation_id,
              }
          : item
        )));
      }
      trackAcceptedTurn(accepted);
      setError(null);
      return true;
    } catch (submitError) {
      if (workflowGeneration !== workflowGenerationRef.current) return false;
      setOptimisticItems((current) => current.filter((item) => (
        item.item_type !== "message" || item.message_id !== optimisticId
      )));
      setFailedDraft({ ...draft, idempotencyKey });
      setError(chatRequestErrorMessage(submitError, "Message could not be sent."));
      return false;
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setSending(false);
      }
    }
  }, [activeVideoSkillRunId, trackAcceptedTurn, workflowId]);

  const selectProposal = useCallback(async (
    proposalId: string,
    actionDescriptor: ProposalActionDescriptorV2,
    optionId: string,
    acceptedReferences: ProposedDraftReferenceV2[],
  ) => {
    if (!workflowId || actingProposalId || actionDescriptor.action !== "select_option") return;
    const workflowGeneration = workflowGenerationRef.current;
    setActingProposalId(proposalId);
    setError(null);
    setProposalIssues((current) => {
      const next = { ...current };
      delete next[proposalId];
      return next;
    });
    try {
      const request = {
        action_id: actionDescriptor.action_id,
        expected_session_revision: actionDescriptor.expected_session_revision,
        action: "select_option",
        option_id: optionId,
        accepted_references: acceptedReferences,
      } as const;
      const accepted = await agentCanvasApi.actOnAgentCanvasProposal(
        workflowId,
        proposalId,
        request,
        createOperationKey("proposal-select-option"),
      );
      pendingActionTurnIdsRef.current.add(accepted.turn_id);
      trackAcceptedTurn(accepted);
      void refresh();
    } catch (actionError) {
      if (workflowGeneration === workflowGenerationRef.current) {
        await handleProposalFailure(proposalId, actionError, "The proposal could not be selected.");
      }
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setActingProposalId(null);
      }
    }
  }, [actingProposalId, handleProposalFailure, refresh, trackAcceptedTurn, workflowId]);

  const reviseProposal = useCallback(async (
    proposalId: string,
    actionDescriptor: ProposalActionDescriptorV2,
    instruction: string,
  ) => {
    if (
      !workflowId
      || !instruction.trim()
      || actingProposalId
      || !["revise_options", "revise_direction"].includes(actionDescriptor.action)
    ) return;
    const workflowGeneration = workflowGenerationRef.current;
    setActingProposalId(proposalId);
    setError(null);
    setProposalIssues((current) => {
      const next = { ...current };
      delete next[proposalId];
      return next;
    });
    try {
      const request = actionDescriptor.action === "revise_direction"
        ? {
            action_id: actionDescriptor.action_id,
            expected_session_revision: actionDescriptor.expected_session_revision,
            action: "revise_direction" as const,
            option_id: actionDescriptor.option_id ?? "",
            instruction: instruction.trim(),
          }
        : {
            action_id: actionDescriptor.action_id,
            expected_session_revision: actionDescriptor.expected_session_revision,
            action: "revise_options" as const,
            instruction: instruction.trim(),
          };
      if (request.action === "revise_direction" && !request.option_id) return;
      const accepted = await agentCanvasApi.actOnAgentCanvasProposal(
        workflowId,
        proposalId,
        request,
        createOperationKey(`proposal-${request.action.replaceAll("_", "-")}`),
      );
      pendingActionTurnIdsRef.current.add(accepted.turn_id);
      trackAcceptedTurn(accepted);
      void refresh();
    } catch (actionError) {
      if (workflowGeneration === workflowGenerationRef.current) {
        await handleProposalFailure(proposalId, actionError, "The proposal could not be revised.");
      }
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setActingProposalId(null);
      }
    }
  }, [actingProposalId, handleProposalFailure, refresh, trackAcceptedTurn, workflowId]);

  const applyProposalAction = useCallback(async (
    proposalId: string,
    actionDescriptor: ProposalActionDescriptorV2,
  ) => {
    if (
      !workflowId
      || actingProposalId
      || !["defer_topic", "exclude_element", "delegate_choice", "reuse_direction"].includes(actionDescriptor.action)
    ) return;
    const workflowGeneration = workflowGenerationRef.current;
    setActingProposalId(proposalId);
    setError(null);
    setProposalIssues((current) => {
      const next = { ...current };
      delete next[proposalId];
      return next;
    });
    try {
      const request = actionDescriptor.action === "reuse_direction"
        ? {
            action_id: actionDescriptor.action_id,
            expected_session_revision: actionDescriptor.expected_session_revision,
            action: "reuse_direction" as const,
            option_id: actionDescriptor.option_id ?? "",
          }
        : {
            action_id: actionDescriptor.action_id,
            expected_session_revision: actionDescriptor.expected_session_revision,
            action: actionDescriptor.action as "defer_topic" | "exclude_element" | "delegate_choice",
          };
      if (request.action === "reuse_direction" && !request.option_id) return;
      const accepted = await agentCanvasApi.actOnAgentCanvasProposal(
        workflowId,
        proposalId,
        request,
        createOperationKey(`proposal-${actionDescriptor.action.replaceAll("_", "-")}`),
      );
      pendingActionTurnIdsRef.current.add(accepted.turn_id);
      trackAcceptedTurn(accepted);
      void refresh();
    } catch (actionError) {
      if (workflowGeneration === workflowGenerationRef.current) {
        await handleProposalFailure(proposalId, actionError, "The proposal action could not be applied.");
      }
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setActingProposalId(null);
      }
    }
  }, [actingProposalId, handleProposalFailure, refresh, trackAcceptedTurn, workflowId]);

  const actOnCommandPlan = useCallback(async (
    planId: string,
    action: "confirm" | "reject",
  ) => {
    if (!workflowId || actingCommandPlanId) return;
    const workflowGeneration = workflowGenerationRef.current;
    pendingCommandPlanIdsRef.current.add(planId);
    setActingCommandPlanId(planId);
    setError(null);
    try {
      const accepted = await agentCanvasApi.actOnAgentCanvasCommandPlan(
        workflowId,
        planId,
        { action },
        createOperationKey(`command-${action}`),
      );
      pendingActionTurnIdsRef.current.add(accepted.turn_id);
      trackAcceptedTurn(accepted);
      void refresh();
    } catch (actionError) {
      pendingCommandPlanIdsRef.current.delete(planId);
      if (workflowGeneration === workflowGenerationRef.current) {
        if (!handleStructuredActionError(actionError)) {
          setError(chatRequestErrorMessage(
            actionError,
            `The command could not be ${action === "confirm" ? "confirmed" : "rejected"}.`,
          ));
        }
      }
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setActingCommandPlanId(null);
      }
    }
  }, [actingCommandPlanId, handleStructuredActionError, refresh, trackAcceptedTurn, workflowId]);

  const applyGuidedAction = useCallback(async (action: GuidanceSessionActionV2) => {
    const actionId = action.action_id;
    if (!workflowId || actingGuidedActionId) return;
    if (action.action === "set_creative_authority" && !action.authority) {
      setError("The creative authority action is incomplete. Refresh the conversation and try again.");
      return;
    }
    const workflowGeneration = workflowGenerationRef.current;
    setActingGuidedActionId(actionId);
    setError(null);
    try {
      const accepted = await agentCanvasApi.applyAgentCanvasGuidedAction(
        workflowId,
        actionId,
        action.action === "set_creative_authority"
          ? {
              confirmed: true,
              action: "set_creative_authority",
              authority: action.authority!,
              expected_session_revision: action.expected_session_revision,
            }
          : { confirmed: true },
        createOperationKey("guided-action"),
      );
      pendingActionTurnIdsRef.current.add(actionId);
      trackAcceptedTurn(accepted);
      void refresh();
    } catch (actionError) {
      if (workflowGeneration === workflowGenerationRef.current) {
        if (!handleStructuredActionError(actionError)) {
          setError(chatRequestErrorMessage(actionError, "The guided action could not be applied."));
        }
      }
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setActingGuidedActionId(null);
      }
    }
  }, [actingGuidedActionId, handleStructuredActionError, refresh, trackAcceptedTurn, workflowId]);

  const actOnDecisionBundle = useCallback(async (
    bundleId: string,
    request: DecisionBundleActionRequestV2,
  ) => {
    if (!workflowId || actingDecisionBundleId) return;
    const workflowGeneration = workflowGenerationRef.current;
    setActingDecisionBundleId(bundleId);
    setError(null);
    try {
      const accepted = await agentCanvasApi.actOnAgentCanvasDecisionBundle(
        workflowId,
        bundleId,
        request,
        createOperationKey(`decision-bundle-${request.action}`),
      );
      trackAcceptedTurn(accepted);
      void refresh();
    } catch (actionError) {
      if (workflowGeneration === workflowGenerationRef.current) {
        if (!handleStructuredActionError(actionError)) {
          setError(chatRequestErrorMessage(actionError, "The production decisions could not be saved."));
        }
      }
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setActingDecisionBundleId(null);
      }
    }
  }, [actingDecisionBundleId, handleStructuredActionError, refresh, trackAcceptedTurn, workflowId]);

  const submitGuidedInteraction = useCallback(async (
    interaction: GuidedInteractionV1,
    request: GuidedInteractionSubmitRequestV1,
  ) => {
    if (!workflowId || actingInteractionId || interaction.status !== "open") return false;
    const workflowGeneration = workflowGenerationRef.current;
    setActingInteractionId(interaction.interaction_id);
    setError(null);
    try {
      const accepted = await agentCanvasApi.submitAgentCanvasGuidedInteraction(
        workflowId,
        interaction.interaction_id,
        request,
        createOperationKey(`guided-interaction-${interaction.kind}`),
      );
      if (workflowGeneration !== workflowGenerationRef.current) return false;
      setNotice(accepted.replayed ? "The existing submission is still being processed." : null);
      await refresh();
      await onWorkflowRefresh?.();
      await onRuntimeRefresh?.();
      return true;
    } catch (interactionError) {
      if (workflowGeneration !== workflowGenerationRef.current) return false;
      if (!handleStructuredActionError(interactionError)) {
        setError(chatRequestErrorMessage(interactionError, "The guided response could not be submitted."));
      }
      return false;
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setActingInteractionId(null);
      }
    }
  }, [
    actingInteractionId,
    handleStructuredActionError,
    onRuntimeRefresh,
    onWorkflowRefresh,
    refresh,
    workflowId,
  ]);

  const retryTurn = useCallback(async (turnId: string, retryable: boolean) => {
    if (
      !workflowId
      || workflowRevision === null
      || sending
      || !retryable
      || retryingSourceTurnIdsRef.current.has(turnId)
    ) return false;
    const workflowGeneration = workflowGenerationRef.current;
    retryingSourceTurnIdsRef.current.add(turnId);
    setRetryingSourceTurnIds((current) => ({ ...current, [turnId]: "pending" }));
    setError(null);
    try {
      const accepted = await agentCanvasApi.retryAgentCanvasChatTurn(
        workflowId,
        turnId,
        {
          expected_session_revision: guidanceSession?.revision ?? 0,
          expected_workflow_revision: workflowRevision,
        },
        createOperationKey(`chat-turn-retry-${turnId}`),
      );
      if (workflowGeneration !== workflowGenerationRef.current) return false;
      trackAcceptedTurn(accepted);
      setNotice(accepted.replayed ? "The existing recovery attempt is still in progress." : null);
      void refresh();
      return true;
    } catch (retryError) {
      retryingSourceTurnIdsRef.current.delete(turnId);
      setRetryingSourceTurnIds((current) => {
        if (!(turnId in current)) return current;
        const next = { ...current };
        delete next[turnId];
        return next;
      });
      if (workflowGeneration !== workflowGenerationRef.current) return false;
      if (isV2ApiError(retryError) && retryError.code === "chat_turn_retry_stale") {
        setNotice("This failed request no longer matches the latest state. Review the refreshed conversation before trying again.");
        void onWorkflowRefresh?.();
        void refresh();
        return false;
      }
      setError(chatRequestErrorMessage(retryError, "The failed request could not be retried."));
      return false;
    }
  }, [guidanceSession?.revision, onWorkflowRefresh, refresh, sending, trackAcceptedTurn, workflowId, workflowRevision]);

  const retryCapabilityActivity = useCallback((activity: ChatCapabilityActivityV2) => {
    if (activity.status !== "failed") return Promise.resolve(false);
    return retryTurn(activity.turn_id, activity.retryable);
  }, [retryTurn]);

  const retryProposalMaterialization = useCallback((
    materialization: ProposalMaterializationProjectionV2,
  ) => {
    if (materialization.status !== "failed") return Promise.resolve(false);
    return retryTurn(materialization.turn_id, materialization.retryable);
  }, [retryTurn]);

  const projectedItems = useMemo(() => projectChatEvents(chatEvents), [chatEvents]);
  const items = useMemo(
    () => mergeTimelineItems(persistedItems, projectedItems, optimisticItems),
    [optimisticItems, persistedItems, projectedItems],
  );
  const retryableFailedTurn = useMemo(() => {
    const activityTurnIds = new Set(items.flatMap((item) => (
      item.item_type === "expert_activity" ? [item.turn_id] : []
    )));
    return Object.values(turnsById)
      .filter((turn) => (
        turn.status === "failed"
        && turn.retryable
        && !activityTurnIds.has(turn.turn_id)
      ))
      .sort((left, right) => right.updated_at.localeCompare(left.updated_at))[0] ?? null;
  }, [items, turnsById]);
  const agentWaitingForModel = useMemo(() => (
    Object.values(turnsById).some((turn) => (
      turn.status === "running" && turn.operation_stage === "provider_waiting"
    ))
  ), [turnsById]);

  return {
    state: {
      items,
      guidanceSession,
      guidedInteraction: guidanceSession?.interaction ?? null,
      guidanceAwaiting: guidanceSession?.awaiting ?? null,
      currentSessionActions,
      continuations: Object.values(continuationsById),
      turnsById,
      retryingSourceTurnIds,
      retryableFailedTurn,
      loading,
      sending,
      agentWorking: sending || advancingGuidance || Boolean(postReadyBarrier) || pendingAgentTurnIds.length > 0,
      postReadyCheckpoint,
      agentWaitingForModel,
      actingProposalId,
      actingDecisionBundleId,
      actingCommandPlanId,
      actingGuidedActionId,
      actingInteractionId,
      error,
      notice,
      proposalIssues,
      failedDraft,
    },
    actions: {
      refresh,
      submit,
      selectProposal,
      reviseProposal,
      applyProposalAction,
      actOnCommandPlan,
      applyGuidedAction,
      actOnDecisionBundle,
      submitGuidedInteraction,
      retryCapabilityActivity,
      retryProposalMaterialization,
      retryTurn: (turn: AgentCanvasChatTurnV2) => retryTurn(turn.turn_id, turn.retryable),
      clearFailedDraft: () => setFailedDraft(null),
      clearNotice: () => setNotice(null),
    },
  };
}
