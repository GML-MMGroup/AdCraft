"""Bounded contracts for Agent operation recovery and Draft fallback."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_canvas_creative_session import (
    DraftReferenceIntentV2,
    SpecialistDraftV2,
)
from app.schemas.agent_canvas_world_setting import WorldSettingMaterializationDraftV2
from app.schemas.agent_operation_contexts import SpecialistContextV2


AgentOperationPolicyClassV2 = Literal[
    "routing",
    "proposal",
    "materialization",
    "long_form",
]
AgentOperationAttemptStageV2 = Literal[
    "initial",
    "transport_retry",
    "structured_repair",
    "fallback",
]
AgentOperationFailureStageV2 = Literal[
    "routing",
    "proposal",
    "materialization",
    "safety",
    "model_capability",
    "provider",
    "asset_publication",
    "revision",
]


class _RecoveryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentOperationPolicyV2(_RecoveryModel):
    policy_id: str = Field(min_length=1, max_length=160)
    agent_name: str = Field(min_length=1, max_length=120)
    operation: str = Field(min_length=1, max_length=120)
    contract_id: str = Field(min_length=1, max_length=160)
    policy_class: AgentOperationPolicyClassV2
    hard_deadline_seconds: int = Field(ge=1, le=900)
    transport_retry_limit: Literal[1] = 1
    structured_repair_limit: Literal[1] = 1
    fallback_class: Literal[
        "none",
        "selected_world_setting",
        "selected_media_draft",
    ] = "none"


class AgentTransportClassificationV2(_RecoveryModel):
    code: str = Field(min_length=1, max_length=120)
    retryable: bool
    retry_after_seconds: float | None = Field(default=None, ge=0, le=900)


class AgentOperationFailureV2(_RecoveryModel):
    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=1_024)
    operation: str = Field(min_length=1, max_length=120)
    specialist_name: str | None = Field(default=None, max_length=120)
    attempt_stage: AgentOperationAttemptStageV2
    failure_stage: AgentOperationFailureStageV2
    elapsed_ms: int = Field(ge=0)
    retryable: bool = False
    validation_paths: tuple[str, ...] = Field(default=(), max_length=32)
    occurred_at: datetime


class DeterministicDraftFallbackRequestV2(_RecoveryModel):
    proposal_kind: Literal[
        "world_setting",
        "script",
        "product",
        "prop",
        "character",
        "scene",
        "storyboard",
        "video",
        "bgm",
    ]
    context: SpecialistContextV2
    selected_option_id: str = Field(min_length=1, max_length=160)
    accepted_references: tuple[DraftReferenceIntentV2, ...] = Field(default=(), max_length=64)
    required_reference_ids: tuple[str, ...] = Field(default=(), max_length=64)
    expected_workflow_revision: int = Field(ge=1)
    current_workflow_revision: int = Field(ge=1)
    expected_session_revision: int = Field(ge=0)
    current_session_revision: int = Field(ge=0)
    safety_approved: bool
    model_capability_valid: bool
    provider_started: bool
    failure: AgentOperationFailureV2
    operation_policy_id: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_selected_option_identity(self) -> "DeterministicDraftFallbackRequestV2":
        if self.context.selected_option_id != self.selected_option_id:
            raise ValueError("Selected option identity is inconsistent.")
        return self


class DeterministicDraftFallbackResultV2(_RecoveryModel):
    materialization_mode: Literal["deterministic_fallback"] = "deterministic_fallback"
    warning_code: Literal["specialist_materialization_fallback"] = (
        "specialist_materialization_fallback"
    )
    operation_policy_id: str = Field(min_length=1, max_length=160)
    draft: SpecialistDraftV2 | None = None
    world_setting: WorldSettingMaterializationDraftV2 | None = None

    @model_validator(mode="after")
    def validate_single_output(self) -> "DeterministicDraftFallbackResultV2":
        if (self.draft is None) == (self.world_setting is None):
            raise ValueError("Fallback must contain exactly one materialization output.")
        return self
