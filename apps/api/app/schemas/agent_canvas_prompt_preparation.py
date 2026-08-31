"""Strict prompt-preparation state shared by Agent Canvas nodes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_canvas_errors import CanvasNodeErrorV2
from app.schemas.agent_canvas_prompt_assertion import (
    PromptAssertionEvidenceV1,
    PromptAssertionSourceSnapshotV1,
    ProviderPromptAssertionEvidenceV1,
    prompt_assertion_evidence_digest,
)
from app.schemas.agent_canvas_role_prompt_preparation import ResolvedNodeParameterV2
from app.schemas.agent_canvas_role_prompt_preparation import RolePromptCompactionDecisionV2
from app.schemas.agent_canvas_requirements import CharacterAuthoringPhaseV1

__all__ = (
    "NodePromptPreparationV1",
    "PromptAssertionEvidenceV1",
    "PromptAssertionSourceSnapshotV1",
    "ProviderPromptAssertionEvidenceV1",
    "prompt_assertion_evidence_digest",
)


class NodePromptPreparationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "queued",
        "working",
        "ready",
        "failed",
        "superseded",
        "not_applicable",
        "waiting_user",
    ]
    operation_id: str | None = Field(default=None, min_length=1, max_length=160)
    presentation_stream_id: str | None = Field(default=None, max_length=160)
    attempt_no: int = Field(ge=0)
    context_snapshot_id: str | None = Field(default=None, min_length=1, max_length=160)
    occurrence_id: str | None = Field(default=None, min_length=1, max_length=160)
    character_phase: CharacterAuthoringPhaseV1 | None = None
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
    compaction_policy_version: str | None = Field(default=None, max_length=32)
    compaction_policy_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[a-f0-9]{64}$",
    )
    compaction_decisions: tuple[RolePromptCompactionDecisionV2, ...] = Field(
        default=(), max_length=64
    )
    assertion_evidence: PromptAssertionEvidenceV1 | None = None
    attempt_stage: str | None = Field(default=None, max_length=80)
    error: CanvasNodeErrorV2 | None = None
    updated_at: datetime

    @model_validator(mode="after")
    def validate_state(self) -> "NodePromptPreparationV1":
        if self.status == "waiting_user":
            if any(
                value is not None
                for value in (
                    self.operation_id,
                    self.presentation_stream_id,
                    self.context_snapshot_id,
                    self.occurrence_id,
                    self.character_phase,
                    self.prompt_digest,
                    self.role_variant,
                    self.recipe_id,
                    self.recipe_version,
                    self.recipe_digest,
                    self.requirement_revision_id,
                    self.requirement_revision_no,
                    self.binding_digest,
                    self.style_projection_digest,
                    self.brief_digest,
                    self.compaction_policy_version,
                    self.compaction_policy_digest,
                    self.assertion_evidence,
                    self.attempt_stage,
                    self.error,
                )
            ):
                raise ValueError("Waiting-user prompt preparation cannot have work identity.")
            if (
                self.attempt_no != 0
                or self.document_revisions
                or self.parameter_origins
                or self.compaction_decisions
            ):
                raise ValueError("Waiting-user prompt preparation cannot have preparation data.")
            return self
        if self.status == "not_applicable":
            if any(
                value is not None
                for value in (
                    self.operation_id,
                    self.presentation_stream_id,
                    self.context_snapshot_id,
                    self.prompt_digest,
                    self.role_variant,
                    self.recipe_id,
                    self.recipe_version,
                    self.recipe_digest,
                    self.requirement_revision_id,
                    self.binding_digest,
                    self.style_projection_digest,
                    self.brief_digest,
                    self.assertion_evidence,
                    self.error,
                )
            ):
                raise ValueError("Not-applicable prompt preparation cannot have model identity.")
            if self.document_revisions or self.parameter_origins:
                raise ValueError("Not-applicable prompt preparation cannot have preparation data.")
            return self
        if self.status == "failed" and self.error is None:
            raise ValueError("Failed prompt preparation requires a safe error.")
        if self.status not in {"failed", "superseded"} and self.error is not None:
            raise ValueError("Only failed or superseded prompt preparation may expose an error.")
        if self.status == "ready" and self.prompt_digest is None:
            raise ValueError("Ready prompt preparation requires a prompt digest.")
        return self

    @classmethod
    def source_only(cls, *, updated_at: datetime) -> "NodePromptPreparationV1":
        """Return the explicit non-generative preparation state."""

        return cls(
            status="not_applicable",
            attempt_no=0,
            updated_at=updated_at,
        )

    @classmethod
    def waiting_user(cls, *, updated_at: datetime) -> "NodePromptPreparationV1":
        """Return the explicit manual-prompt waiting projection."""

        return cls(
            status="waiting_user",
            attempt_no=0,
            updated_at=updated_at,
        )

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
