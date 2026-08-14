"""Typed control, progress, and repair contracts for guided production."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.schemas.agent_canvas_production_journey import JourneyStageV1


class _GuidanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _PrivateGuidanceRepairModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _PrivateGuidanceAuthorityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GuidedActionExecutionLeafV1(_PrivateGuidanceAuthorityModel):
    """Bounded causal execution state for one logical guided action."""

    workflow_id: str = Field(min_length=1, max_length=160)
    logical_action_id: str = Field(min_length=1, max_length=160)
    root_turn_id: str = Field(min_length=1, max_length=160)
    leaf_turn_id: str = Field(min_length=1, max_length=160)
    leaf_turn_kind: str = Field(min_length=1, max_length=64)
    leaf_status: Literal["queued", "running", "completed", "failed"]
    continuation_id: str | None = Field(default=None, min_length=1, max_length=160)
    continuation_status: str | None = Field(default=None, min_length=1, max_length=64)
    operation: Literal["next_action", "capability_command"] | None = None
    retry_attempt_no: int = Field(ge=1)
    error_code: str | None = Field(default=None, min_length=1, max_length=160)
    retryable: bool = False


class ContinuationTurnRetrySnapshotV1(_PrivateGuidanceAuthorityModel):
    """Frozen authority required to repeat one typed Agent operation."""

    schema_version: Literal["1"] = "1"
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    workflow_revision: int = Field(ge=1)
    session_revision: int = Field(ge=1)
    journey_stage: JourneyStageV1
    journey_stage_revision: int = Field(ge=1)
    logical_action_id: str = Field(min_length=1, max_length=160)
    root_turn_id: str = Field(min_length=1, max_length=160)
    operation: Literal["next_action", "capability_command"]
    envelope_id: str = Field(min_length=1, max_length=160)
    envelope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_revision_id: str = Field(min_length=1, max_length=160)
    requirement_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    node_revisions: dict[str, int] = Field(default_factory=dict, max_length=256)
    asset_ids: tuple[str, ...] = Field(default=(), max_length=64)
    response_locale: str = Field(min_length=2, max_length=64)
    policy_identity_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    skill_identity_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class GuidanceAdvanceRequestV1(_GuidanceModel):
    expected_workflow_revision: int = Field(ge=1)
    expected_session_revision: int = Field(ge=1)
    expected_journey_stage: JourneyStageV1
    expected_journey_stage_revision: int = Field(ge=1)


class GuidanceAdvanceTargetV1(_GuidanceModel):
    source_kind: Literal["fresh_next_action"] = "fresh_next_action"
    source_id: str = Field(min_length=1, max_length=160)
    journey_stage: JourneyStageV1
    journey_stage_revision: int = Field(ge=1)
    requirement_revision_id: str = Field(min_length=1, max_length=160)
    guidance_session_revision: int = Field(ge=1)


class GuidanceAdvanceRequestSnapshotV1(_PrivateGuidanceAuthorityModel):
    expected_workflow_revision: int = Field(ge=1)
    expected_session_revision: int = Field(ge=1)
    expected_journey_stage: JourneyStageV1
    expected_journey_stage_revision: int = Field(ge=1)


class GuidanceAdvanceAuthorityPlanV1(_PrivateGuidanceAuthorityModel):
    """Read-only plan whose complete authority is rechecked before delivery."""

    workflow_id: str = Field(min_length=1, max_length=160)
    request: GuidanceAdvanceRequestSnapshotV1
    idempotency_key: str = Field(min_length=1, max_length=256)
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    session_id: str = Field(min_length=1, max_length=160)
    session_status: Literal["active", "paused", "completed"]
    journey_active_action_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_revision_id: str = Field(min_length=1, max_length=160)
    requirement_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    conversation_id: str | None = Field(default=None, min_length=1, max_length=160)
    open_proposal_id: str | None = Field(default=None, min_length=1, max_length=160)
    open_decision_bundle_id: str | None = Field(default=None, min_length=1, max_length=160)
    active_continuation_id: str | None = Field(default=None, min_length=1, max_length=160)
    target: GuidanceAdvanceTargetV1
    command_turn_id: str = Field(min_length=1, max_length=160)
    executable_turn_id: str = Field(min_length=1, max_length=160)
    continuation_id: str = Field(min_length=1, max_length=160)
    continuation_idempotency_key: str = Field(min_length=1, max_length=256)
    created_at: datetime


class GuidanceAdvanceCommitReceiptV1(_PrivateGuidanceAuthorityModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    command_turn_id: str = Field(min_length=1, max_length=160)
    executable_turn_id: str = Field(min_length=1, max_length=160)
    continuation_id: str | None = Field(default=None, min_length=1, max_length=160)
    event_cursor: int = Field(ge=1)
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    retry_of_turn_id: str | None = Field(default=None, min_length=1, max_length=160)
    retry_attempt_no: int = Field(ge=1)
    replayed: bool


class GuidanceProgressSnapshotV1(_GuidanceModel):
    activity_token: str = Field(min_length=1, max_length=96)
    semantic_progress_token: str = Field(min_length=1, max_length=96)
    activity_components: dict[str, JsonValue]
    semantic_components: dict[str, JsonValue]


class GuidanceReadyAssetAssertionV1(_GuidanceModel):
    asset_id: str = Field(min_length=1, max_length=160)
    asset_version_id: str = Field(min_length=1, max_length=160)
    local_path: str = Field(min_length=1, max_length=2_048)
    size_bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class GuidanceAuthorityRepairPlanV1(_GuidanceModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    expected_workflow_revision: int = Field(ge=1)
    expected_requirement_revision_id: str = Field(min_length=1, max_length=160)
    expected_session_revision: int = Field(ge=1)
    expected_journey_stage_revision: int = Field(ge=1)
    selected_topic_ids: tuple[str, ...] = Field(default=(), max_length=64)
    ready_assets: tuple[GuidanceReadyAssetAssertionV1, ...] = Field(min_length=1, max_length=6)
    intended_element_decisions: dict[str, Literal["include"]]
    plan_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class GuidanceAuthorityRepairReceiptV1(_GuidanceModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    plan_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    appended_requirement_revision_id: str = Field(min_length=1, max_length=160)
    resulting_session_revision: int = Field(ge=1)
    event_id: str = Field(min_length=1, max_length=160)
    applied_at: datetime
    replayed: bool = False


class GuidanceRequirementLedgerRepairRuntimeAssertionV1(_PrivateGuidanceRepairModel):
    stale_turn_id: str = Field(min_length=1, max_length=160)
    turn_status: Literal["running"]
    turn_operation_stage: str = Field(min_length=1, max_length=160)
    turn_error_code: str = Field(min_length=1, max_length=160)
    turn_error_message: str = Field(min_length=1, max_length=1_024)
    stale_continuation_id: str = Field(min_length=1, max_length=160)
    continuation_status: Literal["retry_wait"]
    continuation_attempt_count: int = Field(ge=0)
    continuation_lease_generation: int = Field(ge=0)
    continuation_error_code: str = Field(min_length=1, max_length=160)
    continuation_error_message: str = Field(min_length=1, max_length=1_024)


class GuidanceRequirementLedgerRepairPlanV1(_PrivateGuidanceRepairModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    expected_workflow_revision: int = Field(ge=1)
    before_requirement_revision_id: str = Field(min_length=1, max_length=160)
    before_requirement_revision_no: int = Field(ge=1)
    before_requirement_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    before_directive_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_session_revision: int = Field(ge=1)
    expected_journey_stage_revision: int = Field(ge=1)
    selected_topic_ids: tuple[str, ...] = Field(default=(), max_length=64)
    obsolete_directive_ids: tuple[str, ...] = Field(default=(), max_length=256)
    duplicate_directive_ids: tuple[str, ...] = Field(default=(), max_length=256)
    retained_directive_ids: tuple[str, ...] = Field(default=(), max_length=256)
    representative_directive_ids: tuple[str, ...] = Field(default=(), max_length=256)
    runtime: GuidanceRequirementLedgerRepairRuntimeAssertionV1
    ready_assets: tuple[GuidanceReadyAssetAssertionV1, ...] = Field(
        min_length=6,
        max_length=6,
    )
    ready_asset_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    after_requirement_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    repair_error_code: Literal["requirement_projection_budget_exceeded"]
    repair_error_message: str = Field(min_length=1, max_length=1_024)
    plan_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class GuidanceRequirementLedgerRepairReceiptV1(_PrivateGuidanceRepairModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    plan_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    before_requirement_revision_id: str = Field(min_length=1, max_length=160)
    before_requirement_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    after_requirement_revision_id: str = Field(min_length=1, max_length=160)
    after_requirement_revision_no: int = Field(ge=1)
    after_requirement_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    removed_directive_ids: tuple[str, ...] = Field(default=(), max_length=256)
    retained_directive_ids: tuple[str, ...] = Field(default=(), max_length=256)
    terminalized_turn_id: str = Field(min_length=1, max_length=160)
    terminalized_continuation_id: str = Field(min_length=1, max_length=160)
    ready_asset_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_id: str = Field(min_length=1, max_length=160)
    applied_at: datetime
    replayed: bool = False
