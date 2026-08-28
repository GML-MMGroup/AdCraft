"""Private authority contracts for guided media result publication."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_canvas_guided_interactions import GuidedInteractionActionV1
from app.schemas.agent_canvas_production_journey import JourneyStageV2
from app.schemas.language import BCP47Tag


class _MediaReviewAuthorityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CanvasExecutionResultLineageV2(_MediaReviewAuthorityModel):
    commit_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    execution_id: str = Field(min_length=1, max_length=160)
    member_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    outcome: Literal["succeeded", "failed", "cancelled"]
    asset_id: str | None = Field(default=None, min_length=1, max_length=160)
    asset_version_id: str | None = Field(default=None, min_length=1, max_length=160)
    committed_at: datetime


class CanvasPostReadyEffectDispositionV1(_MediaReviewAuthorityModel):
    outcome: Literal["applied", "already_applied", "superseded", "deferred"]
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    interaction_id: str | None = Field(default=None, min_length=1, max_length=160)


class GuidedMediaReviewPublicationCommandV1(_MediaReviewAuthorityModel):
    lineage: CanvasExecutionResultLineageV2
    session_id: str = Field(min_length=1, max_length=160)
    plan_document_id: str = Field(min_length=1, max_length=160)
    plan_revision: int = Field(ge=1)
    planned_node_role: Literal["storyboard_grid", "video_segment", "bgm"]
    planned_sequence_id: str | None = Field(default=None, min_length=1, max_length=160)
    planned_node_revision: int = Field(ge=1)
    current_node_revision: int = Field(ge=1)
    asset_id: str = Field(min_length=1, max_length=160)
    asset_version_id: str = Field(min_length=1, max_length=160)
    expected_awaiting_id: str = Field(min_length=1, max_length=160)
    expected_awaiting_node_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    expected_awaiting_kind: Literal["manual_node_run"] = "manual_node_run"
    expected_resume_policy: Literal["node_terminal"] = "node_terminal"
    expected_session_revision: int = Field(ge=1)
    expected_stage: JourneyStageV2
    expected_stage_revision: int = Field(ge=1)
    interaction_id: str = Field(min_length=1, max_length=160)
    checkpoint_id: str = Field(min_length=1, max_length=160)
    review_awaiting_id: str = Field(min_length=1, max_length=160)
    response_locale: BCP47Tag
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=512)
    allowed_actions: tuple[GuidedInteractionActionV1, ...] = Field(
        min_length=1,
        max_length=8,
    )

    @model_validator(mode="after")
    def validate_cross_identity(self) -> "GuidedMediaReviewPublicationCommandV1":
        if self.lineage.outcome != "succeeded":
            raise ValueError("Media review publication requires successful result lineage.")
        if self.lineage.asset_id != self.asset_id or (
            self.lineage.asset_version_id != self.asset_version_id
        ):
            raise ValueError("Publication Asset identity must match result lineage.")
        if self.lineage.node_id not in self.expected_awaiting_node_ids:
            raise ValueError("The result Node must belong to the exact terminal wait.")
        if len(set(self.expected_awaiting_node_ids)) != len(self.expected_awaiting_node_ids):
            raise ValueError("Terminal wait Node identities must be distinct.")
        return self
