"""Typed control, progress, and repair contracts for guided production."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.agent_canvas_production_journey import JourneyStageV1


class _GuidanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GuidanceAdvanceRequestV1(_GuidanceModel):
    expected_workflow_revision: int = Field(ge=1)
    expected_session_revision: int = Field(ge=1)
    expected_journey_stage: JourneyStageV1
    expected_journey_stage_revision: int = Field(ge=1)


class GuidanceAdvanceTargetV1(_GuidanceModel):
    source_kind: Literal["fresh_next_action", "retry_current_turn"]
    source_id: str = Field(min_length=1, max_length=160)
    journey_stage: JourneyStageV1
    journey_stage_revision: int = Field(ge=1)
    retry_turn_id: str | None = Field(default=None, min_length=1, max_length=160)
    requirement_revision_id: str = Field(min_length=1, max_length=160)
    guidance_session_revision: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_retry_shape(self) -> "GuidanceAdvanceTargetV1":
        has_retry = self.retry_turn_id is not None
        if has_retry != (self.source_kind == "retry_current_turn"):
            raise ValueError("Retry target identity does not match the source kind.")
        return self


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
