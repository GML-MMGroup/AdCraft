"""Bounded contracts for Agent operation recovery and Draft fallback."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: str = Field(min_length=1, max_length=160)
    agent_name: Literal["video_agent"] = "video_agent"
    operation: str = Field(min_length=1, max_length=120)
    contract_id: str = Field(min_length=1, max_length=160)
    policy_class: AgentOperationPolicyClassV2
    hard_deadline_seconds: int = Field(ge=1, le=900)
    primary_timeout_seconds: int = Field(ge=1, le=900)
    recovery_timeout_seconds: int = Field(ge=0, le=900)
    persistence_reserve_seconds: int = Field(ge=1, le=900)
    max_output_tokens: int = Field(ge=1, le=65_536)
    reasoning_mode: Literal["low", "deep"]
    enable_thinking: bool
    thinking_budget_tokens: int | None = Field(default=None, ge=1, le=65_536)
    transport_retry_limit: int = Field(default=1, ge=0, le=1)
    structured_repair_limit: int = Field(default=1, ge=0, le=1)
    max_model_submissions: Literal[1, 2] = 2
    recovery_mode: Literal[
        "none",
        "structured_repair_only",
        "transport_retry_or_structured_repair",
    ] = "transport_retry_or_structured_repair"
    fallback_class: Literal[
        "none",
        "selected_world_setting",
        "selected_media_draft",
    ] = "none"

    @model_validator(mode="after")
    def validate_reasoning_request(self) -> "AgentOperationPolicyV2":
        if (
            self.primary_timeout_seconds
            + self.recovery_timeout_seconds
            + self.persistence_reserve_seconds
            != self.hard_deadline_seconds
        ):
            raise ValueError("Operation timeout partitions must equal the hard deadline.")
        if self.reasoning_mode == "low":
            if self.enable_thinking or self.thinking_budget_tokens is not None:
                raise ValueError("Low reasoning cannot include a thinking budget.")
        elif not self.enable_thinking or self.thinking_budget_tokens is None:
            raise ValueError("Deep reasoning requires a bounded thinking budget.")
        if (
            self.thinking_budget_tokens is not None
            and self.thinking_budget_tokens > self.max_output_tokens
        ):
            raise ValueError("Thinking budget exceeds the operation output bound.")
        if self.max_model_submissions == 1:
            if (
                self.recovery_mode != "none"
                or self.recovery_timeout_seconds != 0
                or self.transport_retry_limit != 0
                or self.structured_repair_limit != 0
            ):
                raise ValueError("Single-submission policy cannot configure recovery.")
        elif self.recovery_timeout_seconds == 0 or self.recovery_mode == "none":
            raise ValueError("Two-submission policy requires bounded recovery.")
        elif self.recovery_mode == "structured_repair_only" and (
            self.transport_retry_limit != 0 or self.structured_repair_limit != 1
        ):
            raise ValueError("Structured-repair-only policy cannot retry transport.")
        return self


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
