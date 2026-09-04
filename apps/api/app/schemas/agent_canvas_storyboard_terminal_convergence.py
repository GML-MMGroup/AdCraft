"""Strict internal contracts for committed Storyboard terminal convergence."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent_canvas_production_journey import JourneyStageV2


class _StoryboardTerminalConvergenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StoryboardTerminalConvergenceCommandV1(_StoryboardTerminalConvergenceModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    stage: JourneyStageV2
    stage_revision: int = Field(ge=1)
    proposal_id: str = Field(min_length=1, max_length=160)
    interaction_id: str = Field(min_length=1, max_length=160)
    parent_turn_id: str = Field(min_length=1, max_length=160)
    materialization_id: str = Field(min_length=1, max_length=160)
    materialization_receipt_id: str = Field(min_length=1, max_length=160)
    materialization_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_workflow_revision: int = Field(ge=1)
    expected_proposal_revision: int = Field(ge=1)
    expected_interaction_revision: int = Field(ge=1)
    expected_session_revision: int = Field(ge=1)
    terminal_cause: Literal["commit", "callback", "recovery"]


class StoryboardTerminalConvergenceOutcomeV1(_StoryboardTerminalConvergenceModel):
    convergence_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    stage: JourneyStageV2
    stage_revision: int = Field(ge=1)
    proposal_id: str = Field(min_length=1, max_length=160)
    interaction_id: str = Field(min_length=1, max_length=160)
    parent_turn_id: str = Field(min_length=1, max_length=160)
    materialization_id: str = Field(min_length=1, max_length=160)
    materialization_receipt_id: str = Field(min_length=1, max_length=160)
    resulting_workflow_revision: int = Field(ge=1)
    resulting_proposal_revision: int = Field(ge=1)
    resulting_interaction_revision: int = Field(ge=1)
    resulting_session_revision: int = Field(ge=1)
    changed: bool
    replayed: bool = False

