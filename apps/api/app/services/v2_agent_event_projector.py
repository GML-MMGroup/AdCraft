"""Project private Pi events into bounded V2 audit entries."""

from __future__ import annotations

from math import isfinite
from pathlib import Path
from typing import Any

from app.schemas.agent_runtime import AgentRuntimeEvent
from app.services.agent_trace import V2AgentTraceWriter
from app.services.agent_structured_validation_audit import (
    safe_structured_validation_attempts,
)


_AUDITED_EVENTS = {
    "run_started",
    "tool_call",
    "tool_result",
    "run_completed",
    "run_failed",
    "run_cancelled",
}
_TRANSPORT_AUDIT_KEYS = (
    "provider",
    "model_ref",
    "structured_transport",
    "thinking_format",
    "reasoning_control",
    "reasoning_mode",
    "reasoning_effort",
    "enable_thinking",
    "thinking_budget_tokens",
    "deadline_seconds",
    "max_output_tokens",
    "operation_policy_id",
    "operation_class",
    "effective_timeout_ms",
    "request_bytes",
    "schema_bytes",
    "attempt_stage",
    "started_at",
    "first_response_at",
    "last_activity_at",
    "finished_at",
    "duration_ms",
    "finish_reason",
    "provider_trace_id",
    "safe_exception_class",
    "safe_error_code",
    "http_status",
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "response_activity_observed",
    "transport_retry_count",
    "capability_fallback_count",
    "structured_attempt_count",
    "failure_boundary",
    "model_submission_count",
    "operation",
    "retryable",
    "terminal_code",
    "agent_name",
    "context_contract_name",
    "projection_id",
)
_BOOLEAN_AUDIT_KEYS = {
    "enable_thinking",
    "response_activity_observed",
    "retryable",
}
_NUMERIC_AUDIT_KEYS = {
    "deadline_seconds",
    "duration_ms",
    "effective_timeout_ms",
    "http_status",
    "input_tokens",
    "max_output_tokens",
    "model_submission_count",
    "output_tokens",
    "reasoning_tokens",
    "request_bytes",
    "schema_bytes",
    "structured_attempt_count",
    "thinking_budget_tokens",
    "transport_retry_count",
    "capability_fallback_count",
}
_AUDIT_TEXT_LIMITS = {
    "agent_name": 80,
    "attempt_stage": 80,
    "context_contract_name": 160,
    "failure_boundary": 80,
    "finish_reason": 160,
    "finished_at": 64,
    "first_response_at": 64,
    "last_activity_at": 64,
    "model_ref": 320,
    "operation": 120,
    "operation_class": 80,
    "operation_policy_id": 160,
    "projection_id": 160,
    "provider": 160,
    "provider_trace_id": 320,
    "reasoning_control": 80,
    "reasoning_effort": 80,
    "reasoning_mode": 80,
    "safe_error_code": 120,
    "safe_exception_class": 160,
    "started_at": 64,
    "structured_transport": 80,
    "terminal_code": 120,
    "thinking_format": 80,
}


class V2AgentEventProjector:
    """Persist coarse Agent audit without publishing token or reasoning events."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def consume(
        self,
        event: AgentRuntimeEvent,
        *,
        workflow_id: str | None,
        model_id: str | None = None,
    ) -> bool:
        if not workflow_id or event.event_type not in _AUDITED_EVENTS:
            return False
        output = _coarse_payload(event)
        is_error = event.event_type in {"run_failed", "run_cancelled"}
        V2AgentTraceWriter(self._data_dir, workflow_id).append(
            agent=event.agent_name,
            model=model_id,
            prompt="",
            output=output,
            error=str(output.get("error_code") or "") or None if is_error else None,
            started_at=event.created_at,
            finished_at=event.created_at,
            duration_ms=0,
            metadata={
                "trace_role": "agent_runtime_error" if is_error else "agent_runtime",
                "agent_run_id": event.run_id,
                "agent_event_seq": event.seq,
                "agent_event_type": event.event_type,
            },
        )
        return True


def _coarse_payload(event: AgentRuntimeEvent) -> dict[str, Any]:
    payload = event.payload
    if event.event_type in {"tool_call", "tool_result"}:
        return {
            "tool_name": payload.get("tool_name"),
            "tool_call_id": payload.get("tool_call_id"),
            "status": payload.get("status"),
            "error_code": payload.get("error_code"),
        }
    if event.event_type in {"run_failed", "run_cancelled"}:
        output: dict[str, Any] = {"error_code": payload.get("code")}
    else:
        output = {"status": event.event_type.removeprefix("run_")}
    audit = safe_agent_transport_audit(payload.get("audit"))
    if audit:
        output["audit"] = audit
    return output


def safe_agent_transport_audit(candidate: Any) -> dict[str, Any]:
    """Return only bounded scalar transport evidence and typed validation audits."""

    if not isinstance(candidate, dict):
        return {}
    safe: dict[str, Any] = {}
    for key in _TRANSPORT_AUDIT_KEYS:
        if key not in candidate:
            continue
        value = _bounded_audit_value(key, candidate[key])
        if value is not _UNSAFE:
            safe[key] = value
    validation_attempts = safe_structured_validation_attempts(
        candidate.get("structured_validation_attempts")
    )
    if validation_attempts:
        safe["structured_validation_attempts"] = validation_attempts
    return safe


_UNSAFE = object()


def _bounded_audit_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in _BOOLEAN_AUDIT_KEYS:
        return value if isinstance(value, bool) else _UNSAFE
    if key in _NUMERIC_AUDIT_KEYS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return _UNSAFE
        if not isfinite(value) or value < 0 or value > 9_007_199_254_740_991:
            return _UNSAFE
        return value
    limit = _AUDIT_TEXT_LIMITS.get(key)
    if limit is None or not isinstance(value, str):
        return _UNSAFE
    return value[:limit]
