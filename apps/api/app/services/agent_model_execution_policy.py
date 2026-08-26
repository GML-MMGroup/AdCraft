"""Resolve immutable Agent model transport policy from trusted metadata."""

from __future__ import annotations

from collections.abc import Mapping

from app.schemas.agent_operation_recovery import AgentOperationPolicyV2
from app.schemas.agent_runtime import AgentModelExecutionPolicyV1
from app.services.video_agent_operation_registry import (
    VideoAgentOperationRegistry,
    VideoAgentOperationRegistryError,
)


class AgentModelExecutionPolicyError(ValueError):
    """A selected model cannot satisfy one registered Agent operation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def resolve_agent_model_execution_policy(
    *,
    model_ref: str,
    operation_policy: AgentOperationPolicyV2,
    capability_metadata: Mapping[str, object],
) -> AgentModelExecutionPolicyV1:
    if not isinstance(operation_policy, AgentOperationPolicyV2):
        raise _mismatch("The Agent operation policy is invalid.")
    try:
        VideoAgentOperationRegistry().resolve(operation_policy.operation)
    except VideoAgentOperationRegistryError as error:
        raise _mismatch("The Agent operation has no registered model policy.") from error

    thinking_format = _enum(
        capability_metadata,
        "thinking_format",
        {"zai", "qwen", "none"},
    )
    reasoning_control = _enum(
        capability_metadata,
        "reasoning_control",
        {"provider_default", "enable_thinking", "reasoning_effort", "none"},
    )
    structured_transport = _enum(
        capability_metadata,
        "structured_transport",
        {
            "streamed_tool_call",
            "non_streaming_tool_call",
            "non_streaming_json_object",
            "streaming_json_object",
            "json_object",
        },
    )
    supports_tool_calls = _flag(capability_metadata, "supports_tool_calls")
    supports_streamed_tool_calls = _flag(
        capability_metadata,
        "supports_streamed_tool_calls",
    )
    supports_reasoning_controls = _flag(
        capability_metadata,
        "supports_reasoning_controls",
    )
    model_token_ceiling = _positive_int(
        capability_metadata,
        "default_max_output_tokens",
    )
    if structured_transport in {"streamed_tool_call", "non_streaming_tool_call"} and not (
        supports_tool_calls
    ):
        raise _mismatch("The selected structured transport requires tool calls.")
    if structured_transport == "streamed_tool_call" and not supports_streamed_tool_calls:
        raise _mismatch("The selected model does not support streamed tool calls.")
    if reasoning_control == "none" and thinking_format != "none":
        raise _mismatch("A disabled reasoning policy cannot select a thinking format.")
    if reasoning_control == "enable_thinking" and not supports_reasoning_controls:
        raise _mismatch("The selected model cannot honor the frozen reasoning policy.")
    if reasoning_control not in {"none", "enable_thinking"}:
        raise _mismatch("The selected model uses an unsupported reasoning control.")

    enable_thinking = (
        operation_policy.enable_thinking if reasoning_control == "enable_thinking" else False
    )
    thinking_budget_tokens = operation_policy.thinking_budget_tokens if enable_thinking else None
    reasoning_mode = operation_policy.reasoning_mode if enable_thinking else "low"

    return AgentModelExecutionPolicyV1(
        model_ref=model_ref,
        operation=operation_policy.operation,
        operation_class=operation_policy.policy_class,
        thinking_format=thinking_format,
        reasoning_control=reasoning_control,
        reasoning_mode=reasoning_mode,
        enable_thinking=enable_thinking,
        thinking_budget_tokens=thinking_budget_tokens,
        structured_transport=structured_transport,
        supports_tool_calls=supports_tool_calls,
        supports_streamed_tool_calls=supports_streamed_tool_calls,
        deadline_seconds=operation_policy.hard_deadline_seconds,
        primary_timeout_seconds=operation_policy.primary_timeout_seconds,
        recovery_timeout_seconds=operation_policy.recovery_timeout_seconds,
        persistence_reserve_seconds=operation_policy.persistence_reserve_seconds,
        max_model_submissions=operation_policy.max_model_submissions,
        recovery_mode=operation_policy.recovery_mode,
        max_output_tokens=min(operation_policy.max_output_tokens, model_token_ceiling),
        transport_retry_limit=operation_policy.transport_retry_limit,
        structured_repair_limit=operation_policy.structured_repair_limit,
    )


def _enum(
    metadata: Mapping[str, object],
    key: str,
    allowed: set[str],
) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or value not in allowed:
        raise _mismatch(f"Trusted model metadata has an invalid {key} value.")
    return value


def _flag(metadata: Mapping[str, object], key: str) -> bool:
    value = metadata.get(key)
    if not isinstance(value, bool):
        raise _mismatch(f"Trusted model metadata has an invalid {key} value.")
    return value


def _positive_int(metadata: Mapping[str, object], key: str) -> int:
    value = metadata.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _mismatch(f"Trusted model metadata has an invalid {key} value.")
    return value


def _mismatch(message: str) -> AgentModelExecutionPolicyError:
    return AgentModelExecutionPolicyError("agent_model_capability_mismatch", message)
