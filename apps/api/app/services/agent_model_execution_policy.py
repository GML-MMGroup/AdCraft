"""Resolve immutable Agent model transport policy from trusted metadata."""

from __future__ import annotations

from collections.abc import Mapping

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


_LONG_FORM_OPERATIONS = frozenset(
    {
        "execute_canvas_script",
        "script_writer",
        "script_edit_normalization",
        "storyboard_prompt",
        "storyboard_detail",
    }
)


def resolve_agent_model_execution_policy(
    *,
    model_ref: str,
    operation: str,
    capability_metadata: Mapping[str, object],
) -> AgentModelExecutionPolicyV1:
    try:
        VideoAgentOperationRegistry().resolve(operation)
    except VideoAgentOperationRegistryError as error:
        raise _mismatch("The Agent operation has no registered model policy.") from error

    operation_class, deadline_seconds, token_ceiling = _operation_budget(operation)
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
        {"streamed_tool_call", "non_streaming_tool_call", "json_object"},
    )
    supports_tool_calls = _flag(capability_metadata, "supports_tool_calls")
    supports_streamed_tool_calls = _flag(
        capability_metadata,
        "supports_streamed_tool_calls",
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

    return AgentModelExecutionPolicyV1(
        model_ref=model_ref,
        operation=operation,
        operation_class=operation_class,
        thinking_format=thinking_format,
        reasoning_control=reasoning_control,
        structured_transport=structured_transport,
        supports_tool_calls=supports_tool_calls,
        supports_streamed_tool_calls=supports_streamed_tool_calls,
        deadline_seconds=deadline_seconds,
        max_output_tokens=min(token_ceiling, model_token_ceiling),
        transport_retry_limit=1,
        structured_repair_limit=1,
    )


def _operation_budget(operation: str) -> tuple[str, int, int]:
    if operation.startswith(("propose_", "revise_")) and operation.endswith("_options"):
        return "proposal", 300, 3_072
    if operation in _LONG_FORM_OPERATIONS:
        return "long_form", 600, 8_192
    return "routing", 120, 1_024


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
