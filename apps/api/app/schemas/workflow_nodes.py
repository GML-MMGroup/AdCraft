from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.asset_library import AssetReference
from app.schemas.workflow_executions import WorkflowExecutionState

NodeRunMode = Literal["mock", "real"]
WorkflowRunMode = Literal[
    "run_from_frontier",
    "force_rerun_all",
    "single_node",
    "single_entity",
]
WorkflowRevisionMode = Literal[
    "regenerate_entity",
    "regenerate_asset",
    "select_existing_asset",
]


class WorkflowNodeRevisionRequest(BaseModel):
    mode: WorkflowRevisionMode
    target_entity_id: str | None = None
    target_asset_id: str | None = None
    semantic_type: str | None = None
    target_field: str | None = None
    instruction: str | None = None
    preserve_other_outputs: bool = True


class WorkflowNodeCatalogItem(BaseModel):
    node_type: str
    display_name: str
    category: str
    description: str
    required_inputs: list[str] = Field(default_factory=list)
    optional_inputs: list[str] = Field(default_factory=list)
    input_asset_roles: list[str] = Field(default_factory=list)
    output_asset_roles: list[str] = Field(default_factory=list)
    supports_override_prompt: bool = False
    supports_mock: bool = True
    supports_real: bool = True
    can_run_standalone: bool = True
    downstream_nodes: list[str] = Field(default_factory=list)


class WorkflowNodeCatalogResponse(BaseModel):
    nodes: list[WorkflowNodeCatalogItem]


class WorkflowNodeRunRequest(BaseModel):
    workflow_id: str | None = None
    node_id: str | None = None
    node_type: str | None = None
    input_context: dict[str, Any] = Field(default_factory=dict)
    input_assets: list[dict[str, Any]] = Field(default_factory=list)
    override_prompt: str | None = None
    mode: NodeRunMode | None = None
    media_mode: NodeRunMode | None = None
    save_outputs: bool = True
    run_downstream: bool = False
    force_rerun: bool = False
    auto_resolve: bool = False
    optimize_only: bool = False
    revision: WorkflowNodeRevisionRequest | None = None
    asset_references: list[AssetReference] = Field(default_factory=list)
    library_entity_ids: list[str] = Field(default_factory=list)
    reference_mode: Literal["best_effort", "strict"] = "strict"
    provider: str | None = None
    allow_provider_fallback: bool = True
    provider_hints: dict[str, Any] = Field(default_factory=lambda: {"priority": "capability_first"})
    allow_optimizer_fallback: bool = False


class WorkflowNodeRunResponse(BaseModel):
    workflow_id: str
    node_id: str
    node_run_id: str
    node_type: str
    status: Literal["completed", "failed", "skipped", "waiting"]
    output: dict[str, Any] = Field(default_factory=dict)
    input_context: dict[str, Any] = Field(default_factory=dict)
    input_assets: list[dict[str, Any]] = Field(default_factory=list)
    output_assets: list[dict[str, Any]] = Field(default_factory=list)
    trace_path: str | None = None
    metadata_path: str | None = None
    error: str | None = None
    resolved_input_context: dict[str, Any] = Field(default_factory=dict)
    resolved_input_assets: list[dict[str, Any]] = Field(default_factory=list)
    asset_references: list[dict[str, Any]] = Field(default_factory=list)
    prompt_context_assets: list[dict[str, Any]] = Field(default_factory=list)
    provider_reference_assets: list[dict[str, Any]] = Field(default_factory=list)
    display_input_assets: list[dict[str, Any]] = Field(default_factory=list)
    materialized_prompt: str | None = None
    materialized_assets: list[dict[str, Any]] = Field(default_factory=list)
    source_mappings: list[dict[str, Any]] = Field(default_factory=list)
    resolved_prompt_preview: str | None = None
    resolved_prompt_with_assets: str | None = None
    effective_prompt: str | None = None
    missing_inputs: list[dict[str, Any]] = Field(default_factory=list)
    stale_upstream_nodes: list[dict[str, Any]] = Field(default_factory=list)
    locked_upstream_nodes: list[dict[str, Any]] = Field(default_factory=list)
    affected_downstream_nodes: list[str] = Field(default_factory=list)
    stale: bool = False
    has_active_output: bool = True


class ResolvedNodeInputsResponse(BaseModel):
    node_id: str
    node_type: str
    upstream_nodes: list[dict[str, Any]] = Field(default_factory=list)
    resolved_input_context: dict[str, Any] = Field(default_factory=dict)
    resolved_input_assets: list[dict[str, Any]] = Field(default_factory=list)
    asset_references: list[dict[str, Any]] = Field(default_factory=list)
    prompt_context_assets: list[dict[str, Any]] = Field(default_factory=list)
    provider_reference_assets: list[dict[str, Any]] = Field(default_factory=list)
    display_input_assets: list[dict[str, Any]] = Field(default_factory=list)
    materialized_prompt: str | None = None
    materialized_assets: list[dict[str, Any]] = Field(default_factory=list)
    source_mappings: list[dict[str, Any]] = Field(default_factory=list)
    resolved_prompt_preview: str
    resolved_prompt_with_assets: str | None = None
    missing_inputs: list[dict[str, Any]] = Field(default_factory=list)
    stale_upstream_nodes: list[dict[str, Any]] = Field(default_factory=list)
    locked_upstream_nodes: list[dict[str, Any]] = Field(default_factory=list)
    effective_prompt: str | None = None


class WorkflowNodeListResponse(BaseModel):
    workflow_id: str
    nodes: list[WorkflowNodeRunResponse]


class WorkflowRunRequest(BaseModel):
    mode: WorkflowRunMode = "run_from_frontier"
    force_rerun: bool = False
    run_downstream: bool = True
    start_node_id: str | None = None
    only_missing: bool = True
    download_media: bool = True
    compose_when_ready: bool = True
    target_node_id: str | None = None
    target_entity_id: str | None = None
    target_asset_id: str | None = None
    revision: WorkflowNodeRevisionRequest | None = None
    asset_references: list[AssetReference] = Field(default_factory=list)
    library_entity_ids: list[str] = Field(default_factory=list)
    reference_mode: Literal["best_effort", "strict"] = "strict"
    provider: str | None = None
    allow_provider_fallback: bool = True
    provider_hints: dict[str, Any] = Field(default_factory=lambda: {"priority": "capability_first"})


class WorkflowRunResponse(BaseModel):
    workflow_id: str
    execution_id: str
    mode: WorkflowRunMode = "run_from_frontier"
    status: str
    frontier_node_id: str = ""
    selected_node_ids: list[str] = Field(default_factory=list)
    queued_node_ids: list[str] = Field(default_factory=list)
    running_node_ids: list[str] = Field(default_factory=list)
    waiting_node_ids: list[str] = Field(default_factory=list)
    completed_node_ids: list[str] = Field(default_factory=list)
    executed_node_ids: list[str] = Field(default_factory=list)
    skipped_node_ids: list[str] = Field(default_factory=list)
    failed_node_ids: list[str] = Field(default_factory=list)
    failed_node_id: str = ""
    message: str = ""
    execution: WorkflowExecutionState | None = None
    graph: dict[str, Any] = Field(default_factory=dict)
    executed_nodes: list[str] = Field(default_factory=list)
    skipped_nodes: list[str] = Field(default_factory=list)
    stale_nodes: list[str] = Field(default_factory=list)
    failed_nodes: list[dict[str, str]] = Field(default_factory=list)
    media_status: dict[str, Any] = Field(default_factory=dict)
    final_video: dict[str, Any] = Field(default_factory=dict)
    affected_downstream_nodes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def derive_legacy_node_aliases(self) -> "WorkflowRunResponse":
        self.executed_node_ids = _canonical_string_list(self.executed_node_ids, self.executed_nodes)
        self.skipped_node_ids = _canonical_string_list(self.skipped_node_ids, self.skipped_nodes)
        self.waiting_node_ids = _canonical_string_list(self.waiting_node_ids, self.stale_nodes)
        self.executed_nodes = list(self.executed_node_ids)
        self.skipped_nodes = list(self.skipped_node_ids)
        self.stale_nodes = list(self.waiting_node_ids)

        if not self.failed_node_ids and self.failed_nodes:
            self.failed_node_ids = [
                str(node.get("node_id") or "")
                for node in self.failed_nodes
                if str(node.get("node_id") or "")
            ]
        if self.failed_node_ids:
            errors_by_node = {
                str(node.get("node_id") or ""): str(node.get("error") or "")
                for node in self.failed_nodes
                if str(node.get("node_id") or "")
            }
            self.failed_nodes = [
                {"node_id": node_id, "error": errors_by_node.get(node_id, "")}
                for node_id in self.failed_node_ids
            ]
        if not self.failed_node_id and self.failed_node_ids:
            self.failed_node_id = self.failed_node_ids[0]
        return self


def _canonical_string_list(
    canonical: list[str],
    legacy: list[str],
) -> list[str]:
    values = canonical or legacy
    return [str(value) for value in values if str(value)]
