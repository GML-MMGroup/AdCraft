from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.asset_library import AssetReference
from app.schemas.assets import WorkflowAssetReference
from app.schemas.front_desk import FrontDeskChatResponse
from app.schemas.workflow_v2_intent import V2FrontDeskPlanningSeed


WorkflowNodeStatusV2 = Literal[
    "not_ready",
    "ready",
    "running",
    "waiting",
    "completed",
    "partial_failed",
    "failed",
]
WorkflowSlotStatusV2 = Literal[
    "empty",
    "blocked",
    "ready",
    "running",
    "waiting",
    "completed",
    "failed",
    "skipped",
]
WorkflowMediaTypeV2 = Literal["image", "video", "audio", "text"]
WorkflowOutputResolutionV2 = Literal["480p", "720p", "1080p"]
WorkflowAssetSourceTypeV2 = Literal["upload", "generated", "imported", "derived"]
V2PromptMaterializerMode = Literal["real", "fallback", "mock"]
V2ProviderExecutionStatus = Literal["completed", "waiting", "failed", "skipped"]
V2ProviderTaskStatus = Literal[
    "submitted", "running", "waiting", "completed", "failed", "cancelled"
]
WorkflowV2ExecutionStatus = Literal[
    "queued",
    "running",
    "waiting",
    "completed",
    "partial_failed",
    "failed",
    "cancelled",
]
WorkflowV2Specialist = Literal[
    "product_designer",
    "character_designer",
    "scene_designer",
    "storyboard_artist",
    "video_director",
    "sound_director",
    "composition_tool",
    "quick_image_generator",
    "quick_video_generator",
    "quick_audio_generator",
]
WorkflowAssetRelationTypeV2 = Literal[
    "selected_for_slot",
    "working_version_for_slot",
    "history_version_for_slot",
    "reference_for_item",
    "reference_for_slot",
    "implicit_reference_for_slot",
    "available_for_composition",
    "selected_for_timeline",
    "derived_from",
    "absorbed_into",
]
WorkflowAssetStateV2 = Literal[
    "selected",
    "working",
    "history",
    "reference",
    "implicit_reference",
]
WorkflowAssetSemanticTypeV2 = Literal[
    "product_reference",
    "style_reference",
    "generic_reference",
    "character_reference",
    "scene_reference",
    "audio_reference",
    "product_main",
    "product_multi_view",
    "character_main",
    "character_three_view",
    "scene_main",
    "scene_multi_view",
    "shot_cell_image",
    "shot_video_segment",
    "bgm",
    "final_video",
    "free_image",
    "free_video",
    "free_audio",
]
WorkflowAssetOwnerTypeV2 = Literal[
    "product",
    "character",
    "scene",
    "storyboard",
    "bgm",
    "final_composition",
    "free",
]
WorkflowReferenceRoleV2 = Literal[
    "style",
    "identity",
    "character",
    "product",
    "scene",
    "composition",
    "motion",
    "audio",
]
WorkflowAssetAbsorbModeV2 = Literal["reference", "selected"]
V2ReferenceBundleGenerationMode = Literal[
    "slot_generation",
    "global_run",
    "chat_revise_and_generate",
    "free_generation",
    "storyboard_cell_generation",
    "storyboard_video_generation",
    "bgm_generation",
    "final_composition",
]


class WorkflowSlotV2(BaseModel):
    slot_id: str
    node_id: str
    item_id: str
    slot_type: str
    media_type: WorkflowMediaTypeV2
    required: bool = True
    status: WorkflowSlotStatusV2 = "empty"
    slot_prompt: str | None = None
    system_suggested_prompt: str | None = None
    user_prompt: str | None = None
    negative_prompt: str | None = None
    dialogue_prompt: str | None = None
    audio_description_prompt: str | None = None
    voice_style_prompt: str | None = None
    negative_constraints: str | None = None
    prompt_source: str = "system"
    manual_prompt_dirty: bool = False
    media_prompt_asset_ids: list[str] = Field(default_factory=list)
    implicit_reference_ids: list[str] = Field(default_factory=list)
    explicit_reference_ids: list[str] = Field(default_factory=list)
    dependency_slot_ids: list[str] = Field(default_factory=list)
    provider: str | None = None
    provider_params: dict[str, Any] = Field(default_factory=dict)
    selected_asset_id: str | None = None
    selected_version_id: str | None = None
    current_working_asset_id: str | None = None
    current_working_version_id: str | None = None
    history_version_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_prompt_layers(self) -> "WorkflowSlotV2":
        if self.system_suggested_prompt is not None or self.user_prompt is not None:
            return self
        if self.manual_prompt_dirty or self.prompt_source == "user":
            self.user_prompt = self.slot_prompt
        else:
            self.system_suggested_prompt = self.slot_prompt
        return self


class WorkflowItemV2(BaseModel):
    item_id: str
    node_id: str
    item_type: Literal[
        "product",
        "character",
        "scene",
        "bgm",
        "shot",
        "free",
        "final_composition",
        "script",
    ]
    display_name: str
    description: str = ""
    item_prompt: str | None = None
    system_suggested_prompt: str | None = None
    user_prompt: str | None = None
    prompt_source: str = "system"
    manual_prompt_dirty: bool = False
    status: WorkflowSlotStatusV2 | WorkflowNodeStatusV2 = "empty"
    lifecycle_state: Literal["active", "archived"] = "active"
    shot_id: str | None = None
    shot_index: int | None = None
    aspect_ratio: str | None = None
    duration_seconds: int | None = None
    summary_prompt: str | None = None
    cell_prompts: list[dict[str, Any]] = Field(default_factory=list)
    shot_summary_prompt: str | None = None
    detail_prompts: dict[str, Any] = Field(default_factory=dict)
    reference_item_ids: list[str] = Field(default_factory=list)
    primary_scene_item_id: str | None = None
    reference_source: Literal["llm_structured", "repaired", "deterministic_fallback"] | None = None
    timeline_plan: dict[str, Any] = Field(default_factory=dict)
    timeline_clips: list[dict[str, Any]] = Field(default_factory=list)
    slots: list[WorkflowSlotV2] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_prompt_layers(self) -> "WorkflowItemV2":
        if self.item_type != "shot" and self.primary_scene_item_id is not None:
            raise ValueError("primary_scene_item_id is only valid for shot items")
        if self.system_suggested_prompt is not None or self.user_prompt is not None:
            return self
        if self.manual_prompt_dirty or self.prompt_source == "user":
            self.user_prompt = self.item_prompt
        else:
            self.system_suggested_prompt = self.item_prompt
        return self


class WorkflowNodeV2(BaseModel):
    node_id: str
    node_type: str
    title: str
    status: WorkflowNodeStatusV2
    position: dict[str, float] = Field(default_factory=dict)
    items: list[WorkflowItemV2] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdgeV2(BaseModel):
    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_kind: Literal["display_flow"] = "display_flow"
    label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowAssetVersionV2(BaseModel):
    asset_id: str
    version_id: str
    media_type: WorkflowMediaTypeV2
    source_type: WorkflowAssetSourceTypeV2
    file_path: str
    public_url: str | None = None
    thumbnail_path: str | None = None
    proxy_path: str | None = None
    rendition_paths: list[str] = Field(default_factory=list)
    workflow_id: str | None = None
    node_id: str | None = None
    item_id: str | None = None
    slot_id: str | None = None
    semantic_type: str | None = None
    prompt_snapshot: dict[str, Any] = Field(default_factory=dict)
    provider_payload_snapshot: dict[str, Any] = Field(default_factory=dict)
    reference_asset_ids: list[str] = Field(default_factory=list)
    library_entity_id: str | None = None
    created_at: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowAssetRelationV2(BaseModel):
    relation_id: str
    relation_type: WorkflowAssetRelationTypeV2
    source_asset_id: str
    target_workflow_id: str | None = None
    target_node_id: str | None = None
    target_item_id: str | None = None
    target_slot_id: str | None = None
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowRuntimeV2(BaseModel):
    workflow_id: str
    running_node_ids: list[str] = Field(default_factory=list)
    running_item_ids: list[str] = Field(default_factory=list)
    running_slot_ids: list[str] = Field(default_factory=list)
    waiting_slot_ids: list[str] = Field(default_factory=list)
    failed_slot_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowV2(BaseModel):
    workflow_schema_version: Literal[2] = 2
    workflow_id: str
    name: str
    description: str = ""
    prompt: str
    duration_seconds: int = 30
    aspect_ratio: str = "16:9"
    output_resolution: WorkflowOutputResolutionV2 = "720p"
    audio_mode: Literal["none", "bgm_only", "full"] = "bgm_only"
    nodes: list[WorkflowNodeV2] = Field(default_factory=list)
    edges: list[WorkflowEdgeV2] = Field(default_factory=list)
    runtime: WorkflowRuntimeV2 | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class WorkflowV2ShotPrimarySceneUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_item_id: str = Field(min_length=1)


class WorkflowV2ShotPrimarySceneUpdateResponse(BaseModel):
    workflow: WorkflowV2
    shot_id: str
    previous_primary_scene_item_id: str | None = None
    primary_scene_item_id: str
    reference_item_ids: list[str] = Field(default_factory=list)
    affected_slot_ids: list[str] = Field(default_factory=list)
    selected_asset_versions_changed: bool = False
    provider_execution_started: bool = False
    events_cursor: int = 0


class WorkflowV2PlanFromPromptRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4_000)
    product_name: str | None = Field(default=None, max_length=120)
    visual_style: str | None = Field(default=None, max_length=500)
    duration_seconds: int = Field(default=30, ge=1, le=300)
    requested_shot_count: int | None = None
    aspect_ratio: str = "16:9"
    output_resolution: WorkflowOutputResolutionV2 = "720p"
    audio_mode: Literal["none", "bgm_only", "full"] = "bgm_only"
    selected_assets: list[WorkflowAssetReference] = Field(default_factory=list)
    asset_references: list[AssetReference] = Field(default_factory=list)
    input_asset_locators: list[str] = Field(default_factory=list)
    library_entity_ids: list[str] = Field(default_factory=list)
    reference_mode: Literal["best_effort", "strict"] = "strict"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("prompt", "product_name", "visual_style", mode="after")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class WorkflowV2PlanningClarificationResponse(BaseModel):
    status: Literal["needs_clarification"] = "needs_clarification"
    error_code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    suggested_actions: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowV2NormalizedPlanningRequestView(BaseModel):
    prompt: str
    product_name: str | None = None
    visual_style: str | None = None
    duration_seconds: int
    requested_shot_count: int | None = None
    aspect_ratio: str
    output_resolution: WorkflowOutputResolutionV2 = "720p"
    audio_mode: Literal["none", "bgm_only", "full"]
    reference_mode: Literal["best_effort", "strict"] = "strict"
    input_asset_locators: list[str] = Field(default_factory=list)
    library_entity_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    v2_planning_seed: V2FrontDeskPlanningSeed | None = None


class WorkflowV2PlanFromChatResponse(BaseModel):
    front_desk: FrontDeskChatResponse
    workflow: WorkflowV2 | None = None
    normalized_v2_request: WorkflowV2NormalizedPlanningRequestView | None = None
    status: str | None = None
    error_code: str | None = None
    message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    suggested_actions: list[dict[str, Any]] = Field(default_factory=list)


class V2ProviderCallSummary(BaseModel):
    node_id: str | None = None
    item_id: str | None = None
    slot_id: str | None = None
    slot_type: str | None = None
    status: str | None = None
    provider: str | None = None
    provider_model: str | None = None
    agent_route: dict[str, Any] = Field(default_factory=dict)
    materializer_mode: str | None = None
    asset_id: str | None = None
    version_id: str | None = None
    provider_task_id: str | None = None
    remote_task_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class WorkflowV2RunResponse(BaseModel):
    workflow: WorkflowV2
    workflow_id: str | None = None
    execution_id: str | None = None
    status: str | None = None
    executed_slot_ids: list[str] = Field(default_factory=list)
    provider_calls: list[dict[str, Any]] = Field(default_factory=list)
    provider_call_summaries: list[V2ProviderCallSummary] = Field(default_factory=list)
    waiting_slot_ids: list[str] = Field(default_factory=list)
    failed_slot_ids: list[str] = Field(default_factory=list)
    blocked_slot_ids: list[str] = Field(default_factory=list)
    created_item_ids: list[str] = Field(default_factory=list)
    created_slot_ids: list[str] = Field(default_factory=list)


class WorkflowV2RunRequest(BaseModel):
    mode: Literal[
        "fill_missing_required_slots",
        "regenerate_missing_stale",
        "force_rerun_all",
    ] = "fill_missing_required_slots"
    source_action: str = "global_run"


class WorkflowV2RunStartResponse(BaseModel):
    workflow_id: str
    execution_id: str
    status: WorkflowV2ExecutionStatus
    active: bool = True
    runtime: WorkflowV2RuntimeSnapshot | dict[str, Any] = Field(default_factory=dict)
    events_cursor: int = 0
    message: str | None = None


class V2SlotVersionsResponse(BaseModel):
    workflow_id: str
    slot_id: str
    selected_asset_id: str | None = None
    working_asset_id: str | None = None
    current_working_version_id: str | None = None
    versions: list[WorkflowAssetVersionV2] = Field(default_factory=list)
    relations: list[WorkflowAssetRelationV2] = Field(default_factory=list)


class WorkflowAssetViewV2(BaseModel):
    asset_id: str
    version_id: str
    workflow_id: str
    node_id: str | None = None
    item_id: str | None = None
    slot_id: str | None = None
    media_type: WorkflowMediaTypeV2
    semantic_type: WorkflowAssetSemanticTypeV2
    source_type: WorkflowAssetSourceTypeV2
    state: WorkflowAssetStateV2
    locator: str
    owner_type: WorkflowAssetOwnerTypeV2 | None = None
    owner_node_id: str | None = None
    owner_item_id: str | None = None
    owner_slot_id: str | None = None
    owner_display_name: str | None = None
    display_name: str
    public_url: str | None = None
    thumbnail_url: str | None = None
    created_at: str | None = None
    prompt_summary: str | None = None
    prompt_summary_source: Literal["user", "system", "agent", "provider"] = "system"
    user_summary_prompt: str | None = None
    provider_prompt: str | None = None
    provider: str | None = None
    quality_status: str = "unknown"
    library_entity_id: str | None = None
    relation_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowAssetListResponseV2(BaseModel):
    workflow_id: str
    assets: list[WorkflowAssetViewV2] = Field(default_factory=list)


class WorkflowAssetVersionViewV2(BaseModel):
    asset_id: str
    version_id: str
    state: WorkflowAssetStateV2
    media_type: WorkflowMediaTypeV2
    semantic_type: WorkflowAssetSemanticTypeV2
    locator: str
    owner_type: WorkflowAssetOwnerTypeV2 | None = None
    owner_node_id: str | None = None
    owner_item_id: str | None = None
    owner_slot_id: str | None = None
    owner_display_name: str | None = None
    display_name: str
    public_url: str | None = None
    thumbnail_url: str | None = None
    created_at: str | None = None
    prompt_summary: str | None = None
    prompt_summary_source: Literal["user", "system", "agent", "provider"] = "system"
    user_summary_prompt: str | None = None
    provider_prompt: str | None = None
    provider: str | None = None
    quality_status: str = "unknown"
    quality_issues: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowAssetVersionsResponseV2(BaseModel):
    workflow_id: str
    asset_id: str
    selected_version_id: str | None = None
    working_version_id: str | None = None
    versions: list[WorkflowAssetVersionViewV2] = Field(default_factory=list)


class SelectSlotVersionRequestV2(BaseModel):
    asset_id: str
    version_id: str


class SelectSlotVersionResponseV2(BaseModel):
    workflow_id: str
    slot_id: str
    selected_asset_id: str
    selected_version_id: str
    state: Literal["selected"] = "selected"
    events: list[str] = Field(default_factory=list)
    outdated_hint_ids: list[str] = Field(default_factory=list)
    compatibility_only: bool = False
    canonical_endpoint: str | None = None


class AddSlotReferenceRequestV2(BaseModel):
    asset_id: str
    version_id: str
    reference_role: WorkflowReferenceRoleV2


class AddSlotReferenceResponseV2(BaseModel):
    workflow_id: str
    slot_id: str
    reference_asset_id: str
    reference_version_id: str
    reference_role: WorkflowReferenceRoleV2
    relation_id: str
    state: Literal["reference"] = "reference"
    events: list[str] = Field(default_factory=list)


class AbsorbAssetRequestV2(BaseModel):
    version_id: str
    target_node_id: str
    target_item_id: str | None = None
    target_slot_id: str | None = None
    mode: WorkflowAssetAbsorbModeV2 = "reference"


class AbsorbAssetResponseV2(BaseModel):
    workflow_id: str
    asset_id: str
    version_id: str
    target_slot_id: str | None = None
    mode: WorkflowAssetAbsorbModeV2
    relation_ids: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)


class V2AssetOwner(BaseModel):
    node_id: str | None = None
    item_id: str | None = None
    slot_id: str | None = None
    relation_type: WorkflowAssetRelationTypeV2
    relation_id: str


class V2AssetOwnerResponse(BaseModel):
    workflow_id: str
    asset_id: str
    owner: V2AssetOwner
    relations: list[WorkflowAssetRelationV2] = Field(default_factory=list)


class V2GenerationTarget(BaseModel):
    workflow_id: str
    target_type: Literal["node", "item", "slot", "asset"] = "slot"
    node_id: str | None = None
    node_type: str | None = None
    item_id: str | None = None
    item_type: str | None = None
    slot_id: str | None = None
    slot_type: str | None = None
    asset_id: str | None = None
    media_type: WorkflowMediaTypeV2 | None = None
    is_free_generation: bool = False


class V2AgentRoute(BaseModel):
    specialist: WorkflowV2Specialist
    owner_node_id: str | None = None
    owner_item_id: str | None = None
    owner_slot_id: str | None = None
    generation_mode: str
    materializer_version: str = "v2.0"


class V2MaterializedPrompt(BaseModel):
    summary_prompt: str | None = None
    specialist_prompt: str | None = None
    detail_prompts: dict[str, Any] = Field(default_factory=dict)
    provider_prompt: str | None = None
    negative_prompt: str | None = None
    negative_constraints: str | None = None
    reference_asset_ids: list[str] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    materializer_mode: V2PromptMaterializerMode = "fallback"
    model_id: str | None = None
    selected_skill_ids: list[str] = Field(default_factory=list)
    selected_skill_paths: list[str] = Field(default_factory=list)
    skill_context_warnings: list[dict[str, Any]] = Field(default_factory=list)
    quality_notes: list[str] = Field(default_factory=list)
    materializer_version: str | None = None
    model_env_key: str | None = None
    profile_id: str | None = None
    profile_version: str | None = None
    ownership_scope_id: str | None = None
    provider_payload: dict[str, Any] = Field(default_factory=dict)


class V2GenerationPlan(BaseModel):
    target: V2GenerationTarget
    agent_route: V2AgentRoute
    materialized_prompt: V2MaterializedPrompt
    provider_payload: dict[str, Any] = Field(default_factory=dict)
    reference_asset_ids: list[str] = Field(default_factory=list)
    reference_audit: dict[str, Any] = Field(default_factory=dict)


class V2SpecialistPromptRequest(BaseModel):
    workflow_id: str
    target: dict[str, Any] = Field(default_factory=dict)
    agent_route: dict[str, Any] = Field(default_factory=dict)
    summary_prompt: str | None = None
    current_slot_prompt: str | None = None
    detail_prompts: dict[str, Any] = Field(default_factory=dict)
    reference_asset_summaries: list[dict[str, Any]] = Field(default_factory=list)
    dependency_asset_summaries: list[dict[str, Any]] = Field(default_factory=list)
    director_context_summary: dict[str, Any] = Field(default_factory=dict)
    script_summary: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    skill_context: dict[str, Any] = Field(default_factory=dict)
    provider_capability_summary: dict[str, Any] = Field(default_factory=dict)


class V2SpecialistPromptResult(BaseModel):
    summary_prompt: str | None = None
    specialist_prompt: str | None = None
    detail_prompts: dict[str, Any] = Field(default_factory=dict)
    provider_prompt: str | None = None
    negative_prompt: str | None = None
    negative_constraints: str | None = None
    reference_asset_ids: list[str] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    materializer_mode: V2PromptMaterializerMode
    model_id: str | None = None
    selected_skill_ids: list[str] = Field(default_factory=list)
    selected_skill_paths: list[str] = Field(default_factory=list)
    skill_context_warnings: list[dict[str, Any]] = Field(default_factory=list)
    quality_notes: list[str] = Field(default_factory=list)
    materializer_version: str | None = None
    model_env_key: str | None = None
    profile_id: str | None = None
    profile_version: str | None = None
    ownership_scope_id: str | None = None


class V2ProviderResult(BaseModel):
    status: V2ProviderExecutionStatus
    media_type: WorkflowMediaTypeV2
    asset_bytes: bytes | None = None
    local_file_path: str | None = None
    remote_task_id: str | None = None
    provider: str | None = None
    provider_model: str | None = None
    provider_payload_snapshot: dict[str, Any] = Field(default_factory=dict)
    reference_asset_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class V2ProviderTask(BaseModel):
    task_id: str
    workflow_id: str
    execution_id: str | None = None
    node_id: str
    item_id: str
    slot_id: str
    asset_id: str
    version_id: str
    provider: str | None = None
    provider_model: str | None = None
    remote_task_id: str | None = None
    status: V2ProviderTaskStatus = "submitted"
    submitted_at: str
    updated_at: str
    completed_at: str | None = None
    poll_count: int = 0
    attempt_count: int = 0
    retry_count: int = Field(default=0, ge=0)
    download_attempt_count: int = Field(default=0, ge=0)
    last_polled_at: str | None = None
    next_poll_at: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    provider_payload_snapshot: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class V2ProviderTaskListResponse(BaseModel):
    tasks: list[V2ProviderTask] = Field(default_factory=list)


class V2ProviderTaskPollResponse(BaseModel):
    task: V2ProviderTask
    workflow: WorkflowV2
    provider_result: V2ProviderResult | None = None
    executed_slot_ids: list[str] = Field(default_factory=list)
    provider_calls: list[dict[str, Any]] = Field(default_factory=list)
    provider_call_summaries: list[V2ProviderCallSummary] = Field(default_factory=list)
    waiting_slot_ids: list[str] = Field(default_factory=list)
    failed_slot_ids: list[str] = Field(default_factory=list)
    blocked_slot_ids: list[str] = Field(default_factory=list)
    created_item_ids: list[str] = Field(default_factory=list)
    created_slot_ids: list[str] = Field(default_factory=list)


class V2RunConcurrencyConfig(BaseModel):
    max_parallel_image_jobs: int = 4
    max_parallel_video_jobs: int = 1
    max_parallel_audio_jobs: int = 1
    max_parallel_generation_jobs: int = 5


class V2SlotExecutionJob(BaseModel):
    workflow_id: str
    execution_id: str | None = None
    attempt_id: str | None = None
    input_fingerprint: str | None = None
    node_id: str
    item_id: str
    slot_id: str
    slot_type: str
    media_type: WorkflowMediaTypeV2
    source_action: str = "global_run"
    select_generated: bool = True


class V2SlotExecutionResult(BaseModel):
    job: V2SlotExecutionJob
    status: V2ProviderExecutionStatus
    plan: V2GenerationPlan | None = None
    provider_result: V2ProviderResult
    provider_payload_snapshot: dict[str, Any] = Field(default_factory=dict)
    provider_result_id: str | None = None
    manifest_path: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class V2ProviderTaskPollResult(BaseModel):
    workflow_id: str
    execution_id: str | None = None
    polled_task_ids: list[str] = Field(default_factory=list)
    completed_task_ids: list[str] = Field(default_factory=list)
    waiting_task_ids: list[str] = Field(default_factory=list)
    failed_task_ids: list[str] = Field(default_factory=list)
    executed_slot_ids: list[str] = Field(default_factory=list)
    waiting_slot_ids: list[str] = Field(default_factory=list)
    failed_slot_ids: list[str] = Field(default_factory=list)


class V2ProviderCooldownState(BaseModel):
    media_type: WorkflowMediaTypeV2
    active_until: str | None = None
    reason: str | None = None
    reduced_parallel_jobs: int | None = None


class WorkflowV2ItemGenerateRequest(BaseModel):
    node_id: str | None = None
    mode: Literal["missing_only", "regenerate"] = "missing_only"
    select_generated: bool = True


class WorkflowV2ChatTarget(BaseModel):
    workflow_id: str | None = None
    target_type: Literal["node", "item", "slot", "asset"]
    node_id: str | None = None
    item_id: str | None = None
    slot_id: str | None = None
    asset_id: str | None = None


class WorkflowV2ChatTargetRequest(BaseModel):
    target: WorkflowV2ChatTarget
    instruction: str = Field(min_length=1, max_length=4_000)
    action_mode: Literal["revise_prompt", "revise_and_generate"] = "revise_prompt"
    prompt_scope: Literal["auto", "item", "slot"] = "auto"
    item_prompt: str | None = Field(default=None, max_length=4_000)
    slot_prompt: str | None = Field(default=None, max_length=4_000)
    dialogue_prompt: str | None = Field(default=None, max_length=4_000)
    audio_description_prompt: str | None = Field(default=None, max_length=4_000)
    voice_style_prompt: str | None = Field(default=None, max_length=2_000)
    negative_prompt: str | None = Field(default=None, max_length=2_000)
    negative_constraints: str | None = Field(default=None, max_length=2_000)
    asset_references: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("instruction")
    @classmethod
    def strip_instruction(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("instruction must not be blank")
        return normalized

    @field_validator(
        "item_prompt",
        "slot_prompt",
        "dialogue_prompt",
        "audio_description_prompt",
        "voice_style_prompt",
        "negative_prompt",
        "negative_constraints",
    )
    @classmethod
    def strip_optional_chat_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class WorkflowV2ChatTargetResponse(BaseModel):
    workflow_id: str
    target: WorkflowV2ChatTarget
    specialist: WorkflowV2Specialist | None = None
    action_mode: Literal["revise_prompt", "revise_and_generate"]
    applied: bool = False
    generated: bool = False
    updated_prompt_scope: str | None = None
    affected_slot_ids: list[str] = Field(default_factory=list)
    agent_route_snapshot: dict[str, Any] = Field(default_factory=dict)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    executed_slot_ids: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    version_ids: list[str] = Field(default_factory=list)
    provider_calls: list[dict[str, Any]] = Field(default_factory=list)
    provider_call_summaries: list[V2ProviderCallSummary] = Field(default_factory=list)
    workflow: WorkflowV2 | None = None
    compatibility_only: bool = False
    canonical_endpoint: str | None = None


class WorkflowV2ChatActionTarget(BaseModel):
    target_type: Literal["node", "slot", "asset", "free_node"]
    locator: str | None = None
    node_id: str | None = None
    slot_id: str | None = None
    asset_id: str | None = None
    version_id: str | None = None


class WorkflowV2ChatActionRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    target: WorkflowV2ChatActionTarget
    action_mode: Literal[
        "auto",
        "revise_prompt",
        "revise_and_generate",
        "select_version",
        "discard_working",
    ] = "auto"
    asset_id: str | None = None
    version_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized


class WorkflowV2ResolvedChatActionTarget(BaseModel):
    target_type: Literal["slot"] = "slot"
    node_id: str
    item_id: str | None = None
    slot_id: str
    slot_type: str | None = None


class WorkflowV2WorkingVersionView(BaseModel):
    asset_id: str
    version_id: str
    state: Literal["working"] = "working"


class WorkflowV2ChatActionResponse(BaseModel):
    workflow_id: str
    conversation_id: str
    action_id: str
    target: WorkflowV2ChatActionTarget
    resolved_target: WorkflowV2ResolvedChatActionTarget | None = None
    specialist: WorkflowV2Specialist | None = None
    action_mode: Literal[
        "revise_prompt",
        "revise_and_generate",
        "select_version",
        "discard_working",
    ]
    applied: bool = False
    working_version: WorkflowV2WorkingVersionView | None = None
    events: list[str] = Field(default_factory=list)
    message: str
    workflow: WorkflowV2 | None = None


class V2ReferenceAsset(BaseModel):
    asset_id: str
    version_id: str
    slot_id: str | None = None
    role: str
    semantic_type: WorkflowAssetSemanticTypeV2
    media_type: WorkflowMediaTypeV2
    public_url: str | None = None
    local_path: str | None = None
    display_name: str | None = None
    source_relation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class V2ReferenceBundleTarget(BaseModel):
    node_id: str
    item_id: str | None = None
    slot_id: str
    slot_type: str


class V2ReferenceBundleTextContext(BaseModel):
    user_summary_prompt: str | None = None
    summary_prompt_source: Literal["user", "system", "agent", "provider"] = "system"
    system_context: str | None = None
    provider_prompt: str | None = None
    negative_prompt: str | None = None


class V2ReferenceWarning(BaseModel):
    code: str
    asset_id: str | None = None
    message: str


class V2ReferenceBundle(BaseModel):
    workflow_id: str
    target: V2ReferenceBundleTarget
    text_context: V2ReferenceBundleTextContext
    explicit_reference_assets: list[V2ReferenceAsset] = Field(default_factory=list)
    implicit_reference_assets: list[V2ReferenceAsset] = Field(default_factory=list)
    provider_reference_assets: list[V2ReferenceAsset] = Field(default_factory=list)
    llm_context_assets: list[V2ReferenceAsset] = Field(default_factory=list)
    reference_warnings: list[V2ReferenceWarning] = Field(default_factory=list)
    audit: dict[str, Any] = Field(default_factory=dict)


class V2AssetLocatorResponse(BaseModel):
    locator: str
    target_type: Literal["asset", "slot", "free_node"]
    asset_id: str | None = None
    version_id: str | None = None
    slot_id: str | None = None
    node_id: str | None = None
    display_name: str
    owner_type: WorkflowAssetOwnerTypeV2 | None = None
    owner_node_id: str | None = None
    owner_item_id: str | None = None
    owner_slot_id: str | None = None
    owner_display_name: str | None = None
    resolved_owner: dict[str, Any] | None = None


class V2InputAssetUploadView(BaseModel):
    asset_id: str
    version_id: str
    locator: str
    media_type: WorkflowMediaTypeV2
    semantic_type: str
    source_type: WorkflowAssetSourceTypeV2
    public_url: str | None = None
    display_name: str


class V2InputAssetUploadResponse(BaseModel):
    assets: list[V2InputAssetUploadView] = Field(default_factory=list)


class V2RegisterReferenceSource(BaseModel):
    kind: Literal["existing_v2_asset_version", "data_assets_file"]
    asset_id: str | None = None
    version_id: str | None = None
    file_path: str | None = None
    media_type: WorkflowMediaTypeV2 | None = None
    semantic_type: str | None = None
    display_name: str | None = None
    tags: list[str] = Field(default_factory=list)


class V2RegisterReferenceTarget(BaseModel):
    target_type: Literal["slot"]
    slot_id: str


class V2RegisterReferenceRequest(BaseModel):
    source: V2RegisterReferenceSource
    target: V2RegisterReferenceTarget | None = None
    reference_role: WorkflowReferenceRoleV2 | None = None


class V2RegisterLibraryReferenceRequest(BaseModel):
    library_entity_id: str = Field(min_length=1)
    library_asset_id: str | None = None
    target: V2RegisterReferenceTarget | None = None
    reference_role: WorkflowReferenceRoleV2 | None = None
    semantic_type: str | None = None
    use_as_prompt: bool = True


class V2ReferenceAssetMutationResponse(BaseModel):
    workflow: WorkflowV2
    assets: list[WorkflowAssetViewV2] = Field(default_factory=list)
    relations: list[WorkflowAssetRelationV2] = Field(default_factory=list)
    runtime: WorkflowV2RuntimeSnapshot
    events: list[str] = Field(default_factory=list)


class WorkflowV2ConfirmShotSummaryRequest(BaseModel):
    shot_summary_prompt: str = Field(min_length=1, max_length=2_000)

    @field_validator("shot_summary_prompt")
    @classmethod
    def strip_summary(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("shot_summary_prompt must not be blank")
        return normalized


class WorkflowV2ShotDetailPromptPatchRequest(BaseModel):
    storyboard_content: str | None = Field(default=None, max_length=6_000)
    dialogue: str | None = Field(default=None, max_length=4_000)
    audio_description: str | None = Field(default=None, max_length=4_000)
    voice_style: str | None = Field(default=None, max_length=2_000)
    video_negative_constraints: str | None = Field(default=None, max_length=2_000)
    time_segments: list[dict[str, Any]] | None = None
    desired_duration_seconds: int | None = Field(default=None, ge=1, le=300)
    provider_duration_seconds: int | None = Field(default=None, ge=1, le=300)

    @field_validator(
        "storyboard_content",
        "dialogue",
        "audio_description",
        "voice_style",
        "video_negative_constraints",
    )
    @classmethod
    def strip_optional_detail_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class WorkflowV2ShotDetailPromptRefineRequest(BaseModel):
    overwrite_user_edits: bool = False


class WorkflowV2ItemPromptUpdateRequest(BaseModel):
    item_prompt: str = Field(min_length=1, max_length=4_000)

    @field_validator("item_prompt")
    @classmethod
    def strip_item_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("item_prompt must not be blank")
        return normalized


class WorkflowV2SlotPromptUpdateRequest(BaseModel):
    slot_prompt: str | None = Field(default=None, max_length=4_000)
    negative_prompt: str | None = Field(default=None, max_length=2_000)
    detail_prompt_key: str | None = Field(default=None, max_length=120)
    visual_style_override: str | None = Field(default=None, max_length=500)

    @field_validator(
        "slot_prompt",
        "negative_prompt",
        "detail_prompt_key",
        "visual_style_override",
    )
    @classmethod
    def strip_optional_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class WorkflowV2ReferenceAttachRequest(BaseModel):
    target_type: Literal["item", "slot"]
    target_id: str = Field(min_length=1)
    source_asset_id: str = Field(min_length=1)
    reference_kind: Literal["explicit", "absorbed"] = "explicit"
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowV2ReferenceMutationResponse(BaseModel):
    workflow: WorkflowV2
    relation: WorkflowAssetRelationV2 | None = None
    removed_relation_id: str | None = None


class WorkflowV2Event(BaseModel):
    seq: int
    event_type: str
    workflow_id: str
    execution_id: str | None = None
    node_id: str | None = None
    item_id: str | None = None
    slot_id: str | None = None
    asset_id: str | None = None
    version_id: str | None = None
    created_at: str
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowV2EventListResponse(BaseModel):
    workflow_id: str
    events: list[WorkflowV2Event] = Field(default_factory=list)
    events_cursor: int = 0
    next_after_seq: int = 0


class WorkflowV2RuntimeSnapshot(BaseModel):
    workflow_id: str
    active_execution_id: str | None = None
    execution_status: str = "completed"
    running_slot_ids: list[str] = Field(default_factory=list)
    running_item_ids: list[str] = Field(default_factory=list)
    running_node_ids: list[str] = Field(default_factory=list)
    waiting_node_ids: list[str] = Field(default_factory=list)
    waiting_item_ids: list[str] = Field(default_factory=list)
    waiting_slot_ids: list[str] = Field(default_factory=list)
    completed_node_ids: list[str] = Field(default_factory=list)
    completed_item_ids: list[str] = Field(default_factory=list)
    failed_slot_ids: list[str] = Field(default_factory=list)
    failed_item_ids: list[str] = Field(default_factory=list)
    failed_node_ids: list[str] = Field(default_factory=list)
    completed_slot_ids: list[str] = Field(default_factory=list)
    blocked_slot_ids: list[str] = Field(default_factory=list)
    skipped_slot_ids: list[str] = Field(default_factory=list)
    node_runtime: dict[str, dict[str, Any]] = Field(default_factory=dict)
    item_runtime: dict[str, dict[str, Any]] = Field(default_factory=dict)
    slot_runtime: dict[str, dict[str, Any]] = Field(default_factory=dict)
    events_cursor: int = 0
    updated_at: str | None = None


class WorkflowV2FreeNodeCreateRequest(BaseModel):
    slot_prompt: str = Field(default="Free generation output.", max_length=4_000)
    negative_prompt: str | None = Field(default=None, max_length=2_000)
    provider: str | None = None
    provider_params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("slot_prompt", "negative_prompt")
    @classmethod
    def strip_free_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class WorkflowV2FreeNodeGenerateRequest(BaseModel):
    output_media_type: WorkflowMediaTypeV2 = "image"


class WorkflowV2FreeNodeAbsorbRequest(BaseModel):
    target_node_id: str
    target_item_id: str | None = None
    target_slot_id: str | None = None
    asset_id: str
    absorb_role: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowV2FreeNodeAbsorbResponse(BaseModel):
    workflow: WorkflowV2
    relations: list[WorkflowAssetRelationV2] = Field(default_factory=list)


class WorkflowV2TimelineTransform(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(default=0, ge=-1, le=1)
    y: float = Field(default=0, ge=-1, le=1)
    scale_x: float = Field(default=1, gt=0, le=4)
    scale_y: float = Field(default=1, gt=0, le=4)
    rotation_degrees: float = Field(default=0, ge=-360, le=360)
    opacity: float = Field(default=1, ge=0, le=1)
    fit: Literal["cover", "contain"] = "contain"


class WorkflowV2TimelineAudioControls(BaseModel):
    model_config = ConfigDict(extra="forbid")

    volume: float = Field(default=1, ge=0, le=4)
    muted: bool = False
    fade_in_seconds: float = Field(default=0, ge=0)
    fade_out_seconds: float = Field(default=0, ge=0)


class WorkflowV2TimelineColorControls(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset_id: Literal["none", "warm", "cool", "high_contrast", "muted"] = "none"
    brightness: float = Field(default=0, ge=-1, le=1)
    contrast: float = Field(default=1, ge=0, le=3)
    saturation: float = Field(default=1, ge=0, le=3)
    exposure: float = Field(default=0, ge=-4, le=4)
    temperature: float = Field(default=0, ge=-100, le=100)
    tint: float = Field(default=0, ge=-100, le=100)
    hue: float = Field(default=0, ge=-180, le=180)


class WorkflowV2TimelineSubtitleStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    font_size: int = Field(default=42, ge=12, le=96)
    color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    position: Literal["top_center", "center", "bottom_center"] = "bottom_center"


class WorkflowV2TimelineRenderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_codec: str | None = Field(default=None, min_length=1, max_length=64)
    audio_codec: Literal["aac"] = "aac"
    video_bitrate: str | None = Field(default=None, pattern=r"^[1-9][0-9]*(?:[kKmM])?$")
    audio_bitrate: str | None = Field(default=None, pattern=r"^[1-9][0-9]*k$")


class V2MediaToolchainCapabilities(BaseModel):
    profile_id: Literal["final_composition_editor_v1"] = "final_composition_editor_v1"
    status: Literal["ready", "degraded", "unsupported"]
    ffmpeg_version: str | None = None
    ffprobe_version: str | None = None
    ffmpeg_fingerprint: str
    ffprobe_fingerprint: str
    selected_video_encoder: str | None = None
    audio_encoder: str | None = None
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    missing_requirements: list[str] = Field(default_factory=list)
    degraded_fallbacks: list[str] = Field(default_factory=list)
    error_code: str | None = None


class WorkflowV2TimelineTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: str = Field(min_length=1)
    track_type: Literal["video", "audio", "subtitle", "image"]
    order: int = Field(default=1, ge=1)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowV2TimelineClip(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_id: str = Field(min_length=1)
    track_id: str = Field(min_length=1)
    clip_type: Literal["video", "audio", "subtitle", "image"]
    source_asset_id: str | None = None
    source_version_id: str | None = None
    source_slot_id: str | None = None
    start_time: float = Field(default=0, ge=0)
    duration: float = Field(gt=0)
    trim_in: float = Field(default=0, ge=0)
    trim_out: float | None = Field(default=None, gt=0)
    volume: float = Field(default=1, ge=0)
    muted: bool = False
    enabled: bool = True
    transform: WorkflowV2TimelineTransform = Field(default_factory=WorkflowV2TimelineTransform)
    audio: WorkflowV2TimelineAudioControls = Field(default_factory=WorkflowV2TimelineAudioControls)
    color: WorkflowV2TimelineColorControls = Field(default_factory=WorkflowV2TimelineColorControls)
    text: str | None = None
    subtitle_style: WorkflowV2TimelineSubtitleStyle = Field(
        default_factory=WorkflowV2TimelineSubtitleStyle
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_media_source(self) -> "WorkflowV2TimelineClip":
        if self.clip_type in {"video", "audio", "image"}:
            if not self.source_asset_id:
                raise ValueError("source_asset_id is required for media clips")
            if not self.source_version_id:
                raise ValueError("source_version_id is required for media clips")
        if self.clip_type == "subtitle" and self.enabled and not self.text:
            raise ValueError("text is required for enabled subtitle clips")
        if self.clip_type in {"video", "audio"}:
            if self.trim_out is None:
                self.trim_out = _round_timeline_seconds(self.trim_in + self.duration)
            if abs(self.duration - (self.trim_out - self.trim_in)) > 0.01:
                raise ValueError("duration must match trim_out - trim_in for video and audio clips")
        if self.audio.fade_in_seconds + self.audio.fade_out_seconds > self.duration:
            raise ValueError("audio fades cannot exceed clip duration")
        self.start_time = _round_timeline_seconds(self.start_time)
        self.duration = _round_timeline_seconds(self.duration)
        self.trim_in = _round_timeline_seconds(self.trim_in)
        if self.trim_out is not None:
            self.trim_out = _round_timeline_seconds(self.trim_out)
        if self.volume != 1 and self.audio.volume == 1:
            self.audio = self.audio.model_copy(update={"volume": self.volume})
        elif self.audio.volume != 1 and self.volume == 1:
            self.volume = self.audio.volume
        if self.muted and not self.audio.muted:
            self.audio = self.audio.model_copy(update={"muted": True})
        elif self.audio.muted and not self.muted:
            self.muted = True
        return self


class WorkflowV2Timeline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeline_id: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    duration_seconds: float = Field(default=0, ge=0)
    aspect_ratio: str = "16:9"
    resolution: dict[str, int] = Field(default_factory=lambda: {"width": 1280, "height": 720})
    fps: int = Field(default=24, ge=1, le=120)
    tracks: list[WorkflowV2TimelineTrack] = Field(default_factory=list)
    clips: list[WorkflowV2TimelineClip] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_tracks_and_clips(self) -> "WorkflowV2Timeline":
        track_ids = [track.track_id for track in self.tracks]
        track_orders = [track.order for track in self.tracks]
        if len(track_ids) != len(set(track_ids)):
            raise ValueError("timeline track ids must be unique")
        if len(track_orders) != len(set(track_orders)):
            raise ValueError("timeline track orders must be unique")
        tracks = {track.track_id: track for track in self.tracks}
        clip_ids: set[str] = set()
        for clip in self.clips:
            if clip.clip_id in clip_ids:
                raise ValueError("timeline clip ids must be unique")
            clip_ids.add(clip.clip_id)
            track = tracks.get(clip.track_id)
            if track is None:
                raise ValueError("timeline clip references a missing track")
            if clip.clip_type != track.track_type:
                raise ValueError("timeline clip type must match track type")
        _validate_timeline_track_overlaps(self.clips, tracks)
        computed_duration = _round_timeline_seconds(
            max(
                (
                    clip.start_time + clip.duration
                    for clip in self.clips
                    if clip.enabled and tracks[clip.track_id].enabled
                ),
                default=0,
            )
        )
        if abs(self.duration_seconds - computed_duration) > 0.01:
            raise ValueError("timeline duration_seconds must match enabled clip duration")
        self.duration_seconds = computed_duration
        return self


class WorkflowV2TimelineResponse(BaseModel):
    workflow_id: str
    node_id: Literal["final-composition"] = "final-composition"
    item_id: str
    timeline: WorkflowV2Timeline
    source: Literal["default", "saved"]
    runtime: dict[str, Any] = Field(default_factory=dict)
    available_sources: list["WorkflowV2TimelineSource"] = Field(default_factory=list)
    stale_clip_ids: list[str] = Field(default_factory=list)
    missing_source_clip_ids: list[str] = Field(default_factory=list)


class WorkflowV2TimelineUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    timeline: WorkflowV2Timeline


class WorkflowV2TimelineUpdateResponse(BaseModel):
    workflow_id: str
    timeline: WorkflowV2Timeline
    changed_clip_ids: list[str] = Field(default_factory=list)
    runtime: dict[str, Any] = Field(default_factory=dict)


class WorkflowV2TimelineRenderRequest(BaseModel):
    timeline_id: str = Field(min_length=1)
    timeline_version: int = Field(ge=1)
    render_settings: WorkflowV2TimelineRenderSettings = Field(
        default_factory=WorkflowV2TimelineRenderSettings
    )


class WorkflowV2TimelineRenderResponse(BaseModel):
    workflow_id: str
    render_id: str
    slot_id: str
    asset_id: str
    version_id: str
    status: Literal["completed"]
    public_url: str | None = None
    timeline_id: str
    timeline_version: int
    runtime: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowV2TimelineRenderStartResponse(BaseModel):
    workflow_id: str
    render_id: str
    status: Literal["queued"] = "queued"
    timeline_id: str
    timeline_version: int
    events_cursor: int = Field(ge=0)


class WorkflowV2TimelineRenderStateResponse(BaseModel):
    workflow_id: str
    render_id: str
    slot_id: str
    status: Literal[
        "queued",
        "running",
        "completed",
        "failed",
        "cancellation_requested",
        "cancelled",
    ]
    timeline_id: str
    timeline_version: int
    events_cursor: int = Field(ge=0)
    progress_seconds: float | None = Field(default=None, ge=0)
    total_seconds: float | None = Field(default=None, ge=0)
    progress_percent: float | None = Field(default=None, ge=0, le=100)
    asset_id: str | None = None
    version_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str


class WorkflowV2TimelineClipCreateRequest(BaseModel):
    expected_version: int | None = Field(default=None, ge=1)
    source_asset_id: str
    source_version_id: str | None = None
    clip_type: Literal["video", "audio", "subtitle", "image"]
    start_time: float = 0
    duration: float
    track_index: int = 0
    trim_in: float = 0
    trim_out: float | None = None
    volume: float = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowV2TimelineClipDeleteRequest(BaseModel):
    expected_version: int | None = Field(default=None, ge=1)


class WorkflowV2TimelineSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    version_id: str
    media_type: Literal["video", "audio", "image"]
    display_name: str
    public_url: str | None = None
    duration_seconds: float | None = None
    origin: Literal["selected_slot", "workflow_asset", "asset_library"]
    slot_id: str | None = None


class WorkflowV2TimelineSourceImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    library_entity_id: str = Field(min_length=1)
    library_asset_id: str = Field(min_length=1)
    expected_media_type: Literal["video", "audio", "image"]


class WorkflowV2TimelineSourceImportResponse(BaseModel):
    workflow_id: str
    source: WorkflowV2TimelineSource


class WorkflowV2TimelineClipMutationResponse(BaseModel):
    workflow: WorkflowV2
    clip: dict[str, Any] | None = None
    removed_clip_id: str | None = None


def _round_timeline_seconds(value: float) -> float:
    return round(float(value) + 0.0, 2)


def _validate_timeline_track_overlaps(
    clips: list[WorkflowV2TimelineClip],
    tracks: dict[str, WorkflowV2TimelineTrack],
) -> None:
    for track_id, track in tracks.items():
        if track.track_type == "audio" or not track.enabled:
            continue
        intervals = sorted(
            (
                (clip.start_time, clip.start_time + clip.duration)
                for clip in clips
                if clip.track_id == track_id and clip.enabled
            ),
            key=lambda interval: interval[0],
        )
        for previous, current in zip(intervals, intervals[1:]):
            if current[0] < previous[1] - 0.01:
                raise ValueError("enabled non-audio clips cannot overlap on the same track")
