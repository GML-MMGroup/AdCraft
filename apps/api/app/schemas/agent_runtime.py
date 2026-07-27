"""Canonical internal contracts shared by Python and the Pi Agent runtime."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_operation_contexts import PlanningAgentContext


AgentName = Literal[
    "front_desk",
    "script_writer",
    "product_designer",
    "character_designer",
    "scene_designer",
    "storyboard_artist",
    "video_director",
    "bgm_director",
    "quick_media_agent",
]
AgentRunStatus = Literal[
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
]
AgentEventType = Literal[
    "run_started",
    "output_delta",
    "tool_call",
    "tool_result",
    "heartbeat",
    "run_completed",
    "run_failed",
    "run_cancelled",
]

_PROTOCOL_VERSION = "1"
_MAX_CONTEXT_TEXT = 65_536
_MAX_COLLECTION_ITEMS = 128
_MAX_SAFE_PAYLOAD_BYTES = 65_536
_SENSITIVE_KEY_PARTS = ("api_key", "authorization", "credential", "secret", "token")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class V2ResolvedAgentTarget(_StrictModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    state_version: int = Field(ge=1)
    target_locator: str = Field(min_length=1, max_length=320)
    target_type: Literal["node", "item", "slot", "asset"]
    node_id: Literal["character-generation", "scene-generation"]
    item_id: str = Field(min_length=1, max_length=160)
    slot_id: str = Field(min_length=1, max_length=240)
    slot_type: Literal[
        "character_main_image",
        "character_three_view",
        "scene_main_image",
        "scene_multi_view_grid",
    ]
    owner_type: Literal["character", "scene"]
    display_name: str = Field(min_length=1, max_length=256)
    requested_scope: Literal["main", "multiview"] = "main"
    asset_id: str | None = Field(default=None, max_length=160)
    version_id: str | None = Field(default=None, max_length=160)
    selected_main_asset_locator: str | None = Field(default=None, max_length=320)
    related_multiview_slot_id: str | None = Field(default=None, max_length=240)


class V2AgentTargetCatalog(_StrictModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    state_version: int = Field(ge=1)
    targets: list[V2ResolvedAgentTarget] = Field(default_factory=list, max_length=256)


def _validate_safe_payload(value: Any, *, field_name: str = "payload") -> Any:
    encoded_size = len(str(value).encode("utf-8"))
    if encoded_size > _MAX_SAFE_PAYLOAD_BYTES:
        raise ValueError(f"{field_name} exceeds the internal payload limit")

    def visit(current: Any, key: str | None = None) -> None:
        if key is not None and any(part in key.casefold() for part in _SENSITIVE_KEY_PARTS):
            raise ValueError(f"{field_name} contains a sensitive field")
        if isinstance(current, dict):
            for child_key, child_value in current.items():
                visit(child_value, str(child_key))
        elif isinstance(current, (list, tuple)):
            for child in current:
                visit(child)
        elif isinstance(current, str) and current.startswith(("/", "\\\\")):
            raise ValueError(f"{field_name} contains an absolute path")

    visit(value)
    return value


class AgentReferenceSummary(_StrictModel):
    asset_id: str = Field(min_length=1, max_length=160)
    version_id: str | None = Field(default=None, max_length=160)
    semantic_type: str = Field(min_length=1, max_length=80)
    display_name: str = Field(default="", max_length=256)
    media_type: Literal["image", "video", "audio", "text"] | None = None
    description: str = Field(default="", max_length=2_048)


class AgentTargetContext(_StrictModel):
    target_type: str = Field(min_length=1, max_length=80)
    workflow_id: str | None = Field(default=None, max_length=160)
    node_id: str | None = Field(default=None, max_length=160)
    item_id: str | None = Field(default=None, max_length=160)
    slot_id: str | None = Field(default=None, max_length=160)
    asset_id: str | None = Field(default=None, max_length=160)
    version_id: str | None = Field(default=None, max_length=160)
    owner_type: str | None = Field(default=None, max_length=80)
    owner_display_name: str | None = Field(default=None, max_length=256)
    semantic_type: str | None = Field(default=None, max_length=80)
    current_prompt: str | None = Field(default=None, max_length=16_384)
    selected_version_summary: AgentReferenceSummary | None = None
    reference_asset_summaries: tuple[AgentReferenceSummary, ...] = Field(
        default=(), max_length=_MAX_COLLECTION_ITEMS
    )
    expected_revision: int | None = Field(default=None, ge=1)


class AgentRunContext(_StrictModel):
    operation: str = Field(min_length=1, max_length=120)
    user_input: str = Field(min_length=1, max_length=_MAX_CONTEXT_TEXT)
    conversation_id: str | None = Field(default=None, max_length=160)
    workflow_id: str | None = Field(default=None, max_length=160)
    target: AgentTargetContext | None = None
    screenplay_summary: str | None = Field(default=None, max_length=16_384)
    style_summary: str | None = Field(default=None, max_length=8_192)
    continuity_summary: str | None = Field(default=None, max_length=8_192)
    reference_summaries: tuple[AgentReferenceSummary, ...] = Field(
        default=(), max_length=_MAX_COLLECTION_ITEMS
    )
    constraints: tuple[str, ...] = Field(default=(), max_length=_MAX_COLLECTION_ITEMS)
    system_prompt: str | None = Field(default=None, max_length=32_768)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    contract_schema: dict[str, Any] = Field(default_factory=dict)


class AgentRunPolicy(_StrictModel):
    max_turns: int = Field(default=8, ge=1, le=64)
    max_tool_calls: int = Field(default=16, ge=0, le=128)
    max_handoffs: int = Field(default=8, ge=0, le=32)
    timeout_seconds: float = Field(default=120.0, gt=0, le=900)
    max_input_bytes: int = Field(default=131_072, ge=1, le=4_194_304)
    max_output_bytes: int = Field(default=262_144, ge=1, le=4_194_304)
    max_event_bytes: int = Field(default=65_536, ge=1, le=1_048_576)


class AgentRunRequest(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    run_id: str = Field(min_length=1, max_length=160)
    request_id: str = Field(min_length=1, max_length=160)
    parent_run_id: str | None = Field(default=None, max_length=160)
    agent_name: AgentName
    operation: str = Field(min_length=1, max_length=120)
    deadline_at: datetime
    model_policy_id: str = Field(min_length=1, max_length=160)
    context: PlanningAgentContext | AgentRunContext
    policy: AgentRunPolicy = Field(default_factory=AgentRunPolicy)
    credential_ref: str = Field(default="llm-default", min_length=1, max_length=120)
    contract_name: str | None = Field(default=None, max_length=160)
    contract_schema: dict[str, Any] = Field(default_factory=dict)
    validation_profile: str | None = Field(default=None, max_length=160)
    validation_context: dict[str, Any] = Field(default_factory=dict)
    audit_metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRuntimeEvent(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    seq: int = Field(ge=1)
    run_id: str = Field(min_length=1, max_length=160)
    agent_name: AgentName
    event_type: AgentEventType
    created_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_payload(self) -> AgentRuntimeEvent:
        _validate_safe_payload(self.payload)
        if self.event_type == "run_completed":
            AgentRunCompletedPayload.model_validate(self.payload)
        elif self.event_type == "run_failed":
            AgentRunFailedPayload.model_validate(self.payload)
        elif self.event_type == "run_cancelled":
            AgentRunCancelledPayload.model_validate(self.payload)
        return self


class AgentRunCompletedPayload(_StrictModel):
    value: dict[str, Any]
    audit: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_safe_values(self) -> AgentRunCompletedPayload:
        _validate_safe_payload(self.value, field_name="value")
        _validate_safe_payload(self.audit, field_name="audit")
        return self


class AgentRunFailedPayload(_StrictModel):
    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=1_024)
    retryable: bool = False
    audit: dict[str, Any] = Field(default_factory=dict)


class AgentRunCancelledPayload(_StrictModel):
    code: Literal["agent_run_cancelled"]
    message: str = Field(min_length=1, max_length=1_024)
    audit: dict[str, Any] = Field(default_factory=dict)


class AgentToolCall(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    run_id: str = Field(min_length=1, max_length=160)
    tool_call_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=256)
    tool_name: str = Field(min_length=1, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_arguments(self) -> AgentToolCall:
        _validate_safe_payload(self.arguments, field_name="arguments")
        return self


class AgentToolResult(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    run_id: str = Field(min_length=1, max_length=160)
    tool_call_id: str = Field(min_length=1, max_length=160)
    status: Literal["accepted", "completed", "rejected", "failed"]
    result: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = Field(default=None, max_length=120)
    error_message: str | None = Field(default=None, max_length=1_024)


class AgentStructuredSubmission(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    run_id: str = Field(min_length=1, max_length=160)
    submission_id: str = Field(min_length=1, max_length=160)
    contract_name: str = Field(min_length=1, max_length=160)
    value: dict[str, Any]
    attempt: int = Field(default=1, ge=1, le=2)


class StructuredViolation(_StrictModel):
    code: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=1_024)
    field_path: str | None = Field(default=None, max_length=512)
    expected: Any | None = None
    actual: Any | None = None


class AgentStructuredValidationResult(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    accepted: bool
    normalized_result_id: str | None = Field(default=None, max_length=160)
    normalized_value: dict[str, Any] | None = None
    violations: tuple[StructuredViolation, ...] = Field(default=(), max_length=128)
    repair_allowed: bool = False


class AgentRuntimeHealth(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    runtime_version: str = Field(min_length=1, max_length=80)
    status: Literal["ready", "degraded", "unavailable"]
    mode: Literal["real", "fake"]
    contract_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    skill_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    pi_version: str = Field(min_length=1, max_length=80)
    active_runs: int = Field(default=0, ge=0)


class AgentRuntimeManifest(_StrictModel):
    runtime_version: str = Field(min_length=1, max_length=80)
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    contract_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    skill_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class AgentRuntimeError(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    code: Literal[
        "agent_runtime_unavailable",
        "agent_protocol_mismatch",
        "agent_model_unavailable",
        "agent_structured_output_invalid",
        "agent_run_budget_exceeded",
        "agent_stream_backpressure_exceeded",
        "agent_tool_not_allowed",
        "agent_target_revision_conflict",
        "agent_run_cancelled",
        "agent_runtime_fake_forbidden",
    ]
    message: str = Field(min_length=1, max_length=1_024)
    retryable: bool = False


class SpecialistDraft(_StrictModel):
    contract_name: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=16_384)
    generation_prompt: str | None = Field(default=None, max_length=32_768)
    negative_prompt: str | None = Field(default=None, max_length=8_192)
    constraints: tuple[str, ...] = Field(default=(), max_length=128)
    reference_roles: tuple[str, ...] = Field(default=(), max_length=128)
    warnings: tuple[str, ...] = Field(default=(), max_length=128)
