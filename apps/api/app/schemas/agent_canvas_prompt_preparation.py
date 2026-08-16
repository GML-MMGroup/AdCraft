"""Strict prompt-preparation state shared by Agent Canvas nodes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_canvas_errors import CanvasNodeErrorV2
from app.schemas.agent_canvas_role_prompt_preparation import ResolvedNodeParameterV2


class NodePromptPreparationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["queued", "working", "ready", "failed", "superseded"]
    operation_id: str | None = Field(default=None, min_length=1, max_length=160)
    attempt_no: int = Field(ge=0)
    context_snapshot_id: str | None = Field(default=None, min_length=1, max_length=160)
    prompt_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    role_variant: str | None = Field(default=None, max_length=80)
    recipe_id: str | None = Field(default=None, max_length=160)
    recipe_version: str | None = Field(default=None, max_length=32)
    recipe_digest: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    requirement_revision_id: str | None = Field(default=None, max_length=160)
    requirement_revision_no: int | None = Field(default=None, ge=1)
    document_revisions: dict[str, int] = Field(default_factory=dict, max_length=16)
    binding_digest: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    style_projection_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[a-f0-9]{64}$",
    )
    brief_digest: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    parameter_origins: tuple[ResolvedNodeParameterV2, ...] = Field(default=(), max_length=32)
    attempt_stage: str | None = Field(default=None, max_length=80)
    error: CanvasNodeErrorV2 | None = None
    updated_at: datetime

    @model_validator(mode="after")
    def validate_state(self) -> "NodePromptPreparationV1":
        if self.status == "failed" and self.error is None:
            raise ValueError("Failed prompt preparation requires a safe error.")
        if self.status not in {"failed", "superseded"} and self.error is not None:
            raise ValueError("Only failed or superseded prompt preparation may expose an error.")
        if self.status == "ready" and self.prompt_digest is None:
            raise ValueError("Ready prompt preparation requires a prompt digest.")
        return self

    @classmethod
    def legacy_ready(cls) -> "NodePromptPreparationV1":
        """Preserve existing nodes during the additive pre-release cutover."""

        return cls(
            status="ready",
            operation_id=None,
            attempt_no=0,
            context_snapshot_id=None,
            prompt_digest="0" * 64,
            error=None,
            updated_at=datetime.now(timezone.utc),
        )
