"""Strict contracts for the persisted Agent Canvas production journey."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_canvas_requirements import CharacterAuthoringPhaseV1


JourneyStageStatusV2 = Literal[
    "ready",
    "working",
    "waiting_user",
    "blocked_external",
    "failed",
    "completed",
]
JourneyActionKindV2 = Literal[
    "wait_for_user",
    "invoke_capability",
    "invoke_internal_checkpoint",
    "materialize_selected_option",
    "advance_stage",
    "prepare_editing",
    "complete",
]


class _JourneyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


JourneyStageV2 = Literal[
    "intake",
    "world_view",
    "product",
    "props",
    "character",
    "scene",
    "narrative_direction",
    "style_lock",
    "storyboard_plan",
    "storyboard_grids",
    "videos",
    "bgm",
    "editing",
    "completed",
]
JourneyEvidenceKindV2 = Literal[
    "creative_goal_validated",
    "clarification_completed",
    "world_view_selected",
    "world_view_delegated",
    "world_view_excluded",
    "product_materialized",
    "product_delegated",
    "product_excluded",
    "props_materialized",
    "props_delegated",
    "props_excluded",
    "character_materialized",
    "character_delegated",
    "character_excluded",
    "scene_materialized",
    "scene_delegated",
    "scene_excluded",
    "narrative_direction_accepted",
    "style_lock_accepted",
    "storyboard_plan_accepted",
    "storyboard_plan_excluded",
    "storyboard_grids_prepared",
    "storyboard_grids_excluded",
    "videos_prepared",
    "videos_excluded",
    "bgm_prepared",
    "bgm_delegated",
    "bgm_excluded",
    "editing_prepared",
    "editing_export_completed",
    "editing_excluded",
    "targeted_action_started",
    "targeted_action_finished",
    "stage_failed",
]


class JourneyElementDecisionV2(_JourneyModel):
    decision_id: str = Field(min_length=1, max_length=160)
    element_kind: str = Field(min_length=1, max_length=80)
    occurrence_id: str = Field(min_length=1, max_length=160)
    occurrence_index: int = Field(ge=1, le=32)
    outcome: Literal["include", "exclude", "delegate", "unresolved"]
    source: Literal["user", "delegated", "system"]
    source_revision: int = Field(ge=1)
    requirements: dict[str, JsonValue] = Field(default_factory=dict)


class JourneyActionProjectionV2(_JourneyModel):
    action_id: str = Field(min_length=1, max_length=160)
    action_kind: str = Field(min_length=1, max_length=80)
    stage: JourneyStageV2
    stage_revision: int = Field(ge=1)
    status: Literal["reserved", "working", "waiting_user"]
    turn_id: str | None = Field(default=None, max_length=160)
    occurrence_id: str | None = Field(default=None, max_length=160)
    character_phase: CharacterAuthoringPhaseV1 | None = None

    @model_validator(mode="after")
    def validate_character_phase(self) -> "JourneyActionProjectionV2":
        if self.stage != "character" and self.character_phase is not None:
            raise ValueError("Character phase is only valid for the Character stage.")
        return self


class JourneyTransitionEvidenceV2(_JourneyModel):
    evidence_id: str = Field(min_length=1, max_length=160)
    evidence_kind: JourneyEvidenceKindV2
    source_id: str = Field(min_length=1, max_length=160)
    source_revision: int | None = Field(default=None, ge=1)
    stage: JourneyStageV2
    stage_revision: int = Field(ge=1)
    occurrence_id: str | None = Field(default=None, max_length=160)
    character_phase: CharacterAuthoringPhaseV1 | None = None
    actor: Literal["user", "delegated", "system"] = "system"
    recorded_at: datetime


class JourneyEvidenceV2(_JourneyModel):
    evidence_id: str = Field(min_length=1, max_length=160)
    evidence_kind: JourneyEvidenceKindV2
    source_id: str = Field(min_length=1, max_length=160)
    source_revision: int | None = Field(default=None, ge=1)
    stage: JourneyStageV2 | None = None
    stage_revision: int | None = Field(default=None, ge=1)
    occurrence_id: str | None = Field(default=None, max_length=160)
    character_phase: CharacterAuthoringPhaseV1 | None = None
    action_id: str | None = Field(default=None, max_length=160)
    actor: Literal["user", "delegated", "system"] = "system"

    def as_transition(
        self,
        *,
        stage: JourneyStageV2,
        stage_revision: int,
        recorded_at: datetime | None = None,
    ) -> JourneyTransitionEvidenceV2:
        return JourneyTransitionEvidenceV2(
            evidence_id=self.evidence_id,
            evidence_kind=self.evidence_kind,
            source_id=self.source_id,
            source_revision=self.source_revision,
            stage=stage,
            stage_revision=stage_revision,
            occurrence_id=self.occurrence_id,
            character_phase=self.character_phase,
            actor=self.actor,
            recorded_at=recorded_at or datetime.now(timezone.utc),
        )


class GuidedProductionJourneyV2(_JourneyModel):
    policy_version: Literal["fixed_ad_production_v2"] = "fixed_ad_production_v2"
    stage: JourneyStageV2 = "intake"
    stage_status: JourneyStageStatusV2 = "ready"
    stage_revision: int = Field(default=1, ge=1)
    decisions: tuple[JourneyElementDecisionV2, ...] = Field(default=(), max_length=128)
    active_occurrence_id: str | None = Field(default=None, max_length=160)
    active_action: JourneyActionProjectionV2 | None = None
    suspended_action: JourneyActionProjectionV2 | None = None
    transition_evidence: tuple[JourneyTransitionEvidenceV2, ...] = Field(default=(), max_length=512)

    @model_validator(mode="after")
    def validate_authority(self) -> "GuidedProductionJourneyV2":
        decision_ids = [item.decision_id for item in self.decisions]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("Journey decision IDs must be unique.")
        occurrence_ids = [item.occurrence_id for item in self.decisions]
        if len(occurrence_ids) != len(set(occurrence_ids)):
            raise ValueError("Journey occurrence IDs must be unique.")
        for action in (self.active_action, self.suspended_action):
            if action is not None and (
                action.stage != self.stage or action.stage_revision != self.stage_revision
            ):
                raise ValueError("Journey action must belong to the current stage revision.")
        return self


class JourneyPolicyContextV2(_JourneyModel):
    journey: GuidedProductionJourneyV2
    clarification_required: bool = False


class JourneyPolicyResultV2(_JourneyModel):
    action: JourneyActionKindV2
    expected_stage_revision: int = Field(ge=1)
    next_stage: JourneyStageV2 | None = None
    capability_id: CapabilityIdV1 | None = None
    occurrence_id: str | None = Field(default=None, max_length=160)
    character_phase: CharacterAuthoringPhaseV1 | None = None
    requires_model_call: bool = False

    @model_validator(mode="after")
    def validate_action_shape(self) -> "JourneyPolicyResultV2":
        if self.action == "advance_stage" and self.next_stage is None:
            raise ValueError("Stage advancement requires the next stage.")
        if self.action in {"invoke_capability", "invoke_internal_checkpoint"} and (
            self.capability_id is None
        ):
            raise ValueError("Capability invocation requires a capability ID.")
        if self.character_phase is not None and self.capability_id != "character_design":
            raise ValueError("Character phase requires the Character capability.")
        return self


class CharacterAuthoringCursorV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    occurrence_id: str = Field(min_length=1, max_length=160)
    occurrence_index: int = Field(ge=1, le=32)
    phase: CharacterAuthoringPhaseV1
    ledger_revision_id: str = Field(min_length=1, max_length=160)
    stage_revision: int = Field(ge=1)


DeterministicJourneyActionV2 = JourneyPolicyResultV2
