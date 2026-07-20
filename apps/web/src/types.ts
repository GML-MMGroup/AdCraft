export type RouteName = "home" | "projects" | "assets" | "trash" | "workflow" | "api-space";

export type AssetRole = "product" | "character" | "scene" | "reference" | "audio" | "document";
export type AssetType = "image" | "video" | "audio" | "document";
export type RunMode = "mock" | "real";
export type WorkflowRunMode = "run_from_frontier" | "force_rerun_all" | "single_node" | "single_entity";
export type WorkflowStatus = "draft" | "ready" | "running" | "completed" | "failed";
export type WorkflowExecutionStatus = "queued" | "running" | "waiting" | "completed" | "partial_failed" | "failed" | "cancelled";
export type WorkflowNodeExecutionStatus = "pending" | "blocked" | "queued" | "running" | "completed" | "waiting" | "failed" | "skipped" | "cancelled";
export type WorkflowRevisionStatus = "queued" | "running" | "waiting" | "completed" | "failed" | "cancelled";
export type NodeCategory = "agent_text" | "image_generation" | "video_generation" | "audio_generation" | "composition" | "utility" | "agent";
export type GraphValidationLevel = "error" | "warning" | "info";
export type QualityReviewStatus = "passed" | "warning" | "failed" | "unavailable" | "unchecked" | string;
export type AssetLibraryEntityType = "product" | "character" | "scene" | "storyboard" | "storyboard_shot" | "video" | "video_clip" | "bgm" | "style_reference" | "uploaded_reference";
export type AssetLibraryUploadKind = "" | "product" | "character" | "scene" | "style_reference" | "bgm" | "storyboard_image" | "storyboard_video";
export type AssetLibraryGroupUploadKind = "character" | "scene" | "storyboard_shot";
export type AssetReferenceMode = "best_effort" | "strict";
export type AssetReferenceSource = "asset_library" | "canvas_asset";
export type AssetReferenceSuggestCategory = "all" | "character" | "scene" | "style_reference" | "bgm" | "video" | "storyboard" | "canvas";
export type AssetLifecycleState = "uploaded" | "generated" | "candidate" | "selected" | "active" | "archived" | "deleted_missing_file" | string;
export type AssetVisibilityState = "visible" | "hidden" | "archived" | string;
export type AssetOrigin = "user_upload" | "provider_generation" | "revision_candidate" | "working_version" | "imported" | "migration" | string;
export type AssetFlowFailureStage = "none" | "prompt_optimizer" | "reference_policy" | "provider_selection" | "provider_call" | "output_contract" | "persistence" | string;
export type LibraryIngestState = "pending" | "created" | "linked" | "ready" | "failed" | "skipped";

export interface CandidateLibraryState {
  library_state?: LibraryIngestState | string | null;
  library_entity_id?: string | null;
  library_asset_id?: string | null;
  library_error?: string | null;
  source_type?: "upload" | "workflow_generation" | string;
}

export interface AssetLineage {
  workflow_id?: string | null;
  node_id?: string | null;
  node_run_id?: string | null;
  revision_id?: string | null;
  working_version_id?: string | null;
  source_asset_ids?: string[];
  source_entity_ids?: string[];
  prompt_hash?: string | null;
  provider?: string | null;
  provider_model?: string | null;
  created_from_binding_ids?: string[];
  [key: string]: unknown;
}

export interface AssetBinding {
  binding_id?: string | null;
  asset_id?: string | null;
  entity_id?: string | null;
  scope_type?: "global" | "node" | "item" | "shot" | "final_composition" | string;
  scope_id?: string | null;
  role?: string | null;
  media_type?: string | null;
  use_as_prompt?: boolean | null;
  reference_mode?: AssetReferenceMode | string | null;
  lock_identity?: boolean | null;
  binding_source?: string | null;
  priority?: number | null;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ProviderReferencePlan {
  provider?: string | null;
  node_type?: string | null;
  media_type?: string | null;
  accepted_reference_assets?: unknown;
  transformed_reference_assets?: unknown;
  prompt_only_reference_assets?: unknown;
  rejected_reference_assets?: unknown;
  warnings?: unknown;
  errors?: unknown;
  [key: string]: unknown;
}

export interface AssetFlowDebug {
  input_reference_count?: number | null;
  display_asset_count?: number | null;
  prompt_context_asset_count?: number | null;
  provider_reference_asset_count?: number | null;
  prompt_only_asset_count?: number | null;
  rejected_reference_count?: number | null;
  provider_attempt_count?: number | null;
  selected_provider?: string | null;
  failure_stage?: "none" | "prompt_optimizer" | "reference_policy" | "provider_selection" | "provider_call" | "output_contract" | "persistence" | string;
  user_explainable_reason?: string | null;
  warnings?: unknown;
  [key: string]: unknown;
}

export interface QualityReviewIssue {
  code?: string;
  message?: string;
  asset_id?: string | null;
  entity_id?: string | null;
  semantic_type?: string | null;
  severity?: string | null;
  [key: string]: unknown;
}

export interface QualityReviewSummary {
  status?: QualityReviewStatus;
  quality_status?: QualityReviewStatus;
  reviewer?: string | null;
  method?: string | null;
  checked_asset_count?: number | null;
  asset_count?: number | null;
  warning_count?: number | null;
  failed_count?: number | null;
  passed_count?: number | null;
  unavailable_count?: number | null;
  quality_score?: number | null;
  issues?: QualityReviewIssue[];
  warnings?: QualityReviewIssue[];
  asset_issues?: QualityReviewIssue[];
  [key: string]: unknown;
}

export type WorkflowNodeOutput = Record<string, unknown> & {
  quality_summary?: QualityReviewSummary;
};

export interface UploadedAsset {
  asset_id: string;
  asset_type: AssetType;
  media_type?: AssetType | string;
  asset_role: AssetRole;
  filename: string;
  mime_type: string;
  local_path: string;
  uri?: string;
  use_as_prompt?: boolean;
  prompt_targets?: string[];
  size_bytes?: number;
  url?: string;
  remote_url?: string;
  public_url?: string;
  thumbnail_path?: string;
  thumbnail_url?: string;
  poster_path?: string;
  poster_url?: string;
  preview_path?: string;
  preview_url?: string;
  content_hash?: string;
  file_hash?: string;
  output_hash?: string;
  hash?: string;
  etag?: string;
  updated_at?: string;
  node_run_id?: string;
  version?: string | number;
  version_id?: string | null;
  is_active?: boolean;
  is_archived?: boolean;
  run_id?: string;
  entity_type?: AssetLibraryEntityType | string;
  entity_id?: string;
  semantic_type?: string;
  library_entity_id?: string | null;
  library_asset_id?: string | null;
  library_asset_ids?: string[];
  library_state?: LibraryIngestState | string | null;
  library_error?: string | null;
  source_type?: "upload" | "workflow_generation" | string | null;
  library_entity?: AssetLibraryEntitySummary | AssetLibraryEntityDetail;
  library_assets?: UploadedAsset[];
  metadata?: Record<string, unknown>;
  asset_state?: "uploaded" | "generated" | "candidate" | "selected" | "active" | "archived" | "deleted_missing_file" | string;
  asset_visibility?: AssetVisibilityState;
  asset_origin?: AssetOrigin;
  lineage?: AssetLineage;
  quality_status?: QualityReviewStatus;
  quality_score?: number | null;
  quality_issues?: QualityReviewIssue[];
  quality_warnings?: QualityReviewIssue[];
  reviewer?: string | null;
}

export type DynamicMediaItemType =
  | "character"
  | "scene"
  | "storyboard_image"
  | "storyboard_video"
  | "bgm"
  | "product_image"
  | "unknown";

export interface DynamicMediaItemWorkingVersion {
  version_id?: string | null;
  revision_id?: string | null;
  asset_ids?: string[];
  assets?: UploadedAsset[];
  status?: string | null;
  prompt?: string | null;
  provider_prompt?: string | null;
  quality_status?: QualityReviewStatus | string | null;
  quality_issues?: QualityReviewIssue[];
  created_at?: string | null;
  source?: string | null;
  selected_at?: string | null;
  selected_by?: string | null;
  quality_override?: boolean;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface DynamicMediaItem {
  itemId: string;
  itemType: DynamicMediaItemType;
  semanticType?: string | null;
  order?: number | null;
  displayName: string;
  description?: string | null;
  prompt: string;
  negativePrompt?: string | null;
  lifecycleState?: "draft" | "active" | "archived" | string | null;
  shotType?: string | null;
  segmentId?: string | null;
  primarySceneId?: string | null;
  sceneReferenceIds?: string[];
  characterIds?: string[];
  productReferenceIds?: string[];
  styleReferenceIds?: string[];
  noSceneReason?: string | null;
  missingSceneBinding?: boolean;
  referenceBindings?: Record<string, unknown>;
  legacyFallback?: boolean;
  currentWorkingVersion?: DynamicMediaItemWorkingVersion | null;
  selectedVersion?: DynamicMediaItemWorkingVersion | null;
  historyVersions?: DynamicMediaItemWorkingVersion[];
  needsApply?: boolean;
  qualityStatus?: QualityReviewStatus | string | null;
  qualityIssues?: QualityReviewIssue[];
  videoCurrentWorkingVersion?: DynamicMediaItemWorkingVersion | null;
  videoSelectedVersion?: DynamicMediaItemWorkingVersion | null;
  videoHistoryVersions?: DynamicMediaItemWorkingVersion[];
  inputAssetIds: string[];
  inputAssets: UploadedAsset[];
  referenceAssets: UploadedAsset[];
  status: string;
  outputAssets: UploadedAsset[];
  mainAsset?: UploadedAsset | null;
  faceIdAsset?: UploadedAsset | null;
  threeViewAsset?: UploadedAsset | null;
  multiViewAsset?: UploadedAsset | null;
  libraryState?: LibraryIngestState | string | null;
  libraryEntityId?: string | null;
  libraryAssetId?: string | null;
  libraryError?: string | null;
  sourceType?: "upload" | "workflow_generation" | string | null;
  candidateCount?: number;
  candidateWarningCount?: number;
  historyCount?: number;
  durationSeconds?: number | null;
  referenceMode?: AssetReferenceMode | string | null;
  referenceRequired?: boolean;
  identityLocked?: boolean;
  error?: string | null;
  errorCode?: string | null;
  metadata?: Record<string, unknown>;
}

export interface FinalCompositionTimelineClip {
  clip_id: string;
  clip_type: "video" | "image" | "audio" | "subtitle" | string;
  source_asset_id?: string | null;
  source_node_id: string;
  source_item_id?: string | null;
  start_time: number;
  duration: number;
  trim_start?: number | null;
  trim_end?: number | null;
  enabled: boolean;
  stale?: boolean;
  stale_reason?: string | null;
  missing_source?: boolean;
  missing_reason?: string | null;
  text?: string | null;
  transform?: Record<string, unknown>;
  style?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface FinalCompositionTimelineTrack {
  track_id: "video_main" | "image_overlay" | "subtitle" | "audio_bgm" | string;
  track_type: "video" | "image" | "audio" | "subtitle" | string;
  enabled?: boolean;
  order?: number;
  clips: FinalCompositionTimelineClip[];
  [key: string]: unknown;
}

export interface FinalCompositionTimeline {
  timeline_id: string;
  workflow_id: string;
  node_id: "final-composition" | string;
  version: number;
  source_graph_version?: number;
  duration_seconds: number;
  fps?: number;
  resolution?: string;
  aspect_ratio?: string;
  manual_timeline_dirty?: boolean;
  tracks: FinalCompositionTimelineTrack[];
  updated_at?: string;
  updated_by?: string;
  [key: string]: unknown;
}

export interface FinalCompositionAvailableSource {
  source_id?: string | null;
  asset_id: string;
  asset?: UploadedAsset | null;
  source_node_id?: string | null;
  source_item_id?: string | null;
  semantic_type?: string | null;
  source_type?: string | null;
  display_name?: string | null;
  track_id?: "video_main" | "image_overlay" | "subtitle" | "audio_bgm" | string | null;
  accepted?: boolean;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface FinalCompositionTimelineResponse {
  workflow_id: string;
  node_id: "final-composition" | string;
  timeline: FinalCompositionTimeline;
  available_sources: FinalCompositionAvailableSource[];
  stale_clip_ids: string[];
  missing_source_clip_ids: string[];
  stale_reasons?: Record<string, string>;
  missing_source_reasons?: Record<string, string>;
  [key: string]: unknown;
}

export interface FinalCompositionTimelineSaveRequest {
  timeline: FinalCompositionTimeline;
  expected_version: number;
}

export interface FinalCompositionTimelineRenderRequest {
  timeline_id: string;
  timeline_version: number;
  acceptance_policy: "manual_candidate";
}

export interface AssetUploadOptions {
  asset_role?: string;
  use_as_prompt?: boolean;
  prompt_targets?: string[];
  entity_type?: AssetLibraryEntityType;
  semantic_type?: string;
  display_name?: string;
  tags?: string[];
}

export interface AssetUploadGroupOptions extends AssetUploadOptions {
  assets_metadata?: Array<{ filename?: string; semantic_type?: string | null }>;
  description?: string;
}

export interface AssetUploadBatchResponse {
  assets: UploadedAsset[];
  library_entity_id?: string;
  library_asset_ids?: string[];
  library_entity?: AssetLibraryEntitySummary | AssetLibraryEntityDetail;
  library_assets?: UploadedAsset[];
}

export interface AssetLibraryEntitySummary {
  entity_id: string;
  entity_type: AssetLibraryEntityType;
  semantic_type?: string | null;
  display_name: string;
  description?: string | null;
  tags: string[];
  reuse_policy?: string | null;
  source_workflow_id?: string | null;
  source_node_id?: string | null;
  source_entity_id?: string | null;
  asset_ids?: string[];
  assets?: UploadedAsset[];
  asset_count: number;
  preview_asset?: UploadedAsset | null;
  preview_url?: string | null;
  thumbnail_url?: string | null;
  is_archived: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface AssetLibraryEntityDetail extends AssetLibraryEntitySummary {
  assets: UploadedAsset[];
  metadata?: Record<string, unknown>;
}

export interface AssetLibraryReference {
  reference_source?: AssetReferenceSource;
  entity_id?: string | null;
  asset_id?: string | null;
  mention_text?: string;
  display_name?: string;
  role?: string;
  reference_kind?: string;
  use_as_prompt?: boolean;
  lock_identity?: boolean;
  reference_mode?: AssetReferenceMode;
  is_primary?: boolean;
  target_node_id?: string | null;
  target_node_type?: string | null;
  target_node_ids?: string[];
  target_entity_id?: string | null;
  target_item_id?: string | null;
  target_slot_id?: string | null;
  item_id?: string | null;
}

export type ChatNodeReferenceSource = "mention" | "selected_node" | "inferred";

export interface ChatNodeReference {
  node_id: string;
  node_type?: string | null;
  mention_text: string;
  source: ChatNodeReferenceSource;
}

export type CanvasTargetType = "node" | "item" | "slot" | "asset";
export type CanvasTargetIntentScope = "single" | "downstream" | "all_in_node";
export type CanvasTargetReferenceSource = "mention" | "selected_node" | "selected_item" | "selected_asset" | "inferred";

export interface CanvasTargetReference {
  target_type: CanvasTargetType;
  node_id?: string | null;
  item_id?: string | null;
  slot_id?: string | null;
  asset_id?: string | null;
  semantic_type?: string | null;
  intent_scope?: CanvasTargetIntentScope;
  mention_text?: string | null;
  source?: CanvasTargetReferenceSource;
}

export interface AssetReferenceSuggestion extends CandidateLibraryState {
  reference_source: AssetReferenceSource;
  display_name: string;
  entity_id?: string | null;
  asset_id?: string | null;
  entity_type?: AssetLibraryEntityType | string | null;
  semantic_type?: string | null;
  asset_type?: AssetType | string | null;
  role?: string | null;
  mention_text?: string | null;
  tags?: string[];
  preview_url?: string | null;
  thumbnail_url?: string | null;
  thumbnail_path?: string | null;
  local_path?: string | null;
  warning?: string | null;
  warnings?: string[];
  asset?: UploadedAsset | null;
  library_entity?: AssetLibraryEntitySummary | null;
}

export interface AssetReferenceSuggestParams {
  q?: string;
  types?: string | string[];
  workflow_id?: string | null;
  node_id?: string | null;
  include_canvas_assets?: boolean;
  include_library_assets?: boolean;
  limit?: number;
}

export interface AssetReferenceSuggestResponse {
  suggestions: AssetReferenceSuggestion[];
}

export type AgentConversationVisibleAgent =
  | "creative_director"
  | "script_writer"
  | "character_designer"
  | "scene_designer"
  | "storyboard_artist"
  | "video_director"
  | "sound_director"
  | "final_composition_assistant";

export type AgentConversationStatus = "active" | "archived";

export type AgentConversationEventType =
  | "agent_message"
  | "agent_handoff"
  | "node_prompt_updated"
  | "item_prompt_updated"
  | "execution_started"
  | "revision_started"
  | "revision_waiting"
  | "revision_completed"
  | "revision_failed"
  | "clarification_requested"
  | "conversation_memory_updated"
  | "director_context_updated"
  | "specialist_result"
  | "suggested_action"
  | "chat_action_created"
  | "chat_action_applied"
  | "chat_action_rejected"
  | "chat_action_failed"
  | "action_applied"
  | "action_rejected"
  | "error";

export type AgentConversationActionType =
  | "apply_prompt_to_node"
  | "optimize_node_prompt"
  | "run_node"
  | "revise_node_asset"
  | "update_director_context"
  | "create_workflow"
  | (string & {});

export type AgentConversationActionStatus = "pending" | "running" | "applied" | "rejected" | "failed";

export interface AgentConversationEvent {
  event_id: string;
  conversation_id: string;
  event_type: AgentConversationEventType;
  speaker_agent?: AgentConversationVisibleAgent | null;
  target_agent?: AgentConversationVisibleAgent | null;
  workflow_id?: string | null;
  target_node_id?: string | null;
  target_node_type?: string | null;
  text: string;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface AgentConversationSuggestedAction {
  action_id: string;
  conversation_id: string;
  action_type: AgentConversationActionType;
  status: AgentConversationActionStatus;
  speaker_agent: AgentConversationVisibleAgent;
  workflow_id?: string | null;
  target_node_id?: string | null;
  target_node_type?: string | null;
  title: string;
  summary: string;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface AgentConversation {
  conversation_id: string;
  workflow_id?: string | null;
  focus_node_id?: string | null;
  topic: string;
  status: AgentConversationStatus;
  created_at: string;
  updated_at: string;
  events: AgentConversationEvent[];
  suggested_actions: AgentConversationSuggestedAction[];
}

export interface AgentConversationCreateRequest {
  workflow_id?: string | null;
  focus_node_id?: string | null;
  topic?: string;
}

export interface AgentConversationMessageRequest {
  message: string;
  agent_mentions?: AgentConversationVisibleAgent[];
  asset_references?: AssetLibraryReference[];
  node_references?: ChatNodeReference[];
  target_references?: CanvasTargetReference[];
  context?: Record<string, unknown>;
}

export interface AgentConversationListResponse {
  items: AgentConversation[];
}

export interface AgentConversationEventsResponse {
  conversation_id: string;
  events: AgentConversationEvent[];
  suggested_actions: AgentConversationSuggestedAction[];
}

export interface AgentConversationActionResponse {
  conversation_id: string;
  events: AgentConversationEvent[];
  action: AgentConversationSuggestedAction;
}

export interface ReferencePolicy {
  accepted_assets?: unknown;
  transformed_assets?: unknown;
  prompt_only_assets?: unknown;
  rejected_assets?: unknown;
  accepted_reference_assets?: unknown;
  transformed_reference_assets?: unknown;
  prompt_only_reference_assets?: unknown;
  rejected_reference_assets?: unknown;
  warnings?: unknown;
  errors?: unknown;
}

export type ProviderAttemptStatus = "succeeded" | "failed" | "skipped";

export interface ProviderAttempt {
  provider: string;
  status: ProviderAttemptStatus | string;
  error_code?: string | null;
  error?: string | null;
  duration_ms?: number | null;
}

export interface ProviderStrategyDebug {
  selected_provider?: string | null;
  fallback_used?: boolean;
  selection_reason?: string | null;
  reference_mode?: string | null;
  eligible_providers?: string[];
  rejected_providers?: Array<string | Record<string, unknown>>;
  provider_attempts?: ProviderAttempt[];
  fallback_warnings?: Array<string | Record<string, unknown>>;
  provider_reference_plan?: ProviderReferencePlan;
}

export interface PromptOptimizerMetadata {
  optimizer_agent?: string | null;
  selected_skill_ids?: string[];
  optimizer_warnings?: Array<string | Record<string, unknown>>;
  quality_notes?: string | string[] | Record<string, unknown> | null;
}

export type IdentityCertificationStatus =
  | "certified"
  | "experimental"
  | "uncertified"
  | "revoked";

export interface IdentityCertificationIssue {
  code?: string;
  message?: string;
  asset_id?: string | null;
  entity_id?: string | null;
  semantic_type?: string | null;
  [key: string]: unknown;
}

export type IdentityCertificationWarning = IdentityCertificationIssue;
export type IdentityCertificationError = IdentityCertificationIssue;

export interface IdentityCertificationMetadata {
  status?: IdentityCertificationStatus | string;
  mode?: "strict" | "best_effort" | string;
  provider?: string | null;
  model_id?: string | null;
  reference_semantic_types?: string[];
  certification_ids?: string[];
  warnings?: IdentityCertificationWarning[];
  errors?: IdentityCertificationError[];
  [key: string]: unknown;
}

export interface AssetLibraryListFilters {
  entity_type?: AssetLibraryEntityType | "all";
  semantic_type?: string;
  tag?: string;
  q?: string;
  source_workflow_id?: string;
  include_archived?: boolean;
}

export interface AssetLibraryListResponse {
  entities: AssetLibraryEntitySummary[];
}

export interface AssetLibraryEntityDetailResponse {
  entity?: AssetLibraryEntitySummary;
  assets?: UploadedAsset[];
}

export interface AssetLibraryCreateEntityResponse {
  entity_id?: string;
  asset_ids?: string[];
  entity?: AssetLibraryEntitySummary;
  assets?: UploadedAsset[];
}

export interface AssetLibraryCreatePayload {
  source_workflow_id: string;
  source_node_id: string;
  source_entity_id?: string | null;
  entity_type: AssetLibraryEntityType;
  display_name: string;
  asset_ids: string[];
  tags: string[];
  reuse_policy?: string | null;
}

export interface AssetLibraryPatchPayload {
  display_name?: string;
  description?: string | null;
  tags?: string[];
  reuse_policy?: string | null;
  is_archived?: boolean;
}

export interface FrontDeskMessage {
  role: "user" | "assistant";
  content: string;
}

export interface AdRequest {
  product_name: string;
  product_description: string;
  core_selling_point?: string | null;
  target_audience: string;
  campaign_goal?: string;
  desired_emotion?: string;
  duration_seconds?: number;
  visual_style?: string | null;
  references?: string[];
  channels?: string[];
  selected_assets?: UploadedAsset[];
  skip_audio_agents?: boolean;
  audio_mode?: "none" | "bgm_only" | "full";
  output_resolution?: "480p" | "720p" | "1080p" | null;
  aspect_ratio?: "16:9" | "9:16" | "4:3" | "3:4" | "1:1" | "21:9" | null;
}

export interface FrontDeskResponse {
  intent: "conversation" | "needs_clarification" | "ready_for_workflow";
  reply: string;
  ad_request: AdRequest | null;
  missing_fields: string[];
  should_start_workflow: boolean;
}

export interface WorkflowNode {
  id: string;
  type?: string;
  workflow_id?: string;
  node_type?: string;
  category?: NodeCategory | string;
  title: string;
  description?: string;
  position?: CanvasPosition;
  config?: Record<string, unknown>;
  prompt?: string;
  override_prompt?: string;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  input_context?: Record<string, unknown>;
  output?: WorkflowNodeOutput;
  content?: Record<string, unknown>;
  status?: string;
  metadata?: Record<string, unknown>;
  input_assets?: UploadedAsset[];
  output_assets?: UploadedAsset[];
  depends_on?: string[];
  version?: number;
  input_hash?: string | null;
  output_hash?: string | null;
  locked?: boolean;
  stale?: boolean;
  stale_reason?: string | null;
  can_run_standalone?: boolean;
  supports_override_prompt?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface WorkflowEdge {
  id?: string;
  workflow_id?: string;
  source?: string;
  target?: string;
  source_node_id?: string;
  target_node_id?: string;
  source_handle?: string | null;
  target_handle?: string | null;
  label?: string;
  mapping?: WorkflowEdgeMapping[];
  required?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface WorkflowGraph {
  workflow_id: string;
  name?: string;
  description?: string;
  version?: number;
  status?: WorkflowStatus | string;
  metadata?: Record<string, unknown>;
  ad_request?: Partial<AdRequest> | null;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  variables?: WorkflowVariable[];
  transactions?: WorkflowTransaction[];
  viewport?: unknown;
  affected_downstream_nodes?: string[];
  warnings?: GraphValidationIssue[];
  created_at?: string;
  updated_at?: string;
}

export interface WorkflowSaveNodePayload {
  id: string;
  workflow_id: string;
  node_type: string;
  category?: string;
  title: string;
  description?: string;
  position?: CanvasPosition;
  config?: Record<string, unknown>;
  prompt?: string;
  override_prompt?: string;
  input_context?: Record<string, unknown>;
  output?: WorkflowNodeOutput;
  input_assets?: UploadedAsset[];
  output_assets?: UploadedAsset[];
  content?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  status?: string;
  locked?: boolean;
  stale?: boolean;
  stale_reason?: string | null;
}

export interface WorkflowSaveEdgePayload {
  id: string;
  workflow_id: string;
  source_node_id: string;
  target_node_id: string;
  source_handle?: string | null;
  target_handle?: string | null;
  label?: string;
  mapping?: WorkflowEdgeMapping[];
  required?: boolean;
}

export interface WorkflowSavePayload {
  workflow_id?: string;
  name?: string;
  description?: string;
  status?: string;
  metadata?: Record<string, unknown>;
  ad_request?: Partial<AdRequest>;
  nodes: WorkflowSaveNodePayload[];
  edges: WorkflowSaveEdgePayload[];
}

export interface CanvasPosition {
  x: number;
  y: number;
}

export interface WorkflowEdgeMapping {
  from: string;
  to: string;
}

export interface WorkflowVariable {
  variable_id: string;
  name: string;
  description?: string;
  variable_type: "string" | "resource" | "option";
  required?: boolean;
  resource_types?: AssetType[];
  options?: string[];
  is_single?: boolean;
  value?: string | UploadedAsset | UploadedAsset[] | null;
}

export interface WorkflowTransaction {
  id: string;
  type: string;
  summary: string;
  created_at: string;
}

export interface GraphValidationIssue {
  level: GraphValidationLevel;
  code?: string;
  node_id?: string;
  edge_id?: string;
  message: string;
}

export interface GraphValidationResult {
  valid: boolean;
  errors: GraphValidationIssue[];
  warnings: GraphValidationIssue[];
}

export interface WorkflowNodeMutationResponse {
  node: WorkflowNode;
  affected_downstream_nodes?: string[];
  workflow_version?: number;
}

export interface WorkflowNodeDeleteResponse {
  deleted_node_id: string;
  deleted_edge_ids?: string[];
  affected_downstream_nodes?: string[];
  workflow_version?: number;
}

export interface WorkflowEdgeMutationResponse {
  edge?: WorkflowEdge;
  affected_downstream_nodes?: string[];
  workflow_version?: number;
}

export interface WorkflowEdgeDeleteResponse {
  deleted_edge_id: string;
  affected_downstream_nodes?: string[];
  workflow_version?: number;
}

export interface WorkflowNodeVersion {
  version: number;
  node_run_id?: string;
  status?: string;
  created_at?: string;
  output_hash?: string | null;
  active?: boolean;
}

export interface WorkflowNodeVersionsResponse {
  workflow_id: string;
  node_id: string;
  versions: WorkflowNodeVersion[];
}

export interface WorkflowLockResponse {
  node_id: string;
  locked: boolean;
  workflow_version?: number;
}

export interface MarkStaleRequest {
  node_ids: string[];
  include_downstream?: boolean;
  reason?: string;
}

export interface MarkStaleResponse {
  stale_nodes: string[];
}

export interface FromChatResponse {
  front_desk: FrontDeskResponse;
  workflow: WorkflowGraph | null;
}

export interface NodeCatalogItem {
  node_type: string;
  display_name: string;
  category: string;
  description?: string;
  required_inputs?: string[];
  optional_inputs?: string[];
  input_asset_roles?: string[];
  output_asset_roles?: string[];
  supports_override_prompt?: boolean;
  supports_mock?: boolean;
  supports_real?: boolean;
  can_run_standalone?: boolean;
  downstream_nodes?: string[];
}

export interface NodeRunRequest {
  workflow_id?: string | null;
  node_id?: string | null;
  node_type: string;
  item_id?: string | null;
  target_entity_id?: string | null;
  semantic_type?: string | null;
  input_context?: Record<string, unknown>;
  input_assets?: UploadedAsset[];
  library_entity_ids?: string[];
  asset_references?: AssetLibraryReference[];
  reference_mode?: AssetReferenceMode;
  override_prompt?: string | null;
  mode?: RunMode | null;
  media_mode?: RunMode | null;
  save_outputs?: boolean;
  run_downstream?: boolean;
  force_rerun?: boolean;
  auto_resolve?: boolean;
  optimize_only?: boolean;
  revision?: WorkflowRunRevision;
}

export interface MissingInputReport {
  key?: string;
  input_key?: string;
  reason?: string;
  message?: string;
  source_node_id?: string | null;
  required?: boolean;
}

export interface NodeRunResult {
  workflow_id: string;
  node_id: string;
  node_run_id: string;
  node_type: string;
  status: string;
  output?: WorkflowNodeOutput;
  input_assets?: UploadedAsset[];
  output_assets?: UploadedAsset[];
  resolved_input_context?: Record<string, unknown>;
  resolved_input_assets?: UploadedAsset[];
  materialized_prompt?: string | null;
  materialized_assets?: UploadedAsset[];
  source_mappings?: Array<Record<string, unknown>>;
  resolved_prompt_preview?: string;
  resolved_prompt_with_assets?: string | null;
  effective_prompt?: string;
  metadata?: Record<string, unknown>;
  missing_inputs?: MissingInputReport[];
  stale_upstream_nodes?: string[];
  locked_upstream_nodes?: string[];
  trace_path?: string;
  metadata_path?: string;
  error?: string | null;
  has_active_output?: boolean;
  last_failed_run_id?: string | null;
  last_run_id?: string | null;
  active_run_id?: string | null;
  last_error?: string | null;
  reference_policy?: ReferencePolicy;
  selected_provider?: string | null;
  provider_strategy?: ProviderStrategyDebug;
  provider_attempts?: ProviderAttempt[];
  fallback_warnings?: Array<string | Record<string, unknown>>;
  failure_stage?: AssetFlowFailureStage;
  user_explainable_reason?: string | null;
  asset_bindings?: AssetBinding[];
  provider_reference_plan?: ProviderReferencePlan;
  asset_flow_debug?: AssetFlowDebug;
  optimizer_metadata?: PromptOptimizerMetadata;
  identity_certification?: IdentityCertificationMetadata;
}

export interface QualityReviewResponse {
  workflow_id?: string;
  node_id?: string;
  status?: QualityReviewStatus | string;
  quality_summary?: QualityReviewSummary;
  output?: WorkflowNodeOutput;
  output_assets?: UploadedAsset[];
  assets?: UploadedAsset[];
  node?: WorkflowNode;
  run?: NodeRunResult;
  node_run?: NodeRunResult;
  message?: string;
}

export interface ResolvedNodeInputs {
  workflow_id?: string;
  node_id?: string;
  resolved_input_context?: Record<string, unknown>;
  resolved_input_assets?: UploadedAsset[];
  materialized_prompt?: string | null;
  materialized_assets?: UploadedAsset[];
  source_mappings?: Array<Record<string, unknown>>;
  resolved_prompt_preview?: string;
  resolved_prompt_with_assets?: string | null;
  effective_prompt?: string;
  missing_inputs?: MissingInputReport[];
  stale_upstream_nodes?: string[];
  locked_upstream_nodes?: string[];
  reference_policy?: ReferencePolicy;
  selected_provider?: string | null;
  provider_strategy?: ProviderStrategyDebug;
  provider_attempts?: ProviderAttempt[];
  fallback_warnings?: Array<string | Record<string, unknown>>;
  failure_stage?: AssetFlowFailureStage;
  user_explainable_reason?: string | null;
  asset_bindings?: AssetBinding[];
  provider_reference_plan?: ProviderReferencePlan;
  asset_flow_debug?: AssetFlowDebug;
  optimizer_metadata?: PromptOptimizerMetadata;
  identity_certification?: IdentityCertificationMetadata;
}

export interface WorkflowRunRevision {
  mode?: string;
  target_node_id?: string | null;
  target_node_type?: string | null;
  target_entity_id?: string | null;
  target_asset_id?: string | null;
  semantic_type?: string | null;
  target_field?: string | null;
  instruction?: string | null;
  preserve_other_outputs?: boolean;
  library_entity_ids?: string[];
  asset_references?: AssetLibraryReference[];
  reference_mode?: AssetReferenceMode;
}

export interface WorkflowRevisionRequest {
  mode: string;
  target_entity_id: string;
  target_asset_id: string;
  semantic_type: string;
  target_field: string;
  instruction: string | null;
  preserve_other_outputs: boolean;
  asset_references: AssetLibraryReference[];
  library_entity_ids?: string[];
  reference_mode?: AssetReferenceMode;
  provider?: string | null;
  allow_provider_fallback?: boolean;
  provider_hints?: Record<string, unknown>;
  allow_optimizer_fallback?: boolean;
  metadata?: Record<string, unknown>;
}

export type RevisionGenerationStatus =
  | "queued"
  | "running"
  | "waiting"
  | "completed"
  | "failed"
  | "cancelled";

export type RevisionAcceptanceStatus =
  | "pending"
  | "accepted"
  | "rejected"
  | "superseded"
  | "archived";

export type RevisionVisibilityStatus = "visible" | "hidden" | "archived";

export interface RevisionCandidateState extends CandidateLibraryState {
  revisionId: string;
  generationStatus: RevisionGenerationStatus | string;
  acceptanceStatus: RevisionAcceptanceStatus | string;
  visibilityStatus: RevisionVisibilityStatus | string;
  targetEntityId?: string | null;
  semanticType?: string | null;
  asset?: UploadedAsset | null;
  qualityStatus?: QualityReviewStatus | string;
  issueCount: number;
  reviewer?: string | null;
  librarySuggested?: boolean;
}

export interface WorkflowRevisionAcceptRequest {
  note?: string;
  override_quality_failure?: boolean;
}

export interface WorkflowRevisionRejectRequest {
  reason?: string;
}

export interface WorkflowRevisionState extends CandidateLibraryState {
  revision_id: string;
  workflow_id?: string;
  node_id?: string;
  node_type?: string;
  status: WorkflowRevisionStatus | string;
  generation_status?: RevisionGenerationStatus | string;
  acceptance_status?: RevisionAcceptanceStatus | string;
  visibility_status?: RevisionVisibilityStatus | string;
  revision?: WorkflowRunRevision;
  asset_references?: AssetLibraryReference[];
  target_entity_id?: string | null;
  target_asset_id?: string | null;
  semantic_type?: string | null;
  active_asset?: UploadedAsset | null;
  candidate_asset?: UploadedAsset | null;
  candidate_assets?: UploadedAsset[];
  candidate_asset_ids?: string[];
  acceptance_policy?: string | null;
  assets?: UploadedAsset[];
  history?: UploadedAsset[];
  library_suggested?: boolean;
  error?: string | null;
  message?: string | null;
  affected_downstream_nodes?: string[];
  optimizedRevisionPrompt?: string | null;
  providerRevisionPrompt?: string | null;
  revisionRequirements?: unknown;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export interface WorkflowRevisionListResponse {
  revisions: WorkflowRevisionState[];
}

export interface WorkflowAssetHistoryResponse {
  workflow_id?: string;
  node_id?: string;
  entity_id?: string | null;
  semantic_type?: string | null;
  active_asset?: UploadedAsset | null;
  assets: UploadedAsset[];
  revisions?: WorkflowRevisionState[];
  history?: UploadedAsset[];
}

export interface WorkflowItemUseCurrentVersionRequest {
  force_use_current_version?: boolean;
  use_for_composition?: boolean;
}

export interface WorkflowItemUseCurrentVersionResponse {
  workflow_id?: string;
  node_id?: string;
  item_id?: string;
  selected_version?: DynamicMediaItemWorkingVersion | null;
  current_working_version?: DynamicMediaItemWorkingVersion | null;
  needs_apply?: boolean;
  lifecycle_state?: string | null;
  affected_downstream_node_ids?: string[];
  affected_downstream_nodes?: string[];
  message?: string | null;
  [key: string]: unknown;
}

export interface WorkflowItemRegenerateRequest {
  prompt_scope: "item" | string;
  source_item_id: string;
  source_item_prompt: string;
  source_asset_id?: string | null;
  source_asset_prompt?: string | null;
  reference_asset_ids?: string[];
  asset_slot_id?: string | null;
  semantic_type?: string | null;
  asset_references?: AssetLibraryReference[];
  library_entity_ids?: string[];
  reference_mode?: AssetReferenceMode;
  provider?: string | null;
  allow_provider_fallback?: boolean;
  provider_hints?: Record<string, unknown>;
  allow_optimizer_fallback?: boolean;
  metadata?: Record<string, unknown>;
}

export interface WorkflowItemRegenerateResponse extends CandidateLibraryState {
  workflow_id?: string;
  node_id?: string;
  item_id?: string;
  status?: string | null;
  generation_status?: string | null;
  current_working_version?: DynamicMediaItemWorkingVersion | null;
  selected_version?: DynamicMediaItemWorkingVersion | null;
  needs_apply?: boolean;
  affected_downstream_node_ids?: string[];
  affected_downstream_nodes?: string[];
  message?: string | null;
  error?: string | null;
  [key: string]: unknown;
}

export type WorkflowItemBatchUseScope = "listed_items" | "all_needs_apply_in_node" | "selected_shots";

export interface WorkflowItemBatchUseCurrentVersionsRequest {
  item_ids?: string[];
  scope: WorkflowItemBatchUseScope | string;
  use_for_composition?: boolean;
}

export interface WorkflowItemBatchUseCurrentVersionsResponse {
  workflow_id?: string;
  node_id?: string;
  applied_item_ids?: string[];
  skipped_items?: Array<Record<string, unknown>>;
  failed_items?: Array<Record<string, unknown>>;
  affected_downstream_node_ids?: string[];
  affected_downstream_nodes?: string[];
  message?: string | null;
  [key: string]: unknown;
}

export interface StoryboardShotVideoGenerationResponse {
  workflow_id?: string;
  shot_id?: string;
  status?: string;
  current_working_version?: DynamicMediaItemWorkingVersion | null;
  per_shot_status?: Array<Record<string, unknown>>;
  applied_item_ids?: string[];
  skipped_items?: Array<Record<string, unknown>>;
  failed_items?: Array<Record<string, unknown>>;
  affected_downstream_node_ids?: string[];
  affected_downstream_nodes?: string[];
  message?: string | null;
  [key: string]: unknown;
}

export interface WorkflowRunRequest extends Partial<AdRequest> {
  mode?: WorkflowRunMode;
  target_node_id?: string | null;
  target_node_type?: string | null;
  target_entity_id?: string | null;
  target_asset_id?: string | null;
  library_entity_ids?: string[];
  asset_references?: AssetLibraryReference[];
  reference_mode?: AssetReferenceMode;
  revision?: WorkflowRunRevision;
  force_rerun?: boolean;
  run_downstream?: boolean;
  start_node_id?: string | null;
  only_missing?: boolean;
  download_media?: boolean;
  compose_when_ready?: boolean;
  ad_request?: Partial<AdRequest>;
}

export interface WorkflowExecutionNodeState {
  node_id: string;
  node_type?: string;
  status: WorkflowNodeExecutionStatus | string;
  selected?: boolean;
  started_at?: string | null;
  finished_at?: string | null;
  node_run_id?: string | null;
  output_status?: string | null;
  has_active_output?: boolean | null;
  error?: string | null;
  skipped_reason?: string | null;
  waiting_reason?: string | null;
  metadata?: Record<string, unknown>;
}

export interface WorkflowExecutionState {
  workflow_id?: string;
  execution_id: string;
  status?: WorkflowExecutionStatus | string;
  request?: Record<string, unknown>;
  mode?: WorkflowRunMode | string;
  frontier_node_id?: string | null;
  nodes?: WorkflowExecutionNodeState[];
  selected_node_ids?: string[];
  queued_node_ids?: string[];
  running_node_ids?: string[];
  waiting_node_ids?: string[];
  completed_node_ids?: string[];
  failed_node_ids?: string[];
  skipped_node_ids?: string[];
  started_at?: string | null;
  finished_at?: string | null;
  final_result?: WorkflowRunResponse | Record<string, unknown> | null;
  error?: string | null;
}

export type WorkflowExecutionEventType =
  | "execution_queued"
  | "execution_started"
  | "node_started"
  | "node_completed"
  | "node_waiting"
  | "node_failed"
  | "node_skipped"
  | "execution_completed"
  | "execution_waiting"
  | "execution_failed";

export interface WorkflowExecutionEvent {
  seq?: number;
  sequence?: number;
  event_type?: WorkflowExecutionEventType | string;
  type?: WorkflowExecutionEventType | string;
  workflow_id?: string;
  execution_id?: string;
  node_id?: string | null;
  status?: string | null;
  message?: string | null;
  created_at?: string | null;
  payload?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface WorkflowExecutionEventsResponse {
  workflow_id?: string;
  execution_id?: string;
  events: WorkflowExecutionEvent[];
  next_after_seq?: number;
}

export interface WorkflowRunResponse {
  workflow_id?: string;
  execution_id?: string;
  status?: string;
  selected_node_ids?: string[];
  queued_node_ids?: string[];
  waiting_node_ids?: string[];
  executed_nodes?: string[];
  skipped_nodes?: string[];
  stale_nodes?: string[];
  failed_nodes?: string[];
  nodes?: WorkflowExecutionNodeState[];
  mode?: WorkflowRunMode | string;
  frontier_node_id?: string | null;
  executed_node_ids?: string[];
  skipped_node_ids?: string[];
  failed_node_id?: string | null;
  running_node_ids?: string[];
  completed_node_ids?: string[];
  failed_node_ids?: string[];
  execution?: WorkflowExecutionState | null;
  graph?: WorkflowGraph;
  media_status?: Record<string, unknown> | null;
  final_video?: UploadedAsset | Record<string, unknown> | string | null;
  message?: string;
  reference_policy?: ReferencePolicy;
}

export interface MediaPollRequest {
  download_media?: boolean;
  compose_when_ready?: boolean;
  wait_until_ready?: boolean;
  interval_seconds?: number;
  max_attempts?: number;
}

export interface MediaStatus {
  workflow_id?: string;
  status?: string;
  storyboard_video_status?: string;
  final_composition_status?: string;
  final_video?: UploadedAsset | Record<string, unknown> | null;
  segments?: Array<Record<string, unknown>>;
  segments_ready?: boolean;
  ready_segment_count?: number;
  total_segment_count?: number;
  ready_segments?: number;
  total_segments?: number;
  all_ready?: boolean;
  all_segments_ready?: boolean;
  timed_out?: boolean;
  attempts?: number;
  message?: string;
}

export interface MediaPollResponse extends MediaStatus {
  downloaded?: Array<Record<string, unknown>>;
  composed?: Record<string, unknown> | null;
}

export interface VideoEditingExportRequest {
  workflow_id: string;
  timeline: Record<string, unknown>;
  export_settings: Record<string, unknown>;
}

export interface VideoEditingExportResult {
  workflow_id: string;
  export_id: string;
  status: string;
  local_path?: string | null;
  intended_local_path?: string | null;
  public_url?: string | null;
  duration_seconds?: number | null;
  resolution?: string | null;
  aspect_ratio?: string | null;
  source_clips?: Array<Record<string, unknown>>;
  subtitle_tracks?: Array<Record<string, unknown>>;
  watermark?: Record<string, unknown> | null;
  ffmpeg_commands?: string[];
  metadata_path?: string | null;
  created_at?: string | null;
  error?: string | null;
}
