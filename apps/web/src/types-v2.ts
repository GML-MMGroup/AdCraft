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
  selected_version_id?: string | null;
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

export type V2CompositionRenderMode = "simple_sequence" | "timeline_editor";

export interface V2CompositionCapabilities {
  render_mode: V2CompositionRenderMode;
  supports_timeline_controls: boolean;
  supports_shot_reorder: boolean;
  supports_bgm_volume_edit: boolean;
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
  slot_id?: string | null;
}

export interface V2FinalTimelineResponse {
  workflow_id: string;
  node_id: "final-composition";
  item_id: string;
  source: "default" | "saved" | string;
  timeline: V2FinalCompositionTimeline;
  available_sources: V2FinalTimelineSource[];
  composition_capabilities: V2CompositionCapabilities;
  stale_clip_ids: string[];
  missing_source_clip_ids: string[];
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

export type CanvasNodeTypeV2 = "text" | "script" | "image" | "video" | "audio" | "editing";

export type CanvasNodeStatusV2 = "draft" | "working" | "ready" | "failed";

export type CanvasCreativeRoleV2 =
  | "creative_brief"
  | "script"
  | "product"
  | "prop"
  | "character"
  | "scene"
  | "storyboard_sequence"
  | "storyboard_video"
  | "bgm"
  | "general_text"
  | "general_image"
  | "general_video"
  | "general_audio"
  | "editing";

export type CanvasBindingInputRoleV2 =
  | "text_context"
  | "image_reference"
  | "video_reference"
  | "audio_reference";

export type CanvasBindingKindV2 = CanvasBindingInputRoleV2;

export type AgentCanvasAssetMediaTypeV2 = "image" | "video" | "audio";

export type AgentCanvasAssetSourceTypeV2 = "upload" | "generated" | "recommended" | "library" | "editing_export";

export type ProjectAssetStatusV2 = "ready" | "unavailable";

export interface CanvasPositionV2 {
  x: number;
  y: number;
}

export type AgentPlacementIntentV2 =
  | "append_flow"
  | "after_anchor"
  | "right_sibling"
  | "near_selection";

export interface AgentPlacementHintV2 {
  intent: AgentPlacementIntentV2;
  anchor_node_id: string | null;
  group_key: string | null;
}

export interface CanvasNodeErrorV2 {
  code: string;
  message: string;
  retryable: boolean;
}

export interface CanvasVariationDraftV2 {
  source_node_id: string;
  source_node_revision: number;
  title: string;
  generation_prompt: string;
  model_id: string | null;
  parameters: Record<string, unknown>;
  variation_revision: number;
  created_at: string;
  updated_at: string;
}

export interface CanvasNodeV2 {
  node_id: string;
  workflow_id: string;
  node_type: CanvasNodeTypeV2;
  creative_role: CanvasCreativeRoleV2;
  role_contract_version: "ad-media-role-v1";
  title: string;
  status: CanvasNodeStatusV2;
  summary_prompt: string | null;
  generation_prompt: string | null;
  structured_content: Record<string, unknown>;
  model_id: string | null;
  parameters: Record<string, unknown>;
  prompt_context_snapshot_id: string | null;
  output_asset_id: string | null;
  position: CanvasPositionV2;
  revision: number;
  error: CanvasNodeErrorV2 | null;
  variation_draft: CanvasVariationDraftV2 | null;
  created_at: string;
  updated_at: string;
}

export interface CanvasBindingSourceNodeV2 {
  kind: "node_output";
  source_node_id: string;
}

export interface CanvasBindingSourceImageAssetV2 {
  kind: "image_asset";
  source_asset_id: string;
}

export type CanvasBindingSourceV2 = CanvasBindingSourceNodeV2 | CanvasBindingSourceImageAssetV2;

export interface CanvasBindingV2 {
  binding_id: string;
  workflow_id: string;
  source: CanvasBindingSourceV2;
  target_node_id: string;
  input_role: CanvasBindingInputRoleV2;
  required: boolean;
  enabled: boolean;
  order: number;
  label: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ProjectAssetSummaryV2 {
  asset_id: string;
  project_id: string | null;
  workflow_id: string | null;
  media_type: AgentCanvasAssetMediaTypeV2;
  source_type: AgentCanvasAssetSourceTypeV2;
  semantic_type: string | null;
  display_name: string;
  mime_type: string;
  status: ProjectAssetStatusV2;
  size_bytes: number;
  storage_key: string | null;
  preview_url: string | null;
  media_url: string | null;
  width: number | null;
  height: number | null;
  duration_seconds: number | null;
  checksum: string;
  source_semantic_role: string | null;
  source_node_id: string | null;
  source_execution_id: string | null;
  provider: string | null;
  model_id: string | null;
  prompt_provenance: Record<string, unknown>;
  quality_metadata: Record<string, unknown>;
  created_at: string | null;
}

export interface AgentCanvasWorkflowV2 {
  workflow_id: string;
  project_id: string;
  workflow_schema_version: 2;
  canvas_model: "agent_canvas_v1";
  revision: number;
  layout_revision: number;
  nodes: CanvasNodeV2[];
  bindings: CanvasBindingV2[];
  assets: ProjectAssetSummaryV2[];
}

export interface AgentCanvasProjectCreateResponseV2 extends AgentCanvasWorkflowV2 {
  creative_session_id: string;
}

export interface ResolvedTextInputSnapshotV2 {
  snapshot_type: "text";
  source_kind: "node_output";
  source_node_id: string;
  source_node_revision: number;
  binding_kind: "text_context";
  document_kind: "text" | "script";
  content: string;
  content_hash: string;
  binding_id: string | null;
  input_role: "text_context";
  required: boolean;
  display_order: number;
}

export interface ResolvedMediaInputSnapshotV2 {
  snapshot_type: "media";
  source_kind: "node_output" | "image_asset";
  source_node_id: string | null;
  source_node_revision: number | null;
  binding_kind: "image_reference" | "video_reference" | "audio_reference";
  source_semantic_role: string | null;
  asset_id: string;
  media_type: AgentCanvasAssetMediaTypeV2;
  asset_checksum: string;
  access_descriptor: StorageAccessDescriptorV2;
  binding_id: string | null;
  input_role: CanvasBindingInputRoleV2;
  required: boolean;
  display_order: number;
}

export type ResolvedInputSnapshotV2 = ResolvedTextInputSnapshotV2 | ResolvedMediaInputSnapshotV2;

export interface StorageAccessDescriptorV2 {
  descriptor_type: "asset_content";
  asset_id: string;
  media_url: string;
  checksum: string;
}

export type CanvasExecutionStatusV2 = "queued" | "running" | "waiting" | "completed" | "partial_failed" | "failed" | "cancelled";

export type NodeRuntimePhaseV2 = "waiting_for_input" | "queued" | "running" | "waiting_provider" | "recovering" | "publishing";

export interface NodeRuntimeV2 {
  node_id: string;
  visible_status: CanvasNodeStatusV2;
  phase: NodeRuntimePhaseV2 | null;
  execution_id: string | null;
  provider_task_id: string | null;
  waiting_for_node_ids: string[];
  blocked_by_node_ids: string[];
  attempt_no: number;
  updated_at: string;
  error: CanvasNodeErrorV2 | null;
}

export interface CanvasRuntimeSnapshotV2 {
  workflow_id: string;
  active_execution_id: string | null;
  execution_status: CanvasExecutionStatusV2 | null;
  node_runtime: Record<string, NodeRuntimeV2>;
  queued_node_ids: string[];
  working_node_ids: string[];
  waiting_node_ids: string[];
  ready_node_ids: string[];
  failed_node_ids: string[];
  events_cursor: number;
  updated_at: string;
}

export interface CanvasRuntimeEventV2 {
  seq: number;
  workflow_id: string;
  event_type: string;
  project_id: string | null;
  execution_id: string | null;
  node_id: string | null;
  asset_id: string | null;
  binding_id: string | null;
  conversation_id: string | null;
  turn_id: string | null;
  action_id: string | null;
  trace_id: string | null;
  span_id: string | null;
  created_at: string;
  payload: Record<string, unknown> | null;
}

export interface ProviderModelCapabilityV2 {
  provider: string;
  model_id: string;
  output_type: "script" | AgentCanvasAssetMediaTypeV2;
  accepted_input_types: Array<"text" | "image" | "video" | "audio">;
  max_references: number;
  reference_limits: Partial<Record<AgentCanvasAssetMediaTypeV2, number>>;
  supported_parameters: string[];
  supported_aspect_ratios: string[];
  duration_range_seconds: [number, number] | null;
  pixel_bounds: [number, number] | null;
  available: boolean;
  unavailable_reason: string | null;
  supports_native_audio: boolean;
}

export type ProviderModelCapabilityListV2 = ProviderModelCapabilityV2[];

export interface BindingCapabilityDecisionV2 {
  accepted: boolean;
  target_node_id: string;
  selected_model_id: string | null;
  required_input_types: Array<"text" | "image" | "video" | "audio">;
  compatible_model_ids: string[];
  switch_model_required: boolean;
}

export type SpecialistAgentNameV2 =
  | "script_writer"
  | "product_designer"
  | "prop_designer"
  | "character_designer"
  | "scene_designer"
  | "storyboard_artist"
  | "video_director"
  | "bgm_director"
  | "quick_media_agent";

export type PlanningTopicStatusV2 =
  | "pending"
  | "in_review"
  | "resolved"
  | "skipped"
  | "not_required"
  | "deferred";

export interface PlanningTopicStateV2 {
  topic_id: string;
  skill_run_id: string;
  topic_kind: string;
  display_order: number;
  status: PlanningTopicStatusV2;
  related_node_ids: string[];
  updated_at: string;
}

export interface ChatMessageV2 {
  item_type: "message";
  message_id: string;
  conversation_id: string;
  speaker: "user" | "adcraft_video_agent";
  text: string;
  linked_node_ids: string[];
  script_node_id: string | null;
  proposal_id: string | null;
  sequence: number;
  created_at: string;
}

export interface ChatArtifactCardV2 {
  item_type: "artifact";
  artifact_id: string;
  artifact_kind: "script";
  node_id: string;
  title: string;
  summary: string;
  action_label: "View Script";
  source_turn_id: string | null;
  sequence: number;
  created_at: string;
}

export interface ConceptOptionV2 {
  option_id: string;
  title: string;
  summary_prompt: string;
}

export interface ProposedDraftReferenceV2 {
  source_kind: "node" | "image_asset";
  source_id: string;
  binding_kind: CanvasBindingKindV2;
  input_role: CanvasBindingInputRoleV2;
  required: boolean;
  display_order: number;
  display_name: string;
  media_type: "text" | "image" | "video" | "audio";
}

export interface ConceptProposalV2 {
  proposal_id: string;
  workflow_id: string;
  turn_id: string;
  video_skill_run_id: string | null;
  topic_id: string | null;
  creative_direction_snapshot_id: string | null;
  proposal_revision: number;
  source_proposal_id: string | null;
  proposal_kind: "script" | "product" | "prop" | "character" | "scene" | "storyboard" | "video" | "bgm";
  specialist_name: SpecialistAgentNameV2;
  status: "pending" | "selected" | "revised" | "skipped";
  options: ConceptOptionV2[];
  proposed_references: ProposedDraftReferenceV2[];
  selected_option_id: string | null;
  selection_actor: "user" | "agent" | null;
  created_at: string;
  updated_at: string;
}

export interface ChatProposalCardV2 {
  item_type: "proposal";
  proposal: ConceptProposalV2;
  sequence: number;
  created_at: string;
}

export interface ChatProposalPointerV2 {
  item_type: "proposal_pointer";
  proposal_id: string;
  sequence: number;
  created_at: string;
}

export interface ChatExpertActivityV2 {
  item_type: "expert_activity";
  activity_id: string;
  turn_id: string;
  specialist: SpecialistAgentNameV2;
  label: string;
  operation: string;
  status: "working" | "completed" | "failed";
  sequence: number;
  started_at: string;
  finished_at: string | null;
}

export interface AgentNodeIdRefV2 {
  kind: "node_id";
  node_id: string;
}

export interface AgentOperationResultRefV2 {
  kind: "operation_result";
  operation_id: string;
}

export type AgentNodeRefV2 = AgentNodeIdRefV2 | AgentOperationResultRefV2;

export interface AgentImageAssetRefV2 {
  kind: "image_asset";
  asset_id: string;
}

export type AgentCommandBindingKindV2 =
  | "brief_context"
  | "script_context"
  | "image_reference"
  | "video_reference"
  | "audio_reference";

interface AgentCommandOperationBaseV2 {
  operation_id: string;
}

export interface AgentCreateNodeOperationV2 extends AgentCommandOperationBaseV2 {
  operation_type: "create_draft_node";
  node_type: Exclude<CanvasNodeTypeV2, "editing">;
  creative_role: CanvasCreativeRoleV2;
  title: string;
  summary_prompt: string | null;
  generation_prompt: string | null;
  structured_content: Record<string, unknown>;
  model_id: string | null;
  parameters: Record<string, unknown>;
  source_asset_id: string | null;
  video_skill_run_id: string | null;
  placement_hint: AgentPlacementHintV2;
}

export interface AgentPatchEditableNodeOperationV2 extends AgentCommandOperationBaseV2 {
  operation_type: "patch_editable_node";
  node: AgentNodeRefV2;
  title: string | null;
  summary_prompt: string | null;
  generation_prompt: string | null;
  structured_content: Record<string, unknown> | null;
  model_id: string | null;
  parameters: Record<string, unknown> | null;
}

export interface AgentCreateBindingOperationV2 extends AgentCommandOperationBaseV2 {
  operation_type: "create_binding";
  source: AgentNodeRefV2 | AgentImageAssetRefV2;
  target: AgentNodeRefV2;
  binding_kind: AgentCommandBindingKindV2;
  required: boolean;
  display_order: number;
}

export interface AgentPatchBindingOperationV2 extends AgentCommandOperationBaseV2 {
  operation_type: "patch_binding";
  binding_id: string;
  required: boolean | null;
  enabled: boolean | null;
  display_order: number | null;
}

export interface AgentDeleteBindingOperationV2 extends AgentCommandOperationBaseV2 {
  operation_type: "delete_binding";
  binding_id: string;
}

export interface AgentDeleteNodeOperationV2 extends AgentCommandOperationBaseV2 {
  operation_type: "delete_node";
  node: AgentNodeRefV2;
}

export interface AgentForkReadyMediaOperationV2 extends AgentCommandOperationBaseV2 {
  operation_type: "materialize_sibling_draft";
  source_node: AgentNodeRefV2;
  title: string;
  generation_prompt: string;
  model_id: string | null;
  parameters: Record<string, unknown>;
  placement_hint: AgentPlacementHintV2;
}

export interface AgentRequestNodeRunOperationV2 extends AgentCommandOperationBaseV2 {
  operation_type: "request_node_run";
  node: AgentNodeRefV2;
}

export interface AgentUpdatePlanningTopicOperationV2 extends AgentCommandOperationBaseV2 {
  operation_type: "update_topic_status";
  skill_run_id: string;
  topic_id: string;
  status: "resolved" | "skipped" | "not_required";
  related_nodes: AgentNodeRefV2[];
}

export type AgentCommandOperationV2 =
  | AgentCreateNodeOperationV2
  | AgentPatchEditableNodeOperationV2
  | AgentCreateBindingOperationV2
  | AgentPatchBindingOperationV2
  | AgentDeleteBindingOperationV2
  | AgentDeleteNodeOperationV2
  | AgentForkReadyMediaOperationV2
  | AgentRequestNodeRunOperationV2
  | AgentUpdatePlanningTopicOperationV2;

export type AgentCommandRiskV2 =
  | "reversible_authoring"
  | "destructive_authoring"
  | "external_effect";

export type AgentCommandPlanStatusV2 =
  | "pending_confirmation"
  | "applying"
  | "applied"
  | "rejected"
  | "superseded"
  | "failed";

export interface AgentCommandPlanV2 {
  plan_id: string;
  workflow_id: string;
  conversation_id: string;
  source_turn_id: string;
  context_snapshot_id: string;
  base_workflow_revision: number;
  expires_at: string;
  operations: AgentCommandOperationV2[];
  continuation_requested: boolean;
  risk: AgentCommandRiskV2;
  confirmation_required: boolean;
  target_summary: string;
  operation_fingerprint: string;
  idempotency_key: string;
  status: AgentCommandPlanStatusV2;
  supersedes_plan_id: string | null;
  replacement_plan_id: string | null;
  actor: "agent" | "user" | "system";
  created_at: string;
  updated_at: string;
}

export interface AgentOperationResultV2 {
  operation_id: string;
  node_id: string | null;
  binding_id: string | null;
  execution_id: string | null;
  status: "applied" | "queued" | "failed";
  error_code: string | null;
}

export type AgentActionReceiptStatusV2 =
  | "applied"
  | "applied_with_run_error"
  | "rejected"
  | "failed";

export interface AgentActionReceiptV2 {
  receipt_id: string;
  workflow_id: string;
  plan_id: string | null;
  action_id: string | null;
  actor_kind: "agent" | "user" | "system";
  idempotency_key: string | null;
  status: AgentActionReceiptStatusV2;
  summary: string;
  created_node_ids: string[];
  updated_node_ids: string[];
  deleted_node_ids: string[];
  created_binding_ids: string[];
  deleted_binding_ids: string[];
  queued_execution_ids: string[];
  run_queue_errors: string[];
  operation_results: AgentOperationResultV2[];
  workflow_revision: number;
  before_workflow_revision: number | null;
  placement_hints: AgentPlacementHintV2[];
  continuation_turn_id: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
}

export interface ChatCommandPlanCardV2 {
  item_type: "command_plan";
  command_plan: AgentCommandPlanV2;
  sequence: number;
  created_at: string;
}

export interface ChatActionReceiptCardV2 {
  item_type: "action_receipt";
  action_receipt: AgentActionReceiptV2;
  sequence: number;
  created_at: string;
}

export interface ChatGuidedActionsCardV2 {
  item_type: "guided_actions";
  source_entry_id: string;
  actions: GuidedDeliveryActionV2[];
  sequence: number;
  created_at: string;
}

export type ChatTimelineItemV2 =
  | ChatMessageV2
  | ChatArtifactCardV2
  | ChatProposalCardV2
  | ChatProposalPointerV2
  | ChatExpertActivityV2
  | ChatCommandPlanCardV2
  | ChatActionReceiptCardV2
  | ChatGuidedActionsCardV2;

export interface ChatTimelineListResponseV2 {
  workflow_id: string;
  conversation_id: string | null;
  items: ChatTimelineItemV2[];
  next_after_seq: number;
}

export interface ChatTurnAcceptedV2 {
  workflow_id: string;
  conversation_id: string;
  message_id: string | null;
  turn_id: string;
  status: "queued";
  events_cursor: number;
}

export interface EditingOutputSettingsV2 {
  resolution: string | null;
  aspect_ratio: string | null;
  fps: number | null;
  video_codec: "h264";
  audio_codec: "aac";
  container: "mp4";
}

export interface EditingManifestV2 {
  ordered_video_binding_ids: string[];
  bgm_audio_binding_id: string | null;
  bgm_volume: number;
  output: EditingOutputSettingsV2;
  manifest_revision: number;
}

export interface EditingSkippedInputV2 {
  node_id: string;
  reason: "source_not_ready" | "source_failed" | "source_output_unavailable" | "source_media_invalid";
}

export interface EditingPreviewClipV2 {
  binding_id: string;
  node_id: string;
  asset_id: string | null;
  status: CanvasNodeStatusV2;
  display_order: number;
  preview_url: string | null;
  duration_seconds: number | null;
  warning: string | null;
}

export interface EditingPreviewV2 {
  clips: EditingPreviewClipV2[];
  bgm_binding_id: string | null;
  bgm_node_id: string | null;
  bgm_asset_id: string | null;
  estimated_duration_seconds: number;
  warnings: string[];
}

export interface EditingExportRuntimeV2 {
  export_id: string;
  status: "queued" | "exporting" | "completed" | "failed" | "cancelled";
  manifest_revision: number;
  fingerprint: string;
  ready_video_node_ids: string[];
  skipped_inputs: EditingSkippedInputV2[];
  bgm_node_id: string | null;
  output_asset_id: string | null;
  error: CanvasNodeErrorV2 | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface EditingNodeContentV2 {
  manifest: EditingManifestV2;
  dirty: boolean;
  preview: EditingPreviewV2;
  last_successful_export: EditingExportRuntimeV2 | null;
  active_export: EditingExportRuntimeV2 | null;
}

export interface AgentCanvasProjectCreateRequestV2 {
  name: string;
  description?: string;
  video_skill_id?: string | null;
  video_skill_version?: string | null;
}

export interface CanvasNodeCreateRequestV2 {
  node_type: CanvasNodeTypeV2;
  creative_role: CanvasCreativeRoleV2;
  role_contract_version?: "ad-media-role-v1";
  title: string;
  summary_prompt?: string | null;
  generation_prompt?: string | null;
  structured_content?: Record<string, unknown>;
  model_id?: string | null;
  parameters?: Record<string, unknown>;
  position: CanvasPositionV2;
  clone_inputs_from_node_id?: string | null;
  source_asset_id?: string | null;
}

export interface CanvasNodePatchRequestV2 {
  title?: string | null;
  summary_prompt?: string | null;
  generation_prompt?: string | null;
  structured_content?: Record<string, unknown> | null;
  model_id?: string | null;
  parameters?: Record<string, unknown> | null;
  position?: CanvasPositionV2 | null;
}

export interface CanvasVariationDraftUpsertV2 {
  title: string;
  generation_prompt: string;
  model_id?: string | null;
  parameters?: Record<string, unknown>;
}

export interface CanvasVariationDraftResponseV2 {
  workflow_id: string;
  workflow_revision: number;
  node_id: string;
  variation_draft: CanvasVariationDraftV2;
}

export interface CanvasVariationMaterializeRequestV2 {
  generation_action: "draft_only" | "generate_now";
  position?: CanvasPositionV2 | null;
}

export interface CanvasVariationMaterializeResponseV2 {
  workflow_id: string;
  workflow_revision: number;
  source_node_id: string;
  sibling_node: CanvasNodeV2;
  copied_binding_ids: string[];
  run: Record<string, unknown> | null;
  run_error: CanvasNodeErrorV2 | null;
  placement_hint: AgentPlacementHintV2;
}

export interface CanvasLayoutPositionV2 extends CanvasPositionV2 {
  node_id: string;
}

export interface CanvasLayoutPatchRequestV2 {
  expected_layout_revision: number;
  positions: CanvasLayoutPositionV2[];
}

export interface CanvasLayoutPatchResponseV2 {
  workflow_id: string;
  revision: number;
  layout_revision: number;
  positions: CanvasLayoutPositionV2[];
}

export interface CanvasBindingCreateRequestV2 {
  source: CanvasBindingSourceV2;
  target_node_id: string;
  input_role: CanvasBindingInputRoleV2;
  required?: boolean;
  enabled?: boolean;
  order?: number | null;
  label?: string | null;
  metadata?: Record<string, unknown>;
}

export interface CanvasBindingPatchRequestV2 {
  input_role?: CanvasBindingInputRoleV2 | null;
  required?: boolean | null;
  enabled?: boolean | null;
  order?: number | null;
  label?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface CanvasConnectionRoleRuleV2 {
  source_node_type: CanvasNodeTypeV2;
  target_node_type: CanvasNodeTypeV2;
  roles: CanvasBindingInputRoleV2[];
  default_role: CanvasBindingInputRoleV2;
}

export interface CanvasConnectionPolicyV2 {
  policy_version: "agent_canvas_connection_policy_v1";
  target_node_types: Record<CanvasNodeTypeV2, CanvasNodeTypeV2[]>;
  input_roles: CanvasConnectionRoleRuleV2[];
  image_asset_targets: Partial<Record<CanvasNodeTypeV2, CanvasBindingInputRoleV2[]>>;
  binding_kind_by_source_type: Record<CanvasNodeTypeV2, CanvasBindingKindV2>;
  model_validation: Record<string, string>;
}

export interface CanvasConnectedNodeBindingRequestV2 {
  input_role: CanvasBindingInputRoleV2;
  required?: boolean;
  order?: number | null;
}

export interface CanvasConnectedNodeCreateRequestV2 {
  anchor_node_id: string;
  direction: "upstream" | "downstream";
  node: CanvasNodeCreateRequestV2;
  binding: CanvasConnectedNodeBindingRequestV2;
}

export interface CanvasConnectedNodeCreateResponseV2 {
  workflow_id: string;
  revision: number;
  layout_revision: number;
  node: CanvasNodeV2;
  binding: CanvasBindingV2;
  events_cursor: number;
}

export interface CanvasBindingMutationResponseV2 {
  workflow_id: string;
  revision: number;
  binding: CanvasBindingV2;
  incoming_bindings: CanvasBindingV2[];
  events_cursor: number;
}

export interface CanvasMutationResponseV2 {
  workflow: AgentCanvasWorkflowV2;
  node: CanvasNodeV2 | null;
  binding: CanvasBindingV2 | null;
}

export interface ProjectAssetUploadMetadataV2 {
  media_type: AgentCanvasAssetMediaTypeV2;
  title: string;
  semantic_role?: string | null;
  metadata?: Record<string, unknown>;
}

export interface ProjectAssetUploadResponseV2 {
  workflow_id: string;
  asset: ProjectAssetSummaryV2;
}

export interface ProjectAssetListResponseV2 {
  workflow_id: string;
  assets: ProjectAssetSummaryV2[];
}

export type AgentCanvasImageLibraryCategoryV2 = "character" | "scene" | "prop";

export interface AgentCanvasImageLibraryListResponseV2 {
  items: Array<Record<string, unknown>>;
}

export interface SaveAgentCanvasImageToLibraryRequestV2 {
  category: AgentCanvasImageLibraryCategoryV2;
  display_name: string;
}

export interface AgentCanvasChatMessageRequestV2 {
  text: string;
  mentioned_node_ids: string[];
  mentioned_image_asset_ids: string[];
  video_skill_run_id: string | null;
  auto_continue: boolean;
}

export type GuidedDeliveryActionTypeV2 =
  | "add_another_topic_node"
  | "generate_node"
  | "run_all_drafts"
  | "skip_topic";

export interface GuidedDeliveryActionV2 {
  action_id: string;
  action: GuidedDeliveryActionTypeV2;
  state: "pending" | "applying" | "applied" | "failed";
  creating_turn_id: string;
  expected_semantic_revision: number;
  label: string;
  workflow_id: string;
  proposal_id: string | null;
  topic_id: string | null;
  node_id: string | null;
  ordered_node_ids: string[];
  manifest_revision: number | null;
  confirmation_required: boolean;
  reason: string;
}

export interface CreativeSessionTopicV2 {
  topic_id: string;
  topic_kind: string;
  display_order: number;
  required: boolean;
  specialist_name: SpecialistAgentNameV2;
  status: PlanningTopicStatusV2;
  outcome: string | null;
  related_node_ids: string[];
}

export interface CreativeSessionStateV2 {
  skill_run_id: string;
  workflow_id: string;
  skill_id: string;
  skill_version: string;
  status: "active" | "superseded";
  creative_direction_snapshot_id: string | null;
  current_topic_id: string | null;
  topics: CreativeSessionTopicV2[];
  deferred_topic_ids: string[];
  memory_revision: number;
  updated_at: string;
}

export interface AgentCanvasChatTimelineEntryV2 {
  entry_id: string;
  workflow_id: string;
  conversation_id: string;
  sequence_no: number;
  entry_type:
    | "message"
    | "script_artifact"
    | "concept_proposal"
    | "expert_activity"
    | "planning_progress"
    | "command_plan"
    | "action_receipt";
  speaker: "user" | "adcraft_video_agent" | null;
  content: string;
  metadata: Record<string, unknown>;
  command_plan: AgentCommandPlanV2 | null;
  action_receipt: AgentActionReceiptV2 | null;
  guided_actions: GuidedDeliveryActionV2[];
  created_at: string;
}

export interface AgentCanvasChatTimelineResponseV2 {
  workflow_id: string;
  conversation_id: string | null;
  creative_session: CreativeSessionStateV2 | null;
  items: AgentCanvasChatTimelineEntryV2[];
  next_cursor: number;
}

export interface AgentCanvasChatTurnV2 {
  turn_id: string;
  workflow_id: string;
  conversation_id: string;
  status: "queued" | "running" | "completed" | "failed";
  turn_kind: "message" | "proposal_action" | "command_action" | "guided_action";
  request: Record<string, unknown>;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export type AgentCanvasProposalActionRequestV2 =
  | {
      action: "select";
      option_id: string;
      generation_action: "draft_only" | "generate_now";
      accepted_references?: ProposedDraftReferenceV2[] | null;
      position?: CanvasPositionV2 | null;
      instruction?: null;
    }
  | {
      action: "revise";
      instruction: string;
      option_id?: null;
      generation_action?: null;
      accepted_references?: null;
      position?: null;
    }
  | {
      action: "skip";
      option_id?: null;
      generation_action?: null;
      accepted_references?: null;
      instruction?: null;
      position?: null;
    };

export interface AgentCanvasCommandPlanActionRequestV2 {
  action: "confirm" | "reject";
}

export interface AgentCanvasGuidedActionApplyRequestV2 {
  confirmed: boolean;
}

export interface AgentCanvasVideoSkillRunCreateRequestV2 {
  skill_id: string;
  skill_version: string;
  source_skill_run_id?: string | null;
}

export interface AgentCanvasVideoSkillRunV2 {
  skill_run_id: string;
  workflow_id: string;
  skill_id: string;
  skill_version: string;
  source_skill_run_id: string | null;
  created_at: string;
}

export interface CanvasRunRequestV2 {
  scope: "all_drafts" | "selected_nodes";
  node_ids: string[];
  retry_failed: boolean;
  source_action: string;
}

export interface CanvasRunSkippedNodeV2 {
  node_id: string;
  reason: string;
}

export interface CanvasRunAcceptedV2 {
  workflow_id: string;
  execution_id: string;
  status: CanvasExecutionStatusV2;
  accepted_node_ids: string[];
  joined_node_ids: string[];
  skipped: CanvasRunSkippedNodeV2[];
  waiting_node_ids: string[];
  events_cursor: number;
}

export interface CanvasRunCancelRequestV2 {
  reason: string;
}

export interface CanvasRunCancelResponseV2 {
  workflow_id: string;
  execution_id: string;
  status: "cancellation_requested" | "cancelled";
  cancelled_node_ids: string[];
  events_cursor: number;
}

export interface CanvasRuntimeEventsResponseV2 {
  workflow_id: string | null;
  events: CanvasRuntimeEventV2[];
  next_cursor: number;
}

export interface EditingExportRequestV2 {
  expected_manifest_revision: number;
  availability_policy: "use_ready_inputs";
}

export interface EditingExportAcceptedV2 {
  workflow_id: string;
  node_id: string;
  export_id: string;
  status: "queued" | "exporting" | "completed" | "failed" | "cancelled";
  manifest_revision: number;
  ready_video_node_ids: string[];
  skipped_inputs: EditingSkippedInputV2[];
  bgm_node_id: string | null;
  events_cursor: number;
}

export interface EditingExportCancelResponseV2 {
  workflow_id: string;
  node_id: string;
  export_id: string;
  status: "cancellation_requested" | "cancelled";
  events_cursor: number;
}
