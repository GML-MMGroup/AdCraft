import type {
  AdRequest,
  AgentConversation,
  AgentConversationActionResponse,
  AgentConversationCreateRequest,
  AgentConversationEventsResponse,
  AgentConversationListResponse,
  AgentConversationMessageRequest,
  AssetReferenceSuggestParams,
  AssetReferenceSuggestResponse,
  AssetReferenceSuggestion,
  AssetUploadBatchResponse,
  AssetUploadGroupOptions,
  AssetUploadOptions,
  AssetLibraryCreatePayload,
  AssetLibraryEntitySummary,
  AssetLibraryListFilters,
  AssetLibraryPatchPayload,
  AssetLibraryReference,
  AssetReferenceMode,
  FinalCompositionTimelineResponse,
  FinalCompositionTimelineRenderRequest,
  FinalCompositionTimelineSaveRequest,
  FromChatResponse,
  FrontDeskMessage,
  FrontDeskResponse,
  GraphValidationResult,
  MarkStaleRequest,
  MarkStaleResponse,
  MediaPollRequest,
  MediaPollResponse,
  MediaStatus,
  NodeCatalogItem,
  NodeRunRequest,
  NodeRunResult,
  QualityReviewResponse,
  ResolvedNodeInputs,
  StoryboardShotVideoGenerationResponse,
  UploadedAsset,
  VideoEditingExportRequest,
  VideoEditingExportResult,
  WorkflowEdge,
  WorkflowEdgeDeleteResponse,
  WorkflowEdgeMutationResponse,
  WorkflowExecutionEventsResponse,
  WorkflowExecutionState,
  WorkflowAssetHistoryResponse,
  WorkflowGraph,
  WorkflowItemBatchUseCurrentVersionsRequest,
  WorkflowItemBatchUseCurrentVersionsResponse,
  WorkflowItemRegenerateRequest,
  WorkflowItemRegenerateResponse,
  WorkflowItemUseCurrentVersionRequest,
  WorkflowItemUseCurrentVersionResponse,
  WorkflowLockResponse,
  WorkflowNode,
  WorkflowNodeDeleteResponse,
  WorkflowNodeMutationResponse,
  WorkflowNodeVersionsResponse,
  WorkflowRunRequest,
  WorkflowRunResponse,
  WorkflowRevisionAcceptRequest,
  WorkflowRevisionListResponse,
  WorkflowRevisionRejectRequest,
  WorkflowRevisionRequest,
  WorkflowRevisionState,
  WorkflowSavePayload,
} from "../types";
import {
  backendGraphToLockResponse,
  backendGraphToNodeDeleteResponse,
  backendGraphToNodeMutation,
  backendGraphToStaleResponse,
  buildMediaUrl,
  normalizeAssetList,
  normalizeAssetLibraryDetail,
  normalizeAssetLibraryListResponse,
  normalizeAssetLibrarySummary,
  normalizeMediaStatus,
  normalizeNodeRunResult,
  normalizeQualityReviewResponse,
  normalizeResolvedNodeInputs,
  normalizeUploadedAsset,
  normalizeUploadedAssetBatch,
  normalizeWorkflowExecutionState,
  normalizeWorkflowGraph,
  normalizeWorkflowRunResponse,
} from "./workflowNormalizers";
import type { CanvasRuntimeEventsResponse, CanvasRuntimeSnapshot } from "../workflow/canvasRuntime.ts";
import { assertV1WorkflowId } from "./v1WorkflowGuard";

export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

const API_BASE_URL = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL ?? "/api/v1");
const API_DETAIL_ERROR_CODES = new Set([
  "identity_certification_required",
  "identity_certification_revoked",
  "reference_policy_failed",
  "provider_capability_missing",
  "provider_strategy_all_attempts_failed",
  "provider_strategy_no_eligible_provider",
  "provider_reference_type_unsupported",
  "strict_reference_not_supported",
  "identity_lock_not_supported",
  "product_reference_required",
  "product_reference_missing",
  "product_reference_provider_unsupported",
  "product_reference_dropped",
  "timeline_not_found",
  "timeline_version_conflict",
  "timeline_invalid_source",
  "timeline_missing_source_asset",
  "timeline_has_stale_enabled_clips",
  "timeline_no_enabled_video_clips",
  "timeline_render_failed",
  "final_video_candidate_create_failed",
  "ambiguous_node_type",
  "node_type_mismatch",
  "workflow_node_not_found",
  "node_id_required",
  "node_identity_resolution_failed",
  "legacy_node_type_ambiguous",
  "workflow_execution_already_running",
  "workflow_execution_not_found",
  "workflow_execution_invalid_state",
  "prompt_optimizer_failed",
  "prompt_optimizer_invalid_output",
  "prompt_optimizer_not_supported",
  "quality_review_failed",
  "quality_review_not_supported",
  "quality_review_no_assets",
  "quality_review_node_not_found",
  "quality_review_unavailable",
  "item_prompt_empty",
  "item_prompt_missing",
  "item_prompt_update_failed",
  "unsupported_chat_canvas_action",
  "target_item_not_found",
  "target_asset_not_found",
  "target_reference_ambiguous",
  "unsupported_target_action",
  "node_reference_not_found",
  "node_reference_ambiguous",
  "node_reference_hidden",
  "node_locked",
  "prompt_revision_failed",
  "node_prompt_missing",
  "execution_start_failed",
  "execution_already_running",
  "unsupported_target_scope",
  "item_revision_start_failed",
  "semantic_type_mismatch",
  "node_item_prompt_unsupported",
  "candidate_not_ready",
  "candidate_assets_missing",
  "candidate_accept_conflict",
  "candidate_reject_conflict",
  "candidate_quality_blocked",
  "candidate_target_mismatch",
  "asset_history_select_failed",
  "asset_reference_asset_not_found",
  "asset_reference_entity_not_found",
  "asset_reference_no_usable_assets",
]);
const API_DETAIL_ERROR_MESSAGES: Record<string, string> = {
  reference_policy_failed: "The selected reference assets do not satisfy the reference policy. Adjust or remove the references.",
  provider_capability_missing: "当前参考图类型不被模型严格参考能力支持，请更换参考类型或移除参考图。",
  provider_strategy_all_attempts_failed: "All provider attempts failed. Current active preview is unchanged when available.",
  provider_strategy_no_eligible_provider: "当前没有可用模型能满足这次严格参考要求，请更换参考类型或移除参考图。",
  provider_reference_type_unsupported: "当前参考图类型不被模型严格参考能力支持，请更换参考类型或移除参考图。",
  identity_certification_required: "The selected model cannot satisfy the requested identity consistency. Choose another model or remove the character reference.",
  identity_certification_revoked: "This model's identity consistency certification has been revoked. Choose another model or remove the character reference.",
  strict_reference_not_supported: "当前参考图类型不被模型严格参考能力支持，请更换参考类型或移除参考图。",
  identity_lock_not_supported: "The selected model cannot satisfy the requested identity consistency. Choose another model or remove the character reference.",
  product_reference_required: "A product reference image is required before generating product visuals.",
  product_reference_missing: "A product reference image is required. Upload or select a product reference and try again.",
  product_reference_provider_unsupported: "The selected provider cannot satisfy strict product reference generation. Current active preview is unchanged.",
  product_reference_dropped: "The backend reported that the product reference was dropped. Current active preview is unchanged.",
  timeline_not_found: "Final composition timeline was not found. Refresh the timeline and try again.",
  timeline_version_conflict: "Final composition timeline was updated elsewhere. Review the refreshed timeline before saving again.",
  timeline_invalid_source: "Final composition timeline contains an invalid source. Current active final video is unchanged.",
  timeline_missing_source_asset: "Final composition timeline has a missing source asset. Current active final video is unchanged.",
  timeline_has_stale_enabled_clips: "Final composition timeline has stale enabled clips. Current active final video is unchanged.",
  timeline_no_enabled_video_clips: "Enable at least one video clip before rendering the final video.",
  timeline_render_failed: "Final composition render failed. Current active final video is unchanged.",
  final_video_candidate_create_failed: "Final video candidate could not be created. Current active final video is unchanged.",
  prompt_optimizer_failed: "Prompt optimization failed. Keep editing your prompt or try again.",
  prompt_optimizer_invalid_output: "Prompt optimizer returned invalid output.",
  prompt_optimizer_not_supported: "Prompt optimization is not supported for this node.",
  quality_review_failed: "Quality review failed. Existing previews and quality results are unchanged.",
  quality_review_not_supported: "Quality review is not supported for this node.",
  quality_review_no_assets: "No generated assets are available for quality review.",
  quality_review_node_not_found: "Quality review target node was not found.",
  quality_review_unavailable: "Quality review is currently unavailable.",
  item_prompt_empty: "Item prompt cannot be empty.",
  item_prompt_missing: "Item prompt is missing.",
  item_prompt_update_failed: "Item prompt update failed.",
  unsupported_chat_canvas_action: "This chat action is not supported for the current canvas target.",
  target_item_not_found: "The selected item no longer exists or was refreshed.",
  target_asset_not_found: "The selected asset no longer exists or was archived.",
  target_reference_ambiguous: "Choose a more specific node, item, or asset from the @ menu.",
  unsupported_target_action: "This target action is not available yet.",
  node_reference_not_found: "The mentioned node no longer exists.",
  node_reference_ambiguous: "Choose a specific node from the @ menu.",
  node_reference_hidden: "This node cannot be edited directly from chat.",
  node_locked: "This node is locked and cannot be edited right now.",
  prompt_revision_failed: "Prompt revision failed. The old prompt was kept.",
  node_prompt_missing: "The target node has no editable prompt.",
  execution_start_failed: "Prompt updated, but execution could not be started.",
  execution_already_running: "This workflow already has a running task.",
  unsupported_target_scope: "This target does not support the requested scope.",
  item_revision_start_failed: "Item regeneration could not be started.",
  semantic_type_mismatch: "The selected item does not match the requested media type.",
  node_item_prompt_unsupported: "This node does not support item-level prompt editing.",
  candidate_not_ready: "Candidate is not ready yet. Current active preview is unchanged.",
  candidate_assets_missing: "Candidate assets are missing. Current active preview is unchanged.",
  candidate_accept_conflict: "Candidate accept conflict. Please refresh candidates and history.",
  candidate_reject_conflict: "Candidate reject conflict. Please refresh candidates and history.",
  candidate_quality_blocked: "Candidate is blocked by quality review. Confirm override or choose another version.",
  candidate_target_mismatch: "Candidate target mismatch. Refresh this item before trying again.",
  asset_history_select_failed: "Historical asset selection failed. Current active preview is unchanged.",
  asset_reference_asset_not_found: "参考图片引用失效，请重新选择或上传图片。",
  asset_reference_entity_not_found: "参考图片引用失效，请重新选择或上传图片。",
  asset_reference_no_usable_assets: "参考图片引用失效，请重新选择或上传图片。",
};

export function mediaUrl(path?: string | null) {
  return buildMediaUrl(path, API_BASE_URL);
}

type WorkflowChatOptions = {
  message: string;
  history: FrontDeskMessage[];
  selected_assets: UploadedAsset[];
  audio_mode?: "none" | "bgm_only" | "full";
  library_entity_ids?: string[];
  asset_references?: AssetLibraryReference[];
  reference_mode?: AssetReferenceMode;
};

async function parseResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const detail = payload?.detail;
    const detailObjectMessage = formatDetailObjectMessage(detail);
    const detailMessage = Array.isArray(detail)
      ? detail
          .map((item) => {
            if (!item || typeof item !== "object") return String(item);
            const record = item as Record<string, unknown>;
            const loc = Array.isArray(record.loc) ? record.loc.join(".") : "";
            return `${loc ? `${loc}: ` : ""}${String(record.msg ?? JSON.stringify(record))}`;
          })
          .join("; ")
      : undefined;
    const detailString = typeof payload?.detail === "string" ? payload.detail : "";
    const message =
      detailString
        ? API_DETAIL_ERROR_MESSAGES[detailString] ?? detailString
        : detailObjectMessage
          ? detailObjectMessage
        : detailMessage
          ? detailMessage
        : `Request failed with status ${response.status}`;
    console.error("[API Error]", {
      url: response.url,
      status: response.status,
      message,
      payload,
    });
    throw new ApiError(message, response.status, payload);
  }

  return payload as T;
}

function formatDetailObjectMessage(detail: unknown) {
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return "";
  const detailRecord = detail as Record<string, unknown>;
  const message = typeof detailRecord.message === "string" && detailRecord.message.trim()
    ? detailRecord.message.trim()
    : typeof detailRecord.msg === "string" && detailRecord.msg.trim()
      ? detailRecord.msg.trim()
      : "";
  const code = typeof detailRecord.code === "string" && detailRecord.code.trim() ? detailRecord.code.trim() : "";
  const phase8Code = code && API_DETAIL_ERROR_CODES.has(code) ? code : "";
  const displayCode = phase8Code || code;
  const fallbackMessage = code ? API_DETAIL_ERROR_MESSAGES[code] : "";
  if (message && displayCode) return `${displayCode}: ${message}`;
  if (fallbackMessage && displayCode) return `${displayCode}: ${fallbackMessage}`;
  if (fallbackMessage) return fallbackMessage;
  return message || displayCode || JSON.stringify(detailRecord);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(joinUrl(API_BASE_URL, path), {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });

  return parseResponse<T>(response);
}

async function optionalRequest<T>(path: string, init?: RequestInit): Promise<T | null> {
  const response = await fetch(joinUrl(API_BASE_URL, path), {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });

  if (response.status === 404) return null;
  return parseResponse<T>(response);
}

export const api = {
  baseUrl: API_BASE_URL,

  health() {
    return request<{ status: string; service: string; version: string; mode: string }>("/health");
  },

  listAssets() {
    return request<{ assets?: unknown[] }>("/assets").then((response) => ({
      ...response,
      assets: normalizeAssetList(response.assets) ?? [],
    }));
  },

  uploadAsset(file: File, options: AssetUploadOptions = {}) {
    const form = new FormData();
    form.append("file", file);
    appendAssetUploadOptions(form, options);

    return request<UploadedAsset>("/assets/upload", {
      method: "POST",
      body: form,
    }).then((asset) => normalizeUploadedAsset(asset) ?? asset);
  },

  uploadAssetGroup(files: File[], options: AssetUploadGroupOptions) {
    const form = new FormData();
    files.forEach((file) => {
      form.append("files[]", file);
    });
    appendAssetUploadOptions(form, options);
    form.append("group_as_entity", "true");
    if (options.assets_metadata?.length) {
      form.append("assets_metadata", JSON.stringify(options.assets_metadata));
    }
    if (options.description) {
      form.append("description", options.description);
    }

    return request<AssetUploadBatchResponse>("/assets/upload", {
      method: "POST",
      body: form,
    }).then((response) => normalizeUploadedAssetBatch(response) ?? response);
  },

  listAssetLibraryEntities(filters: AssetLibraryListFilters = {}) {
    const params = new URLSearchParams();
    if (filters.entity_type && filters.entity_type !== "all") params.set("entity_type", filters.entity_type);
    if (filters.semantic_type) params.set("semantic_type", filters.semantic_type);
    if (filters.tag) params.set("tag", filters.tag);
    if (filters.q) params.set("q", filters.q);
    if (filters.source_workflow_id) params.set("source_workflow_id", filters.source_workflow_id);
    if (filters.include_archived) params.set("include_archived", "true");
    const query = params.toString();
    return request<unknown>(`/asset-library/entities${query ? `?${query}` : ""}`).then(normalizeAssetLibraryListResponse);
  },

  assetLibraryEntity(entityId: string) {
    return request<unknown>(`/asset-library/entities/${encodeURIComponent(entityId)}`).then(normalizeAssetLibraryDetail);
  },

  createAssetLibraryEntity(body: AssetLibraryCreatePayload) {
    return request<unknown>("/asset-library/entities", {
      method: "POST",
      body: JSON.stringify(body),
    }).then(normalizeAssetLibraryDetail);
  },

  patchAssetLibraryEntity(entityId: string, body: AssetLibraryPatchPayload) {
    return request<unknown>(`/asset-library/entities/${encodeURIComponent(entityId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }).then(normalizeAssetLibraryDetail);
  },

  suggestAssetReferences(params: AssetReferenceSuggestParams = {}) {
    const query = assetReferenceSuggestParams(params);
    return request<AssetReferenceSuggestResponse>(`/asset-references/suggest${query ? `?${query}` : ""}`).then(normalizeAssetReferenceSuggestResponse);
  },

  listAgentConversations(params: { workflow_id?: string | null; focus_node_id?: string | null; status?: string | null } = {}) {
    const query = agentConversationListParams(params);
    return request<AgentConversationListResponse>(`/agent-conversations${query ? `?${query}` : ""}`);
  },

  createAgentConversation(body: AgentConversationCreateRequest) {
    return request<AgentConversation>("/agent-conversations", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  agentConversation(conversationId: string) {
    return request<AgentConversation>(`/agent-conversations/${encodeURIComponent(conversationId)}`);
  },

  sendAgentConversationMessage(conversationId: string, body: AgentConversationMessageRequest) {
    return request<AgentConversationEventsResponse>(`/agent-conversations/${encodeURIComponent(conversationId)}/messages`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  applyAgentConversationAction(conversationId: string, actionId: string) {
    return request<AgentConversationActionResponse>(
      `/agent-conversations/${encodeURIComponent(conversationId)}/actions/${encodeURIComponent(actionId)}/apply`,
      {
        method: "POST",
        body: JSON.stringify({}),
      },
    );
  },

  rejectAgentConversationAction(conversationId: string, actionId: string, reason?: string) {
    return request<AgentConversationActionResponse>(
      `/agent-conversations/${encodeURIComponent(conversationId)}/actions/${encodeURIComponent(actionId)}/reject`,
      {
        method: "POST",
        body: JSON.stringify(reason ? { reason } : {}),
      },
    );
  },

  chat(message: string, history: FrontDeskMessage[], selected_assets: UploadedAsset[], asset_references: AssetLibraryReference[] = []) {
    return request<FrontDeskResponse>("/front-desk/chat", {
      method: "POST",
      body: JSON.stringify({
        message,
        history,
        skip_audio_agents: true,
        selected_assets,
        asset_references,
      }),
    });
  },

  generateWorkflow(adRequest: AdRequest) {
    return request<WorkflowGraph>("/ad-workflows/generate", {
      method: "POST",
      body: JSON.stringify(adRequest),
    }).then(normalizeWorkflowGraph);
  },

  planWorkflow(adRequest: AdRequest) {
    return request<WorkflowGraph>("/ad-workflows/plan", {
      method: "POST",
      body: JSON.stringify(adRequest),
    }).then(normalizeWorkflowGraph);
  },

  workflowFromChat(options: WorkflowChatOptions) {
    return request<FromChatResponse>("/ad-workflows/from-chat", {
      method: "POST",
      body: JSON.stringify({
        message: options.message,
        history: options.history,
        skip_audio_agents: true,
        selected_assets: options.selected_assets,
        library_entity_ids: options.library_entity_ids,
        asset_references: options.asset_references,
        reference_mode: options.reference_mode,
      }),
    }).then((response) => ({ ...response, workflow: response.workflow ? normalizeWorkflowGraph(response.workflow) : null }));
  },

  workflowPlanFromChat(options: WorkflowChatOptions) {
    return request<FromChatResponse>("/ad-workflows/plan-from-chat", {
      method: "POST",
      body: JSON.stringify({
        message: options.message,
        history: options.history,
        audio_mode: options.audio_mode ?? "bgm_only",
        selected_assets: options.selected_assets,
        library_entity_ids: options.library_entity_ids,
        asset_references: options.asset_references,
        reference_mode: options.reference_mode,
      }),
    }).then((response) => ({ ...response, workflow: response.workflow ? normalizeWorkflowGraph(response.workflow) : null }));
  },

  nodeCatalog() {
    return request<{ nodes: NodeCatalogItem[] }>("/workflow-nodes/catalog");
  },

  runNode(body: NodeRunRequest) {
    if (body.workflow_id) assertV1WorkflowId(body.workflow_id, "runNode");
    return request<NodeRunResult>("/workflow-nodes/run", {
      method: "POST",
      body: JSON.stringify(body),
    }).then(normalizeNodeRunResult);
  },

  workflowNodes(workflowId: string) {
    assertV1WorkflowId(workflowId, "workflowNodes");
    return request<{ workflow_id: string; nodes?: NodeRunResult[] }>(`/workflows/${workflowId}/nodes`).then((response) => ({
      ...response,
      nodes: (response.nodes ?? []).map(normalizeNodeRunResult),
    }));
  },

  workflowNode(workflowId: string, nodeId: string) {
    assertV1WorkflowId(workflowId, "workflowNode");
    return request<NodeRunResult>(`/workflows/${workflowId}/nodes/${nodeId}`).then(normalizeNodeRunResult);
  },

  updateNodeItemPrompt(
    workflowId: string,
    nodeId: string,
    itemId: string,
    payload: { prompt: string; semantic_type?: string | null; mark_stale?: boolean },
  ) {
    assertV1WorkflowId(workflowId, "updateNodeItemPrompt");
    return request<unknown>(
      `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}/items/${encodeURIComponent(itemId)}/prompt`,
      {
        method: "PATCH",
        body: JSON.stringify(payload),
      },
    );
  },

  regenerateNodeItem(workflowId: string, nodeId: string, itemId: string, payload: WorkflowItemRegenerateRequest): Promise<WorkflowItemRegenerateResponse> {
    assertV1WorkflowId(workflowId, "regenerateNodeItem");
    return request<WorkflowItemRegenerateResponse>(
      `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}/items/${encodeURIComponent(itemId)}/regenerate`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
  },

  useCurrentItemVersion(workflowId: string, nodeId: string, itemId: string, payload: WorkflowItemUseCurrentVersionRequest = {}): Promise<WorkflowItemUseCurrentVersionResponse> {
    assertV1WorkflowId(workflowId, "useCurrentItemVersion");
    return request<WorkflowItemUseCurrentVersionResponse>(
      `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}/items/${encodeURIComponent(itemId)}/use-current-version`,
      {
        method: "POST",
        body: JSON.stringify({
          force_use_current_version: false,
          use_for_composition: false,
          ...payload,
        }),
      },
    );
  },

  batchUseCurrentItemVersions(workflowId: string, nodeId: string, payload: WorkflowItemBatchUseCurrentVersionsRequest): Promise<WorkflowItemBatchUseCurrentVersionsResponse> {
    assertV1WorkflowId(workflowId, "batchUseCurrentItemVersions");
    return request<WorkflowItemBatchUseCurrentVersionsResponse>(
      `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}/items/batch-use-current-versions`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
  },

  generateStoryboardShotVideo(workflowId: string, shotId: string, payload: Record<string, unknown> = {}): Promise<StoryboardShotVideoGenerationResponse> {
    assertV1WorkflowId(workflowId, "generateStoryboardShotVideo");
    return request<StoryboardShotVideoGenerationResponse>(
      `/workflows/${encodeURIComponent(workflowId)}/storyboard/shots/${encodeURIComponent(shotId)}/videos/generate`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
  },

  generateMissingStaleStoryboardVideos(workflowId: string, payload: Record<string, unknown> = {}): Promise<StoryboardShotVideoGenerationResponse> {
    assertV1WorkflowId(workflowId, "generateMissingStaleStoryboardVideos");
    return request<StoryboardShotVideoGenerationResponse>(
      `/workflows/${encodeURIComponent(workflowId)}/storyboard/videos/generate-missing-stale`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
  },

  regenerateAllSelectedStoryboardVideos(workflowId: string, payload: Record<string, unknown> = {}): Promise<StoryboardShotVideoGenerationResponse> {
    assertV1WorkflowId(workflowId, "regenerateAllSelectedStoryboardVideos");
    return request<StoryboardShotVideoGenerationResponse>(
      `/workflows/${encodeURIComponent(workflowId)}/storyboard/videos/regenerate-all-selected`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
  },

  useCurrentStoryboardVideosForComposition(workflowId: string, payload: { shot_ids?: string[]; scope: string }): Promise<StoryboardShotVideoGenerationResponse> {
    assertV1WorkflowId(workflowId, "useCurrentStoryboardVideosForComposition");
    return request<StoryboardShotVideoGenerationResponse>(
      `/workflows/${encodeURIComponent(workflowId)}/storyboard/videos/use-current-for-composition`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
  },

  reviewNodeQuality(workflowId: string, nodeId: string): Promise<QualityReviewResponse> {
    assertV1WorkflowId(workflowId, "reviewNodeQuality");
    return request<unknown>(
      `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}/quality-review`,
      {
        method: "POST",
        body: JSON.stringify({}),
      },
    ).then(normalizeQualityReviewResponse);
  },

  resolvedNodeInputs(workflowId: string, nodeId: string) {
    assertV1WorkflowId(workflowId, "resolvedNodeInputs");
    return optionalRequest<unknown>(`/workflows/${workflowId}/nodes/${nodeId}/resolved-inputs`).then((value) => (value ? normalizeResolvedNodeInputs(value) : null));
  },

  createNodeRevision(workflowId: string, nodeId: string, payload: WorkflowRevisionRequest) {
    assertV1WorkflowId(workflowId, "createNodeRevision");
    return request<unknown>(`/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}/revisions`, {
      method: "POST",
      body: JSON.stringify(payload),
    }).then(normalizeWorkflowRevisionState);
  },

  getNodeRevision(workflowId: string, nodeId: string, revisionId: string) {
    assertV1WorkflowId(workflowId, "getNodeRevision");
    return request<unknown>(
      `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}/revisions/${encodeURIComponent(revisionId)}`,
    ).then(normalizeWorkflowRevisionState);
  },

  listNodeRevisions(workflowId: string, nodeId: string): Promise<WorkflowRevisionListResponse> {
    assertV1WorkflowId(workflowId, "listNodeRevisions");
    return request<unknown>(`/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}/revisions`).then((value) => ({
      revisions: normalizeWorkflowRevisionList(value),
    }));
  },

  acceptNodeRevision(workflowId: string, nodeId: string, revisionId: string, payload: WorkflowRevisionAcceptRequest = {}) {
    assertV1WorkflowId(workflowId, "acceptNodeRevision");
    return request<unknown>(
      `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}/revisions/${encodeURIComponent(revisionId)}/accept`,
      {
        method: "POST",
        body: JSON.stringify({ note: "", override_quality_failure: false, ...payload }),
      },
    ).then(normalizeWorkflowRevisionState);
  },

  rejectNodeRevision(workflowId: string, nodeId: string, revisionId: string, payload: WorkflowRevisionRejectRequest = {}) {
    assertV1WorkflowId(workflowId, "rejectNodeRevision");
    return request<unknown>(
      `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}/revisions/${encodeURIComponent(revisionId)}/reject`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ).then(normalizeWorkflowRevisionState);
  },

  getNodeAssetHistory(workflowId: string, nodeId: string, filters: { entity_id?: string | null; semantic_type?: string | null }) {
    assertV1WorkflowId(workflowId, "getNodeAssetHistory");
    const search = new URLSearchParams();
    if (filters.entity_id) search.set("entity_id", filters.entity_id);
    if (filters.semantic_type) search.set("semantic_type", filters.semantic_type);
    const query = search.toString();
    return request<unknown>(
      `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}/assets/history${query ? `?${query}` : ""}`,
    ).then(normalizeWorkflowAssetHistoryResponse);
  },

  getFinalCompositionTimeline(workflowId: string): Promise<FinalCompositionTimelineResponse> {
    assertV1WorkflowId(workflowId, "getFinalCompositionTimeline");
    return request<FinalCompositionTimelineResponse>(
      `/workflows/${encodeURIComponent(workflowId)}/final-composition/timeline`,
    );
  },

  saveFinalCompositionTimeline(workflowId: string, payload: FinalCompositionTimelineSaveRequest): Promise<FinalCompositionTimelineResponse> {
    assertV1WorkflowId(workflowId, "saveFinalCompositionTimeline");
    return request<FinalCompositionTimelineResponse>(
      `/workflows/${encodeURIComponent(workflowId)}/final-composition/timeline`,
      {
        method: "PUT",
        body: JSON.stringify(payload),
      },
    );
  },

  renderFinalCompositionTimeline(workflowId: string, payload: FinalCompositionTimelineRenderRequest) {
    assertV1WorkflowId(workflowId, "renderFinalCompositionTimeline");
    const renderPayload = { ...payload, acceptance_policy: "manual_candidate" as const };
    return request<unknown>(
      `/workflows/${encodeURIComponent(workflowId)}/final-composition/render`,
      {
        method: "POST",
        body: JSON.stringify(renderPayload),
      },
    ).then(normalizeWorkflowRevisionState);
  },

  getWorkflow(workflowId: string) {
    assertV1WorkflowId(workflowId, "getWorkflow");
    return request<WorkflowGraph>(`/workflows/${workflowId}`).then(normalizeWorkflowGraph);
  },

  validateWorkflow(workflowId: string) {
    assertV1WorkflowId(workflowId, "validateWorkflow");
    return request<GraphValidationResult>(`/workflows/${workflowId}/validate`, {
      method: "POST",
      body: JSON.stringify({}),
    });
  },

  runWorkflow(workflowId: string, body: WorkflowRunRequest = {}) {
    assertV1WorkflowId(workflowId, "runWorkflow");
    return request<unknown>(`/workflows/${workflowId}/run`, {
      method: "POST",
      body: JSON.stringify(body),
    }).then(normalizeWorkflowRunResponse);
  },

  workflowExecution(workflowId: string, executionId: string): Promise<WorkflowExecutionState | null> {
    assertV1WorkflowId(workflowId, "workflowExecution");
    return optionalRequest<unknown>(
      `/workflows/${encodeURIComponent(workflowId)}/executions/${encodeURIComponent(executionId)}`,
    ).then((value) => (value ? normalizeWorkflowExecutionState(value) : null));
  },

  workflowExecutionEvents(workflowId: string, executionId: string, afterSeq = 0): Promise<WorkflowExecutionEventsResponse | null> {
    assertV1WorkflowId(workflowId, "workflowExecutionEvents");
    const search = new URLSearchParams();
    search.set("after_seq", String(afterSeq));
    return optionalRequest<WorkflowExecutionEventsResponse>(
      `/workflows/${encodeURIComponent(workflowId)}/executions/${encodeURIComponent(executionId)}/events?${search.toString()}`,
    );
  },

  async canvasRuntime(workflowId: string): Promise<CanvasRuntimeSnapshot | null> {
    assertV1WorkflowId(workflowId, "canvasRuntime");
    const value = await optionalRequest<unknown>(
      `/workflows/${encodeURIComponent(workflowId)}/canvas/runtime`,
    );
    if (!value) return null;
    const { normalizeCanvasRuntimeSnapshot } = await import("../workflow/canvasRuntime.ts");
    return normalizeCanvasRuntimeSnapshot(value);
  },

  async canvasEvents(workflowId: string, afterSeq = 0): Promise<CanvasRuntimeEventsResponse | null> {
    assertV1WorkflowId(workflowId, "canvasEvents");
    const search = new URLSearchParams();
    search.set("after_seq", String(afterSeq));
    const value = await optionalRequest<unknown>(
      `/workflows/${encodeURIComponent(workflowId)}/canvas/events?${search.toString()}`,
    );
    if (!value) return null;
    const { normalizeCanvasRuntimeEventsResponse } = await import("../workflow/canvasRuntime.ts");
    return normalizeCanvasRuntimeEventsResponse(value);
  },

  openCanvasEventStream(workflowId: string, afterSeq = 0) {
    assertV1WorkflowId(workflowId, "openCanvasEventStream");
    const search = new URLSearchParams();
    search.set("after_seq", String(afterSeq));
    return new EventSource(joinUrl(API_BASE_URL, `/workflows/${encodeURIComponent(workflowId)}/canvas/events/stream?${search.toString()}`));
  },

  saveWorkflow(workflowId: string, body: WorkflowSavePayload) {
    assertV1WorkflowId(workflowId, "saveWorkflow");
    return request<WorkflowGraph>(`/workflows/${workflowId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }).then(normalizeWorkflowGraph);
  },

  createWorkflowNode(workflowId: string, body: Partial<WorkflowNode>) {
    assertV1WorkflowId(workflowId, "createWorkflowNode");
    return request<unknown>(`/workflows/${workflowId}/nodes`, {
      method: "POST",
      body: JSON.stringify(body),
    }).then((value) => backendGraphToNodeMutation(value, String(body.id ?? body.node_type ?? "")));
  },

  updateWorkflowNode(workflowId: string, nodeId: string, body: Partial<WorkflowNode>) {
    assertV1WorkflowId(workflowId, "updateWorkflowNode");
    return request<unknown>(`/workflows/${workflowId}/nodes/${nodeId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }).then((value) => backendGraphToNodeMutation(value, nodeId));
  },

  deleteWorkflowNode(workflowId: string, nodeId: string) {
    assertV1WorkflowId(workflowId, "deleteWorkflowNode");
    return request<unknown>(`/workflows/${workflowId}/nodes/${nodeId}`, {
      method: "DELETE",
    }).then((value) => backendGraphToNodeDeleteResponse(value, nodeId));
  },

  createWorkflowEdge(workflowId: string, body: Partial<WorkflowEdge>) {
    assertV1WorkflowId(workflowId, "createWorkflowEdge");
    return request<WorkflowEdgeMutationResponse>(`/workflows/${workflowId}/edges`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  updateWorkflowEdge(workflowId: string, edgeId: string, body: Partial<WorkflowEdge>) {
    assertV1WorkflowId(workflowId, "updateWorkflowEdge");
    return request<WorkflowEdgeMutationResponse>(`/workflows/${workflowId}/edges/${edgeId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  },

  deleteWorkflowEdge(workflowId: string, edgeId: string) {
    assertV1WorkflowId(workflowId, "deleteWorkflowEdge");
    return request<WorkflowEdgeDeleteResponse>(`/workflows/${workflowId}/edges/${edgeId}`, {
      method: "DELETE",
    });
  },

  workflowNodeVersions(workflowId: string, nodeId: string) {
    assertV1WorkflowId(workflowId, "workflowNodeVersions");
    return request<WorkflowNodeVersionsResponse>(`/workflows/${workflowId}/nodes/${nodeId}/versions`);
  },

  lockWorkflowNode(workflowId: string, nodeId: string) {
    assertV1WorkflowId(workflowId, "lockWorkflowNode");
    return request<unknown>(`/workflows/${workflowId}/nodes/${nodeId}/lock`, {
      method: "POST",
      body: JSON.stringify({}),
    }).then((value) => backendGraphToLockResponse(value, nodeId));
  },

  unlockWorkflowNode(workflowId: string, nodeId: string) {
    assertV1WorkflowId(workflowId, "unlockWorkflowNode");
    return request<unknown>(`/workflows/${workflowId}/nodes/${nodeId}/unlock`, {
      method: "POST",
      body: JSON.stringify({}),
    }).then((value) => backendGraphToLockResponse(value, nodeId));
  },

  markStale(workflowId: string, body: MarkStaleRequest) {
    assertV1WorkflowId(workflowId, "markStale");
    return request<unknown>(`/workflows/${workflowId}/mark-stale`, {
      method: "POST",
      body: JSON.stringify(body),
    }).then(backendGraphToStaleResponse);
  },

  mediaStatus(workflowId: string) {
    assertV1WorkflowId(workflowId, "mediaStatus");
    return request<unknown>(`/ad-workflows/${workflowId}/media-status`).then(normalizeMediaStatus);
  },

  pollMedia(workflowId: string, body: MediaPollRequest) {
    assertV1WorkflowId(workflowId, "pollMedia");
    return request<unknown>(`/ad-workflows/${workflowId}/media/poll`, {
      method: "POST",
      body: JSON.stringify(body),
    }).then((response) => normalizeMediaStatus(response) as MediaPollResponse);
  },

  exportVideo(body: VideoEditingExportRequest) {
    return request<VideoEditingExportResult>("/video-editing/export", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  videoExport(exportId: string) {
    return request<VideoEditingExportResult>(`/video-editing/exports/${exportId}`);
  },
};

function assetReferenceSuggestParams(params: AssetReferenceSuggestParams) {
  const search = new URLSearchParams();
  if (params.q) search.set("q", params.q);
  if (params.types) search.set("types", Array.isArray(params.types) ? params.types.join(",") : params.types);
  if (params.workflow_id) search.set("workflow_id", params.workflow_id);
  if (params.node_id) search.set("node_id", params.node_id);
  if (params.include_canvas_assets !== undefined) search.set("include_canvas_assets", String(params.include_canvas_assets));
  if (params.include_library_assets !== undefined) search.set("include_library_assets", String(params.include_library_assets));
  if (params.limit !== undefined) search.set("limit", String(params.limit));
  return search.toString();
}

function agentConversationListParams(params: { workflow_id?: string | null; focus_node_id?: string | null; status?: string | null }) {
  const search = new URLSearchParams();
  if (params.workflow_id) search.set("workflow_id", params.workflow_id);
  if (params.focus_node_id) search.set("focus_node_id", params.focus_node_id);
  if (params.status) search.set("status", params.status);
  return search.toString();
}

function normalizeAssetReferenceSuggestResponse(value: unknown): AssetReferenceSuggestResponse {
  if (!value || typeof value !== "object") return { suggestions: [] };
  const record = value as Record<string, unknown>;
  const rawSuggestions = Array.isArray(record.suggestions)
    ? record.suggestions
    : Array.isArray(record.items)
      ? record.items
      : Array.isArray(record.results)
        ? record.results
        : [];
  return {
    suggestions: rawSuggestions.map(normalizeAssetReferenceSuggestion).filter(Boolean) as AssetReferenceSuggestion[],
  };
}

function normalizeAssetReferenceSuggestion(value: unknown): AssetReferenceSuggestion | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const source = record.reference_source === "canvas_asset" ? "canvas_asset" : "asset_library";
  const entityId = firstString(record.entity_id, record.library_entity_id);
  const assetId = firstString(record.asset_id, record.library_asset_id, record.id);
  const displayName = firstString(record.display_name, record.name, record.title, record.filename) ?? entityId ?? assetId;
  if (!displayName) return null;
  const tags = Array.isArray(record.tags) ? record.tags.filter((item): item is string => typeof item === "string") : [];
  const warnings = Array.isArray(record.warnings) ? record.warnings.filter((item): item is string => typeof item === "string") : [];
  return {
    reference_source: source,
    display_name: displayName,
    entity_id: entityId ?? null,
    asset_id: assetId ?? null,
    library_entity_id: firstString(record.library_entity_id) ?? null,
    library_asset_id: firstString(record.library_asset_id) ?? null,
    library_state: firstString(record.library_state) ?? undefined,
    library_error: firstString(record.library_error, record.library_ingest_error) ?? null,
    source_type: firstString(record.source_type) ?? undefined,
    entity_type: firstString(record.entity_type, record.type, record.category) ?? null,
    semantic_type: firstString(record.semantic_type) ?? null,
    asset_type: firstString(record.asset_type, record.media_type) ?? null,
    role: firstString(record.role) ?? null,
    mention_text: firstString(record.mention_text) ?? null,
    tags,
    preview_url: firstString(record.preview_url, record.public_url, record.url) ?? null,
    thumbnail_url: firstString(record.thumbnail_url) ?? null,
    thumbnail_path: firstString(record.thumbnail_path) ?? null,
    local_path: firstString(record.local_path, record.path) ?? null,
    warning: firstString(record.warning) ?? null,
    warnings,
    asset: record.asset && typeof record.asset === "object" ? normalizeUploadedAsset(record.asset) : null,
    library_entity: record.library_entity && typeof record.library_entity === "object" ? normalizeAssetLibrarySummary(record.library_entity as AssetLibraryEntitySummary) : null,
  };
}

function normalizeWorkflowRevisionList(value: unknown): WorkflowRevisionState[] {
  let raw: unknown[] = [];
  if (Array.isArray(value)) {
    raw = value;
  } else if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (Array.isArray(record.revisions)) raw = record.revisions;
    else if (Array.isArray(record.items)) raw = record.items;
  }
  return raw.map(normalizeWorkflowRevisionState);
}

function normalizeWorkflowRevisionState(value: unknown): WorkflowRevisionState {
  const record = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const assets = normalizeAssetList(record.assets) ?? [];
  const history = normalizeAssetList(record.history) ?? [];
  const activeAsset = normalizeUploadedAsset(record.active_asset);
  const candidateAsset = normalizeUploadedAsset(record.candidate_asset);
  const candidateAssets = normalizeAssetList(record.candidate_assets) ?? [];
  const libraryState = firstString(record.library_state, candidateAsset?.library_state);
  const libraryEntityId = firstString(record.library_entity_id, candidateAsset?.library_entity_id);
  const libraryAssetId = firstString(record.library_asset_id, candidateAsset?.library_asset_id);
  return {
    ...(record as unknown as WorkflowRevisionState),
    revision_id: firstString(record.revision_id, record.id) ?? "",
    workflow_id: firstString(record.workflow_id),
    node_id: firstString(record.node_id),
    node_type: firstString(record.node_type),
    status: firstString(record.status) ?? "queued",
    generation_status: firstString(record.generation_status),
    acceptance_status: firstString(record.acceptance_status),
    visibility_status: firstString(record.visibility_status),
    revision: record.revision && typeof record.revision === "object" ? record.revision as WorkflowRevisionState["revision"] : undefined,
    target_entity_id: firstString(record.target_entity_id) ?? null,
    target_asset_id: firstString(record.target_asset_id) ?? null,
    semantic_type: firstString(record.semantic_type) ?? null,
    active_asset: activeAsset,
    candidate_asset: candidateAsset,
    candidate_assets: candidateAssets,
    candidate_asset_ids: stringArray(record.candidate_asset_ids),
    library_state: firstString(record.library_state, candidateAsset?.library_state),
    library_entity_id: firstString(record.library_entity_id, candidateAsset?.library_entity_id),
    library_asset_id: firstString(record.library_asset_id, candidateAsset?.library_asset_id),
    library_error: firstString(record.library_error, record.library_ingest_error, candidateAsset?.library_error),
    source_type: firstString(record.source_type, candidateAsset?.source_type),
    acceptance_policy: firstString(record.acceptance_policy) ?? null,
    assets,
    history,
    library_suggested: Boolean(record.library_suggested) || Boolean(libraryEntityId || libraryAssetId || isLibraryIngestReadyState(libraryState)),
    error: firstString(record.error) ?? null,
    message: firstString(record.message) ?? null,
    affected_downstream_nodes: stringArray(record.affected_downstream_nodes),
    created_at: firstString(record.created_at),
    updated_at: firstString(record.updated_at),
  };
}

function isLibraryIngestReadyState(value?: string | null) {
  return ["created", "linked", "ready"].includes(String(value ?? "").trim().toLowerCase());
}

function normalizeWorkflowAssetHistoryResponse(value: unknown): WorkflowAssetHistoryResponse {
  const record = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const assets = normalizeAssetList(record.assets) ?? normalizeAssetList(record.history) ?? [];
  const history = normalizeAssetList(record.history) ?? assets;
  return {
    ...(record as unknown as WorkflowAssetHistoryResponse),
    workflow_id: firstString(record.workflow_id),
    node_id: firstString(record.node_id),
    entity_id: firstString(record.entity_id) ?? null,
    semantic_type: firstString(record.semantic_type) ?? null,
    active_asset: normalizeUploadedAsset(record.active_asset),
    assets,
    history,
    revisions: normalizeWorkflowRevisionList(record.revisions),
  };
}

function stringArray(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim())) : [];
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return undefined;
}

function normalizeBaseUrl(value: string) {
  return value.replace(/\/+$/, "");
}

function joinUrl(baseUrl: string, path: string) {
  return `${baseUrl}/${path.replace(/^\/+/, "")}`;
}

function appendAssetUploadOptions(form: FormData, options: AssetUploadOptions) {
  form.append("asset_role", options.asset_role ?? "reference");
  form.append("use_as_prompt", String(options.use_as_prompt ?? false));
  if (options.prompt_targets?.length) {
    form.append("prompt_targets", options.prompt_targets.join(","));
  }
  if (options.entity_type) {
    form.append("entity_type", options.entity_type);
  }
  if (options.semantic_type) {
    form.append("semantic_type", options.semantic_type);
  }
  if (options.display_name) {
    form.append("display_name", options.display_name);
  }
  if (options.tags?.length) {
    form.append("tags", options.tags.join(","));
  }
}
