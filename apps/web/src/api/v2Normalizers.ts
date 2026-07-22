import type {
  AssetOwnerRelationV2,
  AssetOwnerResponseV2,
  AssetVersionV2,
  V2AssetLibraryEntityDetail,
  V2AssetLibraryEntitySummary,
  V2AssetLibraryListResponse,
  V2AssetLibraryMember,
  V2AssetLibraryPreviewMember,
  ProviderTaskV2,
  SlotVersionRelationV2,
  SlotVersionsResponseV2,
  V2InputAssetUploadItem,
  V2InputAssetUploadResponse,
  V2FinalCompositionTimeline,
  V2FinalTimelineClip,
  V2FinalTimelineRenderStartResponse,
  V2FinalTimelineRenderStateResponse,
  V2FinalTimelineResponse,
  V2FinalTimelineSource,
  V2FinalTimelineSourceImportResponse,
  V2FinalTimelineUpdateResponse,
  V2AssetLocatorResponse,
  V2AssetOwnerDisplay,
  V2ChatActionResponse,
  V2LinkedContextSummary,
  V2RegisterReferenceResponse,
  V2RecommendedCatalogStatus,
  V2ReferenceBinding,
  V2ReferenceSelectionsResponse,
  V2ScriptCharacter,
  V2ScriptConfirmResponse,
  V2ScriptDialogueLine,
  V2ScriptLocation,
  V2ScriptPlan,
  V2ScriptReadResponse,
  V2ScriptScene,
  V2ScriptSelectVersionResponse,
  V2ScriptShot,
  V2ScriptStructuralDiff,
  V2ScriptVersionListResponse,
  V2ScriptVersionSummary,
  V2Warning,
  WorkflowAssetListResponseV2,
  WorkflowAssetListRowV2,
  WorkflowAssetVersionsResponseV2,
  WorkflowDisplayEdgeV2,
  WorkflowAssetRelationV2,
  WorkflowItemV2,
  WorkflowNodeV2,
  WorkflowRuntimeEventV2,
  WorkflowRuntimeV2,
  WorkflowV2ItemRuntime,
  WorkflowV2NodeRuntime,
  WorkflowSlotV2,
  WorkflowV2SlotRuntime,
  WorkflowV2,
  V2SlotReferenceUploadResponse,
} from "../types-v2.ts";

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function stringValue(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function numberValue(value: unknown, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && Boolean(item));
}

function recordValue(value: unknown): Record<string, unknown> | undefined {
  return isRecord(value) ? value : undefined;
}

function recordArray(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Record<string, unknown> => isRecord(item));
}

function metadataWithExtras(record: Record<string, unknown>, canonicalFields: Set<string>): Record<string, unknown> | undefined {
  const extras = Object.fromEntries(Object.entries(record).filter(([key]) => !canonicalFields.has(key)));
  const metadata = {
    ...extras,
    ...(recordValue(record.metadata) ?? {}),
  };
  return Object.keys(metadata).length ? metadata : undefined;
}

function normalizeRuntimeError(value: unknown) {
  if (typeof value === "string" && value.trim()) {
    return { code: "runtime_error", message: value };
  }
  const record = recordValue(value);
  if (!record) return null;
  const code = stringValue(record.code);
  const message = stringValue(record.message);
  if (!code && !message) return null;
  return {
    code: code || "runtime_error",
    message: message || code || "Runtime error",
    stage: stringOrNull(record.stage) ?? null,
  };
}

export function normalizeV2WarningArray(value: unknown): V2Warning[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return { message: item };
      if (!isRecord(item)) return null;
      const message = stringValue(item.message, stringValue(item.detail, JSON.stringify(item)));
      const severity = stringValue(item.severity);
      return {
        code: stringValue(item.code) || undefined,
        message,
        severity: severity === "info" || severity === "warning" || severity === "error" ? severity : undefined,
        metadata: recordValue(item.metadata),
      };
    })
    .filter((item): item is V2Warning => Boolean(item?.message));
}

function warningArray(value: unknown): Array<{ code?: string; message?: string; [key: string]: unknown }> {
  return normalizeV2WarningArray(value) as Array<{ code?: string; message?: string; [key: string]: unknown }>;
}

function numberOrNull(value: unknown): number | null | undefined {
  if (value === null) return null;
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function stringOrNull(value: unknown): string | null | undefined {
  if (value === null) return null;
  return stringValue(value) || undefined;
}

function invalidScriptPayload(): never {
  throw new Error("invalid_v2_script_payload");
}

function requiredScriptRecord(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) invalidScriptPayload();
  return value;
}

function requiredScriptString(record: Record<string, unknown>, key: string): string {
  const value = stringValue(record[key]).trim();
  if (!value) invalidScriptPayload();
  return value;
}

function requiredScriptAspectRatio(record: Record<string, unknown>): V2ScriptPlan["aspect_ratio"] {
  const value = requiredScriptString(record, "aspect_ratio");
  if (!(["16:9", "9:16", "4:3", "3:4", "1:1", "21:9"] as const).includes(value as V2ScriptPlan["aspect_ratio"])) {
    invalidScriptPayload();
  }
  return value as V2ScriptPlan["aspect_ratio"];
}

function requiredScriptMaterializerMode(record: Record<string, unknown>): V2ScriptPlan["materializer_mode"] {
  const value = requiredScriptString(record, "materializer_mode");
  if (value !== "real" && value !== "mock") invalidScriptPayload();
  return value;
}

function requiredScriptSourceAction(record: Record<string, unknown>): V2ScriptVersionSummary["source_action"] {
  const value = requiredScriptString(record, "source_action");
  if (value !== "initial_planning" && value !== "script_editor_confirm" && value !== "agent_chat_edit") invalidScriptPayload();
  return value;
}

function nullableScriptString(value: unknown): string | null {
  return value === null ? null : stringValue(value) || null;
}

function nullableScriptSettingType(value: unknown): "interior" | "exterior" | null {
  return value === "interior" || value === "exterior" ? value : null;
}

function requiredScriptInteger(record: Record<string, unknown>, key: string, minimum: number): number {
  const value = record[key];
  if (typeof value !== "number" || !Number.isInteger(value) || value < minimum) invalidScriptPayload();
  return value;
}

function requiredScriptArray(record: Record<string, unknown>, key: string): unknown[] {
  const value = record[key];
  if (!Array.isArray(value) || value.length === 0) invalidScriptPayload();
  return value;
}

function requiredScriptStringArray(record: Record<string, unknown>, key: string): string[] {
  const value = record[key];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) invalidScriptPayload();
  return value;
}

function requiredScriptBoolean(record: Record<string, unknown>, key: string): boolean {
  if (typeof record[key] !== "boolean") invalidScriptPayload();
  return record[key];
}

function requiredScriptFalse(record: Record<string, unknown>, key: string): false {
  if (record[key] !== false) invalidScriptPayload();
  return false;
}

function optionalScriptArray(value: unknown): unknown[] {
  if (value === undefined) return [];
  if (!Array.isArray(value)) invalidScriptPayload();
  return value;
}

function scriptRecordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => isRecord(item)) : [];
}

function normalizeV2ScriptDialogueLine(value: unknown): V2ScriptDialogueLine {
  const record = requiredScriptRecord(value);
  return {
    dialogue_id: requiredScriptString(record, "dialogue_id"),
    character_id: requiredScriptString(record, "character_id"),
    performance_cue: nullableScriptString(record.performance_cue),
    text: requiredScriptString(record, "text"),
  };
}

function normalizeV2ScriptShot(value: unknown): V2ScriptShot {
  const record = requiredScriptRecord(value);
  return {
    shot_id: requiredScriptString(record, "shot_id"),
    scene_id: requiredScriptString(record, "scene_id"),
    shot_index: requiredScriptInteger(record, "shot_index", 1),
    product_ids: stringArray(record.product_ids),
    character_ids: stringArray(record.character_ids),
    scene_ids: stringArray(record.scene_ids),
    reference_item_ids: stringArray(record.reference_item_ids),
    description: requiredScriptString(record, "description"),
    dialogue: optionalScriptArray(record.dialogue).map(normalizeV2ScriptDialogueLine),
    narration: nullableScriptString(record.narration),
    visual_prompt: requiredScriptString(record, "visual_prompt"),
    duration_seconds: requiredScriptInteger(record, "duration_seconds", 1),
  };
}

function normalizeV2ScriptScene(value: unknown): V2ScriptScene {
  const record = requiredScriptRecord(value);
  return {
    scene_id: requiredScriptString(record, "scene_id"),
    title: requiredScriptString(record, "title"),
    description: requiredScriptString(record, "description"),
    location_id: nullableScriptString(record.location_id),
    shot_ids: stringArray(record.shot_ids),
    duration_seconds: requiredScriptInteger(record, "duration_seconds", 1),
    location_type: nullableScriptString(record.location_type),
    time_of_day: nullableScriptString(record.time_of_day),
    setting_type: nullableScriptSettingType(record.setting_type),
  };
}

function normalizeV2ScriptCharacter(value: unknown): V2ScriptCharacter {
  const record = requiredScriptRecord(value);
  return {
    character_id: requiredScriptString(record, "character_id"),
    display_name: requiredScriptString(record, "display_name"),
    description: requiredScriptString(record, "description"),
    role: requiredScriptString(record, "role"),
    visual_notes: requiredScriptString(record, "visual_notes"),
    gender: nullableScriptString(record.gender),
  };
}

function normalizeV2ScriptLocation(value: unknown): V2ScriptLocation {
  const record = requiredScriptRecord(value);
  return {
    location_id: requiredScriptString(record, "location_id"),
    display_name: requiredScriptString(record, "display_name"),
    description: requiredScriptString(record, "description"),
    visual_notes: requiredScriptString(record, "visual_notes"),
    location_type: nullableScriptString(record.location_type),
    time_of_day: nullableScriptString(record.time_of_day),
    setting_type: nullableScriptSettingType(record.setting_type),
  };
}

export function normalizeV2ScriptPlan(value: unknown): V2ScriptPlan {
  const record = requiredScriptRecord(value);
  if (record.script_plan_version !== 2) invalidScriptPayload();
  return {
    script_plan_version: 2,
    script_brief_id: requiredScriptString(record, "script_brief_id"),
    script_version_id: requiredScriptString(record, "script_version_id"),
    language: requiredScriptString(record, "language"),
    script_title: requiredScriptString(record, "script_title"),
    script_text: stringValue(record.script_text),
    scenes: requiredScriptArray(record, "scenes").map(normalizeV2ScriptScene),
    shots: requiredScriptArray(record, "shots").map(normalizeV2ScriptShot),
    characters: scriptRecordArray(record.characters).map(normalizeV2ScriptCharacter),
    locations: scriptRecordArray(record.locations).map(normalizeV2ScriptLocation),
    product_beats: stringArray(record.product_beats),
    tone: requiredScriptString(record, "tone"),
    visual_style: requiredScriptString(record, "visual_style"),
    duration_seconds: requiredScriptInteger(record, "duration_seconds", 1),
    aspect_ratio: requiredScriptAspectRatio(record),
    materializer_mode: requiredScriptMaterializerMode(record),
    model_id: nullableScriptString(record.model_id),
    selected_skill_ids: stringArray(record.selected_skill_ids),
    selected_skill_paths: stringArray(record.selected_skill_paths),
    skill_context_warnings: scriptRecordArray(record.skill_context_warnings),
    quality_notes: stringArray(record.quality_notes),
    materializer_version: nullableScriptString(record.materializer_version),
    metadata: recordValue(record.metadata) ?? {},
    warnings: scriptRecordArray(record.warnings),
  };
}

function normalizeV2ScriptStructuralDiff(value: unknown): V2ScriptStructuralDiff {
  const record = requiredScriptRecord(value);
  return {
    added_character_ids: requiredScriptStringArray(record, "added_character_ids"),
    archived_character_ids: requiredScriptStringArray(record, "archived_character_ids"),
    reactivated_character_ids: requiredScriptStringArray(record, "reactivated_character_ids"),
    updated_character_ids: requiredScriptStringArray(record, "updated_character_ids"),
    added_location_ids: requiredScriptStringArray(record, "added_location_ids"),
    archived_location_ids: requiredScriptStringArray(record, "archived_location_ids"),
    reactivated_location_ids: requiredScriptStringArray(record, "reactivated_location_ids"),
    updated_location_ids: requiredScriptStringArray(record, "updated_location_ids"),
    added_scene_ids: requiredScriptStringArray(record, "added_scene_ids"),
    archived_scene_ids: requiredScriptStringArray(record, "archived_scene_ids"),
    reactivated_scene_ids: requiredScriptStringArray(record, "reactivated_scene_ids"),
    updated_scene_ids: requiredScriptStringArray(record, "updated_scene_ids"),
    added_shot_ids: requiredScriptStringArray(record, "added_shot_ids"),
    archived_shot_ids: requiredScriptStringArray(record, "archived_shot_ids"),
    reactivated_shot_ids: requiredScriptStringArray(record, "reactivated_shot_ids"),
    updated_shot_ids: requiredScriptStringArray(record, "updated_shot_ids"),
    added_dialogue_ids: requiredScriptStringArray(record, "added_dialogue_ids"),
    archived_dialogue_ids: requiredScriptStringArray(record, "archived_dialogue_ids"),
    updated_dialogue_ids: requiredScriptStringArray(record, "updated_dialogue_ids"),
    order_changed: requiredScriptBoolean(record, "order_changed"),
  };
}

function normalizeV2LinkedContextSummary(value: unknown): V2LinkedContextSummary {
  const record = requiredScriptRecord(value);
  return {
    updated_node_ids: requiredScriptStringArray(record, "updated_node_ids"),
    updated_item_ids: requiredScriptStringArray(record, "updated_item_ids"),
    updated_slot_ids: requiredScriptStringArray(record, "updated_slot_ids"),
    updated_fields: requiredScriptStringArray(record, "updated_fields"),
    selected_asset_versions_changed: requiredScriptFalse(record, "selected_asset_versions_changed"),
    provider_execution_started: requiredScriptFalse(record, "provider_execution_started"),
    refresh: requiredScriptStringArray(record, "refresh"),
  };
}

export function normalizeV2ScriptReadResponse(value: unknown): V2ScriptReadResponse {
  const record = requiredScriptRecord(value);
  const selectedScriptVersionId = requiredScriptString(record, "selected_script_version_id");
  const script = normalizeV2ScriptPlan(record.script);
  if (selectedScriptVersionId !== script.script_version_id) invalidScriptPayload();
  return {
    workflow_id: requiredScriptString(record, "workflow_id"),
    selected_script_version_id: selectedScriptVersionId,
    script,
    events_cursor: requiredScriptInteger(record, "events_cursor", 0),
  };
}

export function normalizeV2ScriptConfirmResponse(value: unknown): V2ScriptConfirmResponse {
  const record = requiredScriptRecord(value);
  return {
    ...normalizeV2ScriptReadResponse(record),
    structural_diff: normalizeV2ScriptStructuralDiff(record.structural_diff),
    linked_context: normalizeV2LinkedContextSummary(record.linked_context),
  };
}

export function normalizeV2ScriptSelectVersionResponse(value: unknown): V2ScriptSelectVersionResponse {
  return normalizeV2ScriptConfirmResponse(value);
}

function normalizeV2ScriptVersionSummary(value: unknown): V2ScriptVersionSummary {
  const record = requiredScriptRecord(value);
  return {
    script_version_id: requiredScriptString(record, "script_version_id"),
    parent_script_version_id: nullableScriptString(record.parent_script_version_id),
    created_at: requiredScriptString(record, "created_at"),
    source_action: requiredScriptSourceAction(record),
    script_title: requiredScriptString(record, "script_title"),
    content_hash: requiredScriptString(record, "content_hash"),
    structural_diff_summary: recordValue(record.structural_diff_summary) ?? {},
  };
}

export function normalizeV2ScriptVersionListResponse(value: unknown): V2ScriptVersionListResponse {
  const record = requiredScriptRecord(value);
  return {
    workflow_id: requiredScriptString(record, "workflow_id"),
    selected_script_version_id: requiredScriptString(record, "selected_script_version_id"),
    versions: scriptRecordArray(record.versions).map(normalizeV2ScriptVersionSummary),
    events_cursor: requiredScriptInteger(record, "events_cursor", 0),
  };
}

export function isWorkflowV2(value: unknown): value is WorkflowV2 {
  return isRecord(value) && value.workflow_schema_version === 2;
}

const RUNTIME_SLOT_FIELDS = new Set([
  "slot_id",
  "node_id",
  "item_id",
  "slot_type",
  "media_type",
  "status",
  "selected_asset_id",
  "selected_version_id",
  "current_working_asset_id",
  "current_working_version_id",
  "provider_task_id",
  "waiting_reason",
  "error",
  "started_at",
  "finished_at",
  "updated_at",
  "metadata",
]);

const RUNTIME_ITEM_FIELDS = new Set([
  "item_id",
  "node_id",
  "status",
  "active_slot_ids",
  "started_at",
  "finished_at",
  "updated_at",
  "metadata",
]);

const RUNTIME_NODE_FIELDS = new Set([
  "node_id",
  "status",
  "running_slot_ids",
  "waiting_slot_ids",
  "failed_slot_ids",
  "completed_slot_ids",
  "started_at",
  "finished_at",
  "updated_at",
  "metadata",
]);

function runtimeRecordMap<T>(value: unknown, normalize: (key: string, value: unknown) => T): Record<string, T> {
  if (!isRecord(value)) return {};
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, normalize(key, item)]));
}

function normalizeSlotRuntimeV2(key: string, value: unknown): WorkflowV2SlotRuntime {
  const record = isRecord(value) ? value : {};
  return {
    slot_id: stringValue(record.slot_id, key),
    node_id: stringValue(record.node_id),
    item_id: stringValue(record.item_id),
    slot_type: stringOrNull(record.slot_type),
    media_type: stringOrNull(record.media_type),
    status: stringValue(record.status, "ready"),
    selected_asset_id: stringOrNull(record.selected_asset_id),
    selected_version_id: stringOrNull(record.selected_version_id),
    current_working_asset_id: stringOrNull(record.current_working_asset_id),
    current_working_version_id: stringOrNull(record.current_working_version_id),
    provider_task_id: stringOrNull(record.provider_task_id),
    waiting_reason: stringOrNull(record.waiting_reason),
    error: normalizeRuntimeError(record.error),
    started_at: stringOrNull(record.started_at),
    finished_at: stringOrNull(record.finished_at),
    updated_at: stringOrNull(record.updated_at),
    metadata: metadataWithExtras(record, RUNTIME_SLOT_FIELDS),
  };
}

function normalizeItemRuntimeV2(key: string, value: unknown): WorkflowV2ItemRuntime {
  const record = isRecord(value) ? value : {};
  return {
    item_id: stringValue(record.item_id, key),
    node_id: stringValue(record.node_id),
    status: stringValue(record.status, "ready"),
    active_slot_ids: stringArray(record.active_slot_ids),
    started_at: stringOrNull(record.started_at),
    finished_at: stringOrNull(record.finished_at),
    updated_at: stringOrNull(record.updated_at),
    metadata: metadataWithExtras(record, RUNTIME_ITEM_FIELDS),
  };
}

function normalizeNodeRuntimeV2(key: string, value: unknown): WorkflowV2NodeRuntime {
  const record = isRecord(value) ? value : {};
  return {
    node_id: stringValue(record.node_id, key),
    status: stringValue(record.status, "ready"),
    running_slot_ids: stringArray(record.running_slot_ids),
    waiting_slot_ids: stringArray(record.waiting_slot_ids),
    failed_slot_ids: stringArray(record.failed_slot_ids),
    completed_slot_ids: stringArray(record.completed_slot_ids),
    started_at: stringOrNull(record.started_at),
    finished_at: stringOrNull(record.finished_at),
    updated_at: stringOrNull(record.updated_at),
    metadata: metadataWithExtras(record, RUNTIME_NODE_FIELDS),
  };
}

export function normalizeWorkflowRuntimeV2(value: unknown): WorkflowRuntimeV2 {
  const record = isRecord(value) ? value : {};
  const eventCursor = numberValue(record.events_cursor, numberValue(record.last_event_seq));

  return {
    workflow_id: stringValue(record.workflow_id),
    active_execution_id: stringOrNull(record.active_execution_id ?? record.execution_id),
    execution_status: stringOrNull(record.execution_status ?? record.status),
    running_slot_ids: stringArray(record.running_slot_ids),
    running_item_ids: stringArray(record.running_item_ids),
    running_node_ids: stringArray(record.running_node_ids),
    waiting_slot_ids: stringArray(record.waiting_slot_ids),
    waiting_item_ids: stringArray(record.waiting_item_ids),
    waiting_node_ids: stringArray(record.waiting_node_ids),
    failed_slot_ids: stringArray(record.failed_slot_ids),
    failed_item_ids: stringArray(record.failed_item_ids),
    failed_node_ids: stringArray(record.failed_node_ids),
    completed_slot_ids: stringArray(record.completed_slot_ids),
    completed_item_ids: stringArray(record.completed_item_ids),
    completed_node_ids: stringArray(record.completed_node_ids),
    blocked_slot_ids: stringArray(record.blocked_slot_ids),
    blocked_item_ids: stringArray(record.blocked_item_ids),
    blocked_node_ids: stringArray(record.blocked_node_ids),
    skipped_slot_ids: stringArray(record.skipped_slot_ids),
    skipped_item_ids: stringArray(record.skipped_item_ids),
    skipped_node_ids: stringArray(record.skipped_node_ids),
    node_runtime: runtimeRecordMap(record.node_runtime, normalizeNodeRuntimeV2),
    item_runtime: runtimeRecordMap(record.item_runtime, normalizeItemRuntimeV2),
    slot_runtime: runtimeRecordMap(record.slot_runtime, normalizeSlotRuntimeV2),
    events_cursor: eventCursor,
    updated_at: stringOrNull(record.updated_at),
    metadata: recordValue(record.metadata),
  };
}

export function normalizeWorkflowNodeV2(value: unknown): WorkflowNodeV2 {
  const record = isRecord(value) ? value : {};
  const metadata = recordValue(record.metadata) ?? {};
  return {
    node_id: stringValue(record.node_id),
    node_type: stringValue(record.node_type),
    title: stringValue(record.title, stringValue(record.node_id, "Untitled node")),
    status: stringValue(record.status, "not_ready"),
    position: isRecord(record.position) ? { x: numberValue(record.position.x), y: numberValue(record.position.y) } : undefined,
    not_ready_reason: record.not_ready_reason === null ? null : stringValue(record.not_ready_reason, stringValue(metadata.not_ready_reason)) || undefined,
    resolved_media_type: record.resolved_media_type === null || metadata.resolved_media_type === null ? null : (stringValue(record.resolved_media_type, stringValue(metadata.resolved_media_type)) as WorkflowNodeV2["resolved_media_type"]) || undefined,
    resolved_node_role: record.resolved_node_role === null || metadata.resolved_node_role === null ? null : stringValue(record.resolved_node_role, stringValue(metadata.resolved_node_role)) || undefined,
    metadata,
    items: recordArray(record.items).map(normalizeWorkflowItemV2),
  };
}

export function normalizeWorkflowItemV2(value: unknown): WorkflowItemV2 {
  const record = isRecord(value) ? value : {};
  const detailPrompts = recordValue(record.detail_prompts);
  const timelinePlan = recordValue(record.timeline_plan);
  return {
    item_id: stringValue(record.item_id),
    node_id: stringValue(record.node_id),
    item_type: stringValue(record.item_type),
    display_name: stringValue(record.display_name, stringValue(record.item_id, "Untitled item")),
    description: stringValue(record.description) || undefined,
    item_prompt: stringValue(record.item_prompt) || undefined,
    prompt_source: stringValue(record.prompt_source) || undefined,
    manual_prompt_dirty: typeof record.manual_prompt_dirty === "boolean" ? record.manual_prompt_dirty : undefined,
    status: stringValue(record.status, "ready"),
    lifecycle_state: stringValue(record.lifecycle_state, "active") as WorkflowItemV2["lifecycle_state"],
    shot_id: record.shot_id === null ? null : stringValue(record.shot_id) || undefined,
    shot_index: numberOrNull(record.shot_index),
    aspect_ratio: record.aspect_ratio === null ? null : stringValue(record.aspect_ratio) || undefined,
    duration_seconds: numberOrNull(record.duration_seconds),
    shot_summary_prompt: record.shot_summary_prompt === null ? null : stringValue(record.shot_summary_prompt) || undefined,
    detail_prompts: detailPrompts,
    reference_item_ids: stringArray(record.reference_item_ids),
    timeline_plan: timelinePlan,
    timeline_clips: recordArray(record.timeline_clips),
    metadata: recordValue(record.metadata),
    slots: recordArray(record.slots).map(normalizeWorkflowSlotV2),
  };
}

export function normalizeWorkflowSlotV2(value: unknown): WorkflowSlotV2 {
  const record = isRecord(value) ? value : {};
  const metadata = recordValue(record.metadata);
  return {
    slot_id: stringValue(record.slot_id),
    node_id: stringValue(record.node_id),
    item_id: stringValue(record.item_id),
    slot_type: stringValue(record.slot_type),
    media_type: stringValue(record.media_type, "image") as WorkflowSlotV2["media_type"],
    required: typeof record.required === "boolean" ? record.required : true,
    status: stringValue(record.status, "empty"),
    slot_prompt: stringValue(record.slot_prompt) || undefined,
    system_suggested_prompt: typeof record.system_suggested_prompt === "string" ? record.system_suggested_prompt : undefined,
    user_prompt: typeof record.user_prompt === "string" ? record.user_prompt : undefined,
    negative_prompt: stringValue(record.negative_prompt) || undefined,
    media_prompt_asset_ids: stringArray(record.media_prompt_asset_ids),
    implicit_reference_ids: stringArray(record.implicit_reference_ids),
    explicit_reference_ids: stringArray(record.explicit_reference_ids),
    dependency_slot_ids: stringArray(record.dependency_slot_ids),
    provider: record.provider === null ? null : stringValue(record.provider) || undefined,
    provider_params: recordValue(record.provider_params),
    selected_asset_id: record.selected_asset_id === null ? null : stringValue(record.selected_asset_id) || undefined,
    current_working_asset_id: record.current_working_asset_id === null ? null : stringValue(record.current_working_asset_id) || undefined,
    current_working_version_id: record.current_working_version_id === null ? null : stringValue(record.current_working_version_id) || undefined,
    history_version_ids: stringArray(record.history_version_ids),
    prompt_source: stringValue(record.prompt_source) || undefined,
    manual_prompt_dirty: typeof record.manual_prompt_dirty === "boolean" ? record.manual_prompt_dirty : undefined,
    dialogue_prompt: record.dialogue_prompt === null ? null : stringValue(record.dialogue_prompt) || undefined,
    audio_description_prompt: record.audio_description_prompt === null ? null : stringValue(record.audio_description_prompt) || undefined,
    voice_style_prompt: record.voice_style_prompt === null ? null : stringValue(record.voice_style_prompt) || undefined,
    negative_constraints: record.negative_constraints === null ? null : stringValue(record.negative_constraints) || undefined,
    warnings: warningArray(record.warnings ?? metadata?.warnings ?? metadata?.warning),
    metadata,
  };
}

export function normalizeAssetVersionV2(value: unknown): AssetVersionV2 {
  const record = isRecord(value) ? value : {};
  return {
    asset_id: stringValue(record.asset_id),
    version_id: stringValue(record.version_id),
    media_type: stringValue(record.media_type, "image") as AssetVersionV2["media_type"],
    source_type: stringValue(record.source_type, "generated"),
    mime_type: record.mime_type === null ? null : stringValue(record.mime_type) || undefined,
    file_path: record.file_path === null ? null : stringValue(record.file_path) || undefined,
    public_url: record.public_url === null ? null : stringValue(record.public_url) || undefined,
    thumbnail_path: record.thumbnail_path === null ? null : stringValue(record.thumbnail_path, stringValue(record.thumbnail_url)) || undefined,
    proxy_path: record.proxy_path === null ? null : stringValue(record.proxy_path) || undefined,
    rendition_paths: stringArray(record.rendition_paths),
    duration_seconds: numberOrNull(record.duration_seconds),
    width: numberOrNull(record.width),
    height: numberOrNull(record.height),
    status: record.status === null ? null : stringValue(record.status) || undefined,
    quality_status: record.quality_status === null ? null : stringValue(record.quality_status) || undefined,
    workflow_id: record.workflow_id === null ? null : stringValue(record.workflow_id) || undefined,
    node_id: record.node_id === null ? null : stringValue(record.node_id) || undefined,
    item_id: record.item_id === null ? null : stringValue(record.item_id) || undefined,
    slot_id: record.slot_id === null ? null : stringValue(record.slot_id) || undefined,
    semantic_type: stringValue(record.semantic_type),
    prompt_snapshot: record.prompt_snapshot === null ? null : isRecord(record.prompt_snapshot) ? record.prompt_snapshot : stringValue(record.prompt_snapshot) || undefined,
    provider_payload_snapshot: recordValue(record.provider_payload_snapshot),
    reference_asset_ids: stringArray(record.reference_asset_ids),
    library_entity_id: record.library_entity_id === null ? null : stringValue(record.library_entity_id) || undefined,
    created_at: stringValue(record.created_at) || undefined,
    created_by: record.created_by === null ? null : stringValue(record.created_by) || undefined,
    metadata: recordValue(record.metadata),
  };
}

export function normalizeV2FinalTimelineResponse(value: unknown): V2FinalTimelineResponse {
  const record = isRecord(value) ? value : {};
  return {
    workflow_id: stringValue(record.workflow_id),
    node_id: "final-composition",
    item_id: stringValue(record.item_id),
    source: stringValue(record.source, "saved"),
    timeline: normalizeV2FinalCompositionTimeline(record.timeline),
    available_sources: recordArray(record.available_sources).map(normalizeV2FinalTimelineSource),
    runtime: record.runtime ? normalizeWorkflowRuntimeV2(record.runtime) : null,
  };
}

export function normalizeV2FinalTimelineUpdateResponse(value: unknown): V2FinalTimelineUpdateResponse {
  const record = isRecord(value) ? value : {};
  return {
    workflow_id: stringValue(record.workflow_id),
    timeline: normalizeV2FinalCompositionTimeline(record.timeline),
    changed_clip_ids: stringArray(record.changed_clip_ids),
    runtime: record.runtime ? normalizeWorkflowRuntimeV2(record.runtime) : null,
  };
}

export function normalizeV2FinalTimelineSourceImportResponse(value: unknown): V2FinalTimelineSourceImportResponse {
  const record = isRecord(value) ? value : {};
  return {
    workflow_id: stringValue(record.workflow_id),
    source: normalizeV2FinalTimelineSource(record.source),
  };
}

export function normalizeV2FinalTimelineRenderStartResponse(value: unknown): V2FinalTimelineRenderStartResponse {
  const record = isRecord(value) ? value : {};
  return {
    workflow_id: stringValue(record.workflow_id),
    render_id: stringValue(record.render_id),
    status: "queued",
    timeline_id: stringValue(record.timeline_id),
    timeline_version: numberValue(record.timeline_version),
    events_cursor: numberValue(record.events_cursor),
  };
}

export function normalizeV2FinalTimelineRenderStateResponse(value: unknown): V2FinalTimelineRenderStateResponse {
  const record = isRecord(value) ? value : {};
  return {
    workflow_id: stringValue(record.workflow_id),
    render_id: stringValue(record.render_id),
    slot_id: stringValue(record.slot_id),
    status: normalizeV2FinalTimelineRenderStatus(record.status),
    timeline_id: stringValue(record.timeline_id),
    timeline_version: numberValue(record.timeline_version),
    events_cursor: numberValue(record.events_cursor),
    progress_seconds: numberOrNull(record.progress_seconds) ?? null,
    total_seconds: numberOrNull(record.total_seconds) ?? null,
    progress_percent: numberOrNull(record.progress_percent) ?? null,
    asset_id: stringOrNull(record.asset_id) ?? null,
    version_id: stringOrNull(record.version_id) ?? null,
    error_code: stringOrNull(record.error_code) ?? null,
    error_message: stringOrNull(record.error_message) ?? null,
    created_at: stringValue(record.created_at),
    updated_at: stringValue(record.updated_at),
  };
}

function normalizeV2FinalCompositionTimeline(value: unknown): V2FinalCompositionTimeline {
  const record = isRecord(value) ? value : {};
  const resolution = recordValue(record.resolution);
  return {
    timeline_id: stringValue(record.timeline_id),
    version: numberValue(record.version, 1),
    duration_seconds: numberValue(record.duration_seconds),
    aspect_ratio: stringValue(record.aspect_ratio, "16:9"),
    resolution: {
      width: numberValue(resolution?.width, 1280),
      height: numberValue(resolution?.height, 720),
    },
    fps: numberValue(record.fps, 24),
    tracks: recordArray(record.tracks).map((track, index) => ({
      track_id: stringValue(track.track_id, `track-${index + 1}`),
      track_type: normalizeTimelineTrackType(track.track_type),
      order: numberValue(track.order, 1),
      enabled: track.enabled !== false,
      metadata: recordValue(track.metadata) ?? {},
    })),
    clips: recordArray(record.clips).map(normalizeV2FinalTimelineClip),
    metadata: recordValue(record.metadata) ?? {},
  };
}

function normalizeV2FinalTimelineClip(record: Record<string, unknown>, index: number): V2FinalTimelineClip {
  const transform = recordValue(record.transform);
  const audio = recordValue(record.audio);
  const color = recordValue(record.color);
  const subtitleStyle = recordValue(record.subtitle_style);
  return {
    clip_id: stringValue(record.clip_id, `clip-${index + 1}`),
    track_id: stringValue(record.track_id),
    clip_type: normalizeTimelineTrackType(record.clip_type),
    source_asset_id: stringOrNull(record.source_asset_id) ?? null,
    source_version_id: stringOrNull(record.source_version_id) ?? null,
    source_slot_id: stringOrNull(record.source_slot_id) ?? null,
    start_time: numberValue(record.start_time),
    duration: numberValue(record.duration),
    trim_in: numberValue(record.trim_in),
    trim_out: numberOrNull(record.trim_out) ?? null,
    volume: numberValue(record.volume, 1),
    muted: Boolean(record.muted),
    enabled: record.enabled !== false,
    transform: {
      x: numberValue(transform?.x), y: numberValue(transform?.y), scale_x: numberValue(transform?.scale_x, 1), scale_y: numberValue(transform?.scale_y, 1), rotation_degrees: numberValue(transform?.rotation_degrees), opacity: numberValue(transform?.opacity, 1), fit: transform?.fit === "cover" ? "cover" : "contain",
    },
    audio: {
      volume: numberValue(audio?.volume, 1), muted: Boolean(audio?.muted), fade_in_seconds: numberValue(audio?.fade_in_seconds), fade_out_seconds: numberValue(audio?.fade_out_seconds),
    },
    color: {
      preset_id: normalizeTimelineColorPreset(color?.preset_id), brightness: numberValue(color?.brightness), contrast: numberValue(color?.contrast, 1), saturation: numberValue(color?.saturation, 1), exposure: numberValue(color?.exposure), temperature: numberValue(color?.temperature), tint: numberValue(color?.tint), hue: numberValue(color?.hue),
    },
    text: stringOrNull(record.text) ?? null,
    subtitle_style: {
      font_size: numberValue(subtitleStyle?.font_size, 42), color: stringValue(subtitleStyle?.color, "#FFFFFF"), position: subtitleStyle?.position === "top_center" || subtitleStyle?.position === "center" ? subtitleStyle.position : "bottom_center",
    },
    metadata: recordValue(record.metadata) ?? {},
  };
}

function normalizeV2FinalTimelineSource(value: unknown): V2FinalTimelineSource {
  const record = isRecord(value) ? value : {};
  return {
    asset_id: stringValue(record.asset_id),
    version_id: stringValue(record.version_id),
    media_type: record.media_type === "audio" || record.media_type === "image" ? record.media_type : "video",
    display_name: stringValue(record.display_name, stringValue(record.asset_id)),
    public_url: stringOrNull(record.public_url),
    thumbnail_url: stringOrNull(record.thumbnail_url ?? record.thumbnail_path),
    duration_seconds: numberOrNull(record.duration_seconds),
    origin: stringValue(record.origin, "workflow"),
  };
}

function normalizeTimelineTrackType(value: unknown): "video" | "audio" | "image" | "subtitle" {
  return value === "audio" || value === "image" || value === "subtitle" ? value : "video";
}

function normalizeV2FinalTimelineRenderStatus(value: unknown): V2FinalTimelineRenderStateResponse["status"] {
  if (value === "queued" || value === "running" || value === "completed" || value === "failed" || value === "cancellation_requested" || value === "cancelled") return value;
  throw new Error(`Invalid final timeline render status: ${String(value)}`);
}

function normalizeTimelineColorPreset(value: unknown): "none" | "warm" | "cool" | "high_contrast" | "muted" {
  return value === "warm" || value === "cool" || value === "high_contrast" || value === "muted" ? value : "none";
}

export function normalizeWorkflowAssetListRowV2(value: unknown): WorkflowAssetListRowV2 {
  const record = isRecord(value) ? value : {};
  const asset = normalizeAssetVersionV2({
    ...record,
    node_id: record.node_id ?? record.owner_node_id,
    item_id: record.item_id ?? record.owner_item_id,
    slot_id: record.slot_id ?? record.owner_slot_id,
    source_type: record.source_type ?? record.state ?? "generated",
    thumbnail_path: record.thumbnail_path ?? record.thumbnail_url,
  });
  return {
    ...asset,
    state: stringOrNull(record.state),
    locator: stringOrNull(record.locator),
    display_name: stringOrNull(record.display_name),
    thumbnail_url: stringOrNull(record.thumbnail_url),
    prompt_summary: stringOrNull(record.prompt_summary),
    provider_prompt: stringOrNull(record.provider_prompt),
    quality_issues: recordArray(record.quality_issues),
    relation_ids: stringArray(record.relation_ids),
    owner_display_name: stringOrNull(record.owner_display_name ?? record.display_name),
    owner_type: stringOrNull(record.owner_type),
    owner_node_id: stringOrNull(record.owner_node_id ?? record.node_id),
    owner_item_id: stringOrNull(record.owner_item_id ?? record.item_id),
    owner_slot_id: stringOrNull(record.owner_slot_id ?? record.slot_id),
  };
}

export function normalizeWorkflowAssetListResponseV2(value: unknown): WorkflowAssetListResponseV2 {
  const record = isRecord(value) ? value : {};
  return {
    workflow_id: stringValue(record.workflow_id),
    assets: recordArray(record.assets ?? record.items).map(normalizeWorkflowAssetListRowV2),
  };
}

export function normalizeWorkflowAssetVersionsResponseV2(value: unknown): WorkflowAssetVersionsResponseV2 {
  const record = isRecord(value) ? value : {};
  return {
    workflow_id: stringValue(record.workflow_id),
    asset_id: stringValue(record.asset_id),
    selected_version_id: stringOrNull(record.selected_version_id),
    working_version_id: stringOrNull(record.working_version_id),
    versions: recordArray(record.versions ?? record.assets ?? record.items).map(normalizeWorkflowAssetListRowV2),
  };
}

export function normalizeSlotVersionRelationV2(value: unknown): SlotVersionRelationV2 {
  const record = isRecord(value) ? value : {};
  return {
    relation_id: stringOrNull(record.relation_id ?? record.binding_id ?? record.id),
    relation_type: stringOrNull(record.relation_type ?? record.type),
    workflow_id: stringOrNull(record.workflow_id),
    node_id: stringOrNull(record.node_id),
    item_id: stringOrNull(record.item_id),
    slot_id: stringOrNull(record.slot_id),
    asset_id: stringOrNull(record.asset_id),
    version_id: stringOrNull(record.version_id),
    created_at: stringOrNull(record.created_at),
    metadata: recordValue(record.metadata),
  };
}

export function normalizeWorkflowAssetRelationV2(value: unknown): WorkflowAssetRelationV2 {
  const record = isRecord(value) ? value : {};
  return {
    relation_id: stringOrNull(record.relation_id ?? record.binding_id ?? record.id),
    relation_type: stringOrNull(record.relation_type ?? record.type),
    workflow_id: stringOrNull(record.workflow_id),
    target_type: record.target_type === null ? null : stringValue(record.target_type) || undefined,
    target_id: record.target_id === null ? null : stringValue(record.target_id) || undefined,
    node_id: stringOrNull(record.node_id),
    item_id: stringOrNull(record.item_id),
    slot_id: stringOrNull(record.slot_id),
    source_asset_id: stringOrNull(record.source_asset_id ?? record.asset_id),
    asset_id: stringOrNull(record.asset_id ?? record.source_asset_id),
    version_id: stringOrNull(record.version_id),
    reference_kind: record.reference_kind === null ? null : stringValue(record.reference_kind) || undefined,
    semantic_type: stringOrNull(record.semantic_type),
    created_at: stringOrNull(record.created_at),
    metadata: recordValue(record.metadata),
  };
}

export function normalizeSlotVersionsResponseV2(value: unknown): SlotVersionsResponseV2 {
  const record = isRecord(value) ? value : {};
  const versions = Array.isArray(record.versions)
    ? record.versions
    : Array.isArray(record.assets)
      ? record.assets
      : Array.isArray(record.items)
        ? record.items
        : [];
  const relations = Array.isArray(record.relations) ? record.relations : Array.isArray(record.version_relations) ? record.version_relations : [];
  return {
    workflow_id: stringValue(record.workflow_id),
    slot_id: stringValue(record.slot_id),
    selected_asset_id: stringOrNull(record.selected_asset_id),
    working_asset_id: stringOrNull(record.working_asset_id ?? record.current_working_asset_id),
    current_working_version_id: stringOrNull(record.current_working_version_id),
    versions: versions.map(normalizeAssetVersionV2),
    relations: relations.map(normalizeSlotVersionRelationV2),
    metadata: recordValue(record.metadata),
  };
}

export function normalizeAssetOwnerRelationV2(value: unknown): AssetOwnerRelationV2 {
  const record = isRecord(value) ? value : {};
  return {
    relation_id: stringOrNull(record.relation_id ?? record.id),
    relation_type: stringOrNull(record.relation_type ?? record.type),
    workflow_id: stringOrNull(record.workflow_id),
    node_id: stringOrNull(record.node_id),
    item_id: stringOrNull(record.item_id),
    slot_id: stringOrNull(record.slot_id),
    asset_id: stringOrNull(record.asset_id),
    version_id: stringOrNull(record.version_id),
    created_at: stringOrNull(record.created_at),
    metadata: recordValue(record.metadata),
  };
}

export function normalizeAssetOwnerResponseV2(value: unknown): AssetOwnerResponseV2 {
  const record = isRecord(value) ? value : {};
  const owner = recordValue(record.owner);
  const relations = Array.isArray(record.relations) ? record.relations : [];
  return {
    workflow_id: stringValue(record.workflow_id),
    asset_id: stringValue(record.asset_id),
    owner: owner
      ? {
          node_id: stringOrNull(owner.node_id),
          item_id: stringOrNull(owner.item_id),
          slot_id: stringOrNull(owner.slot_id),
          owner_display_name: stringOrNull(owner.owner_display_name ?? owner.display_name),
          owner_type: stringOrNull(owner.owner_type ?? owner.type),
          owner_node_id: stringOrNull(owner.owner_node_id ?? owner.node_id),
          owner_item_id: stringOrNull(owner.owner_item_id ?? owner.item_id),
          owner_slot_id: stringOrNull(owner.owner_slot_id ?? owner.slot_id),
          relation_type: stringOrNull(owner.relation_type ?? owner.type),
          metadata: recordValue(owner.metadata),
        }
      : null,
    relations: relations.map(normalizeAssetOwnerRelationV2),
    metadata: recordValue(record.metadata),
  };
}

function normalizeV2AssetOwnerDisplay(value: unknown): (V2AssetOwnerDisplay & { relation_type?: string | null }) | null {
  const record = recordValue(value);
  if (!record) return null;
  const owner = {
    owner_display_name: stringOrNull(record.owner_display_name ?? record.display_name),
    owner_type: stringOrNull(record.owner_type ?? record.type),
    owner_node_id: stringOrNull(record.owner_node_id ?? record.node_id),
    owner_item_id: stringOrNull(record.owner_item_id ?? record.item_id),
    owner_slot_id: stringOrNull(record.owner_slot_id ?? record.slot_id),
    relation_type: stringOrNull(record.relation_type),
  };
  const hasOwnerPayload = [
    "owner_display_name",
    "display_name",
    "owner_type",
    "type",
    "owner_node_id",
    "node_id",
    "owner_item_id",
    "item_id",
    "owner_slot_id",
    "slot_id",
    "relation_type",
  ].some((key) => key in record);
  return hasOwnerPayload ? owner : null;
}

function normalizeV2LocatorTarget(record: Record<string, unknown>): V2AssetLocatorResponse["target"] {
  if (recordValue(record.target)) return record.target as V2AssetLocatorResponse["target"];
  const targetType = stringValue(record.target_type);
  if (!targetType) return null;
  return {
    target_type: targetType,
    node_id: stringOrNull(record.node_id),
    item_id: stringOrNull(record.item_id),
    slot_id: stringOrNull(record.slot_id),
    asset_id: stringOrNull(record.asset_id),
    version_id: stringOrNull(record.version_id),
  };
}

export function normalizeV2AssetLocatorResponse(value: unknown): V2AssetLocatorResponse {
  const record = isRecord(value) ? value : {};
  const assetRecord = recordValue(record.asset) ?? recordValue(record.asset_version) ?? {
    asset_id: record.asset_id,
    version_id: record.version_id,
    media_type: record.media_type,
    source_type: record.source_type,
    mime_type: record.mime_type,
    file_path: record.file_path,
    public_url: record.public_url,
    thumbnail_path: record.thumbnail_path,
    proxy_path: record.proxy_path,
    rendition_paths: record.rendition_paths,
    duration_seconds: record.duration_seconds,
    width: record.width,
    height: record.height,
    status: record.status,
    quality_status: record.quality_status,
    workflow_id: record.workflow_id,
    node_id: record.node_id,
    item_id: record.item_id,
    slot_id: record.slot_id,
    semantic_type: record.semantic_type,
    created_at: record.created_at,
    metadata: record.metadata,
  };
  const owner = normalizeV2AssetOwnerDisplay(record.owner)
    ?? normalizeV2AssetOwnerDisplay(record);
  return {
    workflow_id: stringValue(record.workflow_id),
    locator: stringValue(record.locator),
    asset: normalizeAssetVersionV2(assetRecord),
    target: normalizeV2LocatorTarget(record),
    owner,
    warnings: normalizeV2WarningArray(record.warnings),
  };
}

export function normalizeWorkflowDisplayEdgeV2(value: unknown): WorkflowDisplayEdgeV2 {
  const record = isRecord(value) ? value : {};
  const source = stringValue(record.source, stringValue(record.source_node_id));
  const target = stringValue(record.target, stringValue(record.target_node_id));
  return {
    id: stringValue(record.id, stringValue(record.edge_id, `${source}-${target}`)),
    source,
    target,
    edge_kind: stringValue(record.edge_kind, "display_flow"),
    source_handle: record.source_handle === null ? null : stringValue(record.source_handle) || undefined,
    target_handle: record.target_handle === null ? null : stringValue(record.target_handle) || undefined,
    metadata: recordValue(record.metadata),
  };
}

export function normalizeWorkflowRuntimeEventV2(value: unknown): WorkflowRuntimeEventV2 {
  const record = isRecord(value) ? value : {};
  return {
    seq: numberValue(record.seq),
    event_type: stringValue(record.event_type),
    workflow_id: stringValue(record.workflow_id),
    node_id: record.node_id === null ? null : stringValue(record.node_id) || undefined,
    item_id: record.item_id === null ? null : stringValue(record.item_id) || undefined,
    slot_id: record.slot_id === null ? null : stringValue(record.slot_id) || undefined,
    asset_id: record.asset_id === null ? null : stringValue(record.asset_id) || undefined,
    version_id: record.version_id === null ? null : stringValue(record.version_id) || undefined,
    created_at: stringValue(record.created_at) || undefined,
    payload: recordValue(record.payload) ?? {},
  };
}

function normalizeWorkflowRuntimeEventArrayV2(value: unknown, context: Record<string, unknown>): WorkflowRuntimeEventV2[] {
  if (!Array.isArray(value)) return [];
  const workflowRecord = recordValue(context.workflow);
  const workflowId = stringValue(context.workflow_id, stringValue(workflowRecord?.workflow_id));
  const baseSeq = numberValue(context.events_cursor, numberValue(context.next_after_seq));
  return value.map((item, index) => {
    if (typeof item === "string") {
      return normalizeWorkflowRuntimeEventV2({
        seq: baseSeq + index + 1,
        event_type: item,
        workflow_id: workflowId,
        payload: { source: "chat_action_response" },
      });
    }
    return normalizeWorkflowRuntimeEventV2(item);
  });
}

export function normalizeWorkflowV2RunResponse(value: unknown) {
  const record = isRecord(value) ? value : {};
  const workflowRecord = recordValue(record.workflow);
  const workflow = workflowRecord
    ? normalizeWorkflowV2(workflowRecord)
    : isWorkflowV2(record)
      ? normalizeWorkflowV2(record)
      : null;
  return {
    workflow,
    workflow_id: stringValue(record.workflow_id, workflow?.workflow_id ?? ""),
    execution_id: stringOrNull(record.execution_id),
    status: stringOrNull(record.status),
    runtime: record.runtime ? normalizeWorkflowRuntimeV2(record.runtime) : null,
    events_cursor: typeof record.events_cursor === "number" && Number.isFinite(record.events_cursor) ? record.events_cursor : null,
    executed_slot_ids: stringArray(record.executed_slot_ids),
    provider_calls: recordArray(record.provider_calls),
    waiting_slot_ids: stringArray(record.waiting_slot_ids),
    failed_slot_ids: stringArray(record.failed_slot_ids),
    blocked_slot_ids: stringArray(record.blocked_slot_ids),
    created_item_ids: stringArray(record.created_item_ids),
    created_slot_ids: stringArray(record.created_slot_ids),
    message: stringOrNull(record.message),
  };
}

export function normalizeWorkflowV2MutationResponse(value: unknown): WorkflowV2 {
  const record = isRecord(value) ? value : {};
  return normalizeWorkflowV2(record.workflow ?? record);
}

export function normalizeWorkflowV2ReferenceMutationResponse(value: unknown) {
  const record = isRecord(value) ? value : {};
  const assets = recordArray(record.assets ?? record.asset_versions).map(normalizeAssetVersionV2);
  return {
    workflow: record.workflow ? normalizeWorkflowV2(record.workflow) : null,
    relation: record.relation ? normalizeWorkflowAssetRelationV2(record.relation) : null,
    assets,
    warnings: normalizeV2WarningArray(record.warnings),
    removed_relation_id: stringOrNull(record.removed_relation_id),
  };
}

function normalizeV2AssetLibraryPreviewMember(value: unknown): V2AssetLibraryPreviewMember | null {
  const record = recordValue(value);
  if (!record) return null;
  const memberId = stringValue(record.member_id);
  const assetId = stringValue(record.asset_id);
  const versionId = stringValue(record.version_id);
  if (!memberId || !assetId || !versionId) return null;
  return {
    member_id: memberId,
    semantic_type: stringValue(record.semantic_type, "reference"),
    asset_id: assetId,
    version_id: versionId,
    public_url: stringOrNull(record.public_url),
    thumbnail_url: stringOrNull(record.thumbnail_url),
    media_type: stringOrNull(record.media_type),
  };
}

function normalizeV2AssetLibraryEntitySummary(value: unknown): V2AssetLibraryEntitySummary {
  const record = recordValue(value) ?? {};
  const scope = stringValue(record.scope, "my");
  const category = stringValue(record.library_category, "characters");
  return {
    entity_id: stringValue(record.entity_id),
    scope: scope === "recommended" ? "recommended" : "my",
    entity_type: stringValue(record.entity_type, "character"),
    library_category: category === "scenes" || category === "props" ? category : "characters",
    display_name: stringValue(record.display_name, stringValue(record.entity_id, "Untitled asset")),
    description: stringOrNull(record.description),
    tags: stringArray(record.tags),
    is_favorite: typeof record.is_favorite === "boolean" ? record.is_favorite : false,
    status: stringOrNull(record.status),
    preview_member: normalizeV2AssetLibraryPreviewMember(record.preview_member),
    member_count: numberValue(record.member_count),
  };
}

function normalizeV2AssetLibraryMember(value: unknown): V2AssetLibraryMember {
  const record = recordValue(value) ?? {};
  const preview = normalizeV2AssetLibraryPreviewMember(record) ?? {
    member_id: stringValue(record.member_id),
    semantic_type: stringValue(record.semantic_type, "reference"),
    asset_id: stringValue(record.asset_id),
    version_id: stringValue(record.version_id),
  };
  return {
    ...preview,
    is_primary: typeof record.is_primary === "boolean" ? record.is_primary : undefined,
    is_default_reference: typeof record.is_default_reference === "boolean" ? record.is_default_reference : undefined,
    sort_order: typeof record.sort_order === "number" ? record.sort_order : undefined,
    display_name: stringOrNull(record.display_name),
    mime_type: stringOrNull(record.mime_type),
    width: numberOrNull(record.width),
    height: numberOrNull(record.height),
    duration_seconds: numberOrNull(record.duration_seconds),
  };
}

export function normalizeV2AssetLibraryEntityDetail(value: unknown): V2AssetLibraryEntityDetail {
  const record = recordValue(value) ?? {};
  const summary = normalizeV2AssetLibraryEntitySummary(record.entity ?? record);
  return {
    ...summary,
    members: recordArray(record.members ?? record.assets).map(normalizeV2AssetLibraryMember),
    catalog_source_url: stringOrNull(record.catalog_source_url),
    license_id: stringOrNull(record.license_id),
    attribution: stringOrNull(record.attribution),
    created_at: stringOrNull(record.created_at),
    updated_at: stringOrNull(record.updated_at),
  };
}

export function normalizeV2RecommendedCatalogStatus(value: unknown): V2RecommendedCatalogStatus {
  const record = recordValue(value) ?? {};
  return {
    catalog_key: stringValue(record.catalog_key, "recommended"),
    catalog_version: stringOrNull(record.catalog_version),
    status: stringValue(record.status, "not_installed"),
    progress_current: numberOrNull(record.progress_current),
    progress_total: numberOrNull(record.progress_total),
    last_error_code: stringOrNull(record.last_error_code),
    message: stringOrNull(record.message),
  };
}

export function normalizeV2AssetLibraryListResponse(value: unknown): V2AssetLibraryListResponse {
  const record = recordValue(value) ?? {};
  return {
    entities: recordArray(record.entities).map(normalizeV2AssetLibraryEntitySummary),
    next_cursor: stringOrNull(record.next_cursor),
    catalog_status: record.catalog_status ? normalizeV2RecommendedCatalogStatus(record.catalog_status) : null,
  };
}

function normalizeV2ReferenceBinding(value: unknown): V2ReferenceBinding {
  const record = recordValue(value) ?? {};
  return {
    binding_id: stringValue(record.binding_id, stringValue(record.relation_id)),
    source_entity_id: stringOrNull(record.source_entity_id),
    asset_id: stringValue(record.asset_id),
    version_id: stringValue(record.version_id),
    reference_role: stringValue(record.reference_role, "visual_reference"),
  };
}

export function normalizeV2ReferenceSelectionsResponse(value: unknown): V2ReferenceSelectionsResponse {
  const record = recordValue(value) ?? {};
  return {
    workflow: record.workflow ? normalizeWorkflowV2(record.workflow) : null,
    selection_group_id: stringOrNull(record.selection_group_id),
    bindings: recordArray(record.bindings).map(normalizeV2ReferenceBinding),
    removed_binding_id: stringOrNull(record.removed_binding_id ?? record.binding_id),
    runtime: record.runtime ? normalizeWorkflowRuntimeV2(record.runtime) : null,
    events: normalizeWorkflowRuntimeEventArrayV2(record.events, record),
  };
}

export function normalizeV2SlotReferenceUploadResponse(value: unknown): V2SlotReferenceUploadResponse {
  const record = isRecord(value) ? value : {};
  const assets = recordArray(record.assets ?? record.asset_versions).map(normalizeAssetVersionV2);
  const sourceAssetIds = stringArray(record.source_asset_ids).length
    ? stringArray(record.source_asset_ids)
    : stringArray(record.asset_ids).length
      ? stringArray(record.asset_ids)
      : assets.map((asset) => asset.asset_id).filter(Boolean);
  return {
    workflow: record.workflow ? normalizeWorkflowV2(record.workflow) : null,
    assets,
    source_asset_ids: sourceAssetIds,
    asset_ids: sourceAssetIds,
    relations: recordArray(record.relations).map(normalizeWorkflowAssetRelationV2),
    warnings: normalizeV2WarningArray(record.warnings),
  };
}

export function normalizeV2InputAssetUploadResponse(value: unknown): V2InputAssetUploadResponse {
  const record = isRecord(value) ? value : {};
  return {
    assets: recordArray(record.assets).map(normalizeV2InputAssetUploadItem),
  };
}

function normalizeV2InputAssetUploadItem(value: unknown): V2InputAssetUploadItem {
  const record = isRecord(value) ? value : {};
  return {
    asset_id: stringValue(record.asset_id),
    version_id: stringValue(record.version_id),
    locator: stringValue(record.locator),
    media_type: stringValue(record.media_type, "image"),
    semantic_type: stringValue(record.semantic_type),
    source_type: stringValue(record.source_type, "upload"),
    public_url: stringOrNull(record.public_url),
    display_name: stringValue(record.display_name, stringValue(record.asset_id, "Uploaded reference")),
  };
}

export function normalizeV2RegisterReferenceResponse(value: unknown): V2RegisterReferenceResponse {
  const record = isRecord(value) ? value : {};
  const assets = recordArray(record.assets ?? record.asset_versions);
  const assetRecord = recordValue(record.asset) ?? recordValue(record.asset_version) ?? assets[0] ?? {};
  const asset = normalizeAssetVersionV2(assetRecord);
  return {
    source_asset_id: stringValue(record.source_asset_id, asset.asset_id),
    asset,
    relation: record.relation ? normalizeWorkflowAssetRelationV2(record.relation) : recordArray(record.relations)[0] ? normalizeWorkflowAssetRelationV2(recordArray(record.relations)[0]) : null,
    workflow: record.workflow ? normalizeWorkflowV2(record.workflow) : null,
    warnings: normalizeV2WarningArray(record.warnings),
    events: stringArray(record.events),
  };
}

export function normalizeV2ChatActionResponse(value: unknown): V2ChatActionResponse {
  const record = isRecord(value) ? value : {};
  return {
    workflow: record.workflow ? normalizeWorkflowV2(record.workflow) : null,
    message: stringValue(record.message) || undefined,
    action_id: stringValue(record.action_id) || undefined,
    action_mode: stringValue(record.action_mode) || undefined,
    status: stringValue(record.status) || undefined,
    target: recordValue(record.target) ? (record.target as V2ChatActionResponse["target"]) : null,
    resolved_target: recordValue(record.resolved_target) ?? null,
    specialist: stringOrNull(record.specialist),
    applied: typeof record.applied === "boolean" ? record.applied : undefined,
    materializer_mode: stringOrNull(record.materializer_mode),
    agent_route_snapshot: recordValue(record.agent_route_snapshot),
    updated_prompt_scope: stringOrNull(record.updated_prompt_scope),
    affected_slot_ids: stringArray(record.affected_slot_ids),
    executed_slot_ids: stringArray(record.executed_slot_ids),
    asset_ids: stringArray(record.asset_ids),
    version_ids: stringArray(record.version_ids),
    provider_calls: recordArray(record.provider_calls),
    warnings: normalizeV2WarningArray(record.warnings),
    events: normalizeWorkflowRuntimeEventArrayV2(record.events, record),
  };
}

const PROVIDER_TASK_CANONICAL_FIELDS = new Set([
  "task_id",
  "id",
  "workflow_id",
  "node_id",
  "item_id",
  "slot_id",
  "asset_id",
  "version_id",
  "provider",
  "provider_model",
  "remote_task_id",
  "status",
  "submitted_at",
  "updated_at",
  "completed_at",
  "poll_count",
  "last_error_code",
  "last_error_message",
  "provider_payload_snapshot",
  "metadata",
]);

export function normalizeProviderTaskV2(value: unknown): ProviderTaskV2 {
  const record = isRecord(value) ? value : {};
  const extraMetadata = Object.fromEntries(Object.entries(record).filter(([key]) => !PROVIDER_TASK_CANONICAL_FIELDS.has(key)));
  const metadata = {
    ...extraMetadata,
    ...(recordValue(record.metadata) ?? {}),
  };
  return {
    task_id: stringValue(record.task_id, stringValue(record.id)),
    workflow_id: stringOrNull(record.workflow_id),
    node_id: stringOrNull(record.node_id),
    item_id: stringOrNull(record.item_id),
    slot_id: stringOrNull(record.slot_id),
    asset_id: stringOrNull(record.asset_id),
    version_id: stringOrNull(record.version_id),
    provider: stringOrNull(record.provider),
    provider_model: stringOrNull(record.provider_model),
    remote_task_id: stringOrNull(record.remote_task_id),
    status: stringValue(record.status, "waiting"),
    submitted_at: stringOrNull(record.submitted_at),
    updated_at: stringOrNull(record.updated_at),
    completed_at: stringOrNull(record.completed_at),
    poll_count: typeof record.poll_count === "number" && Number.isFinite(record.poll_count) ? record.poll_count : undefined,
    last_error_code: stringOrNull(record.last_error_code),
    last_error_message: stringOrNull(record.last_error_message),
    provider_payload_snapshot: recordValue(record.provider_payload_snapshot),
    metadata: Object.keys(metadata).length ? metadata : undefined,
  };
}

export function normalizeWorkflowV2(value: unknown): WorkflowV2 {
  if (!isRecord(value) || value.workflow_schema_version !== 2) {
    throw new Error("unsupported_workflow_schema_version");
  }

  const nestedItems = recordArray(value.nodes).flatMap((node) => recordArray(node.items));
  const explicitItems = recordArray(value.items);
  const items = dedupeById([...explicitItems, ...nestedItems], "item_id").map(normalizeWorkflowItemV2);
  const nestedSlots = [...explicitItems, ...nestedItems].flatMap((item) => recordArray(item.slots));
  const explicitSlots = recordArray(value.slots);
  const slots = dedupeById([...explicitSlots, ...nestedSlots], "slot_id").map(normalizeWorkflowSlotV2);
  const explicitAssetVersions = recordArray(value.asset_versions);
  const derivedAssetVersions = deriveAssetVersionRecordsFromSlots(slots, stringValue(value.workflow_id));

  return {
    workflow_id: stringValue(value.workflow_id),
    workflow_schema_version: 2,
    state_version: typeof value.state_version === "number" && Number.isFinite(value.state_version) ? value.state_version : undefined,
    name: stringValue(value.name) || undefined,
    description: stringValue(value.description) || undefined,
    prompt: stringValue(value.prompt) || undefined,
    ad_request: recordValue(value.ad_request),
    aspect_ratio: stringValue(value.aspect_ratio) || undefined,
    duration_seconds: typeof value.duration_seconds === "number" ? value.duration_seconds : undefined,
    audio_mode: stringValue(value.audio_mode) || undefined,
    nodes: recordArray(value.nodes).map(normalizeWorkflowNodeV2),
    items,
    slots,
    asset_versions: dedupeAssetVersionRecords([...explicitAssetVersions, ...derivedAssetVersions]).map(normalizeAssetVersionV2),
    asset_relations: recordArray(value.asset_relations ?? value.relations).map(normalizeWorkflowAssetRelationV2),
    edges: Array.isArray(value.edges) ? value.edges.map(normalizeWorkflowDisplayEdgeV2) : [],
    runtime: value.runtime ? normalizeWorkflowRuntimeV2(value.runtime) : undefined,
    metadata: recordValue(value.metadata),
    created_at: stringValue(value.created_at) || undefined,
    updated_at: stringValue(value.updated_at) || undefined,
  };
}

function deriveAssetVersionRecordsFromSlots(slots: WorkflowSlotV2[], workflowId: string): Record<string, unknown>[] {
  const records: Record<string, unknown>[] = [];
  for (const slot of slots) {
    if (slot.selected_asset_id) {
      records.push(idOnlyAssetVersionRecord(slot.selected_asset_id, slot.selected_asset_id, slot, workflowId));
    }
    if (slot.current_working_asset_id) {
      records.push(idOnlyAssetVersionRecord(slot.current_working_asset_id, slot.current_working_version_id || slot.current_working_asset_id, slot, workflowId));
    }
    for (const versionId of slot.history_version_ids ?? []) {
      records.push(idOnlyAssetVersionRecord(versionId, versionId, slot, workflowId));
    }
  }
  return records;
}

function idOnlyAssetVersionRecord(assetId: string, versionId: string, slot: WorkflowSlotV2, workflowId: string): Record<string, unknown> {
  return {
    asset_id: assetId,
    version_id: versionId,
    media_type: slot.media_type,
    source_type: "generated",
    workflow_id: workflowId || null,
    node_id: slot.node_id,
    item_id: slot.item_id,
    slot_id: slot.slot_id,
    semantic_type: slot.slot_type,
    metadata: { id_only: true },
  };
}

function dedupeAssetVersionRecords(items: Record<string, unknown>[]) {
  const seenVersionIds = new Set<string>();
  const seenAssetIds = new Set<string>();
  const result: Record<string, unknown>[] = [];
  for (const item of items) {
    const versionId = stringValue(item.version_id);
    const assetId = stringValue(item.asset_id);
    if (!versionId && !assetId) continue;
    if (versionId && seenVersionIds.has(versionId)) continue;
    if (!versionId && assetId && seenAssetIds.has(assetId)) continue;
    if (assetId && isRecord(item.metadata) && item.metadata.id_only && seenAssetIds.has(assetId)) continue;
    if (versionId) seenVersionIds.add(versionId);
    if (assetId) seenAssetIds.add(assetId);
    result.push(item);
  }
  return result;
}

function dedupeById(items: Record<string, unknown>[], key: string) {
  const seen = new Set<string>();
  const result: Record<string, unknown>[] = [];
  for (const item of items) {
    const id = stringValue(item[key]);
    if (!id || seen.has(id)) continue;
    seen.add(id);
    result.push(item);
  }
  return result;
}
