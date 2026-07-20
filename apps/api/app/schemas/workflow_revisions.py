from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.asset_library import AssetReference
from app.schemas.workflow_nodes import WorkflowRevisionMode

WorkflowRevisionStatus = Literal[
    "queued",
    "running",
    "waiting",
    "completed",
    "failed",
    "cancelled",
]
WorkflowRevisionAcceptanceStatus = Literal[
    "not_required",
    "pending",
    "accepted",
    "rejected",
    "superseded",
]
WorkflowRevisionVisibilityStatus = Literal["visible", "archived"]


class WorkflowRevisionRequest(BaseModel):
    mode: WorkflowRevisionMode
    target_entity_id: str | None = None
    target_asset_id: str | None = None
    semantic_type: str | None = None
    target_field: str | None = None
    instruction: str | None = None
    preserve_other_outputs: bool = True
    asset_references: list[AssetReference] = Field(default_factory=list)
    library_entity_ids: list[str] = Field(default_factory=list)
    reference_mode: Literal["best_effort", "strict"] = "strict"
    provider: str | None = None
    allow_provider_fallback: bool = True
    provider_hints: dict[str, Any] = Field(default_factory=lambda: {"priority": "capability_first"})
    allow_optimizer_fallback: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowRevisionAcceptRequest(BaseModel):
    note: str | None = None
    override_quality_failure: bool = False


class WorkflowRevisionRejectRequest(BaseModel):
    reason: str | None = None


class WorkflowRevisionState(BaseModel):
    workflow_id: str
    node_id: str
    node_type: str
    revision_id: str
    status: WorkflowRevisionStatus
    generation_status: WorkflowRevisionStatus | None = None
    acceptance_status: WorkflowRevisionAcceptanceStatus = "not_required"
    visibility_status: WorkflowRevisionVisibilityStatus = "visible"
    mode: WorkflowRevisionMode
    target_entity_id: str | None = None
    target_asset_id: str | None = None
    semantic_type: str | None = None
    target_field: str | None = None
    instruction: str | None = None
    previous_active_asset_id: str | None = None
    previous_active_asset_ids: list[str] = Field(default_factory=list)
    new_asset_id: str | None = None
    candidate_assets: list[dict[str, Any]] = Field(default_factory=list)
    candidate_output: dict[str, Any] = Field(default_factory=dict)
    candidate_entity: dict[str, Any] = Field(default_factory=dict)
    quality_summary: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None
    rejection_reason: str | None = None
    started_at: str
    finished_at: str | None = None
    error: str | None = None
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    events_path: str = ""
    trace_path: str = ""
    optimizedRevisionPrompt: str | None = None
    providerRevisionPrompt: str | None = None
    revisionRequirements: dict[str, Any] = Field(default_factory=dict)
    affected_downstream_nodes: list[str] = Field(default_factory=list)
    node: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowRevisionListResponse(BaseModel):
    workflow_id: str
    node_id: str
    revisions: list[WorkflowRevisionState] = Field(default_factory=list)


class WorkflowAssetHistoryResponse(BaseModel):
    workflow_id: str
    node_id: str
    entity_id: str
    semantic_type: str
    active_asset_id: str | None = None
    assets: list[dict[str, Any]] = Field(default_factory=list)
    revisions: list[WorkflowRevisionState] = Field(default_factory=list)
