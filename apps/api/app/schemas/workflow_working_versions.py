from typing import Any, Literal

from pydantic import BaseModel, Field


class WorkflowAddItemInsert(BaseModel):
    mode: Literal["append", "insert_before", "insert_after"] = "append"
    relative_item_id: str | None = None


class WorkflowAddItemRequest(BaseModel):
    item_type: str | None = None
    prompt: str
    insert: WorkflowAddItemInsert = Field(default_factory=WorkflowAddItemInsert)
    run_after_apply: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowUseCurrentVersionRequest(BaseModel):
    force_use_current_version: bool = False
    use_for_composition: bool = False


class WorkflowAssetPromptUpdateRequest(BaseModel):
    prompt: str
    asset_slot_id: str | None = None
    semantic_type: str | None = None
    mark_stale: bool = True


class WorkflowAssetRegenerateRequest(BaseModel):
    prompt: str | None = None
    instruction: str | None = None
    asset_slot_id: str | None = None
    semantic_type: str | None = None
    reference_asset_ids: list[str] = Field(default_factory=list)
    provider_hints: dict[str, Any] = Field(default_factory=dict)


class WorkflowAssetUseCurrentVersionRequest(BaseModel):
    force_use_current_version: bool = False
    quality_override: bool = False
    use_for_composition: bool = False
    asset_slot_id: str | None = None


class WorkflowItemRegenerateRequest(BaseModel):
    prompt: str | None = None
    semantic_type: str | None = None
    preserve_other_outputs: bool = True
    asset_reference_ids: list[str] = Field(default_factory=list)
    library_entity_ids: list[str] = Field(default_factory=list)
    provider_hints: dict[str, Any] = Field(default_factory=dict)
    apply_as_current: bool = False
    regenerate_and_use: bool = False
    auto_accept: bool = False
    run_downstream: bool = False


class WorkflowBatchUseCurrentVersionsRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list)
    scope: Literal["listed_items", "all_needs_apply_in_node", "selected_shots"] = "listed_items"
    use_for_composition: bool = False


class WorkflowShotVideoGenerateRequest(BaseModel):
    prompt: str | None = None
    strict_reference_mode: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowShotVideoBatchRequest(BaseModel):
    shot_ids: list[str] = Field(default_factory=list)


class WorkflowUseShotVideosForCompositionRequest(BaseModel):
    shot_ids: list[str] = Field(default_factory=list)
    scope: Literal["listed_items", "all_needs_apply_in_node", "selected_shots"] = "listed_items"


class WorkflowItemMutationResponse(BaseModel):
    workflow_id: str
    node_id: str
    node_type: str
    item: dict[str, Any]
    affected_downstream_node_ids: list[str] = Field(default_factory=list)
    followup_suggestions: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowAssetMutationResponse(WorkflowItemMutationResponse):
    asset: dict[str, Any]


class WorkflowAssetSlotHistoryResponse(BaseModel):
    workflow_id: str
    node_id: str
    node_type: str
    item_id: str
    asset_id: str
    asset_slot_id: str
    history_versions: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowBatchUseCurrentVersionsResponse(BaseModel):
    workflow_id: str
    node_id: str
    applied_item_ids: list[str] = Field(default_factory=list)
    skipped_items: list[dict[str, Any]] = Field(default_factory=list)
    failed_items: list[dict[str, Any]] = Field(default_factory=list)
    affected_downstream_node_ids: list[str] = Field(default_factory=list)


class WorkflowShotVideoBatchResponse(BaseModel):
    workflow_id: str
    statuses: list[dict[str, Any]] = Field(default_factory=list)
    followup_suggestions: list[dict[str, Any]] = Field(default_factory=list)
