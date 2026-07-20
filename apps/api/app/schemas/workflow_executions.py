from typing import Any, Literal

from pydantic import BaseModel, Field


WorkflowExecutionStatus = Literal[
    "queued",
    "running",
    "waiting",
    "completed",
    "partial_failed",
    "failed",
    "cancelled",
]

WorkflowNodeExecutionStatus = Literal[
    "pending",
    "blocked",
    "queued",
    "running",
    "waiting",
    "completed",
    "failed",
    "skipped",
    "cancelled",
]


class WorkflowNodeExecutionState(BaseModel):
    node_id: str
    node_type: str
    status: WorkflowNodeExecutionStatus = "pending"
    selected: bool = False
    started_at: str | None = None
    finished_at: str | None = None
    node_run_id: str | None = None
    output_status: str | None = None
    has_active_output: bool | None = None
    waiting_reason: str | None = None
    skipped_reason: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowExecutionState(BaseModel):
    workflow_id: str
    execution_id: str
    request: dict[str, Any] = Field(default_factory=dict)
    mode: str
    status: WorkflowExecutionStatus = "queued"
    frontier_node_id: str = ""
    selected_node_ids: list[str] = Field(default_factory=list)
    queued_node_ids: list[str] = Field(default_factory=list)
    running_node_ids: list[str] = Field(default_factory=list)
    waiting_node_ids: list[str] = Field(default_factory=list)
    completed_node_ids: list[str] = Field(default_factory=list)
    failed_node_ids: list[str] = Field(default_factory=list)
    skipped_node_ids: list[str] = Field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    nodes: dict[str, WorkflowNodeExecutionState] = Field(default_factory=dict)
    final_result: dict[str, Any] | None = None
    error: str | None = None


class WorkflowExecutionEvent(BaseModel):
    seq: int
    event_type: str
    workflow_id: str
    execution_id: str
    node_id: str | None = None
    node_type: str | None = None
    created_at: str
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowExecutionStartResponse(BaseModel):
    workflow_id: str
    execution_id: str
    status: WorkflowExecutionStatus
    mode: str
    frontier_node_id: str = ""
    selected_node_ids: list[str] = Field(default_factory=list)
    queued_node_ids: list[str] = Field(default_factory=list)
    running_node_ids: list[str] = Field(default_factory=list)
    waiting_node_ids: list[str] = Field(default_factory=list)
    completed_node_ids: list[str] = Field(default_factory=list)
    failed_node_ids: list[str] = Field(default_factory=list)
    skipped_node_ids: list[str] = Field(default_factory=list)
    execution: WorkflowExecutionState


class WorkflowExecutionStateResponse(BaseModel):
    workflow_id: str
    execution_id: str
    status: WorkflowExecutionStatus
    mode: str
    execution: WorkflowExecutionState


class WorkflowExecutionEventsResponse(BaseModel):
    workflow_id: str
    execution_id: str
    events: list[WorkflowExecutionEvent] = Field(default_factory=list)
