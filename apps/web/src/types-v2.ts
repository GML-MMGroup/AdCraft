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
export type ProjectCoverStateV2 = "ready" | "unresolved" | "none" | "broken";
export type ProjectCoverSourceV2 = "manual" | "product_main" | "migrated";

export interface ProjectCoverV2 {
  asset_id: string;
  version_id: string;
  media_type: "image" | "video";
  preview_url: string;
  poster_url: string | null;
}

export interface ProjectV2Summary {
  project_id: string;
  workflow_id: string;
  name: string;
  status: ProjectV2Status;
  is_favorite: boolean;
  cover_asset_id: string | null;
  cover_version_id?: string | null;
  cover_state?: ProjectCoverStateV2;
  cover_source?: ProjectCoverSourceV2 | null;
  cover_updated_at?: string | null;
  cover?: ProjectCoverV2 | null;
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
  cover_version_id?: string | null;
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

export type CanvasNodeExecutionModeV2 = "generative" | "source_only";

export type CanvasCreativeRoleV2 =
  | "creative_brief"
  | "world_setting"
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

export interface WorldSettingAuthoringProvenanceV2 {
  source_proposal_id: string;
  source_option_id: string;
  materialization_run_id: string;
  style_skill_run_id: string | null;
  creative_direction_snapshot_id: string | null;
}

export interface WorldSettingCoreV2 {
  premise: string;
  era_and_place: string;
  world_rules: string[];
  visual_continuity: string[];
}

export interface WorldSettingDocumentV2 {
  document_kind: "world_setting";
  contract_version: "world-setting-v2";
  content: string;
  core: WorldSettingCoreV2;
  authoring_provenance: WorldSettingAuthoringProvenanceV2;
}

export type CanvasBindingInputRoleV2 =
  | "text_context"
  | "image_reference"
  | "video_reference"
  | "audio_reference";

export type CanvasBindingKindV2 = CanvasBindingInputRoleV2;

export type AgentCanvasAssetMediaTypeV2 = "image" | "video" | "audio";

export type AgentCanvasAssetSourceTypeV2 =
  | "upload"
  | "generated"
  | "recommended"
  | "library"
  | "editing_export"
  | "derived";

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

export type NodePromptPreparationStatusV1 =
  | "queued"
  | "working"
  | "waiting_user"
  | "ready"
  | "failed"
  | "superseded"
  | "not_applicable";

export interface ResolvedNodeParameterV2 {
  name: string;
  value: unknown;
  source_kind:
    | "explicit_user"
    | "bound_text"
    | "node_parameter"
    | "storyboard_plan"
    | "style_advice"
    | "installation_default";
  source_id: string;
  source_revision: number | null;
}

export interface PromptAssertionSourceSnapshotV1 {
  schema_version: "1";
  source_kind: "binding" | "document" | "sequence";
  binding_id: string | null;
  binding_revision: number | null;
  source_node_id: string | null;
  source_node_revision: number | null;
  asset_id: string | null;
  asset_version_id: string | null;
  reference_purpose: string | null;
  document_id: string | null;
  document_revision: number | null;
  sequence_id: string | null;
}

export interface PromptAssertionEvidenceV1 {
  schema_version: "1";
  policy_ref: string;
  policy_version: string;
  policy_digest: string;
  recipe_id: string;
  recipe_version: string;
  assertion_ids: string[];
  assertion_block_digest: string;
  prepared_prompt_digest: string;
  source_snapshots: PromptAssertionSourceSnapshotV1[];
  document_revisions: Record<string, number>;
  sequence_id: string | null;
  engine_owned_fields_digest: string;
  evidence_digest: string;
}

export interface RolePromptCompactionDecisionV2 {
  block_id: string;
  source_id: string;
  source_digest: string;
  precedence: number;
  outcome: "compacted" | "preserved";
  retained_block_id: string | null;
  retained_precedence: number | null;
  reason:
    | "policy_disabled"
    | "not_eligible"
    | "ownership_unknown"
    | "identity_unproven"
    | "exact_duplicate"
    | "preserved_authority";
}

/**
 * Backend-owned prompt authoring progress for a visible Draft node.
 * It deliberately does not alter the Canvas node's four visible statuses.
 */
export interface NodePromptPreparationV1 {
  status: NodePromptPreparationStatusV1;
  operation_id: string | null;
  presentation_stream_id: string | null;
  attempt_no: number;
  context_snapshot_id: string | null;
  occurrence_id: string | null;
  character_phase: "main" | "turnaround" | null;
  prompt_digest: string | null;
  role_variant: string | null;
  recipe_id: string | null;
  recipe_version: string | null;
  recipe_digest: string | null;
  requirement_revision_id: string | null;
  requirement_revision_no: number | null;
  document_revisions: Record<string, number>;
  binding_digest: string | null;
  style_projection_digest: string | null;
  brief_digest: string | null;
  parameter_origins: ResolvedNodeParameterV2[];
  compaction_policy_version: string | null;
  compaction_policy_digest: string | null;
  compaction_decisions: RolePromptCompactionDecisionV2[];
  assertion_evidence: PromptAssertionEvidenceV1 | null;
  attempt_stage: string | null;
  error: CanvasNodeErrorV2 | null;
  updated_at: string;
}

export type CanvasModelSelectionModeV2 = "default" | "explicit";
export type CanvasRoleContractVersionV2 = "ad-media-role-v1" | "ad-media-role-v2";

export interface CanvasModelSummaryV2 {
  model_ref: string;
  provider_id: string;
  display_name: string;
  capability: "text" | "image" | "video" | "audio";
  availability: "available" | "unavailable" | "unauthorized" | "unsupported" | "deprecated";
  unavailable_reason: string | null;
  catalog_revision: number;
}

export type CanvasParameterOriginV2 =
  | "manual"
  | "node_prompt"
  | "binding"
  | "user_explicit"
  | "structured_content"
  | "guidance_default"
  | "role_default"
  | "provider_clamp";
export type CanvasParameterScalarV2 = string | number | boolean;

export interface CanvasParameterProvenanceV2 {
  origin: CanvasParameterOriginV2;
  source_node_id: string | null;
  binding_id: string | null;
  source_revision: number | null;
  requested_value: CanvasParameterScalarV2;
  effective_value: CanvasParameterScalarV2;
  normalization_code: string | null;
}

/** Secret-safe model identity frozen for one runtime attempt. */
export interface CanvasRuntimeModelResolutionV2 {
  node_id: string;
  model_ref: string;
  provider_id: string;
  provider_model_id: string;
  credential_revision: number;
  catalog_revision: number;
}

export interface CanvasVariationDraftV2 {
  source_node_id: string;
  source_node_revision: number;
  title: string;
  generation_prompt: string;
  model_id: string | null;
  model_selection_mode: CanvasModelSelectionModeV2;
  model_ref: string | null;
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
  role_contract_version: CanvasRoleContractVersionV2;
  title: string;
  status: CanvasNodeStatusV2;
  execution_mode: CanvasNodeExecutionModeV2;
  summary_prompt: string | null;
  generation_prompt: string | null;
  structured_content: Record<string, unknown>;
  model_id: string | null;
  model_selection_mode: CanvasModelSelectionModeV2;
  model_ref: string | null;
  model_summary: CanvasModelSummaryV2 | null;
  parameters: Record<string, unknown>;
  metadata: Record<string, unknown>;
  parameter_provenance: Record<string, CanvasParameterProvenanceV2>;
  prompt_context_snapshot_id: string | null;
  output_asset_id: string | null;
  position: CanvasPositionV2;
  revision: number;
  error: CanvasNodeErrorV2 | null;
  prompt_preparation: NodePromptPreparationV1 | null;
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
  /** Null only for legacy persisted bindings created before immutable AssetVersion references. */
  source_asset_version_id: string | null;
}

export type CanvasBindingSourceV2 = CanvasBindingSourceNodeV2 | CanvasBindingSourceImageAssetV2;

export interface CanvasBindingSourceImageAssetWriteV2 {
  kind: "image_asset";
  source_asset_id: string;
  source_asset_version_id: string;
}

export type CanvasBindingSourceWriteV2 = CanvasBindingSourceNodeV2 | CanvasBindingSourceImageAssetWriteV2;

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
  version_id: string | null;
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
  actual_media_facts: Record<string, unknown>;
  generation_provenance: Record<string, unknown>;
  quality_metadata: Record<string, unknown>;
  created_at: string | null;
}

export interface VideoSkillPreviewV2 {
  kind: "none" | "image" | "video";
  summary: string | null;
  media_url: string | null;
}

export interface VideoSkillCategoryV2 {
  category_id: string;
  title: string;
  display_order: number;
}

export interface VideoSkillPublicDetailV2 {
  skill_id: string;
  version: string;
  title: string;
  summary: string;
  category: string;
  tags: string[];
  supported_use_cases: string[];
  preview: VideoSkillPreviewV2 | null;
  display_order: number;
}

export interface VideoSkillSummaryListV2 {
  items: VideoSkillPublicDetailV2[];
  next_cursor: string | null;
}

export interface VideoSkillCatalogResponseV2 extends VideoSkillSummaryListV2 {
  catalog_version: string;
  categories: VideoSkillCategoryV2[];
}

export interface ActiveStyleSkillSummaryV2 {
  skill_run_id: string;
  skill_id: string;
  skill_version: string;
  title: string;
  summary: string;
  category: string;
  creative_direction_snapshot_id: string;
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
  active_style_skill: ActiveStyleSkillSummaryV2 | null;
}

export type AgentMediaExecutionModeV2 = "manual" | "automatic";

export interface AgentExecutionSettingsV2 {
  workflow_id: string;
  media_execution_mode: AgentMediaExecutionModeV2;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface AgentExecutionSettingsPatchV2 {
  media_execution_mode: AgentMediaExecutionModeV2;
}

export type AgentWorkingDocumentKindV2 =
  | "anchor_registry"
  | "storyboard_production_plan";

export type AgentAnchorTypeV2 =
  | "subject"
  | "environment"
  | "world_setting"
  | "style"
  | "composition";

export interface AgentAnchorV2 {
  alias: string;
  anchor_type: AgentAnchorTypeV2;
  display_name: string;
  summary: string;
  source_kind: "node" | "image_asset" | "skill_snapshot";
  source_id: string | null;
  availability: "pending" | "available" | "failed";
}

export interface AnchorRegistryContentV2 {
  anchors: AgentAnchorV2[];
}

export type AgentAnchorSemanticRoleV3 =
  | "world_setting"
  | "product"
  | "prop"
  | "character"
  | "scene"
  | "style"
  | "composition";

export interface AgentAnchorNodeSourceV3 {
  source_kind: "node";
  workflow_id: string;
  node_id: string;
  node_revision: number;
}

export type AgentAnchorSourceV3 =
  | AgentAnchorNodeSourceV3
  | {
      source_kind: "image_asset_version";
      workflow_id: string;
      node_id: string;
      node_revision: number;
      asset_id: string;
      asset_version_id: string;
    }
  | {
      source_kind: "skill_snapshot";
      skill_id: string;
      skill_version: string;
      package_digest: string;
    };

export type AgentAnchorMaterializedRoleV3 =
  | "product_main"
  | "product_multiview"
  | "character_main"
  | "character_turnaround";

export interface AgentAnchorRoleSourceV3 {
  role: AgentAnchorMaterializedRoleV3;
  source: AgentAnchorNodeSourceV3;
}

export interface AnchorAcceptanceEvidenceV1 {
  evidence_id: string;
  actor: "user" | "agent" | "system";
  decision: "accepted" | "delegated" | "activated" | "retired" | "invalidated";
  action_id: string;
  requirement_revision_id: string;
  requirement_revision_no: number;
  node_revision: number | null;
  asset_version_id: string | null;
  document_revision: number;
  recorded_at: string;
}

export interface AgentAnchorV3 {
  alias: string;
  identity_id: string;
  semantic_role: AgentAnchorSemanticRoleV3;
  display_name: string;
  summary: string;
  lifecycle: "planned" | "active" | "retired" | "invalid";
  source: AgentAnchorSourceV3;
  role_sources: AgentAnchorRoleSourceV3[];
  acceptance_evidence: AnchorAcceptanceEvidenceV1[];
}

export interface AnchorRegistryContentV3 {
  schema_version: "3";
  anchors: AgentAnchorV3[];
}

export interface StoryboardPlanGlobalParametersV2 {
  aspect_ratio: string;
  total_duration_seconds: number;
  segment_count: number;
}

export interface StoryboardNarrativeSegmentV2 {
  sequence_id: string;
  order: number;
  start_seconds: number;
  end_seconds: number;
  narrative_goal: string;
  start_state: string;
  end_state: string;
  continuity_from_previous: string | null;
  terminal_policy: "continue" | "close" | null;
}

export interface StoryboardPlanRowV2 {
  shot_index: number;
  sequence_id: string;
  panel_index: number;
  content_beat: string;
  anchor_aliases: string[];
  camera_description: string;
}

export interface StoryboardNodeRecordV2 {
  sequence_id: string | null;
  node_role: "storyboard_grid" | "video_segment" | "bgm" | "editing";
  node_id: string;
}

export interface StoryboardSegmentMaterializationV2 {
  sequence_id: string;
  status: "pending" | "materialized";
  generation_prompt: string | null;
}

export interface StoryboardVisualAnchorV2 {
  node_id: string;
  asset_id: string;
  node_revision: number;
  document_revision: number;
}

export interface StoryboardPlannedNodeV3 {
  sequence_id: string | null;
  node_role: StoryboardNodeRecordV2["node_role"];
  node_id: string;
  node_revision: number;
  materialization_id: string;
}

export interface StoryboardExcludedMediaV3 {
  sequence_id: string | null;
  node_role: "video_segment" | "bgm";
  node_id: string;
  node_revision: number;
  action_id: string;
}

export interface StoryboardVisualAnchorV3 {
  sequence_id: string;
  node_id: string;
  node_revision: number;
  asset_id: string;
  asset_version_id: string;
  acceptance_evidence_id: string;
}

export interface StoryboardProductionPlanContentV2 {
  narrative_outline: string;
  global_parameters: StoryboardPlanGlobalParametersV2;
  segments: StoryboardNarrativeSegmentV2[];
  rows: StoryboardPlanRowV2[];
  node_records: StoryboardNodeRecordV2[];
  materialized_panel_cursor: number;
  segment_materializations: StoryboardSegmentMaterializationV2[];
  visual_anchor: StoryboardVisualAnchorV2 | null;
}

export interface StoryboardProductionPlanContentV3 {
  schema_version: "3";
  narrative_outline: string;
  requirement_revision_id: string;
  requirement_revision_no: number;
  global_parameters: StoryboardPlanGlobalParametersV2;
  segments: StoryboardNarrativeSegmentV2[];
  rows: StoryboardPlanRowV2[];
  planned_nodes: StoryboardPlannedNodeV3[];
  excluded_media: StoryboardExcludedMediaV3[];
  visual_anchor: StoryboardVisualAnchorV3 | null;
}

export interface AgentDocumentLinkedNodeRuntimeV2 {
  node_id: string;
  node_type: CanvasNodeTypeV2;
  creative_role: string;
  status: CanvasNodeStatusV2;
  revision: number;
}

interface AgentWorkingDocumentBaseV2 {
  document_id: string;
  workflow_id: string;
  guidance_session_id: string;
  title: string;
  revision: number;
  content_schema_version: 2 | 3;
  content_digest: string;
  created_by_agent_run_id: string;
  updated_by_agent_run_id: string;
  linked_nodes: AgentDocumentLinkedNodeRuntimeV2[];
  created_at: string;
  updated_at: string;
}

export interface AgentAnchorRegistryDocumentV2 extends AgentWorkingDocumentBaseV2 {
  kind: "anchor_registry";
  content: AnchorRegistryContentV2 | AnchorRegistryContentV3;
}

export interface AgentStoryboardProductionPlanDocumentV2 extends AgentWorkingDocumentBaseV2 {
  kind: "storyboard_production_plan";
  content: StoryboardProductionPlanContentV2 | StoryboardProductionPlanContentV3;
}

export type AgentWorkingDocumentV2 =
  | AgentAnchorRegistryDocumentV2
  | AgentStoryboardProductionPlanDocumentV2;

export interface AgentWorkingDocumentPageV2 {
  items: AgentWorkingDocumentV2[];
  next_cursor: string | null;
}

export interface AgentCanvasProjectCreateResponseV2 extends AgentCanvasWorkflowV2 {
  active_style_skill_run_id: string;
  guidance_session_id: string | null;
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

export type CanvasExecutionStatusV2 = "queued" | "running" | "waiting" | "completed" | "partial_completed" | "failed" | "cancelled";

export type CanvasPostReadyCheckpointStatusV2 = "pending" | "completed" | "failed";

export type CanvasPostReadyEffectTypeV2 =
  | "persist_script_document"
  | "persist_text_document"
  | "advance_storyboard_progression";

export type CanvasPostReadyEffectStatusV2 = "queued" | "running" | "completed" | "failed";

export interface CanvasPostReadyEffectCountsV2 {
  total: number;
  queued: number;
  running: number;
  completed: number;
  failed: number;
}

export interface CanvasPostReadyEffectSummaryV2 {
  effect_id: string;
  effect_type: CanvasPostReadyEffectTypeV2;
  node_id: string;
  status: CanvasPostReadyEffectStatusV2;
  attempt_no: number;
  error: CanvasNodeErrorV2 | null;
  updated_at: string;
}

/**
 * Backend-owned post-ready work which must settle before an otherwise valid
 * guidance transition can be accepted.
 */
export interface CanvasPostReadyCheckpointV2 {
  checkpoint_id: string;
  workflow_id: string;
  execution_id: string;
  execution_status: CanvasExecutionStatusV2;
  status: CanvasPostReadyCheckpointStatusV2;
  counts: CanvasPostReadyEffectCountsV2;
  effects: CanvasPostReadyEffectSummaryV2[];
  error: CanvasNodeErrorV2 | null;
  updated_at: string;
}

export type NodeRuntimePhaseV2 =
  | "waiting_for_input"
  | "blocked_by_upstream"
  | "queued"
  | "running"
  | "waiting_provider"
  | "recovering"
  | "publishing";

export interface VideoParameterNormalizationV2 {
  field: "duration_seconds" | "resolution" | "aspect_ratio" | "generate_audio";
  requested_value: CanvasParameterScalarV2;
  effective_value: CanvasParameterScalarV2;
  normalization_code:
    | "duration_clamped_to_minimum"
    | "duration_clamped_to_maximum"
    | "resolution_reduced_to_supported";
}

export interface NodeRuntimeV2 {
  node_id: string;
  visible_status: CanvasNodeStatusV2;
  phase: NodeRuntimePhaseV2 | null;
  execution_id: string | null;
  provider_task_id: string | null;
  run_intent_snapshot_id: string | null;
  parameter_compilation_snapshot_id: string | null;
  input_manifest_id?: string | null;
  effective_parameters: Record<string, unknown>;
  normalizations: Array<string | VideoParameterNormalizationV2>;
  omitted_optional_inputs: Array<Record<string, unknown>>;
  waiting_reason?: string | null;
  missing_required_source_node_ids?: string[];
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
  transition_key?: string | null;
  attempt?: number | null;
  created_at: string;
  payload: Record<string, unknown> | null;
}

export type PresentationStreamKindV1 = "assistant" | "node_prompt";
export type PresentationStreamStatusV1 = "open" | "completed" | "failed" | "superseded";
export type PresentationStreamEventTypeV1 =
  | "started"
  | "delta"
  | "committed"
  | "failed"
  | "superseded"
  | "reset"
  | "heartbeat";

export interface PresentationStreamResetV1 {
  reason: "cursor_expired" | "store_recovered";
  authoritative_id: string | null;
  resource_kind: "message" | "prompt" | "workflow";
}

export interface PresentationStreamEventV1 {
  schema_version: 1;
  stream_id: string;
  workflow_id: string;
  stream_kind: PresentationStreamKindV1;
  event_type: PresentationStreamEventTypeV1;
  sequence_no: number;
  turn_id: string | null;
  node_id: string | null;
  generation_id: string;
  response_locale: string | null;
  node_revision: number | null;
  delta: string | null;
  authoritative_id: string | null;
  content_digest: string | null;
  error_code: string | null;
  reset: PresentationStreamResetV1 | null;
}

export interface ProviderResolvedTextInputAuditV2 {
  binding_id: string;
  source_node_id: string;
  snapshot_id: string | null;
  input_role: "text_context";
  required: boolean;
  display_order: number;
}

export type WorldSettingContextAudienceV2 =
  | "script_writer"
  | "product_designer"
  | "prop_designer"
  | "character_designer"
  | "scene_designer"
  | "storyboard_artist"
  | "video_director"
  | "bgm_director";

export interface ProviderResolvedWorldSettingInputAuditV2 {
  binding_id: string;
  source_node_id: string;
  source_node_revision: number;
  source_content_digest: string;
  source_core_digest: string;
  required: boolean;
  display_order: number;
  target_audience: WorldSettingContextAudienceV2;
  compiler_id: string;
  compiler_digest: string;
  context_digest: string;
}

export interface ProviderResolvedMediaInputAuditV2 {
  binding_id: string;
  source_node_id: string | null;
  asset_id: string;
  media_type: AgentCanvasAssetMediaTypeV2;
  input_role: CanvasBindingInputRoleV2;
  source_semantic_role: string | null;
  transport_type: string | null;
  required: boolean;
  display_order: number;
}

export interface ProviderOmittedOptionalInputAuditV2 {
  binding_id: string;
  source_node_id: string | null;
  reason_code: string;
}

/** A browser-safe projection of one backend-resolved provider input manifest. */
export interface ProviderInputManifestAuditV2 {
  node_id: string;
  input_manifest_id: string;
  execution_id: string | null;
  node_run_id: string | null;
  text_inputs: ProviderResolvedTextInputAuditV2[];
  world_setting_inputs: ProviderResolvedWorldSettingInputAuditV2[];
  media_inputs: ProviderResolvedMediaInputAuditV2[];
  omitted_optional_inputs: ProviderOmittedOptionalInputAuditV2[];
}

export interface UpstreamInputReadinessIssueV2 {
  target_node_id: string;
  source_node_ids: string[];
}

export interface ProviderModelCapabilityV2 {
  provider: string;
  model_id: string;
  output_type: AgentCanvasAssetMediaTypeV2;
  accepted_input_types: Array<"text" | "image" | "video" | "audio">;
  max_references: number;
  reference_limits: Partial<Record<AgentCanvasAssetMediaTypeV2, number>>;
  supported_parameters: string[];
  default_parameters: Record<string, unknown>;
  supported_resolutions: string[];
  supported_aspect_ratios: string[];
  duration_range_seconds: [number, number] | null;
  pixel_bounds: [number, number] | null;
  available: boolean;
  unavailable_reason: string | null;
  supports_native_audio: boolean;
  capability_revision: number;
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

export type AgentCapabilityIdV2 =
  | "world_setting"
  | "product_design"
  | "prop_design"
  | "character_design"
  | "scene_design"
  | "script_authoring"
  | "storyboard_design"
  | "video_direction"
  | "bgm_direction"
  | "quick_media";

export interface CapabilityIdentityV2 {
  capability_id: AgentCapabilityIdV2;
  capability_display_name: string;
}

export interface ChatMessageV2 {
  item_type: "message";
  message_kind: "conversation" | "planning_progress";
  message_id: string;
  conversation_id: string;
  speaker: "user" | "adcraft_video_agent";
  text: string;
  linked_node_ids: string[];
  script_node_id: string | null;
  proposal_id: string | null;
  capability_id: AgentCapabilityIdV2 | null;
  /** Structured presentation metadata retained from the authoritative timeline. */
  metadata?: Record<string, unknown>;
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

export interface CapabilityProposalOptionV2 {
  option_id: string;
  title: string;
  public_summary: string;
  /** Backend public projections may omit this private field; normalizers fill it with []. */
  key_decisions: string[];
}

export type ProposalMaterializationStatusV2 = "queued" | "working" | "failed" | "completed";

export interface ProposalMaterializationErrorV2 {
  code: string;
  message: string;
}

export interface ProposalMaterializationProjectionV2 {
  materialization_id: string;
  option_id: string;
  turn_id: string;
  status: ProposalMaterializationStatusV2;
  attempt_no: number;
  retryable: boolean;
  error: ProposalMaterializationErrorV2 | null;
  created_at: string;
  updated_at: string;
}

export interface ProposalApplicationSummaryV2 {
  application_id: string;
  option_id: string;
  action: "select_option" | "custom_direction" | "delegate_choice" | "reuse_direction";
  receipt_id: string;
  created_node_ids: string[];
  queued_execution_ids: string[];
  created_at: string;
}

export type ProposalAvailabilityV2 = "open" | "applied" | "superseded";
export type ProposalActionTypeV2 =
  | "select_option"
  | "custom_direction"
  | "revise_options"
  | "defer_topic"
  | "exclude_element"
  | "delegate_choice"
  | "reuse_direction"
  | "revise_direction";

export interface ProposalActionDescriptorV2 {
  action_id: string;
  action: ProposalActionTypeV2;
  label: string;
  proposal_id: string;
  expected_session_revision: number;
  confirmation_required: boolean;
  reason: string;
  option_id: string | null;
  enabled: boolean;
  disabled_reason: string | null;
}

export interface ProposedDraftReferenceV2 {
  source_kind: "node" | "image_asset";
  source_id: string;
  binding_kind: CanvasBindingKindV2;
  input_role: CanvasBindingInputRoleV2;
  required: boolean;
  display_order: number;
  semantic_reference_role: SemanticReferenceRoleV2 | null;
  occurrence_id: string | null;
  character_phase: "main" | "turnaround" | null;
  display_name: string;
  media_type: "text" | "image" | "video" | "audio";
}

export type SemanticReferenceRoleV2 =
  | "world_setting_reference"
  | "subject_reference"
  | "environment_reference"
  | "product_reference"
  | "prop_reference"
  | "style_reference"
  | "style_composition_reference"
  | "storyboard_visual_reference";

export type ConceptProposalKindV2 =
  | "world_setting"
  | "script"
  | "product"
  | "prop"
  | "character"
  | "scene"
  | "storyboard"
  | "video"
  | "bgm";

export interface ConceptProposalV2 extends CapabilityIdentityV2 {
  proposal_id: string;
  workflow_id: string;
  turn_id: string;
  video_skill_run_id: string | null;
  topic_id: string | null;
  occurrence_id: string | null;
  occurrence_index: number | null;
  occurrence_count: number | null;
  character_phase: "main" | "turnaround" | null;
  creative_direction_snapshot_id: string | null;
  proposal_revision: number;
  source_proposal_id: string | null;
  proposal_kind: ConceptProposalKindV2;
  options: CapabilityProposalOptionV2[];
  proposed_references: ProposedDraftReferenceV2[];
  target_node_id: string | null;
  target_node_revision: number | null;
  proposal_purpose: string | null;
  availability: ProposalAvailabilityV2;
  application_count: number;
  latest_application: ProposalApplicationSummaryV2 | null;
  materialization: ProposalMaterializationProjectionV2 | null;
  guidance_session_id: string;
  guidance_session_revision: number;
  actions: ProposalActionDescriptorV2[];
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

export interface ChatCapabilityActivityV2 extends CapabilityIdentityV2 {
  item_type: "expert_activity";
  activity_id: string;
  turn_id: string;
  status: "working" | "completed" | "failed" | "superseded";
  sequence: number;
  started_at: string;
  finished_at: string | null;
  message: string | null;
  presentation_text?: string | null;
  error_code: string | null;
  elapsed_ms: number | null;
  attempt_stage: "initial" | "transport_retry" | "structured_repair" | "fallback" | null;
  retryable: boolean;
  validation_paths: string[];
  suggested_actions: Array<"retry" | "revise_request">;
  completion_mode: "deterministic_fallback" | null;
  warning_code: "specialist_materialization_fallback" | null;
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
  model_selection_mode: CanvasModelSelectionModeV2;
  model_ref: string | null;
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
  model_selection_mode: CanvasModelSelectionModeV2 | null;
  model_ref: string | null;
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
  model_selection_mode: CanvasModelSelectionModeV2;
  model_ref: string | null;
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
  | "not_applied"
  | "rejected"
  | "superseded"
  | "failed";

export interface AgentActionReceiptV2 {
  receipt_id: string;
  workflow_id: string;
  plan_id: string | null;
  action_id: string | null;
  proposal_id: string | null;
  proposal_option_id: string | null;
  proposal_action: ProposalActionTypeV2 | null;
  actor_kind: "agent" | "user" | "system";
  occurrence_id: string | null;
  character_phase: "main" | "turnaround" | null;
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
  superseded_by: string | null;
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

export interface ChatAgentDocumentReferenceV2 {
  item_type: "agent_document";
  document_id: string;
  document_kind: AgentWorkingDocumentKindV2;
  revision: number;
  content_digest: string;
  title: string;
  sequence: number;
  created_at: string;
}

export interface DecisionBundleOptionV2 {
  option_id: string;
  label: string;
  description: string;
}

export interface DecisionBundleQuestionV2 {
  question_id: string;
  prompt: string;
  selection_mode: "single" | "multiple";
  allow_custom_answer: boolean;
  allow_skip: boolean;
  options: DecisionBundleOptionV2[];
}

export interface DecisionBundleAnswerV2 {
  question_id: string;
  selected_option_ids: string[];
  custom_answer: string | null;
  skipped: boolean;
}

export interface DecisionBundleV2 {
  bundle_id: string;
  workflow_id: string;
  conversation_id: string;
  source_turn_id: string;
  replacement_bundle_id: string | null;
  status: "open" | "answered" | "skipped" | "superseded";
  revision: number;
  title: string;
  introduction: string;
  questions: DecisionBundleQuestionV2[];
  answers: DecisionBundleAnswerV2[];
  requirement_revision_no: number | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
}

export type DecisionBundleActionRequestV2 =
  | {
      action: "submit";
      expected_revision: number;
      answers: DecisionBundleAnswerV2[];
    }
  | {
      action: "skip_bundle";
      expected_revision: number;
    };

export interface DecisionBundleActionAcceptedV2 {
  workflow_id: string;
  bundle_id: string;
  status: "answered" | "skipped";
  revision: number;
  requirement_revision_no: number;
  turn_id: string;
  events_cursor: number;
  replayed: boolean;
}

export interface ChatDecisionBundlePointerV2 {
  item_type: "decision_bundle_pointer";
  bundle_id: string;
  sequence: number;
  created_at: string;
}

export interface ChatDecisionBundleCardV2 {
  item_type: "decision_bundle";
  decision_bundle: DecisionBundleV2;
  sequence: number;
  created_at: string;
}

export type ChatTimelineItemV2 =
  | ChatMessageV2
  | ChatArtifactCardV2
  | ChatProposalCardV2
  | ChatProposalPointerV2
  | ChatCapabilityActivityV2
  | ChatCommandPlanCardV2
  | ChatActionReceiptCardV2
  | ChatAgentDocumentReferenceV2
  | ChatDecisionBundleCardV2
  | ChatDecisionBundlePointerV2;

export interface ChatTimelineListResponseV2 {
  workflow_id: string;
  conversation_id: string | null;
  guidance_advance_precondition: GuidanceAdvancePreconditionV1 | null;
  items: ChatTimelineItemV2[];
  next_after_seq: number;
}

export interface ChatTimelinePresentationViewItemV2 {
  presentation_key: string;
  presentation_revision: number;
  source_entry_ids: string[];
  message_key: string | null;
  message_args: Record<string, unknown>;
  response_locale: string;
  item: ChatTimelineItemV2;
}

export interface AgentCanvasChatViewTimelineV2 {
  workflow_id: string;
  conversation_id: string | null;
  guidanceSession: GuidedSessionStateV2 | null;
  /** Server-issued authority snapshot for one deterministic Guidance Advance. */
  guidanceAdvancePrecondition: GuidanceAdvancePreconditionV1 | null;
  continuations: AgentCanvasContinuationV2[];
  current_session_actions: GuidanceSessionActionV2[];
  items: ChatTimelineItemV2[];
  /** Null means an older backend has not added the presentation projection yet. */
  presentationItems: ChatTimelinePresentationViewItemV2[] | null;
  next_cursor: number;
}

export interface ChatTurnAcceptedV2 {
  workflow_id: string;
  conversation_id: string;
  message_id: string | null;
  turn_id: string;
  status: "queued";
  events_cursor: number;
  retry_of_turn_id: string | null;
  retry_attempt_no: number;
  replayed: boolean;
  presentation_stream_id: string | null;
}

export interface EditingOutputSettingsV2 {
  resolution: string | null;
  aspect_ratio: string | null;
  fps: number | null;
  video_codec: "h264";
  audio_codec: "aac";
  container: "mp4";
}

export interface EditingVideoEntryV2 {
  binding_id: string | null;
  asset_id: string | null;
  enabled: boolean;
  timeline_start_seconds?: number;
  trim_start_seconds: number;
  trim_end_seconds: number | null;
  volume: number;
  preserve_native_audio: boolean;
  transition: "cut" | "fade";
  transition_duration_seconds: number;
  fit_mode: "fit" | "fill";
}

export interface EditingBgmEntryV2 {
  binding_id: string | null;
  asset_id: string | null;
  enabled: boolean;
  trim_start_seconds: number;
  trim_end_seconds: number | null;
  volume: number;
  fade_in_seconds: number;
  fade_out_seconds: number;
}

export interface EditingManifestV2 {
  video_entries: EditingVideoEntryV2[];
  bgm: EditingBgmEntryV2 | null;
  output: EditingOutputSettingsV2;
  manifest_revision: number;
  timeline_duration_seconds?: number;
}

export interface EditingSkippedInputV2 {
  reference_id: string;
  node_id: string | null;
  asset_id: string | null;
  reason: "source_not_ready" | "source_failed" | "source_output_unavailable" | "source_media_invalid";
}

export interface EditingPreviewClipV2 {
  reference_id: string;
  binding_id: string | null;
  node_id: string | null;
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
  role_contract_version?: CanvasRoleContractVersionV2;
  title: string;
  summary_prompt?: string | null;
  generation_prompt?: string | null;
  structured_content?: Record<string, unknown>;
  model_selection_mode?: CanvasModelSelectionModeV2;
  model_ref?: string | null;
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
  model_selection_mode?: CanvasModelSelectionModeV2;
  model_ref?: string | null;
  parameters?: Record<string, unknown> | null;
  position?: CanvasPositionV2 | null;
}

export interface CanvasVariationDraftUpsertV2 {
  title: string;
  generation_prompt: string;
  model_selection_mode?: CanvasModelSelectionModeV2;
  model_ref?: string | null;
  parameters?: Record<string, unknown>;
}

export interface CanvasVariationDraftResponseV2 {
  workflow_id: string;
  workflow_revision: number;
  node_id: string;
  variation_draft: CanvasVariationDraftV2;
}

export interface CanvasVariationMaterializeRequestV2 {
  action: "create_draft" | "generate";
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
  created_node_ids: string[];
  created_binding_ids: string[];
  placement_hints: AgentPlacementHintV2[];
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
  source: CanvasBindingSourceWriteV2;
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
  pending_handoff_id: string | null;
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
}

export type GuidanceOutputKindV2 = "text" | "script" | "image" | "video" | "audio";

export type GuidanceTopicKindV2 =
  | "world_setting"
  | "creative_direction"
  | "product"
  | "prop"
  | "character"
  | "scene"
  | "script"
  | "storyboard"
  | "video"
  | "audio";

export type AgentCanvasCreationModeV2 =
  | "ordinary_conversation"
  | "targeted_authoring"
  | "quick_media"
  | "guided_production";

export interface CreationModeDecisionV2 {
  mode: AgentCanvasCreationModeV2;
  reason: string;
  target_node_id: string | null;
  target_asset_id: string | null;
}

export interface CreativeGoalV2 {
  requested_output: GuidanceOutputKindV2;
  delivery_scope: "draft" | "generated_media";
  summary: string;
  explicit_constraints: Record<string, unknown>;
}

export interface CreativeElementDecisionV2 {
  element_kind: Exclude<GuidanceTopicKindV2, "creative_direction">;
  presence: "include" | "exclude" | "unspecified";
  authority: "user" | "agent";
  requirements: Record<string, unknown>;
  source: "explicit_user" | "accepted_proposal" | "delegated_to_agent";
}

export interface GuidanceTopicStateV2 extends CapabilityIdentityV2 {
  topic_id: string;
  topic_kind: GuidanceTopicKindV2;
  title: string;
  status: "proposed" | "selected" | "deferred" | "excluded";
  related_node_ids: string[];
  source_proposal_id: string | null;
  revision: number;
}

export interface GuidanceCompletionProjectionV2 {
  authoring: "not_ready" | "ready";
  delivery: "not_ready" | "ready";
  plan_document_id: string | null;
  plan_revision: number | null;
  editing_preparation: "not_ready" | "prepared";
  editing_node_id: string | null;
  preparation_receipt_id: string | null;
  manifest_revision: number | null;
  export_status: "not_started" | "queued" | "exporting" | "completed" | "failed" | "cancelled";
  export_id: string | null;
  final_completion_receipt_id: string | null;
  final_asset_id: string | null;
  matching_node_ids: string[];
  matching_asset_ids: string[];
}

export type CreativeAuthorityV2 = "user" | "director";
export type CreativeAuthoritySourceV2 =
  | "explicit_user"
  | "explicit_delegation"
  | "director_inference";

export interface CreativeAuthorityStateV2 {
  authority: CreativeAuthorityV2;
  source: CreativeAuthoritySourceV2;
  decided_at_turn_id: string;
  revision: number;
}

export type GuidanceStageKindV2 =
  | "world_setting"
  | "narrative_direction"
  | "product"
  | "prop"
  | "character"
  | "scene"
  | "script"
  | "storyboard"
  | "video"
  | "bgm"
  | "editing";

export interface GuidedStepCheckpointV2 {
  checkpoint_id: string;
  workflow_id: string;
  session_revision: number;
  stage_kind: GuidanceStageKindV2 | null;
  status: "pending" | "waiting_user" | "completed" | "failed" | "superseded";
  trigger: "user_message" | "proposal_action" | "continuation" | "recovery";
  action_id: string | null;
}

export type GuidedJourneyStageV2 =
  | "intake"
  | "world_view"
  | "product"
  | "props"
  | "character"
  | "scene"
  | "narrative_direction"
  | "style_lock"
  | "storyboard_plan"
  | "storyboard_grids"
  | "videos"
  | "bgm"
  | "editing"
  | "completed";

export type GuidedJourneyStageStatusV2 =
  | "ready"
  | "working"
  | "waiting_user"
  | "blocked_external"
  | "failed"
  | "completed";

export interface JourneyElementDecisionV2 {
  decision_id: string;
  element_kind: string;
  occurrence_id: string;
  occurrence_index: number;
  outcome: "include" | "exclude" | "delegate" | "unresolved";
  source: "user" | "delegated" | "system";
  source_revision: number;
  requirements: Record<string, unknown>;
}

export interface JourneyActionProjectionV2 {
  action_id: string;
  action_kind: string;
  stage: GuidedJourneyStageV2;
  stage_revision: number;
  status: "reserved" | "working" | "waiting_user";
  turn_id: string | null;
  occurrence_id: string | null;
  character_phase: "main" | "turnaround" | null;
}

export interface JourneyTransitionEvidenceV2 {
  evidence_id: string;
  evidence_kind:
    | "creative_goal_validated"
    | "clarification_completed"
    | "world_view_selected"
    | "world_view_delegated"
    | "world_view_excluded"
    | "product_materialized"
    | "product_delegated"
    | "product_excluded"
    | "props_materialized"
    | "props_delegated"
    | "props_excluded"
    | "character_materialized"
    | "character_delegated"
    | "character_excluded"
    | "scene_materialized"
    | "scene_delegated"
    | "scene_excluded"
    | "narrative_direction_accepted"
    | "style_lock_accepted"
    | "storyboard_plan_accepted"
    | "storyboard_plan_excluded"
    | "storyboard_grids_prepared"
    | "storyboard_grids_excluded"
    | "videos_prepared"
    | "videos_excluded"
    | "bgm_prepared"
    | "bgm_delegated"
    | "bgm_excluded"
    | "editing_prepared"
    | "editing_export_completed"
    | "editing_excluded"
    | "targeted_action_started"
    | "targeted_action_finished"
    | "stage_failed";
  source_id: string;
  source_revision: number | null;
  stage: GuidedJourneyStageV2;
  stage_revision: number;
  occurrence_id: string | null;
  character_phase: "main" | "turnaround" | null;
  actor: "user" | "delegated" | "system";
  recorded_at: string;
}

export interface GuidedProductionJourneyV2 {
  policy_version: "fixed_ad_production_v2";
  stage: GuidedJourneyStageV2;
  stage_status: GuidedJourneyStageStatusV2;
  stage_revision: number;
  decisions: JourneyElementDecisionV2[];
  active_occurrence_id: string | null;
  active_action: JourneyActionProjectionV2 | null;
  suspended_action: JourneyActionProjectionV2 | null;
  transition_evidence: JourneyTransitionEvidenceV2[];
}

export type GuidedInteractionKindV1 =
  | "clarification_questionnaire"
  | "product_source"
  | "concept_choice"
  | "media_review"
  | "reference_source";
export type GuidedInteractionStatusV1 = "open" | "submitted" | "closed" | "superseded";
export type GuidedInteractionActionV1 =
  | "answer"
  | "select_source"
  | "use_reference"
  | "skip_reference"
  | "select"
  | "custom"
  | "skip"
  | "revise"
  | "defer"
  | "exclude"
  | "delegate"
  | "accept"
  | "retry"
  | "replace";

export interface GuidedReferencePreviewV1 {
  source_kind: "node" | "image_asset";
  source_id: string;
  display_name: string;
  media_type: "text" | "image" | "video" | "audio";
}

export interface GuidedChoiceOptionV1 {
  option_id: string;
  title: string;
  summary: string;
  difference_tags: string[];
  recommended: boolean;
  reference_preview: GuidedReferencePreviewV1[];
}

export interface GuidedQuestionV1 {
  question_id: string;
  prompt: string;
  input_kind: "single_select";
  options: GuidedChoiceOptionV1[];
  allow_custom: boolean;
  allow_skip: boolean;
  required: boolean;
}

export interface GuidedAcceptedReferenceV1 extends GuidedReferencePreviewV1 {
  binding_kind: string;
  input_role: string;
  required: boolean;
  display_order: number;
  semantic_reference_role: string | null;
  occurrence_id: string | null;
  character_phase: "main" | "turnaround" | null;
}

export interface GuidedProductAssetVersionRefV1 {
  asset_id: string;
  version_id: string;
}

export interface GuidedProductSourceActionV1 {
  input_kind: "main" | "multiview";
  choice: "upload" | "generate";
  handoff_mode: "pending" | "apply";
  asset_versions: GuidedProductAssetVersionRefV1[];
  pending_handoff_id: string | null;
  expected_guidance_revision: number;
  question_id: string;
}

export type GuidedReferenceKindV1 = "character_main" | "scene_main";
export type GuidedReferenceActionV1 = "use_reference" | "skip_reference";
export type GuidedReferenceCandidateScopeV2 = "project" | "mine" | "recommended";

export interface GuidedReferenceCandidateV2 {
  entity_id: string | null;
  member_id: string | null;
  asset_id: string;
  asset_version_id: string;
  media_type: "image";
  display_name: string;
  preview_url: string;
  content_url: string;
  reference_kind: GuidedReferenceKindV1;
  semantic_reference_role: "character_reference" | "scene_reference";
  reference_purpose: "identity_guidance" | "environment_guidance";
  selectable: boolean;
}

export interface GuidedReferenceCandidateListResponseV2 {
  workflow_id: string;
  reference_kind: GuidedReferenceKindV1;
  scope: GuidedReferenceCandidateScopeV2;
  items: GuidedReferenceCandidateV2[];
  next_cursor: string | null;
}

export interface GuidedReferenceSourceQuestionV1 {
  content_kind: "reference_source";
  reference_kind: GuidedReferenceKindV1;
  target_node_id: string;
  target_node_revision: number;
  occurrence_id: string | null;
  question: string;
  use_reference_label: string;
  skip_reference_label: string;
  expected_guidance_revision: number;
}

export type GuidedInteractionContentV1 =
  | { content_kind: "questionnaire"; questions: GuidedQuestionV1[] }
  | {
      content_kind: "product_source";
      input_kind: "main" | "multiview";
      question_id: string;
      prompt: string;
      expected_guidance_revision: number;
      min_asset_count: number;
      max_asset_count: number;
    }
  | {
      content_kind: "concept_choice";
      proposal_id: string | null;
      stage: GuidedJourneyStageV2;
      stage_revision: number;
      action_id: string;
      occurrence_id: string | null;
      occurrence_index?: number | null;
      occurrence_count?: number | null;
      character_phase?: "main" | null;
      capability_id: string;
      options: GuidedChoiceOptionV1[];
      allow_custom: true;
      allow_exclusion: boolean;
    }
  | {
      content_kind: "media_review";
      node_id: string;
      node_revision: number;
      asset_id: string;
      asset_version_id: string;
      summary: string;
    }
  | GuidedReferenceSourceQuestionV1;

export interface GuidedInteractionV1 {
  interaction_id: string;
  workflow_id: string;
  session_id: string;
  checkpoint_id: string;
  kind: GuidedInteractionKindV1;
  status: GuidedInteractionStatusV1;
  response_locale: string;
  expected_session_revision: number;
  revision: number;
  title: string;
  context: string;
  content: GuidedInteractionContentV1;
  allowed_actions: GuidedInteractionActionV1[];
  submit_path: string;
  created_at: string;
  updated_at: string;
}

export type GuidedInteractionSubmitRequestV1 =
  | {
      submission_kind: "questionnaire";
      expected_interaction_revision: number;
      expected_session_revision: number;
      answers: Array<
        | { answer_kind: "option"; question_id: string; option_id: string }
        | { answer_kind: "custom"; question_id: string; value: string }
        | { answer_kind: "skip"; question_id: string }
      >;
    }
  | {
      submission_kind: "product_source";
      expected_interaction_revision: number;
      expected_session_revision: number;
      action: GuidedProductSourceActionV1;
    }
  | {
      submission_kind: "concept_choice";
      expected_interaction_revision: number;
      expected_session_revision: number;
      action: "select" | "custom" | "defer" | "exclude" | "delegate";
      option_id?: string | null;
      custom_text?: string | null;
      accepted_references?: GuidedAcceptedReferenceV1[];
    }
  | {
      submission_kind: "media_review";
      expected_interaction_revision: number;
      expected_session_revision: number;
      action: "accept" | "retry" | "replace" | "exclude";
      instruction?: string | null;
    }
  | {
      submission_kind: "reference_source";
      expected_interaction_revision: number;
      expected_session_revision: number;
      action: GuidedReferenceActionV1;
      reference_kind: GuidedReferenceKindV1;
      source_scope: GuidedReferenceCandidateScopeV2;
      entity_id?: string | null;
      member_id?: string | null;
      asset_id?: string | null;
      asset_version_id?: string | null;
    };

export interface GuidedInteractionAcceptedV1 {
  workflow_id: string;
  interaction_id: string;
  submission_id: string;
  receipt_id: string;
  created_node_ids: string[];
  created_binding_ids: string[];
  document_revisions: Record<string, number>;
  continuation_id: string | null;
  automatic_run_command_ids: string[];
  resulting_session_revision: number;
  events_cursor: number;
  replayed: boolean;
}

export interface GuidanceAwaitingV1 {
  awaiting_id: string;
  workflow_id: string;
  session_id: string;
  checkpoint_id: string;
  kind: "clarification" | "concept_selection" | "product_source" | "media_review" | "reference_source" | "manual_node_run" | "milestone_idle";
  requires_user_action: boolean;
  resume_policy: "submit_interaction" | "node_terminal" | "next_user_message" | "explicit_resume";
  interaction_id: string | null;
  node_ids: string[];
  stage: GuidedJourneyStageV2;
  stage_revision: number;
  created_at: string;
}

/**
 * Opaque, transactionally consistent authority snapshot issued by the Timeline
 * projection. Clients return it unchanged when advancing deterministic guidance.
 */
export interface GuidanceAdvancePreconditionV1 {
  schema_version: "1";
  workflow_id: string;
  workflow_revision: number;
  session_id: string;
  session_revision: number;
  session_status: "active" | "paused" | "completed";
  journey_stage: GuidedJourneyStageV2;
  journey_stage_status: GuidedJourneyStageStatusV2;
  journey_stage_revision: number;
  source_id: string;
  requirement_revision_id: string;
  requirement_digest: string;
  active_action_digest: string;
  owner_state_digest: string;
  authority_digest: string;
}

export interface GuidanceAdvanceRequestV1 {
  precondition: GuidanceAdvancePreconditionV1;
}

export interface GuidedSessionStateV2 {
  session_id: string;
  workflow_id: string;
  status: "active" | "paused" | "completed";
  /** Informational backend locale for generated creative content. */
  response_locale: string;
  goal: CreativeGoalV2;
  creative_authority: CreativeAuthorityStateV2 | null;
  current_checkpoint: GuidedStepCheckpointV2 | null;
  narrative_direction: string | null;
  element_decisions: CreativeElementDecisionV2[];
  current_topic_id: string | null;
  topics: GuidanceTopicStateV2[];
  active_proposal_id: string | null;
  active_style_skill_run_id: string | null;
  completion: GuidanceCompletionProjectionV2;
  journey: GuidedProductionJourneyV2;
  interaction: GuidedInteractionV1 | null;
  awaiting: GuidanceAwaitingV1 | null;
  revision: number;
  updated_at: string;
}

export interface GuidanceSessionActionV2 {
  action_id: string;
  logical_key: string;
  action: "stop_guidance" | "resume_guidance" | "set_creative_authority";
  state: "pending" | "applying" | "applied" | "superseded" | "failed";
  creating_turn_id: string;
  expected_session_revision: number;
  label: string;
  workflow_id: string;
  confirmation_required: boolean;
  reason: string;
  authority: CreativeAuthorityV2 | null;
}

export type AgentContinuationDeliveryStatusV2 =
  | "queued"
  | "leased"
  | "retry_wait"
  | "completed"
  | "failed"
  | "superseded";

export interface AgentCanvasContinuationV2 {
  continuation_id: string;
  delivery_status: AgentContinuationDeliveryStatusV2;
  attempt_count: number;
  next_attempt_at: string | null;
  source_turn_id: string | null;
  continuation_turn_id: string | null;
  occurrence_id: string | null;
  character_phase: "main" | "turnaround" | null;
  action_owner: "guided_journey" | "targeted_authoring" | "quick_media" | null;
  max_attempts: number | null;
  last_error_code: string | null;
  last_error_message: string | null;
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
    | "action_receipt"
    | "agent_document_reference"
    | "decision_bundle";
  speaker: "user" | "adcraft_video_agent" | null;
  content: string;
  metadata: Record<string, unknown>;
  command_plan: AgentCommandPlanV2 | null;
  action_receipt: AgentActionReceiptV2 | null;
  created_at: string;
}

export interface AgentCanvasChatTimelinePresentationItemV2 extends AgentCanvasChatTimelineEntryV2 {
  presentation_key: string;
  presentation_revision: number;
  source_entry_ids: string[];
  message_key: string | null;
  message_args: Record<string, unknown>;
  response_locale: string;
}

export interface AgentCanvasChatTimelineResponseV2 {
  workflow_id: string;
  conversation_id: string | null;
  guidance_session: GuidedSessionStateV2 | null;
  guidance_advance_precondition: GuidanceAdvancePreconditionV1 | null;
  continuations: AgentCanvasContinuationV2[];
  current_session_actions: GuidanceSessionActionV2[];
  items: AgentCanvasChatTimelineEntryV2[];
  /** Null means an older backend has not added the presentation projection yet. */
  presentation_items: AgentCanvasChatTimelinePresentationItemV2[] | null;
  next_cursor: number;
}

export interface AgentCanvasChatTurnV2 {
  turn_id: string;
  workflow_id: string;
  conversation_id: string;
  status: "queued" | "running" | "completed" | "failed" | "superseded";
  turn_kind:
    | "message"
    | "proposal_action"
    | "command_action"
    | "guided_action"
    | "capability"
    | "next_action"
    | "guidance_advance";
  request: Record<string, unknown>;
  error_code: string | null;
  error_message: string | null;
  creation_mode: CreationModeDecisionV2 | null;
  guidance_session_revision: number | null;
  continuation: AgentCanvasContinuationV2 | null;
  retry_of_turn_id: string | null;
  retry_attempt_no: number;
  retryable: boolean;
  operation_stage: string | null;
  operation_failure: AgentOperationFailureV2 | null;
  created_at: string;
  updated_at: string;
}

export interface AgentOperationFailureV2 {
  code: string;
  message: string;
  operation: string;
  capability_id: AgentCapabilityIdV2 | null;
  attempt_stage: "initial" | "transport_retry" | "structured_repair" | "fallback";
  failure_stage:
    | "routing"
    | "proposal"
    | "materialization"
    | "safety"
    | "model_capability"
    | "provider"
    | "asset_publication"
    | "revision";
  elapsed_ms: number;
  retryable: boolean;
  validation_paths: string[];
  occurred_at: string;
}

export interface AgentCanvasChatTurnRetryRequestV2 {
  expected_session_revision: number;
  expected_workflow_revision: number;
}

export type AgentCanvasProposalActionRequestV2 =
  | {
      action_id: string;
      expected_session_revision: number;
      action: "select_option";
      option_id: string;
      accepted_references?: ProposedDraftReferenceV2[] | null;
    }
  | {
      action_id: string;
      expected_session_revision: number;
      action: "custom_direction";
      custom_text: string;
    }
  | {
      action_id: string;
      expected_session_revision: number;
      action: "revise_options";
      instruction: string;
    }
  | {
      action_id: string;
      expected_session_revision: number;
      action: "defer_topic" | "exclude_element" | "delegate_choice";
    }
  | {
      action_id: string;
      expected_session_revision: number;
      action: "reuse_direction";
      option_id: string;
    }
  | {
      action_id: string;
      expected_session_revision: number;
      action: "revise_direction";
      option_id: string;
      instruction: string;
    };

export interface AgentCanvasCommandPlanActionRequestV2 {
  action: "confirm" | "reject";
}

export type AgentCanvasGuidedActionApplyRequestV2 =
  | {
      confirmed: boolean;
      action?: null;
      authority?: null;
      expected_session_revision?: null;
    }
  | {
      confirmed: boolean;
      action: "set_creative_authority";
      authority: CreativeAuthorityV2;
      expected_session_revision: number;
    };

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
  status: "active" | "superseded";
  active_creative_direction_snapshot_id: string | null;
  public_skill: VideoSkillPublicDetailV2 | null;
  created_at: string;
  updated_at: string | null;
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
  run_intent_snapshot_ids: Record<string, string>;
  events_cursor: number;
}

export interface CanvasRunCancelRequestV2 {
  reason: string;
}

export interface CanvasRunCancelResponseV2 {
  workflow_id: string;
  execution_id: string;
  status: "cancelled";
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
  status: "cancelled";
  events_cursor: number;
}

export interface CanvasEditingExportImportRequestV2 {
  export_id: string;
  title?: string | null;
  position: CanvasPositionV2;
}

export interface CanvasEditingExportImportResponseV2 {
  workflow_id: string;
  revision: number;
  layout_revision: number;
  node: CanvasNodeV2;
  binding: CanvasBindingV2;
  asset: ProjectAssetSummaryV2;
  events_cursor: number;
  replayed: boolean;
}
