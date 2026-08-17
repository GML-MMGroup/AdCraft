import type {
  AgentCanvasChatMessageRequestV2,
  AgentCanvasChatTurnRetryRequestV2,
  AgentCanvasChatViewTimelineV2,
  AgentCanvasCommandPlanActionRequestV2,
  AgentCanvasChatTurnV2,
  AgentCanvasImageLibraryListResponseV2,
  AgentCanvasGuidedActionApplyRequestV2,
  GuidedInteractionAcceptedV1,
  GuidedInteractionSubmitRequestV1,
  GuidedSessionStateV2,
  AgentCanvasProjectCreateResponseV2,
  AgentCanvasProjectCreateRequestV2,
  AgentCanvasProposalActionRequestV2,
  DecisionBundleActionAcceptedV2,
  DecisionBundleActionRequestV2,
  DecisionBundleV2,
  AgentCanvasVideoSkillRunCreateRequestV2,
  AgentCanvasVideoSkillRunV2,
  VideoSkillCatalogResponseV2,
  VideoSkillPublicDetailV2,
  AgentCanvasWorkflowV2,
  AgentExecutionSettingsPatchV2,
  AgentExecutionSettingsV2,
  AgentWorkingDocumentKindV2,
  AgentWorkingDocumentPageV2,
  AgentWorkingDocumentV2,
  AssetOwnerResponseV2,
  CanvasBindingCreateRequestV2,
  CanvasBindingMutationResponseV2,
  CanvasBindingPatchRequestV2,
  CanvasConnectedNodeCreateRequestV2,
  CanvasConnectedNodeCreateResponseV2,
  CanvasConnectionPolicyV2,
  CanvasLayoutPatchRequestV2,
  CanvasLayoutPatchResponseV2,
  CanvasMutationResponseV2,
  CanvasNodeCreateRequestV2,
  CanvasNodePatchRequestV2,
  CanvasNodeV2,
  ConceptProposalV2,
  CanvasVariationDraftResponseV2,
  CanvasVariationDraftUpsertV2,
  CanvasVariationMaterializeRequestV2,
  CanvasVariationMaterializeResponseV2,
  CanvasRunAcceptedV2,
  CanvasRunCancelRequestV2,
  CanvasRunCancelResponseV2,
  CanvasRunRequestV2,
  CanvasRuntimeEventsResponseV2,
  CanvasRuntimeSnapshotV2,
  ChatTurnAcceptedV2,
  EditingExportAcceptedV2,
  EditingExportCancelResponseV2,
  EditingExportRequestV2,
  ProjectV2,
  ProjectV2ListResponse,
  ProjectV2Status,
  ProjectV2UpdateRequest,
  ProjectAssetListResponseV2,
  ProjectAssetUploadResponseV2,
  ProviderModelCapabilityListV2,
  SaveAgentCanvasImageToLibraryRequestV2,
  ProviderTaskV2,
  SlotVersionsResponseV2,
  V2AddSlotReferenceRequest,
  V2AssetLibraryCreateRequest,
  V2AssetLibraryEntityDetail,
  V2AssetLibraryListRequest,
  V2AssetLibraryListResponse,
  V2AssetLibraryPatchRequest,
  V2EtaggedResponse,
  V2FreeNodeAbsorbRequest,
  V2FreeNodeAbsorbResponse,
  V2FreeNodeCreateRequest,
  V2FreeNodeGenerateRequest,
  V2GlobalRunRequest,
  V2InputAssetUploadResponse,
  V2FinalTimelineRenderRequest,
  V2FinalTimelineRenderStartResponse,
  V2FinalTimelineRenderStateResponse,
  V2FinalTimelineResponse,
  V2FinalTimelineSourceImportRequest,
  V2FinalTimelineSourceImportResponse,
  V2FinalTimelineUpdateRequest,
  V2FinalTimelineUpdateResponse,
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
  V2ReferenceSelectionsRequest,
  V2ReferenceSelectionsResponse,
  V2RecommendedCatalogStatus,
  V2ReferenceMutationResponse,
  V2ScriptConfirmRequest,
  V2ScriptConfirmResponse,
  V2ScriptReadResponse,
  V2ScriptSelectVersionRequest,
  V2ScriptSelectVersionResponse,
  V2ScriptVersionListResponse,
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
  PersistedWorkflowV2,
  WorkflowRevisionPage,
  WorkflowRevisionRestoreResponse,
  WorkflowRevisionV2Detail,
} from "../types-v2.ts";
import {
  normalizeAssetOwnerResponseV2,
  normalizeProjectV2,
  normalizeProjectV2ListResponse,
  normalizeV2AssetLibraryEntityDetail,
  normalizeV2AssetLibraryListResponse,
  normalizeV2RecommendedCatalogStatus,
  normalizeV2ReferenceSelectionsResponse,
  normalizeProviderTaskV2,
  normalizeSlotVersionsResponseV2,
  normalizeV2AssetLocatorResponse,
  normalizeV2ChatActionResponse,
  normalizeV2WarningArray,
  normalizeWorkflowRuntimeEventV2,
  normalizeWorkflowRuntimeV2,
  normalizePersistedWorkflowV2,
  normalizeWorkflowV2,
  normalizeWorkflowV2MutationResponse,
  normalizeWorkflowV2ReferenceMutationResponse,
  normalizeWorkflowV2RunResponse,
  normalizeWorkflowRevisionPage,
  normalizeWorkflowRevisionRestoreResponse,
  normalizeWorkflowRevisionV2Detail,
  normalizeV2RegisterReferenceResponse,
  normalizeV2ScriptConfirmResponse,
  normalizeV2ScriptReadResponse,
  normalizeV2ScriptSelectVersionResponse,
  normalizeV2ScriptVersionListResponse,
  normalizeV2SlotReferenceUploadResponse,
  normalizeV2InputAssetUploadResponse,
  normalizeV2FinalTimelineRenderStartResponse,
  normalizeV2FinalTimelineRenderStateResponse,
  normalizeV2FinalTimelineResponse,
  normalizeV2FinalTimelineSourceImportResponse,
  normalizeV2FinalTimelineUpdateResponse,
  normalizeWorkflowAssetListResponseV2,
  normalizeWorkflowAssetVersionsResponseV2,
} from "./v2Normalizers.ts";
import {
  normalizeAgentCanvasChatTurnV2,
  normalizeAgentCanvasChatTimelineV2,
  normalizeDecisionBundleActionAcceptedV2,
  normalizeDecisionBundleV2,
  normalizeGuidedSessionStateV2,
  normalizeGuidedInteractionAcceptedV1,
  normalizeAgentCanvasImageLibraryListResponseV2,
  normalizeAgentCanvasProjectCreateResponseV2,
  normalizeAgentCanvasVideoSkillRunV2,
  normalizeVideoSkillCatalogResponseV2,
  normalizeVideoSkillPublicDetailV2,
  normalizeAgentCanvasWorkflowV2,
  normalizeAgentExecutionSettingsV2,
  normalizeAgentWorkingDocumentPageV2,
  normalizeAgentWorkingDocumentV2,
  normalizeCanvasMutationResponseV2,
  normalizeCanvasBindingMutationResponseV2,
  normalizeCanvasConnectedNodeCreateResponseV2,
  normalizeCanvasConnectionPolicyV2,
  normalizeCanvasLayoutPatchResponseV2,
  normalizeCanvasNodeV2,
  normalizeCanvasVariationDraftResponseV2,
  normalizeCanvasVariationMaterializeResponseV2,
  normalizeCanvasRunAcceptedV2,
  normalizeCanvasRunCancelResponseV2,
  normalizeCanvasRuntimeEventsResponseV2,
  normalizeCanvasRuntimeSnapshotV2,
  normalizeChatTurnAcceptedV2,
  normalizeConceptProposalV2,
  normalizeEditingExportAcceptedV2,
  normalizeEditingExportCancelResponseV2,
  normalizeProjectAssetListResponseV2,
  normalizeProjectAssetUploadResponseV2,
  normalizeProviderModelCapabilityListV2,
} from "../features/agent-canvas/model/normalizers.ts";
import { v2EtagStore, type V2AuthoringResource } from "./v2EtagStore.ts";

const API_V2_BASE = "/api/v2";
const inFlightMetadataReads = new Map<string, Promise<unknown>>();

type V2PreconditionTarget = { resource: V2AuthoringResource; id: string };
type V2RequestBehavior = {
  captureAuthoringEtag?: boolean;
  explicitAuthoringPrecondition?: V2PreconditionTarget;
  allowMissingAuthoringEtag?: boolean;
};

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

export class V2NetworkError extends Error {
  override readonly cause: unknown;

  constructor(cause: unknown) {
    super(cause instanceof Error ? cause.message : "Network request failed");
    this.name = "V2NetworkError";
    this.cause = cause;
  }
}

export function isV2ApiError(value: unknown): value is V2ApiError {
  return value instanceof V2ApiError;
}

export function isNetworkError(value: unknown): value is V2NetworkError {
  return value instanceof V2NetworkError;
}

async function requestV2Payload(path: string, options: RequestInit = {}): Promise<unknown> {
  return (await requestV2Response(path, options)).payload;
}

async function requestV2Response(
  path: string,
  options: RequestInit = {},
  optionsByBehavior: V2RequestBehavior = {},
): Promise<{ payload: unknown; etag: string | null }> {
  const bodyIsFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const method = (options.method ?? "GET").toUpperCase();
  const headers = new Headers(options.headers);
  const precondition = optionsByBehavior.explicitAuthoringPrecondition
    ?? v2AuthoringPreconditionTarget(path, method);
  if (precondition && !headers.has("If-Match") && !optionsByBehavior.allowMissingAuthoringEtag) {
    const etag = v2EtagStore.get(precondition.resource, precondition.id)
      ?? await fetchCurrentAuthoringEtag(precondition);
    if (!etag) throw new Error(`Missing backend ETag for ${precondition.resource} ${precondition.id}.`);
    headers.set("If-Match", etag);
  }
  if (options.body && !bodyIsFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let response: Response;
  try {
    response = await fetch(`${API_V2_BASE}${path}`, {
      ...options,
      cache: method === "GET" ? "no-store" : options.cache,
      headers,
    });
  } catch (error) {
    throw new V2NetworkError(error);
  }
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
    if (precondition && (response.status === 412 || response.status === 428)) {
      const { v2AuthoringConflictStore } = await import("./v2AuthoringConflictStore.ts");
      const retryOptions = { ...options, headers: new Headers(options.headers) };
      retryOptions.headers.delete("If-Match");
      try {
        await fetchCurrentAuthoringEtag(precondition);
      } catch {
        // Keep the original precondition error actionable even when the refresh cannot complete.
      }
      v2AuthoringConflictStore.raise({
        target: precondition,
        operationPath: path,
        message,
        retry: async () => {
          await requestV2Response(path, retryOptions, {
            ...optionsByBehavior,
            allowMissingAuthoringEtag: false,
          });
        },
        discard: async () => {},
      });
    }
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
  const etag = response.headers.get("etag");
  if (optionsByBehavior.captureAuthoringEtag !== false) {
    captureAuthoringEtag(path, payload, etag, precondition);
  }
  return { payload, etag };
}

export function v2AuthoringPreconditionTarget(path: string, method: string): V2PreconditionTarget | null {
  if (!new Set(["POST", "PATCH", "PUT", "DELETE"]).has(method.toUpperCase())) return null;
  const pathname = path.split("?", 1)[0] ?? path;
  const project = pathname.match(/^\/projects\/([^/]+)(?:\/restore)?$/);
  if (project) return { resource: "project", id: decodeURIComponent(project[1] ?? "") };
  if (/^\/workflows\/plan-from-(?:prompt|chat)$/.test(pathname)) return null;
  const workflow = pathname.match(/^\/workflows\/([^/]+)(\/.*)?$/);
  if (!workflow) return null;
  const workflowId = decodeURIComponent(workflow[1] ?? "");
  const suffix = workflow[2] ?? "";
  if (
    suffix === "/layout"
    || suffix === "/agent-settings"
    || suffix === "/run"
    || suffix === "/runs"
    || suffix === "/chat-target"
    || suffix.startsWith("/chat/")
    || suffix === "/skill-runs"
    || suffix === "/assets/upload"
    || /\/(?:generate|regenerate)$/.test(suffix)
    || /\/runs\/[^/]+\/cancel$/.test(suffix)
    || /\/nodes\/[^/]+\/export$/.test(suffix)
    || /\/nodes\/[^/]+\/exports\/[^/]+\/cancel$/.test(suffix)
    || suffix === "/final-composition/render"
    || /\/provider-tasks(?:\/|$)/.test(suffix)
    || /\/executions\/[^/]+\/(?:resume|cancel)$/.test(suffix)
    || /\/working-version\/discard$/.test(suffix)
    || /\/renders\/[^/]+\/cancel$/.test(suffix)
  ) return null;
  return { resource: "workflow", id: workflowId };
}

async function fetchCurrentAuthoringEtag(target: V2PreconditionTarget): Promise<string | null> {
  const path = target.resource === "project"
    ? `/projects/${encodeURIComponent(target.id)}`
    : `/workflows/${encodeURIComponent(target.id)}`;
  const response = await requestV2Response(path);
  if (response.etag) v2EtagStore.set(target.resource, target.id, response.etag);
  return response.etag;
}

function captureAuthoringEtag(
  path: string,
  payload: unknown,
  etag: string | null,
  precondition: V2PreconditionTarget | null,
): void {
  if (etag && precondition) v2EtagStore.set(precondition.resource, precondition.id, etag);
  const record = asRecord(payload);
  const workflow = asRecord(record?.workflow) ?? (record?.workflow_schema_version === 2 ? record : null);
  if (etag && workflow && typeof workflow.workflow_id === "string") {
    v2EtagStore.set("workflow", workflow.workflow_id, etag);
    return;
  }
  if (etag && record && typeof record.project_id === "string" && typeof record.project_version === "number") {
    v2EtagStore.set("project", record.project_id, etag);
    return;
  }
  const workflowRead = path.match(/^\/workflows\/([^/]+)$/);
  if (etag && workflowRead) v2EtagStore.set("workflow", decodeURIComponent(workflowRead[1] ?? ""), etag);
}

function metadataReadKey(path: string, options: RequestInit) {
  const headers = new Headers(options.headers);
  const headerKey = Array.from(headers.entries())
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}:${value}`)
    .join("|");
  return `${path}|${headerKey}`;
}

async function requestV2<T>(path: string, options: RequestInit = {}, normalize?: (value: unknown) => T): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const canDedupe = method === "GET" && !options.signal;
  const key = canDedupe ? metadataReadKey(path, options) : null;
  let payloadRequest = key ? inFlightMetadataReads.get(key) : undefined;
  if (!payloadRequest) {
    payloadRequest = requestV2Payload(path, options);
    if (key) {
      inFlightMetadataReads.set(key, payloadRequest);
      void payloadRequest.finally(() => {
        if (inFlightMetadataReads.get(key) === payloadRequest) inFlightMetadataReads.delete(key);
      }).catch(() => {});
    }
  }
  const payload = await payloadRequest;
  return normalize ? normalize(payload) : (payload as T);
}

async function requestV2WithEtag<T>(
  path: string,
  options: RequestInit = {},
  normalize?: (value: unknown) => T,
  optionsByBehavior: V2RequestBehavior = {},
): Promise<V2EtaggedResponse<T>> {
  const response = await requestV2Response(path, options, optionsByBehavior);
  return {
    value: normalize ? normalize(response.payload) : (response.payload as T),
    etag: response.etag,
  };
}

async function requestV2GlobalRun<T>(
  workflowId: string,
  path: string,
  options: RequestInit,
  normalize: (value: unknown) => T,
): Promise<T> {
  const etag = v2EtagStore.getWorkflow(workflowId)
    ?? await fetchCurrentAuthoringEtag({ resource: "workflow", id: workflowId });
  const headers = new Headers(options.headers);
  if (etag) headers.set("If-Match", etag);
  const response = await requestV2Response(path, { ...options, headers }, {
    captureAuthoringEtag: false,
    explicitAuthoringPrecondition: etag ? { resource: "workflow", id: workflowId } : undefined,
    allowMissingAuthoringEtag: true,
  });
  return normalize(response.payload);
}

function idempotencyHeaders(idempotencyKey: string): Headers {
  const headers = new Headers();
  headers.set("Idempotency-Key", idempotencyKey);
  return headers;
}

export const v2Api = {
  createAgentCanvasProject(
    request: AgentCanvasProjectCreateRequestV2,
    idempotencyKey: string,
  ): Promise<V2EtaggedResponse<AgentCanvasProjectCreateResponseV2>> {
    return requestV2WithEtag(
      "/projects",
      {
        method: "POST",
        headers: idempotencyHeaders(idempotencyKey),
        body: JSON.stringify(request),
      },
      normalizeAgentCanvasProjectCreateResponseV2,
    );
  },

  agentCanvasWorkflowWithEtag(
    workflowId: string,
  ): Promise<V2EtaggedResponse<AgentCanvasWorkflowV2>> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}`,
      {},
      normalizeAgentCanvasWorkflowV2,
    );
  },

  agentCanvasExecutionSettings(
    workflowId: string,
  ): Promise<V2EtaggedResponse<AgentExecutionSettingsV2>> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}/agent-settings`,
      {},
      normalizeAgentExecutionSettingsV2,
      { captureAuthoringEtag: false },
    );
  },

  patchAgentCanvasExecutionSettings(
    workflowId: string,
    request: AgentExecutionSettingsPatchV2,
    expectedRevision: number,
  ): Promise<V2EtaggedResponse<AgentExecutionSettingsV2>> {
    const headers = new Headers();
    headers.set("If-Match", `"${expectedRevision}"`);
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}/agent-settings`,
      {
        method: "PATCH",
        headers,
        body: JSON.stringify(request),
      },
      normalizeAgentExecutionSettingsV2,
      { captureAuthoringEtag: false },
    );
  },

  agentCanvasNode(workflowId: string, nodeId: string): Promise<CanvasNodeV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}`,
      {},
      normalizeCanvasNodeV2,
    );
  },

  patchAgentCanvasLayout(
    workflowId: string,
    request: CanvasLayoutPatchRequestV2,
  ): Promise<CanvasLayoutPatchResponseV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/layout`,
      {
        method: "PATCH",
        body: JSON.stringify(request),
      },
      normalizeCanvasLayoutPatchResponseV2,
    );
  },

  createAgentCanvasNode(
    workflowId: string,
    request: CanvasNodeCreateRequestV2,
  ): Promise<V2EtaggedResponse<CanvasMutationResponseV2>> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}/nodes`,
      { method: "POST", body: JSON.stringify(request) },
      normalizeCanvasMutationResponseV2,
    );
  },

  patchAgentCanvasNode(
    workflowId: string,
    nodeId: string,
    request: CanvasNodePatchRequestV2,
  ): Promise<V2EtaggedResponse<CanvasMutationResponseV2>> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}`,
      { method: "PATCH", body: JSON.stringify(request) },
      normalizeCanvasMutationResponseV2,
    );
  },

  saveAgentCanvasVariationDraft(
    workflowId: string,
    nodeId: string,
    request: CanvasVariationDraftUpsertV2,
  ): Promise<CanvasVariationDraftResponseV2> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}/variation-draft`,
      {
        method: "PUT",
        body: JSON.stringify(request),
      },
      normalizeCanvasVariationDraftResponseV2,
    ).then((response) => response.value);
  },

  discardAgentCanvasVariationDraft(
    workflowId: string,
    nodeId: string,
  ): Promise<void> {
    return requestV2WithEtag<void>(
      `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}/variation-draft`,
      { method: "DELETE" },
    ).then(() => undefined);
  },

  materializeAgentCanvasVariationDraft(
    workflowId: string,
    nodeId: string,
    request: CanvasVariationMaterializeRequestV2,
    idempotencyKey: string,
  ): Promise<CanvasVariationMaterializeResponseV2> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}/variation-draft/materialize`,
      {
        method: "POST",
        headers: idempotencyHeaders(idempotencyKey),
        body: JSON.stringify(request),
      },
      normalizeCanvasVariationMaterializeResponseV2,
    ).then((response) => response.value);
  },

  deleteAgentCanvasNode(
    workflowId: string,
    nodeId: string,
  ): Promise<V2EtaggedResponse<CanvasMutationResponseV2>> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}`,
      { method: "DELETE" },
      normalizeCanvasMutationResponseV2,
    );
  },

  createAgentCanvasBinding(
    workflowId: string,
    request: CanvasBindingCreateRequestV2,
  ): Promise<V2EtaggedResponse<CanvasMutationResponseV2>> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}/bindings`,
      { method: "POST", body: JSON.stringify(request) },
      normalizeCanvasMutationResponseV2,
    );
  },

  agentCanvasConnectionPolicy(): Promise<CanvasConnectionPolicyV2> {
    return requestV2(
      "/canvas/connection-policy",
      {},
      normalizeCanvasConnectionPolicyV2,
    );
  },

  createAgentCanvasConnectedNode(
    workflowId: string,
    request: CanvasConnectedNodeCreateRequestV2,
    idempotencyKey: string,
  ): Promise<V2EtaggedResponse<CanvasConnectedNodeCreateResponseV2>> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}/connected-nodes`,
      {
        method: "POST",
        headers: idempotencyHeaders(idempotencyKey),
        body: JSON.stringify(request),
      },
      normalizeCanvasConnectedNodeCreateResponseV2,
    );
  },

  patchAgentCanvasBinding(
    workflowId: string,
    bindingId: string,
    request: CanvasBindingPatchRequestV2,
    idempotencyKey: string,
  ): Promise<V2EtaggedResponse<CanvasBindingMutationResponseV2>> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}/bindings/${encodeURIComponent(bindingId)}`,
      {
        method: "PATCH",
        headers: idempotencyHeaders(idempotencyKey),
        body: JSON.stringify(request),
      },
      normalizeCanvasBindingMutationResponseV2,
    );
  },

  deleteAgentCanvasBinding(
    workflowId: string,
    bindingId: string,
  ): Promise<V2EtaggedResponse<CanvasMutationResponseV2>> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}/bindings/${encodeURIComponent(bindingId)}`,
      { method: "DELETE" },
      normalizeCanvasMutationResponseV2,
    );
  },

  uploadAgentCanvasAsset(
    workflowId: string,
    formData: FormData,
    idempotencyKey: string,
  ): Promise<ProjectAssetUploadResponseV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/assets/upload`,
      {
        method: "POST",
        headers: idempotencyHeaders(idempotencyKey),
        body: formData,
      },
      normalizeProjectAssetUploadResponseV2,
    );
  },

  listAgentCanvasProjectAssets(workflowId: string): Promise<ProjectAssetListResponseV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/assets`,
      {},
      normalizeProjectAssetListResponseV2,
    );
  },

  listAgentCanvasMyAssets(category?: string | null): Promise<AgentCanvasImageLibraryListResponseV2> {
    const query = category ? `?category=${encodeURIComponent(category)}` : "";
    return requestV2(
      `/assets/mine${query}`,
      {},
      normalizeAgentCanvasImageLibraryListResponseV2,
    );
  },

  listAgentCanvasRecommendedAssets(category?: string | null): Promise<AgentCanvasImageLibraryListResponseV2> {
    const query = category ? `?category=${encodeURIComponent(category)}` : "";
    return requestV2(
      `/assets/recommended${query}`,
      {},
      normalizeAgentCanvasImageLibraryListResponseV2,
    );
  },

  saveAgentCanvasImageToLibrary(
    assetId: string,
    request: SaveAgentCanvasImageToLibraryRequestV2,
    idempotencyKey: string,
  ): Promise<V2AssetLibraryEntityDetail> {
    return requestV2(
      `/assets/${encodeURIComponent(assetId)}/save-to-library`,
      {
        method: "POST",
        headers: idempotencyHeaders(idempotencyKey),
        body: JSON.stringify(request),
      },
      normalizeV2AssetLibraryEntityDetail,
    );
  },

  deleteAgentCanvasAsset(assetId: string): Promise<void> {
    return requestV2(`/assets/${encodeURIComponent(assetId)}`, { method: "DELETE" });
  },

  agentCanvasCreativeSession(workflowId: string): Promise<GuidedSessionStateV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/creative-session`,
      {},
      normalizeGuidedSessionStateV2,
    );
  },

  agentCanvasDecisionBundle(
    workflowId: string,
    bundleId: string,
  ): Promise<DecisionBundleV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/chat/decision-bundles/${encodeURIComponent(bundleId)}`,
      {},
      normalizeDecisionBundleV2,
    );
  },

  actOnAgentCanvasDecisionBundle(
    workflowId: string,
    bundleId: string,
    request: DecisionBundleActionRequestV2,
    idempotencyKey: string,
  ): Promise<DecisionBundleActionAcceptedV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/chat/decision-bundles/${encodeURIComponent(bundleId)}/answers`,
      {
        method: "POST",
        headers: idempotencyHeaders(idempotencyKey),
        body: JSON.stringify(request),
      },
      normalizeDecisionBundleActionAcceptedV2,
    );
  },

  agentCanvasChatTimeline(
    workflowId: string,
    afterSeq = 0,
    limit = 100,
  ): Promise<AgentCanvasChatViewTimelineV2> {
    const query = new URLSearchParams({
      after_seq: String(afterSeq),
      limit: String(limit),
    });
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/chat/timeline?${query.toString()}`,
      {},
      normalizeAgentCanvasChatTimelineV2,
    );
  },

  listAgentCanvasDocuments(
    workflowId: string,
    filters: {
      kind?: AgentWorkingDocumentKindV2;
      cursor?: string;
      limit?: number;
    } = {},
  ): Promise<AgentWorkingDocumentPageV2> {
    const query = new URLSearchParams();
    if (filters.kind) query.set("kind", filters.kind);
    if (filters.cursor) query.set("cursor", filters.cursor);
    if (filters.limit !== undefined) query.set("limit", String(filters.limit));
    const suffix = query.size ? `?${query.toString()}` : "";
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/agent-documents${suffix}`,
      {},
      normalizeAgentWorkingDocumentPageV2,
    );
  },

  agentCanvasDocument(
    workflowId: string,
    documentId: string,
  ): Promise<AgentWorkingDocumentV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/agent-documents/${encodeURIComponent(documentId)}`,
      {},
      normalizeAgentWorkingDocumentV2,
    );
  },

  submitAgentCanvasGuidedInteraction(
    workflowId: string,
    interactionId: string,
    request: GuidedInteractionSubmitRequestV1,
    idempotencyKey: string,
  ): Promise<GuidedInteractionAcceptedV1> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/chat/interactions/${encodeURIComponent(interactionId)}/submit`,
      {
        method: "POST",
        headers: idempotencyHeaders(idempotencyKey),
        body: JSON.stringify(request),
      },
      normalizeGuidedInteractionAcceptedV1,
    );
  },

  submitAgentCanvasChatMessage(
    workflowId: string,
    request: AgentCanvasChatMessageRequestV2,
    idempotencyKey: string,
  ): Promise<ChatTurnAcceptedV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/chat/messages`,
      {
        method: "POST",
        headers: idempotencyHeaders(idempotencyKey),
        body: JSON.stringify(request),
      },
      normalizeChatTurnAcceptedV2,
    );
  },

  retryAgentCanvasChatTurn(
    workflowId: string,
    turnId: string,
    request: AgentCanvasChatTurnRetryRequestV2,
    idempotencyKey: string,
  ): Promise<ChatTurnAcceptedV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/chat/turns/${encodeURIComponent(turnId)}/retry`,
      {
        method: "POST",
        headers: idempotencyHeaders(idempotencyKey),
        body: JSON.stringify(request),
      },
      normalizeChatTurnAcceptedV2,
    );
  },

  agentCanvasChatTurn(workflowId: string, turnId: string): Promise<AgentCanvasChatTurnV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/chat/turns/${encodeURIComponent(turnId)}`,
      {},
      normalizeAgentCanvasChatTurnV2,
    );
  },

  agentCanvasProposal(
    workflowId: string,
    proposalId: string,
  ): Promise<ConceptProposalV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/chat/proposals/${encodeURIComponent(proposalId)}`,
      {},
      normalizeConceptProposalV2,
    );
  },

  actOnAgentCanvasProposal(
    workflowId: string,
    proposalId: string,
    request: AgentCanvasProposalActionRequestV2,
    idempotencyKey: string,
  ): Promise<ChatTurnAcceptedV2> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}/chat/proposals/${encodeURIComponent(proposalId)}/actions`,
      {
        method: "POST",
        headers: idempotencyHeaders(idempotencyKey),
        body: JSON.stringify(request),
      },
      normalizeChatTurnAcceptedV2,
      {
        captureAuthoringEtag: false,
        explicitAuthoringPrecondition: {
          resource: "workflow",
          id: workflowId,
        },
      },
    ).then((response) => response.value);
  },

  actOnAgentCanvasCommandPlan(
    workflowId: string,
    planId: string,
    request: AgentCanvasCommandPlanActionRequestV2,
    idempotencyKey: string,
  ): Promise<ChatTurnAcceptedV2> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}/chat/command-plans/${encodeURIComponent(planId)}/actions`,
      {
        method: "POST",
        headers: idempotencyHeaders(idempotencyKey),
        body: JSON.stringify(request),
      },
      normalizeChatTurnAcceptedV2,
      {
        captureAuthoringEtag: false,
        explicitAuthoringPrecondition: {
          resource: "workflow",
          id: workflowId,
        },
      },
    ).then((response) => response.value);
  },

  applyAgentCanvasGuidedAction(
    workflowId: string,
    actionId: string,
    request: AgentCanvasGuidedActionApplyRequestV2,
    idempotencyKey: string,
  ): Promise<ChatTurnAcceptedV2> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}/chat/guided-actions/${encodeURIComponent(actionId)}/apply`,
      {
        method: "POST",
        headers: idempotencyHeaders(idempotencyKey),
        body: JSON.stringify(request),
      },
      normalizeChatTurnAcceptedV2,
      {
        captureAuthoringEtag: false,
        explicitAuthoringPrecondition: {
          resource: "workflow",
          id: workflowId,
        },
      },
    ).then((response) => response.value);
  },

  listVideoSkills(filters: {
    category?: string;
    cursor?: string;
    limit?: number;
  } = {}): Promise<VideoSkillCatalogResponseV2> {
    const query = new URLSearchParams();
    if (filters.category) query.set("category", filters.category);
    if (filters.cursor) query.set("cursor", filters.cursor);
    if (filters.limit !== undefined) query.set("limit", String(filters.limit));
    const suffix = query.size ? `?${query.toString()}` : "";
    return requestV2(
      `/video-skills${suffix}`,
      {},
      normalizeVideoSkillCatalogResponseV2,
    );
  },

  getVideoSkill(skillId: string): Promise<VideoSkillPublicDetailV2> {
    return requestV2(
      `/video-skills/${encodeURIComponent(skillId)}`,
      {},
      normalizeVideoSkillPublicDetailV2,
    );
  },

  createAgentCanvasVideoSkillRun(
    workflowId: string,
    request: AgentCanvasVideoSkillRunCreateRequestV2,
    idempotencyKey: string,
  ): Promise<AgentCanvasVideoSkillRunV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/skill-runs`,
      {
        method: "POST",
        headers: idempotencyHeaders(idempotencyKey),
        body: JSON.stringify(request),
      },
      normalizeAgentCanvasVideoSkillRunV2,
    );
  },

  runAgentCanvas(
    workflowId: string,
    request: CanvasRunRequestV2,
    idempotencyKey: string,
  ): Promise<CanvasRunAcceptedV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/runs`,
      {
        method: "POST",
        headers: idempotencyHeaders(idempotencyKey),
        body: JSON.stringify(request),
      },
      normalizeCanvasRunAcceptedV2,
    );
  },

  cancelAgentCanvasRun(
    workflowId: string,
    executionId: string,
    request: CanvasRunCancelRequestV2,
  ): Promise<CanvasRunCancelResponseV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(executionId)}/cancel`,
      {
        method: "POST",
        body: JSON.stringify(request),
      },
      normalizeCanvasRunCancelResponseV2,
    );
  },

  agentCanvasRuntime(workflowId: string): Promise<CanvasRuntimeSnapshotV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/runtime`,
      {},
      normalizeCanvasRuntimeSnapshotV2,
    );
  },

  agentCanvasEvents(
    workflowId: string,
    afterSeq = 0,
    limit = 200,
    signal?: AbortSignal,
  ): Promise<CanvasRuntimeEventsResponseV2> {
    const query = new URLSearchParams({
      after_seq: String(afterSeq),
      limit: String(limit),
    });
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/events?${query.toString()}`,
      { signal },
      normalizeCanvasRuntimeEventsResponseV2,
    );
  },

  openAgentCanvasEventStream(workflowId: string, afterSeq = 0): EventSource {
    return new EventSource(
      `${API_V2_BASE}/workflows/${encodeURIComponent(workflowId)}/events/stream?after_seq=${encodeURIComponent(String(afterSeq))}`,
    );
  },

  agentCanvasProviderCapabilities(filters: {
    output_type?: string;
    input_types?: string[];
    include_unavailable?: boolean;
  } = {}): Promise<ProviderModelCapabilityListV2> {
    const query = new URLSearchParams();
    if (filters.output_type) query.set("output_type", filters.output_type);
    if (filters.input_types?.length) query.set("input_types", filters.input_types.join(","));
    if (filters.include_unavailable) query.set("include_unavailable", "true");
    const suffix = query.size ? `?${query.toString()}` : "";
    return requestV2(
      `/provider-models/capabilities${suffix}`,
      {},
      normalizeProviderModelCapabilityListV2,
    );
  },

  exportAgentCanvasEditingNode(
    workflowId: string,
    nodeId: string,
    request: EditingExportRequestV2,
    idempotencyKey: string,
  ): Promise<EditingExportAcceptedV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}/export`,
      {
        method: "POST",
        headers: idempotencyHeaders(idempotencyKey),
        body: JSON.stringify(request),
      },
      normalizeEditingExportAcceptedV2,
    );
  },

  cancelAgentCanvasEditingExport(
    workflowId: string,
    nodeId: string,
    exportId: string,
  ): Promise<EditingExportCancelResponseV2> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}/exports/${encodeURIComponent(exportId)}/cancel`,
      {
        method: "POST",
      },
      normalizeEditingExportCancelResponseV2,
    );
  },

  uploadInputAssets(formData: FormData): Promise<V2InputAssetUploadResponse> {
    return requestV2(`/input-assets/upload`, { method: "POST", body: formData }, normalizeV2InputAssetUploadResponse);
  },

  workflow(workflowId: string): Promise<PersistedWorkflowV2> {
    return requestV2(`/workflows/${encodeURIComponent(workflowId)}`, {}, normalizePersistedWorkflowV2);
  },

  workflowWithEtag(workflowId: string): Promise<V2EtaggedResponse<PersistedWorkflowV2>> {
    return requestV2WithEtag(`/workflows/${encodeURIComponent(workflowId)}`, {}, normalizePersistedWorkflowV2);
  },

  workflowWithEtagWithoutCapture(workflowId: string): Promise<V2EtaggedResponse<PersistedWorkflowV2>> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}`,
      {},
      normalizePersistedWorkflowV2,
      { captureAuthoringEtag: false },
    );
  },

  listProjects(status: ProjectV2Status = "active", limit = 100, cursor?: string | null): Promise<ProjectV2ListResponse> {
    const query = new URLSearchParams({ status, limit: String(limit) });
    if (cursor) query.set("cursor", cursor);
    return requestV2(`/projects?${query.toString()}`, {}, normalizeProjectV2ListResponse);
  },

  projectWithEtag(projectId: string): Promise<V2EtaggedResponse<ProjectV2>> {
    return requestV2WithEtag(`/projects/${encodeURIComponent(projectId)}`, {}, normalizeProjectV2);
  },

  projectWorkflow(projectId: string): Promise<V2EtaggedResponse<PersistedWorkflowV2>> {
    return requestV2WithEtag(`/projects/${encodeURIComponent(projectId)}/workflow`, {}, normalizePersistedWorkflowV2);
  },

  updateProject(projectId: string, request: ProjectV2UpdateRequest): Promise<V2EtaggedResponse<ProjectV2>> {
    return requestV2WithEtag(
      `/projects/${encodeURIComponent(projectId)}`,
      { method: "PATCH", body: JSON.stringify(request) },
      normalizeProjectV2,
    );
  },

  trashProject(projectId: string): Promise<void> {
    return requestV2(`/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" });
  },

  restoreProject(projectId: string): Promise<V2EtaggedResponse<ProjectV2>> {
    return requestV2WithEtag(`/projects/${encodeURIComponent(projectId)}/restore`, { method: "POST" }, normalizeProjectV2);
  },

  workflowRevisions(workflowId: string, limit = 100, cursor?: string | null): Promise<WorkflowRevisionPage> {
    const query = new URLSearchParams({ limit: String(limit) });
    if (cursor) query.set("cursor", cursor);
    return requestV2(`/workflows/${encodeURIComponent(workflowId)}/revisions?${query.toString()}`, {}, normalizeWorkflowRevisionPage);
  },

  workflowRevision(workflowId: string, revisionNo: number): Promise<WorkflowRevisionV2Detail> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/revisions/${revisionNo}`,
      {},
      normalizeWorkflowRevisionV2Detail,
    );
  },

  restoreWorkflowRevision(workflowId: string, revisionNo: number): Promise<V2EtaggedResponse<WorkflowRevisionRestoreResponse>> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}/revisions/${revisionNo}/restore`,
      { method: "POST" },
      normalizeWorkflowRevisionRestoreResponse,
    );
  },

  listAssetLibraryEntities(
    request: V2AssetLibraryListRequest,
    options: { signal?: AbortSignal } = {},
  ): Promise<V2AssetLibraryListResponse> {
    const query = new URLSearchParams({ scope: request.scope });
    if (request.category) query.set("category", request.category);
    if (request.search?.trim()) query.set("search", request.search.trim());
    if (request.cursor) query.set("cursor", request.cursor);
    if (request.limit) query.set("limit", String(request.limit));
    return requestV2(`/asset-library/entities?${query.toString()}`, { signal: options.signal }, normalizeV2AssetLibraryListResponse);
  },

  assetLibraryEntity(entityId: string): Promise<V2AssetLibraryEntityDetail> {
    return requestV2(`/asset-library/entities/${encodeURIComponent(entityId)}`, {}, normalizeV2AssetLibraryEntityDetail);
  },

  createAssetLibraryEntity(request: V2AssetLibraryCreateRequest): Promise<V2AssetLibraryEntityDetail> {
    return requestV2(`/asset-library/entities`, { method: "POST", body: JSON.stringify(request) }, normalizeV2AssetLibraryEntityDetail);
  },

  uploadAssetLibraryEntity(formData: FormData): Promise<V2AssetLibraryEntityDetail> {
    return requestV2(`/asset-library/entities/upload`, { method: "POST", body: formData }, normalizeV2AssetLibraryEntityDetail);
  },

  updateAssetLibraryEntity(entityId: string, request: V2AssetLibraryPatchRequest): Promise<V2AssetLibraryEntityDetail> {
    return requestV2(
      `/asset-library/entities/${encodeURIComponent(entityId)}`,
      { method: "PATCH", body: JSON.stringify(request) },
      normalizeV2AssetLibraryEntityDetail,
    );
  },

  deleteAssetLibraryEntity(entityId: string): Promise<void> {
    return requestV2(`/asset-library/entities/${encodeURIComponent(entityId)}`, { method: "DELETE" });
  },

  restoreAssetLibraryEntity(entityId: string): Promise<V2AssetLibraryEntityDetail> {
    return requestV2(
      `/asset-library/entities/${encodeURIComponent(entityId)}/restore`,
      { method: "POST" },
      normalizeV2AssetLibraryEntityDetail,
    );
  },

  recommendedCatalogStatus(): Promise<V2RecommendedCatalogStatus> {
    return requestV2(`/asset-library/catalogs/recommended/status`, {}, normalizeV2RecommendedCatalogStatus);
  },

  attachReferenceSelections(
    workflowId: string,
    slotId: string,
    request: V2ReferenceSelectionsRequest,
  ): Promise<V2EtaggedResponse<V2ReferenceSelectionsResponse>> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}/slots/${encodeURIComponent(slotId)}/reference-selections`,
      { method: "POST", body: JSON.stringify(request) },
      normalizeV2ReferenceSelectionsResponse,
    );
  },

  removeReferenceBinding(workflowId: string, bindingId: string): Promise<V2EtaggedResponse<V2ReferenceSelectionsResponse>> {
    return requestV2WithEtag(
      `/workflows/${encodeURIComponent(workflowId)}/references/${encodeURIComponent(bindingId)}`,
      { method: "DELETE" },
      normalizeV2ReferenceSelectionsResponse,
    );
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

  script(workflowId: string): Promise<V2ScriptReadResponse> {
    return requestV2(`/workflows/${encodeURIComponent(workflowId)}/script`, {}, normalizeV2ScriptReadResponse);
  },

  confirmScript(workflowId: string, request: V2ScriptConfirmRequest): Promise<V2ScriptConfirmResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/script/confirm`,
      { method: "POST", body: JSON.stringify(request) },
      normalizeV2ScriptConfirmResponse,
    );
  },

  scriptVersions(workflowId: string): Promise<V2ScriptVersionListResponse> {
    return requestV2(`/workflows/${encodeURIComponent(workflowId)}/script/versions`, {}, normalizeV2ScriptVersionListResponse);
  },

  selectScriptVersion(
    workflowId: string,
    versionId: string,
    request: V2ScriptSelectVersionRequest,
  ): Promise<V2ScriptSelectVersionResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/script/versions/${encodeURIComponent(versionId)}/select`,
      { method: "POST", body: JSON.stringify(request) },
      normalizeV2ScriptSelectVersionResponse,
    );
  },

  async events(workflowId: string, afterSeq = 0, signal?: AbortSignal): Promise<{ events: WorkflowRuntimeEventV2[]; next_after_seq: number }> {
    return requestV2(`/workflows/${encodeURIComponent(workflowId)}/events?after_seq=${encodeURIComponent(String(afterSeq))}`, { signal }, (value) => {
      const record = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
      const events = Array.isArray(record.events) ? record.events.map(normalizeWorkflowRuntimeEventV2) : [];
      const next = typeof record.next_after_seq === "number" ? record.next_after_seq : events.at(-1)?.seq ?? afterSeq;
      return { events, next_after_seq: next };
    });
  },

  openEventStream(workflowId: string, afterSeq = 0): EventSource {
    return new EventSource(`${API_V2_BASE}/workflows/${encodeURIComponent(workflowId)}/events/stream?after_seq=${encodeURIComponent(String(afterSeq))}`);
  },

  listWorkflowAssets(
    workflowId: string,
    filters: V2WorkflowAssetFilters = {},
    options: { signal?: AbortSignal } = {},
  ): Promise<WorkflowAssetListResponseV2> {
    const query = v2WorkflowAssetFilterQuery(filters);
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/assets${query}`,
      { signal: options.signal },
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
    return requestV2GlobalRun(
      workflowId,
      `/workflows/${encodeURIComponent(workflowId)}/run`,
      { method: "POST", body: JSON.stringify(body) },
      normalizeWorkflowV2RunResponse,
    );
  },

  runWorkflowAsync(workflowId: string, body: V2GlobalRunRequest = { mode: "fill_missing_required_slots" }): Promise<WorkflowV2RunResponse> {
    return requestV2GlobalRun(
      workflowId,
      `/workflows/${encodeURIComponent(workflowId)}/run?wait=false`,
      { method: "POST", body: JSON.stringify(body) },
      normalizeWorkflowV2RunResponse,
    );
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

  getFinalTimeline(workflowId: string): Promise<V2FinalTimelineResponse> {
    return requestV2(`/workflows/${encodeURIComponent(workflowId)}/final-composition/timeline`, {}, normalizeV2FinalTimelineResponse);
  },

  saveFinalTimeline(workflowId: string, body: V2FinalTimelineUpdateRequest): Promise<V2FinalTimelineUpdateResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/final-composition/timeline`,
      { method: "PATCH", body: JSON.stringify(body) },
      normalizeV2FinalTimelineUpdateResponse,
    );
  },

  importFinalTimelineSource(workflowId: string, body: V2FinalTimelineSourceImportRequest): Promise<V2FinalTimelineSourceImportResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/final-composition/timeline/sources`,
      { method: "POST", body: JSON.stringify(body) },
      normalizeV2FinalTimelineSourceImportResponse,
    );
  },

  renderFinalTimeline(workflowId: string, body: V2FinalTimelineRenderRequest): Promise<V2FinalTimelineRenderStartResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/final-composition/render`,
      { method: "POST", body: JSON.stringify(body) },
      normalizeV2FinalTimelineRenderStartResponse,
    );
  },

  getFinalTimelineRender(workflowId: string, renderId: string): Promise<V2FinalTimelineRenderStateResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/final-composition/renders/${encodeURIComponent(renderId)}`,
      {},
      normalizeV2FinalTimelineRenderStateResponse,
    );
  },

  cancelFinalTimelineRender(workflowId: string, renderId: string): Promise<V2FinalTimelineRenderStateResponse> {
    return requestV2(
      `/workflows/${encodeURIComponent(workflowId)}/final-composition/renders/${encodeURIComponent(renderId)}/cancel`,
      { method: "POST" },
      normalizeV2FinalTimelineRenderStateResponse,
    );
  },
};

function normalizeWorkflowV2PlanFromChatResponse(value: unknown): V2PlanFromChatResponse {
  const record = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    front_desk: (record.front_desk ?? {}) as V2PlanFromChatResponse["front_desk"],
    workflow: record.workflow ? normalizeWorkflowV2(record.workflow) : null,
    project_id: typeof record.project_id === "string" ? record.project_id : null,
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
