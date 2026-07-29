"""Strict public and persistence contracts for Agent Canvas execution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_canvas import CanvasNodeErrorV2, CanvasNodeStatusV2


CanvasRunScopeV2 = Literal["all_drafts", "selected_nodes"]
CanvasExecutionStatusV2 = Literal[
    "queued",
    "running",
    "waiting",
    "completed",
    "partial_completed",
    "failed",
    "cancelled",
]
NodeRuntimePhaseV2 = Literal[
    "waiting_for_input",
    "queued",
    "running",
    "waiting_provider",
    "recovering",
    "publishing",
]


class _RuntimeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CanvasRunRequestV2(_RuntimeModel):
    scope: CanvasRunScopeV2
    node_ids: tuple[str, ...] = ()
    retry_failed: bool = False
    source_action: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_scope(self) -> "CanvasRunRequestV2":
        if self.scope == "selected_nodes" and not self.node_ids:
            raise ValueError("selected_nodes requires at least one node ID")
        if self.scope == "all_drafts" and (self.node_ids or self.retry_failed):
            raise ValueError("all_drafts does not accept node IDs or failed retry")
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("node IDs must be unique")
        return self


class CanvasRunSkippedNodeV2(_RuntimeModel):
    node_id: str
    reason: str


class CanvasRunAcceptedV2(_RuntimeModel):
    workflow_id: str
    execution_id: str
    status: CanvasExecutionStatusV2
    accepted_node_ids: tuple[str, ...] = ()
    joined_node_ids: tuple[str, ...] = ()
    skipped: tuple[CanvasRunSkippedNodeV2, ...] = ()
    waiting_node_ids: tuple[str, ...] = ()
    events_cursor: int = Field(default=0, ge=0)


class CanvasExecutionRecordV2(_RuntimeModel):
    execution_id: str
    workflow_id: str
    status: CanvasExecutionStatusV2
    scope: CanvasRunScopeV2
    cancel_requested: bool = False
    created_at: datetime
    updated_at: datetime


class CanvasExecutionMembershipV2(_RuntimeModel):
    execution_id: str
    workflow_id: str
    node_id: str
    state: Literal[
        "queued",
        "waiting",
        "running",
        "succeeded",
        "failed",
        "cancelled",
    ]
    phase: NodeRuntimePhaseV2 | None = None
    attempt_no: int = Field(default=0, ge=0)
    waiting_for_node_ids: tuple[str, ...] = ()
    provider_task_id: str | None = None
    prompt_metadata: dict[str, object] = Field(default_factory=dict)
    error: CanvasNodeErrorV2 | None = None
    updated_at: datetime


class CanvasRunCancelRequestV2(_RuntimeModel):
    reason: str = Field(default="user_cancelled", min_length=1, max_length=512)


class CanvasRunCancelResponseV2(_RuntimeModel):
    workflow_id: str
    execution_id: str
    status: Literal["cancelled"]
    cancelled_node_ids: tuple[str, ...] = ()
    events_cursor: int = Field(ge=0)


class NodeRuntimeV2(_RuntimeModel):
    node_id: str
    visible_status: CanvasNodeStatusV2
    phase: NodeRuntimePhaseV2 | None = None
    execution_id: str | None = None
    provider_task_id: str | None = None
    waiting_for_node_ids: tuple[str, ...] = ()
    attempt_no: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: CanvasNodeErrorV2 | None = None


class CanvasRuntimeSnapshotV2(_RuntimeModel):
    workflow_id: str
    active_execution_id: str | None = None
    execution_status: CanvasExecutionStatusV2 | None = None
    node_runtime: dict[str, NodeRuntimeV2] = Field(default_factory=dict)
    queued_node_ids: tuple[str, ...] = ()
    working_node_ids: tuple[str, ...] = ()
    waiting_node_ids: tuple[str, ...] = ()
    ready_node_ids: tuple[str, ...] = ()
    failed_node_ids: tuple[str, ...] = ()
    events_cursor: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CanvasProviderModelCapabilityV2(_RuntimeModel):
    provider: str
    model_id: str
    output_type: Literal["image", "video", "audio"]
    accepted_input_types: frozenset[Literal["text", "image", "video", "audio"]]
    max_references: int = Field(ge=0)
    supported_parameters: frozenset[str] = frozenset()
    supported_aspect_ratios: tuple[str, ...] = ()
    duration_range_seconds: tuple[float, float] | None = None
    pixel_bounds: tuple[int, int] | None = None
    available: bool
    unavailable_reason: str | None = None
    supports_native_audio: bool = False


class CanvasProviderModelCapabilityListV2(_RuntimeModel):
    items: tuple[CanvasProviderModelCapabilityV2, ...]


class BindingCapabilityDecisionV2(_RuntimeModel):
    accepted: bool
    target_node_id: str
    selected_model_id: str | None = None
    required_input_types: frozenset[Literal["text", "image", "video", "audio"]]
    compatible_model_ids: tuple[str, ...] = ()
    switch_model_required: bool = False


class NodeExecutionLeaseV2(_RuntimeModel):
    workflow_id: str
    execution_id: str
    node_id: str
    owner_id: str
    generation: int = Field(ge=1)
    state: Literal["claimed", "completed", "released", "expired"]
    heartbeat_at: datetime
    expires_at: datetime


class CanvasProviderTaskV2(_RuntimeModel):
    task_id: str
    workflow_id: str
    execution_id: str
    node_id: str
    provider: str
    remote_task_id: str | None = None
    status: Literal[
        "submitted",
        "waiting",
        "recovering",
        "succeeded",
        "failed",
        "cancelled",
    ]
    lease_generation: int = Field(ge=1)
    next_poll_at: datetime | None = None
    recovery_deadline: datetime
    result_descriptor: dict[str, object] = Field(default_factory=dict)
    error: CanvasNodeErrorV2 | None = None


class CanvasRuntimeEventV2(_RuntimeModel):
    sequence_no: int = Field(ge=1)
    workflow_id: str
    event_type: str
    execution_id: str | None = None
    node_id: str | None = None
    asset_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class CanvasRuntimeEventListV2(_RuntimeModel):
    items: tuple[CanvasRuntimeEventV2, ...]
    next_cursor: int = Field(ge=0)
