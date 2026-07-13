import type {
  AssetOwnerResponseV2,
  ProviderTaskV2,
  SlotVersionsResponseV2,
  V2AddSlotReferenceRequest,
  V2FreeNodeAbsorbRequest,
  V2FreeNodeAbsorbResponse,
  V2FreeNodeCreateRequest,
  V2FreeNodeGenerateRequest,
  V2GlobalRunRequest,
  V2InputAssetUploadResponse,
  V2AssetLocatorResponse,
  V2ChatActionRequest,
  V2ChatActionResponse,
  V2ChatTargetRequest,
  V2ChatTargetResponse,
  V2ItemGenerateRequest,
  V2ItemPromptUpdateRequest,
  V2PlanFromChatRequest,
  V2PlanFromChatResponse,
  V2PlanFromPromptRequest,
  V2RegisterLibraryReferenceRequest,
  V2RegisterReferenceAssetRequest,
  V2RegisterReferenceResponse,
  V2ReferenceAttachRequest,
  V2ReferenceMutationResponse,
  V2SelectSlotVersionRequest,
  V2SlotPromptUpdateRequest,
  V2SlotReferenceUploadResponse,
  V2TimelineClipCreateRequest,
  V2TimelineClipMutationResponse,
  V2WorkflowAssetFilters,
  WorkflowAssetListResponseV2,
  WorkflowAssetVersionsResponseV2,
  WorkflowV2RunResponse,
  WorkflowRuntimeEventV2,
  WorkflowRuntimeV2,
  WorkflowV2,
} from "../types-v2.ts";
import {
  normalizeAssetOwnerResponseV2,
  normalizeProviderTaskV2,
  normalizeSlotVersionsResponseV2,
  normalizeV2AssetLocatorResponse,
  normalizeV2ChatActionResponse,
  normalizeV2WarningArray,
  normalizeWorkflowRuntimeEventV2,
  normalizeWorkflowRuntimeV2,
  normalizeWorkflowV2,
  normalizeWorkflowV2MutationResponse,
  normalizeWorkflowV2ReferenceMutationResponse,
  normalizeWorkflowV2RunResponse,
  normalizeV2RegisterReferenceResponse,
  normalizeV2SlotReferenceUploadResponse,
  normalizeV2InputAssetUploadResponse,
  normalizeWorkflowAssetListResponseV2,
  normalizeWorkflowAssetVersionsResponseV2,
} from "./v2Normalizers.ts";

const API_V2_BASE = "/api/v2";

export class V2ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly details: Record<string, unknown>;
  readonly stage?: string;
  readonly violations: unknown[];
  readonly suggestedActions: Array<Record<string, unknown>>;
  readonly payload: unknown;

  constructor({
    status,
    code,
    message,
    details,
    stage,
    violations,
    suggestedActions,
    payload,
  }: {
    status: number;
    code?: string;
    message: string;
    details: Record<string, unknown>;
    stage?: string;
    violations: unknown[];
    suggestedActions: Array<Record<string, unknown>>;
    payload: unknown;
  }) {
    super(message);
    this.name = "V2ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.stage = stage;
    this.violations = violations;
    this.suggestedActions = suggestedActions;
    this.payload = payload;
  }
}

export function isV2ApiError(value: unknown): value is V2ApiError {
  return value instanceof V2ApiError;
}

export function isNetworkError(value: unknown): value is Error {
  if (isV2ApiError(value) || !(value instanceof Error)) return false;
  return value instanceof TypeError || /(?:failed to fetch|network|connection|load failed)/i.test(value.message);
}

async function requestV2<T>(path: string, options: RequestInit = {}, normalize?: (value: unknown) => T): Promise<T> {
  const bodyIsFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const response = await fetch(`${API_V2_BASE}${path}`, {
    headers: options.body && !bodyIsFormData ? { "Content-Type": "application/json", ...(options.headers ?? {}) } : options.headers,
    ...options,
  });
  const payload = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload ? (payload as { detail?: unknown }).detail : payload;
    const detailRecord = asRecord(detail);
    const code = typeof detailRecord?.code === "string" ? detailRecord.code : undefined;
    const message = detailRecord && "message" in detailRecord
      ? String(detailRecord.message)
      : typeof detail === "string"
        ? detail
        : `Request failed with status ${response.status}`;
    const details = asRecord(detailRecord?.details) ?? {};
    const violations = Array.isArray(detailRecord?.violations)
      ? detailRecord.violations
      : Array.isArray(details.violations)
        ? details.violations
        : [];
    const suggestedActions = recordsFrom(detailRecord?.suggested_actions ?? details.suggested_actions);
    const stage = firstString(detailRecord?.stage, details.stage);
    throw new V2ApiError({
      status: response.status,
      code,
      message,
      details,
      stage,
      violations,
      suggestedActions,
      payload,
    });
  }
  return normalize ? normalize(payload) : (payload as T);
}

export const v2Api = {
  uploadInputAssets(formData: FormData): Promise<V2InputAssetUploadResponse> {
    return requestV2(`/input-assets/upload`, { method: "POST", body: formData }, normalizeV2InputAssetUploadResponse);
  },

  workflow(workflowId: string): Promise<WorkflowV2> {
    return requestV2(`/workflows/${encodeURIComponent(workflowId)}`, {}, normalizeWorkflowV2);
  },

  planFromPrompt(body: V2PlanFromPromptRequest): Promise<WorkflowV2> {
    return requestV2(`/workflows/plan-from-prompt`, { method: "POST", body: JSON.stringify(body) }, normalizeWorkflowV2);
  },

  planFromChat(body: V2PlanFromChatRequest): Promise<V2PlanFromChatResponse> {
    return requestV2(`/workflows/plan-from-chat`, { method: "POST", body: JSON.stringify(body) }, normalizeWorkflowV2PlanFromChatResponse);
  },

  runtime(workflowId: string): Promise<WorkflowRuntimeV2> {
    return requestV2(`/workflows/${encodeURIComponent(workflowId)}/runtime`, {}, normalizeWorkflowRuntimeV2);
  },

  async events(workflowId: string, afterSeq = 0): Promise<{ events: WorkflowRuntimeEventV2[]; next_after_seq: number }> {
    return requestV2(`/workflows/${encodeURIComponent(workflowId)}/events?after_seq=${encodeURIComponent(String(afterSeq))}`, {}, (value) => {
      const record = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
      const events = Array.isArray(record.events) ? record.events.map(normalizeWorkflowRuntimeEventV2) : [];
      const next = typeof record.next_after_seq === "number" ? record.next_after_seq : events.at(-1)?.seq ?? afterSeq;
      return { events, next_after_seq: next };
    });
  },

  openEventStream(workflowId: string, afterSeq = 0): EventSource {
    return new EventSource(`${API_V2_BASE}/workflows/${encodeURIComponent(workflowId)}/events/stream?after_seq=${encodeURIComponent(String(afterSeq))}`);
  },

  listWorkflowAssets(workflowId: string, filters: V2WorkflowAssetFilters = {}): Promise<WorkflowAssetListResponseV2> {
    const query = v2WorkflowAssetFilterQuery(filters);
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/assets${query}`,
      {},
      normalizeWorkflowAssetListResponseV2,
    );
  },

  listAssetVersions(workflowId: string, assetId: string): Promise<WorkflowAssetVersionsResponseV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/assets/${encodeURIComponent(assetId)}/versions`,
      {},
      normalizeWorkflowAssetVersionsResponseV2,
    );
  },

  updateItemPrompt(workflowId: string, itemId: string, body: V2ItemPromptUpdateRequest): Promise<WorkflowV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/items/${encodeURIComponent(itemId)}/prompt`,
      { method: "PATCH", body: JSON.stringify(body) },
      normalizeWorkflowV2,
    );
  },

  updateSlotPrompt(workflowId: string, slotId: string, body: V2SlotPromptUpdateRequest): Promise<WorkflowV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/slots/${encodeURIComponent(slotId)}/prompt`,
      { method: "PATCH", body: JSON.stringify(body) },
      normalizeWorkflowV2,
    );
  },

  generateSlot(workflowId: string, slotId: string): Promise<WorkflowV2RunResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/slots/${encodeURIComponent(slotId)}/generate`,
      { method: "POST" },
      normalizeWorkflowV2RunResponse,
    );
  },

  slotVersions(workflowId: string, slotId: string): Promise<SlotVersionsResponseV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/slots/${encodeURIComponent(slotId)}/versions`,
      {},
      normalizeSlotVersionsResponseV2,
    );
  },

  regenerateSlot(workflowId: string, slotId: string): Promise<WorkflowV2RunResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/slots/${encodeURIComponent(slotId)}/regenerate`,
      { method: "POST" },
      normalizeWorkflowV2RunResponse,
    );
  },

  discardWorkingVersion(workflowId: string, slotId: string): Promise<WorkflowV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/slots/${encodeURIComponent(slotId)}/working-version/discard`,
      { method: "POST" },
      normalizeWorkflowV2MutationResponse,
    );
  },

  generateItem(workflowId: string, itemId: string, body: V2ItemGenerateRequest = { prompt_scope: "auto" }): Promise<WorkflowV2RunResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/items/${encodeURIComponent(itemId)}/generate`,
      { method: "POST", body: JSON.stringify(body) },
      normalizeWorkflowV2RunResponse,
    );
  },

  chatAction(workflowId: string, body: V2ChatActionRequest): Promise<V2ChatActionResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/chat-actions`,
      { method: "POST", body: JSON.stringify(body) },
      normalizeV2ChatActionResponse,
    );
  },

  chatTarget(workflowId: string, body: V2ChatTargetRequest): Promise<V2ChatTargetResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/chat-target`,
      { method: "POST", body: JSON.stringify(body) },
      normalizeWorkflowV2ChatTargetResponse,
    );
  },

  resolveLocator(workflowId: string, locator: string): Promise<V2AssetLocatorResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/locators/resolve?locator=${encodeURIComponent(locator)}`,
      {},
      normalizeV2AssetLocatorResponse,
    );
  },

  selectSlotVersion(workflowId: string, slotId: string, body: V2SelectSlotVersionRequest): Promise<Record<string, unknown>> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/slots/${encodeURIComponent(slotId)}/select-version`,
      { method: "POST", body: JSON.stringify(body) },
    );
  },

  selectVersion(workflowId: string, slotId: string, versionId: string): Promise<WorkflowV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/slots/${encodeURIComponent(slotId)}/versions/${encodeURIComponent(versionId)}/select`,
      { method: "POST" },
      normalizeWorkflowV2,
    );
  },

  assetOwner(workflowId: string, assetId: string): Promise<AssetOwnerResponseV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/assets/${encodeURIComponent(assetId)}/owner`,
      {},
      normalizeAssetOwnerResponseV2,
    );
  },

  confirmShotSummary(workflowId: string, shotId: string, shotSummaryPrompt: string): Promise<WorkflowV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/storyboard/shots/${encodeURIComponent(shotId)}/confirm-summary`,
      { method: "POST", body: JSON.stringify({ shot_summary_prompt: shotSummaryPrompt }) },
      normalizeWorkflowV2,
    );
  },

  deleteSelectedSlotAsset(workflowId: string, slotId: string): Promise<WorkflowV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/slots/${encodeURIComponent(slotId)}/selected-asset`,
      { method: "DELETE" },
      normalizeWorkflowV2,
    );
  },

  attachReference(workflowId: string, body: V2ReferenceAttachRequest): Promise<V2ReferenceMutationResponse> {
    return requestV2(`/workflows/${encodeURIComponent(workflowId)}/references`, { method: "POST", body: JSON.stringify(body) }, normalizeWorkflowV2ReferenceMutationResponse);
  },

  registerLibraryReference(workflowId: string, body: V2RegisterLibraryReferenceRequest): Promise<V2RegisterReferenceResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/assets/register-library-reference`,
      { method: "POST", body: JSON.stringify(body) },
      normalizeV2RegisterReferenceResponse,
    );
  },

  registerReferenceAsset(workflowId: string, body: V2RegisterReferenceAssetRequest): Promise<V2RegisterReferenceResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/assets/register-reference`,
      { method: "POST", body: JSON.stringify(body) },
      normalizeV2RegisterReferenceResponse,
    );
  },

  uploadSlotReferenceAsset(workflowId: string, slotId: string, formData: FormData): Promise<V2SlotReferenceUploadResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/slots/${encodeURIComponent(slotId)}/reference-assets/upload`,
      { method: "POST", body: formData },
      normalizeV2SlotReferenceUploadResponse,
    );
  },

  attachSlotReference(workflowId: string, slotId: string, body: V2AddSlotReferenceRequest): Promise<Record<string, unknown>> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/slots/${encodeURIComponent(slotId)}/references`,
      { method: "POST", body: JSON.stringify(body) },
    );
  },

  removeReference(workflowId: string, relationId: string): Promise<V2ReferenceMutationResponse> {
    return requestV2(`/workflows/${encodeURIComponent(workflowId)}/references/${encodeURIComponent(relationId)}`, { method: "DELETE" }, normalizeWorkflowV2ReferenceMutationResponse);
  },

  runWorkflow(workflowId: string, body: V2GlobalRunRequest = { mode: "fill_missing_required_slots" }): Promise<WorkflowV2RunResponse> {
    return requestV2(`/workflows/${encodeURIComponent(workflowId)}/run`, { method: "POST", body: JSON.stringify(body) }, normalizeWorkflowV2RunResponse);
  },

  runWorkflowAsync(workflowId: string, body: V2GlobalRunRequest = { mode: "fill_missing_required_slots" }): Promise<WorkflowV2RunResponse> {
    return requestV2(`/workflows/${encodeURIComponent(workflowId)}/run?wait=false`, { method: "POST", body: JSON.stringify(body) }, normalizeWorkflowV2RunResponse);
  },

  createFreeNode(workflowId: string, body: V2FreeNodeCreateRequest): Promise<WorkflowV2> {
    return requestV2(`/workflows/${encodeURIComponent(workflowId)}/free-nodes`, { method: "POST", body: JSON.stringify(body) }, normalizeWorkflowV2);
  },

  generateFreeNode(workflowId: string, nodeId: string, body: V2FreeNodeGenerateRequest): Promise<WorkflowV2RunResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/free-nodes/${encodeURIComponent(nodeId)}/generate`,
      { method: "POST", body: JSON.stringify(body) },
      normalizeWorkflowV2RunResponse,
    );
  },

  absorbFreeNode(workflowId: string, nodeId: string, body: V2FreeNodeAbsorbRequest): Promise<V2FreeNodeAbsorbResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/free-nodes/${encodeURIComponent(nodeId)}/absorb`,
      { method: "POST", body: JSON.stringify(body) },
      normalizeWorkflowV2FreeNodeAbsorbResponse,
    );
  },

  deleteFreeNode(workflowId: string, nodeId: string): Promise<WorkflowV2> {
    return requestV2(`/workflows/${encodeURIComponent(workflowId)}/free-nodes/${encodeURIComponent(nodeId)}`, { method: "DELETE" }, normalizeWorkflowV2);
  },

  providerTask(workflowId: string, taskId: string): Promise<ProviderTaskV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/provider-tasks/${encodeURIComponent(taskId)}`,
      {},
      normalizeProviderTaskV2,
    );
  },

  pollProviderTask(workflowId: string, taskId: string): Promise<ProviderTaskV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/provider-tasks/${encodeURIComponent(taskId)}/poll`,
      { method: "POST" },
      normalizeProviderTaskV2,
    );
  },

  listProviderTasks(workflowId: string, params: { slot_id?: string | null } = {}): Promise<ProviderTaskV2[]> {
    const query = params.slot_id ? `?slot_id=${encodeURIComponent(params.slot_id)}` : "";
    return requestV2(`/workflows/${encodeURIComponent(workflowId)}/provider-tasks${query}`, {}, normalizeProviderTaskListResponse);
  },

  createTimelineClip(workflowId: string, body: V2TimelineClipCreateRequest): Promise<V2TimelineClipMutationResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/final-composition/timeline/clips`,
      { method: "POST", body: JSON.stringify(body) },
      normalizeWorkflowV2TimelineClipMutationResponse,
    );
  },

  deleteTimelineClip(workflowId: string, clipId: string): Promise<V2TimelineClipMutationResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/final-composition/timeline/clips/${encodeURIComponent(clipId)}`,
      { method: "DELETE" },
      normalizeWorkflowV2TimelineClipMutationResponse,
    );
  },
};

function normalizeWorkflowV2PlanFromChatResponse(value: unknown): V2PlanFromChatResponse {
  const record = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    front_desk: (record.front_desk ?? {}) as V2PlanFromChatResponse["front_desk"],
    workflow: record.workflow ? normalizeWorkflowV2(record.workflow) : null,
    normalized_v2_request: asRecord(record.normalized_v2_request),
    status: typeof record.status === "string" ? record.status : null,
    error_code: typeof record.error_code === "string" ? record.error_code : null,
    message: typeof record.message === "string" ? record.message : null,
    details: asRecord(record.details) ?? {},
    suggested_actions: recordsFrom(record.suggested_actions),
  };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function recordsFrom(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(asRecord(item))) : [];
}

function firstString(...values: unknown[]): string | undefined {
  return values.find((value): value is string => typeof value === "string");
}

function normalizeWorkflowV2ChatTargetResponse(value: unknown): V2ChatTargetResponse {
  const record = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    workflow: record.workflow ? normalizeWorkflowV2(record.workflow) : null,
    target: record.target && typeof record.target === "object" ? (record.target as V2ChatTargetResponse["target"]) : undefined,
    message: typeof record.message === "string" ? record.message : undefined,
    action_mode: typeof record.action_mode === "string" ? record.action_mode : undefined,
    specialist: typeof record.specialist === "string" ? record.specialist : undefined,
    applied: typeof record.applied === "boolean" ? record.applied : undefined,
    updated_prompt_scope: typeof record.updated_prompt_scope === "string" ? record.updated_prompt_scope : undefined,
    generated: typeof record.generated === "boolean" ? record.generated : undefined,
    affected_slot_ids: Array.isArray(record.affected_slot_ids) ? record.affected_slot_ids.filter((item): item is string => typeof item === "string") : [],
    executed_slot_ids: Array.isArray(record.executed_slot_ids) ? record.executed_slot_ids.filter((item): item is string => typeof item === "string") : [],
    asset_ids: Array.isArray(record.asset_ids) ? record.asset_ids.filter((item): item is string => typeof item === "string") : [],
    version_ids: Array.isArray(record.version_ids) ? record.version_ids.filter((item): item is string => typeof item === "string") : [],
    provider_calls: Array.isArray(record.provider_calls) ? record.provider_calls.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item))) : [],
    warnings: normalizeV2WarningArray(record.warnings),
    agent_route_snapshot: record.agent_route_snapshot && typeof record.agent_route_snapshot === "object" ? (record.agent_route_snapshot as Record<string, unknown>) : null,
  };
}

function normalizeProviderTaskListResponse(value: unknown): ProviderTaskV2[] {
  if (Array.isArray(value)) return value.map(normalizeProviderTaskV2);
  const record = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  const items = Array.isArray(record.tasks) ? record.tasks : Array.isArray(record.items) ? record.items : [];
  return items.map(normalizeProviderTaskV2);
}

function normalizeWorkflowV2FreeNodeAbsorbResponse(value: unknown): V2FreeNodeAbsorbResponse {
  const record = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    workflow: normalizeWorkflowV2(record.workflow),
    relations: Array.isArray(record.relations) ? record.relations.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item))) : [],
  };
}

function normalizeWorkflowV2TimelineClipMutationResponse(value: unknown): V2TimelineClipMutationResponse {
  const record = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    workflow: normalizeWorkflowV2(record.workflow),
    clip: record.clip && typeof record.clip === "object" ? (record.clip as Record<string, unknown>) : null,
    removed_clip_id: typeof record.removed_clip_id === "string" ? record.removed_clip_id : null,
  };
}

function v2WorkflowAssetFilterQuery(filters: V2WorkflowAssetFilters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}
