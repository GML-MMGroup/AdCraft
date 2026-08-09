"""Bounded contracts for Agent operation recovery and Draft fallback."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent_canvas_capability_identity import CapabilityIdV1


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
    agent_name: Literal["video_agent"] = "video_agent"
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
    capability_id: CapabilityIdV1 | None = None
    attempt_stage: AgentOperationAttemptStageV2
    failure_stage: AgentOperationFailureStageV2
    elapsed_ms: int = Field(ge=0)
    retryable: bool = False
    validation_paths: tuple[str, ...] = Field(default=(), max_length=32)
    occurred_at: datetime
