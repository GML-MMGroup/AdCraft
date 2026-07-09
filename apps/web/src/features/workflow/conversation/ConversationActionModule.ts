import { useCallback, useMemo, useState } from "react";
import { api } from "../../../api/client.ts";
import { v2Api } from "../../../api/v2Client.ts";
import type { PromptGenerateContext } from "../../../components/PromptComposer.tsx";
import type {
  AgentConversation,
  AgentConversationEvent,
  AgentConversationSuggestedAction,
  FrontDeskMessage,
  WorkflowGraph,
} from "../../../types.ts";
import type {
  V2AssetLocatorResponse,
  V2ChatActionMode,
  V2ChatActionResponse,
  WorkflowV2,
  WorkflowV2ChatTarget,
} from "../../../types-v2.ts";
import { appendConversationEvents, conversationEventsFromActionResponse, conversationEventsFromResponse } from "../../../workflow/agentConversations.ts";
import { v2ChatActionMode } from "../../../workflow-v2/agentRouting.ts";
import { buildV2PlanFromChatRequest } from "../copilot/copilotRequestBuilders.ts";

export type ConversationActionModuleArgs = {
  workflow: WorkflowGraph | null;
  workflowV2: WorkflowV2 | null;
  workflowId: string | null;
  selectedNodeId: string | null;
  activeConversationId: string | null;
  messages: FrontDeskMessage[];
  conversations: AgentConversation[];
  onConversationCreated?: (conversation: AgentConversation) => void;
  onEvents?: (events: AgentConversationEvent[]) => void;
  onV2Workflow?: (workflow: WorkflowV2) => Promise<void> | void;
  onV1Workflow?: (workflow: WorkflowGraph) => Promise<void> | void;
  onError?: (message: string) => void;
};

export type ConversationActionModule = {
  conversationView: {
    activeConversationId: string | null;
    conversations: AgentConversation[];
    pending: boolean;
  };
  sendCopilotMessage: (prompt: string, context?: PromptGenerateContext) => Promise<void>;
  sendAgentConversationMessage: (prompt: string, context?: PromptGenerateContext) => Promise<void>;
  sendV2ChatTargetMessage: (prompt: string, target: WorkflowV2ChatTarget | null, context?: PromptGenerateContext, mode?: V2ChatActionMode) => Promise<V2ChatActionResponse | null>;
  resolveLocator: (locator: string) => Promise<V2AssetLocatorResponse | null>;
  applyConversationAction: (action: AgentConversationSuggestedAction) => Promise<void>;
  rejectConversationAction: (action: AgentConversationSuggestedAction, reason?: string) => Promise<void>;
};

async function ensureConversation(args: ConversationActionModuleArgs) {
  if (args.activeConversationId) return args.activeConversationId;
  if (!args.workflowId) return null;
  const conversation = await api.createAgentConversation({
    workflow_id: args.workflowId,
    focus_node_id: args.selectedNodeId,
    topic: args.selectedNodeId ? `Node ${args.selectedNodeId}` : "Workflow",
  });
  args.onConversationCreated?.(conversation);
  return conversation.conversation_id;
}

function v2ChatActionAttachmentsFromLocators(resolvedLocators: V2AssetLocatorResponse[]) {
  return resolvedLocators.map((locator) => ({
    source_asset_id: locator.asset.asset_id,
    semantic_type: locator.asset.semantic_type,
    use_as_prompt: true,
  }));
}

export function useConversationActionModule(args: ConversationActionModuleArgs): ConversationActionModule {
  const [pending, setPending] = useState(false);

  const conversationView = useMemo(() => ({
    activeConversationId: args.activeConversationId,
    conversations: args.conversations,
    pending,
  }), [args.activeConversationId, args.conversations, pending]);

  const sendCopilotMessage = useCallback(async (prompt: string, context: PromptGenerateContext = { asset_references: [] }) => {
    setPending(true);
    try {
      if (args.workflowV2) {
        const response = await v2Api.planFromChat(buildV2PlanFromChatRequest({
          message: prompt,
          history: args.messages,
          inputAssets: context.input_asset_locators ?? context.asset_locators ?? [],
        }));
        if (response.workflow) await args.onV2Workflow?.(response.workflow);
        return;
      }
      const response = await api.workflowPlanFromChat({
        message: prompt,
        history: args.messages,
        selected_assets: [],
        asset_references: context.asset_references ?? [],
      });
      if (response.workflow) await args.onV1Workflow?.(response.workflow);
    } catch (error) {
      args.onError?.(error instanceof Error ? error.message : "Copilot request failed");
    } finally {
      setPending(false);
    }
  }, [args]);

  const sendAgentConversationMessage = useCallback(async (prompt: string, context: PromptGenerateContext = { asset_references: [] }) => {
    if (!args.workflowId) {
      await sendCopilotMessage(prompt, context);
      return;
    }
    setPending(true);
    try {
      const conversationId = await ensureConversation(args);
      if (!conversationId) return;
      const response = await api.sendAgentConversationMessage(conversationId, {
        message: prompt,
        asset_references: context.asset_references ?? [],
        target_references: context.target_references ?? [],
        context: {
          workflow_id: args.workflowId,
          focus_node_id: args.selectedNodeId,
          selected_node_id: args.selectedNodeId,
        },
      });
      args.onEvents?.(conversationEventsFromResponse(response));
    } catch (error) {
      args.onError?.(error instanceof Error ? error.message : "Conversation request failed");
    } finally {
      setPending(false);
    }
  }, [args, sendCopilotMessage]);

  const sendV2ChatTargetMessage = useCallback(async (
    prompt: string,
    target: WorkflowV2ChatTarget | null,
    context: PromptGenerateContext = { asset_references: [] },
    actionMode: V2ChatActionMode = v2ChatActionMode(prompt),
  ) => {
    if (!args.workflowId) return null;
    setPending(true);
    try {
      const asset_locators = Array.from(new Set(context.asset_locators ?? []));
      const resolvedLocators = await Promise.all(asset_locators.map((locator) => v2Api.resolveLocator(args.workflowId ?? "", locator)));
      const target_references = [
        ...(target ? [target] : []),
        ...((context.target_references ?? []) as WorkflowV2ChatTarget[]),
      ];
      const response = await v2Api.chatAction(args.workflowId, {
        message: prompt,
        action_mode: actionMode,
        target,
        target_references,
        asset_locators,
        attachments: v2ChatActionAttachmentsFromLocators(resolvedLocators),
        conversation_id: args.activeConversationId,
        history: args.messages,
        context: {
          workflow_id: args.workflowId,
          selected_node_id: args.selectedNodeId,
          focus_node_id: args.selectedNodeId,
        },
      });
      if (response.workflow) await args.onV2Workflow?.(response.workflow);
      return response;
    } catch (error) {
      args.onError?.(error instanceof Error ? error.message : "V2 chat action failed");
      return null;
    } finally {
      setPending(false);
    }
  }, [args]);

  const resolveLocator = useCallback(async (locator: string) => {
    if (!args.workflowId || !locator.trim()) return null;
    return v2Api.resolveLocator(args.workflowId, locator.trim());
  }, [args.workflowId]);

  const applyConversationAction = useCallback(async (action: AgentConversationSuggestedAction) => {
    const response = await api.applyAgentConversationAction(action.conversation_id, action.action_id);
    args.onEvents?.(conversationEventsFromActionResponse(response));
  }, [args]);

  const rejectConversationAction = useCallback(async (action: AgentConversationSuggestedAction, reason?: string) => {
    const response = await api.rejectAgentConversationAction(action.conversation_id, action.action_id, reason);
    args.onEvents?.(appendConversationEvents([], conversationEventsFromActionResponse(response)));
  }, [args]);

  return {
    conversationView,
    sendCopilotMessage,
    sendAgentConversationMessage,
    sendV2ChatTargetMessage,
    resolveLocator,
    applyConversationAction,
    rejectConversationAction,
  };
}
