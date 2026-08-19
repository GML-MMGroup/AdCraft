"""Strict contracts for the persisted Agent Canvas production journey."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.agent_canvas_capability_identity import CapabilityIdV1


JourneyStageV1 = Literal[
    "intake",
    "clarification",
    "world_setting",
    "foundation_design",
    "narrative_direction",
    "style_lock",
    "storyboard_plan",
    "storyboard_grids",
    "video_segments",
    "bgm",
    "editing_ready",
    "completed",
]
JourneyStageStatusV1 = Literal[
    "ready",
    "working",
    "waiting_user",
    "blocked_external",
    "failed",
    "completed",
]
FoundationKindV1 = Literal["product", "prop", "character", "scene"]
FoundationItemStatusV1 = Literal[
    "pending",
    "active",
    "selected",
    "deferred",
    "excluded",
]
JourneyActionKindV1 = Literal[
    "wait_for_user",
    "invoke_capability",
    "materialize_selected_option",
    "advance_stage",
    "prepare_editing",
    "complete",
]
JourneyEvidenceKindV1 = Literal[
    "creative_goal_validated",
    "clarification_completed",
    "world_setting_selected",
    "world_setting_deferred",
    "world_setting_excluded",
    "foundation_item_selected",
    "foundation_item_deferred",
    "foundation_item_excluded",
    "narrative_direction_selected",
    "style_locked",
    "storyboard_plan_accepted",
    "storyboard_grids_prepared",
    "video_segments_prepared",
    "bgm_prepared",
    "bgm_deferred",
    "bgm_excluded",
    "editing_prepared",
    "targeted_action_started",
    "targeted_action_finished",
    "stage_failed",
    "foundation_queue_amended",
]


class _JourneyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class JourneyElementDecisionV1(_JourneyModel):
    element_kind: str = Field(min_length=1, max_length=80)
    presence: Literal["include", "exclude", "unspecified"]
    authority: Literal["user", "agent"]
    requirements: dict[str, JsonValue] = Field(default_factory=dict)
    source: Literal["explicit_user", "accepted_proposal", "delegated_to_agent"]


class FoundationJourneyItemV1(_JourneyModel):
    item_id: str = Field(min_length=1, max_length=160)
    kind: FoundationKindV1
    occurrence_index: int = Field(ge=1, le=32)
    requirement_source: Literal["explicit_user", "questionnaire", "delegated"]
    required: bool
    status: FoundationItemStatusV1 = "pending"
    topic_id: str | None = Field(default=None, max_length=160)
    selected_node_ids: tuple[str, ...] = Field(default=(), max_length=32)


class JourneyActionProjectionV1(_JourneyModel):
    action_id: str = Field(min_length=1, max_length=160)
    action_kind: str = Field(min_length=1, max_length=80)
    stage: JourneyStageV1
    status: Literal["reserved", "working", "waiting_user"]
    turn_id: str | None = Field(default=None, max_length=160)
    foundation_item_id: str | None = Field(default=None, max_length=160)


class JourneyTransitionEvidenceV1(_JourneyModel):
    evidence_id: str = Field(min_length=1, max_length=160)
    evidence_kind: JourneyEvidenceKindV1
    source_id: str = Field(min_length=1, max_length=160)
    source_revision: int | None = Field(default=None, ge=1)
    recorded_at: datetime


class JourneyEvidenceV1(_JourneyModel):
    evidence_id: str = Field(min_length=1, max_length=160)
    evidence_kind: JourneyEvidenceKindV1
    source_id: str = Field(min_length=1, max_length=160)
    source_revision: int | None = Field(default=None, ge=1)
    foundation_item_id: str | None = Field(default=None, max_length=160)
    action_id: str | None = Field(default=None, max_length=160)

    def as_transition(
        self,
        *,
        recorded_at: datetime | None = None,
    ) -> JourneyTransitionEvidenceV1:
        return JourneyTransitionEvidenceV1(
            evidence_id=self.evidence_id,
            evidence_kind=self.evidence_kind,
            source_id=self.source_id,
            source_revision=self.source_revision,
            recorded_at=recorded_at or datetime.now(timezone.utc),
        )


class GuidedProductionJourneyV1(_JourneyModel):
    policy_version: Literal["fixed_ad_production_v1"] = "fixed_ad_production_v1"
    stage: JourneyStageV1 = "intake"
    stage_status: JourneyStageStatusV1 = "ready"
    stage_revision: int = Field(default=1, ge=1)
    foundation_queue: tuple[FoundationJourneyItemV1, ...] = Field(default=(), max_length=64)
    foundation_cursor: int | None = Field(default=None, ge=0)
    active_action: JourneyActionProjectionV1 | None = None
    suspended_action: JourneyActionProjectionV1 | None = None
    transition_evidence: tuple[JourneyTransitionEvidenceV1, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def validate_queue(self) -> "GuidedProductionJourneyV1":
        identifiers = [item.item_id for item in self.foundation_queue]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Foundation journey item IDs must be unique.")
        occurrences = [(item.kind, item.occurrence_index) for item in self.foundation_queue]
        if len(occurrences) != len(set(occurrences)):
            raise ValueError("Foundation journey occurrences must be unique.")
        if self.foundation_cursor is not None and self.foundation_cursor >= len(
            self.foundation_queue
        ):
            raise ValueError("Foundation journey cursor is out of range.")
        return self


class JourneyPolicyContextV1(_JourneyModel):
    journey: GuidedProductionJourneyV1
    element_decisions: tuple[JourneyElementDecisionV1, ...] = Field(default=(), max_length=32)
    completed_evidence_kinds: tuple[JourneyEvidenceKindV1, ...] = Field(default=(), max_length=64)
    clarification_required: bool = False


class JourneyPolicyResultV1(_JourneyModel):
    action: JourneyActionKindV1
    expected_stage_revision: int = Field(ge=1)
    next_stage: JourneyStageV1 | None = None
    capability_id: CapabilityIdV1 | None = None
    foundation_item_id: str | None = Field(default=None, max_length=160)
    requires_model_call: bool = False

    @model_validator(mode="after")
    def validate_action_shape(self) -> "JourneyPolicyResultV1":
        if self.action == "advance_stage" and self.next_stage is None:
            raise ValueError("Stage advancement requires the next stage.")
        if self.action == "invoke_capability" and self.capability_id is None:
            raise ValueError("Capability invocation requires a capability ID.")
        return self


DeterministicJourneyActionV1 = JourneyPolicyResultV1
