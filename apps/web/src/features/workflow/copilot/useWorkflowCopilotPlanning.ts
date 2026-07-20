import { useCallback, useMemo } from "react";
import { v2Api } from "../../../api/v2Client.ts";
import type { PromptGenerateContext } from "../../../components/PromptComposer";
import type { AdRequest, AssetLibraryEntitySummary, AssetLibraryReference, FrontDeskMessage, UploadedAsset } from "../../../types";
import type { V2InputAssetUploadItem, WorkflowV2 } from "../../../types-v2.ts";
import { buildCopilotChatReferences, buildV2PlanFromChatRequest, buildV2PlanFromPromptRequest } from "./copilotRequestBuilders.ts";

type WorkflowMutationScope = {
  token: number;
  projectId: string | null;
  workflowId: string | null;
};

export type WorkflowCopilotPlanningActions = {
  askCopilot: (prompt: string, context?: PromptGenerateContext) => Promise<void>;
  uploadV2PromptInputAsset: (file: File) => Promise<V2InputAssetUploadItem[]>;
  v2PlanFromPromptRequest: () => ReturnType<typeof buildV2PlanFromPromptRequest>;
};

export function useWorkflowCopilotPlanning({
  messages,
  workflowPrompt,
  adRequest,
  promptLibraryEntities,
  selectedAssets,
  workflowPromptAssetReferences,
  beginWorkflowMutationScope,
  shouldApplyWorkflowMutationScope,
  setMessages,
  setStatus,
  syncFrontDeskAdRequest,
  applyWorkflowV2,
  bridgeFrontDeskMessagesToAgentConversation,
}: {
  messages: FrontDeskMessage[];
  workflowPrompt: string;
  adRequest: AdRequest;
  promptLibraryEntities: AssetLibraryEntitySummary[];
  selectedAssets: UploadedAsset[];
  workflowPromptAssetReferences: () => AssetLibraryReference[];
  beginWorkflowMutationScope: () => WorkflowMutationScope;
  shouldApplyWorkflowMutationScope: (scope: WorkflowMutationScope) => boolean;
  setMessages: (messages: FrontDeskMessage[]) => void;
  setStatus: (status: string) => void;
  syncFrontDeskAdRequest: (adRequest: AdRequest | null | undefined) => void;
  applyWorkflowV2: (workflow: WorkflowV2) => Promise<void>;
  bridgeFrontDeskMessagesToAgentConversation: (workflowId: string, messages: FrontDeskMessage[]) => Promise<void>;
}): {
  actions: WorkflowCopilotPlanningActions;
} {
  const uploadV2PromptInputAsset = useCallback(async (file: File): Promise<V2InputAssetUploadItem[]> => {
    const formData = new FormData();
    formData.append("files[]", file);
    formData.append("intent", "product_reference");
    const response = await v2Api.uploadInputAssets(formData);
    return response.assets;
  }, []);

  const v2PlanFromPromptRequest = useCallback(() => buildV2PlanFromPromptRequest({
    prompt: workflowPrompt.trim() || adRequestPrompt(adRequest),
    product_name: adRequest.product_name || null,
    duration_seconds: adRequest.duration_seconds ?? 30,
    aspect_ratio: adRequest.aspect_ratio ?? "16:9",
    selectedAssets,
    assetReferences: workflowPromptAssetReferences(),
    audioMode: adRequest.audio_mode ?? "bgm_only",
    libraryEntityIds: promptLibraryEntities.map((entity) => entity.entity_id),
    referenceMode: "strict",
  }), [adRequest, promptLibraryEntities, selectedAssets, workflowPrompt, workflowPromptAssetReferences]);

  const askCopilot = useCallback(async (prompt: string, context: PromptGenerateContext = { asset_references: [] }) => {
    const requestScope = beginWorkflowMutationScope();
    const nextMessages = [...messages, { role: "user" as const, content: prompt }];
    setMessages(nextMessages);
    setStatus("Planning workflow...");
    try {
      const response = await v2Api.planFromChat(buildV2PlanFromChatRequest({
        message: prompt,
        history: messages,
        inputAssets: v2PlanInputAssetLocators(context),
        selectedAssets,
        assetReferences: buildCopilotChatReferences({
          promptReferences: context.asset_references,
          workflowReferences: workflowPromptAssetReferences(),
        }),
        audioMode: adRequest.audio_mode ?? "bgm_only",
        libraryEntityIds: promptLibraryEntities.map((entity) => entity.entity_id),
        referenceMode: "strict",
      }));
      if (!shouldApplyWorkflowMutationScope(requestScope)) return;
      const plannedMessages: FrontDeskMessage[] = [...nextMessages, { role: "assistant", content: response.front_desk.reply }];
      setMessages(plannedMessages);
      syncFrontDeskAdRequest(response.front_desk.ad_request);
      if (response.workflow) {
        await applyWorkflowV2(response.workflow);
        await bridgeFrontDeskMessagesToAgentConversation(response.workflow.workflow_id, plannedMessages);
        setStatus(`Workflow ${response.workflow.workflow_id} planned`);
      } else {
        setStatus("Copilot needs more detail");
      }
    } catch (error) {
      if (!shouldApplyWorkflowMutationScope(requestScope)) return;
      setStatus(error instanceof Error ? error.message : "Workflow generation failed");
    }
  }, [
    adRequest.audio_mode,
    applyWorkflowV2,
    beginWorkflowMutationScope,
    bridgeFrontDeskMessagesToAgentConversation,
    messages,
    promptLibraryEntities,
    selectedAssets,
    setMessages,
    setStatus,
    shouldApplyWorkflowMutationScope,
    syncFrontDeskAdRequest,
    workflowPromptAssetReferences,
  ]);

  return useMemo(() => ({
    actions: {
      askCopilot,
      uploadV2PromptInputAsset,
      v2PlanFromPromptRequest,
    },
  }), [askCopilot, uploadV2PromptInputAsset, v2PlanFromPromptRequest]);
}

function v2PlanInputAssetLocators(context: PromptGenerateContext = { asset_references: [] }) {
  return uniqueStringList([...(context.input_asset_locators ?? []), ...(context.asset_locators ?? [])]);
}

function adRequestPrompt(request: AdRequest) {
  return [
    request.product_name,
    request.product_description,
    request.core_selling_point,
    request.target_audience ? `Target audience: ${request.target_audience}` : "",
    request.campaign_goal ? `Goal: ${request.campaign_goal}` : "",
    request.desired_emotion ? `Emotion: ${request.desired_emotion}` : "",
    request.visual_style ? `Style: ${request.visual_style}` : "",
    request.duration_seconds ? `Duration: ${request.duration_seconds}s` : "",
    request.aspect_ratio ? `Aspect ratio: ${request.aspect_ratio}` : "",
  ].filter(Boolean).join("\n");
}

function uniqueStringList(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.map((value) => value?.trim()).filter((value): value is string => Boolean(value))));
}
