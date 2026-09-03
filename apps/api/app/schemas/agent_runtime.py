"""Canonical internal contracts shared by Python and the Pi Agent runtime."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_operation_contexts import PlanningAgentContext
from app.schemas.agent_canvas_commands import AgentPlacementHintV2
from app.schemas.agent_canvas import CanvasCreativeRoleV2, ModelSelectionModeV1
from app.schemas.agent_canvas_capabilities import (
    CapabilityInvocationContextV2,
    NextActionContextV1,
    TurnIntentContextV2,
)
from app.schemas.agent_canvas_materialization import CapabilityMaterializationContextV1
from app.schemas.agent_canvas_role_prompt_preparation import RolePromptPreparationContextV2
from app.schemas.agent_canvas_storyboard_sequences import StoryboardSegmentAuthoringContextV2
from app.schemas.agent_canvas_world_setting import WorldSettingContextEnvelopeV2
from app.schemas.provider_models import ProviderConformanceTargetV1


AgentName = Literal["video_agent"]
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
    "presentation_delta",
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
_SAFE_TOKEN_METADATA_KEYS = {
    "input_tokens",
    "max_output_tokens",
    "output_tokens",
    "reasoning_tokens",
    "thinking_budget_tokens",
}


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
        if key is not None:
            normalized_key = key.casefold()
            if normalized_key not in _SAFE_TOKEN_METADATA_KEYS and any(
                part in normalized_key for part in _SENSITIVE_KEY_PARTS
            ):
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
    world_setting: WorldSettingContextEnvelopeV2 | None = None
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


class AgentCanvasScriptOutput(BaseModel):
    """Validated Script Writer output while preserving editable structured fields."""

    model_config = ConfigDict(extra="allow")

    content: str = Field(min_length=1, max_length=32_768)


class AgentCanvasTextOutput(BaseModel):
    """Validated generic Text Node output from the bounded Quick Media Agent."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=32_768)


class AgentRunPolicy(_StrictModel):
    operation_policy_id: str | None = Field(default=None, max_length=160)
    operation_class: Literal["routing", "proposal", "materialization", "long_form"] | None = None
    transport_retry_limit: int = Field(default=0, ge=0, le=1)
    structured_repair_limit: int = Field(default=1, ge=0, le=1)
    max_turns: int = Field(default=8, ge=1, le=64)
    max_tool_calls: int = Field(default=16, ge=0, le=128)
    max_handoffs: Literal[0] = 0
    timeout_seconds: float = Field(default=120.0, gt=0, le=900)
    primary_timeout_seconds: int | None = Field(default=None, ge=1, le=900)
    recovery_timeout_seconds: int | None = Field(default=None, ge=0, le=900)
    persistence_reserve_seconds: int | None = Field(default=None, ge=1, le=900)
    max_model_submissions: Literal[1, 2] | None = None
    recovery_mode: (
        Literal[
            "none",
            "structured_repair_only",
            "transport_retry_or_structured_repair",
        ]
        | None
    ) = None
    max_output_tokens: int | None = Field(default=None, ge=1, le=65_536)
    reasoning_mode: Literal["low", "deep"] | None = None
    enable_thinking: bool | None = None
    thinking_budget_tokens: int | None = Field(default=None, ge=1, le=65_536)
    max_input_bytes: int = Field(default=131_072, ge=1, le=4_194_304)
    max_output_bytes: int = Field(default=262_144, ge=1, le=4_194_304)
    max_event_bytes: int = Field(default=65_536, ge=1, le=1_048_576)

    @model_validator(mode="after")
    def validate_recovery_policy(self) -> "AgentRunPolicy":
        if self.max_model_submissions is None:
            return self
        partitions = (
            self.primary_timeout_seconds,
            self.recovery_timeout_seconds,
            self.persistence_reserve_seconds,
        )
        if (
            any(value is None for value in partitions)
            or sum(int(value) for value in partitions if value is not None) != self.timeout_seconds
        ):
            raise ValueError("Agent run policy partitions must equal its deadline.")
        if self.max_model_submissions == 1:
            if (
                self.recovery_mode != "none"
                or self.recovery_timeout_seconds != 0
                or self.transport_retry_limit != 0
                or self.structured_repair_limit != 0
            ):
                raise ValueError("Single-submission Agent run cannot configure recovery.")
        elif not self.recovery_timeout_seconds or self.recovery_mode == "none":
            raise ValueError("Two-submission Agent run requires bounded recovery.")
        elif self.recovery_mode == "structured_repair_only" and (
            self.transport_retry_limit != 0 or self.structured_repair_limit != 1
        ):
            raise ValueError("Structured-repair-only Agent run cannot retry transport.")
        return self


class AgentModelExecutionPolicyV1(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_ref: str = Field(min_length=1, max_length=320)
    operation: str = Field(min_length=1, max_length=120)
    operation_class: Literal["routing", "proposal", "materialization", "long_form"]
    thinking_format: Literal["zai", "qwen", "none"]
    reasoning_control: Literal[
        "provider_default",
        "enable_thinking",
        "reasoning_effort",
        "none",
    ]
    reasoning_mode: Literal["low", "deep"]
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None
    enable_thinking: bool
    thinking_budget_tokens: int | None = Field(default=None, ge=1, le=65_536)
    structured_transport: Literal[
        "streamed_tool_call",
        "non_streaming_tool_call",
        "non_streaming_json_object",
        "streaming_json_object",
        "json_object",
    ]
    supports_tool_calls: bool
    supports_streamed_tool_calls: bool
    deadline_seconds: int = Field(ge=1, le=900)
    primary_timeout_seconds: int = Field(ge=1, le=900)
    recovery_timeout_seconds: int = Field(ge=0, le=900)
    persistence_reserve_seconds: int = Field(ge=1, le=900)
    max_model_submissions: Literal[1, 2]
    recovery_mode: Literal[
        "none",
        "structured_repair_only",
        "transport_retry_or_structured_repair",
    ]
    max_output_tokens: int = Field(ge=1, le=65_536)
    transport_retry_limit: int = Field(ge=0, le=1)
    structured_repair_limit: int = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_recovery_policy(self) -> "AgentModelExecutionPolicyV1":
        if self.reasoning_control == "reasoning_effort":
            if self.reasoning_effort is None or self.enable_thinking:
                raise ValueError("Reasoning-effort policy cannot use legacy thinking fields.")
            if self.thinking_budget_tokens is not None:
                raise ValueError("Reasoning-effort policy cannot use a thinking budget.")
        elif self.reasoning_effort is not None:
            raise ValueError("Reasoning effort is only valid for its matching control.")
        if (
            self.primary_timeout_seconds
            + self.recovery_timeout_seconds
            + self.persistence_reserve_seconds
            != self.deadline_seconds
        ):
            raise ValueError("Model policy partitions must equal its deadline.")
        if self.max_model_submissions == 1:
            if (
                self.recovery_mode != "none"
                or self.recovery_timeout_seconds != 0
                or self.transport_retry_limit != 0
                or self.structured_repair_limit != 0
            ):
                raise ValueError("Single-submission model policy cannot configure recovery.")
        elif self.recovery_timeout_seconds == 0 or self.recovery_mode == "none":
            raise ValueError("Two-submission model policy requires bounded recovery.")
        elif self.recovery_mode == "structured_repair_only" and (
            self.transport_retry_limit != 0 or self.structured_repair_limit != 1
        ):
            raise ValueError("Structured-repair-only model policy cannot retry transport.")
        return self


class AgentStructuredValidationAttemptAuditV1(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt: Literal[1, 2]
    attempt_stage: Literal["initial", "structured_repair"]
    violation_count: int = Field(ge=1, le=128)
    validation_paths: tuple[Annotated[str, Field(min_length=1, max_length=512)], ...] = Field(
        max_length=32
    )
    violation_codes: tuple[Annotated[str, Field(min_length=1, max_length=160)], ...] = Field(
        min_length=1, max_length=32
    )
    repair_allowed: bool
    truncated: bool

    @model_validator(mode="after")
    def validate_ordered_unique_evidence(self) -> "AgentStructuredValidationAttemptAuditV1":
        if len(self.validation_paths) != len(set(self.validation_paths)):
            raise ValueError("Validation paths must be ordered and unique.")
        if len(self.violation_codes) != len(set(self.violation_codes)):
            raise ValueError("Violation codes must be ordered and unique.")
        expected_stage = "initial" if self.attempt == 1 else "structured_repair"
        if self.attempt_stage != expected_stage:
            raise ValueError("Validation attempt stage must match its attempt number.")
        return self


class AgentTransportAttemptMetadataV1(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, max_length=160)
    model_ref: str = Field(min_length=1, max_length=320)
    structured_transport: Literal[
        "streamed_tool_call",
        "non_streaming_tool_call",
        "non_streaming_json_object",
        "streaming_json_object",
        "json_object",
    ]
    thinking_format: Literal["zai", "qwen", "none"]
    reasoning_control: Literal[
        "provider_default",
        "enable_thinking",
        "reasoning_effort",
        "none",
    ]
    reasoning_mode: Literal["low", "deep"]
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None
    enable_thinking: bool
    thinking_budget_tokens: int | None = Field(default=None, ge=1, le=65_536)
    deadline_seconds: int = Field(ge=1, le=900)
    max_output_tokens: int = Field(ge=1, le=65_536)
    operation_policy_id: str = Field(min_length=1, max_length=160)
    operation_class: Literal["routing", "proposal", "materialization", "long_form"]
    effective_timeout_ms: int = Field(ge=0, le=900_000)
    request_bytes: int = Field(ge=0, le=4_194_304)
    schema_bytes: int = Field(ge=0, le=4_194_304)
    response_bytes: int | None = Field(default=None, ge=0, le=4_194_304)
    response_activity_observed: bool
    attempt_stage: Literal["initial", "transport_retry", "structured_repair"]
    started_at: datetime
    first_response_at: datetime | None = None
    last_activity_at: datetime | None = None
    finished_at: datetime
    duration_ms: int = Field(ge=0, le=900_000)
    finish_reason: str | None = Field(default=None, max_length=120)
    provider_trace_id: str | None = Field(default=None, max_length=320)
    safe_exception_class: str | None = Field(default=None, max_length=160)
    safe_error_code: str | None = Field(default=None, max_length=120)
    http_status: int | None = Field(default=None, ge=100, le=599)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    transport_retry_count: int = Field(ge=0, le=1)
    structured_attempt_count: int = Field(ge=1, le=2)
    structured_validation_attempts: tuple[AgentStructuredValidationAttemptAuditV1, ...] = Field(
        default=(), max_length=2
    )

    @model_validator(mode="after")
    def validate_structured_validation_attempt_order(self) -> "AgentTransportAttemptMetadataV1":
        attempts = tuple(item.attempt for item in self.structured_validation_attempts)
        if attempts != tuple(range(1, len(attempts) + 1)):
            raise ValueError("Structured validation attempts must use ordered identities.")
        return self


class AgentRunRequest(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    run_id: str = Field(min_length=1, max_length=160)
    request_id: str = Field(min_length=1, max_length=160)
    contract_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    context_snapshot_id: str = Field(min_length=1, max_length=160)
    parent_run_id: str | None = Field(default=None, max_length=160)
    agent_name: AgentName
    operation: str = Field(min_length=1, max_length=120)
    deadline_at: datetime
    model_policy_id: str = Field(min_length=1, max_length=160)
    model_ref: str | None = Field(default=None, min_length=1, max_length=320)
    context: (
        PlanningAgentContext
        | AgentRunContext
        | TurnIntentContextV2
        | NextActionContextV1
        | CapabilityInvocationContextV2
        | CapabilityMaterializationContextV1
        | StoryboardSegmentAuthoringContextV2
        | RolePromptPreparationContextV2
    )
    policy: AgentRunPolicy = Field(default_factory=AgentRunPolicy)
    credential_ref: str = Field(default="llm-default", min_length=1, max_length=120)
    contract_name: str | None = Field(default=None, max_length=160)
    contract_schema: dict[str, Any] = Field(default_factory=dict)
    validation_profile: str | None = Field(default=None, max_length=160)
    validation_context: dict[str, Any] = Field(default_factory=dict)
    audit_metadata: dict[str, Any] = Field(default_factory=dict)
    presentation_channel: Literal["assistant", "node_prompt"] | None = None


def canonical_agent_run_request_digest(request: AgentRunRequest) -> str:
    payload = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{sha256(payload).hexdigest()}"


class AgentProviderConformanceBudgetPlanV1(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    budget_version: Literal["1"] = "1"
    maximum_submissions: Literal[6] = 6
    exact_case_timeout_ms: int = Field(ge=1_000, le=900_000)
    isolation_case_timeout_ms: int = Field(ge=1_000, le=60_000)
    matrix_timeout_ms: int = Field(ge=1_000)
    child_timeout_ms: int = Field(ge=1_000)
    lease_duration_seconds: int = Field(ge=1, le=3_600)

    @model_validator(mode="after")
    def validate_derived_budget(self) -> "AgentProviderConformanceBudgetPlanV1":
        expected_isolation_ms = min(self.exact_case_timeout_ms, 60_000)
        success_path_ms = expected_isolation_ms + (3 * self.exact_case_timeout_ms)
        diagnostic_path_ms = self.exact_case_timeout_ms + (5 * expected_isolation_ms)
        expected_matrix_ms = max(success_path_ms, diagnostic_path_ms) + 30_000
        expected_child_ms = expected_matrix_ms + 60_000
        expected_lease_seconds = (expected_child_ms // 1_000) + 60
        if (
            self.isolation_case_timeout_ms != expected_isolation_ms
            or self.matrix_timeout_ms != expected_matrix_ms
            or self.child_timeout_ms != expected_child_ms
            or self.lease_duration_seconds != expected_lease_seconds
        ):
            raise ValueError("conformance_budget_invalid")
        return self


class AgentProviderConformanceInputV2(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2"] = "2"
    frozen_agent_request: AgentRunRequest
    frozen_agent_request_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    target: ProviderConformanceTargetV1
    budget_plan: AgentProviderConformanceBudgetPlanV1
    evidence_destination_id: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_frozen_authority(self) -> "AgentProviderConformanceInputV2":
        if self.frozen_agent_request_digest != canonical_agent_run_request_digest(
            self.frozen_agent_request
        ):
            raise ValueError("Frozen Agent request digest does not match the request.")
        request = self.frozen_agent_request
        if (
            self.target.model_ref != request.model_ref
            or self.target.operation != request.operation
            or self.target.contract_digest != request.contract_digest
            or self.target.capability != "text"
        ):
            raise ValueError("conformance_target_mismatch")

        from app.services.agent_provider_conformance_budget import (
            AgentProviderConformanceBudgetError,
            derive_agent_provider_conformance_budget,
        )

        try:
            expected_budget = derive_agent_provider_conformance_budget(self.frozen_agent_request)
        except AgentProviderConformanceBudgetError as exc:
            raise ValueError("conformance_budget_invalid") from exc
        if self.budget_plan != expected_budget:
            raise ValueError("conformance_budget_invalid")
        return self


class AgentPresentationDeltaV1(_StrictModel):
    """Explicit user-visible text emitted only through an approved channel."""

    channel: Literal["assistant", "node_prompt"]
    workflow_id: str = Field(min_length=1, max_length=160)
    generation_id: str = Field(min_length=1, max_length=160)
    turn_id: str | None = Field(default=None, max_length=160)
    node_id: str | None = Field(default=None, max_length=160)
    node_revision: int | None = Field(default=None, ge=1)
    text: str = Field(min_length=1, max_length=4_096)
    response_locale: str | None = Field(default=None, max_length=35)

    @model_validator(mode="after")
    def validate_text(self) -> "AgentPresentationDeltaV1":
        if len(self.text.encode("utf-8")) > 4_096:
            raise ValueError("Presentation text exceeds the UTF-8 byte limit.")
        return self


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
        if self.event_type == "presentation_delta":
            AgentPresentationDeltaV1.model_validate(self.payload)
        elif self.event_type == "run_completed":
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
    tool_name: Literal["submit_structured_result"] = "submit_structured_result"
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


class AgentStructuredNormalizationAuditV1(_StrictModel):
    contract_name: str = Field(min_length=1, max_length=160)
    rule_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    normalized_path_count: int = Field(ge=1, le=128)
    submission_attempt: int = Field(ge=1, le=2)


class AgentStructuredValidationResult(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    accepted: bool
    normalized_result_id: str | None = Field(default=None, max_length=160)
    normalized_value: dict[str, Any] | None = None
    violations: tuple[StructuredViolation, ...] = Field(default=(), max_length=128)
    repair_allowed: bool = False
    normalization_audit: AgentStructuredNormalizationAuditV1 | None = None


class AgentRuntimeHealth(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    runtime_version: str = Field(min_length=1, max_length=80)
    status: Literal["ready", "degraded", "unavailable"]
    mode: Literal["real", "fake"]
    contract_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    capability_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    skill_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    pi_version: str = Field(min_length=1, max_length=80)
    active_runs: int = Field(default=0, ge=0)


class AgentRuntimeManifest(_StrictModel):
    runtime_version: str = Field(min_length=1, max_length=80)
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    contract_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    capability_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    skill_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class AgentRuntimeError(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    code: Literal[
        "agent_runtime_unavailable",
        "agent_protocol_mismatch",
        "agent_model_incompatible",
        "agent_model_policy_mismatch",
        "agent_model_unavailable",
        "agent_operation_not_allowed",
        "agent_structured_output_invalid",
        "agent_run_budget_exceeded",
        "agent_deadline_exceeded",
        "agent_stream_backpressure_exceeded",
        "agent_tool_not_allowed",
        "agent_target_revision_conflict",
        "agent_run_cancelled",
        "agent_runtime_fake_forbidden",
        "provider_credentials_invalid",
        "provider_credentials_missing",
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


class AgentNodeIdRefV2(_StrictModel):
    kind: Literal["node_id"] = "node_id"
    node_id: str = Field(min_length=1, max_length=160)


class AgentOperationResultRefV2(_StrictModel):
    kind: Literal["operation_result"] = "operation_result"
    operation_id: str = Field(min_length=1, max_length=160)


AgentNodeRefV2 = Annotated[
    AgentNodeIdRefV2 | AgentOperationResultRefV2,
    Field(discriminator="kind"),
]


class AgentAssetRefV2(_StrictModel):
    kind: Literal["image_asset"] = "image_asset"
    asset_id: str = Field(min_length=1, max_length=160)
    version_id: str | None = Field(default=None, max_length=160)


class _AgentCommandOperationV2(_StrictModel):
    operation_id: str = Field(min_length=1, max_length=160)


def _validate_model_selection(
    mode: ModelSelectionModeV1 | None,
    model_ref: str | None,
    *,
    partial: bool = False,
) -> None:
    if partial and mode is None and model_ref is None:
        return
    if (mode == "default" and model_ref is not None) or (mode == "explicit" and not model_ref):
        raise ValueError("model_selection_invalid")


class AgentCreateDraftNodeOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["create_draft_node"] = "create_draft_node"
    node_type: Literal["text", "script", "image", "video", "audio"]
    creative_role: CanvasCreativeRoleV2
    title: str = Field(min_length=1, max_length=256)
    summary_prompt: str | None = Field(default=None, max_length=8_192)
    generation_prompt: str | None = Field(default=None, max_length=32_768)
    structured_content: dict[str, Any] = Field(default_factory=dict)
    model_selection_mode: ModelSelectionModeV1 = "default"
    model_ref: str | None = Field(default=None, min_length=3, max_length=320)
    parameters: dict[str, Any] = Field(default_factory=dict)
    source_asset_id: str | None = Field(default=None, max_length=160)
    video_skill_run_id: str | None = Field(default=None, max_length=160)
    placement_hint: AgentPlacementHintV2

    @model_validator(mode="after")
    def validate_model_selection(self) -> "AgentCreateDraftNodeOperationV2":
        _validate_model_selection(self.model_selection_mode, self.model_ref)
        return self


class AgentPatchEditableNodeOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["patch_editable_node"] = "patch_editable_node"
    node: AgentNodeRefV2
    title: str | None = Field(default=None, min_length=1, max_length=256)
    summary_prompt: str | None = Field(default=None, max_length=8_192)
    generation_prompt: str | None = Field(default=None, max_length=32_768)
    structured_content: dict[str, Any] | None = None
    model_selection_mode: ModelSelectionModeV1 | None = None
    model_ref: str | None = Field(default=None, min_length=3, max_length=320)
    parameters: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_model_selection(self) -> "AgentPatchEditableNodeOperationV2":
        _validate_model_selection(
            self.model_selection_mode,
            self.model_ref,
            partial=True,
        )
        return self


class AgentCreateBindingOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["create_binding"] = "create_binding"
    source: AgentNodeRefV2 | AgentAssetRefV2
    target: AgentNodeRefV2
    binding_kind: Literal[
        "brief_context",
        "script_context",
        "image_reference",
        "video_reference",
        "audio_reference",
    ]
    required: bool = True
    display_order: int = Field(default=0, ge=0)


class AgentPatchBindingOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["patch_binding"] = "patch_binding"
    binding_id: str = Field(min_length=1, max_length=160)
    required: bool | None = None
    enabled: bool | None = None
    display_order: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_changes(self) -> "AgentPatchBindingOperationV2":
        if self.required is None and self.enabled is None and self.display_order is None:
            raise ValueError("Binding patch requires at least one change.")
        return self


class AgentDeleteBindingOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["delete_binding"] = "delete_binding"
    binding_id: str = Field(min_length=1, max_length=160)


class AgentDeleteNodeOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["delete_node"] = "delete_node"
    node: AgentNodeRefV2


class AgentMaterializeSiblingDraftOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["materialize_sibling_draft"] = "materialize_sibling_draft"
    source_node: AgentNodeRefV2
    title: str = Field(min_length=1, max_length=256)
    generation_prompt: str = Field(min_length=1, max_length=32_768)
    model_selection_mode: ModelSelectionModeV1 = "default"
    model_ref: str | None = Field(default=None, min_length=3, max_length=320)
    parameters: dict[str, Any] = Field(default_factory=dict)
    placement_hint: AgentPlacementHintV2

    @model_validator(mode="after")
    def validate_model_selection(self) -> "AgentMaterializeSiblingDraftOperationV2":
        _validate_model_selection(self.model_selection_mode, self.model_ref)
        return self


class AgentRequestNodeRunOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["request_node_run"] = "request_node_run"
    node: AgentNodeRefV2


AgentCommandOperationDraftV2 = Annotated[
    AgentCreateDraftNodeOperationV2
    | AgentPatchEditableNodeOperationV2
    | AgentCreateBindingOperationV2
    | AgentPatchBindingOperationV2
    | AgentDeleteBindingOperationV2
    | AgentDeleteNodeOperationV2
    | AgentMaterializeSiblingDraftOperationV2
    | AgentRequestNodeRunOperationV2,
    Field(discriminator="operation_type"),
]


_NODE_RESULT_OPERATIONS = {
    "create_draft_node",
    "materialize_sibling_draft",
}


def _operation_result_references(value: Any) -> tuple[str, ...]:
    references: list[str] = []

    def visit(current: Any) -> None:
        if isinstance(current, dict):
            if current.get("kind") == "operation_result":
                operation_id = current.get("operation_id")
                if isinstance(operation_id, str):
                    references.append(operation_id)
            for child in current.values():
                visit(child)
        elif isinstance(current, (list, tuple)):
            for child in current:
                visit(child)

    visit(value)
    return tuple(references)


class AgentCommandPlanDraftV2(_StrictModel):
    operations: tuple[AgentCommandOperationDraftV2, ...] = Field(
        min_length=1,
        max_length=8,
    )
    continuation_requested: bool = False

    @model_validator(mode="after")
    def validate_operation_graph(self) -> "AgentCommandPlanDraftV2":
        all_operations = {operation.operation_id: operation for operation in self.operations}
        if len(all_operations) != len(self.operations):
            raise ValueError("Command operation_id values must be unique.")
        seen: dict[str, _AgentCommandOperationV2] = {}
        for operation in self.operations:
            operation_payload = operation.model_dump(mode="python")
            _validate_safe_payload(operation_payload, field_name="command operation")
            for reference_id in _operation_result_references(operation_payload):
                if reference_id not in seen:
                    raise ValueError("Command operation result reference must point backward.")
                if seen[reference_id].operation_type not in _NODE_RESULT_OPERATIONS:
                    raise ValueError("Referenced command operation does not produce a node.")
            seen[operation.operation_id] = operation
        return self


AgentCommandRiskV2 = Literal[
    "reversible_authoring",
    "destructive_authoring",
    "external_effect",
]
AgentCommandPlanStatusV2 = Literal[
    "pending_confirmation",
    "applying",
    "applied",
    "rejected",
    "superseded",
    "failed",
]


class AgentCommandPlanCreateV2(AgentCommandPlanDraftV2):
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    source_turn_id: str = Field(min_length=1, max_length=160)
    context_snapshot_id: str = Field(min_length=1, max_length=160)
    base_workflow_revision: int = Field(ge=1)
    expires_at: datetime
    risk: AgentCommandRiskV2
    confirmation_required: bool
    target_summary: str = Field(default="", max_length=4_000)


class AgentCommandPlanV2(AgentCommandPlanCreateV2):
    plan_id: str = Field(min_length=1, max_length=160)
    operation_fingerprint: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=256)
    status: AgentCommandPlanStatusV2
    supersedes_plan_id: str | None = Field(default=None, max_length=160)
    replacement_plan_id: str | None = Field(default=None, max_length=160)
    actor: Literal["agent", "user", "system"] = "agent"
    created_at: datetime
    updated_at: datetime


class AgentCommandReplanResultV2(_StrictModel):
    original_plan_id: str = Field(min_length=1, max_length=160)
    replacement_plan: AgentCommandPlanV2
    confirmation_transferred: bool


class AgentOperationResultV2(_StrictModel):
    operation_id: str = Field(min_length=1, max_length=160)
    node_id: str | None = Field(default=None, max_length=160)
    binding_id: str | None = Field(default=None, max_length=160)
    execution_id: str | None = Field(default=None, max_length=160)
    status: Literal["applied", "queued", "failed"]
    error_code: str | None = Field(default=None, max_length=160)


class AgentCommandTransactionResultV2(_StrictModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    workflow_revision: int = Field(ge=1)
    operation_results: tuple[AgentOperationResultV2, ...] = Field(max_length=8)
    created_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    updated_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    deleted_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    created_binding_ids: tuple[str, ...] = Field(default=(), max_length=64)
    deleted_binding_ids: tuple[str, ...] = Field(default=(), max_length=64)
    post_commit_run_node_ids: tuple[str, ...] = Field(default=(), max_length=8)


class AgentActionEnvelopeV2(_StrictModel):
    assistant_message: str = Field(min_length=1, max_length=4_000)
    command_plan: AgentCommandPlanDraftV2 | None = None
