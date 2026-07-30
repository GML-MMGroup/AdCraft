import type {
  AgentActionReceiptV2,
  AgentCanvasWorkflowV2,
  AgentCanvasChatTurnV2,
  AgentCanvasChatTimelineResponseV2,
  AgentCommandOperationV2,
  AgentCommandPlanV2,
  AgentCanvasImageLibraryListResponseV2,
  AgentCanvasVideoSkillRunV2,
  AgentNodeRefV2,
  AgentOperationResultV2,
  AgentPlacementHintV2,
  BindingCapabilityDecisionV2,
  CanvasBindingKindV2,
  CanvasInputRoleV2,
  CanvasBindingSourceImageAssetV2,
  CanvasBindingSourceNodeV2,
  CanvasBindingSourceV2,
  CanvasBindingV2,
  CanvasExecutionStatusV2,
  CanvasMutationResponseV2,
  CanvasLayoutPatchResponseV2,
  CanvasNodeErrorV2,
  CanvasNodeStatusV2,
  CanvasNodeTypeV2,
  CanvasNodeV2,
  CanvasPositionV2,
  CanvasVariationDraftResponseV2,
  CanvasVariationDraftV2,
  CanvasVariationMaterializeResponseV2,
  CanvasRuntimeEventV2,
  CanvasRuntimeEventsResponseV2,
  CanvasRuntimeSnapshotV2,
  CanvasRunAcceptedV2,
  CanvasRunCancelResponseV2,
  ChatArtifactCardV2,
  ChatExpertActivityV2,
  ChatMessageV2,
  ChatProposalCardV2,
  ChatTimelineItemV2,
  ChatTimelineListResponseV2,
  ChatTurnAcceptedV2,
  ConceptOptionV2,
  ConceptProposalV2,
  EditingExportRuntimeV2,
  EditingExportAcceptedV2,
  EditingExportCancelResponseV2,
  EditingManifestV2,
  EditingNodeContentV2,
  EditingOutputSettingsV2,
  EditingPreviewClipV2,
  EditingPreviewV2,
  EditingSkippedInputV2,
  NodeRuntimePhaseV2,
  NodeRuntimeV2,
  PlanningTopicStateV2,
  PlanningTopicStatusV2,
  ProjectAssetSummaryV2,
  ProjectAssetListResponseV2,
  ProjectAssetStatusV2,
  ProjectAssetUploadResponseV2,
  ProviderModelCapabilityListV2,
  ProviderModelCapabilityV2,
  ResolvedInputSnapshotV2,
  ResolvedMediaInputSnapshotV2,
  ResolvedTextInputSnapshotV2,
  SpecialistAgentNameV2,
  StorageAccessDescriptorV2,
} from "../../../types-v2.ts";

type JsonRecord = Record<string, unknown>;

const CANVAS_NODE_TYPES = new Set<CanvasNodeTypeV2>(["text", "script", "image", "video", "audio", "editing"]);
const COMMAND_NODE_TYPES = new Set<Exclude<CanvasNodeTypeV2, "editing">>(["text", "script", "image", "video", "audio"]);
const CANVAS_NODE_STATUSES = new Set<CanvasNodeStatusV2>(["draft", "working", "ready", "failed"]);
const CANVAS_BINDING_KINDS = new Set<CanvasBindingKindV2>([
  "brief_context",
  "script_context",
  "image_reference",
  "video_reference",
  "audio_reference",
]);
const CANVAS_INPUT_ROLES = new Set<CanvasInputRoleV2>([
  "instruction",
  "visual_reference",
  "first_frame",
  "motion_reference",
  "source_video",
  "audio_reference",
]);
const CANVAS_EXECUTION_STATUSES = new Set<CanvasExecutionStatusV2>([
  "queued",
  "running",
  "waiting",
  "completed",
  "partial_completed",
  "failed",
  "cancelled",
]);
const NODE_RUNTIME_PHASES = new Set<NodeRuntimePhaseV2>([
  "waiting_for_input",
  "queued",
  "running",
  "waiting_provider",
  "recovering",
  "publishing",
]);
const ASSET_MEDIA_TYPES = new Set<ProjectAssetSummaryV2["media_type"]>(["image", "video", "audio"]);
const ASSET_SOURCE_TYPES = new Set<ProjectAssetSummaryV2["source_type"]>([
  "upload",
  "generated",
  "recommended",
  "library",
  "editing_export",
]);
const PROJECT_ASSET_STATUSES = new Set<ProjectAssetStatusV2>(["ready", "unavailable"]);
const SPECIALIST_AGENT_NAMES = new Set<SpecialistAgentNameV2>([
  "script_writer",
  "product_designer",
  "prop_designer",
  "character_designer",
  "scene_designer",
  "storyboard_artist",
  "video_director",
  "bgm_director",
]);
const PLANNING_TOPIC_STATUSES = new Set<PlanningTopicStatusV2>(["pending", "in_review", "resolved", "skipped", "not_required"]);
const CHAT_MESSAGE_SPEAKERS = new Set<ChatMessageV2["speaker"]>(["user", "adcraft_video_agent"]);
const CONCEPT_PROPOSAL_STATUSES = new Set<ConceptProposalV2["status"]>(["pending", "selected", "revised", "skipped", "superseded"]);
const PROPOSAL_SELECTION_ACTORS = new Set<NonNullable<ConceptProposalV2["selection_actor"]>>(["user", "agent"]);
const EXPERT_ACTIVITY_STATUSES = new Set<ChatExpertActivityV2["status"]>(["working", "completed", "failed"]);
const EDITING_EXPORT_STATUSES = new Set<EditingExportRuntimeV2["status"]>(["queued", "exporting", "completed", "failed", "cancelled"]);
const EDITING_SKIPPED_REASONS = new Set<EditingSkippedInputV2["reason"]>([
  "source_not_ready",
  "source_failed",
  "source_output_unavailable",
  "source_media_invalid",
]);
const EDITING_VIDEO_CODEC = new Set<EditingOutputSettingsV2["video_codec"]>(["h264"]);
const EDITING_AUDIO_CODEC = new Set<EditingOutputSettingsV2["audio_codec"]>(["aac"]);
const EDITING_CONTAINER = new Set<EditingOutputSettingsV2["container"]>(["mp4"]);
const RESOLVED_TEXT_BINDING_KINDS = new Set<ResolvedTextInputSnapshotV2["binding_kind"]>(["brief_context", "script_context"]);
const RESOLVED_DOCUMENT_KINDS = new Set<ResolvedTextInputSnapshotV2["document_kind"]>(["text", "script"]);
const RESOLVED_MEDIA_BINDING_KINDS = new Set<ResolvedMediaInputSnapshotV2["binding_kind"]>([
  "image_reference",
  "video_reference",
  "audio_reference",
]);
const PROVIDER_INPUT_TYPES = new Set<ProviderModelCapabilityV2["accepted_input_types"][number]>(["text", "image", "video", "audio"]);
const PLACEMENT_INTENTS = new Set<AgentPlacementHintV2["intent"]>([
  "append_flow",
  "after_anchor",
  "right_sibling",
  "near_selection",
]);
const COMMAND_PLAN_STATUSES = new Set<AgentCommandPlanV2["status"]>([
  "pending_confirmation",
  "applying",
  "applied",
  "rejected",
  "superseded",
  "failed",
]);
const COMMAND_RISKS = new Set<AgentCommandPlanV2["risk"]>([
  "reversible_authoring",
  "destructive_authoring",
  "external_effect",
]);
const RECEIPT_STATUSES = new Set<AgentActionReceiptV2["status"]>([
  "applied",
  "applied_with_run_error",
  "rejected",
  "failed",
]);

function defaultInputRole(bindingKind: CanvasBindingKindV2): CanvasInputRoleV2 {
  if (bindingKind === "image_reference") return "visual_reference";
  if (bindingKind === "video_reference") return "source_video";
  if (bindingKind === "audio_reference") return "audio_reference";
  return "instruction";
}

function fail(path: string, message: string): never {
  throw new Error(`Invalid ${path}: ${message}`);
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function expectRecord(value: unknown, path: string): JsonRecord {
  if (!isRecord(value)) fail(path, "expected object");
  return value;
}

function forbidUnknownFields(record: JsonRecord, allowed: readonly string[], path: string) {
  const allowedSet = new Set(allowed);
  for (const key of Object.keys(record)) {
    if (!allowedSet.has(key)) fail(`${path}.${key}`, "unknown field");
  }
}

function expectString(value: unknown, path: string) {
  if (typeof value !== "string") fail(path, "expected string");
  return value;
}

function expectNonEmptyString(value: unknown, path: string) {
  const result = expectString(value, path);
  if (!result.trim()) fail(path, "expected non-empty string");
  return result;
}

function optionalString(value: unknown, path: string) {
  if (value === undefined) return undefined;
  return expectString(value, path);
}

function nullableString(value: unknown, path: string) {
  if (value === null) return null;
  return expectString(value, path);
}

function expectBoolean(value: unknown, path: string) {
  if (typeof value !== "boolean") fail(path, "expected boolean");
  return value;
}

function optionalBoolean(value: unknown, path: string) {
  if (value === undefined) return undefined;
  return expectBoolean(value, path);
}

function expectFiniteNumber(value: unknown, path: string) {
  if (typeof value !== "number" || !Number.isFinite(value)) fail(path, "expected finite number");
  return value;
}

function expectInteger(value: unknown, path: string) {
  const result = expectFiniteNumber(value, path);
  if (!Number.isInteger(result)) fail(path, "expected integer");
  return result;
}

function expectNonNegativeInteger(value: unknown, path: string) {
  const result = expectInteger(value, path);
  if (result < 0) fail(path, "expected non-negative integer");
  return result;
}

function expectPositiveInteger(value: unknown, path: string) {
  const result = expectInteger(value, path);
  if (result <= 0) fail(path, "expected positive integer");
  return result;
}

function nullableFiniteNumber(value: unknown, path: string) {
  if (value === null) return null;
  return expectFiniteNumber(value, path);
}

function nullablePositiveInteger(value: unknown, path: string) {
  if (value === null) return null;
  return expectPositiveInteger(value, path);
}

function nullableNonNegativeNumber(value: unknown, path: string) {
  if (value === null) return null;
  const result = expectFiniteNumber(value, path);
  if (result < 0) fail(path, "expected non-negative number");
  return result;
}

function nullableBrowserSafeUrl(value: unknown, path: string) {
  if (value === null) return null;
  const result = expectNonEmptyString(value, path);
  if (!result.startsWith("/api/") && !result.startsWith("https://") && !result.startsWith("http://")) {
    fail(path, "expected browser-safe URL");
  }
  return result;
}

function optionalNullableString(value: unknown, path: string) {
  if (value === undefined) return undefined;
  return nullableString(value, path);
}

function nullableStringWithDefault(value: unknown, path: string) {
  return value === undefined ? null : nullableString(value, path);
}

function expectStringArray(value: unknown, path: string) {
  if (!Array.isArray(value)) fail(path, "expected array");
  return value.map((item, index) => expectString(item, `${path}[${index}]`));
}

function optionalStringArray(value: unknown, path: string, defaultValue: string[] = []) {
  if (value === undefined) return defaultValue;
  return expectStringArray(value, path);
}

function expectLiteral<T extends string>(value: unknown, allowed: ReadonlySet<T>, path: string): T {
  const result = expectString(value, path);
  if (!allowed.has(result as T)) fail(path, `expected one of ${Array.from(allowed).join(", ")}`);
  return result as T;
}

function optionalNullableLiteral<T extends string>(value: unknown, allowed: ReadonlySet<T>, path: string): T | null | undefined {
  if (value === undefined) return undefined;
  if (value === null) return null;
  return expectLiteral(value, allowed, path);
}

function expectRecordValue(value: unknown, path: string) {
  return expectRecord(value, path);
}

function expectUnknownRecord(value: unknown, path: string) {
  if (!isRecord(value)) fail(path, "expected object");
  return value;
}

function optionalUnknownRecord(value: unknown, path: string, defaultValue: JsonRecord = {}) {
  if (value === undefined) return defaultValue;
  return expectUnknownRecord(value, path);
}

function normalizeReferenceLimits(
  value: unknown,
  path: string,
): ProviderModelCapabilityV2["reference_limits"] {
  if (value === undefined) return {};
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["image", "video", "audio"], path);
  return Object.fromEntries(
    Object.entries(record).map(([key, limit]) => [
      key,
      expectNonNegativeInteger(limit, `${path}.${key}`),
    ]),
  );
}

function expectNullableRecord(value: unknown, path: string) {
  if (value === null) return null;
  return expectRecord(value, path);
}

function expectArray(value: unknown, path: string) {
  if (!Array.isArray(value)) fail(path, "expected array");
  return value;
}

function expectTuple2Number(value: unknown, path: string, integer = false): [number, number] {
  const tuple = expectArray(value, path);
  if (tuple.length !== 2) fail(path, "expected two items");
  return [
    integer ? expectInteger(tuple[0], `${path}[0]`) : expectFiniteNumber(tuple[0], `${path}[0]`),
    integer ? expectInteger(tuple[1], `${path}[1]`) : expectFiniteNumber(tuple[1], `${path}[1]`),
  ];
}

function expectIsoDateTimeString(value: unknown, path: string) {
  return expectNonEmptyString(value, path);
}

function normalizeCanvasPositionV2(value: unknown, path: string): CanvasPositionV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["x", "y"], path);
  return {
    x: expectFiniteNumber(record.x, `${path}.x`),
    y: expectFiniteNumber(record.y, `${path}.y`),
  };
}

export function normalizeAgentPlacementHintV2(
  value: unknown,
  path = "placementHint",
): AgentPlacementHintV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["intent", "anchor_node_id", "group_key"], path);
  return {
    intent: expectLiteral(record.intent, PLACEMENT_INTENTS, `${path}.intent`),
    anchor_node_id: nullableStringWithDefault(record.anchor_node_id, `${path}.anchor_node_id`),
    group_key: nullableStringWithDefault(record.group_key, `${path}.group_key`),
  };
}

export function normalizeCanvasVariationDraftV2(
  value: unknown,
  path = "variationDraft",
): CanvasVariationDraftV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "source_node_id",
    "source_node_revision",
    "title",
    "generation_prompt",
    "model_id",
    "parameters",
    "variation_revision",
    "created_at",
    "updated_at",
  ], path);
  return {
    source_node_id: expectNonEmptyString(record.source_node_id, `${path}.source_node_id`),
    source_node_revision: expectPositiveInteger(record.source_node_revision, `${path}.source_node_revision`),
    title: expectNonEmptyString(record.title, `${path}.title`),
    generation_prompt: expectNonEmptyString(record.generation_prompt, `${path}.generation_prompt`),
    model_id: nullableStringWithDefault(record.model_id, `${path}.model_id`),
    parameters: optionalUnknownRecord(record.parameters, `${path}.parameters`, {}),
    variation_revision: expectPositiveInteger(record.variation_revision, `${path}.variation_revision`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

export function normalizeCanvasNodeErrorV2(value: unknown, path = "error"): CanvasNodeErrorV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["code", "message", "retryable"], path);
  return {
    code: expectNonEmptyString(record.code, `${path}.code`),
    message: expectNonEmptyString(record.message, `${path}.message`),
    retryable: expectBoolean(record.retryable, `${path}.retryable`),
  };
}

export function normalizeCanvasNodeV2(value: unknown, path = "node"): CanvasNodeV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "node_id",
      "workflow_id",
      "node_type",
      "semantic_role",
      "role_contract_version",
      "title",
      "status",
      "summary_prompt",
      "generation_prompt",
      "structured_content",
      "model_id",
      "parameters",
      "prompt_context_snapshot_id",
      "output_asset_id",
      "video_skill_run_id",
      "position",
      "revision",
      "error",
      "variation_draft",
      "created_at",
      "updated_at",
    ],
    path,
  );
  const nodeType = expectLiteral(record.node_type, CANVAS_NODE_TYPES, `${path}.node_type`);
  const status = expectLiteral(record.status, CANVAS_NODE_STATUSES, `${path}.status`);
  const outputAssetId = nullableString(record.output_asset_id, `${path}.output_asset_id`);
  if (
    status === "ready"
    && ["image", "video", "audio", "editing"].includes(nodeType)
    && !outputAssetId
  ) {
    fail(`${path}.output_asset_id`, "ready media node requires an output asset");
  }
  return {
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    node_type: nodeType,
    semantic_role: expectNonEmptyString(record.semantic_role, `${path}.semantic_role`),
    role_contract_version: expectLiteral(
      record.role_contract_version,
      new Set<CanvasNodeV2["role_contract_version"]>(["ad-media-role-v1"]),
      `${path}.role_contract_version`,
    ),
    title: expectNonEmptyString(record.title, `${path}.title`),
    status,
    summary_prompt: nullableString(record.summary_prompt, `${path}.summary_prompt`),
    generation_prompt: nullableString(record.generation_prompt, `${path}.generation_prompt`),
    structured_content: expectRecordValue(record.structured_content, `${path}.structured_content`),
    model_id: nullableString(record.model_id, `${path}.model_id`),
    parameters: expectRecordValue(record.parameters, `${path}.parameters`),
    prompt_context_snapshot_id: nullableString(record.prompt_context_snapshot_id, `${path}.prompt_context_snapshot_id`),
    output_asset_id: outputAssetId,
    video_skill_run_id: nullableString(record.video_skill_run_id, `${path}.video_skill_run_id`),
    position: normalizeCanvasPositionV2(record.position, `${path}.position`),
    revision: expectPositiveInteger(record.revision, `${path}.revision`),
    error: record.error === null ? null : normalizeCanvasNodeErrorV2(record.error, `${path}.error`),
    variation_draft: record.variation_draft === null || record.variation_draft === undefined
      ? null
      : normalizeCanvasVariationDraftV2(record.variation_draft, `${path}.variation_draft`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

function normalizeCanvasBindingSourceNodeV2(value: unknown, path: string): CanvasBindingSourceNodeV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["kind", "node_id"], path);
  return {
    kind: expectLiteral(record.kind, new Set<CanvasBindingSourceNodeV2["kind"]>(["node"]), `${path}.kind`),
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
  };
}

function normalizeCanvasBindingSourceImageAssetV2(value: unknown, path: string): CanvasBindingSourceImageAssetV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["kind", "asset_id"], path);
  return {
    kind: expectLiteral(record.kind, new Set<CanvasBindingSourceImageAssetV2["kind"]>(["image_asset"]), `${path}.kind`),
    asset_id: expectNonEmptyString(record.asset_id, `${path}.asset_id`),
  };
}

export function normalizeCanvasBindingSourceV2(value: unknown, path = "binding.source"): CanvasBindingSourceV2 {
  const record = expectRecord(value, path);
  const kind = expectString(record.kind, `${path}.kind`);
  if (kind === "node") return normalizeCanvasBindingSourceNodeV2(record, path);
  if (kind === "image_asset") return normalizeCanvasBindingSourceImageAssetV2(record, path);
  fail(`${path}.kind`, "unsupported discriminator");
}

export function normalizeCanvasBindingV2(value: unknown, path = "binding"): CanvasBindingV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["binding_id", "workflow_id", "source", "target_node_id", "binding_kind", "input_role", "required", "display_order", "created_at"], path);
  const bindingKind = expectLiteral(record.binding_kind, CANVAS_BINDING_KINDS, `${path}.binding_kind`);
  return {
    binding_id: expectNonEmptyString(record.binding_id, `${path}.binding_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    source: normalizeCanvasBindingSourceV2(record.source, `${path}.source`),
    target_node_id: expectNonEmptyString(record.target_node_id, `${path}.target_node_id`),
    binding_kind: bindingKind,
    input_role: record.input_role === undefined
      ? defaultInputRole(bindingKind)
      : expectLiteral(record.input_role, CANVAS_INPUT_ROLES, `${path}.input_role`),
    required: expectBoolean(record.required, `${path}.required`),
    display_order: expectNonNegativeInteger(record.display_order, `${path}.display_order`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
  };
}

export function normalizeProjectAssetSummaryV2(value: unknown, path = "asset"): ProjectAssetSummaryV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "asset_id",
      "media_type",
      "source_type",
      "display_name",
      "mime_type",
      "status",
      "preview_url",
      "media_url",
      "width",
      "height",
      "duration_seconds",
      "checksum",
      "source_semantic_role",
    ],
    path,
  );
  return {
    asset_id: expectNonEmptyString(record.asset_id, `${path}.asset_id`),
    media_type: expectLiteral(record.media_type, ASSET_MEDIA_TYPES, `${path}.media_type`),
    source_type: expectLiteral(record.source_type, ASSET_SOURCE_TYPES, `${path}.source_type`),
    display_name: expectNonEmptyString(record.display_name, `${path}.display_name`),
    mime_type: expectNonEmptyString(record.mime_type, `${path}.mime_type`),
    status: expectLiteral(record.status, PROJECT_ASSET_STATUSES, `${path}.status`),
    preview_url: nullableBrowserSafeUrl(record.preview_url, `${path}.preview_url`),
    media_url: nullableBrowserSafeUrl(record.media_url, `${path}.media_url`),
    width: nullablePositiveInteger(record.width, `${path}.width`),
    height: nullablePositiveInteger(record.height, `${path}.height`),
    duration_seconds: nullableNonNegativeNumber(record.duration_seconds, `${path}.duration_seconds`),
    checksum: expectNonEmptyString(record.checksum, `${path}.checksum`),
    source_semantic_role: record.source_semantic_role === undefined
      ? null
      : nullableString(record.source_semantic_role, `${path}.source_semantic_role`),
  };
}

export function normalizeAgentCanvasWorkflowV2(value: unknown, path = "workflow"): AgentCanvasWorkflowV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["workflow_id", "project_id", "workflow_schema_version", "canvas_model", "revision", "layout_revision", "nodes", "bindings", "assets"], path);
  const schemaVersion = expectInteger(record.workflow_schema_version, `${path}.workflow_schema_version`);
  if (schemaVersion !== 2) fail(`${path}.workflow_schema_version`, "expected 2");
  const canvasModel = expectString(record.canvas_model, `${path}.canvas_model`);
  if (canvasModel !== "agent_canvas_v1") fail(`${path}.canvas_model`, "expected agent_canvas_v1");
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    project_id: expectNonEmptyString(record.project_id, `${path}.project_id`),
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: expectPositiveInteger(record.revision, `${path}.revision`),
    layout_revision: record.layout_revision === undefined
      ? 1
      : expectPositiveInteger(record.layout_revision, `${path}.layout_revision`),
    nodes: expectArray(record.nodes, `${path}.nodes`).map((item, index) => normalizeCanvasNodeV2(item, `${path}.nodes[${index}]`)),
    bindings: expectArray(record.bindings, `${path}.bindings`).map((item, index) => normalizeCanvasBindingV2(item, `${path}.bindings[${index}]`)),
    assets: expectArray(record.assets, `${path}.assets`).map((item, index) => normalizeProjectAssetSummaryV2(item, `${path}.assets[${index}]`)),
  };
}

export function normalizeResolvedTextInputSnapshotV2(value: unknown, path = "resolvedInput"): ResolvedTextInputSnapshotV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["snapshot_type", "source_kind", "source_node_id", "source_node_revision", "binding_kind", "document_kind", "content", "content_hash", "binding_id", "input_role", "required", "display_order"], path);
  const bindingKind = expectLiteral(record.binding_kind, RESOLVED_TEXT_BINDING_KINDS, `${path}.binding_kind`);
  return {
    snapshot_type: expectLiteral(record.snapshot_type, new Set<ResolvedTextInputSnapshotV2["snapshot_type"]>(["text"]), `${path}.snapshot_type`),
    source_kind: expectLiteral(record.source_kind, new Set<ResolvedTextInputSnapshotV2["source_kind"]>(["node"]), `${path}.source_kind`),
    source_node_id: expectNonEmptyString(record.source_node_id, `${path}.source_node_id`),
    source_node_revision: expectPositiveInteger(record.source_node_revision, `${path}.source_node_revision`),
    binding_kind: bindingKind,
    document_kind: expectLiteral(record.document_kind, RESOLVED_DOCUMENT_KINDS, `${path}.document_kind`),
    content: expectString(record.content, `${path}.content`),
    content_hash: expectNonEmptyString(record.content_hash, `${path}.content_hash`),
    binding_id: record.binding_id === undefined
      ? null
      : nullableString(record.binding_id, `${path}.binding_id`),
    input_role: record.input_role === undefined
      ? "instruction"
      : expectLiteral(record.input_role, CANVAS_INPUT_ROLES, `${path}.input_role`),
    required: record.required === undefined
      ? true
      : expectBoolean(record.required, `${path}.required`),
    display_order: record.display_order === undefined
      ? 0
      : expectNonNegativeInteger(record.display_order, `${path}.display_order`),
  };
}

export function normalizeStorageAccessDescriptorV2(
  value: unknown,
  path = "accessDescriptor",
): StorageAccessDescriptorV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["descriptor_type", "asset_id", "media_url", "checksum"], path);
  if (record.descriptor_type !== "asset_content") {
    fail(`${path}.descriptor_type`, "expected asset_content");
  }
  return {
    descriptor_type: "asset_content",
    asset_id: expectNonEmptyString(record.asset_id, `${path}.asset_id`),
    media_url: nullableBrowserSafeUrl(record.media_url, `${path}.media_url`)
      ?? fail(`${path}.media_url`, "expected URL"),
    checksum: expectNonEmptyString(record.checksum, `${path}.checksum`),
  };
}

export function normalizeResolvedMediaInputSnapshotV2(value: unknown, path = "resolvedInput"): ResolvedMediaInputSnapshotV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["snapshot_type", "source_kind", "source_node_id", "source_node_revision", "binding_kind", "source_semantic_role", "asset_id", "media_type", "asset_checksum", "access_descriptor", "binding_id", "input_role", "required", "display_order"], path);
  const sourceKind = expectLiteral(
    record.source_kind,
    new Set<ResolvedMediaInputSnapshotV2["source_kind"]>(["node", "image_asset"]),
    `${path}.source_kind`,
  );
  const sourceNodeId = nullableString(record.source_node_id, `${path}.source_node_id`);
  const sourceNodeRevision = record.source_node_revision === null
    ? null
    : expectPositiveInteger(record.source_node_revision, `${path}.source_node_revision`);
  if (sourceKind === "node" && (!sourceNodeId || sourceNodeRevision === null)) {
    fail(path, "node media source requires node identity");
  }
  if (sourceKind === "image_asset" && (sourceNodeId !== null || sourceNodeRevision !== null)) {
    fail(path, "image asset media source cannot include node identity");
  }
  const bindingKind = expectLiteral(record.binding_kind, RESOLVED_MEDIA_BINDING_KINDS, `${path}.binding_kind`);
  return {
    snapshot_type: expectLiteral(record.snapshot_type, new Set<ResolvedMediaInputSnapshotV2["snapshot_type"]>(["media"]), `${path}.snapshot_type`),
    source_kind: sourceKind,
    source_node_id: sourceNodeId,
    source_node_revision: sourceNodeRevision,
    binding_kind: bindingKind,
    source_semantic_role: record.source_semantic_role === undefined
      ? null
      : nullableString(record.source_semantic_role, `${path}.source_semantic_role`),
    asset_id: expectNonEmptyString(record.asset_id, `${path}.asset_id`),
    media_type: expectLiteral(record.media_type, ASSET_MEDIA_TYPES, `${path}.media_type`),
    asset_checksum: expectNonEmptyString(record.asset_checksum, `${path}.asset_checksum`),
    access_descriptor: normalizeStorageAccessDescriptorV2(record.access_descriptor, `${path}.access_descriptor`),
    binding_id: record.binding_id === undefined
      ? null
      : nullableString(record.binding_id, `${path}.binding_id`),
    input_role: record.input_role === undefined
      ? defaultInputRole(bindingKind)
      : expectLiteral(record.input_role, CANVAS_INPUT_ROLES, `${path}.input_role`),
    required: record.required === undefined
      ? true
      : expectBoolean(record.required, `${path}.required`),
    display_order: record.display_order === undefined
      ? 0
      : expectNonNegativeInteger(record.display_order, `${path}.display_order`),
  };
}

export function normalizeResolvedInputSnapshotV2(value: unknown, path = "resolvedInput"): ResolvedInputSnapshotV2 {
  const record = expectRecord(value, path);
  const snapshotType = expectString(record.snapshot_type, `${path}.snapshot_type`);
  if (snapshotType === "text") return normalizeResolvedTextInputSnapshotV2(record, path);
  if (snapshotType === "media") return normalizeResolvedMediaInputSnapshotV2(record, path);
  fail(`${path}.snapshot_type`, "unsupported discriminator");
}

export function normalizeNodeRuntimeV2(value: unknown, path = "runtime.node_runtime"): NodeRuntimeV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["node_id", "visible_status", "phase", "execution_id", "provider_task_id", "waiting_for_node_ids", "blocked_by_node_ids", "requested_duration_seconds", "effective_duration_seconds", "normalizations", "attempt_no", "updated_at", "error"], path);
  const phase = optionalNullableLiteral(record.phase, NODE_RUNTIME_PHASES, `${path}.phase`);
  return {
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    visible_status: expectLiteral(record.visible_status, CANVAS_NODE_STATUSES, `${path}.visible_status`),
    phase: phase ?? null,
    execution_id: nullableString(record.execution_id, `${path}.execution_id`),
    provider_task_id: nullableString(record.provider_task_id, `${path}.provider_task_id`),
    waiting_for_node_ids: optionalStringArray(record.waiting_for_node_ids, `${path}.waiting_for_node_ids`, []),
    blocked_by_node_ids: optionalStringArray(record.blocked_by_node_ids, `${path}.blocked_by_node_ids`, []),
    requested_duration_seconds: record.requested_duration_seconds === undefined
      ? null
      : nullableNonNegativeNumber(record.requested_duration_seconds, `${path}.requested_duration_seconds`),
    effective_duration_seconds: record.effective_duration_seconds === undefined
      ? null
      : nullableNonNegativeNumber(record.effective_duration_seconds, `${path}.effective_duration_seconds`),
    normalizations: optionalStringArray(record.normalizations, `${path}.normalizations`, []),
    attempt_no: expectNonNegativeInteger(record.attempt_no, `${path}.attempt_no`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
    error: record.error === null ? null : normalizeCanvasNodeErrorV2(record.error, `${path}.error`),
  };
}

export function normalizeCanvasRuntimeSnapshotV2(value: unknown, path = "runtime"): CanvasRuntimeSnapshotV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "workflow_id",
      "active_execution_id",
      "execution_status",
      "node_runtime",
      "queued_node_ids",
      "working_node_ids",
      "waiting_node_ids",
      "ready_node_ids",
      "failed_node_ids",
      "events_cursor",
      "updated_at",
    ],
    path,
  );
  const runtimeRecord = expectRecord(record.node_runtime, `${path}.node_runtime`);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    active_execution_id: nullableString(record.active_execution_id, `${path}.active_execution_id`),
    execution_status: optionalNullableLiteral(record.execution_status, CANVAS_EXECUTION_STATUSES, `${path}.execution_status`) ?? null,
    node_runtime: Object.fromEntries(
      Object.entries(runtimeRecord).map(([key, item]) => [key, normalizeNodeRuntimeV2(item, `${path}.node_runtime.${key}`)]),
    ),
    queued_node_ids: expectStringArray(record.queued_node_ids, `${path}.queued_node_ids`),
    working_node_ids: expectStringArray(record.working_node_ids, `${path}.working_node_ids`),
    waiting_node_ids: expectStringArray(record.waiting_node_ids, `${path}.waiting_node_ids`),
    ready_node_ids: expectStringArray(record.ready_node_ids, `${path}.ready_node_ids`),
    failed_node_ids: expectStringArray(record.failed_node_ids, `${path}.failed_node_ids`),
    events_cursor: expectNonNegativeInteger(record.events_cursor, `${path}.events_cursor`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

export function normalizeCanvasRuntimeEventV2(value: unknown, path = "event"): CanvasRuntimeEventV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "seq",
      "sequence_no",
      "workflow_id",
      "event_type",
      "execution_id",
      "node_id",
      "asset_id",
      "binding_id",
      "created_at",
      "payload",
    ],
    path,
  );
  return {
    seq: expectNonNegativeInteger(record.seq ?? record.sequence_no, `${path}.seq`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    event_type: expectNonEmptyString(record.event_type, `${path}.event_type`),
    execution_id: record.execution_id === undefined ? null : nullableString(record.execution_id, `${path}.execution_id`),
    node_id: record.node_id === undefined ? null : nullableString(record.node_id, `${path}.node_id`),
    asset_id: record.asset_id === undefined ? null : nullableString(record.asset_id, `${path}.asset_id`),
    binding_id: record.binding_id === undefined ? null : nullableString(record.binding_id, `${path}.binding_id`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
    payload: record.payload === null || record.payload === undefined
      ? null
      : expectRecordValue(record.payload, `${path}.payload`),
  };
}

export function normalizeProviderModelCapabilityV2(value: unknown, path = "capability"): ProviderModelCapabilityV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "provider",
      "model_id",
      "output_type",
      "accepted_input_types",
      "max_references",
      "reference_limits",
      "supported_parameters",
      "supported_aspect_ratios",
      "duration_range_seconds",
      "pixel_bounds",
      "available",
      "unavailable_reason",
      "supports_native_audio",
    ],
    path,
  );
  return {
    provider: expectNonEmptyString(record.provider, `${path}.provider`),
    model_id: expectNonEmptyString(record.model_id, `${path}.model_id`),
    output_type: expectLiteral(record.output_type, ASSET_MEDIA_TYPES, `${path}.output_type`),
    accepted_input_types: expectArray(record.accepted_input_types, `${path}.accepted_input_types`).map((item, index) =>
      expectLiteral(item, PROVIDER_INPUT_TYPES, `${path}.accepted_input_types[${index}]`),
    ),
    max_references: expectNonNegativeInteger(record.max_references, `${path}.max_references`),
    reference_limits: normalizeReferenceLimits(record.reference_limits, `${path}.reference_limits`),
    supported_parameters: expectStringArray(record.supported_parameters, `${path}.supported_parameters`),
    supported_aspect_ratios: expectStringArray(record.supported_aspect_ratios, `${path}.supported_aspect_ratios`),
    duration_range_seconds: record.duration_range_seconds === null ? null : expectTuple2Number(record.duration_range_seconds, `${path}.duration_range_seconds`),
    pixel_bounds: record.pixel_bounds === null ? null : expectTuple2Number(record.pixel_bounds, `${path}.pixel_bounds`, true),
    available: expectBoolean(record.available, `${path}.available`),
    unavailable_reason: nullableString(record.unavailable_reason, `${path}.unavailable_reason`),
    supports_native_audio: record.supports_native_audio === undefined
      ? false
      : expectBoolean(record.supports_native_audio, `${path}.supports_native_audio`),
  };
}

export function normalizeProviderModelCapabilityListV2(value: unknown, path = "capabilities"): ProviderModelCapabilityListV2 {
  let items: unknown[];
  if (Array.isArray(value)) {
    items = value;
  } else {
    const record = expectRecord(value, path);
    forbidUnknownFields(record, ["items"], path);
    items = expectArray(record.items, `${path}.items`);
  }
  return items.map((item, index) => normalizeProviderModelCapabilityV2(item, `${path}[${index}]`));
}

export function normalizeBindingCapabilityDecisionV2(value: unknown, path = "bindingCapabilityDecision"): BindingCapabilityDecisionV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["accepted", "target_node_id", "selected_model_id", "required_input_types", "compatible_model_ids", "switch_model_required"], path);
  return {
    accepted: expectBoolean(record.accepted, `${path}.accepted`),
    target_node_id: expectNonEmptyString(record.target_node_id, `${path}.target_node_id`),
    selected_model_id: nullableString(record.selected_model_id, `${path}.selected_model_id`),
    required_input_types: expectArray(record.required_input_types, `${path}.required_input_types`).map((item, index) =>
      expectLiteral(item, PROVIDER_INPUT_TYPES, `${path}.required_input_types[${index}]`),
    ),
    compatible_model_ids: expectStringArray(record.compatible_model_ids, `${path}.compatible_model_ids`),
    switch_model_required: expectBoolean(record.switch_model_required, `${path}.switch_model_required`),
  };
}

export function normalizePlanningTopicStateV2(value: unknown, path = "planningTopic"): PlanningTopicStateV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["topic_id", "skill_run_id", "topic_kind", "display_order", "status", "related_node_ids", "updated_at"], path);
  return {
    topic_id: expectNonEmptyString(record.topic_id, `${path}.topic_id`),
    skill_run_id: expectNonEmptyString(record.skill_run_id, `${path}.skill_run_id`),
    topic_kind: expectNonEmptyString(record.topic_kind, `${path}.topic_kind`),
    display_order: expectNonNegativeInteger(record.display_order, `${path}.display_order`),
    status: expectLiteral(record.status, PLANNING_TOPIC_STATUSES, `${path}.status`),
    related_node_ids: optionalStringArray(record.related_node_ids, `${path}.related_node_ids`, []),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

function normalizeConceptOptionV2(value: unknown, path: string): ConceptOptionV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["option_id", "display_name", "summary_prompt", "semantic_role", "proposed_node_type", "reference_node_ids", "reference_image_asset_ids"], path);
  return {
    option_id: expectNonEmptyString(record.option_id, `${path}.option_id`),
    display_name: expectNonEmptyString(record.display_name, `${path}.display_name`),
    summary_prompt: expectNonEmptyString(record.summary_prompt, `${path}.summary_prompt`),
    semantic_role: expectNonEmptyString(record.semantic_role, `${path}.semantic_role`),
    proposed_node_type: expectLiteral(record.proposed_node_type, CANVAS_NODE_TYPES, `${path}.proposed_node_type`),
    reference_node_ids: optionalStringArray(record.reference_node_ids, `${path}.reference_node_ids`, []),
    reference_image_asset_ids: optionalStringArray(record.reference_image_asset_ids, `${path}.reference_image_asset_ids`, []),
  };
}

function normalizeConceptProposalV2(value: unknown, path: string): ConceptProposalV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["proposal_id", "workflow_id", "turn_id", "specialist", "status", "options", "workflow_revision", "selection_actor"], path);
  const options = expectArray(record.options, `${path}.options`).map((item, index) => normalizeConceptOptionV2(item, `${path}.options[${index}]`));
  if (options.length < 1 || options.length > 4) fail(`${path}.options`, "expected between 1 and 4 options");
  const selectionActor = record.selection_actor === undefined ? null : record.selection_actor === null ? null : expectLiteral(record.selection_actor, PROPOSAL_SELECTION_ACTORS, `${path}.selection_actor`);
  return {
    proposal_id: expectNonEmptyString(record.proposal_id, `${path}.proposal_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    turn_id: expectNonEmptyString(record.turn_id, `${path}.turn_id`),
    specialist: expectLiteral(record.specialist, SPECIALIST_AGENT_NAMES, `${path}.specialist`),
    status: expectLiteral(record.status, CONCEPT_PROPOSAL_STATUSES, `${path}.status`),
    options,
    workflow_revision: expectNonNegativeInteger(record.workflow_revision, `${path}.workflow_revision`),
    selection_actor: selectionActor,
  };
}

function normalizeChatMessageV2(value: unknown, path: string): ChatMessageV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["item_type", "message_id", "conversation_id", "speaker", "text", "linked_node_ids", "script_node_id", "proposal_id", "sequence", "created_at"], path);
  return {
    item_type: expectLiteral(record.item_type, new Set<ChatMessageV2["item_type"]>(["message"]), `${path}.item_type`),
    message_id: expectNonEmptyString(record.message_id, `${path}.message_id`),
    conversation_id: expectNonEmptyString(record.conversation_id, `${path}.conversation_id`),
    speaker: expectLiteral(record.speaker, CHAT_MESSAGE_SPEAKERS, `${path}.speaker`),
    text: expectString(record.text, `${path}.text`),
    linked_node_ids: optionalStringArray(record.linked_node_ids, `${path}.linked_node_ids`, []),
    script_node_id: record.script_node_id === undefined ? null : nullableString(record.script_node_id, `${path}.script_node_id`),
    proposal_id: record.proposal_id === undefined ? null : nullableString(record.proposal_id, `${path}.proposal_id`),
    sequence: expectNonNegativeInteger(record.sequence, `${path}.sequence`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
  };
}

function normalizeChatArtifactCardV2(value: unknown, path: string): ChatArtifactCardV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["item_type", "artifact_id", "artifact_kind", "node_id", "title", "summary", "action_label", "source_turn_id", "sequence", "created_at"], path);
  const actionLabel = record.action_label === undefined ? "View Script" : expectString(record.action_label, `${path}.action_label`);
  if (actionLabel !== "View Script") fail(`${path}.action_label`, "expected View Script");
  return {
    item_type: expectLiteral(record.item_type, new Set<ChatArtifactCardV2["item_type"]>(["artifact"]), `${path}.item_type`),
    artifact_id: expectNonEmptyString(record.artifact_id, `${path}.artifact_id`),
    artifact_kind: expectLiteral(record.artifact_kind, new Set<ChatArtifactCardV2["artifact_kind"]>(["script"]), `${path}.artifact_kind`),
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    title: expectNonEmptyString(record.title, `${path}.title`),
    summary: expectNonEmptyString(record.summary, `${path}.summary`),
    action_label: "View Script",
    source_turn_id: record.source_turn_id === undefined ? null : nullableString(record.source_turn_id, `${path}.source_turn_id`),
    sequence: expectNonNegativeInteger(record.sequence, `${path}.sequence`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
  };
}

function normalizeChatProposalCardV2(value: unknown, path: string): ChatProposalCardV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["item_type", "proposal", "sequence", "created_at"], path);
  return {
    item_type: expectLiteral(record.item_type, new Set<ChatProposalCardV2["item_type"]>(["proposal"]), `${path}.item_type`),
    proposal: normalizeConceptProposalV2(record.proposal, `${path}.proposal`),
    sequence: expectNonNegativeInteger(record.sequence, `${path}.sequence`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
  };
}

function normalizeChatExpertActivityV2(value: unknown, path: string): ChatExpertActivityV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["item_type", "activity_id", "turn_id", "specialist", "label", "operation", "status", "sequence", "started_at", "finished_at"], path);
  return {
    item_type: expectLiteral(record.item_type, new Set<ChatExpertActivityV2["item_type"]>(["expert_activity"]), `${path}.item_type`),
    activity_id: expectNonEmptyString(record.activity_id, `${path}.activity_id`),
    turn_id: expectNonEmptyString(record.turn_id, `${path}.turn_id`),
    specialist: expectLiteral(record.specialist, SPECIALIST_AGENT_NAMES, `${path}.specialist`),
    label: expectNonEmptyString(record.label, `${path}.label`),
    operation: expectNonEmptyString(record.operation, `${path}.operation`),
    status: expectLiteral(record.status, EXPERT_ACTIVITY_STATUSES, `${path}.status`),
    sequence: expectNonNegativeInteger(record.sequence, `${path}.sequence`),
    started_at: expectIsoDateTimeString(record.started_at, `${path}.started_at`),
    finished_at: record.finished_at === undefined ? null : nullableString(record.finished_at, `${path}.finished_at`),
  };
}

function normalizeAgentNodeRefV2(value: unknown, path: string): AgentNodeRefV2 {
  const record = expectRecord(value, path);
  const kind = expectString(record.kind, `${path}.kind`);
  if (kind === "node_id") {
    forbidUnknownFields(record, ["kind", "node_id"], path);
    return {
      kind,
      node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    };
  }
  if (kind === "operation_result") {
    forbidUnknownFields(record, ["kind", "operation_id"], path);
    return {
      kind,
      operation_id: expectNonEmptyString(record.operation_id, `${path}.operation_id`),
    };
  }
  fail(`${path}.kind`, "unsupported node reference");
}

function normalizeAgentCommandOperationV2(
  value: unknown,
  path: string,
): AgentCommandOperationV2 {
  const record = expectRecord(value, path);
  const operationType = expectString(record.operation_type, `${path}.operation_type`);
  const operationId = expectNonEmptyString(record.operation_id, `${path}.operation_id`);
  if (operationType === "create_node") {
    forbidUnknownFields(record, [
      "operation_type",
      "operation_id",
      "node_type",
      "semantic_role",
      "title",
      "summary_prompt",
      "generation_prompt",
      "structured_content",
      "model_id",
      "parameters",
      "source_asset_id",
      "video_skill_run_id",
      "placement_hint",
    ], path);
    return {
      operation_type: operationType,
      operation_id: operationId,
      node_type: expectLiteral(record.node_type, COMMAND_NODE_TYPES, `${path}.node_type`),
      semantic_role: expectNonEmptyString(record.semantic_role, `${path}.semantic_role`),
      title: expectNonEmptyString(record.title, `${path}.title`),
      summary_prompt: nullableStringWithDefault(record.summary_prompt, `${path}.summary_prompt`),
      generation_prompt: nullableStringWithDefault(record.generation_prompt, `${path}.generation_prompt`),
      structured_content: optionalUnknownRecord(record.structured_content, `${path}.structured_content`, {}),
      model_id: nullableStringWithDefault(record.model_id, `${path}.model_id`),
      parameters: optionalUnknownRecord(record.parameters, `${path}.parameters`, {}),
      source_asset_id: nullableStringWithDefault(record.source_asset_id, `${path}.source_asset_id`),
      video_skill_run_id: nullableStringWithDefault(record.video_skill_run_id, `${path}.video_skill_run_id`),
      placement_hint: normalizeAgentPlacementHintV2(record.placement_hint, `${path}.placement_hint`),
    };
  }
  if (operationType === "patch_editable_node") {
    forbidUnknownFields(record, [
      "operation_type",
      "operation_id",
      "node",
      "title",
      "summary_prompt",
      "generation_prompt",
      "structured_content",
      "model_id",
      "parameters",
    ], path);
    return {
      operation_type: operationType,
      operation_id: operationId,
      node: normalizeAgentNodeRefV2(record.node, `${path}.node`),
      title: nullableStringWithDefault(record.title, `${path}.title`),
      summary_prompt: nullableStringWithDefault(record.summary_prompt, `${path}.summary_prompt`),
      generation_prompt: nullableStringWithDefault(record.generation_prompt, `${path}.generation_prompt`),
      structured_content: record.structured_content === undefined
        ? null
        : expectNullableRecord(record.structured_content, `${path}.structured_content`),
      model_id: nullableStringWithDefault(record.model_id, `${path}.model_id`),
      parameters: record.parameters === undefined
        ? null
        : expectNullableRecord(record.parameters, `${path}.parameters`),
    };
  }
  if (operationType === "create_binding") {
    forbidUnknownFields(record, [
      "operation_type",
      "operation_id",
      "source",
      "target",
      "binding_kind",
      "required",
      "display_order",
    ], path);
    const source = expectRecord(record.source, `${path}.source`);
    return {
      operation_type: operationType,
      operation_id: operationId,
      source: source.kind === "image_asset"
        ? {
            kind: "image_asset",
            asset_id: expectNonEmptyString(source.asset_id, `${path}.source.asset_id`),
          }
        : normalizeAgentNodeRefV2(source, `${path}.source`),
      target: normalizeAgentNodeRefV2(record.target, `${path}.target`),
      binding_kind: expectLiteral(record.binding_kind, CANVAS_BINDING_KINDS, `${path}.binding_kind`),
      required: record.required === undefined
        ? true
        : expectBoolean(record.required, `${path}.required`),
      display_order: record.display_order === undefined
        ? 0
        : expectNonNegativeInteger(record.display_order, `${path}.display_order`),
    };
  }
  if (operationType === "delete_binding") {
    forbidUnknownFields(record, ["operation_type", "operation_id", "binding_id"], path);
    return {
      operation_type: operationType,
      operation_id: operationId,
      binding_id: expectNonEmptyString(record.binding_id, `${path}.binding_id`),
    };
  }
  if (operationType === "delete_node") {
    forbidUnknownFields(record, ["operation_type", "operation_id", "node"], path);
    return {
      operation_type: operationType,
      operation_id: operationId,
      node: normalizeAgentNodeRefV2(record.node, `${path}.node`),
    };
  }
  if (operationType === "materialize_proposal") {
    forbidUnknownFields(record, [
      "operation_type",
      "operation_id",
      "proposal_id",
      "option_id",
      "placement_hint",
    ], path);
    return {
      operation_type: operationType,
      operation_id: operationId,
      proposal_id: expectNonEmptyString(record.proposal_id, `${path}.proposal_id`),
      option_id: expectNonEmptyString(record.option_id, `${path}.option_id`),
      placement_hint: normalizeAgentPlacementHintV2(record.placement_hint, `${path}.placement_hint`),
    };
  }
  if (operationType === "fork_ready_media") {
    forbidUnknownFields(record, [
      "operation_type",
      "operation_id",
      "source_node",
      "title",
      "generation_prompt",
      "model_id",
      "parameters",
      "placement_hint",
    ], path);
    return {
      operation_type: operationType,
      operation_id: operationId,
      source_node: normalizeAgentNodeRefV2(record.source_node, `${path}.source_node`),
      title: expectNonEmptyString(record.title, `${path}.title`),
      generation_prompt: expectNonEmptyString(record.generation_prompt, `${path}.generation_prompt`),
      model_id: nullableStringWithDefault(record.model_id, `${path}.model_id`),
      parameters: optionalUnknownRecord(record.parameters, `${path}.parameters`, {}),
      placement_hint: normalizeAgentPlacementHintV2(record.placement_hint, `${path}.placement_hint`),
    };
  }
  if (operationType === "request_node_run") {
    forbidUnknownFields(record, ["operation_type", "operation_id", "node"], path);
    return {
      operation_type: operationType,
      operation_id: operationId,
      node: normalizeAgentNodeRefV2(record.node, `${path}.node`),
    };
  }
  if (operationType === "update_planning_topic") {
    forbidUnknownFields(record, [
      "operation_type",
      "operation_id",
      "skill_run_id",
      "topic_id",
      "status",
      "related_nodes",
    ], path);
    return {
      operation_type: operationType,
      operation_id: operationId,
      skill_run_id: expectNonEmptyString(record.skill_run_id, `${path}.skill_run_id`),
      topic_id: expectNonEmptyString(record.topic_id, `${path}.topic_id`),
      status: expectLiteral(
        record.status,
        new Set(["resolved", "skipped", "not_required"] as const),
        `${path}.status`,
      ),
      related_nodes: expectArray(record.related_nodes ?? [], `${path}.related_nodes`)
        .map((item, index) => normalizeAgentNodeRefV2(item, `${path}.related_nodes[${index}]`)),
    };
  }
  fail(`${path}.operation_type`, "unsupported command operation");
}

export function normalizeAgentCommandPlanV2(
  value: unknown,
  path = "commandPlan",
): AgentCommandPlanV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "plan_id",
    "workflow_id",
    "conversation_id",
    "source_turn_id",
    "base_workflow_revision",
    "operations",
    "continuation_requested",
    "risk",
    "confirmation_required",
    "target_summary",
    "operation_fingerprint",
    "status",
    "supersedes_plan_id",
    "replacement_plan_id",
    "actor",
    "created_at",
    "updated_at",
  ], path);
  const operations = expectArray(record.operations, `${path}.operations`)
    .map((item, index) => normalizeAgentCommandOperationV2(item, `${path}.operations[${index}]`));
  if (operations.length < 1 || operations.length > 8) {
    fail(`${path}.operations`, "expected between 1 and 8 operations");
  }
  return {
    plan_id: expectNonEmptyString(record.plan_id, `${path}.plan_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    conversation_id: expectNonEmptyString(record.conversation_id, `${path}.conversation_id`),
    source_turn_id: expectNonEmptyString(record.source_turn_id, `${path}.source_turn_id`),
    base_workflow_revision: expectPositiveInteger(record.base_workflow_revision, `${path}.base_workflow_revision`),
    operations,
    continuation_requested: record.continuation_requested === undefined
      ? false
      : expectBoolean(record.continuation_requested, `${path}.continuation_requested`),
    risk: expectLiteral(record.risk, COMMAND_RISKS, `${path}.risk`),
    confirmation_required: expectBoolean(record.confirmation_required, `${path}.confirmation_required`),
    target_summary: record.target_summary === undefined
      ? ""
      : expectString(record.target_summary, `${path}.target_summary`),
    operation_fingerprint: expectNonEmptyString(record.operation_fingerprint, `${path}.operation_fingerprint`),
    status: expectLiteral(record.status, COMMAND_PLAN_STATUSES, `${path}.status`),
    supersedes_plan_id: nullableStringWithDefault(record.supersedes_plan_id, `${path}.supersedes_plan_id`),
    replacement_plan_id: nullableStringWithDefault(record.replacement_plan_id, `${path}.replacement_plan_id`),
    actor: record.actor === undefined
      ? "agent"
      : expectLiteral(record.actor, new Set(["agent", "user", "system"] as const), `${path}.actor`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

function normalizeAgentOperationResultV2(
  value: unknown,
  path: string,
): AgentOperationResultV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "operation_id",
    "node_id",
    "binding_id",
    "execution_id",
    "status",
    "error_code",
  ], path);
  return {
    operation_id: expectNonEmptyString(record.operation_id, `${path}.operation_id`),
    node_id: nullableStringWithDefault(record.node_id, `${path}.node_id`),
    binding_id: nullableStringWithDefault(record.binding_id, `${path}.binding_id`),
    execution_id: nullableStringWithDefault(record.execution_id, `${path}.execution_id`),
    status: expectLiteral(record.status, new Set(["applied", "queued", "failed"] as const), `${path}.status`),
    error_code: nullableStringWithDefault(record.error_code, `${path}.error_code`),
  };
}

export function normalizeAgentActionReceiptV2(
  value: unknown,
  path = "actionReceipt",
): AgentActionReceiptV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "receipt_id",
    "workflow_id",
    "plan_id",
    "action_id",
    "status",
    "summary",
    "created_node_ids",
    "updated_node_ids",
    "deleted_node_ids",
    "created_binding_ids",
    "deleted_binding_ids",
    "queued_execution_ids",
    "run_queue_errors",
    "operation_results",
    "workflow_revision",
    "placement_hints",
    "continuation_turn_id",
    "error_code",
    "error_message",
  ], path);
  return {
    receipt_id: expectNonEmptyString(record.receipt_id, `${path}.receipt_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    plan_id: nullableStringWithDefault(record.plan_id, `${path}.plan_id`),
    action_id: nullableStringWithDefault(record.action_id, `${path}.action_id`),
    status: expectLiteral(record.status, RECEIPT_STATUSES, `${path}.status`),
    summary: expectNonEmptyString(record.summary, `${path}.summary`),
    created_node_ids: optionalStringArray(record.created_node_ids, `${path}.created_node_ids`, []),
    updated_node_ids: optionalStringArray(record.updated_node_ids, `${path}.updated_node_ids`, []),
    deleted_node_ids: optionalStringArray(record.deleted_node_ids, `${path}.deleted_node_ids`, []),
    created_binding_ids: optionalStringArray(record.created_binding_ids, `${path}.created_binding_ids`, []),
    deleted_binding_ids: optionalStringArray(record.deleted_binding_ids, `${path}.deleted_binding_ids`, []),
    queued_execution_ids: optionalStringArray(record.queued_execution_ids, `${path}.queued_execution_ids`, []),
    run_queue_errors: optionalStringArray(record.run_queue_errors, `${path}.run_queue_errors`, []),
    operation_results: expectArray(record.operation_results ?? [], `${path}.operation_results`)
      .map((item, index) => normalizeAgentOperationResultV2(item, `${path}.operation_results[${index}]`)),
    workflow_revision: expectPositiveInteger(record.workflow_revision, `${path}.workflow_revision`),
    placement_hints: expectArray(record.placement_hints ?? [], `${path}.placement_hints`)
      .map((item, index) => normalizeAgentPlacementHintV2(item, `${path}.placement_hints[${index}]`)),
    continuation_turn_id: nullableStringWithDefault(record.continuation_turn_id, `${path}.continuation_turn_id`),
    error_code: nullableStringWithDefault(record.error_code, `${path}.error_code`),
    error_message: nullableStringWithDefault(record.error_message, `${path}.error_message`),
  };
}

function normalizeChatCommandPlanCardV2(value: unknown, path: string): ChatTimelineItemV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["item_type", "command_plan", "sequence", "created_at"], path);
  return {
    item_type: "command_plan",
    command_plan: normalizeAgentCommandPlanV2(record.command_plan, `${path}.command_plan`),
    sequence: expectNonNegativeInteger(record.sequence, `${path}.sequence`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
  };
}

function normalizeChatActionReceiptCardV2(value: unknown, path: string): ChatTimelineItemV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["item_type", "action_receipt", "sequence", "created_at"], path);
  return {
    item_type: "action_receipt",
    action_receipt: normalizeAgentActionReceiptV2(record.action_receipt, `${path}.action_receipt`),
    sequence: expectNonNegativeInteger(record.sequence, `${path}.sequence`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
  };
}

export function normalizeChatTimelineItemV2(value: unknown, path = "chatItem"): ChatTimelineItemV2 {
  const record = expectRecord(value, path);
  const itemType = expectString(record.item_type, `${path}.item_type`);
  if (itemType === "message") return normalizeChatMessageV2(record, path);
  if (itemType === "artifact") return normalizeChatArtifactCardV2(record, path);
  if (itemType === "proposal") return normalizeChatProposalCardV2(record, path);
  if (itemType === "expert_activity") return normalizeChatExpertActivityV2(record, path);
  if (itemType === "command_plan") return normalizeChatCommandPlanCardV2(record, path);
  if (itemType === "action_receipt") return normalizeChatActionReceiptCardV2(record, path);
  fail(`${path}.item_type`, "unsupported discriminator");
}

export function normalizeChatTimelineListResponseV2(value: unknown, path = "chatTimeline"): ChatTimelineListResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["workflow_id", "conversation_id", "items", "next_after_seq"], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    conversation_id: record.conversation_id === null
      ? null
      : expectNonEmptyString(record.conversation_id, `${path}.conversation_id`),
    items: expectArray(record.items, `${path}.items`).map((item, index) => normalizeChatTimelineItemV2(item, `${path}.items[${index}]`)),
    next_after_seq: expectNonNegativeInteger(record.next_after_seq, `${path}.next_after_seq`),
  };
}

export function normalizeAgentCanvasChatTimelineCompatV2(
  value: unknown,
  path = "chatTimeline",
): ChatTimelineListResponseV2 {
  const record = expectRecord(value, path);
  if ("next_after_seq" in record) {
    return normalizeChatTimelineListResponseV2(record, path);
  }
  const persisted = normalizeAgentCanvasChatTimelineResponseV2(record, path);
  return {
    workflow_id: persisted.workflow_id,
    conversation_id: persisted.conversation_id,
    next_after_seq: persisted.next_cursor,
    items: persisted.items.map((entry) => {
      if (entry.entry_type === "message") {
        if (!entry.speaker) fail(`${path}.items`, "persisted message requires speaker");
        return {
          item_type: "message" as const,
          message_id: entry.entry_id,
          conversation_id: entry.conversation_id,
          speaker: entry.speaker,
          text: entry.content,
          linked_node_ids: optionalStringArray(
            entry.metadata.linked_node_ids,
            `${path}.items.metadata.linked_node_ids`,
            [],
          ),
          script_node_id: typeof entry.metadata.script_node_id === "string"
            ? entry.metadata.script_node_id
            : null,
          proposal_id: typeof entry.metadata.proposal_id === "string"
            ? entry.metadata.proposal_id
            : null,
          sequence: entry.sequence_no,
          created_at: entry.created_at,
        };
      }
      if (entry.entry_type === "command_plan") {
        if (!entry.command_plan) fail(`${path}.items.command_plan`, "command plan entry requires a plan");
        return {
          item_type: "command_plan" as const,
          command_plan: entry.command_plan,
          sequence: entry.sequence_no,
          created_at: entry.created_at,
        };
      }
      if (entry.entry_type === "action_receipt") {
        if (!entry.action_receipt) fail(`${path}.items.action_receipt`, "receipt entry requires a receipt");
        return {
          item_type: "action_receipt" as const,
          action_receipt: entry.action_receipt,
          sequence: entry.sequence_no,
          created_at: entry.created_at,
        };
      }
      const nodeId = typeof entry.metadata.script_node_id === "string"
        ? entry.metadata.script_node_id
        : typeof entry.metadata.node_id === "string"
          ? entry.metadata.node_id
          : "";
      if (!nodeId) fail(`${path}.items.metadata.node_id`, "script artifact requires node identity");
      return {
        item_type: "artifact" as const,
        artifact_id: entry.entry_id,
        artifact_kind: "script" as const,
        node_id: nodeId,
        title: typeof entry.metadata.title === "string" ? entry.metadata.title : "Script",
        summary: typeof entry.metadata.summary === "string"
          ? entry.metadata.summary
          : entry.content,
        action_label: "View Script" as const,
        source_turn_id: typeof entry.metadata.source_turn_id === "string"
          ? entry.metadata.source_turn_id
          : null,
        sequence: entry.sequence_no,
        created_at: entry.created_at,
      };
    }),
  };
}

export function normalizeEditingOutputSettingsV2(value: unknown, path = "editing.output"): EditingOutputSettingsV2 {
  const record = value === undefined ? {} : expectRecord(value, path);
  forbidUnknownFields(record, ["resolution", "aspect_ratio", "fps", "video_codec", "audio_codec", "container"], path);
  const fps = record.fps === undefined ? null : nullableFiniteNumber(record.fps, `${path}.fps`);
  if (fps !== null && fps <= 0) fail(`${path}.fps`, "expected positive number");
  if (fps !== null && fps > 120) fail(`${path}.fps`, "expected number <= 120");
  return {
    resolution: record.resolution === undefined ? null : nullableString(record.resolution, `${path}.resolution`),
    aspect_ratio: record.aspect_ratio === undefined ? null : nullableString(record.aspect_ratio, `${path}.aspect_ratio`),
    fps,
    video_codec: record.video_codec === undefined ? "h264" : expectLiteral(record.video_codec, EDITING_VIDEO_CODEC, `${path}.video_codec`),
    audio_codec: record.audio_codec === undefined ? "aac" : expectLiteral(record.audio_codec, EDITING_AUDIO_CODEC, `${path}.audio_codec`),
    container: record.container === undefined ? "mp4" : expectLiteral(record.container, EDITING_CONTAINER, `${path}.container`),
  };
}

export function normalizeEditingManifestV2(value: unknown, path = "editing.manifest"): EditingManifestV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["ordered_video_binding_ids", "bgm_audio_binding_id", "bgm_volume", "output", "manifest_revision"], path);
  const bgmVolume = record.bgm_volume === undefined ? 0.2 : expectFiniteNumber(record.bgm_volume, `${path}.bgm_volume`);
  if (bgmVolume < 0 || bgmVolume > 1) fail(`${path}.bgm_volume`, "expected value between 0 and 1");
  return {
    ordered_video_binding_ids: expectStringArray(record.ordered_video_binding_ids, `${path}.ordered_video_binding_ids`),
    bgm_audio_binding_id: record.bgm_audio_binding_id === undefined ? null : nullableString(record.bgm_audio_binding_id, `${path}.bgm_audio_binding_id`),
    bgm_volume: bgmVolume,
    output: normalizeEditingOutputSettingsV2(record.output, `${path}.output`),
    manifest_revision: expectNonNegativeInteger(record.manifest_revision, `${path}.manifest_revision`),
  };
}

export function normalizeEditingSkippedInputV2(value: unknown, path = "editing.skippedInput"): EditingSkippedInputV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["node_id", "reason"], path);
  return {
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    reason: expectLiteral(record.reason, EDITING_SKIPPED_REASONS, `${path}.reason`),
  };
}

export function normalizeEditingPreviewClipV2(value: unknown, path = "editing.previewClip"): EditingPreviewClipV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["binding_id", "node_id", "asset_id", "status", "display_order", "preview_url", "duration_seconds", "warning"], path);
  return {
    binding_id: expectNonEmptyString(record.binding_id, `${path}.binding_id`),
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    asset_id: nullableString(record.asset_id, `${path}.asset_id`),
    status: expectLiteral(record.status, CANVAS_NODE_STATUSES, `${path}.status`),
    display_order: expectNonNegativeInteger(record.display_order, `${path}.display_order`),
    preview_url: nullableString(record.preview_url, `${path}.preview_url`),
    duration_seconds: nullableFiniteNumber(record.duration_seconds, `${path}.duration_seconds`),
    warning: nullableString(record.warning, `${path}.warning`),
  };
}

export function normalizeEditingPreviewV2(value: unknown, path = "editing.preview"): EditingPreviewV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["clips", "bgm_binding_id", "bgm_node_id", "bgm_asset_id", "estimated_duration_seconds", "warnings"], path);
  return {
    clips: expectArray(record.clips, `${path}.clips`).map((item, index) => normalizeEditingPreviewClipV2(item, `${path}.clips[${index}]`)),
    bgm_binding_id: record.bgm_binding_id === undefined ? null : nullableString(record.bgm_binding_id, `${path}.bgm_binding_id`),
    bgm_node_id: record.bgm_node_id === undefined ? null : nullableString(record.bgm_node_id, `${path}.bgm_node_id`),
    bgm_asset_id: record.bgm_asset_id === undefined ? null : nullableString(record.bgm_asset_id, `${path}.bgm_asset_id`),
    estimated_duration_seconds: expectFiniteNumber(record.estimated_duration_seconds, `${path}.estimated_duration_seconds`),
    warnings: optionalStringArray(record.warnings, `${path}.warnings`, []),
  };
}

export function normalizeEditingExportRuntimeV2(value: unknown, path = "editing.exportRuntime"): EditingExportRuntimeV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["export_id", "status", "manifest_revision", "fingerprint", "ready_video_node_ids", "skipped_inputs", "bgm_node_id", "output_asset_id", "error", "started_at", "finished_at"], path);
  return {
    export_id: expectNonEmptyString(record.export_id, `${path}.export_id`),
    status: expectLiteral(record.status, EDITING_EXPORT_STATUSES, `${path}.status`),
    manifest_revision: expectNonNegativeInteger(record.manifest_revision, `${path}.manifest_revision`),
    fingerprint: expectNonEmptyString(record.fingerprint, `${path}.fingerprint`),
    ready_video_node_ids: optionalStringArray(record.ready_video_node_ids, `${path}.ready_video_node_ids`, []),
    skipped_inputs: expectArray(record.skipped_inputs, `${path}.skipped_inputs`).map((item, index) =>
      normalizeEditingSkippedInputV2(item, `${path}.skipped_inputs[${index}]`),
    ),
    bgm_node_id: record.bgm_node_id === undefined ? null : nullableString(record.bgm_node_id, `${path}.bgm_node_id`),
    output_asset_id: record.output_asset_id === undefined ? null : nullableString(record.output_asset_id, `${path}.output_asset_id`),
    error: record.error === null ? null : normalizeCanvasNodeErrorV2(record.error, `${path}.error`),
    started_at: record.started_at === undefined ? null : nullableString(record.started_at, `${path}.started_at`),
    finished_at: record.finished_at === undefined ? null : nullableString(record.finished_at, `${path}.finished_at`),
  };
}

export function normalizeEditingNodeContentV2(value: unknown, path = "editing"): EditingNodeContentV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["manifest", "dirty", "preview", "last_successful_export", "active_export"], path);
  return {
    manifest: normalizeEditingManifestV2(record.manifest, `${path}.manifest`),
    dirty: expectBoolean(record.dirty, `${path}.dirty`),
    preview: normalizeEditingPreviewV2(record.preview, `${path}.preview`),
    last_successful_export:
      record.last_successful_export === null
        ? null
        : record.last_successful_export === undefined
          ? null
          : normalizeEditingExportRuntimeV2(record.last_successful_export, `${path}.last_successful_export`),
    active_export:
      record.active_export === null
        ? null
        : record.active_export === undefined
          ? null
          : normalizeEditingExportRuntimeV2(record.active_export, `${path}.active_export`),
  };
}

export function normalizeCanvasMutationResponseV2(
  value: unknown,
  path = "mutation",
): CanvasMutationResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["workflow", "node", "binding"], path);
  return {
    workflow: normalizeAgentCanvasWorkflowV2(record.workflow, `${path}.workflow`),
    node: record.node === null || record.node === undefined
      ? null
      : normalizeCanvasNodeV2(record.node, `${path}.node`),
    binding: record.binding === null || record.binding === undefined
      ? null
      : normalizeCanvasBindingV2(record.binding, `${path}.binding`),
  };
}

export function normalizeCanvasVariationDraftResponseV2(
  value: unknown,
  path = "variationDraftResponse",
): CanvasVariationDraftResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "workflow_id",
    "workflow_revision",
    "node_id",
    "variation_draft",
  ], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    workflow_revision: expectPositiveInteger(record.workflow_revision, `${path}.workflow_revision`),
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    variation_draft: normalizeCanvasVariationDraftV2(record.variation_draft, `${path}.variation_draft`),
  };
}

export function normalizeCanvasVariationMaterializeResponseV2(
  value: unknown,
  path = "variationMaterialize",
): CanvasVariationMaterializeResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "workflow_id",
    "workflow_revision",
    "source_node_id",
    "sibling_node",
    "copied_binding_ids",
    "run",
    "run_error",
    "placement_hint",
  ], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    workflow_revision: expectPositiveInteger(record.workflow_revision, `${path}.workflow_revision`),
    source_node_id: expectNonEmptyString(record.source_node_id, `${path}.source_node_id`),
    sibling_node: normalizeCanvasNodeV2(record.sibling_node, `${path}.sibling_node`),
    copied_binding_ids: optionalStringArray(record.copied_binding_ids, `${path}.copied_binding_ids`, []),
    run: record.run === null || record.run === undefined
      ? null
      : expectUnknownRecord(record.run, `${path}.run`),
    run_error: record.run_error === null || record.run_error === undefined
      ? null
      : normalizeCanvasNodeErrorV2(record.run_error, `${path}.run_error`),
    placement_hint: normalizeAgentPlacementHintV2(record.placement_hint, `${path}.placement_hint`),
  };
}

export function normalizeCanvasLayoutPatchResponseV2(
  value: unknown,
  path = "layoutPatch",
): CanvasLayoutPatchResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "workflow_id",
    "revision",
    "layout_revision",
    "positions",
  ], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    revision: expectPositiveInteger(record.revision, `${path}.revision`),
    layout_revision: expectPositiveInteger(record.layout_revision, `${path}.layout_revision`),
    positions: expectArray(record.positions, `${path}.positions`).map((item, index) => {
      const positionPath = `${path}.positions[${index}]`;
      const position = expectRecord(item, positionPath);
      forbidUnknownFields(position, ["node_id", "x", "y"], positionPath);
      return {
        node_id: expectNonEmptyString(position.node_id, `${positionPath}.node_id`),
        x: expectFiniteNumber(position.x, `${positionPath}.x`),
        y: expectFiniteNumber(position.y, `${positionPath}.y`),
      };
    }),
  };
}

export function normalizeProjectAssetUploadResponseV2(
  value: unknown,
  path = "assetUpload",
): ProjectAssetUploadResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["workflow_id", "asset"], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    asset: normalizeProjectAssetSummaryV2(record.asset, `${path}.asset`),
  };
}

export function normalizeProjectAssetListResponseV2(
  value: unknown,
  path = "assetList",
): ProjectAssetListResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["workflow_id", "assets"], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    assets: expectArray(record.assets, `${path}.assets`).map((item, index) =>
      normalizeProjectAssetSummaryV2(item, `${path}.assets[${index}]`),
    ),
  };
}

export function normalizeAgentCanvasImageLibraryListResponseV2(
  value: unknown,
  path = "imageLibrary",
): AgentCanvasImageLibraryListResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["items"], path);
  return {
    items: expectArray(record.items, `${path}.items`).map((item, index) =>
      expectUnknownRecord(item, `${path}.items[${index}]`),
    ),
  };
}

export function normalizeAgentCanvasChatTimelineResponseV2(
  value: unknown,
  path = "chatTimeline",
): AgentCanvasChatTimelineResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["workflow_id", "conversation_id", "items", "next_cursor"], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    conversation_id: record.conversation_id === null
      ? null
      : expectNonEmptyString(record.conversation_id, `${path}.conversation_id`),
    items: expectArray(record.items, `${path}.items`).map((item, index) => {
      const itemPath = `${path}.items[${index}]`;
      const entry = expectRecord(item, itemPath);
      forbidUnknownFields(
        entry,
        [
          "entry_id",
          "workflow_id",
          "conversation_id",
          "sequence_no",
          "entry_type",
          "speaker",
          "content",
          "metadata",
          "command_plan",
          "action_receipt",
          "created_at",
        ],
        itemPath,
      );
      const entryType = expectString(entry.entry_type, `${itemPath}.entry_type`);
      if (
        entryType !== "message"
        && entryType !== "script_artifact"
        && entryType !== "command_plan"
        && entryType !== "action_receipt"
      ) {
        fail(`${itemPath}.entry_type`, "invalid timeline entry type");
      }
      const speaker = entry.speaker === null
        ? null
        : expectLiteral(entry.speaker, CHAT_MESSAGE_SPEAKERS, `${itemPath}.speaker`);
      if (entryType === "message" && speaker === null) {
        fail(`${itemPath}.speaker`, "message requires speaker");
      }
      return {
        entry_id: expectNonEmptyString(entry.entry_id, `${itemPath}.entry_id`),
        workflow_id: expectNonEmptyString(entry.workflow_id, `${itemPath}.workflow_id`),
        conversation_id: expectNonEmptyString(entry.conversation_id, `${itemPath}.conversation_id`),
        sequence_no: expectPositiveInteger(entry.sequence_no, `${itemPath}.sequence_no`),
        entry_type: entryType,
        speaker,
        content: expectString(entry.content, `${itemPath}.content`),
        metadata: optionalUnknownRecord(entry.metadata, `${itemPath}.metadata`, {}),
        command_plan: entry.command_plan === null || entry.command_plan === undefined
          ? null
          : normalizeAgentCommandPlanV2(entry.command_plan, `${itemPath}.command_plan`),
        action_receipt: entry.action_receipt === null || entry.action_receipt === undefined
          ? null
          : normalizeAgentActionReceiptV2(entry.action_receipt, `${itemPath}.action_receipt`),
        created_at: expectIsoDateTimeString(entry.created_at, `${itemPath}.created_at`),
      };
    }),
    next_cursor: expectNonNegativeInteger(record.next_cursor, `${path}.next_cursor`),
  };
}

export function normalizeChatTurnAcceptedV2(
  value: unknown,
  path = "chatAccepted",
): ChatTurnAcceptedV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    ["workflow_id", "conversation_id", "message_id", "turn_id", "status", "events_cursor"],
    path,
  );
  if (record.status !== "queued") fail(`${path}.status`, "expected queued");
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    conversation_id: expectNonEmptyString(record.conversation_id, `${path}.conversation_id`),
    message_id: record.message_id === null
      ? null
      : expectNonEmptyString(record.message_id, `${path}.message_id`),
    turn_id: expectNonEmptyString(record.turn_id, `${path}.turn_id`),
    status: "queued",
    events_cursor: expectNonNegativeInteger(record.events_cursor, `${path}.events_cursor`),
  };
}

export function normalizeAgentCanvasChatTurnV2(
  value: unknown,
  path = "chatTurn",
): AgentCanvasChatTurnV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "turn_id",
      "workflow_id",
      "conversation_id",
      "status",
      "turn_kind",
      "request",
      "error_code",
      "error_message",
      "created_at",
      "updated_at",
    ],
    path,
  );
  const status = expectString(record.status, `${path}.status`);
  if (!["queued", "running", "completed", "failed"].includes(status)) {
    fail(`${path}.status`, "invalid chat turn status");
  }
  const turnKind = expectString(record.turn_kind, `${path}.turn_kind`);
  if (turnKind !== "message" && turnKind !== "proposal_action" && turnKind !== "command_action") {
    fail(`${path}.turn_kind`, "invalid chat turn kind");
  }
  return {
    turn_id: expectNonEmptyString(record.turn_id, `${path}.turn_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    conversation_id: expectNonEmptyString(record.conversation_id, `${path}.conversation_id`),
    status: status as AgentCanvasChatTurnV2["status"],
    turn_kind: turnKind,
    request: expectUnknownRecord(record.request, `${path}.request`),
    error_code: nullableString(record.error_code, `${path}.error_code`),
    error_message: nullableString(record.error_message, `${path}.error_message`),
    created_at: expectNonEmptyString(record.created_at, `${path}.created_at`),
    updated_at: expectNonEmptyString(record.updated_at, `${path}.updated_at`),
  };
}

export function normalizeAgentCanvasVideoSkillRunV2(
  value: unknown,
  path = "videoSkillRun",
): AgentCanvasVideoSkillRunV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    ["skill_run_id", "workflow_id", "skill_id", "skill_version", "source_skill_run_id", "created_at"],
    path,
  );
  return {
    skill_run_id: expectNonEmptyString(record.skill_run_id, `${path}.skill_run_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    skill_id: expectNonEmptyString(record.skill_id, `${path}.skill_id`),
    skill_version: expectNonEmptyString(record.skill_version, `${path}.skill_version`),
    source_skill_run_id: record.source_skill_run_id === undefined
      ? null
      : nullableString(record.source_skill_run_id, `${path}.source_skill_run_id`),
    created_at: expectNonEmptyString(record.created_at, `${path}.created_at`),
  };
}

export function normalizeCanvasRunAcceptedV2(
  value: unknown,
  path = "runAccepted",
): CanvasRunAcceptedV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "workflow_id",
      "execution_id",
      "status",
      "accepted_node_ids",
      "joined_node_ids",
      "skipped",
      "waiting_node_ids",
      "events_cursor",
    ],
    path,
  );
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    execution_id: expectNonEmptyString(record.execution_id, `${path}.execution_id`),
    status: expectLiteral(record.status, CANVAS_EXECUTION_STATUSES, `${path}.status`),
    accepted_node_ids: expectStringArray(record.accepted_node_ids, `${path}.accepted_node_ids`),
    joined_node_ids: expectStringArray(record.joined_node_ids, `${path}.joined_node_ids`),
    skipped: expectArray(record.skipped, `${path}.skipped`).map((item, index) => {
      const skipped = expectRecord(item, `${path}.skipped[${index}]`);
      forbidUnknownFields(skipped, ["node_id", "reason"], `${path}.skipped[${index}]`);
      return {
        node_id: expectNonEmptyString(skipped.node_id, `${path}.skipped[${index}].node_id`),
        reason: expectNonEmptyString(skipped.reason, `${path}.skipped[${index}].reason`),
      };
    }),
    waiting_node_ids: expectStringArray(record.waiting_node_ids, `${path}.waiting_node_ids`),
    events_cursor: expectNonNegativeInteger(record.events_cursor, `${path}.events_cursor`),
  };
}

export function normalizeCanvasRunCancelResponseV2(
  value: unknown,
  path = "runCancel",
): CanvasRunCancelResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["workflow_id", "execution_id", "status", "cancelled_node_ids", "events_cursor"], path);
  const status = expectString(record.status, `${path}.status`);
  if (status !== "cancellation_requested" && status !== "cancelled") {
    fail(`${path}.status`, "invalid cancellation status");
  }
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    execution_id: expectNonEmptyString(record.execution_id, `${path}.execution_id`),
    status,
    cancelled_node_ids: optionalStringArray(record.cancelled_node_ids, `${path}.cancelled_node_ids`, []),
    events_cursor: expectNonNegativeInteger(record.events_cursor, `${path}.events_cursor`),
  };
}

export function normalizeCanvasRuntimeEventsResponseV2(
  value: unknown,
  path = "events",
): CanvasRuntimeEventsResponseV2 {
  const record = expectRecord(value, path);
  if ("items" in record || "next_cursor" in record) {
    forbidUnknownFields(record, ["items", "next_cursor"], path);
    return {
      workflow_id: null,
      events: expectArray(record.items, `${path}.items`).map((item, index) =>
        normalizeCanvasRuntimeEventV2(item, `${path}.items[${index}]`),
      ),
      next_after_seq: expectNonNegativeInteger(record.next_cursor, `${path}.next_cursor`),
    };
  }
  forbidUnknownFields(record, ["workflow_id", "events", "next_after_seq"], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    events: expectArray(record.events, `${path}.events`).map((item, index) =>
      normalizeCanvasRuntimeEventV2(item, `${path}.events[${index}]`),
    ),
    next_after_seq: expectNonNegativeInteger(record.next_after_seq, `${path}.next_after_seq`),
  };
}

export function normalizeEditingExportAcceptedV2(
  value: unknown,
  path = "editingExportAccepted",
): EditingExportAcceptedV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "workflow_id",
      "node_id",
      "export_id",
      "status",
      "manifest_revision",
      "ready_video_node_ids",
      "skipped_inputs",
      "bgm_node_id",
      "events_cursor",
    ],
    path,
  );
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    export_id: expectNonEmptyString(record.export_id, `${path}.export_id`),
    status: expectLiteral(record.status, EDITING_EXPORT_STATUSES, `${path}.status`),
    manifest_revision: expectNonNegativeInteger(record.manifest_revision, `${path}.manifest_revision`),
    ready_video_node_ids: expectStringArray(record.ready_video_node_ids, `${path}.ready_video_node_ids`),
    skipped_inputs: expectArray(record.skipped_inputs, `${path}.skipped_inputs`).map((item, index) =>
      normalizeEditingSkippedInputV2(item, `${path}.skipped_inputs[${index}]`),
    ),
    bgm_node_id: nullableString(record.bgm_node_id, `${path}.bgm_node_id`),
    events_cursor: expectNonNegativeInteger(record.events_cursor, `${path}.events_cursor`),
  };
}

export function normalizeEditingExportCancelResponseV2(
  value: unknown,
  path = "editingExportCancel",
): EditingExportCancelResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["workflow_id", "node_id", "export_id", "status", "events_cursor"], path);
  const status = expectString(record.status, `${path}.status`);
  if (status !== "cancellation_requested" && status !== "cancelled") {
    fail(`${path}.status`, "invalid cancellation status");
  }
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    export_id: expectNonEmptyString(record.export_id, `${path}.export_id`),
    status,
    events_cursor: expectNonNegativeInteger(record.events_cursor, `${path}.events_cursor`),
  };
}
