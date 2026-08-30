"""Strict, bounded contracts for the optional V2 presentation channel."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from app.schemas.agent_runtime import _StrictModel

PresentationStreamKindV1 = Literal["assistant", "node_prompt"]
PresentationStreamStatusV1 = Literal["open", "completed", "failed", "superseded"]
PresentationStreamEventTypeV1 = Literal[
    "started",
    "delta",
    "committed",
    "failed",
    "superseded",
    "reset",
    "heartbeat",
]
PresentationStreamErrorCodeV1 = Literal[
    "presentation_stream_failed",
    "presentation_stream_backpressure_exceeded",
    "presentation_stream_cursor_expired",
    "presentation_stream_superseded",
]

_MAX_IDENTIFIER = 160
_MAX_DELTA_BYTES = 4_096
_MAX_ERROR_CODE = 120


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


class PresentationStreamResetV1(_StrictModel):
    """Safe reset details used when a replay cursor is outside retention."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: Literal["cursor_expired", "store_recovered"]
    authoritative_id: str | None = Field(default=None, max_length=_MAX_IDENTIFIER)
    resource_kind: Literal["message", "prompt", "workflow"]


class PresentationStreamMetadataV1(_StrictModel):
    """Immutable identity and bounded status for one presentation generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    stream_id: str = Field(min_length=1, max_length=_MAX_IDENTIFIER)
    workflow_id: str = Field(min_length=1, max_length=_MAX_IDENTIFIER)
    stream_kind: PresentationStreamKindV1
    generation_id: str = Field(min_length=1, max_length=_MAX_IDENTIFIER)
    turn_id: str | None = Field(default=None, max_length=_MAX_IDENTIFIER)
    node_id: str | None = Field(default=None, max_length=_MAX_IDENTIFIER)
    node_revision: int | None = Field(default=None, ge=1)
    status: PresentationStreamStatusV1
    last_sequence_no: int = Field(default=0, ge=0)
    authoritative_id: str | None = Field(default=None, max_length=_MAX_IDENTIFIER)
    content_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    error_code: str | None = Field(default=None, max_length=_MAX_ERROR_CODE)

    @model_validator(mode="after")
    def validate_target(self) -> "PresentationStreamMetadataV1":
        if self.stream_kind == "assistant" and self.turn_id is None:
            raise ValueError("Assistant presentation streams require turn_id.")
        if self.stream_kind == "node_prompt" and (
            self.node_id is None or self.node_revision is None
        ):
            raise ValueError("Prompt presentation streams require node identity.")
        if self.status == "completed" and (
            self.authoritative_id is None or self.content_digest is None
        ):
            raise ValueError("Completed presentation streams require commit identity.")
        if self.status == "failed" and self.error_code is None:
            raise ValueError("Failed presentation streams require an error code.")
        return self


class PresentationStreamEventV1(_StrictModel):
    """One stream-local SSE envelope; sequence numbers are never lifecycle cursors."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    stream_id: str = Field(min_length=1, max_length=_MAX_IDENTIFIER)
    workflow_id: str = Field(min_length=1, max_length=_MAX_IDENTIFIER)
    stream_kind: PresentationStreamKindV1
    event_type: PresentationStreamEventTypeV1
    sequence_no: int = Field(ge=1)
    turn_id: str | None = Field(default=None, max_length=_MAX_IDENTIFIER)
    node_id: str | None = Field(default=None, max_length=_MAX_IDENTIFIER)
    generation_id: str = Field(min_length=1, max_length=_MAX_IDENTIFIER)
    response_locale: str | None = Field(default=None, max_length=35)
    node_revision: int | None = Field(default=None, ge=1)
    delta: str | None = Field(default=None, max_length=_MAX_DELTA_BYTES)
    authoritative_id: str | None = Field(default=None, max_length=_MAX_IDENTIFIER)
    content_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    error_code: str | None = Field(default=None, max_length=_MAX_ERROR_CODE)
    reset: PresentationStreamResetV1 | None = None

    @model_validator(mode="after")
    def validate_event_shape(self) -> "PresentationStreamEventV1":
        if self.stream_kind == "assistant" and self.turn_id is None:
            raise ValueError("Assistant presentation events require turn_id.")
        if self.stream_kind == "node_prompt" and (
            self.node_id is None or self.node_revision is None
        ):
            raise ValueError("Prompt presentation events require node identity.")
        if self.event_type == "delta":
            if not self.delta or len(self.delta.encode("utf-8")) > _MAX_DELTA_BYTES:
                raise ValueError("Presentation delta exceeds the UTF-8 byte limit.")
            if self.authoritative_id or self.content_digest or self.error_code:
                raise ValueError("Delta events cannot expose terminal metadata.")
        elif self.delta is not None:
            raise ValueError("Only delta events may contain presentation text.")
        if self.event_type == "committed" and (
            self.authoritative_id is None or self.content_digest is None
        ):
            raise ValueError("Committed events require authoritative identity and digest.")
        if self.event_type == "failed" and self.error_code is None:
            raise ValueError("Failed events require a stable error code.")
        if self.event_type == "reset" and self.reset is None:
            raise ValueError("Reset events require reset details.")
        if self.event_type != "reset" and self.reset is not None:
            raise ValueError("Only reset events may contain reset details.")
        return self


class SafePresentationDeltaV1(_StrictModel):
    """Typed input accepted from a runtime safe-presentation callback."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stream_id: str = Field(min_length=1, max_length=_MAX_IDENTIFIER)
    workflow_id: str = Field(min_length=1, max_length=_MAX_IDENTIFIER)
    stream_kind: PresentationStreamKindV1
    generation_id: str = Field(min_length=1, max_length=_MAX_IDENTIFIER)
    turn_id: str | None = Field(default=None, max_length=_MAX_IDENTIFIER)
    node_id: str | None = Field(default=None, max_length=_MAX_IDENTIFIER)
    node_revision: int | None = Field(default=None, ge=1)
    response_locale: str | None = Field(default=None, max_length=35)
    text: str = Field(min_length=1, max_length=_MAX_DELTA_BYTES)

    @model_validator(mode="after")
    def validate_safe_text(self) -> "SafePresentationDeltaV1":
        if len(self.text.encode("utf-8")) > _MAX_DELTA_BYTES:
            raise ValueError("Presentation text exceeds the UTF-8 byte limit.")
        if self.stream_kind == "assistant" and self.turn_id is None:
            raise ValueError("Assistant presentation deltas require turn_id.")
        if self.stream_kind == "node_prompt" and (
            self.node_id is None or self.node_revision is None
        ):
            raise ValueError("Prompt presentation deltas require node identity.")
        normalized = self.text.strip()
        if normalized.startswith(("{", "[", "```")):
            raise ValueError("Structured or code-fenced output is not presentation text.")
        try:
            parsed = json.loads(normalized)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, (dict, list)):
            raise ValueError("Structured output is not presentation text.")
        lowered = normalized.lower()
        if any(
            marker in lowered
            for marker in (
                "<system>",
                "tool_call",
                "reasoning",
                "authorization: bearer",
                "api_key",
                "provider_error",
                "traceback",
            )
        ):
            raise ValueError("Hidden or transport content is not presentation text.")
        return self


class PresentationTimingV1(_StrictModel):
    """Bounded phase timings with no content or credential fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted: int | None = Field(default=None, ge=0, le=900_000)
    queued: int | None = Field(default=None, ge=0, le=900_000)
    context_ready: int | None = Field(default=None, ge=0, le=900_000)
    model_started: int | None = Field(default=None, ge=0, le=900_000)
    first_presentation_byte: int | None = Field(default=None, ge=0, le=900_000)
    model_finished: int | None = Field(default=None, ge=0, le=900_000)
    structured_validated: int | None = Field(default=None, ge=0, le=900_000)
    prompt_compiled: int | None = Field(default=None, ge=0, le=900_000)
    authoritative_persisted: int | None = Field(default=None, ge=0, le=900_000)
    media_scheduled: int | None = Field(default=None, ge=0, le=900_000)


__all__ = (
    "PresentationStreamEventV1",
    "PresentationStreamMetadataV1",
    "PresentationStreamResetV1",
    "PresentationTimingV1",
    "SafePresentationDeltaV1",
)
