"""Public and persistence contracts for durable V2 Agent conversations."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.agent_canvas_capabilities import NextActionContextV1
from app.schemas.language import BCP47Tag


_MAX_SAFE_JSON_BYTES = 16_384
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "chain_of_thought",
    "credential",
    "provider_payload",
    "reasoning",
    "secret",
    "token",
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _validate_safe_json(value: Any) -> Any:
    if len(str(value).encode("utf-8")) > _MAX_SAFE_JSON_BYTES:
        raise ValueError("Agent conversation metadata exceeds the size limit")

    def visit(current: Any, key: str | None = None) -> None:
        normalized_key = key.casefold() if key else ""
        if normalized_key and any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
            raise ValueError("Agent conversation metadata contains a forbidden field")
        if isinstance(current, dict):
            for child_key, child in current.items():
                visit(child, str(child_key))
        elif isinstance(current, (list, tuple)):
            for child in current:
                visit(child)
        elif isinstance(current, (bytes, bytearray, memoryview)):
            raise ValueError("Agent conversation metadata cannot contain media bytes")
        elif isinstance(current, str):
            lowered = current.casefold()
            if lowered.startswith(("data:", "/", "\\\\")) or ";base64," in lowered:
                raise ValueError("Agent conversation metadata contains unsafe media data")

    visit(value)
    return value


class V2AgentConversationCreate(_StrictModel):
    conversation_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    title: str = Field(default="", max_length=256)


class V2AgentConversationCreateRequest(_StrictModel):
    title: str = Field(default="", max_length=256)


class V2AgentConversation(_StrictModel):
    conversation_id: str
    workflow_id: str
    status: Literal["active", "archived"]
    title: str = ""
    rolling_summary: str = ""
    last_message_sequence: int = Field(ge=0)
    created_at: str
    updated_at: str


class V2AgentConversationPage(_StrictModel):
    items: list[V2AgentConversation] = Field(default_factory=list)
    next_cursor: str | None = None


class V2AgentMessageCreate(_StrictModel):
    message_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=16_384)
    target: dict[str, Any] | None = None

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message content must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_target(self) -> "V2AgentMessageCreate":
        if self.target is not None:
            _validate_safe_json(self.target)
        return self


class V2AgentMessage(_StrictModel):
    message_id: str
    conversation_id: str
    sequence_no: int = Field(ge=1)
    role: Literal["user", "assistant", "system"]
    content: str
    target: dict[str, Any] | None = None
    created_at: str


class V2AgentMessagePage(_StrictModel):
    items: list[V2AgentMessage] = Field(default_factory=list)
    next_cursor: int | None = None


V2AgentActionStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class V2AgentActionCreate(_StrictModel):
    action_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    request_id: str = Field(min_length=1, max_length=160)
    action_mode: str = Field(min_length=1, max_length=80)
    target: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_target(self) -> "V2AgentActionCreate":
        if self.target is not None:
            _validate_safe_json(self.target)
        return self


class V2AgentAction(_StrictModel):
    action_id: str
    conversation_id: str
    request_id: str
    action_mode: str
    target: dict[str, Any] | None = None
    status: V2AgentActionStatus
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str


class V2AgentConversationDetail(_StrictModel):
    conversation: V2AgentConversation
    messages: V2AgentMessagePage
    actions: list[V2AgentAction] = Field(default_factory=list)


class V2AgentConversationMessageRequest(_StrictModel):
    request_id: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=4_000)
    target: dict[str, Any] | None = None
    action_mode: Literal["auto", "revise_prompt", "revise_and_generate"] = "auto"

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_target(self) -> "V2AgentConversationMessageRequest":
        if self.target is not None:
            _validate_safe_json(self.target)
        return self


class V2AgentConversationMessageResponse(_StrictModel):
    conversation: V2AgentConversation
    user_message: V2AgentMessage
    assistant_message: V2AgentMessage | None = None
    action: V2AgentAction


class WorkflowConversationAnswerContextV1(_StrictModel):
    """Revision-bound workflow state observed before a conversation reply."""

    workflow_id: str = Field(min_length=1, max_length=160)
    workflow_revision: int = Field(ge=0)
    response_locale: BCP47Tag
    journey_stage: str | None = Field(default=None, max_length=80)
    journey_status: str | None = Field(default=None, max_length=80)
    awaiting_action: NextActionContextV1 | None = None
    next_action: NextActionContextV1 | None = None
    source_revision: int | None = Field(default=None, ge=0)


class WorkflowConversationReply(_StrictModel):
    message: str = Field(min_length=1, max_length=4_000)
    clarification_required: bool = False
    answer_kind: Literal["greeting", "progress", "clarification", "general"] = "general"
    state_reference: WorkflowConversationAnswerContextV1 | None = None


class ConversationSummaryResult(_StrictModel):
    summary: str = Field(min_length=1, max_length=16_384)
