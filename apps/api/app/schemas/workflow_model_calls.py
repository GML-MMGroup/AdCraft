"""Protected, prospective Agent model call inspection contracts."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkflowModelCallWriteV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"] = "1"
    run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,160}$")
    call_id: str = Field(pattern=r"^mcall-[A-Za-z0-9_-]{1,100}$")
    phase: Literal["request", "outcome"]
    stage: Literal["initial", "transport_retry", "structured_repair", "capability_fallback"]
    recorded_at: datetime
    boundary: Literal["sdk_response", "sdk_stream_chunks", "pi_assistant_events"]
    payload: dict[str, Any]
    # Structured metadata for the skills that shaped this model call.  This is
    # optional so previously persisted call records remain readable.
    skill_context: dict[str, Any] | None = None
    complete: bool = True
    failed: bool = False


class WorkflowModelCallRecordV1(WorkflowModelCallWriteV1):
    workflow_id: str
    operation: str
    redacted_paths: list[str] = Field(default_factory=list)


class WorkflowModelCallReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call_id: str
    phase: Literal["request", "outcome"]
    recorded: bool


class WorkflowModelCallSummaryV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call_id: str
    run_id: str
    operation: str
    stage: str
    started_at: datetime
    status: Literal["incomplete", "completed", "failed"]
    skill_context: dict[str, Any] | None = None


class WorkflowModelCallDetailV1(WorkflowModelCallSummaryV1):
    workflow_id: str
    request: WorkflowModelCallRecordV1
    outcome: WorkflowModelCallRecordV1 | None = None


class WorkflowModelCallListV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: str
    items: list[WorkflowModelCallSummaryV1]
    next_offset: int | None = None
