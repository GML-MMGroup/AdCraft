"""Shared strict error contracts for Agent Canvas public projections."""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field


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
