import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { agentCanvasApi, isV2ApiError } from "../../../api/agentCanvasApi.ts";
import { createOperationKey } from "../../../api/operationKey.ts";
import type {
  AgentCanvasWorkflowV2,
  AgentCanvasContinuationV2,
  AgentCanvasCreationModeV2,
  AgentActionReceiptV2,
  AdaptiveProductionRecipeV2,
  CanvasPositionV2,
  CanvasRuntimeEventV2,
  ChatMessageV2,
  ChatTimelineItemV2,
  CreativeSessionStateV2,
  ProposedDraftReferenceV2,
} from "../../../types-v2.ts";
import { projectChatEvents } from "./projectChatEvents.ts";

type SubmitDraft = {
  text: string;
  mentionedNodeIds: string[];
  mentionedImageAssetIds: string[];
  idempotencyKey?: string;
};

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
    if (item.item_type === "proposal_pointer") return `proposal:${item.proposal_id}`;
    return `guided:${item.source_entry_id}`;
  };
  [...persisted, ...projected, ...optimistic].forEach((item) => {
    keys.set(keyFor(item), item);
  });
  return [...keys.values()].sort((left, right) => left.sequence - right.sequence);
}

export function useAgentCanvasChat({
  workflow,
  chatRevision,
  chatEvents,
  proposalPosition,
  onActionReceipt,
  onWorkflowRefresh,
}: {
  workflow: AgentCanvasWorkflowV2 | null;
  chatRevision: number;
  chatEvents: CanvasRuntimeEventV2[];
  proposalPosition: CanvasPositionV2;
  onActionReceipt?: (receipt: AgentActionReceiptV2) => void;
  onWorkflowRefresh?: () => Promise<void> | void;
}) {
  const [persistedItems, setPersistedItems] = useState<ChatTimelineItemV2[]>([]);
  const [optimisticItems, setOptimisticItems] = useState<ChatTimelineItemV2[]>([]);
  const [creativeSession, setCreativeSession] = useState<CreativeSessionStateV2 | null>(null);
  const [creationMode, setCreationMode] = useState<AgentCanvasCreationModeV2 | null>(null);
  const [recipe, setRecipe] = useState<AdaptiveProductionRecipeV2 | null>(null);
  const [continuationsById, setContinuationsById] = useState<Record<string, AgentCanvasContinuationV2>>({});
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [actingProposalId, setActingProposalId] = useState<string | null>(null);
  const [actingCommandPlanId, setActingCommandPlanId] = useState<string | null>(null);
  const [actingGuidedActionId, setActingGuidedActionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [failedDraft, setFailedDraft] = useState<SubmitDraft | null>(null);
  const refreshGenerationRef = useRef(0);
  const workflowGenerationRef = useRef(0);
  const actionKeysRef = useRef(new Map<string, string>());
  const pendingActionTurnIdsRef = useRef(new Set<string>());
  const pendingCommandPlanIdsRef = useRef(new Set<string>());
  const expectedReceiptIdsRef = useRef(new Set<string>());
  const deliveredReceiptIdsRef = useRef(new Set<string>());
  const submittedDraftsByTurnIdRef = useRef(new Map<string, SubmitDraft>());
  const workflowId = workflow?.workflow_id ?? null;

  const upsertContinuation = useCallback((continuation: AgentCanvasContinuationV2) => {
    setContinuationsById((current) => ({
      ...current,
      [continuation.continuation_id]: continuation,
    }));
  }, []);

  const refreshTurn = useCallback(async (turnId: string) => {
    if (!workflowId) return;
    try {
      const turn = await agentCanvasApi.agentCanvasChatTurn(workflowId, turnId);
      if (turn.continuation) upsertContinuation(turn.continuation);
      const terminalErrorCode = turn.continuation?.last_error_code ?? turn.error_code;
      const terminalErrorMessage = turn.continuation?.last_error_message ?? turn.error_message;
      const continuationFailed = turn.continuation?.delivery_status === "failed";
      if ((continuationFailed || turn.status === "failed") && terminalErrorCode) {
        if (terminalErrorCode === "continuation_retry_exhausted") {
          const failedMessage = submittedDraftsByTurnIdRef.current.get(turnId);
          if (failedMessage) {
            // A confirmed backend failure must use a new idempotency key when retried.
            setFailedDraft({ ...failedMessage, idempotencyKey: undefined });
          }
        }
        setError(terminalErrorMessage ?? "The agent could not complete this request.");
      }
    } catch {
      // A later timeline refresh remains authoritative after a transient turn lookup failure.
    }
  }, [upsertContinuation, workflowId]);

  const trackAcceptedTurn = useCallback((
    accepted: { turn_id: string; continuation: AgentCanvasContinuationV2 | null },
    submittedDraft?: SubmitDraft,
  ) => {
    if (submittedDraft) submittedDraftsByTurnIdRef.current.set(accepted.turn_id, submittedDraft);
    if (accepted.continuation) upsertContinuation(accepted.continuation);
    void refreshTurn(accepted.turn_id);
  }, [refreshTurn, upsertContinuation]);

  const refresh = useCallback(async () => {
    if (!workflowId) return;
    const generation = refreshGenerationRef.current + 1;
    refreshGenerationRef.current = generation;
    setLoading(true);
    try {
      const items: ChatTimelineItemV2[] = [];
      let nextCreativeSession: CreativeSessionStateV2 | null = null;
      let nextCreationMode: AgentCanvasCreationModeV2 | null = null;
      let nextRecipe: AdaptiveProductionRecipeV2 | null = null;
      const nextContinuations = new Map<string, AgentCanvasContinuationV2>();
      let hasInvalidProposalCardinality = false;
      let cursor = 0;
      for (;;) {
        const timeline = await agentCanvasApi.agentCanvasChatTimeline(workflowId, cursor, 200);
        nextCreativeSession = timeline.creative_session;
        nextCreationMode = (
          timeline.creation_mode
          ?? timeline.creative_session?.creation_mode?.mode
          ?? null
        );
        nextRecipe = timeline.recipe ?? timeline.creative_session?.active_recipe ?? null;
        (timeline.continuations ?? []).forEach((continuation) => {
          nextContinuations.set(continuation.continuation_id, continuation);
        });
        const hydrated = await Promise.all(timeline.items.map(async (item): Promise<ChatTimelineItemV2> => {
          if (item.item_type !== "proposal_pointer") return item;
          const proposal = await agentCanvasApi.agentCanvasProposal(workflowId, item.proposal_id);
          const stage = timeline.recipe?.stages.find((candidate) => candidate.topic_id === proposal.topic_id);
          if (stage && proposal.options.length !== stage.candidate_count) {
            hasInvalidProposalCardinality = true;
            // Keep the persisted pointer, which is intentionally not rendered as a proposal card.
            return item;
          }
          return {
            item_type: "proposal",
            proposal,
            sequence: item.sequence,
            created_at: item.created_at,
          };
        }));
        items.push(...hydrated);
        if (timeline.items.length < 200 || timeline.next_cursor <= cursor) break;
        cursor = timeline.next_cursor;
      }
      if (generation !== refreshGenerationRef.current) return;
      setCreativeSession(nextCreativeSession);
      setCreationMode(nextCreationMode);
      setRecipe(nextRecipe);
      setContinuationsById(Object.fromEntries(nextContinuations));
      setPersistedItems(items);
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
      setError(hasInvalidProposalCardinality
        ? "The current proposal is incomplete and needs to be regenerated."
        : null);
    } catch (refreshError) {
      if (generation !== refreshGenerationRef.current) return;
      setError(refreshError instanceof Error ? refreshError.message : "Conversation could not be loaded.");
    } finally {
      if (generation === refreshGenerationRef.current) setLoading(false);
    }
  }, [onActionReceipt, workflowId]);

  const handleStructuredActionError = useCallback((actionError: unknown): boolean => {
    if (!isV2ApiError(actionError)) return false;
    if (actionError.code === "guided_action_stale") {
      setNotice("This action is no longer current. The conversation was refreshed.");
      void refresh();
      return true;
    }
    if (actionError.code === "guided_action_no_effect") {
      setNotice("No canvas change was needed.");
      void refresh();
      return true;
    }
    if (actionError.code === "proposal_revision_anchor_drift") {
      setNotice("The previous proposal is still current. Review it before choosing again.");
      return true;
    }
    if (actionError.code === "creative_anchor_drift") {
      setNotice("The current proposal was kept because it no longer matches the approved creative direction.");
      return true;
    }
    if (actionError.code === "proposal_cardinality_invalid") {
      setError("The agent could not produce the required proposal options. Try again.");
      return true;
    }
    if (
      actionError.code === "adaptive_recipe_handoff_invalid"
      || actionError.code === "guided_session_state_conflict"
      || actionError.code === "guided_session_transaction_conflict"
    ) {
      setNotice("The production plan changed. The latest conversation state was refreshed.");
      void refresh();
      void onWorkflowRefresh?.();
      return true;
    }
    return false;
  }, [onWorkflowRefresh, refresh]);

  useEffect(() => {
    refreshGenerationRef.current += 1;
    workflowGenerationRef.current += 1;
    setPersistedItems([]);
    setOptimisticItems([]);
    setCreativeSession(null);
    setCreationMode(null);
    setRecipe(null);
    setContinuationsById({});
    setLoading(false);
    setSending(false);
    setFailedDraft(null);
    setActingProposalId(null);
    setActingCommandPlanId(null);
    setActingGuidedActionId(null);
    actionKeysRef.current.clear();
    pendingActionTurnIdsRef.current.clear();
    pendingCommandPlanIdsRef.current.clear();
    expectedReceiptIdsRef.current.clear();
    deliveredReceiptIdsRef.current.clear();
    submittedDraftsByTurnIdRef.current.clear();
    setError(null);
    setNotice(null);
  }, [workflowId]);

  useEffect(() => {
    chatEvents.forEach((event) => {
      if (event.event_type === "action_receipt_created") {
        const receiptId = event.payload?.receipt_id;
        if (typeof receiptId === "string" && !deliveredReceiptIdsRef.current.has(receiptId)) {
          expectedReceiptIdsRef.current.add(receiptId);
        }
      }
      if (event.event_type.startsWith("continuation_") && event.turn_id) {
        void refreshTurn(event.turn_id);
      }
    });
  }, [chatEvents, refreshTurn]);

  const actionKey = useCallback((identity: string, prefix: string) => {
    const existing = actionKeysRef.current.get(identity);
    if (existing) return existing;
    const created = createOperationKey(prefix);
    actionKeysRef.current.set(identity, created);
    return created;
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 80);
    return () => window.clearTimeout(timer);
  }, [chatRevision, refresh]);

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
        video_skill_run_id: null,
        auto_continue: false,
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
      trackAcceptedTurn(accepted, { ...draft, idempotencyKey });
      setError(null);
      return true;
    } catch (submitError) {
      if (workflowGeneration !== workflowGenerationRef.current) return false;
      setOptimisticItems((current) => current.filter((item) => (
        item.item_type !== "message" || item.message_id !== optimisticId
      )));
      setFailedDraft({ ...draft, idempotencyKey });
      setError(submitError instanceof Error ? submitError.message : "Message could not be sent.");
      return false;
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setSending(false);
      }
    }
  }, [trackAcceptedTurn, workflowId]);

  const selectProposal = useCallback(async (
    proposalId: string,
    optionId: string,
    generationAction: "draft_only" | "generate_now",
    acceptedReferences: ProposedDraftReferenceV2[],
  ) => {
    if (!workflowId || actingProposalId) return;
    const workflowGeneration = workflowGenerationRef.current;
    setActingProposalId(proposalId);
    setError(null);
    try {
      const request = {
        action: "select",
        option_id: optionId,
        generation_action: generationAction,
        accepted_references: acceptedReferences,
        position: proposalPosition,
      } as const;
      const accepted = await agentCanvasApi.actOnAgentCanvasProposal(
        workflowId,
        proposalId,
        request,
        actionKey(
          `proposal-select:${proposalId}:${JSON.stringify(request)}`,
          "proposal-select",
        ),
      );
      pendingActionTurnIdsRef.current.add(accepted.turn_id);
      trackAcceptedTurn(accepted);
      void refresh();
    } catch (actionError) {
      if (workflowGeneration === workflowGenerationRef.current) {
        if (!handleStructuredActionError(actionError)) {
          setError(actionError instanceof Error ? actionError.message : "The proposal could not be selected.");
        }
      }
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setActingProposalId(null);
      }
    }
  }, [actionKey, actingProposalId, handleStructuredActionError, proposalPosition, refresh, trackAcceptedTurn, workflowId]);

  const reviseProposal = useCallback(async (proposalId: string, instruction: string) => {
    if (!workflowId || !instruction.trim() || actingProposalId) return;
    const workflowGeneration = workflowGenerationRef.current;
    setActingProposalId(proposalId);
    setError(null);
    try {
      const accepted = await agentCanvasApi.actOnAgentCanvasProposal(workflowId, proposalId, {
        action: "revise",
        instruction: instruction.trim(),
      }, actionKey(
        `proposal-revise:${proposalId}:${instruction.trim()}`,
        "proposal-revise",
      ));
      pendingActionTurnIdsRef.current.add(accepted.turn_id);
      trackAcceptedTurn(accepted);
      void refresh();
    } catch (actionError) {
      if (workflowGeneration === workflowGenerationRef.current) {
        if (!handleStructuredActionError(actionError)) {
          setError(actionError instanceof Error ? actionError.message : "The proposal could not be revised.");
        }
      }
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setActingProposalId(null);
      }
    }
  }, [actionKey, actingProposalId, handleStructuredActionError, refresh, trackAcceptedTurn, workflowId]);

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
        actionKey(`command-${action}:${planId}`, `command-${action}`),
      );
      pendingActionTurnIdsRef.current.add(accepted.turn_id);
      trackAcceptedTurn(accepted);
      void refresh();
    } catch (actionError) {
      pendingCommandPlanIdsRef.current.delete(planId);
      if (workflowGeneration === workflowGenerationRef.current) {
        if (!handleStructuredActionError(actionError)) {
          setError(actionError instanceof Error
            ? actionError.message
            : `The command could not be ${action === "confirm" ? "confirmed" : "rejected"}.`);
        }
      }
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setActingCommandPlanId(null);
      }
    }
  }, [actionKey, actingCommandPlanId, handleStructuredActionError, refresh, trackAcceptedTurn, workflowId]);

  const applyGuidedAction = useCallback(async (actionId: string) => {
    if (!workflowId || actingGuidedActionId) return;
    const workflowGeneration = workflowGenerationRef.current;
    setActingGuidedActionId(actionId);
    setError(null);
    try {
      const accepted = await agentCanvasApi.applyAgentCanvasGuidedAction(
        workflowId,
        actionId,
        { confirmed: true },
        actionKey(`guided-action:${actionId}`, "guided-action"),
      );
      pendingActionTurnIdsRef.current.add(actionId);
      trackAcceptedTurn(accepted);
      void refresh();
    } catch (actionError) {
      if (workflowGeneration === workflowGenerationRef.current) {
        if (!handleStructuredActionError(actionError)) {
          setError(actionError instanceof Error
            ? actionError.message
            : "The guided action could not be applied.");
        }
      }
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setActingGuidedActionId(null);
      }
    }
  }, [actingGuidedActionId, actionKey, handleStructuredActionError, refresh, trackAcceptedTurn, workflowId]);

  const projectedItems = useMemo(() => projectChatEvents(chatEvents), [chatEvents]);
  const items = useMemo(
    () => mergeTimelineItems(persistedItems, projectedItems, optimisticItems),
    [optimisticItems, persistedItems, projectedItems],
  );

  return {
    state: {
      items,
      creativeSession,
      creationMode,
      recipe,
      continuations: Object.values(continuationsById),
      loading,
      sending,
      actingProposalId,
      actingCommandPlanId,
      actingGuidedActionId,
      error,
      notice,
      failedDraft,
    },
    actions: {
      refresh,
      submit,
      selectProposal,
      reviseProposal,
      actOnCommandPlan,
      applyGuidedAction,
      clearFailedDraft: () => setFailedDraft(null),
      clearNotice: () => setNotice(null),
    },
  };
}
