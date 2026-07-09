import { useCallback, useEffect, useRef } from "react";
import { api } from "../../../api/client.ts";
import { v2Api } from "../../../api/v2Client.ts";
import type {
  AgentConversation,
  AgentConversationEvent,
  AgentConversationSuggestedAction,
  FrontDeskMessage,
  WorkflowGraph,
  WorkflowNode,
} from "../../../types.ts";
import type { AssetOwnerResponseV2, WorkflowItemV2, WorkflowSlotV2, WorkflowV2, WorkflowV2ChatTarget } from "../../../types-v2.ts";
import {
  appendConversationEvents,
  conversationEventsFromActionResponse,
  conversationEventsFromResponse,
} from "../../../workflow/agentConversations.ts";
import { applyCanvasTargetIntentScope } from "../../../workflow/canvasTargets.ts";
import { buildNodeMentionRequestContext } from "../../../workflow/nodeMentions.ts";
import { shouldApplyWorkflowScopedResult } from "../../../workflow/sessionGuards.ts";
import { buildV2ChatTarget } from "../../../workflow-v2/agentRouting.ts";
import type { PromptGenerateContext } from "../../../components/PromptComposer.tsx";
import { buildV2ChatActionPayload } from "../v2/chat/v2ChatActionPayload.ts";
import {
  v2ChatActionAttachmentsFromLocators,
  v2ChatActionResponseStartedGeneration,
  v2ChatTargetsFromCanvasReferences,
} from "../v2/chat/v2ChatActionViewModel.ts";
import {
  createClientConversationErrorEvent,
  createFrontDeskBridgeConversation,
  createUserConversationEvent,
  frontDeskConversationId,
  frontDeskMessagesAsConversationEvents,
  isFrontDeskBridgeConversationId,
} from "./agentConversationPanelModel.ts";
import type { WorkflowConversationController } from "./useWorkflowConversationController.ts";
import type { ScopedWorkflowRefreshPlan } from "../runtime/useCanvasRuntimeEventController.ts";

export type AgentConversationBridgeArgs = {
  workflow: WorkflowGraph | null | undefined;
  selectedPlanNode: WorkflowNode | null | undefined;
  activeWorkflowIdRef: React.RefObject<string | null>;
  conversation: WorkflowConversationController;
  messages: FrontDeskMessage[];
  currentWorkflowIsV2: () => boolean;
  getWorkflowNodeType: (node: WorkflowNode) => string;
  defaultV2SlotForCurrentNode: () => WorkflowSlotV2 | null;
  selectedV2Items: WorkflowItemV2[];
  setStatus: (message: string) => void;
  askCopilot: (prompt: string, context?: PromptGenerateContext) => Promise<void>;
  applyWorkflowV2: (workflow: WorkflowV2) => Promise<void>;
  applyV2RuntimeEventsToPage: (events: NonNullable<Awaited<ReturnType<typeof v2Api.chatAction>>["events"]>) => void;
  handleAgentConversationEvents: (events: AgentConversationEvent[], workflowId: string) => Promise<void>;
  queueScopedWorkflowRefresh: (workflowId: string, plan: ScopedWorkflowRefreshPlan) => void;
};

export function useAgentConversationBridge(args: AgentConversationBridgeArgs) {
  const argsRef = useRef(args);
  const frontDeskBridgeRef = useRef<{ conversationId: string; workflowId: string } | null>(null);

  useEffect(() => {
    argsRef.current = args;
  }, [args]);

  const appendConversationEventForConversation = useCallback((conversationId: string, event: AgentConversationEvent) => {
    argsRef.current.conversation.actions.setConversationEventsById((current) => ({
      ...current,
      [conversationId]: appendConversationEvents(current[conversationId] ?? [], [event]),
    }));
  }, []);

  const appendConversationEventsForConversation = useCallback((conversationId: string, events: AgentConversationEvent[]) => {
    if (!events.length) return;
    argsRef.current.conversation.actions.setConversationEventsById((current) => ({
      ...current,
      [conversationId]: appendConversationEvents(current[conversationId] ?? [], events),
    }));
  }, []);

  const preserveFrontDeskBridgeConversation = useCallback((items: AgentConversation[], workflowId: string) => {
    const bridge = frontDeskBridgeRef.current;
    if (!bridge || bridge.workflowId !== workflowId) return items;
    if (items.some((conversation) => conversation.conversation_id === bridge.conversationId)) return items;
    return [createFrontDeskBridgeConversation(workflowId, bridge.conversationId), ...items];
  }, []);

  const loadAgentConversations = useCallback(async () => {
    const { workflow, conversation } = argsRef.current;
    const {
      setAgentConversations,
      setActiveConversationId,
      setConversationEventsById,
      setConversationLoading,
      setConversationError,
    } = conversation.actions;
    if (!workflow?.workflow_id) {
      frontDeskBridgeRef.current = null;
      setAgentConversations([]);
      setActiveConversationId(null);
      setConversationEventsById({});
      setConversationError(null);
      return;
    }
    const requestWorkflowId = workflow.workflow_id;
    setConversationLoading(true);
    setConversationError(null);
    try {
      const response = await api.listAgentConversations({ workflow_id: requestWorkflowId, status: "active" });
      const items = preserveFrontDeskBridgeConversation(response.items ?? [], requestWorkflowId);
      setAgentConversations(items);
      setConversationEventsById((current) =>
        Object.fromEntries(
          items.map((conversationItem) => {
            const backendEvents = conversationEventsFromResponse({
              conversation_id: conversationItem.conversation_id,
              events: conversationItem.events ?? [],
              suggested_actions: conversationItem.suggested_actions ?? [],
            });
            const bridge = frontDeskBridgeRef.current;
            const bridgeEvents = bridge?.workflowId === requestWorkflowId && bridge.conversationId === conversationItem.conversation_id
              ? current[conversationItem.conversation_id] ?? []
              : [];
            return [conversationItem.conversation_id, appendConversationEvents(bridgeEvents, backendEvents)];
          }),
        ),
      );
      setActiveConversationId((current) =>
        current && items.some((conversationItem) => conversationItem.conversation_id === current)
          ? current
          : items[0]?.conversation_id ?? null,
      );
    } catch (error) {
      setConversationError(error instanceof Error ? error.message : "Agent conversation history failed to load");
    } finally {
      setConversationLoading(false);
    }
  }, [preserveFrontDeskBridgeConversation]);

  const bridgeFrontDeskMessagesToAgentConversation = useCallback(async (workflowId: string, bridgedMessages: FrontDeskMessage[]) => {
    if (!bridgedMessages.length) return;
    let conversation: AgentConversation | null = null;
    try {
      conversation = await api.createAgentConversation({
        workflow_id: workflowId,
        focus_node_id: null,
        topic: "Initial brief",
      });
    } catch {
      // Keep a local bridge so the first prompt-to-workflow exchange stays visible.
    }
    const conversationId = conversation?.conversation_id ?? frontDeskConversationId(workflowId);
    frontDeskBridgeRef.current = { conversationId, workflowId };
    const bridgeEvents = frontDeskMessagesAsConversationEvents(bridgedMessages, {
      conversationId,
      workflowId,
      bridge: true,
    });
    const bridgeConversation = conversation ?? createFrontDeskBridgeConversation(workflowId, conversationId);
    const { setAgentConversations, setConversationEventsById, setActiveConversationId } = argsRef.current.conversation.actions;
    setAgentConversations((current) => [
      bridgeConversation,
      ...current.filter((item) => item.conversation_id !== conversationId),
    ]);
    setConversationEventsById((current) => ({
      ...current,
      [conversationId]: appendConversationEvents(current[conversationId] ?? [], bridgeEvents),
    }));
    setActiveConversationId(conversationId);
  }, []);

  const createAgentConversation = useCallback(async (topic?: string) => {
    const { workflow, selectedPlanNode, conversation } = argsRef.current;
    if (!workflow?.workflow_id) throw new Error("Create or restore a workflow before starting an agent conversation.");
    const created = await api.createAgentConversation({
      workflow_id: workflow.workflow_id,
      focus_node_id: selectedPlanNode?.id ?? null,
      topic: topic ?? (selectedPlanNode ? `${selectedPlanNode.title} discussion` : "Creative conversation"),
    });
    conversation.actions.setAgentConversations((current) => [created, ...current.filter((item) => item.conversation_id !== created.conversation_id)]);
    conversation.actions.setConversationEventsById((current) => ({
      ...current,
      [created.conversation_id]: conversationEventsFromResponse({
        conversation_id: created.conversation_id,
        events: created.events ?? [],
        suggested_actions: created.suggested_actions ?? [],
      }),
    }));
    conversation.actions.setActiveConversationId(created.conversation_id);
    return created.conversation_id;
  }, []);

  const ensureActiveAgentConversation = useCallback(async () => {
    const { workflow, conversation } = argsRef.current;
    const activeConversationId = conversation.state.activeConversationId;
    if (activeConversationId && !isFrontDeskBridgeConversationId(activeConversationId)) return activeConversationId;
    const localConversationId = activeConversationId;
    const localEvents = localConversationId ? conversation.state.conversationEventsById[localConversationId] ?? [] : [];
    const conversationId = await createAgentConversation();
    if (workflow?.workflow_id && localConversationId && localEvents.length) {
      const bridgedEvents = localEvents.map((event) => ({
        ...event,
        conversation_id: conversationId,
        workflow_id: workflow.workflow_id,
      }));
      frontDeskBridgeRef.current = { conversationId, workflowId: workflow.workflow_id };
      conversation.actions.setConversationEventsById((current) => ({
        ...current,
        [conversationId]: appendConversationEvents(current[conversationId] ?? [], bridgedEvents),
      }));
    }
    return conversationId;
  }, [createAgentConversation]);

  const sendAgentConversationMessage = useCallback(async (prompt: string, context: PromptGenerateContext = { asset_references: [] }) => {
    const { workflow, selectedPlanNode, conversation, getWorkflowNodeType, setStatus, handleAgentConversationEvents } = argsRef.current;
    if (!workflow?.workflow_id) {
      setStatus("Create or restore a workflow before starting an agent conversation");
      return;
    }
    conversation.actions.setConversationSending(true);
    conversation.actions.setConversationError(null);
    setStatus("Agent conversation running...");
    let requestConversationId = conversation.state.activeConversationId;
    try {
      requestConversationId = await ensureActiveAgentConversation();
      appendConversationEventForConversation(requestConversationId, createUserConversationEvent(requestConversationId, prompt, workflow.workflow_id, selectedPlanNode?.id ?? null));
      const targetRequest = buildNodeMentionRequestContext(context.node_references ?? [], {
        workflowId: workflow.workflow_id,
        selectedNodeId: selectedPlanNode?.id ?? null,
        selectedNodeType: selectedPlanNode ? getWorkflowNodeType(selectedPlanNode) : null,
        selectedItemId: context.selected_item_id ?? null,
        selectedAssetId: context.selected_asset_id ?? null,
        targetReferences: context.target_references ?? [],
      });
      targetRequest.target_references = applyCanvasTargetIntentScope(targetRequest.target_references, prompt);
      const response = await api.sendAgentConversationMessage(requestConversationId, {
        message: prompt,
        agent_mentions: [],
        asset_references: context.asset_references,
        node_references: context.node_references,
        target_references: targetRequest.target_references,
        context: {
          ...targetRequest.context,
          workflow_id: workflow.workflow_id,
          selected_node_id: targetRequest.context.selected_node_id,
          focus_node_id: selectedPlanNode?.id ?? null,
          selected_item_id: targetRequest.context.selected_item_id,
          selected_asset_id: targetRequest.context.selected_asset_id,
          mentioned_node_ids: targetRequest.context.mentioned_node_ids,
        },
      });
      const events = conversationEventsFromResponse(response);
      appendConversationEventsForConversation(response.conversation_id, events);
      await handleAgentConversationEvents(events, workflow.workflow_id);
      conversation.actions.setConversationMentionReferences([]);
      conversation.actions.setConversationNodeReferences([]);
      conversation.actions.setConversationTargetReferences([]);
      if (!events.some((event) => event.event_type === "node_prompt_updated" || event.event_type === "execution_started" || event.event_type === "error")) {
        setStatus("Agent conversation updated");
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Agent conversation failed";
      conversation.actions.setConversationError(message);
      setStatus(message);
      if (requestConversationId) {
        appendConversationEventForConversation(requestConversationId, createClientConversationErrorEvent(requestConversationId, message));
      }
    } finally {
      conversation.actions.setConversationSending(false);
    }
  }, [appendConversationEventForConversation, appendConversationEventsForConversation, ensureActiveAgentConversation]);

  const selectedV2ChatTarget = useCallback((context: PromptGenerateContext = { asset_references: [] }): WorkflowV2ChatTarget => {
    const { defaultV2SlotForCurrentNode, selectedV2Items, selectedPlanNode } = argsRef.current;
    return buildV2ChatTarget({
      explicitTarget: context.target_references?.[0] ?? null,
      explicitAssetId: context.selected_asset_id ?? null,
      fallbackSlot: defaultV2SlotForCurrentNode(),
      fallbackItem: selectedV2Items[0] ?? null,
      fallbackNodeId: selectedPlanNode?.id ?? null,
    });
  }, []);

  const backendSafeV2ChatActionTarget = useCallback((target: WorkflowV2ChatTarget): WorkflowV2ChatTarget => {
    if (target.target_type === "slot" && target.slot_id) return target;
    if (target.target_type === "asset" && target.asset_id) return target;
    if (target.target_type === "free_node" && target.node_id) return target;
    const fallbackSlot = argsRef.current.defaultV2SlotForCurrentNode();
    if (fallbackSlot) {
      return {
        target_type: "slot",
        node_id: fallbackSlot.node_id,
        item_id: fallbackSlot.item_id,
        slot_id: fallbackSlot.slot_id,
      };
    }
    return { target_type: "free_node", node_id: argsRef.current.selectedPlanNode?.id ?? target.node_id ?? null };
  }, []);

  const selectedV2ChatTargetForRequest = useCallback(async (context: PromptGenerateContext = { asset_references: [] }): Promise<{ target: WorkflowV2ChatTarget; assetOwner: AssetOwnerResponseV2 | null; ownerLookupError?: string }> => {
    const target = backendSafeV2ChatActionTarget(selectedV2ChatTarget(context));
    const workflow = argsRef.current.workflow;
    if (!workflow?.workflow_id || target.target_type !== "asset" || !target.asset_id) {
      return { target, assetOwner: null };
    }
    try {
      const assetOwner = await v2Api.assetOwner(workflow.workflow_id, target.asset_id);
      return { target, assetOwner };
    } catch (error) {
      return {
        target,
        assetOwner: null,
        ownerLookupError: error instanceof Error ? error.message : "asset owner lookup failed",
      };
    }
  }, [backendSafeV2ChatActionTarget, selectedV2ChatTarget]);

  const ensureLocalV2Conversation = useCallback((workflowId: string) => {
    const { conversation } = argsRef.current;
    const conversationId = conversation.state.activeConversationId || frontDeskConversationId(workflowId);
    conversation.actions.setActiveConversationId(conversationId);
    conversation.actions.setAgentConversations((current) =>
      current.some((item) => item.conversation_id === conversationId)
        ? current
        : [createFrontDeskBridgeConversation(workflowId, conversationId), ...current],
    );
    return conversationId;
  }, []);

  const resolveV2AssetLocatorsForChat = useCallback(async (workflowId: string, assetLocators: string[]) => {
    return Promise.all(assetLocators.map((locator) => v2Api.resolveLocator(workflowId, locator)));
  }, []);

  const sendV2ChatTargetMessage = useCallback(async (prompt: string, context: PromptGenerateContext = { asset_references: [] }) => {
    const { workflow, selectedPlanNode, conversation, setStatus, messages, applyWorkflowV2, applyV2RuntimeEventsToPage } = argsRef.current;
    if (!workflow?.workflow_id || !argsRef.current.currentWorkflowIsV2()) {
      setStatus("Create or restore a V2 workflow before sending a V2 chat target action.");
      return;
    }
    conversation.actions.setConversationSending(true);
    conversation.actions.setConversationError(null);
    setStatus("Sending V2 target action...");
    const workflowId = workflow.workflow_id;
    const conversationId = ensureLocalV2Conversation(workflowId);
    appendConversationEventForConversation(conversationId, createUserConversationEvent(conversationId, prompt, workflowId, selectedPlanNode?.id ?? null));
    try {
      const scopedTargetReferences = applyCanvasTargetIntentScope(context.target_references ?? [], prompt);
      const asset_locators = Array.from(new Set(context.asset_locators ?? []));
      const resolvedLocators = await resolveV2AssetLocatorsForChat(workflowId, asset_locators);
      const locatorTargetReferences = resolvedLocators.flatMap((item) => item.target ? [item.target] : []);
      const target_references = [
        ...v2ChatTargetsFromCanvasReferences(scopedTargetReferences),
        ...locatorTargetReferences,
        ...(context.structuredTargets ?? []),
      ];
      const owner_display_names = resolvedLocators
        .map((item) => item.owner?.owner_display_name)
        .filter((name): name is string => Boolean(name));
      const resolvedTarget = await selectedV2ChatTargetForRequest({ ...context, target_references: scopedTargetReferences });
      const actionPayload = buildV2ChatActionPayload({
        message: prompt,
        actionMode: "auto",
        selectedTarget: resolvedTarget.target,
        explicitTargets: target_references,
        assetLocators: asset_locators,
        history: messages,
        attachments: v2ChatActionAttachmentsFromLocators(resolvedLocators),
        context: {
          selected_node_id: selectedPlanNode?.id ?? null,
          selected_item_id: context.selected_item_id ?? null,
          selected_asset_id: context.selected_asset_id ?? null,
          asset_owner: resolvedTarget.assetOwner?.owner ?? null,
          asset_owner_relations: resolvedTarget.assetOwner?.relations ?? [],
          asset_owner_lookup_error: resolvedTarget.ownerLookupError ?? null,
          owner_display_name: owner_display_names[0] ?? null,
          owner_display_names,
        },
      });
      const response = await v2Api.chatAction(workflowId, actionPayload);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      const generated = v2ChatActionResponseStartedGeneration(response);
      appendConversationEventForConversation(conversationId, {
        event_id: `v2_chat_action_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
        conversation_id: conversationId,
        event_type: generated ? "revision_started" : "chat_action_applied",
        speaker_agent: "creative_director",
        workflow_id: workflowId,
        target_node_id: response.target?.node_id ?? selectedPlanNode?.id,
        text: response.message || (generated ? "V2 generation started." : "V2 prompt updated."),
        created_at: new Date().toISOString(),
        metadata: {
          target: response.target,
          target_references,
          asset_locators,
          owner_display_name: owner_display_names[0] ?? null,
          owner_display_names,
          action_mode: response.action_mode,
          updated_prompt_scope: response.updated_prompt_scope,
          affected_slot_ids: response.affected_slot_ids,
          executed_slot_ids: response.executed_slot_ids,
          asset_ids: response.asset_ids,
          version_ids: response.version_ids,
          provider_calls: response.provider_calls,
          warnings: response.warnings,
          status: response.status,
          action_id: response.action_id,
        },
      });
      if (response.workflow) await applyWorkflowV2(response.workflow);
      if (response.events?.length) applyV2RuntimeEventsToPage(response.events);
      conversation.actions.setConversationMentionReferences([]);
      conversation.actions.setConversationNodeReferences([]);
      conversation.actions.setConversationTargetReferences([]);
      setStatus(generated ? "V2 generation started" : "V2 target updated");
    } catch (error) {
      const message = error instanceof Error ? error.message : "V2 chat action failed";
      conversation.actions.setConversationError(message);
      setStatus(message);
      appendConversationEventForConversation(conversationId, createClientConversationErrorEvent(conversationId, message));
    } finally {
      conversation.actions.setConversationSending(false);
    }
  }, [
    appendConversationEventForConversation,
    ensureLocalV2Conversation,
    resolveV2AssetLocatorsForChat,
    selectedV2ChatTargetForRequest,
  ]);

  const sendCopilotMessage = useCallback(async (prompt: string, context: PromptGenerateContext = { asset_references: [] }) => {
    const { workflow, conversation } = argsRef.current;
    if (workflow?.workflow_id) {
      if (argsRef.current.currentWorkflowIsV2()) {
        await sendV2ChatTargetMessage(prompt, context);
        return;
      }
      await sendAgentConversationMessage(prompt, context);
      return;
    }
    conversation.actions.setConversationSending(true);
    conversation.actions.setConversationError(null);
    try {
      await argsRef.current.askCopilot(prompt, context);
      conversation.actions.setConversationMentionReferences([]);
      conversation.actions.setConversationNodeReferences([]);
      conversation.actions.setConversationTargetReferences([]);
    } finally {
      conversation.actions.setConversationSending(false);
    }
  }, [sendAgentConversationMessage, sendV2ChatTargetMessage]);

  const applyConversationAction = useCallback(async (action: AgentConversationSuggestedAction) => {
    const { workflow, selectedPlanNode, conversation, setStatus, handleAgentConversationEvents, queueScopedWorkflowRefresh } = argsRef.current;
    conversation.actions.setActionBusyById((current) => ({ ...current, [action.action_id]: "apply" }));
    conversation.actions.setConversationError(null);
    try {
      const response = await api.applyAgentConversationAction(action.conversation_id, action.action_id);
      const events = conversationEventsFromActionResponse(response);
      appendConversationEventsForConversation(response.conversation_id, events);
      const requestWorkflowId = response.action.workflow_id ?? workflow?.workflow_id;
      if (requestWorkflowId) await handleAgentConversationEvents(events, requestWorkflowId);
      const wasApplied = events.some((event) => event.event_type === "action_applied" || event.event_type === "chat_action_applied");
      if (wasApplied) {
        if (requestWorkflowId) {
          const refreshNodeId = response.action.target_node_id ?? (!response.action.target_node_type ? selectedPlanNode?.id : null);
          queueScopedWorkflowRefresh(requestWorkflowId, {
            graph: true,
            mediaStatus: true,
            nodeIds: [refreshNodeId],
            resolvedInputNodeIds: [refreshNodeId],
          });
        }
        setStatus(`Applied action: ${response.action.title}`);
      } else {
        setStatus(`Action not applied: ${response.action.title}`);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Apply action failed";
      appendConversationEventForConversation(action.conversation_id, createClientConversationErrorEvent(action.conversation_id, message, action));
      conversation.actions.setConversationError(message);
      setStatus(message);
    } finally {
      conversation.actions.setActionBusyById((current) => ({ ...current, [action.action_id]: undefined }));
    }
  }, [appendConversationEventForConversation, appendConversationEventsForConversation]);

  const rejectConversationAction = useCallback(async (action: AgentConversationSuggestedAction) => {
    const { workflow, conversation, setStatus, handleAgentConversationEvents } = argsRef.current;
    conversation.actions.setActionBusyById((current) => ({ ...current, [action.action_id]: "reject" }));
    conversation.actions.setConversationError(null);
    try {
      const response = await api.rejectAgentConversationAction(action.conversation_id, action.action_id);
      const events = conversationEventsFromActionResponse(response);
      appendConversationEventsForConversation(response.conversation_id, events);
      const requestWorkflowId = response.action.workflow_id ?? workflow?.workflow_id;
      if (requestWorkflowId) await handleAgentConversationEvents(events, requestWorkflowId);
      setStatus(`Rejected action: ${response.action.title}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Reject action failed";
      appendConversationEventForConversation(action.conversation_id, createClientConversationErrorEvent(action.conversation_id, message, action));
      conversation.actions.setConversationError(message);
      setStatus(message);
    } finally {
      conversation.actions.setActionBusyById((current) => ({ ...current, [action.action_id]: undefined }));
    }
  }, [appendConversationEventForConversation, appendConversationEventsForConversation]);

  return {
    refs: {
      frontDeskBridgeRef,
    },
    actions: {
      loadAgentConversations,
      preserveFrontDeskBridgeConversation,
      bridgeFrontDeskMessagesToAgentConversation,
      createAgentConversation,
      ensureActiveAgentConversation,
      sendAgentConversationMessage,
      selectedV2ChatTarget,
      selectedV2ChatTargetForRequest,
      backendSafeV2ChatActionTarget,
      ensureLocalV2Conversation,
      resolveV2AssetLocatorsForChat,
      sendV2ChatTargetMessage,
      sendCopilotMessage,
      applyConversationAction,
      rejectConversationAction,
    },
  };
}
