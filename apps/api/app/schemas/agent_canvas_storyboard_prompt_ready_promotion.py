"""Internal contracts for truthful Storyboard prompt-ready promotion."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _PromotionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StoryboardPromptPreparationPairV1(_PromotionModel):
    node_id: str = Field(min_length=1, max_length=160)
    operation_id: str = Field(min_length=1, max_length=160)
    expected_node_revision: int = Field(ge=1)


class StoryboardPromptReadyPromotionCommandV1(_PromotionModel):
    schema_version: Literal["1"] = "1"
    workflow_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    materialization_id: str = Field(min_length=1, max_length=160)
    action_turn_id: str = Field(min_length=1, max_length=160)
    expected_workflow_revision: int = Field(ge=1)
    expected_session_revision: int = Field(ge=1)
    expected_stage_revision: int = Field(ge=1)
    preparations: tuple[StoryboardPromptPreparationPairV1, ...] = Field(
        min_length=1,
        max_length=32,
    )
    production_plan_document_id: str = Field(min_length=1, max_length=160)
    production_plan_revision: int = Field(ge=1)
    execution_mode: Literal["manual", "automatic"]

    @model_validator(mode="after")
    def validate_preparations(self) -> "StoryboardPromptReadyPromotionCommandV1":
        identities = tuple((item.node_id, item.operation_id) for item in self.preparations)
        if identities != tuple(sorted(identities)) or len(identities) != len(set(identities)):
            raise ValueError("Storyboard promotion preparations must be sorted and unique.")
        if len({item.node_id for item in self.preparations}) != len(self.preparations):
            raise ValueError("Storyboard promotion Nodes must be unique.")
        return self


class StoryboardPromptReadyPromotionResultV1(_PromotionModel):
    schema_version: Literal["1"] = "1"
    workflow_id: str = Field(min_length=1, max_length=160)
    materialization_id: str = Field(min_length=1, max_length=160)
    checkpoint_id: str = Field(min_length=1, max_length=160)
    workflow_revision: int = Field(ge=1)
    session_revision: int = Field(ge=1)
    stage_revision: int = Field(ge=1)
    awaiting_id: str | None = Field(default=None, max_length=160)
    automatic_run_command_ids: tuple[str, ...] = Field(default=(), max_length=32)
    replayed: bool = False

    @model_validator(mode="after")
    def validate_mode_result(self) -> "StoryboardPromptReadyPromotionResultV1":
        if self.awaiting_id is not None and self.automatic_run_command_ids:
            raise ValueError(
                "Storyboard promotion cannot publish both manual and automatic authority."
            )
        return self
