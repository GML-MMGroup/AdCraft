"""Shared strict error contracts for Agent Canvas public projections."""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator


ActionableFailureClassV1: TypeAlias = Literal[
    "transient",
    "deterministic",
    "stale",
    "conflict",
    "external",
]
ActionableRetryScopeV1: TypeAlias = Literal[
    "none",
    "prompt_preparation",
    "turn",
    "execution",
    "provider_delivery",
]
ActionableUserActionV1: TypeAlias = Literal[
    "none",
    "retry",
    "revise",
    "regenerate",
    "redesign",
]


class ActionableFailureV1(BaseModel):
    """One validated public disposition for an exact failed operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    failure_class: ActionableFailureClassV1
    retry_scope: ActionableRetryScopeV1
    user_action: ActionableUserActionV1
    retryable: bool = False

    @model_validator(mode="before")
    @classmethod
    def derive_compatibility_retryable(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        derived = value.get("user_action") == "retry" and value.get("retry_scope") != "none"
        supplied = value.get("retryable")
        if supplied is not None and supplied != derived:
            raise ValueError("Retryable must be derived from the actionable disposition.")
        return {**value, "retryable": derived}

    @model_validator(mode="after")
    def validate_disposition(self) -> "ActionableFailureV1":
        if self.user_action == "retry":
            if self.retry_scope == "none":
                raise ValueError("Retry requires one exact operation scope.")
            if self.failure_class not in {"transient", "external"}:
                raise ValueError("Only transient or external failures may be retried.")
        elif self.retry_scope != "none":
            raise ValueError("Non-retry actions cannot carry a retry scope.")
        return self


CharacterAuthoringErrorCodeV1: TypeAlias = Literal[
    "character_occurrence_invalid",
    "character_occurrence_order_invalid",
    "character_authoring_phase_invalid",
    "character_materialization_duplicate",
    "character_parent_provenance_invalid",
    "character_authoring_revision_stale",
    "character_prompt_preparation_failed",
]


class CharacterAuthoringErrorDefinitionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: CharacterAuthoringErrorCodeV1
    retryable: bool


CHARACTER_AUTHORING_ERROR_DEFINITIONS = (
    CharacterAuthoringErrorDefinitionV1(code="character_occurrence_invalid", retryable=False),
    CharacterAuthoringErrorDefinitionV1(code="character_occurrence_order_invalid", retryable=False),
    CharacterAuthoringErrorDefinitionV1(code="character_authoring_phase_invalid", retryable=False),
    CharacterAuthoringErrorDefinitionV1(
        code="character_materialization_duplicate", retryable=False
    ),
    CharacterAuthoringErrorDefinitionV1(
        code="character_parent_provenance_invalid", retryable=False
    ),
    CharacterAuthoringErrorDefinitionV1(code="character_authoring_revision_stale", retryable=True),
    CharacterAuthoringErrorDefinitionV1(code="character_prompt_preparation_failed", retryable=True),
)


class CanvasNodeErrorV2(BaseModel):
    """One safe, retry-aware Canvas error projection."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool
    actionable_failure: ActionableFailureV1 | None = None

    @model_validator(mode="after")
    def validate_retryable_projection(self) -> "CanvasNodeErrorV2":
        if (
            self.actionable_failure is not None
            and self.retryable != self.actionable_failure.retryable
        ):
            raise ValueError("Retryable must match the actionable failure disposition.")
        return self
