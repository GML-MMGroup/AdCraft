"""Contracts for Agent Canvas media execution settings and automatic runs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.agent_canvas import CanvasNodeErrorV2


MediaExecutionModeV2 = Literal["manual", "automatic"]
AutomaticRunCommandStateV2 = Literal["pending", "claimed", "submitted", "failed"]


class _ExecutionSettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentExecutionSettingsV2(_ExecutionSettingsModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    media_execution_mode: MediaExecutionModeV2
    revision: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class AgentExecutionSettingsPatchV2(_ExecutionSettingsModel):
    media_execution_mode: MediaExecutionModeV2

    @field_validator("media_execution_mode", mode="before")
    @classmethod
    def validate_mode(cls, value: object) -> object:
        if value not in {"manual", "automatic"}:
            raise ValueError("agent_execution_mode_invalid")
        return value


class AutomaticRunCommandV2(_ExecutionSettingsModel):
    command_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    source_action_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    command_kind: Literal["agent_auto_generate"] = "agent_auto_generate"
    state: AutomaticRunCommandStateV2
    execution_id: str | None = Field(default=None, min_length=1, max_length=160)
    attempt_count: int = Field(ge=0)
    next_attempt_at: datetime | None = None
    last_error: CanvasNodeErrorV2 | None = None
    created_at: datetime
    updated_at: datetime
