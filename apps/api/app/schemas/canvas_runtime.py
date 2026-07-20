from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.media_tasks import MediaStatusResponse
from app.schemas.workflow_executions import WorkflowExecutionState
from app.schemas.workflow_graph import WorkflowGraph


CanvasNodeRuntimeStatus = Literal[
    "pending",
    "queued",
    "running",
    "waiting",
    "completed",
    "failed",
    "skipped",
    "cancelled",
    "blocked",
]


class CanvasNodeRuntimeState(BaseModel):
    node_id: str
    node_type: str
    status: CanvasNodeRuntimeStatus
    status_source: str
    execution_id: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    error_code: str | None = None
    waiting_reason: str | None = None
    has_active_output: bool = False
    output_status: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanvasRuntimeEvent(BaseModel):
    seq: int
    event_type: str
    workflow_id: str
    execution_id: str | None = None
    node_id: str | None = None
    node_type: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    version: int | None = None
    created_at: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CanvasRuntimeEventsResponse(BaseModel):
    workflow_id: str
    events: list[CanvasRuntimeEvent] = Field(default_factory=list)
    last_event_seq: int = 0


class CanvasRuntimeSnapshotResponse(BaseModel):
    workflow_id: str
    graph: WorkflowGraph
    active_execution: WorkflowExecutionState | None = None
    node_runtime: dict[str, CanvasNodeRuntimeState] = Field(default_factory=dict)
    queued_node_ids: list[str] = Field(default_factory=list)
    running_node_ids: list[str] = Field(default_factory=list)
    waiting_node_ids: list[str] = Field(default_factory=list)
    completed_node_ids: list[str] = Field(default_factory=list)
    failed_node_ids: list[str] = Field(default_factory=list)
    skipped_node_ids: list[str] = Field(default_factory=list)
    media_status: MediaStatusResponse
    last_event_seq: int = 0
