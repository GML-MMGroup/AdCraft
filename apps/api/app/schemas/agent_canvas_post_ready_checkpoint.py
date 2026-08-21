"""Strict public projection for one execution's post-Ready settlement."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_canvas_errors import CanvasNodeErrorV2
from app.schemas.agent_canvas_runtime import CanvasExecutionStatusV2


PostReadyEffectTypeV2 = Literal[
    "persist_script_document",
    "persist_text_document",
    "advance_storyboard_progression",
]
PostReadyEffectStatusV2 = Literal["queued", "running", "completed", "failed"]
PostReadyCheckpointStatusV2 = Literal["pending", "completed", "failed"]


class _CheckpointModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CanvasPostReadyEffectSummaryV2(_CheckpointModel):
    effect_id: str = Field(min_length=1, max_length=160)
    effect_type: PostReadyEffectTypeV2
    node_id: str = Field(min_length=1, max_length=160)
    status: PostReadyEffectStatusV2
    attempt_no: int = Field(ge=0)
    error: CanvasNodeErrorV2 | None = None
    updated_at: datetime


class CanvasPostReadyEffectCountsV2(_CheckpointModel):
    total: int = Field(ge=0)
    queued: int = Field(ge=0)
    running: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> "CanvasPostReadyEffectCountsV2":
        if self.queued + self.running + self.completed + self.failed != self.total:
            raise ValueError("Post-Ready effect counts must sum to total.")
        return self


class CanvasPostReadyCheckpointV2(_CheckpointModel):
    checkpoint_id: str = Field(min_length=1, max_length=320)
    workflow_id: str = Field(min_length=1, max_length=160)
    execution_id: str = Field(min_length=1, max_length=160)
    execution_status: CanvasExecutionStatusV2
    status: PostReadyCheckpointStatusV2
    counts: CanvasPostReadyEffectCountsV2
    effects: tuple[CanvasPostReadyEffectSummaryV2, ...] = ()
    error: CanvasNodeErrorV2 | None = None
    updated_at: datetime

    @model_validator(mode="after")
    def validate_effect_counts(self) -> "CanvasPostReadyCheckpointV2":
        expected = {
            "queued": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
        }
        for effect in self.effects:
            expected[effect.status] += 1
        if self.counts.total != len(self.effects) or any(
            getattr(self.counts, status) != count for status, count in expected.items()
        ):
            raise ValueError("Post-Ready effect summaries must match aggregate counts.")
        return self
