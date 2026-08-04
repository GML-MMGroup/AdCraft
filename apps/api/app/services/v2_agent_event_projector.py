"""Project private Pi events into bounded V2 audit entries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.schemas.agent_runtime import AgentRuntimeEvent
from app.services.agent_trace import V2AgentTraceWriter


_AUDITED_EVENTS = {
    "run_started",
    "tool_call",
    "tool_result",
    "run_completed",
    "run_failed",
    "run_cancelled",
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
        return {"error_code": payload.get("code")}
    return {"status": event.event_type.removeprefix("run_")}
