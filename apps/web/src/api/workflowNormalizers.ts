import type {
  AssetBinding,
  AssetFlowDebug,
  AssetLibraryEntityDetail,
  AssetLibraryEntitySummary,
  AssetLibraryListResponse,
  AssetLibraryUploadKind,
  AssetLineage,
  AssetUploadBatchResponse,
  AssetUploadOptions,
  IdentityCertificationIssue,
  IdentityCertificationMetadata,
  MarkStaleResponse,
  MediaStatus,
  NodeRunResult,
  PromptOptimizerMetadata,
  ProviderAttempt,
  ProviderReferencePlan,
  ProviderStrategyDebug,
  QualityReviewIssue,
  QualityReviewResponse,
  QualityReviewSummary,
  ResolvedNodeInputs,
  UploadedAsset,
  WorkflowExecutionNodeState,
  WorkflowExecutionState,
  WorkflowGraph,
  WorkflowLockResponse,
  WorkflowNode,
  WorkflowNodeDeleteResponse,
  WorkflowNodeMutationResponse,
  WorkflowRunResponse,
} from "../types";
import { dedupeAssets, workflowEdgeMappingOrDefault } from "../workflowShared.ts";

const PUBLIC_MEDIA_PREFIX = "/media";
const EXTERNAL_URL_PATTERN = /^(https?:\/\/|data:|blob:)/i;
const BACKEND_UPLOAD_ROLES = ["product", "character", "scene", "reference"] as const;
const PROMPT_TARGETS = ["script", "product-generation", "character-generation", "scene-generation", "storyboard", "storyboard-video-generation"] as const;
export const ASSET_LIBRARY_UPLOAD_EVENT = "asset-library:uploaded";

export type AssetLibraryRefreshEventDetail = Partial<UploadedAsset> & {
  event_type?: string;
  workflow_id?: string | null;
  node_id?: string | null;
  library_entity_id?: string | null;
  library_asset_id?: string | null;
  library_asset_ids?: string[];
  library_state?: string | null;
  library_error?: string | null;
  source_type?: string | null;
};

type BackendUploadRole = (typeof BACKEND_UPLOAD_ROLES)[number];
type PromptTarget = (typeof PROMPT_TARGETS)[number];
type GraphBacked<T> = T & { graph?: WorkflowGraph };

export function buildMediaUrl(path?: string | null, apiBaseUrl = "") {
  if (!path) return "";
  const value = path.trim();
  if (!value) return "";
  if (EXTERNAL_URL_PATTERN.test(value)) return value;

  const withoutLegacyApiPrefix = value.replace(/^\/?api\/v\d+\/media\//i, "");
  const withoutMediaPrefix = withoutLegacyApiPrefix.replace(/^\/?media\//i, "");
  const publicPath = `${PUBLIC_MEDIA_PREFIX}/${withoutMediaPrefix.replace(/^\/+/, "")}`;
  return absoluteMediaUrl(publicPath, apiBaseUrl);
}

export function backendGraphToNodeMutation(value: unknown, nodeId: string): GraphBacked<WorkflowNodeMutationResponse> {
  if (isWorkflowGraphLike(value)) {
    const node = findGraphNode(value, nodeId) ?? fallbackNode(nodeId);
    return {
      node,
      affected_downstream_nodes: normalizeNodeIdArray(value.affected_downstream_nodes),
      workflow_version: toNumber(value.version),
      graph: normalizeWorkflowGraph(value),
    };
  }

  if (isRecord(value)) {
    const node = isRecord(value.node) ? (value.node as unknown as WorkflowNode) : fallbackNode(nodeId);
    return {
      ...(value as unknown as WorkflowNodeMutationResponse),
      node: normalizeWorkflowNode(node),
      affected_downstream_nodes: normalizeOptionalNodeIdArray(value.affected_downstream_nodes),
      workflow_version: toNumber(value.workflow_version),
      graph: isWorkflowGraphLike(value.graph) ? normalizeWorkflowGraph(value.graph) : undefined,
    };
  }

  return { node: fallbackNode(nodeId) };
}

export function backendGraphToNodeDeleteResponse(value: unknown, nodeId: string): GraphBacked<WorkflowNodeDeleteResponse> {
  if (isWorkflowGraphLike(value)) {
    return {
      deleted_node_id: nodeId,
      deleted_edge_ids: [],
      affected_downstream_nodes: normalizeNodeIdArray(value.affected_downstream_nodes),
      workflow_version: toNumber(value.version),
      graph: normalizeWorkflowGraph(value),
    };
  }

  if (isRecord(value)) {
    return {
      ...(value as unknown as WorkflowNodeDeleteResponse),
      deleted_node_id: typeof value.deleted_node_id === "string" ? value.deleted_node_id : nodeId,
      deleted_edge_ids: normalizeOptionalNodeIdArray(value.deleted_edge_ids),
      affected_downstream_nodes: normalizeOptionalNodeIdArray(value.affected_downstream_nodes),
      workflow_version: toNumber(value.workflow_version),
      graph: isWorkflowGraphLike(value.graph) ? normalizeWorkflowGraph(value.graph) : undefined,
    };
  }

  return { deleted_node_id: nodeId, deleted_edge_ids: [] };
}

export function backendGraphToLockResponse(value: unknown, nodeId: string): GraphBacked<WorkflowLockResponse> {
  if (isWorkflowGraphLike(value)) {
    const node = findGraphNode(value, nodeId);
    return {
      node_id: nodeId,
      locked: Boolean(node?.locked),
      workflow_version: toNumber(value.version),
      graph: normalizeWorkflowGraph(value),
    };
  }

  if (isRecord(value)) {
    return {
      ...(value as unknown as WorkflowLockResponse),
      node_id: typeof value.node_id === "string" ? value.node_id : nodeId,
      locked: Boolean(value.locked),
      workflow_version: toNumber(value.workflow_version),
      graph: isWorkflowGraphLike(value.graph) ? normalizeWorkflowGraph(value.graph) : undefined,
    };
  }

  return { node_id: nodeId, locked: false };
}

export function backendGraphToStaleResponse(value: unknown): GraphBacked<MarkStaleResponse> {
  if (isWorkflowGraphLike(value)) {
    return {
      stale_nodes: value.nodes
        .filter((node) => Boolean(node.stale))
        .map((node) => node.id)
        .filter(Boolean),
      graph: normalizeWorkflowGraph(value),
    };
  }

  if (isRecord(value)) {
    return {
      ...(value as unknown as MarkStaleResponse),
      stale_nodes: normalizeNodeIdArray(value.stale_nodes),
      graph: isWorkflowGraphLike(value.graph) ? normalizeWorkflowGraph(value.graph) : undefined,
    };
  }

  return { stale_nodes: [] };
}

export function normalizeWorkflowGraph(value: WorkflowGraph): WorkflowGraph {
  const affectedDownstreamNodes = normalizeOptionalNodeIdArray(value.affected_downstream_nodes);
  return {
    ...value,
    nodes: Array.isArray(value.nodes) ? value.nodes.map(normalizeWorkflowNode) : [],
    ...(Array.isArray(value.edges) ? { edges: value.edges.map(normalizeWorkflowEdge) } : {}),
    ...(affectedDownstreamNodes ? { affected_downstream_nodes: affectedDownstreamNodes } : {}),
  };
}

function normalizeWorkflowEdge(value: WorkflowGraph["edges"][number]) {
  const record = value as WorkflowGraph["edges"][number] & {
    sourceHandle?: unknown;
    targetHandle?: unknown;
  };
  const { sourceHandle, targetHandle, ...rest } = record;
  const normalizedSourceHandle = firstString(record.source_handle, sourceHandle);
  const normalizedTargetHandle = firstString(record.target_handle, targetHandle);
  const normalized = {
    ...rest,
    ...(normalizedSourceHandle ? { source_handle: normalizedSourceHandle } : {}),
    ...(normalizedTargetHandle ? { target_handle: normalizedTargetHandle } : {}),
  };
  return {
    ...normalized,
    mapping: workflowEdgeMappingOrDefault(normalized),
  };
}

export function normalizeWorkflowNode(value: WorkflowNode): WorkflowNode {
  const output = normalizeNodeOutput(value.output);
  const inputAssets = normalizeAssetList(value.input_assets);
  const outputAssets = normalizeAssetList(value.output_assets ?? output?.output_assets ?? output?.assets);
  return {
    ...value,
    ...(output ? { output } : {}),
    ...(inputAssets ? { input_assets: inputAssets } : {}),
    ...(outputAssets ? { output_assets: outputAssets } : {}),
  };
}

export function normalizeNodeRunResult(value: NodeRunResult): NodeRunResult {
  const record = value as NodeRunResult & Record<string, unknown>;
  const providerStrategy = normalizeProviderStrategyDebug(record.provider_strategy);
  const metadata = isRecord(record.metadata) ? (record.metadata as Record<string, unknown>) : undefined;
  const identityCertification = normalizeIdentityCertification(record.identity_certification ?? metadata?.identity_certification);
  const optimizerMetadata = mergePromptOptimizerMetadata(
    record.optimizer_metadata,
    metadata?.optimizer_metadata,
    record.resolved_input_context,
    metadata,
    record.output,
  );
  const output = normalizeNodeOutput(record.output);
  const outputAssets = normalizeAssetList(value.output_assets ?? output?.output_assets ?? output?.assets);
  const assetBindings = normalizeAssetBindings(record.asset_bindings ?? metadata?.asset_bindings ?? output?.asset_bindings);
  const providerReferencePlan = normalizeProviderReferencePlan(record.provider_reference_plan ?? metadata?.provider_reference_plan ?? output?.provider_reference_plan);
  const assetFlowDebug = normalizeAssetFlowDebug(record.asset_flow_debug ?? metadata?.asset_flow_debug ?? output?.asset_flow_debug);
  return {
    ...value,
    ...(output ? { output } : {}),
    ...(metadata ? { metadata } : {}),
    selected_provider: firstString(record.selected_provider) ?? providerStrategy?.selected_provider ?? null,
    provider_strategy: providerStrategy,
    provider_attempts: normalizeProviderAttempts(record.provider_attempts),
    fallback_warnings: normalizeFallbackWarnings(record.fallback_warnings),
    failure_stage: firstString(record.failure_stage, metadata?.failure_stage, output?.failure_stage),
    user_explainable_reason: firstString(record.user_explainable_reason, metadata?.user_explainable_reason, output?.user_explainable_reason) ?? null,
    ...(assetBindings ? { asset_bindings: assetBindings } : {}),
    ...(providerReferencePlan ? { provider_reference_plan: providerReferencePlan } : {}),
    ...(assetFlowDebug ? { asset_flow_debug: assetFlowDebug } : {}),
    ...(optimizerMetadata ? { optimizer_metadata: optimizerMetadata } : {}),
    identity_certification: identityCertification,
    input_assets: normalizeAssetList(value.input_assets),
    output_assets: outputAssets,
    resolved_input_assets: normalizeAssetList(value.resolved_input_assets),
    materialized_assets: normalizeAssetList(value.materialized_assets),
    stale_upstream_nodes: normalizeOptionalNodeIdArray(value.stale_upstream_nodes),
    locked_upstream_nodes: normalizeOptionalNodeIdArray(value.locked_upstream_nodes),
  };
}

export function normalizeResolvedNodeInputs(value: unknown): ResolvedNodeInputs {
  if (!isRecord(value)) return {};
  const providerStrategy = normalizeProviderStrategyDebug(value.provider_strategy);
  const optimizerMetadata = mergePromptOptimizerMetadata(value.optimizer_metadata, value.resolved_input_context, value);
  const assetBindings = normalizeAssetBindings(value.asset_bindings);
  const providerReferencePlan = normalizeProviderReferencePlan(value.provider_reference_plan);
  const assetFlowDebug = normalizeAssetFlowDebug(value.asset_flow_debug);
  return {
    ...(value as ResolvedNodeInputs),
    selected_provider: firstString(value.selected_provider) ?? providerStrategy?.selected_provider ?? null,
    provider_strategy: providerStrategy,
    provider_attempts: normalizeProviderAttempts(value.provider_attempts),
    fallback_warnings: normalizeFallbackWarnings(value.fallback_warnings),
    failure_stage: firstString(value.failure_stage),
    user_explainable_reason: firstString(value.user_explainable_reason) ?? null,
    ...(assetBindings ? { asset_bindings: assetBindings } : {}),
    ...(providerReferencePlan ? { provider_reference_plan: providerReferencePlan } : {}),
    ...(assetFlowDebug ? { asset_flow_debug: assetFlowDebug } : {}),
    ...(optimizerMetadata ? { optimizer_metadata: optimizerMetadata } : {}),
    identity_certification: normalizeIdentityCertification(value.identity_certification),
    resolved_input_assets: normalizeAssetList(value.resolved_input_assets),
    materialized_assets: normalizeAssetList(value.materialized_assets),
    stale_upstream_nodes: normalizeOptionalNodeIdArray(value.stale_upstream_nodes),
    locked_upstream_nodes: normalizeOptionalNodeIdArray(value.locked_upstream_nodes),
  };
}

export function normalizeWorkflowRunResponse(value: unknown): WorkflowRunResponse {
  if (!isRecord(value)) return {};
  const mediaStatus = isRecord(value.media_status) ? normalizeMediaStatus(value.media_status) : value.media_status;
  const finalVideo = normalizeMediaRecord(value.final_video);
  const graph = isWorkflowGraphLike(value.graph) ? normalizeWorkflowGraph(value.graph) : value.graph;
  const execution = isRecord(value.execution) ? normalizeWorkflowExecutionState(value) : null;
  const executionNodes = normalizeWorkflowExecutionNodes(value.nodes ?? value.execution_nodes ?? value.node_states ?? execution?.nodes);
  return {
    ...(value as WorkflowRunResponse),
    executed_nodes: normalizeOptionalNodeIdArray(value.executed_nodes),
    skipped_nodes: normalizeOptionalNodeIdArray(value.skipped_nodes),
    stale_nodes: normalizeOptionalNodeIdArray(value.stale_nodes),
    failed_nodes: normalizeOptionalNodeIdArray(value.failed_nodes),
    frontier_node_id: nodeIdFromUnknown(value.frontier_node_id) ?? null,
    selected_node_ids: normalizeOptionalExecutionNodeIdArray(value.selected_node_ids ?? execution?.selected_node_ids),
    queued_node_ids: normalizeOptionalExecutionNodeIdArray(value.queued_node_ids ?? execution?.queued_node_ids),
    waiting_node_ids: normalizeOptionalExecutionNodeIdArray(value.waiting_node_ids ?? execution?.waiting_node_ids),
    executed_node_ids: normalizeOptionalNodeIdArray(value.executed_node_ids ?? value.executed_nodes),
    skipped_node_ids: normalizeOptionalNodeIdArray(value.skipped_node_ids ?? value.skipped_nodes),
    failed_node_id: nodeIdFromUnknown(value.failed_node_id) ?? null,
    running_node_ids: normalizeOptionalExecutionNodeIdArray(value.running_node_ids ?? execution?.running_node_ids),
    completed_node_ids: normalizeOptionalExecutionNodeIdArray(value.completed_node_ids ?? execution?.completed_node_ids ?? value.executed_node_ids ?? value.executed_nodes),
    failed_node_ids: normalizeOptionalExecutionNodeIdArray(value.failed_node_ids ?? execution?.failed_node_ids ?? value.failed_nodes),
    execution,
    ...(executionNodes ? { nodes: executionNodes } : {}),
    ...(graph ? { graph: graph as WorkflowRunResponse["graph"] } : {}),
    media_status: mediaStatus as WorkflowRunResponse["media_status"],
    final_video: finalVideo ?? (value.final_video as WorkflowRunResponse["final_video"]),
  };
}

export function normalizeWorkflowExecutionState(value: unknown): WorkflowExecutionState | null {
  if (!isRecord(value)) return null;
  const executionRecord = isRecord(value.execution) ? value.execution : value;
  const executionId = firstString(value.execution_id, executionRecord.execution_id, executionRecord.id, value.id);
  if (!executionId) return null;
  const nodes = normalizeWorkflowExecutionNodes(executionRecord.nodes ?? value.nodes ?? executionRecord.execution_nodes ?? value.execution_nodes ?? executionRecord.node_states ?? value.node_states) ?? [];
  const nodeIdsByStatus = executionNodeIdsByStatus(nodes);
  return {
    ...(executionRecord as unknown as WorkflowExecutionState),
    ...(value as unknown as WorkflowExecutionState),
    workflow_id: firstString(value.workflow_id, executionRecord.workflow_id),
    execution_id: executionId,
    status: toStringValue(value.status) ?? toStringValue(executionRecord.status),
    request: isRecord(executionRecord.request) ? executionRecord.request : isRecord(value.request) ? value.request : undefined,
    mode: firstString(value.mode, executionRecord.mode),
    frontier_node_id: nodeIdFromUnknown(value.frontier_node_id ?? executionRecord.frontier_node_id) ?? null,
    nodes,
    selected_node_ids: normalizeOptionalExecutionNodeIdArray(value.selected_node_ids ?? executionRecord.selected_node_ids) ?? selectedExecutionNodeIds(nodes),
    queued_node_ids: normalizeOptionalExecutionNodeIdArray(value.queued_node_ids ?? executionRecord.queued_node_ids) ?? nodeIdsByStatus.queued,
    running_node_ids: normalizeOptionalExecutionNodeIdArray(value.running_node_ids ?? executionRecord.running_node_ids) ?? nodeIdsByStatus.running,
    waiting_node_ids: normalizeOptionalExecutionNodeIdArray(value.waiting_node_ids ?? executionRecord.waiting_node_ids) ?? nodeIdsByStatus.waiting,
    completed_node_ids: normalizeOptionalExecutionNodeIdArray(value.completed_node_ids ?? executionRecord.completed_node_ids) ?? nodeIdsByStatus.completed,
    failed_node_ids: normalizeOptionalExecutionNodeIdArray(value.failed_node_ids ?? executionRecord.failed_node_ids) ?? nodeIdsByStatus.failed,
    skipped_node_ids: normalizeOptionalExecutionNodeIdArray(value.skipped_node_ids ?? executionRecord.skipped_node_ids) ?? nodeIdsByStatus.skipped,
    started_at: firstString(value.started_at, executionRecord.started_at) ?? null,
    finished_at: firstString(value.finished_at, executionRecord.finished_at) ?? null,
    final_result: isRecord(executionRecord.final_result)
      ? normalizeWorkflowRunResponse(executionRecord.final_result)
      : isRecord(value.final_result)
        ? normalizeWorkflowRunResponse(value.final_result)
        : null,
    error: firstString(value.error, executionRecord.error) ?? null,
  };
}

export function normalizeMediaStatus(value: unknown): MediaStatus {
  if (!isRecord(value)) return {};

  const rawSegments = Array.isArray(value.segments) ? value.segments : [];
  const segments = rawSegments
    .map((segment) => normalizeMediaRecord(segment))
    .filter((segment): segment is Record<string, unknown> => Boolean(segment));
  const finalVideo = normalizeMediaRecord(value.final_video);
  const readySegments = toNumber(value.ready_segment_count) ?? toNumber(value.ready_segments) ?? countReadySegments(segments);
  const totalSegments = toNumber(value.total_segment_count) ?? toNumber(value.total_segments) ?? segments.length;
  const allReady = toBoolean(value.all_ready) ?? toBoolean(value.segments_ready) ?? toBoolean(value.all_segments_ready) ?? (totalSegments > 0 && readySegments >= totalSegments);
  const status =
    toStringValue(value.status) ??
    toStringValue(value.final_composition_status) ??
    (isRecord(value.final_video) ? toStringValue(value.final_video.status) : undefined) ??
    toStringValue(value.storyboard_video_status) ??
    undefined;

  return {
    ...(value as MediaStatus),
    status,
    final_video: finalVideo as MediaStatus["final_video"],
    segments,
    segments_ready: toBoolean(value.segments_ready),
    ready_segment_count: toNumber(value.ready_segment_count),
    total_segment_count: toNumber(value.total_segment_count),
    ready_segments: readySegments,
    total_segments: totalSegments,
    all_ready: allReady,
  };
}

export function normalizeUploadedAsset(value: unknown, fallbackId = "asset", fallbackType: UploadedAsset["asset_type"] = "image"): UploadedAsset | null {
  if (typeof value === "string") {
    return {
      asset_id: fallbackId,
      asset_type: normalizeAssetType(undefined, fallbackType, value),
      asset_role: "reference",
      filename: filenameFromPath(value) || fallbackId,
      mime_type: "",
      local_path: value,
      public_url: buildMediaUrl(value),
    };
  }
  if (!isRecord(value)) return null;

  const metadata = isRecord(value.metadata) ? value.metadata : {};
  const uri = firstString(value.uri, metadata.uri);
  const localPath = firstString(value.local_path, metadata.local_path, value.path, metadata.path, uri, value.public_url, metadata.public_url, value.url, metadata.url, value.remote_url, metadata.remote_url);
  const url = firstString(value.url, metadata.url, value.public_url, metadata.public_url);
  const remoteUrl = firstString(value.remote_url, metadata.remote_url);
  const publicUrl = firstString(value.public_url, metadata.public_url) ?? (localPath ? buildMediaUrl(localPath) : undefined);
  const id = firstString(value.asset_id, value.library_asset_id, value.id) ?? fallbackId;
  const assetState = firstString(value.asset_state, metadata.asset_state);
  const assetVisibility = firstString(value.asset_visibility, metadata.asset_visibility);
  const assetOrigin = firstString(value.asset_origin, metadata.asset_origin);
  const lineage = normalizeAssetLineage(value.lineage ?? metadata.lineage);
  const mediaType = firstString(value.media_type, metadata.media_type, value.asset_type, value.type);
  if (!localPath && !url && !publicUrl && assetState !== "deleted_missing_file") return null;
  const libraryAssetIds = stringArray(value.library_asset_ids)
    ?? (firstString(value.library_asset_id, metadata.library_asset_id) ? [firstString(value.library_asset_id, metadata.library_asset_id)!] : undefined);
  const libraryAssetId = firstString(value.library_asset_id, metadata.library_asset_id);
  const libraryState = firstString(value.library_state, metadata.library_state);
  const libraryError = firstString(value.library_error, value.library_ingest_error, metadata.library_error, metadata.library_ingest_error);
  const sourceType = firstString(value.source_type, metadata.source_type);
  const libraryAssets = Array.isArray(value.library_assets)
    ? value.library_assets
        .map((asset, index) => normalizeUploadedAsset(asset, `library-asset-${index + 1}`))
        .filter((asset): asset is UploadedAsset => Boolean(asset))
    : undefined;

  return {
    ...(value as unknown as UploadedAsset),
    asset_id: id,
    asset_type: normalizeAssetType(value.asset_type ?? value.type ?? value.media_type, fallbackType, localPath ?? url ?? publicUrl),
    media_type: mediaType,
    asset_role: normalizeAssetRole(value.asset_role),
    filename: firstString(value.filename, value.name) ?? filenameFromPath(localPath ?? url ?? publicUrl ?? "") ?? id,
    mime_type: firstString(value.mime_type, value.content_type) ?? "",
    local_path: localPath ?? url ?? publicUrl ?? "",
    uri,
    url,
    remote_url: remoteUrl,
    public_url: publicUrl,
    thumbnail_path: firstString(value.thumbnail_path, metadata.thumbnail_path),
    thumbnail_url: firstString(value.thumbnail_url, metadata.thumbnail_url),
    poster_path: firstString(value.poster_path, metadata.poster_path),
    poster_url: firstString(value.poster_url, metadata.poster_url),
    preview_path: firstString(value.preview_path, metadata.preview_path),
    preview_url: firstString(value.preview_url, metadata.preview_url),
    semantic_type: firstString(value.semantic_type, metadata.semantic_type),
    entity_id: firstString(value.entity_id, value.source_entity_id, metadata.entity_id, metadata.source_entity_id),
    library_entity_id: firstString(value.library_entity_id, metadata.library_entity_id),
    ...(libraryAssetId ? { library_asset_id: libraryAssetId } : {}),
    ...(libraryState ? { library_state: libraryState } : {}),
    ...(libraryError ? { library_error: libraryError } : {}),
    ...(sourceType ? { source_type: sourceType } : {}),
    ...(assetState ? { asset_state: assetState } : {}),
    ...(assetVisibility ? { asset_visibility: assetVisibility } : {}),
    ...(assetOrigin ? { asset_origin: assetOrigin } : {}),
    ...(lineage ? { lineage } : {}),
    ...(Object.keys(metadata).length ? { metadata } : {}),
    ...(libraryAssetIds ? { library_asset_ids: libraryAssetIds } : {}),
    ...(isRecord(value.library_entity) ? { library_entity: value.library_entity as unknown as UploadedAsset["library_entity"] } : {}),
    ...(libraryAssets ? { library_assets: libraryAssets } : {}),
    ...(normalizeQualityReviewStatus(value.quality_status ?? metadata.quality_status) ? { quality_status: normalizeQualityReviewStatus(value.quality_status ?? metadata.quality_status) } : {}),
    ...(value.quality_score !== undefined || metadata.quality_score !== undefined ? { quality_score: toNumber(value.quality_score) ?? toNumber(metadata.quality_score) ?? null } : {}),
    ...(value.quality_issues !== undefined || metadata.quality_issues !== undefined ? { quality_issues: normalizeQualityReviewIssues(value.quality_issues ?? metadata.quality_issues) } : {}),
    ...(value.quality_warnings !== undefined || metadata.quality_warnings !== undefined ? { quality_warnings: normalizeQualityReviewIssues(value.quality_warnings ?? metadata.quality_warnings) } : {}),
    ...(value.reviewer !== undefined || metadata.reviewer !== undefined ? { reviewer: firstString(value.reviewer, metadata.reviewer) ?? null } : {}),
  };
}

export function normalizeAssetList(value: unknown): UploadedAsset[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return dedupeAssets(value
    .map((asset, index) => normalizeUploadedAsset(asset, `asset-${index + 1}`))
    .filter((asset): asset is UploadedAsset => Boolean(asset)));
}

function normalizeAssetLineage(value: unknown): AssetLineage | undefined {
  if (!isRecord(value)) return undefined;
  const lineage: AssetLineage = {
    ...(value as AssetLineage),
    workflow_id: firstString(value.workflow_id) ?? null,
    node_id: firstString(value.node_id) ?? null,
    node_run_id: firstString(value.node_run_id, value.run_id) ?? null,
    revision_id: firstString(value.revision_id) ?? null,
    working_version_id: firstString(value.working_version_id, value.version_id) ?? null,
    provider: firstString(value.provider) ?? null,
    provider_model: firstString(value.provider_model, value.model_id, value.model) ?? null,
  };
  const sourceAssetIds = stringArray(value.source_asset_ids);
  const sourceEntityIds = stringArray(value.source_entity_ids);
  const createdFromBindingIds = stringArray(value.created_from_binding_ids);
  if (sourceAssetIds) lineage.source_asset_ids = sourceAssetIds;
  if (sourceEntityIds) lineage.source_entity_ids = sourceEntityIds;
  if (createdFromBindingIds) lineage.created_from_binding_ids = createdFromBindingIds;
  return Object.values(lineage).some((item) => item !== undefined && item !== null && (!Array.isArray(item) || item.length > 0)) ? lineage : undefined;
}

function normalizeAssetBindings(value: unknown): AssetBinding[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const bindings = value
    .map(normalizeAssetBinding)
    .filter((binding): binding is AssetBinding => Boolean(binding));
  return bindings.length ? bindings : undefined;
}

function normalizeAssetBinding(value: unknown): AssetBinding | null {
  if (!isRecord(value)) return null;
  const metadata = isRecord(value.metadata) ? value.metadata : undefined;
  const binding: AssetBinding = {
    ...(value as AssetBinding),
    binding_id: firstString(value.binding_id, value.id) ?? null,
    asset_id: firstString(value.asset_id) ?? null,
    entity_id: firstString(value.entity_id, value.library_entity_id) ?? null,
    scope_type: firstString(value.scope_type, value.scope) ?? undefined,
    scope_id: firstString(value.scope_id, value.target_node_id, value.target_entity_id, value.target_shot_id) ?? null,
    role: firstString(value.role, value.binding_role) ?? null,
    media_type: firstString(value.media_type, value.asset_type) ?? null,
    use_as_prompt: toBoolean(value.use_as_prompt) ?? null,
    reference_mode: firstString(value.reference_mode) ?? null,
    lock_identity: toBoolean(value.lock_identity) ?? null,
    binding_source: firstString(value.binding_source, value.source) ?? null,
    priority: toNumber(value.priority) ?? null,
    ...(metadata ? { metadata } : {}),
  };
  return Object.values(binding).some((item) => item !== undefined && item !== null && (!Array.isArray(item) || item.length > 0)) ? binding : null;
}

function normalizeProviderReferencePlan(value: unknown): ProviderReferencePlan | undefined {
  if (!isRecord(value)) return undefined;
  const plan: ProviderReferencePlan = {
    ...(value as ProviderReferencePlan),
    provider: firstString(value.provider, value.selected_provider) ?? null,
    node_type: firstString(value.node_type) ?? null,
    media_type: firstString(value.media_type, value.asset_type) ?? null,
  };
  return Object.values(plan).some((item) => item !== undefined && item !== null && (!Array.isArray(item) || item.length > 0)) ? plan : undefined;
}

function normalizeAssetFlowDebug(value: unknown): AssetFlowDebug | undefined {
  if (!isRecord(value)) return undefined;
  const debug: AssetFlowDebug = {
    ...(value as AssetFlowDebug),
    input_reference_count: toNumber(value.input_reference_count) ?? null,
    display_asset_count: toNumber(value.display_asset_count) ?? null,
    prompt_context_asset_count: toNumber(value.prompt_context_asset_count) ?? null,
    provider_reference_asset_count: toNumber(value.provider_reference_asset_count) ?? null,
    prompt_only_asset_count: toNumber(value.prompt_only_asset_count) ?? null,
    rejected_reference_count: toNumber(value.rejected_reference_count) ?? null,
    provider_attempt_count: toNumber(value.provider_attempt_count) ?? null,
    selected_provider: firstString(value.selected_provider, value.provider) ?? null,
    failure_stage: firstString(value.failure_stage) ?? undefined,
    user_explainable_reason: firstString(value.user_explainable_reason, value.reason) ?? null,
  };
  return Object.values(debug).some((item) => item !== undefined && item !== null && (!Array.isArray(item) || item.length > 0)) ? debug : undefined;
}

export function normalizeAssetLibraryListResponse(value: unknown): AssetLibraryListResponse {
  if (!isRecord(value)) return { entities: [] };
  const rawEntities = Array.isArray(value.entities)
    ? value.entities
    : Array.isArray(value.items)
      ? value.items
      : Array.isArray(value.results)
        ? value.results
        : [];
  return {
    ...(value as unknown as AssetLibraryListResponse),
    entities: rawEntities.map(normalizeAssetLibrarySummary).filter((entity): entity is AssetLibraryEntitySummary => Boolean(entity?.entity_id)),
  };
}

export function normalizeAssetLibrarySummary(value: unknown): AssetLibraryEntitySummary {
  const record = isRecord(value) ? value : {};
  const assets = normalizeAssetList(record.assets) ?? [];
  const assetIds = stringArray(record.asset_ids) ?? assets.map((asset) => asset.asset_id).filter(Boolean);
  const previewAsset = normalizeUploadedAsset(record.preview_asset, "preview-asset") ?? assets[0] ?? null;
  const previewUrl = firstString(record.preview_url, record.thumbnail_url, previewAsset?.preview_url, previewAsset?.thumbnail_url, previewAsset?.public_url, previewAsset?.local_path) ?? null;
  const entityId = firstString(record.entity_id, record.id) ?? "";
  return {
    ...(record as unknown as AssetLibraryEntitySummary),
    entity_id: entityId,
    entity_type: (firstString(record.entity_type, record.type) ?? "uploaded_reference") as AssetLibraryEntitySummary["entity_type"],
    semantic_type: firstString(record.semantic_type) ?? null,
    display_name: firstString(record.display_name, record.name, record.title) ?? entityId,
    description: firstString(record.description) ?? null,
    tags: Array.isArray(record.tags) ? record.tags.filter((tag): tag is string => typeof tag === "string") : [],
    reuse_policy: firstString(record.reuse_policy) ?? null,
    source_workflow_id: firstString(record.source_workflow_id) ?? null,
    source_node_id: firstString(record.source_node_id) ?? null,
    source_entity_id: firstString(record.source_entity_id) ?? null,
    asset_ids: assetIds,
    assets,
    asset_count: toNumber(record.asset_count) ?? (assetIds.length || assets.length),
    preview_asset: previewAsset,
    preview_url: previewUrl,
    thumbnail_url: firstString(record.thumbnail_url, previewAsset?.thumbnail_url) ?? previewUrl,
    is_archived: toBoolean(record.is_archived) ?? false,
    created_at: firstString(record.created_at),
    updated_at: firstString(record.updated_at),
  };
}

export function normalizeAssetLibraryDetail(value: unknown): AssetLibraryEntityDetail {
  const record = isRecord(value) ? value : {};
  const rawEntity = isRecord(record.entity) ? record.entity : record;
  const rawAssets = Array.isArray(record.assets) ? record.assets : rawEntity.assets;
  const assets = normalizeAssetList(rawAssets) ?? [];
  const summary = normalizeAssetLibrarySummary({
    ...record,
    ...rawEntity,
    asset_ids: record.asset_ids ?? rawEntity.asset_ids,
    assets,
  });
  return {
    ...summary,
    assets,
    metadata: isRecord(rawEntity.metadata) ? rawEntity.metadata : isRecord(record.metadata) ? record.metadata : undefined,
  };
}

function normalizeProviderStrategyDebug(value: unknown): ProviderStrategyDebug | undefined {
  if (!isRecord(value)) return undefined;
  const attempts = normalizeProviderAttempts(value.provider_attempts);
  const fallbackWarnings = normalizeFallbackWarnings(value.fallback_warnings);
  const eligibleProviders = stringArray(value.eligible_providers);
  const rejectedProviders = normalizeProviderMessages(value.rejected_providers);
  const selectedProvider = firstString(value.selected_provider, value.provider);
  const fallbackUsed = toBoolean(value.fallback_used);
  const strategy: ProviderStrategyDebug = {
    ...(selectedProvider ? { selected_provider: selectedProvider } : {}),
    ...(fallbackUsed !== undefined ? { fallback_used: fallbackUsed } : {}),
    selection_reason: firstString(value.selection_reason, value.reason) ?? null,
    reference_mode: firstString(value.reference_mode) ?? null,
    ...(eligibleProviders ? { eligible_providers: eligibleProviders } : {}),
    ...(rejectedProviders ? { rejected_providers: rejectedProviders } : {}),
    ...(attempts ? { provider_attempts: attempts } : {}),
    ...(fallbackWarnings ? { fallback_warnings: fallbackWarnings } : {}),
  };
  return Object.values(strategy).some((item) => item !== undefined && item !== null && (!Array.isArray(item) || item.length > 0)) ? strategy : undefined;
}

function normalizeProviderAttempts(value: unknown): ProviderAttempt[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value
    .map((item, index): ProviderAttempt | null => {
      if (!isRecord(item)) return null;
      return {
        provider: firstString(item.provider, item.provider_name, item.name, item.id) ?? `provider-${index + 1}`,
        status: firstString(item.status) ?? "skipped",
        error_code: firstString(item.error_code, item.code) ?? null,
        error: firstString(item.error, item.message, item.reason) ?? null,
        duration_ms: toNumber(item.duration_ms) ?? null,
      };
    })
    .filter((item): item is ProviderAttempt => Boolean(item));
}

function normalizeFallbackWarnings(value: unknown): Array<string | Record<string, unknown>> | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.map((item) => {
    if (typeof item === "string") return item;
    if (isRecord(item)) return item;
    return String(item);
  });
}

export function normalizePromptOptimizerMetadata(value: unknown): PromptOptimizerMetadata | undefined {
  if (!isRecord(value)) return undefined;
  const optimizerAgent = firstString(value.optimizer_agent, value.optimizerAgent, value.agent);
  const selectedSkillIds = stringArray(value.selected_skill_ids ?? value.selectedSkillIds ?? value.skill_ids);
  const optimizerWarnings = normalizeProviderMessages(value.optimizer_warnings ?? value.optimizerWarnings ?? value.warnings);
  const qualityNotes = normalizeQualityNotes(value.quality_notes ?? value.qualityNotes);
  const metadata: PromptOptimizerMetadata = {
    ...(optimizerAgent ? { optimizer_agent: optimizerAgent } : {}),
    ...(selectedSkillIds ? { selected_skill_ids: selectedSkillIds } : {}),
    ...(optimizerWarnings ? { optimizer_warnings: optimizerWarnings } : {}),
    ...(qualityNotes !== undefined ? { quality_notes: qualityNotes } : {}),
  };
  return Object.values(metadata).some((item) => item !== undefined && item !== null && (!Array.isArray(item) || item.length > 0)) ? metadata : undefined;
}

function mergePromptOptimizerMetadata(...values: unknown[]): PromptOptimizerMetadata | undefined {
  const merged: PromptOptimizerMetadata = {};
  for (const value of values) {
    const metadata = normalizePromptOptimizerMetadata(value);
    if (!metadata) continue;
    if (metadata.optimizer_agent) merged.optimizer_agent = metadata.optimizer_agent;
    if (metadata.selected_skill_ids?.length) merged.selected_skill_ids = metadata.selected_skill_ids;
    if (metadata.optimizer_warnings?.length) merged.optimizer_warnings = metadata.optimizer_warnings;
    if (metadata.quality_notes !== undefined && metadata.quality_notes !== null) merged.quality_notes = metadata.quality_notes;
  }
  return Object.values(merged).some((item) => item !== undefined && item !== null && (!Array.isArray(item) || item.length > 0)) ? merged : undefined;
}

function normalizeQualityNotes(value: unknown): PromptOptimizerMetadata["quality_notes"] | undefined {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (Array.isArray(value)) {
    const items = value.filter((item): item is string => typeof item === "string" && Boolean(item.trim())).map((item) => item.trim());
    return items.length ? items : undefined;
  }
  if (isRecord(value)) return value;
  return undefined;
}

function normalizeProviderMessages(value: unknown): Array<string | Record<string, unknown>> | undefined {
  if (!Array.isArray(value)) return undefined;
  const items = value
    .map((item) => {
      if (typeof item === "string") return item;
      if (isRecord(item)) return item;
      return null;
    })
    .filter((item): item is string | Record<string, unknown> => Boolean(item));
  return items.length ? items : undefined;
}

function normalizeIdentityCertification(value: unknown): IdentityCertificationMetadata | undefined {
  if (!isRecord(value)) return undefined;
  return {
    ...(value as IdentityCertificationMetadata),
    ...(firstString(value.status) ? { status: firstString(value.status) } : {}),
    ...(firstString(value.mode) ? { mode: firstString(value.mode) } : {}),
    provider: firstString(value.provider, value.selected_provider) ?? null,
    model_id: firstString(value.model_id, value.model) ?? null,
    reference_semantic_types: normalizeIdentityCertificationStrings(value.reference_semantic_types, ["semantic_type", "type"]),
    certification_ids: normalizeIdentityCertificationStrings(value.certification_ids, ["certification_id", "certificate_id", "id"]),
    warnings: normalizeIdentityCertificationIssues(value.warnings),
    errors: normalizeIdentityCertificationIssues(value.errors),
  };
}

function normalizeIdentityCertificationStrings(value: unknown, objectKeys: string[]): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item === "string" && item.trim()) return [item.trim()];
    if (!isRecord(item)) return [];
    for (const key of objectKeys) {
      const text = firstString(item[key]);
      if (text) return [text];
    }
    return [];
  });
}

function normalizeIdentityCertificationIssues(value: unknown): IdentityCertificationIssue[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): IdentityCertificationIssue[] => {
    if (typeof item === "string" && item.trim()) return [{ message: item.trim() }];
    if (!isRecord(item)) return [];
    const issue: IdentityCertificationIssue = {
      ...(item as IdentityCertificationIssue),
    };
    const code = firstString(item.code, item.error_code);
    const message = firstString(item.message, item.reason, item.error);
    const assetId = firstString(item.asset_id);
    const entityId = firstString(item.entity_id, item.library_entity_id);
    const semanticType = firstString(item.semantic_type);
    if (code) issue.code = code;
    if (message) issue.message = message;
    if (assetId) issue.asset_id = assetId;
    if (entityId) issue.entity_id = entityId;
    if (semanticType) issue.semantic_type = semanticType;
    return [issue];
  });
}

export function normalizeUploadedAssetBatch(value: unknown): AssetUploadBatchResponse | null {
  if (!isRecord(value)) return null;
  const assets = normalizeAssetList(value.assets) ?? [];
  const libraryAssets = normalizeAssetList(value.library_assets);
  return {
    assets,
    library_entity_id: firstString(value.library_entity_id),
    ...(stringArray(value.library_asset_ids) ? { library_asset_ids: stringArray(value.library_asset_ids) } : {}),
    ...(isRecord(value.library_entity) ? { library_entity: value.library_entity as unknown as AssetUploadBatchResponse["library_entity"] } : {}),
    ...(libraryAssets ? { library_assets: libraryAssets } : {}),
  };
}

export function normalizeMediaRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value === "string") {
    return {
      local_path: value,
      public_url: buildMediaUrl(value),
    };
  }
  if (!isRecord(value)) return null;

  const localPath = firstString(value.local_path, value.path);
  const publicUrl = firstString(value.public_url) ?? (localPath ? buildMediaUrl(localPath) : undefined);
  return {
    ...value,
    ...(publicUrl ? { public_url: publicUrl } : {}),
  };
}

export function normalizeQualityReviewResponse(value: unknown): QualityReviewResponse {
  const record = isRecord(value) ? value : {};
  const output = normalizeNodeOutput(record.output);
  const node = isRecord(record.node) ? normalizeWorkflowNode(record.node as unknown as WorkflowNode) : undefined;
  const runSource = record.run ?? record.node_run;
  const run = isRecord(runSource) ? normalizeNodeRunResult(runSource as unknown as NodeRunResult) : undefined;
  const qualitySummary =
    normalizeQualityReviewSummary(record.quality_summary) ??
    normalizeQualityReviewSummary(output?.quality_summary) ??
    normalizeQualityReviewSummary(node?.output?.quality_summary) ??
    normalizeQualityReviewSummary(run?.output?.quality_summary);
  const outputAssets =
    normalizeQualityReviewAssetList(record.output_assets ?? record.assets ?? output?.output_assets ?? output?.assets) ??
    node?.output_assets ??
    run?.output_assets;

  return {
    ...(record as QualityReviewResponse),
    workflow_id: firstString(record.workflow_id, node?.workflow_id, run?.workflow_id),
    node_id: firstString(record.node_id, node?.id, run?.node_id),
    status: normalizeQualityReviewStatus(record.status ?? qualitySummary?.status ?? qualitySummary?.quality_status),
    ...(qualitySummary ? { quality_summary: qualitySummary } : {}),
    ...(output ? { output } : {}),
    ...(outputAssets ? { output_assets: outputAssets } : {}),
    ...(Array.isArray(record.assets) ? { assets: normalizeQualityReviewAssetList(record.assets) ?? [] } : {}),
    ...(node ? { node } : {}),
    ...(run ? { run } : {}),
    message: firstString(record.message),
  };
}

function normalizeNodeOutput(value: unknown): WorkflowNode["output"] | undefined {
  if (!isRecord(value)) return undefined;
  const qualitySummary = normalizeQualityReviewSummary(value.quality_summary ?? value.qualitySummary);
  const assets = normalizeAssetList(value.assets);
  const outputAssets = normalizeAssetList(value.output_assets);
  return {
    ...value,
    ...(qualitySummary ? { quality_summary: qualitySummary } : {}),
    ...(assets ? { assets } : {}),
    ...(outputAssets ? { output_assets: outputAssets } : {}),
  };
}

function normalizeQualityReviewAssetList(value: unknown): UploadedAsset[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const assets = dedupeAssets(value
    .map((asset, index) => normalizeQualityReviewAsset(asset, `quality-asset-${index + 1}`))
    .filter((asset): asset is UploadedAsset => Boolean(asset)));
  return assets.length ? assets : undefined;
}

function normalizeQualityReviewAsset(value: unknown, fallbackId: string): UploadedAsset | null {
  const normalized = normalizeUploadedAsset(value, fallbackId);
  if (normalized) return normalized;
  if (!isRecord(value)) return null;
  const assetId = firstString(value.asset_id, value.id, value.library_asset_id);
  if (!assetId) return null;
  return {
    ...(value as unknown as UploadedAsset),
    asset_id: assetId,
    asset_type: normalizeAssetType(value.asset_type ?? value.type ?? value.media_type, "image", firstString(value.local_path, value.path, value.url, value.public_url) ?? ""),
    asset_role: normalizeAssetRole(value.asset_role),
    filename: firstString(value.filename, value.name) ?? assetId,
    mime_type: firstString(value.mime_type, value.content_type) ?? "",
    local_path: firstString(value.local_path, value.path, value.uri) ?? "",
    ...(normalizeQualityReviewStatus(value.quality_status) ? { quality_status: normalizeQualityReviewStatus(value.quality_status) } : {}),
    ...(value.quality_score !== undefined ? { quality_score: toNumber(value.quality_score) ?? null } : {}),
    ...(value.quality_issues !== undefined ? { quality_issues: normalizeQualityReviewIssues(value.quality_issues) } : {}),
    ...(value.quality_warnings !== undefined ? { quality_warnings: normalizeQualityReviewIssues(value.quality_warnings) } : {}),
    ...(value.reviewer !== undefined ? { reviewer: firstString(value.reviewer) ?? null } : {}),
  };
}

function normalizeQualityReviewSummary(value: unknown): QualityReviewSummary | undefined {
  if (!isRecord(value)) return undefined;
  return {
    ...(value as QualityReviewSummary),
    ...(normalizeQualityReviewStatus(value.status ?? value.quality_status) ? { status: normalizeQualityReviewStatus(value.status ?? value.quality_status) } : {}),
    ...(normalizeQualityReviewStatus(value.quality_status) ? { quality_status: normalizeQualityReviewStatus(value.quality_status) } : {}),
    reviewer: firstString(value.reviewer, value.method) ?? null,
    method: firstString(value.method, value.reviewer) ?? null,
    checked_asset_count: toNumber(value.checked_asset_count ?? value.checkedAssetCount) ?? null,
    asset_count: toNumber(value.asset_count ?? value.assetCount) ?? null,
    warning_count: toNumber(value.warning_count ?? value.warningCount) ?? null,
    failed_count: toNumber(value.failed_count ?? value.failedCount) ?? null,
    passed_count: toNumber(value.passed_count ?? value.passedCount) ?? null,
    unavailable_count: toNumber(value.unavailable_count ?? value.unavailableCount) ?? null,
    quality_score: toNumber(value.quality_score ?? value.score) ?? null,
    issues: normalizeQualityReviewIssues(value.issues),
    warnings: normalizeQualityReviewIssues(value.warnings),
    asset_issues: normalizeQualityReviewIssues(value.asset_issues ?? value.assetIssues),
  };
}

function normalizeQualityReviewIssues(value: unknown): QualityReviewIssue[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): QualityReviewIssue[] => {
    if (typeof item === "string" && item.trim()) return [{ message: item.trim() }];
    if (!isRecord(item)) return [];
    const issue: QualityReviewIssue = { ...(item as QualityReviewIssue) };
    const code = firstString(item.code, item.error_code);
    const message = firstString(item.message, item.reason, item.error, item.detail);
    const assetId = firstString(item.asset_id);
    const entityId = firstString(item.entity_id);
    const semanticType = firstString(item.semantic_type);
    const severity = firstString(item.severity, item.level);
    if (code) issue.code = code;
    if (message) issue.message = message;
    if (assetId) issue.asset_id = assetId;
    if (entityId) issue.entity_id = entityId;
    if (semanticType) issue.semantic_type = semanticType;
    if (severity) issue.severity = severity;
    return [issue];
  });
}

function normalizeQualityReviewStatus(value: unknown): QualityReviewSummary["status"] | undefined {
  return firstString(value);
}

export function sanitizeUploadRole(value: unknown): BackendUploadRole {
  const text = typeof value === "string" ? value : "";
  return BACKEND_UPLOAD_ROLES.includes(text as BackendUploadRole) ? (text as BackendUploadRole) : "reference";
}

export function isSupportedUploadMime(mimeType?: string | null, filename?: string | null) {
  const normalized = (mimeType ?? "").toLowerCase();
  const name = (filename ?? "").toLowerCase();
  return (
    normalized.startsWith("image/") ||
    normalized.startsWith("video/") ||
    normalized.startsWith("audio/") ||
    normalized.startsWith("text/") ||
    normalized === "application/pdf" ||
    normalized === "application/msword" ||
    normalized === "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
    /\.(mp3|wav|m4a|aac|ogg|pdf|txt|md|docx?)$/i.test(name)
  );
}

export function isSupportedUploadFile(file: { type?: string | null; name?: string | null }) {
  return isSupportedUploadMime(file.type, file.name);
}

export function uploadOptionsForNode(
  nodeType: string,
  requestedRole: unknown,
  mimeType?: string | null,
  uploadKind: AssetLibraryUploadKind = "",
  metadata: Pick<AssetUploadOptions, "display_name" | "tags"> = {},
) {
  const assetRole = sanitizeUploadRole(requestedRole);
  const isImage = (mimeType ?? "").toLowerCase().startsWith("image/");
  const promptTargets = isImage ? promptTargetsForNode(nodeType, assetRole) : undefined;
  return {
    asset_role: assetRole,
    use_as_prompt: isImage,
    prompt_targets: promptTargets?.length ? promptTargets : undefined,
    ...assetLibraryUploadOptionsForKind(uploadKind, metadata),
  };
}

export function assetLibraryUploadOptionsForKind(
  kind: AssetLibraryUploadKind = "",
  metadata: Pick<AssetUploadOptions, "display_name" | "tags"> = {},
): AssetUploadOptions {
  const cleanMetadata: Pick<AssetUploadOptions, "display_name" | "tags"> = {
    ...(metadata.display_name?.trim() ? { display_name: metadata.display_name.trim() } : {}),
    ...(metadata.tags?.length ? { tags: metadata.tags } : {}),
  };

  if (!kind) return cleanMetadata;
  if (kind === "product") return { ...cleanMetadata, entity_type: "product", semantic_type: "product_reference" };
  if (kind === "character") return { ...cleanMetadata, entity_type: "character", semantic_type: "character_main" };
  if (kind === "scene") return { ...cleanMetadata, entity_type: "scene", semantic_type: "scene_main" };
  if (kind === "style_reference") return { ...cleanMetadata, entity_type: "style_reference", semantic_type: "style_reference" };
  if (kind === "bgm") return { ...cleanMetadata, entity_type: "bgm", semantic_type: "bgm" };
  if (kind === "storyboard_image") return { ...cleanMetadata, entity_type: "storyboard_shot", semantic_type: "storyboard_image" };
  if (kind === "storyboard_video") return { ...cleanMetadata, entity_type: "storyboard_shot", semantic_type: "storyboard_video" };
  return cleanMetadata;
}

export function dispatchAssetLibraryUploadEvent(asset: AssetLibraryRefreshEventDetail) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(ASSET_LIBRARY_UPLOAD_EVENT, { detail: asset }));
}

function promptTargetsForNode(nodeType: string, assetRole: BackendUploadRole): PromptTarget[] | undefined {
  const normalized = nodeType.toLowerCase();
  if (normalized.includes("product")) return ["product-generation"];
  if (normalized.includes("character")) return ["character-generation", "storyboard"];
  if (normalized.includes("scene")) return ["scene-generation", "storyboard"];
  if (normalized.includes("storyboard") || normalized.includes("video")) return ["storyboard", "storyboard-video-generation"];
  if (assetRole === "product") return ["product-generation"];
  if (assetRole === "character") return ["character-generation", "storyboard"];
  if (assetRole === "scene") return ["scene-generation", "storyboard"];
  return undefined;
}

function normalizeOptionalNodeIdArray(value: unknown) {
  if (value === undefined || value === null) return undefined;
  return normalizeNodeIdArray(value);
}

function normalizeNodeIdArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map(nodeIdFromUnknown).filter((item): item is string => Boolean(item));
}

function normalizeOptionalExecutionNodeIdArray(value: unknown) {
  if (value === undefined || value === null) return undefined;
  return normalizeExecutionNodeIdArray(value);
}

function normalizeExecutionNodeIdArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map(executionNodeIdFromUnknown).filter((item): item is string => Boolean(item));
}

function normalizeWorkflowExecutionNodes(value: unknown): WorkflowExecutionNodeState[] | undefined {
  const entries: Array<[string | undefined, unknown]> = Array.isArray(value)
    ? value.map((item) => [undefined, item])
    : isRecord(value)
      ? Object.entries(value)
      : [];
  if (!entries.length) return undefined;
  const nodes = entries
    .map(([key, item]) => normalizeWorkflowExecutionNode(item, key))
    .filter((item): item is WorkflowExecutionNodeState => Boolean(item));
  return nodes.length ? nodes : undefined;
}

function normalizeWorkflowExecutionNode(item: unknown, key?: string): WorkflowExecutionNodeState | null {
  if (!isRecord(item)) return null;
  const nodeId = executionNodeIdFromUnknown(item) ?? key;
  const status = toStringValue(item.status);
  if (!nodeId || !status) return null;
  if (key && item.node_id && key !== nodeId && typeof console !== "undefined") {
    console.warn(`Workflow execution node key "${key}" does not match node_id "${nodeId}".`);
  }
  const nodeType = firstString(item.node_type, item.type);
  return {
    ...(item as unknown as WorkflowExecutionNodeState),
    node_id: nodeId,
    ...(nodeType ? { node_type: nodeType } : {}),
    status,
    selected: toBoolean(item.selected),
    started_at: firstString(item.started_at) ?? null,
    finished_at: firstString(item.finished_at) ?? null,
    node_run_id: firstString(item.node_run_id, item.run_id) ?? null,
    output_status: firstString(item.output_status) ?? null,
    has_active_output: toBoolean(item.has_active_output) ?? null,
    error: firstString(item.error) ?? null,
    skipped_reason: firstString(item.skipped_reason) ?? null,
    waiting_reason: firstString(item.waiting_reason) ?? null,
    metadata: isRecord(item.metadata) ? item.metadata : undefined,
  };
}

function executionNodeIdsByStatus(nodes: WorkflowExecutionNodeState[]) {
  return {
    queued: nodes.filter((node) => normalizedStatus(node.status) === "queued").map((node) => node.node_id),
    running: nodes.filter((node) => normalizedStatus(node.status) === "running").map((node) => node.node_id),
    waiting: nodes.filter((node) => normalizedStatus(node.status) === "waiting").map((node) => node.node_id),
    completed: nodes.filter((node) => ["completed", "complete", "success", "succeeded", "done"].includes(normalizedStatus(node.status))).map((node) => node.node_id),
    failed: nodes.filter((node) => ["failed", "error", "cancelled", "canceled"].includes(normalizedStatus(node.status))).map((node) => node.node_id),
    skipped: nodes.filter((node) => normalizedStatus(node.status) === "skipped").map((node) => node.node_id),
  };
}

function selectedExecutionNodeIds(nodes: WorkflowExecutionNodeState[]) {
  const selected = nodes.filter((node) => node.selected).map((node) => node.node_id);
  return selected.length ? selected : undefined;
}

function nodeIdFromUnknown(value: unknown) {
  if (typeof value === "string") return value;
  if (!isRecord(value)) return undefined;
  return firstString(value.node_id, value.id, value.source_node_id, value.target_node_id, value.node_type);
}

function executionNodeIdFromUnknown(value: unknown) {
  if (typeof value === "string") return value;
  if (!isRecord(value)) return undefined;
  return firstString(value.node_id, value.id);
}

function isWorkflowGraphLike(value: unknown): value is WorkflowGraph {
  return isRecord(value) && Array.isArray(value.nodes);
}

function findGraphNode(graph: WorkflowGraph, nodeId: string) {
  return graph.nodes.find((node) => node.id === nodeId || node.node_type === nodeId);
}

function fallbackNode(nodeId: string): WorkflowNode {
  return {
    id: nodeId,
    title: nodeId,
  };
}

function countReadySegments(segments: Record<string, unknown>[]) {
  return segments.filter((segment) => {
    const status = toStringValue(segment.status ?? segment.download_status ?? segment.render_status)?.toLowerCase();
    if (status && ["ready", "completed", "complete", "success", "succeeded", "done"].includes(status)) return true;
    return Boolean(segment.local_path || segment.public_url || segment.url || segment.remote_url);
  }).length;
}

function normalizeAssetType(value: unknown, fallback: UploadedAsset["asset_type"], path?: string): UploadedAsset["asset_type"] {
  const text = `${typeof value === "string" ? value : ""} ${path ?? ""}`.toLowerCase();
  if (text.includes("audio") || /\.(mp3|wav|m4a|aac|ogg)(?=$|\?)/i.test(text)) return "audio";
  if (text.includes("video") || /\.(mp4|mov|webm|mkv|avi)(?=$|\?)/i.test(text)) return "video";
  if (text.includes("document") || text.includes("text") || text.includes("pdf") || /\.(pdf|txt|md|docx?)(?=$|\?)/i.test(text)) return "document";
  if (text.includes("image") || /\.(png|jpe?g|webp|gif|bmp)(?=$|\?)/i.test(text)) return "image";
  return fallback;
}

function normalizeAssetRole(value: unknown): UploadedAsset["asset_role"] {
  const text = typeof value === "string" ? value : "";
  if (["product", "character", "scene", "reference", "audio", "document"].includes(text)) return text as UploadedAsset["asset_role"];
  return "reference";
}

function absoluteMediaUrl(publicPath: string, apiBaseUrl: string) {
  if (!/^https?:\/\//i.test(apiBaseUrl)) return publicPath;
  try {
    return new URL(publicPath, apiBaseUrl).toString();
  } catch {
    return publicPath;
  }
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value;
  }
  return undefined;
}

function stringArray(value: unknown) {
  if (!Array.isArray(value)) return undefined;
  const items = value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()));
  return items.length ? items : undefined;
}

function toStringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function toNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function toBoolean(value: unknown) {
  return typeof value === "boolean" ? value : undefined;
}

function normalizedStatus(value: unknown) {
  return typeof value === "string" ? value.toLowerCase() : "";
}

function filenameFromPath(path: string) {
  const clean = path.split("?")[0]?.split("#")[0] ?? "";
  const match = clean.match(/([^/\\]+)$/);
  return match?.[1];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
