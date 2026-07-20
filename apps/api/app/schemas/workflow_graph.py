from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, computed_field, model_validator

from app.schemas.workflow_handles import (
    WorkflowNodeHandles,
    get_node_handles,
    normalize_edge_handles,
)

WorkflowStatus = Literal["draft", "ready", "running", "completed", "failed"]
WorkflowGraphNodeStatus = Literal[
    "pending",
    "blocked",
    "waiting",
    "running",
    "completed",
    "failed",
    "skipped",
    "stale",
]
WorkflowNodeCategory = Literal[
    "agent_text",
    "image_generation",
    "video_generation",
    "audio_generation",
    "composition",
    "utility",
]
ValidationLevel = Literal["error", "warning", "info"]


class CanvasPosition(BaseModel):
    x: float = 0.0
    y: float = 0.0


class WorkflowGraphNode(BaseModel):
    id: str
    workflow_id: str
    node_type: str
    category: WorkflowNodeCategory = "utility"
    title: str
    description: str = ""
    position: CanvasPosition = Field(default_factory=CanvasPosition)
    config: dict[str, Any] = Field(default_factory=dict)
    prompt: str | None = None
    override_prompt: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    input_context: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    input_assets: list[dict[str, Any]] = Field(default_factory=list)
    output_assets: list[dict[str, Any]] = Field(default_factory=list)
    status: WorkflowGraphNodeStatus = "pending"
    version: int = 1
    input_hash: str | None = None
    output_hash: str | None = None
    locked: bool = False
    stale: bool = False
    stale_reason: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    can_run_standalone: bool = True
    supports_override_prompt: bool = False
    handles: WorkflowNodeHandles = Field(default_factory=WorkflowNodeHandles)

    @model_validator(mode="after")
    def populate_handles(self) -> "WorkflowGraphNode":
        if not self.handles.inputs and not self.handles.outputs:
            self.handles = get_node_handles(self.node_type)
        return self


class WorkflowGraphEdge(BaseModel):
    id: str
    workflow_id: str
    source_node_id: str
    target_node_id: str
    source_handle: str = Field(
        default="",
        validation_alias=AliasChoices("source_handle", "sourceHandle"),
    )
    target_handle: str = Field(
        default="",
        validation_alias=AliasChoices("target_handle", "targetHandle"),
    )
    label: str | None = None
    mapping: list[dict[str, Any]] = Field(default_factory=list)
    required: bool = True

    @model_validator(mode="after")
    def populate_handles(self) -> "WorkflowGraphEdge":
        self.source_handle, self.target_handle = normalize_edge_handles(
            self.source_node_id,
            self.target_node_id,
            self.source_handle,
            self.target_handle,
            self.label,
        )
        return self

    @computed_field(return_type=str)
    @property
    def source(self) -> str:
        return self.source_node_id

    @computed_field(return_type=str)
    @property
    def target(self) -> str:
        return self.target_node_id

    @computed_field(return_type=str)
    @property
    def sourceHandle(self) -> str:
        return self.source_handle

    @computed_field(return_type=str)
    @property
    def targetHandle(self) -> str:
        return self.target_handle


class WorkflowGraph(BaseModel):
    workflow_id: str
    name: str
    description: str = ""
    version: int = 1
    status: WorkflowStatus = "draft"
    nodes: list[WorkflowGraphNode] = Field(default_factory=list)
    edges: list[WorkflowGraphEdge] = Field(default_factory=list)
    created_at: str
    updated_at: str
    ad_request: dict[str, Any] = Field(default_factory=dict)
    audio_mode: str = "bgm_only"


class WorkflowGraphNodeSaveItem(BaseModel):
    id: str
    workflow_id: str | None = None
    node_type: str | None = None
    category: WorkflowNodeCategory | None = None
    title: str | None = None
    description: str = ""
    position: CanvasPosition = Field(default_factory=CanvasPosition)
    config: dict[str, Any] = Field(default_factory=dict)
    prompt: str | None = None
    override_prompt: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    input_context: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    input_assets: list[dict[str, Any]] = Field(default_factory=list)
    output_assets: list[dict[str, Any]] = Field(default_factory=list)
    status: WorkflowGraphNodeStatus = "pending"
    version: int = 1
    input_hash: str | None = None
    output_hash: str | None = None
    locked: bool = False
    stale: bool = False
    stale_reason: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    can_run_standalone: bool = True
    supports_override_prompt: bool = False
    handles: WorkflowNodeHandles | None = None


class WorkflowGraphEdgeSaveItem(BaseModel):
    id: str | None = None
    workflow_id: str | None = None
    source: str | None = None
    target: str | None = None
    source_node_id: str | None = None
    target_node_id: str | None = None
    source_handle: str | None = Field(
        default=None,
        validation_alias=AliasChoices("source_handle", "sourceHandle"),
    )
    target_handle: str | None = Field(
        default=None,
        validation_alias=AliasChoices("target_handle", "targetHandle"),
    )
    label: str | None = None
    mapping: list[dict[str, Any]] = Field(default_factory=list)
    required: bool = True


class WorkflowGraphSaveRequest(BaseModel):
    workflow_id: str | None = None
    name: str | None = None
    description: str | None = None
    version: int | None = None
    status: WorkflowStatus | None = None
    created_at: str | None = None
    nodes: list[WorkflowGraphNodeSaveItem]
    edges: list[WorkflowGraphEdgeSaveItem]
    ad_request: dict[str, Any] | None = None
    audio_mode: str | None = None


class WorkflowGraphValidationIssue(BaseModel):
    level: ValidationLevel
    message: str
    node_id: str | None = None
    edge_id: str | None = None


class WorkflowGraphValidationResponse(BaseModel):
    workflow_id: str
    valid: bool
    issues: list[WorkflowGraphValidationIssue] = Field(default_factory=list)


class WorkflowGraphEdgeMutationResponse(BaseModel):
    edge: WorkflowGraphEdge
    affected_downstream_nodes: list[str] = Field(default_factory=list)
    workflow_version: int


class WorkflowGraphEdgeDeleteResponse(BaseModel):
    deleted_edge_id: str
    affected_downstream_nodes: list[str] = Field(default_factory=list)
    workflow_version: int


class WorkflowGraphNodeCreateRequest(BaseModel):
    id: str
    node_type: str
    category: WorkflowNodeCategory = "utility"
    title: str
    description: str = ""
    position: CanvasPosition = Field(default_factory=CanvasPosition)
    config: dict[str, Any] = Field(default_factory=dict)
    prompt: str | None = None
    override_prompt: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    input_context: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    input_assets: list[dict[str, Any]] = Field(default_factory=list)
    output_assets: list[dict[str, Any]] = Field(default_factory=list)
    status: WorkflowGraphNodeStatus = "pending"
    can_run_standalone: bool = True
    supports_override_prompt: bool = False
    handles: WorkflowNodeHandles = Field(default_factory=WorkflowNodeHandles)


class WorkflowGraphNodePatchRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    position: CanvasPosition | None = None
    config: dict[str, Any] | None = None
    prompt: str | None = None
    override_prompt: str | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    input_context: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    input_assets: list[dict[str, Any]] | None = None
    output_assets: list[dict[str, Any]] | None = None
    status: WorkflowGraphNodeStatus | None = None
    locked: bool | None = None
    stale: bool | None = None
    stale_reason: str | None = None
    can_run_standalone: bool | None = None
    supports_override_prompt: bool | None = None
    handles: WorkflowNodeHandles | None = None


class WorkflowGraphEdgeCreateRequest(BaseModel):
    id: str | None = None
    source_node_id: str
    target_node_id: str
    source_handle: str | None = Field(
        default=None,
        validation_alias=AliasChoices("source_handle", "sourceHandle"),
    )
    target_handle: str | None = Field(
        default=None,
        validation_alias=AliasChoices("target_handle", "targetHandle"),
    )
    label: str | None = None
    mapping: list[dict[str, Any]] = Field(default_factory=list)
    required: bool = True


class WorkflowGraphEdgePatchRequest(BaseModel):
    source_node_id: str | None = None
    target_node_id: str | None = None
    source_handle: str | None = Field(
        default=None,
        validation_alias=AliasChoices("source_handle", "sourceHandle"),
    )
    target_handle: str | None = Field(
        default=None,
        validation_alias=AliasChoices("target_handle", "targetHandle"),
    )
    label: str | None = None
    mapping: list[dict[str, Any]] | None = None
    required: bool | None = None


class WorkflowNodeVersionsResponse(BaseModel):
    workflow_id: str
    node_id: str
    versions: list[dict[str, Any]] = Field(default_factory=list)


class MarkStaleRequest(BaseModel):
    node_ids: list[str] = Field(default_factory=list)
    include_downstream: bool = True
    reason: str = "manually marked stale"
    changed_entity_ids: list[str] = Field(default_factory=list)
