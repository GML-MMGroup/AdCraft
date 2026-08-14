"""Project private Pi events into bounded V2 audit entries."""

from __future__ import annotations

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
    "deadline_seconds",
    "max_output_tokens",
    "operation_policy_id",
    "operation_class",
    "effective_timeout_ms",
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
    "structured_attempt_count",
)


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
    audit = _safe_transport_audit(payload.get("audit"))
    if audit:
        output["audit"] = audit
    return output


def _safe_transport_audit(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return {}
    safe = {
        key: value
        for key in _TRANSPORT_AUDIT_KEYS
        if (value := candidate.get(key)) is None or isinstance(value, (str, int, float, bool))
        if key in candidate
    }
    validation_attempts = safe_structured_validation_attempts(
        candidate.get("structured_validation_attempts")
    )
    if validation_attempts:
        safe["structured_validation_attempts"] = validation_attempts
    return safe
