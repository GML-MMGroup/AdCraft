"""Safe contracts for one exact guided capability supersession correction."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GuidedCapabilityRepairQueueCountsV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    executions: int = Field(ge=0)
    continuations: int = Field(ge=0)
    agent_runs: int = Field(ge=0)
    provider_tasks: int = Field(ge=0)
    guided_media_resumes: int = Field(ge=0)
    automatic_runs: int = Field(ge=0)
    editing_exports: int = Field(ge=0)


class GuidedCapabilityRepairProtectedDigestsV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow: str = Field(pattern=r"^[0-9a-f]{64}$")
    nodes: str = Field(pattern=r"^[0-9a-f]{64}$")
    bindings: str = Field(pattern=r"^[0-9a-f]{64}$")
    assets: str = Field(pattern=r"^[0-9a-f]{64}$")
    session: str = Field(pattern=r"^[0-9a-f]{64}$")
    journey: str = Field(pattern=r"^[0-9a-f]{64}$")


class GuidedCapabilitySupersessionAuditV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: str
    turn_id: str
    conversation_id: str
    activity_id: str
    continuation_id: str
    envelope_id: str
    capability_id: str
    operation: str
    turn_status: str
    activity_status: str
    continuation_status: str
    previous_error_code: str
    expected_session_revision: int = Field(gt=0)
    current_session_revision: int = Field(gt=0)
    current_journey_stage: str
    current_journey_stage_revision: int = Field(gt=0)
    resume_delivery_id: str
    resume_confirmation_id: str
    resume_delivery_status: str
    storyboard_node_id: str
    storyboard_node_status: str
    storyboard_asset_id: str
    storyboard_version_id: str
    storyboard_asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    storyboard_asset_size_bytes: int = Field(gt=0)
    active_queue_counts: GuidedCapabilityRepairQueueCountsV1
    protected_digests: GuidedCapabilityRepairProtectedDigestsV1
    audited_at: str
    audit_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class GuidedCapabilitySupersessionReceiptV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    correction_receipt_id: str
    workflow_id: str
    turn_id: str
    activity_id: str
    continuation_id: str
    previous_status: str
    previous_error_code: str
    replacement_status: str
    evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    transition_key: str
    event_id: str
    corrected_at: str
    replayed: bool
