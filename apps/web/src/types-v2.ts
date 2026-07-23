import type { AssetLibraryReference, AssetReferenceMode, FrontDeskMessage, FrontDeskResponse, UploadedAsset } from "./types.ts";

export type WorkflowNodeStatusV2 = "not_ready" | "ready" | "running" | "waiting" | "completed" | "partial_failed" | "failed";

export type WorkflowSlotStatusV2 = "empty" | "blocked" | "ready" | "running" | "waiting" | "completed" | "failed" | "skipped";

export type WorkflowExecutionStatusV2 = "queued" | "running" | "waiting" | "completed" | "partial_failed" | "failed" | "cancelled";

export type WorkflowV2ExecutionStatus = WorkflowExecutionStatusV2;

export type WorkflowV2RuntimeStatus =
  | "empty"
  | "ready"
  | "queued"
  | "running"
  | "waiting"
  | "completed"
  | "partial_failed"
  | "failed"
  | "blocked"
  | "skipped"
  | "stale"
  | "cancelled"
  | string;

export type WorkflowNodeTypeV2 =
  | "script"
  | "product-generation"
  | "character-generation"
  | "scene-generation"
  | "bgm"
  | "storyboard"
  | "final-composition"
  | "free-generation"
  | string;

export type WorkflowItemTypeV2 = "product" | "character" | "scene" | "bgm" | "shot" | "free" | "final_composition" | string;

export type WorkflowSlotTypeV2 =
  | "product_main_image"
  | "product_multi_view_grid"
  | "character_main_image"
  | "character_three_view"
  | "scene_main_image"
  | "scene_multi_view_grid"
  | "bgm_audio"
  | "shot_cell_1"
  | "shot_cell_2"
  | "shot_cell_3"
  | "shot_cell_4"
  | "shot_video_segment"
  | "final_video"
  | "free_output"
  | string;

export type WorkflowMediaTypeV2 = "image" | "video" | "audio" | "text";

export type AssetSourceTypeV2 = "upload" | "generated" | "imported" | "derived" | string;

export type ItemLifecycleStateV2 = "active" | "archived";

export interface WorkflowV2 {
  workflow_id: string;
  project_id?: string;
  workflow_schema_version: 2;
  /** Monotonic authoring version reported by the backend. */
  state_version?: number;
  semantic_revision_no?: number;
  name?: string;
  description?: string;
  prompt?: string;
  ad_request?: Record<string, unknown>;
  aspect_ratio?: string;
  duration_seconds?: number;
  audio_mode?: "bgm_only" | "none" | string;
  nodes: WorkflowNodeV2[];
  items: WorkflowItemV2[];
  slots: WorkflowSlotV2[];
  asset_versions: AssetVersionV2[];
  asset_relations?: WorkflowAssetRelationV2[];
  edges: WorkflowDisplayEdgeV2[];
  runtime?: WorkflowRuntimeV2;
  metadata?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

/** A Workflow returned by the backend Project/authoring persistence boundary. */
export interface PersistedWorkflowV2 extends WorkflowV2 {
  project_id: string;
  state_version: number;
  semantic_revision_no: number;
}

export type ProjectV2Status = "active" | "archived" | "trashed";

export interface ProjectV2Summary {
  project_id: string;
  workflow_id: string;
  name: string;
  status: ProjectV2Status;
  is_favorite: boolean;
  cover_asset_id: string | null;
  project_version: number;
  updated_at: string;
}

export interface ProjectV2 extends ProjectV2Summary {
  description: string;
  semantic_revision_no: number;
  created_at: string;
  deleted_at: string | null;
}

export interface ProjectV2ListResponse {
  items: ProjectV2Summary[];
  next_cursor: string | null;
}

export interface ProjectV2UpdateRequest {
  name?: string;
  description?: string;
  is_favorite?: boolean;
  cover_asset_id?: string | null;
  status?: "active" | "archived";
}

export type WorkflowRevisionChangeSourceV2 =
  | "create"
  | "migration"
  | "prompt_edit"
  | "structure_edit"
  | "reference_change"
  | "selected_version_change"
  | "script_confirm"
  | "timeline_edit"
  | "restore"
  | "execution_result";

export interface WorkflowRevisionV2Summary {
  revision_id: string;
  workflow_id: string;
  revision_no: number;
  state_version: number;
  content_hash: string;
  change_source: WorkflowRevisionChangeSourceV2;
  restored_from_revision_no: number | null;
  source_execution_id: string | null;
  created_at: string;
}

export interface WorkflowRevisionV2Detail extends WorkflowRevisionV2Summary {
  document: Record<string, unknown>;
}

export interface WorkflowRevisionPage {
  items: WorkflowRevisionV2Summary[];
  next_cursor: string | null;
}

export interface WorkflowRevisionRestoreResponse {
  workflow: WorkflowV2;
  revision: WorkflowRevisionV2Summary;
  restored_from_revision_no: number;
}

export type V2ProjectWorkflowNotFoundCode = "project_not_found" | "workflow_not_found" | "workflow_revision_not_found";

export type V2AuthoringPreconditionCode =
  | "project_precondition_required"
  | "workflow_precondition_required"
  | "project_state_conflict"
  | "workflow_state_conflict";

export interface V2ProjectWorkflowErrorDetails {
  current_etag?: string;
  current_state_version?: number;
  current_project_version?: number;
  revision_no?: number;
  [key: string]: unknown;
}

export interface V2ProjectWorkflowErrorResponse {
  detail: {
    code: V2ProjectWorkflowNotFoundCode | V2AuthoringPreconditionCode | string;
    message: string;
    details?: V2ProjectWorkflowErrorDetails;
  };
}

export interface WorkflowNodeV2 {
  node_id: string;
  node_type: WorkflowNodeTypeV2;
  title: string;
  status: WorkflowNodeStatusV2 | string;
  position?: { x: number; y: number };
  not_ready_reason?: string | null;
  resolved_media_type?: WorkflowMediaTypeV2 | null;
  resolved_node_role?: "free-image" | "free-video" | "free-audio" | string | null;
  metadata?: Record<string, unknown>;
  items?: WorkflowItemV2[];
}

export interface WorkflowItemV2 {
  item_id: string;
  node_id: string;
  item_type: WorkflowItemTypeV2;
  display_name: string;
  description?: string;
  item_prompt?: string;
  prompt_source?: "user" | "agent" | "system" | string;
  manual_prompt_dirty?: boolean;
  status: string;
  lifecycle_state: ItemLifecycleStateV2;
  shot_id?: string | null;
  shot_index?: number | null;
  aspect_ratio?: string | null;
  duration_seconds?: number | null;
  shot_summary_prompt?: string | null;
  detail_prompts?: Record<string, unknown>;
  reference_item_ids?: string[];
  timeline_plan?: Record<string, unknown>;
  timeline_clips?: Array<Record<string, unknown>>;
  metadata?: Record<string, unknown>;
  slots?: WorkflowSlotV2[];
}

export interface WorkflowSlotV2 {
  slot_id: string;
  node_id: string;
  item_id: string;
  slot_type: WorkflowSlotTypeV2;
  media_type: WorkflowMediaTypeV2;
  required: boolean;
  status: WorkflowSlotStatusV2 | string;
  slot_prompt?: string;
  system_suggested_prompt?: string;
  user_prompt?: string;
  negative_prompt?: string;
  media_prompt_asset_ids?: string[];
  implicit_reference_ids?: string[];
  explicit_reference_ids?: string[];
  dependency_slot_ids?: string[];
  provider?: string | null;
  provider_params?: Record<string, unknown>;
  selected_asset_id?: string | null;
  current_working_asset_id?: string | null;
  current_working_version_id?: string | null;
  history_version_ids?: string[];
  prompt_source?: string;
  manual_prompt_dirty?: boolean;
  dialogue_prompt?: string | null;
  audio_description_prompt?: string | null;
  voice_style_prompt?: string | null;
  negative_constraints?: string | null;
  warnings?: Array<{ code?: string; message?: string; [key: string]: unknown }>;
  metadata?: Record<string, unknown>;
}

/**
 * Returns the editable prompt layer while preserving user-authored whitespace.
 * Whitespace is normalized only to decide whether a layer is present.
 */
export function effectiveSlotPrompt(slot: Pick<WorkflowSlotV2, "slot_prompt" | "system_suggested_prompt" | "user_prompt">): string {
  for (const prompt of [slot.user_prompt, slot.system_suggested_prompt, slot.slot_prompt]) {
    if (typeof prompt === "string" && prompt.trim()) return prompt;
  }
  return "";
}

export interface AssetVersionV2 {
  asset_id: string;
  version_id: string;
  media_type: WorkflowMediaTypeV2;
  source_type: AssetSourceTypeV2;
  mime_type?: string | null;
  file_path?: string | null;
  public_url?: string | null;
  thumbnail_path?: string | null;
  proxy_path?: string | null;
  rendition_paths?: string[];
  duration_seconds?: number | null;
  width?: number | null;
  height?: number | null;
  status?: string | null;
  quality_status?: string | null;
  workflow_id?: string | null;
  node_id?: string | null;
  item_id?: string | null;
  slot_id?: string | null;
  semantic_type: string;
  prompt_snapshot?: string | Record<string, unknown> | null;
  provider_payload_snapshot?: Record<string, unknown>;
  reference_asset_ids?: string[];
  library_entity_id?: string | null;
  created_at?: string;
  created_by?: string | null;
  metadata?: Record<string, unknown>;
}

export interface SlotVersionRelationV2 {
  relation_id?: string | null;
  relation_type?: string | null;
  workflow_id?: string | null;
  node_id?: string | null;
  item_id?: string | null;
  slot_id?: string | null;
  asset_id?: string | null;
  version_id?: string | null;
  created_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface WorkflowAssetRelationV2 {
  relation_id?: string | null;
  relation_type?: string | null;
  workflow_id?: string | null;
  target_type?: "node" | "item" | "slot" | "asset" | string | null;
  target_id?: string | null;
  node_id?: string | null;
  item_id?: string | null;
  slot_id?: string | null;
  source_asset_id?: string | null;
  asset_id?: string | null;
  version_id?: string | null;
  reference_kind?: "explicit" | "absorbed" | string | null;
  semantic_type?: string | null;
  created_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface V2Warning {
  code?: string;
  message: string;
  severity?: "info" | "warning" | "error";
  metadata?: Record<string, unknown>;
}

export interface V2AssetOwnerDisplay {
  owner_display_name?: string | null;
  owner_type?: string | null;
  owner_node_id?: string | null;
  owner_item_id?: string | null;
  owner_slot_id?: string | null;
}

export interface AssetOwnerRelationV2 {
  relation_id?: string | null;
  relation_type?: string | null;
  workflow_id?: string | null;
  node_id?: string | null;
  item_id?: string | null;
  slot_id?: string | null;
  asset_id?: string | null;
  version_id?: string | null;
  created_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface AssetOwnerV2 extends V2AssetOwnerDisplay {
  node_id?: string | null;
  item_id?: string | null;
  slot_id?: string | null;
  relation_type?: string | null;
  metadata?: Record<string, unknown>;
}

export interface AssetOwnerResponseV2 {
  workflow_id: string;
  asset_id: string;
  owner?: AssetOwnerV2 | null;
  relations: AssetOwnerRelationV2[];
  metadata?: Record<string, unknown>;
}

export interface SlotVersionsResponseV2 {
  workflow_id: string;
  slot_id: string;
  selected_asset_id?: string | null;
  working_asset_id?: string | null;
  current_working_version_id?: string | null;
  versions: AssetVersionV2[];
  relations: SlotVersionRelationV2[];
  metadata?: Record<string, unknown>;
}

export interface OutdatedSourceV2 {
  source_node_id?: string | null;
  source_item_id?: string | null;
  source_slot_id?: string | null;
  source_asset_id?: string | null;
  old_asset_id?: string | null;
  new_asset_id?: string | null;
  reason?: string | null;
  created_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface WorkflowV2RuntimeError {
  code: string;
  message: string;
  stage?: string | null;
}

export interface RuntimeRecordV2 {
  status?: WorkflowV2RuntimeStatus;
  started_at?: string | null;
  finished_at?: string | null;
  error?: WorkflowV2RuntimeError | string | null;
  waiting_reason?: string | null;
  updated_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface WorkflowV2SlotRuntime extends RuntimeRecordV2 {
  slot_id: string;
  node_id: string;
  item_id: string;
  slot_type?: string | null;
  media_type?: string | null;
  status: WorkflowV2RuntimeStatus;
  selected_asset_id?: string | null;
  selected_version_id?: string | null;
  current_working_asset_id?: string | null;
  current_working_version_id?: string | null;
  provider_task_id?: string | null;
  waiting_reason?: string | null;
  error?: WorkflowV2RuntimeError | null;
  updated_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface WorkflowV2ItemRuntime extends RuntimeRecordV2 {
  item_id: string;
  node_id: string;
  status: WorkflowV2RuntimeStatus;
  active_slot_ids?: string[];
  updated_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface WorkflowV2NodeRuntime extends RuntimeRecordV2 {
  node_id: string;
  status: WorkflowV2RuntimeStatus;
  running_slot_ids?: string[];
  waiting_slot_ids?: string[];
  failed_slot_ids?: string[];
  completed_slot_ids?: string[];
  updated_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface WorkflowRuntimeV2 {
  workflow_id: string;
  active_execution_id?: string | null;
  execution_status?: WorkflowV2ExecutionStatus | string | null;
  running_slot_ids: string[];
  running_item_ids: string[];
  running_node_ids: string[];
  waiting_slot_ids: string[];
  waiting_item_ids: string[];
  waiting_node_ids: string[];
  failed_slot_ids: string[];
  failed_item_ids: string[];
  failed_node_ids: string[];
  completed_slot_ids: string[];
  completed_item_ids: string[];
  completed_node_ids: string[];
  blocked_slot_ids: string[];
  blocked_item_ids: string[];
  blocked_node_ids: string[];
  skipped_slot_ids: string[];
  skipped_item_ids: string[];
  skipped_node_ids: string[];
  node_runtime: Record<string, WorkflowV2NodeRuntime>;
  item_runtime: Record<string, WorkflowV2ItemRuntime>;
  slot_runtime: Record<string, WorkflowV2SlotRuntime>;
  events_cursor: number;
  updated_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface WorkflowRuntimeEventV2 {
  seq: number;
  event_type: string;
  workflow_id: string;
  node_id?: string | null;
  item_id?: string | null;
  slot_id?: string | null;
  asset_id?: string | null;
  version_id?: string | null;
  created_at?: string;
  payload?: Record<string, unknown>;
}

export type ProviderTaskStatusV2 =
  | "submitted"
  | "running"
  | "waiting"
  | "completed"
  | "failed"
  | "cancelled"
  | "expired"
  | string;

export interface ProviderTaskV2 {
  task_id: string;
  workflow_id?: string | null;
  node_id?: string | null;
  item_id?: string | null;
  slot_id?: string | null;
  asset_id?: string | null;
  version_id?: string | null;
  provider?: string | null;
  provider_model?: string | null;
  remote_task_id?: string | null;
  status: ProviderTaskStatusV2;
  submitted_at?: string | null;
  updated_at?: string | null;
  completed_at?: string | null;
  poll_count?: number;
  last_error_code?: string | null;
  last_error_message?: string | null;
  provider_payload_snapshot?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface WorkflowDisplayEdgeV2 {
  id: string;
  source: string;
  target: string;
  edge_kind: "display_flow" | string;
  source_handle?: string | null;
  target_handle?: string | null;
  metadata?: Record<string, unknown>;
}

export interface V2ItemPromptUpdateRequest {
  item_prompt: string;
}

export interface V2SlotPromptUpdateRequest {
  slot_prompt?: string;
  negative_prompt?: string;
  detail_prompt_key?: string;
}

export interface V2SlotReferenceUploadResponse {
  workflow?: WorkflowV2 | null;
  assets: AssetVersionV2[];
  source_asset_ids: string[];
  asset_ids?: string[];
  relations: WorkflowAssetRelationV2[];
  warnings?: V2Warning[];
}

export interface V2InputAssetUploadItem {
  asset_id: string;
  version_id: string;
  locator: string;
  media_type: WorkflowMediaTypeV2 | string;
  semantic_type: string;
  source_type: AssetSourceTypeV2 | string;
  public_url?: string | null;
  display_name: string;
}

export interface V2InputAssetUploadResponse {
  assets: V2InputAssetUploadItem[];
}

export interface V2SlotCandidateRegenerateRequest {
  slot_prompt: string;
  negative_prompt?: string;
  reference_asset_ids: string[];
  library_entity_ids: string[];
  source_action: "slot_micro_prompt_send" | "run_current_only" | string;
  metadata?: Record<string, unknown>;
}

export interface V2ItemGenerateRequest {
  prompt_scope?: "auto" | "item" | "slots" | string;
  slot_ids?: string[];
  metadata?: Record<string, unknown>;
}

export interface V2ReferenceAttachRequest {
  target_type: "item" | "slot";
  target_id: string;
  source_asset_id: string;
  reference_kind: "explicit" | "absorbed";
  metadata?: Record<string, unknown>;
}

export interface V2AddSlotReferenceRequest {
  asset_id: string;
  version_id: string;
  reference_role: "product" | "character" | "scene" | "style" | "composition" | "motion" | "audio" | string;
}

export type V2AssetLibraryScope = "my" | "recommended";

export type V2AssetLibraryCategory = "characters" | "scenes" | "props";

export type V2AssetLibraryEntityType = "character" | "scene" | "product" | string;

export type V2AssetLibraryMemberSemanticType = string;

export interface V2AssetLibraryPreviewMember {
  member_id: string;
  semantic_type: V2AssetLibraryMemberSemanticType;
  asset_id: string;
  version_id: string;
  public_url?: string | null;
  thumbnail_url?: string | null;
  media_type?: WorkflowMediaTypeV2 | string | null;
}

export interface V2AssetLibraryMember extends V2AssetLibraryPreviewMember {
  is_primary?: boolean;
  is_default_reference?: boolean;
  sort_order?: number;
  display_name?: string | null;
  mime_type?: string | null;
  width?: number | null;
  height?: number | null;
  duration_seconds?: number | null;
}

export interface V2AssetLibraryEntitySummary {
  entity_id: string;
  scope: V2AssetLibraryScope;
  entity_type: V2AssetLibraryEntityType;
  library_category: V2AssetLibraryCategory;
  display_name: string;
  description?: string | null;
  tags: string[];
  is_favorite: boolean;
  status?: string | null;
  preview_member?: V2AssetLibraryPreviewMember | null;
  preview_url?: string | null;
  member_count: number;
}

export interface V2AssetLibraryEntityDetail extends V2AssetLibraryEntitySummary {
  members: V2AssetLibraryMember[];
  catalog_source_url?: string | null;
  license_id?: string | null;
  attribution?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface V2AssetLibraryListResponse {
  entities: V2AssetLibraryEntitySummary[];
  next_cursor?: string | null;
  catalog_status?: V2RecommendedCatalogStatus | null;
}

export interface V2RecommendedCatalogStatus {
  catalog_key: string | null;
  catalog_version?: string | null;
  status: "catalog_missing" | "indexing" | "ready" | "invalid";
  entity_count: number;
  member_count: number;
  manifest_sha256?: string | null;
  expected_relative_path: "data/assets/catalogs/recommended/";
  last_error_code?: string | null;
  message?: string | null;
}

export interface V2AssetLibraryListRequest {
  scope: V2AssetLibraryScope;
  category?: V2AssetLibraryCategory | null;
  search?: string | null;
  cursor?: string | null;
  limit?: number;
}

export interface V2AssetLibraryCreateFromMembersSource {
  type: "members";
  members: Array<{
    asset_id: string;
    version_id: string;
    semantic_type: V2AssetLibraryMemberSemanticType;
    is_primary?: boolean;
    is_default_reference?: boolean;
    sort_order?: number;
  }>;
}

export interface V2AssetLibraryCreateFromRecommendedSource {
  type: "recommended_entity";
  entity_id: string;
}

export interface V2AssetLibraryCreateRequest {
  display_name: string;
  entity_type: V2AssetLibraryEntityType;
  library_category: V2AssetLibraryCategory;
  description?: string | null;
  tags?: string[];
  source: V2AssetLibraryCreateFromMembersSource | V2AssetLibraryCreateFromRecommendedSource;
}

export interface V2AssetLibraryPatchRequest {
  display_name?: string;
  description?: string | null;
  tags?: string[];
  is_favorite?: boolean;
}

export interface V2AssetReferenceSelection {
  selection_type: "entity";
  entity_id: string;
}

export interface V2AssetVersionReferenceSelection {
  selection_type: "asset_version";
  asset_id: string;
  version_id: string;
}

export interface V2ReferenceSelectionsRequest {
  selections: Array<V2AssetReferenceSelection | V2AssetVersionReferenceSelection>;
  reference_role: string;
  use_as_prompt: boolean;
}

export interface V2ReferenceBinding {
  binding_id: string;
  source_entity_id?: string | null;
  asset_id: string;
  version_id: string;
  reference_role: string;
}

export interface V2ReferenceSelectionsResponse {
  workflow?: WorkflowV2 | null;
  selection_group_id?: string | null;
  bindings: V2ReferenceBinding[];
  removed_binding_id?: string | null;
  runtime?: WorkflowRuntimeV2 | null;
  events: WorkflowRuntimeEventV2[];
}

export interface V2EtaggedResponse<T> {
  value: T;
  etag: string | null;
}

export interface V2RegisterLibraryReferenceRequest {
  library_entity_id: string;
  library_asset_id?: string | null;
  target: {
    target_type: "slot";
    slot_id: string;
  };
  reference_role?: "product" | "character" | "scene" | "style" | "composition" | "motion" | "audio" | string | null;
  semantic_type?: string | null;
  use_as_prompt: true;
}

export interface V2RegisterReferenceAssetRequest {
  source: {
    kind?: "existing_v2_asset_version" | "data_assets_file" | string;
    source_type?: string;
    public_url?: string | null;
    local_path?: string | null;
    file_path?: string | null;
    upload_asset_id?: string | null;
    asset_id?: string | null;
    source_asset_id?: string | null;
    version_id?: string | null;
    mime_type?: string | null;
    display_name?: string | null;
    media_type?: WorkflowMediaTypeV2 | string | null;
    semantic_type?: string | null;
  };
  target: {
    target_type: "slot";
    slot_id: string;
  };
  reference_role?: "product" | "character" | "scene" | "style" | "composition" | "motion" | "audio" | string | null;
  semantic_type?: string | null;
  use_as_prompt: true;
}

export interface V2RegisterReferenceResponse {
  source_asset_id: string;
  asset: AssetVersionV2;
  relation?: WorkflowAssetRelationV2 | null;
  workflow?: WorkflowV2 | null;
  warnings?: V2Warning[];
  events?: string[];
}

export interface V2WorkflowAssetFilters {
  media_type?: WorkflowMediaTypeV2 | string | null;
  semantic_type?: string | null;
  node_id?: string | null;
  item_id?: string | null;
  slot_id?: string | null;
  state?: "selected" | "working" | "history" | "reference" | string | null;
  owner_type?: string | null;
}

export interface WorkflowAssetListRowV2 extends AssetVersionV2, V2AssetOwnerDisplay {
  state?: string | null;
  locator?: string | null;
  display_name?: string | null;
  thumbnail_url?: string | null;
  prompt_summary?: string | null;
  provider_prompt?: string | null;
  quality_issues?: Array<Record<string, unknown>>;
  relation_ids?: string[];
}

export interface WorkflowAssetListResponseV2 {
  workflow_id: string;
  assets: WorkflowAssetListRowV2[];
}

export interface WorkflowAssetVersionsResponseV2 {
  workflow_id: string;
  asset_id: string;
  selected_version_id?: string | null;
  working_version_id?: string | null;
  versions: WorkflowAssetListRowV2[];
}

export interface V2GlobalRunRequest {
  mode: "fill_missing_required_slots";
}

export interface V2PlanFromPromptRequest {
  prompt: string;
  product_name?: string | null;
  duration_seconds?: number;
  aspect_ratio?: string;
  audio_mode?: "none" | "bgm_only" | "full" | string;
  input_asset_locators?: string[];
  selected_assets?: UploadedAsset[];
  asset_references?: AssetLibraryReference[];
  library_entity_ids?: string[];
  reference_mode?: AssetReferenceMode;
  metadata?: Record<string, unknown>;
}

export interface V2PlanFromChatRequest {
  message: string;
  history: FrontDeskMessage[];
  input_asset_locators?: string[];
  selected_assets?: UploadedAsset[];
  audio_mode?: "none" | "bgm_only" | "full" | string;
  library_entity_ids?: string[];
  asset_references?: AssetLibraryReference[];
  reference_mode?: AssetReferenceMode;
  metadata?: Record<string, unknown>;
}

export interface V2PlanFromChatResponse {
  front_desk: FrontDeskResponse;
  workflow: WorkflowV2 | null;
  project_id?: string | null;
  normalized_v2_request?: Record<string, unknown> | null;
  status?: string | null;
  error_code?: string | null;
  message?: string | null;
  details: Record<string, unknown>;
  suggested_actions: Array<Record<string, unknown>>;
}

export interface WorkflowV2RunResponse {
  workflow?: WorkflowV2 | null;
  workflow_id?: string;
  execution_id?: string | null;
  status?: WorkflowV2ExecutionStatus | string | null;
  runtime?: WorkflowRuntimeV2 | null;
  events_cursor?: number | null;
  executed_slot_ids: string[];
  provider_calls: Array<Record<string, unknown>>;
  waiting_slot_ids: string[];
  failed_slot_ids: string[];
  blocked_slot_ids: string[];
  created_item_ids: string[];
  created_slot_ids: string[];
  message?: string | null;
}

export interface WorkflowV2ChatTarget {
  target_type: "node" | "item" | "slot" | "asset" | string;
  node_id?: string | null;
  item_id?: string | null;
  slot_id?: string | null;
  asset_id?: string | null;
  version_id?: string | null;
}

export interface V2AssetLocatorResponse {
  workflow_id: string;
  locator: string;
  asset: AssetVersionV2;
  target?: WorkflowV2ChatTarget | null;
  owner?: (V2AssetOwnerDisplay & { relation_type?: string | null }) | null;
  warnings?: V2Warning[];
}

export interface V2SelectSlotVersionRequest {
  asset_id: string;
  version_id: string;
  source_action?: string;
  metadata?: Record<string, unknown>;
}

export type V2ChatActionMode = "revise_prompt" | "revise_and_generate" | "select_version" | "discard_working" | "auto";

export interface V2ChatActionRequest {
  message: string;
  action_mode: V2ChatActionMode;
  target?: WorkflowV2ChatTarget | null;
  target_references?: WorkflowV2ChatTarget[];
  asset_locators?: string[];
  conversation_id?: string | null;
  history?: FrontDeskMessage[];
  context?: Record<string, unknown>;
  attachments?: Array<{ source_asset_id: string; semantic_type?: string | null; use_as_prompt?: boolean }>;
}

export interface V2ChatActionResponse {
  workflow?: WorkflowV2 | null;
  message?: string;
  action_id?: string;
  action_mode?: V2ChatActionMode | string;
  status?: string;
  target?: WorkflowV2ChatTarget | null;
  resolved_target?: Record<string, unknown> | null;
  specialist?: string | null;
  applied?: boolean;
  materializer_mode?: string | null;
  agent_route_snapshot?: Record<string, unknown> | null;
  updated_prompt_scope?: string | null;
  affected_slot_ids: string[];
  executed_slot_ids: string[];
  asset_ids: string[];
  version_ids: string[];
  provider_calls?: Array<Record<string, unknown>>;
  warnings: V2Warning[];
  events?: WorkflowRuntimeEventV2[];
}

export interface V2ChatTargetRequest {
  target: WorkflowV2ChatTarget;
  instruction: string;
  action_mode?: "revise_prompt" | "revise_and_generate" | string;
  prompt_scope?: "auto" | "item" | "slot" | string;
  selected_assets?: UploadedAsset[];
  asset_references?: AssetLibraryReference[];
  metadata?: Record<string, unknown>;
}

export interface V2ChatTargetResponse {
  workflow: WorkflowV2 | null;
  target?: WorkflowV2ChatTarget;
  message?: string;
  action_mode?: string;
  specialist?: string;
  applied?: boolean;
  updated_prompt_scope?: string;
  generated?: boolean;
  affected_slot_ids?: string[];
  executed_slot_ids?: string[];
  asset_ids?: string[];
  version_ids?: string[];
  provider_calls?: Array<Record<string, unknown>>;
  warnings?: V2Warning[];
  agent_route_snapshot?: Record<string, unknown> | null;
}

export interface V2ReferenceMutationResponse {
  workflow?: WorkflowV2 | null;
  relation?: WorkflowAssetRelationV2 | null;
  assets?: AssetVersionV2[];
  warnings?: V2Warning[];
  removed_relation_id?: string | null;
}

export interface SlotReferenceBindingViewModel {
  asset_id: string;
  version_id?: string | null;
  display_name: string;
  media_type?: WorkflowMediaTypeV2 | string;
  source_type?: AssetSourceTypeV2 | string;
  asset?: AssetVersionV2 | null;
}

export interface SlotFunctionalCardViewModel {
  workflow_id: string;
  node_id: string;
  item_id: string;
  slot_id: string;
  slot_type: string;
  media_type: WorkflowMediaTypeV2 | string;
  title: string;
  prompt: string;
  prompt_source: "agent" | "system" | "user" | string;
  manual_prompt_dirty: boolean;
  selected_asset: AssetVersionV2 | null;
  working_asset: AssetVersionV2 | null;
  history_assets: AssetVersionV2[];
  references: SlotReferenceBindingViewModel[];
  runtime_status: WorkflowSlotStatusV2 | "ready" | "empty" | string;
  warnings: Array<{ code: string; message: string }>;
}

export interface V2FreeNodeCreateRequest {
  slot_prompt?: string;
  negative_prompt?: string | null;
  provider?: string | null;
  provider_params?: Record<string, unknown>;
}

export interface V2FreeNodeGenerateRequest {
  output_media_type: WorkflowMediaTypeV2;
}

export interface V2FreeNodeAbsorbRequest {
  target_node_id: string;
  target_item_id?: string | null;
  target_slot_id?: string | null;
  asset_id: string;
  absorb_role: string;
  metadata?: Record<string, unknown>;
}

export interface V2FreeNodeAbsorbResponse {
  workflow: WorkflowV2;
  relations: Array<Record<string, unknown>>;
}

export interface V2TimelineClipCreateRequest {
  source_asset_id: string;
  clip_type: "video" | "audio" | "subtitle" | "image";
  start_time?: number;
  duration: number;
  track_index?: number;
  trim_in?: number;
  trim_out?: number | null;
  volume?: number;
  metadata?: Record<string, unknown>;
}

export interface V2TimelineClipMutationResponse {
  workflow: WorkflowV2;
  clip?: Record<string, unknown> | null;
  removed_clip_id?: string | null;
}

export type V2TimelineTrackType = "video" | "audio" | "image" | "subtitle";

export type V2TimelineColorPreset = "none" | "warm" | "cool" | "high_contrast" | "muted";

export interface V2TimelineTransform {
  x: number;
  y: number;
  scale_x: number;
  scale_y: number;
  rotation_degrees: number;
  opacity: number;
  fit: "cover" | "contain";
}

export interface V2TimelineAudio {
  volume: number;
  muted: boolean;
  fade_in_seconds: number;
  fade_out_seconds: number;
}

export interface V2TimelineColor {
  preset_id: V2TimelineColorPreset;
  brightness: number;
  contrast: number;
  saturation: number;
  exposure: number;
  temperature: number;
  tint: number;
  hue: number;
}

export interface V2TimelineSubtitleStyle {
  font_size: number;
  color: string;
  position: "top_center" | "center" | "bottom_center";
}

export interface V2FinalTimelineTrack {
  track_id: string;
  track_type: V2TimelineTrackType;
  order: number;
  enabled: boolean;
  metadata: Record<string, unknown>;
}

export interface V2FinalTimelineClip {
  clip_id: string;
  track_id: string;
  clip_type: V2TimelineTrackType;
  source_asset_id: string | null;
  source_version_id: string | null;
  source_slot_id: string | null;
  start_time: number;
  duration: number;
  trim_in: number;
  trim_out: number | null;
  volume: number;
  muted: boolean;
  enabled: boolean;
  transform: V2TimelineTransform;
  audio: V2TimelineAudio;
  color: V2TimelineColor;
  text: string | null;
  subtitle_style: V2TimelineSubtitleStyle;
  metadata: Record<string, unknown>;
}

export interface V2FinalTimelineRenderSettings {
  video_codec: string | null;
  audio_codec: "aac";
  video_bitrate: string | null;
  audio_bitrate: string | null;
}

export interface V2FinalTimelineRenderRequest {
  timeline_id: string;
  timeline_version: number;
  render_settings?: V2FinalTimelineRenderSettings;
}

export interface V2FinalCompositionTimeline {
  timeline_id: string;
  version: number;
  duration_seconds: number;
  aspect_ratio: string;
  resolution: { width: number; height: number };
  fps: number;
  tracks: V2FinalTimelineTrack[];
  clips: V2FinalTimelineClip[];
  metadata: Record<string, unknown>;
}

export interface V2FinalTimelineSource {
  asset_id: string;
  version_id: string;
  media_type: "video" | "audio" | "image";
  display_name: string;
  public_url?: string | null;
  thumbnail_url?: string | null;
  duration_seconds?: number | null;
  origin: "workflow" | "asset_library" | "upload" | string;
}

export interface V2FinalTimelineResponse {
  workflow_id: string;
  node_id: "final-composition";
  item_id: string;
  source: "default" | "saved" | string;
  timeline: V2FinalCompositionTimeline;
  available_sources: V2FinalTimelineSource[];
  runtime?: WorkflowRuntimeV2 | null;
}

export interface V2FinalTimelineUpdateRequest {
  expected_version: number;
  timeline: V2FinalCompositionTimeline;
}

export interface V2FinalTimelineUpdateResponse {
  workflow_id: string;
  timeline: V2FinalCompositionTimeline;
  changed_clip_ids: string[];
  runtime?: WorkflowRuntimeV2 | null;
}

export interface V2FinalTimelineSourceImportRequest {
  library_entity_id?: string | null;
  library_asset_id: string;
  expected_media_type: "video" | "audio";
}

export interface V2FinalTimelineSourceImportResponse {
  workflow_id: string;
  source: V2FinalTimelineSource;
}

export interface V2FinalTimelineRenderStartResponse {
  workflow_id: string;
  render_id: string;
  status: "queued";
  timeline_id: string;
  timeline_version: number;
  events_cursor: number;
}

export interface V2FinalTimelineRenderStateResponse {
  workflow_id: string;
  render_id: string;
  slot_id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancellation_requested" | "cancelled";
  timeline_id: string;
  timeline_version: number;
  events_cursor: number;
  progress_seconds: number | null;
  total_seconds: number | null;
  progress_percent: number | null;
  asset_id: string | null;
  version_id: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface V2WorkflowErrorDetail {
  code?: string;
  message?: string;
  [key: string]: unknown;
}

export type V2ScriptSourceAction = "initial_planning" | "script_editor_confirm" | "agent_chat_edit";

export type V2ScriptAspectRatio = "16:9" | "9:16" | "4:3" | "3:4" | "1:1" | "21:9";

export interface V2ScriptDialogueLine {
  dialogue_id: string;
  character_id: string;
  performance_cue: string | null;
  text: string;
}

export interface V2ScriptShot {
  shot_id: string;
  scene_id: string;
  shot_index: number;
  product_ids: string[];
  character_ids: string[];
  scene_ids: string[];
  reference_item_ids: string[];
  description: string;
  dialogue: V2ScriptDialogueLine[];
  narration: string | null;
  visual_prompt: string;
  duration_seconds: number;
}

export interface V2ScriptScene {
  scene_id: string;
  title: string;
  description: string;
  location_id: string | null;
  shot_ids: string[];
  duration_seconds: number;
  location_type: string | null;
  time_of_day: string | null;
  setting_type: "interior" | "exterior" | null;
}

export interface V2ScriptCharacter {
  character_id: string;
  display_name: string;
  description: string;
  role: string;
  visual_notes: string;
  gender: string | null;
}

export interface V2ScriptLocation {
  location_id: string;
  display_name: string;
  description: string;
  visual_notes: string;
  location_type: string | null;
  time_of_day: string | null;
  setting_type: "interior" | "exterior" | null;
}

export interface V2ScriptPlan {
  script_plan_version: 2;
  script_brief_id: string;
  script_version_id: string;
  language: string;
  script_title: string;
  script_text: string;
  scenes: V2ScriptScene[];
  shots: V2ScriptShot[];
  characters: V2ScriptCharacter[];
  locations: V2ScriptLocation[];
  product_beats: string[];
  tone: string;
  visual_style: string;
  duration_seconds: number;
  aspect_ratio: V2ScriptAspectRatio;
  materializer_mode: "real" | "mock";
  model_id: string | null;
  selected_skill_ids: string[];
  selected_skill_paths: string[];
  skill_context_warnings: Array<Record<string, unknown>>;
  quality_notes: string[];
  materializer_version: string | null;
  metadata: Record<string, unknown>;
  warnings: Array<Record<string, unknown>>;
}

export interface V2EditableScriptDialogue {
  dialogue_id?: string | null;
  client_key?: string | null;
  character_id: string;
  performance_cue?: string | null;
  text: string;
}

export interface V2EditableScriptShot {
  shot_id?: string | null;
  client_key?: string | null;
  product_ids?: string[];
  character_ids?: string[];
  scene_ids?: string[];
  description: string;
  dialogue?: V2EditableScriptDialogue[];
  narration?: string | null;
  visual_prompt: string;
  duration_seconds: number;
}

export interface V2EditableScriptScene {
  scene_id?: string | null;
  client_key?: string | null;
  title: string;
  description: string;
  location_id?: string | null;
  location_type?: string | null;
  time_of_day?: string | null;
  setting_type?: "interior" | "exterior" | null;
  shots: V2EditableScriptShot[];
}

export interface V2EditableScriptCharacter {
  character_id?: string | null;
  client_key?: string | null;
  display_name: string;
  description: string;
  role: string;
  visual_notes: string;
  gender?: string | null;
}

export interface V2EditableScriptLocation {
  location_id?: string | null;
  client_key?: string | null;
  display_name: string;
  description: string;
  visual_notes: string;
  location_type?: string | null;
  time_of_day?: string | null;
  setting_type?: "interior" | "exterior" | null;
}

export interface V2EditableScriptDocument {
  script_title: string;
  language: string;
  characters?: V2EditableScriptCharacter[];
  locations?: V2EditableScriptLocation[];
  scenes: V2EditableScriptScene[];
  product_beats?: string[];
  tone: string;
  visual_style: string;
  aspect_ratio: V2ScriptAspectRatio;
}

export interface V2ScriptConfirmRequest {
  base_script_version_id: string;
  document: V2EditableScriptDocument;
  source_action?: "script_editor_confirm" | "agent_chat_edit";
}

export interface V2ScriptSelectVersionRequest {
  base_selected_script_version_id: string;
}

export interface V2ScriptStructuralDiff {
  added_character_ids: string[];
  archived_character_ids: string[];
  reactivated_character_ids: string[];
  updated_character_ids: string[];
  added_location_ids: string[];
  archived_location_ids: string[];
  reactivated_location_ids: string[];
  updated_location_ids: string[];
  added_scene_ids: string[];
  archived_scene_ids: string[];
  reactivated_scene_ids: string[];
  updated_scene_ids: string[];
  added_shot_ids: string[];
  archived_shot_ids: string[];
  reactivated_shot_ids: string[];
  updated_shot_ids: string[];
  added_dialogue_ids: string[];
  archived_dialogue_ids: string[];
  updated_dialogue_ids: string[];
  order_changed: boolean;
}

export interface V2LinkedContextSummary {
  updated_node_ids: string[];
  updated_item_ids: string[];
  updated_slot_ids: string[];
  updated_fields: string[];
  selected_asset_versions_changed: false;
  provider_execution_started: false;
  refresh: string[];
}

export interface V2ScriptReadResponse {
  workflow_id: string;
  selected_script_version_id: string;
  script: V2ScriptPlan;
  events_cursor: number;
}

export interface V2ScriptConfirmResponse extends V2ScriptReadResponse {
  structural_diff: V2ScriptStructuralDiff;
  linked_context: V2LinkedContextSummary;
}

export interface V2ScriptVersionSummary {
  script_version_id: string;
  parent_script_version_id: string | null;
  created_at: string;
  source_action: V2ScriptSourceAction;
  script_title: string;
  content_hash: string;
  structural_diff_summary: Record<string, unknown>;
}

export interface V2ScriptVersionListResponse {
  workflow_id: string;
  selected_script_version_id: string;
  versions: V2ScriptVersionSummary[];
  events_cursor: number;
}

export interface V2ScriptSelectVersionResponse extends V2ScriptReadResponse {
  structural_diff: V2ScriptStructuralDiff;
  linked_context: V2LinkedContextSummary;
}
