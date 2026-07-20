import { useEffect, useRef, type Dispatch, type MutableRefObject, type RefObject, type SetStateAction } from "react";
import type { AgentConversationEvent, UploadedAsset, WorkflowExecutionState, WorkflowRunResponse } from "../../../types";
import {
  chatCanvasActionKind,
  chatCanvasActiveExecutionId,
  chatCanvasErrorCode,
  chatCanvasExecutionId,
  chatCanvasRefreshHints,
  isChatCanvasExecutionConflictCode,
} from "../../../workflow/chatCanvasActions";
import { isExecutionRuntimeTerminal, type ExecutionPollingState } from "../../../workflow/executionRuntime";
import { localRevisionStateKey } from "../../../workflow/localRevision";
import { shouldApplyWorkflowScopedResult } from "../../../workflow/sessionGuards";
import { nodeMentionErrorMessage } from "../../../workflow/nodeMentions";
import { sleep } from "../page/workflowPageFormatters";
import type { LocalRevisionCardState } from "../assets/useWorkflowAssetOperations";
import type { ScopedWorkflowRefreshPlan } from "../runtime/useCanvasRuntimeEventController";
import {
  conversationEventCode,
  conversationEventMemorySummary,
  conversationEventPromptText,
  conversationEventRevisionId,
  conversationEventRevisionStatus,
  conversationEventSpecialistResultSummary,
  conversationEventStringArray,
  conversationEventTargetItemId,
  conversationEventTargetNodeId,
  isRevisionConversationEventType,
  revisionConversationEventStatusText,
} from "./agentConversationPanelModel";
import {
  workflowRunResponseFromExecutionState,
  workflowRunResultFromExecution,
} from "../runtime/workflowExecutionViewModel";

type StateSetter<T> = Dispatch<SetStateAction<T>>;

export type ConversationEventRouterArgs = {
  activeWorkflowIdRef: RefObject<string | null>;
  selectedNodeIdRef: RefObject<string>;
  chatCanvasExecutionRequestRef: MutableRefObject<number>;
  setStatus: StateSetter<string>;
  setDynamicItemPromptDrafts: StateSetter<Record<string, string>>;
  setDynamicItemRunningById: StateSetter<Record<string, boolean>>;
  setActiveExecutionId: StateSetter<string | null>;
  setExecutionPollingState: StateSetter<ExecutionPollingState>;
  setWorkflowRun: StateSetter<WorkflowRunResponse | null>;
  clearPendingNodePatch: (nodeId: string) => void;
  clearNodeDebugCache: (nodeId: string) => void;
  markNodesStale: (nodeIds: string[], reason?: string) => void;
  queueScopedWorkflowRefresh: (workflowId: string, plan: ScopedWorkflowRefreshPlan) => void;
  scopedRefreshPlanFromHints: (refreshHints: string[], targetNodeId?: string | null) => ScopedWorkflowRefreshPlan;
  refreshExecutionRuntime: (workflowId: string, executionId: string) => Promise<WorkflowExecutionState | null>;
  applyWorkflowRunSummary: (response: WorkflowRunResponse) => void;
  updateLocalRevisionCardState: (key: string, patch: Partial<LocalRevisionCardState>) => void;
  loadLocalAssetHistory: (workflowId: string, nodeId: string, asset: UploadedAsset) => Promise<unknown>;
  dynamicMediaItemAssetFromRevisionEvent: (event: AgentConversationEvent, itemId: string) => UploadedAsset;
};

export function useConversationEventRouter(args: ConversationEventRouterArgs) {
  const argsRef = useRef(args);

  useEffect(() => {
    argsRef.current = args;
  }, [args]);

  async function handleAgentConversationEvents(events: AgentConversationEvent[], workflowId: string) {
    const actionKind = chatCanvasActionKind(events);
    for (const event of events) {
      if (event.event_type === "director_context_updated") {
        await handleDirectorContextUpdatedEvent(event, workflowId);
      } else if (event.event_type === "clarification_requested") {
        await handleClarificationRequestedEvent(event);
      } else if (event.event_type === "conversation_memory_updated") {
        await handleConversationMemoryUpdatedEvent(event);
      } else if (event.event_type === "specialist_result") {
        await handleSpecialistResultEvent(event);
      } else if (event.event_type === "chat_action_created" || event.event_type === "chat_action_applied" || event.event_type === "chat_action_rejected" || event.event_type === "chat_action_failed") {
        await handleChatActionStateEvent(event, workflowId);
      } else if (event.event_type === "node_prompt_updated") {
        await handleNodePromptUpdatedEvent(event, workflowId);
      } else if (event.event_type === "item_prompt_updated") {
        await handleItemPromptUpdatedEvent(event, workflowId);
      } else if (event.event_type === "execution_started") {
        await handleExecutionStartedEvent(event, workflowId);
      } else if (isRevisionConversationEventType(event.event_type)) {
        await handleRevisionConversationEvent(event, workflowId);
      } else if (event.event_type === "error") {
        await handleChatCanvasErrorEvent(event, workflowId);
      }
    }
    if (actionKind === "none") return;
  }

  async function handleChatActionStateEvent(event: AgentConversationEvent, workflowId: string) {
    const { selectedNodeIdRef, queueScopedWorkflowRefresh, scopedRefreshPlanFromHints, setStatus } = argsRef.current;
    const refreshHints = chatCanvasRefreshHints(event);
    if (event.event_type === "chat_action_rejected") {
      setStatus(event.text || "Director action rejected");
      return;
    }
    if (event.event_type === "chat_action_failed") {
      setStatus(nodeMentionErrorMessage(conversationEventCode(event), event.text || "Director action failed"));
      return;
    }
    if (event.event_type === "chat_action_created") {
      setStatus(event.text || "Director action needs confirmation");
      return;
    }
    queueScopedWorkflowRefresh(workflowId, scopedRefreshPlanFromHints(refreshHints, event.target_node_id ?? selectedNodeIdRef.current));
    setStatus(event.text || "Director action applied");
  }

  async function handleConversationMemoryUpdatedEvent(event: AgentConversationEvent) {
    const summary = conversationEventMemorySummary(event);
    argsRef.current.setStatus(summary.statusText || event.text || "Conversation memory updated");
  }

  async function handleSpecialistResultEvent(event: AgentConversationEvent) {
    const summary = conversationEventSpecialistResultSummary(event);
    argsRef.current.setStatus(summary.statusText || event.text || "Specialist result received");
  }

  async function handleDirectorContextUpdatedEvent(event: AgentConversationEvent, workflowId: string) {
    const { activeWorkflowIdRef, selectedNodeIdRef, markNodesStale, queueScopedWorkflowRefresh, setStatus } = argsRef.current;
    if (!shouldApplyWorkflowScopedResult(workflowId, activeWorkflowIdRef.current)) return;
    const refreshHints = chatCanvasRefreshHints(event);
    const affectedNodeIds = conversationEventStringArray(event, "affected_node_ids");
    const shouldRefreshGraph = !refreshHints.length || refreshHints.includes("workflow_graph") || refreshHints.includes("director_context");
    const shouldRefreshNodes = !refreshHints.length || refreshHints.includes("node") || refreshHints.includes("workflow_graph");
    const shouldRefreshResolved = !refreshHints.length || refreshHints.includes("resolved_inputs");
    const currentSelectedNodeId = selectedNodeIdRef.current;

    if (affectedNodeIds.length) markNodesStale(affectedNodeIds, "Director context updated");
    queueScopedWorkflowRefresh(workflowId, {
      graph: shouldRefreshGraph,
      nodeIds: shouldRefreshNodes ? affectedNodeIds : [],
      resolvedInputNodeIds: currentSelectedNodeId && shouldRefreshResolved && (!affectedNodeIds.length || affectedNodeIds.includes(currentSelectedNodeId)) ? [currentSelectedNodeId] : [],
    });
    setStatus(event.text || "Director context updated");
  }

  async function handleClarificationRequestedEvent(event: AgentConversationEvent) {
    argsRef.current.setStatus(event.text || "Creative Director needs clarification");
  }

  async function handleChatCanvasErrorEvent(event: AgentConversationEvent, workflowId: string) {
    const { selectedNodeIdRef, queueScopedWorkflowRefresh, setStatus } = argsRef.current;
    const code = chatCanvasErrorCode(event);
    const activeExecutionId = chatCanvasActiveExecutionId(event);
    setStatus(nodeMentionErrorMessage(code, event.text));
    const currentSelectedNodeId = selectedNodeIdRef.current;
    if (code === "target_item_not_found" && currentSelectedNodeId) {
      queueScopedWorkflowRefresh(workflowId, { nodeIds: [currentSelectedNodeId], resolvedInputNodeIds: [currentSelectedNodeId] });
    }
    if (code === "target_asset_not_found") {
      queueScopedWorkflowRefresh(workflowId, { nodeIds: [currentSelectedNodeId], mediaStatus: true, resolvedInputNodeIds: [currentSelectedNodeId] });
    }
    if (activeExecutionId && isChatCanvasExecutionConflictCode(code)) {
      startChatCanvasExecutionObservation(workflowId, activeExecutionId, event);
    }
  }

  async function handleNodePromptUpdatedEvent(event: AgentConversationEvent, workflowId: string) {
    const { activeWorkflowIdRef, selectedNodeIdRef, clearPendingNodePatch, clearNodeDebugCache, markNodesStale, queueScopedWorkflowRefresh, setStatus } = argsRef.current;
    const targetNodeId = conversationEventTargetNodeId(event);
    if (!targetNodeId || !shouldApplyWorkflowScopedResult(workflowId, activeWorkflowIdRef.current)) return;
    clearPendingNodePatch(targetNodeId);
    clearNodeDebugCache(targetNodeId);
    const currentSelectedNodeId = selectedNodeIdRef.current;
    const staleNodeIds = conversationEventStringArray(event, "stale_node_ids");
    if (staleNodeIds.length) markNodesStale(staleNodeIds, "Prompt updated from chat");
    queueScopedWorkflowRefresh(workflowId, {
      graph: true,
      nodeIds: [targetNodeId],
      resolvedInputNodeIds: currentSelectedNodeId && (currentSelectedNodeId === targetNodeId || staleNodeIds.includes(currentSelectedNodeId)) ? [currentSelectedNodeId] : [],
    });
    setStatus(event.text || "Node prompt updated");
  }

  async function handleItemPromptUpdatedEvent(event: AgentConversationEvent, workflowId: string) {
    const { activeWorkflowIdRef, selectedNodeIdRef, clearPendingNodePatch, clearNodeDebugCache, setDynamicItemPromptDrafts, queueScopedWorkflowRefresh, setStatus } = argsRef.current;
    const targetNodeId = conversationEventTargetNodeId(event);
    const targetItemId = conversationEventTargetItemId(event);
    if (!targetNodeId || !shouldApplyWorkflowScopedResult(workflowId, activeWorkflowIdRef.current)) return;
    clearPendingNodePatch(targetNodeId);
    clearNodeDebugCache(targetNodeId);
    const prompt = conversationEventPromptText(event);
    if (targetItemId && prompt) {
      setDynamicItemPromptDrafts((current) => ({ ...current, [targetItemId]: prompt }));
    }
    const currentSelectedNodeId = selectedNodeIdRef.current;
    queueScopedWorkflowRefresh(workflowId, {
      nodeIds: [targetNodeId],
      resolvedInputNodeIds: currentSelectedNodeId && currentSelectedNodeId === targetNodeId ? [currentSelectedNodeId] : [],
    });
    setStatus(event.text || "Item prompt updated");
  }

  async function handleExecutionStartedEvent(event: AgentConversationEvent, workflowId: string) {
    const { selectedNodeIdRef, queueScopedWorkflowRefresh, scopedRefreshPlanFromHints, setStatus } = argsRef.current;
    const executionId = chatCanvasExecutionId(event);
    if (executionId) {
      startChatCanvasExecutionObservation(workflowId, executionId, event);
    }
    const refreshHints = chatCanvasRefreshHints(event);
    queueScopedWorkflowRefresh(workflowId, scopedRefreshPlanFromHints(refreshHints, selectedNodeIdRef.current));
    setStatus(event.text || "Execution started");
  }

  async function handleRevisionConversationEvent(event: AgentConversationEvent, workflowId: string) {
    const {
      activeWorkflowIdRef,
      selectedNodeIdRef,
      dynamicMediaItemAssetFromRevisionEvent,
      updateLocalRevisionCardState,
      queueScopedWorkflowRefresh,
      loadLocalAssetHistory,
      setDynamicItemRunningById,
      setStatus,
    } = argsRef.current;
    const targetNodeId = conversationEventTargetNodeId(event) || selectedNodeIdRef.current;
    const targetItemId = conversationEventTargetItemId(event);
    if (!targetNodeId || !targetItemId || !shouldApplyWorkflowScopedResult(workflowId, activeWorkflowIdRef.current)) return;
    const targetAsset = dynamicMediaItemAssetFromRevisionEvent(event, targetItemId);
    const revisionKey = localRevisionStateKey(workflowId, targetNodeId, targetAsset);
    updateLocalRevisionCardState(revisionKey, {
      revisionId: conversationEventRevisionId(event) || undefined,
      status: conversationEventRevisionStatus(event),
      message: event.text || null,
      error: event.event_type === "revision_failed" ? event.text || "Item regeneration failed" : null,
    });
    if (event.event_type === "revision_completed") {
      const currentSelectedNodeId = selectedNodeIdRef.current;
      queueScopedWorkflowRefresh(workflowId, {
        nodeIds: [targetNodeId],
        mediaStatus: true,
        resolvedInputNodeIds: currentSelectedNodeId && currentSelectedNodeId === targetNodeId ? [currentSelectedNodeId] : [],
      });
      await loadLocalAssetHistory(workflowId, targetNodeId, targetAsset);
    }
    setDynamicItemRunningById((current) => ({
      ...current,
      [targetItemId]: event.event_type === "revision_started" || event.event_type === "revision_waiting",
    }));
    setStatus(event.text || revisionConversationEventStatusText(event.event_type));
  }

  function startChatCanvasExecutionObservation(workflowId: string, executionId: string, event: AgentConversationEvent) {
    const { chatCanvasExecutionRequestRef, setActiveExecutionId, setExecutionPollingState } = argsRef.current;
    const token = chatCanvasExecutionRequestRef.current + 1;
    chatCanvasExecutionRequestRef.current = token;
    setActiveExecutionId(executionId);
    setExecutionPollingState("polling");
    void observeChatCanvasExecution(workflowId, executionId, token, event);
  }

  async function observeChatCanvasExecution(
    workflowId: string,
    executionId: string,
    token: number,
    event: AgentConversationEvent,
  ) {
    let latest: WorkflowExecutionState | null = null;
    for (let attempt = 0; attempt < 45; attempt += 1) {
      if (attempt > 0) await sleep(latest?.status === "waiting" ? 2500 : 1500);
      const { chatCanvasExecutionRequestRef, activeWorkflowIdRef, refreshExecutionRuntime, setStatus } = argsRef.current;
      if (token !== chatCanvasExecutionRequestRef.current || !shouldApplyWorkflowScopedResult(workflowId, activeWorkflowIdRef.current)) return;
      latest = await refreshExecutionRuntime(workflowId, executionId);
      if (!latest || !shouldApplyWorkflowScopedResult(workflowId, activeWorkflowIdRef.current)) continue;
      if (!isExecutionRuntimeTerminal(latest.status)) continue;
      await refreshWorkflowAfterChatExecution(workflowId, latest);
      const finalStatus = latest.status?.toLowerCase() ?? "";
      if (finalStatus.includes("fail") || finalStatus.includes("error")) {
        setStatus(event.text || "Chat execution failed");
      } else {
        setStatus(event.text || "Chat execution complete");
      }
      return;
    }
  }

  async function refreshWorkflowAfterChatExecution(workflowId: string, latest: WorkflowExecutionState) {
    const { selectedNodeIdRef, setWorkflowRun, applyWorkflowRunSummary, queueScopedWorkflowRefresh } = argsRef.current;
    const result = workflowRunResultFromExecution(latest) ?? workflowRunResponseFromExecutionState(latest);
    setWorkflowRun(result);
    applyWorkflowRunSummary(result);
    const currentSelectedNodeId = selectedNodeIdRef.current;
    queueScopedWorkflowRefresh(workflowId, {
      graph: true,
      mediaStatus: true,
      resolvedInputNodeIds: [currentSelectedNodeId],
    });
  }

  return {
    actions: {
      handleAgentConversationEvents,
      handleChatActionStateEvent,
      handleConversationMemoryUpdatedEvent,
      handleSpecialistResultEvent,
      handleDirectorContextUpdatedEvent,
      handleClarificationRequestedEvent,
      handleChatCanvasErrorEvent,
      handleNodePromptUpdatedEvent,
      handleItemPromptUpdatedEvent,
      handleExecutionStartedEvent,
      handleRevisionConversationEvent,
      startChatCanvasExecutionObservation,
      observeChatCanvasExecution,
      refreshWorkflowAfterChatExecution,
    },
  };
}
