"""Strict contracts for acceptance-only Agent model transport traces."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.agent_runtime import AgentModelExecutionPolicyV1
from app.schemas.provider_models import OpenRouterRoutingPolicyV1


_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_MAX_RESPONSE_CHARS = 262_144
_MAX_TRACE_ENTRIES = 128
_FORBIDDEN_KEY_PARTS = (
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
)
_FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"\bBearer\s+\S+", re.IGNORECASE),
    re.compile(r"\b(?:api[_-]?key|authorization|cookie|password|secret)\s*[:=]", re.IGNORECASE),
    re.compile(r"^data:", re.IGNORECASE),
    re.compile(r"(?:[?&](?:x-amz-signature|signature|token|credential)=)", re.IGNORECASE),
    re.compile(r"^(?:/|\\\\|[A-Za-z]:[\\/])"),
    re.compile(r"^file://", re.IGNORECASE),
    re.compile(r"Traceback \(most recent call last\):"),
)
_VOLATILE_DIGEST_FIELDS = frozenset(
    {
        "created_at",
        "sealed_at",
        "started_at",
        "finished_at",
        "first_response_at",
        "last_activity_at",
        "duration_ms",
        "request_id",
        "provider_trace_id",
        "response_id",
    }
)


class _FrozenTraceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _unsafe_trace_error() -> ValueError:
    return ValueError("acceptance_model_trace_unsafe")


def _validate_safe_trace_value(value: Any) -> Any:
    """Reject values that cannot be retained as bounded model evidence."""

    def visit(current: Any, key: str | None = None) -> None:
        if key is not None:
            normalized = key.casefold()
            if any(part in normalized for part in _FORBIDDEN_KEY_PARTS):
                raise _unsafe_trace_error()
        if isinstance(current, Mapping):
            for child_key, child in current.items():
                visit(child, str(child_key))
        elif isinstance(current, (list, tuple)):
            for child in current:
                visit(child)
        elif isinstance(current, str):
            if len(current) > _MAX_RESPONSE_CHARS:
                raise _unsafe_trace_error()
            if any(pattern.search(current) for pattern in _FORBIDDEN_VALUE_PATTERNS):
                raise _unsafe_trace_error()

    visit(value)
    return value


def _canonical_value(value: Any, *, excluded: frozenset[str]) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(child, excluded=excluded)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
            if str(key) not in excluded and child is not None
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(child, excluded=excluded) for child in value]
    return value


def _canonical_digest(value: Any, *, exclude: frozenset[str] = frozenset()) -> str:
    payload = json.dumps(
        _canonical_value(value, excluded=exclude),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{sha256(payload).hexdigest()}"


class AgentModelTraceRequestIdentityV1(_FrozenTraceModel):
    logical_invocation_key: str = Field(min_length=1, max_length=320)
    operation: str = Field(min_length=1, max_length=120)
    attempt_stage: Literal[
        "initial",
        "structured_repair",
        "transport_retry",
        "capability_fallback",
    ]
    attempt_ordinal: int = Field(ge=1, le=4)
    provider: str = Field(min_length=1, max_length=120)
    model_ref: str = Field(min_length=1, max_length=320)
    model_id: str = Field(min_length=1, max_length=320)
    structured_transport: Literal[
        "streamed_tool_call",
        "non_streaming_tool_call",
        "non_streaming_json_object",
        "non_streaming_json_schema",
        "streaming_json_object",
    ]
    operation_policy_id: str = Field(min_length=1, max_length=160)
    request_digest: str = Field(pattern=_DIGEST_PATTERN)
    contract_digest: str = Field(pattern=_DIGEST_PATTERN)
    runtime_digest: str = Field(pattern=_DIGEST_PATTERN)
    prompt_digest: str = Field(pattern=_DIGEST_PATTERN)
    schema_digest: str = Field(pattern=_DIGEST_PATTERN)
    skill_digest: str = Field(pattern=_DIGEST_PATTERN)
    policy_digest: str = Field(pattern=_DIGEST_PATTERN)
    supports_tool_calls: bool
    supports_strict_structured_output: bool
    supports_streaming: bool
    supports_streamed_tool_calls: bool
    supports_reasoning_controls: bool
    adapter_id: str = Field(min_length=1, max_length=160)
    transport_kind: Literal["pi_native_openai_compatible", "litellm_chat"]
    capability_revision: str = Field(min_length=1, max_length=160)
    adapter_revision: str = Field(min_length=1, max_length=160)
    gateway_id: str | None = Field(default=None, max_length=160)
    model_alias: str | None = Field(default=None, max_length=320)
    projection_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    openrouter_routing: OpenRouterRoutingPolicyV1 | None = None
    execution_policy: AgentModelExecutionPolicyV1


def canonical_model_trace_request_digest(
    value: AgentModelTraceRequestIdentityV1 | Mapping[str, Any],
) -> str:
    return _canonical_digest(value)


class AgentModelTraceToolCallV1(_FrozenTraceModel):
    tool_call_id: str = Field(min_length=1, max_length=160)
    tool_name: Literal["submit_structured_result"] = "submit_structured_result"
    arguments_json: str = Field(min_length=2, max_length=_MAX_RESPONSE_CHARS)

    @field_validator("arguments_json")
    @classmethod
    def validate_arguments_json(cls, value: str) -> str:
        _validate_safe_trace_value(value)
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("acceptance_model_trace_invalid") from error
        if not isinstance(parsed, dict):
            raise ValueError("acceptance_model_trace_invalid")
        return value


class AgentModelTraceNonStreamingResponseV1(_FrozenTraceModel):
    response_kind: Literal["non_streaming"] = "non_streaming"
    response_id: str | None = Field(default=None, min_length=1, max_length=160)
    finish_reason: str | None = Field(default=None, max_length=80)
    content: str | None = Field(default=None, max_length=_MAX_RESPONSE_CHARS)
    tool_calls: tuple[AgentModelTraceToolCallV1, ...] = Field(default=(), max_length=1)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_parser_response(self) -> "AgentModelTraceNonStreamingResponseV1":
        if self.content is None and not self.tool_calls:
            raise ValueError("acceptance_model_trace_invalid")
        _validate_safe_trace_value(self.model_dump(mode="json"))
        return self


class AgentModelTraceStreamingChunkV1(_FrozenTraceModel):
    sequence_no: int = Field(ge=1, le=16_384)
    content: str | None = Field(default=None, max_length=65_536)
    finish_reason: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def validate_chunk(self) -> "AgentModelTraceStreamingChunkV1":
        if self.content is None and self.finish_reason is None:
            raise ValueError("acceptance_model_trace_invalid")
        _validate_safe_trace_value(self.model_dump(mode="json"))
        return self


class AgentModelTraceStreamingResponseV1(_FrozenTraceModel):
    response_kind: Literal["streaming"] = "streaming"
    chunks: tuple[AgentModelTraceStreamingChunkV1, ...] = Field(
        min_length=1,
        max_length=16_384,
    )
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_chunk_order(self) -> "AgentModelTraceStreamingResponseV1":
        sequence = tuple(chunk.sequence_no for chunk in self.chunks)
        if sequence != tuple(range(1, len(sequence) + 1)):
            raise ValueError("acceptance_model_trace_invalid")
        terminal_indexes = [index for index, chunk in enumerate(self.chunks) if chunk.finish_reason]
        if len(terminal_indexes) != 1 or terminal_indexes[0] != len(self.chunks) - 1:
            raise ValueError("acceptance_model_trace_invalid")
        _validate_safe_trace_value(self.model_dump(mode="json"))
        return self


class AgentModelTraceSafeFailureV1(_FrozenTraceModel):
    response_kind: Literal["transport_failure"] = "transport_failure"
    error_code: str = Field(min_length=1, max_length=120)
    exception_class: str | None = Field(default=None, max_length=160)
    http_status: int | None = Field(default=None, ge=100, le=599)
    response_started: bool

    @model_validator(mode="after")
    def validate_safe_failure(self) -> "AgentModelTraceSafeFailureV1":
        _validate_safe_trace_value(self.model_dump(mode="json"))
        return self


AgentModelTraceResponseV1 = Annotated[
    AgentModelTraceNonStreamingResponseV1
    | AgentModelTraceStreamingResponseV1
    | AgentModelTraceSafeFailureV1,
    Field(discriminator="response_kind"),
]


class AgentModelTraceEntryV1(_FrozenTraceModel):
    sequence_no: int = Field(ge=1, le=_MAX_TRACE_ENTRIES)
    previous_entry_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    attempt_id: str = Field(min_length=1, max_length=160)
    recorded_agent_run_id: str = Field(min_length=1, max_length=160)
    request_identity: AgentModelTraceRequestIdentityV1
    response: AgentModelTraceResponseV1
    created_at: datetime
    entry_digest: str = Field(pattern=_DIGEST_PATTERN)

    @model_validator(mode="after")
    def validate_entry_digest(self) -> "AgentModelTraceEntryV1":
        if self.entry_digest != canonical_model_trace_entry_digest(self):
            raise ValueError("acceptance_model_trace_invalid")
        return self


def canonical_model_trace_entry_digest(
    value: AgentModelTraceEntryV1 | Mapping[str, Any],
) -> str:
    return _canonical_digest(
        value,
        exclude=_VOLATILE_DIGEST_FIELDS | frozenset({"entry_digest"}),
    )


class AgentModelTraceBundleV1(_FrozenTraceModel):
    schema_version: Literal["1"] = "1"
    fixture_id: str = Field(min_length=1, max_length=160)
    profile_id: str = Field(min_length=1, max_length=160)
    source_acceptance_run_id: str = Field(min_length=1, max_length=160)
    source_attempt_id: str = Field(min_length=1, max_length=160)
    source_workflow_id: str | None = Field(default=None, max_length=160)
    source_project_id: str | None = Field(default=None, max_length=160)
    trace_mode: Literal["live_record", "synthetic"]
    parent_bundle_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    entries: tuple[AgentModelTraceEntryV1, ...] = Field(
        min_length=1,
        max_length=_MAX_TRACE_ENTRIES,
    )
    terminal_disposition: Literal["handled_success", "handled_failure"]
    terminal_failure_code: str | None = Field(default=None, max_length=120)
    created_at: datetime
    sealed_at: datetime
    bundle_digest: str = Field(pattern=_DIGEST_PATTERN)

    @model_validator(mode="after")
    def validate_seal(self) -> "AgentModelTraceBundleV1":
        sequence = tuple(entry.sequence_no for entry in self.entries)
        if sequence != tuple(range(1, len(sequence) + 1)):
            raise ValueError("acceptance_model_trace_invalid")
        previous: str | None = None
        for entry in self.entries:
            if entry.previous_entry_digest != previous:
                raise ValueError("acceptance_model_trace_invalid")
            previous = entry.entry_digest
        if (self.terminal_disposition == "handled_failure") != bool(
            self.terminal_failure_code
        ):
            raise ValueError("acceptance_model_trace_invalid")
        if self.bundle_digest != canonical_model_trace_bundle_digest(self):
            raise ValueError("acceptance_model_trace_invalid")
        return self


def canonical_model_trace_bundle_digest(
    value: AgentModelTraceBundleV1 | Mapping[str, Any],
) -> str:
    return _canonical_digest(
        value,
        exclude=_VOLATILE_DIGEST_FIELDS | frozenset({"bundle_digest"}),
    )


class AgentModelTraceRecordRequestV1(_FrozenTraceModel):
    protocol_version: Literal["1"] = "1"
    session_id: str = Field(min_length=1, max_length=160)
    attempt_id: str = Field(min_length=1, max_length=160)
    recorded_agent_run_id: str = Field(min_length=1, max_length=160)
    request_identity: AgentModelTraceRequestIdentityV1
    response: AgentModelTraceResponseV1


class AgentModelTraceRecordReceiptV1(_FrozenTraceModel):
    protocol_version: Literal["1"] = "1"
    session_id: str = Field(min_length=1, max_length=160)
    attempt_id: str = Field(min_length=1, max_length=160)
    sequence_no: int = Field(ge=1, le=_MAX_TRACE_ENTRIES)
    entry_digest: str = Field(pattern=_DIGEST_PATTERN)
    replayed: bool = False


class AgentModelTraceClaimRequestV1(_FrozenTraceModel):
    protocol_version: Literal["1"] = "1"
    session_id: str = Field(min_length=1, max_length=160)
    attempt_id: str = Field(min_length=1, max_length=160)
    request_identity: AgentModelTraceRequestIdentityV1


class AgentModelTraceClaimResponseV1(_FrozenTraceModel):
    protocol_version: Literal["1"] = "1"
    session_id: str = Field(min_length=1, max_length=160)
    attempt_id: str = Field(min_length=1, max_length=160)
    sequence_no: int = Field(ge=1, le=_MAX_TRACE_ENTRIES)
    entry_digest: str = Field(pattern=_DIGEST_PATTERN)
    response: AgentModelTraceResponseV1
    replayed: bool = False


class AgentModelTraceEvidenceV1(_FrozenTraceModel):
    evidence_kind: Literal["live_record", "model_replay", "checkpoint_resume", "final_fresh"]
    relative_bundle_path: str = Field(min_length=1, max_length=320)
    bundle_digest: str = Field(pattern=_DIGEST_PATTERN)
    source_bundle_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    parent_bundle_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    source_recorded_attempts: int = Field(default=0, ge=0, le=_MAX_TRACE_ENTRIES)
    current_network_submissions: int = Field(default=0, ge=0, le=_MAX_TRACE_ENTRIES)
    replayed_attempts: int = Field(default=0, ge=0, le=_MAX_TRACE_ENTRIES)
    consumed_entries: int = Field(default=0, ge=0, le=_MAX_TRACE_ENTRIES)
    unused_entries: int = Field(default=0, ge=0, le=_MAX_TRACE_ENTRIES)
    structured_repair_count: int = Field(default=0, ge=0, le=_MAX_TRACE_ENTRIES)
    transport_retry_count: int = Field(default=0, ge=0, le=_MAX_TRACE_ENTRIES)
    media_provider_submission_count: int = Field(default=0, ge=0)
    paid_submission_count: int = Field(default=0, ge=0)
    safe_failure_code: str | None = Field(default=None, max_length=120)


class AgentModelTraceReplayConfigV1(_FrozenTraceModel):
    mode: Literal["replay"] = "replay"
    session_id: str = Field(min_length=1, max_length=160)
    bundle_path: str = Field(min_length=1, max_length=1_024)
    expected_bundle_digest: str = Field(pattern=_DIGEST_PATTERN)
    case_profile_id: str = Field(min_length=1, max_length=160)
    isolated_runtime: Literal[True] = True
    media_mode: Literal["mock"] = "mock"

    @field_validator("bundle_path")
    @classmethod
    def validate_bundle_path_is_not_exposed_content(cls, value: str) -> str:
        _validate_safe_trace_value(value)
        return value


class _AgentRuntimeTransportSourceBaseV1(_FrozenTraceModel):
    protocol_version: Literal["1"] = "1"
    provider: str = Field(min_length=1, max_length=120)
    model_ref: str = Field(min_length=1, max_length=320)
    model_id: str = Field(min_length=1, max_length=320)
    model_policy_id: str = Field(min_length=1, max_length=160)
    supports_tool_calls: bool
    supports_strict_structured_output: bool
    supports_streaming: bool
    supports_streamed_tool_calls: bool
    supports_reasoning_controls: bool
    adapter_id: str = Field(min_length=1, max_length=160)
    transport_kind: Literal["pi_native_openai_compatible", "litellm_chat"]
    capability_revision: str = Field(min_length=1, max_length=160)
    adapter_revision: str = Field(min_length=1, max_length=160)
    gateway_id: str | None = Field(default=None, max_length=160)
    model_alias: str | None = Field(default=None, max_length=320)
    projection_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    openrouter_routing: OpenRouterRoutingPolicyV1 | None = None
    execution_policy: AgentModelExecutionPolicyV1


class AgentRuntimeProviderSourceV1(_AgentRuntimeTransportSourceBaseV1):
    source_kind: Literal["provider"] = "provider"
    base_url: str = Field(min_length=1, max_length=2_048)
    api_key: str = Field(min_length=1, max_length=4_096, repr=False)
    trace_mode: Literal["disabled", "live_record"] = "disabled"
    trace_session_id: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_trace_session(self) -> "AgentRuntimeProviderSourceV1":
        if (self.trace_mode == "live_record") != bool(self.trace_session_id):
            raise ValueError("acceptance_model_trace_invalid")
        return self


class AgentRuntimeAcceptanceReplaySourceV1(_AgentRuntimeTransportSourceBaseV1):
    source_kind: Literal["acceptance_replay"] = "acceptance_replay"
    trace_session_id: str = Field(min_length=1, max_length=160)
    expected_bundle_digest: str = Field(pattern=_DIGEST_PATTERN)


AgentRuntimeTransportSourceV1 = Annotated[
    AgentRuntimeProviderSourceV1 | AgentRuntimeAcceptanceReplaySourceV1,
    Field(discriminator="source_kind"),
]
