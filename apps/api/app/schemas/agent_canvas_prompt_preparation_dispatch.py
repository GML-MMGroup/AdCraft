"""Strict internal contract for durable Node prompt-preparation dispatch."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_canvas_requirements import CharacterAuthoringPhaseV1

PromptPreparationDispatchStatusV1 = Literal[
    "queued",
    "leased",
    "completed",
    "failed",
    "superseded",
]


class PromptPreparationDispatchV1(BaseModel):
    """One durable, replayable preparation intent for one Node snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    dispatch_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    node_revision: int = Field(ge=1)
    operation_id: str = Field(min_length=1, max_length=160)
    logical_key: str = Field(min_length=1, max_length=256)
    role_variant: str | None = Field(default=None, max_length=80)
    occurrence_id: str | None = Field(default=None, max_length=160)
    character_phase: CharacterAuthoringPhaseV1 | None = None
    context_snapshot_id: str | None = Field(default=None, max_length=160)
    context_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    context_json: dict[str, object] = Field(default_factory=dict, max_length=128)
    binding_digest: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    recipe_digest: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    style_projection_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[a-f0-9]{64}$",
    )
    brief_digest: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    requirement_revision_id: str | None = Field(default=None, max_length=160)
    requirement_revision_no: int | None = Field(default=None, ge=1)
    document_revisions: dict[str, int] = Field(default_factory=dict, max_length=16)
    source_snapshot: dict[str, object] = Field(default_factory=dict, max_length=64)
    model_policy_revision: int | None = Field(default=None, ge=1)
    status: PromptPreparationDispatchStatusV1
    attempt_no: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=5, ge=1)
    available_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    lease_owner: str | None = Field(default=None, max_length=160)
    lease_generation: int = Field(default=0, ge=0)
    lease_expires_at: datetime | None = None
    last_error_code: str | None = Field(default=None, max_length=160)
    last_error_message: str | None = Field(default=None, max_length=1_024)
    supersession_reason: str | None = Field(default=None, max_length=1_024)
    superseded_by_dispatch_id: str | None = Field(default=None, max_length=160)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    terminal_at: datetime | None = None

    @model_validator(mode="after")
    def validate_identity_and_state(self) -> "PromptPreparationDispatchV1":
        if (self.occurrence_id is None) != (self.character_phase is None):
            raise ValueError("Occurrence and Character phase must be provided together.")
        if self.status == "queued":
            if self.lease_owner is not None or self.lease_expires_at is not None:
                raise ValueError("Queued dispatch cannot have a lease owner.")
            if self.terminal_at is not None:
                raise ValueError("Queued dispatch cannot have a terminal timestamp.")
        elif self.status == "leased":
            if not self.lease_owner or self.lease_expires_at is None:
                raise ValueError("Leased dispatch requires an owner and expiry.")
            if self.terminal_at is not None:
                raise ValueError("Leased dispatch cannot have a terminal timestamp.")
        else:
            if self.lease_owner is not None or self.lease_expires_at is not None:
                raise ValueError("Terminal dispatch cannot retain a lease.")
            if self.terminal_at is None:
                raise ValueError("Terminal dispatch requires a terminal timestamp.")
        if self.status == "failed" and not self.last_error_code:
            raise ValueError("Failed dispatch requires a safe error code.")
        if self.status == "superseded" and not (
            self.supersession_reason or self.last_error_code
        ):
            raise ValueError("Superseded dispatch requires a reason.")
        if self.attempt_no > self.max_attempts:
            raise ValueError("Dispatch attempt count cannot exceed its retry budget.")
        if self.context_digest is not None:
            encoded_context = json.dumps(
                self.context_json,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            if sha256(encoded_context).hexdigest() != self.context_digest:
                raise ValueError("Context digest does not match the frozen context bytes.")
        if self.dispatch_id != prompt_preparation_dispatch_id(self.logical_key):
            raise ValueError("Dispatch ID must be derived from its logical key.")
        return self


# Compatibility aliases keep one contract discoverable under common internal names.
AgentCanvasPromptPreparationDispatchV1 = PromptPreparationDispatchV1
AgentCanvasPromptPreparationDispatchStatusV1 = PromptPreparationDispatchStatusV1


def prompt_preparation_dispatch_logical_key(
    *,
    workflow_id: str,
    node_id: str,
    node_revision: int,
    operation_id: str,
    role_variant: str | None = None,
    occurrence_id: str | None = None,
    character_phase: str | None = None,
    context_snapshot_id: str | None = None,
    context_digest: str | None = None,
    binding_digest: str | None = None,
    recipe_digest: str | None = None,
    style_projection_digest: str | None = None,
    brief_digest: str | None = None,
    requirement_revision_id: str | None = None,
    requirement_revision_no: int | None = None,
    document_revisions: Mapping[str, int] | None = None,
    source_snapshot: Mapping[str, object] | None = None,
    model_policy_revision: int | None = None,
) -> str:
    """Return a digest-complete identity for one immutable input snapshot."""

    payload = {
        "workflow_id": workflow_id,
        "node_id": node_id,
        "node_revision": node_revision,
        "operation_id": operation_id,
        "role_variant": role_variant,
        "occurrence_id": occurrence_id,
        "character_phase": character_phase,
        "context_snapshot_id": context_snapshot_id,
        "context_digest": context_digest,
        "binding_digest": binding_digest,
        "recipe_digest": recipe_digest,
        "style_projection_digest": style_projection_digest,
        "brief_digest": brief_digest,
        "requirement_revision_id": requirement_revision_id,
        "requirement_revision_no": requirement_revision_no,
        "document_revisions": dict(sorted((document_revisions or {}).items())),
        "source_snapshot": dict(source_snapshot or {}),
        "model_policy_revision": model_policy_revision,
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return "ppd:" + sha256(encoded.encode("utf-8")).hexdigest()


def prompt_preparation_dispatch_id(logical_key: str) -> str:
    """Derive a stable opaque dispatch ID from a logical key."""

    return "ppd_" + sha256(logical_key.encode("utf-8")).hexdigest()[:40]


__all__ = (
    "AgentCanvasPromptPreparationDispatchStatusV1",
    "AgentCanvasPromptPreparationDispatchV1",
    "PromptPreparationDispatchStatusV1",
    "PromptPreparationDispatchV1",
    "prompt_preparation_dispatch_id",
    "prompt_preparation_dispatch_logical_key",
)
