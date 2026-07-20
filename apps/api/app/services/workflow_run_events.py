from typing import Any


def node_run_id(result: dict[str, Any]) -> str | None:
    value = result.get("node_run_id")
    return str(value) if value not in (None, "") else None


def output_status_from_result(result: dict[str, Any]) -> str | None:
    output = result.get("output")
    if isinstance(output, dict):
        value = output.get("status") or output.get("composition_status")
        if value not in (None, ""):
            return str(value)
    value = result.get("status")
    return str(value) if value not in (None, "") else None


def waiting_reason_from_result(result: dict[str, Any]) -> str:
    output = result.get("output")
    if isinstance(output, dict):
        for key in ("waiting_reason", "status", "composition_status"):
            value = output.get(key)
            if value not in (None, ""):
                return str(value)
    return "waiting"


def has_active_output_from_result(result: dict[str, Any]) -> bool | None:
    value = result.get("has_active_output")
    if isinstance(value, bool):
        return value
    return None


class WorkflowRunEventRecorder:
    def __init__(self, executions: Any) -> None:
        self._executions = executions

    def record_node_started(
        self,
        workflow_id: str,
        execution_id: str | None,
        node_id: str,
    ) -> None:
        if not execution_id:
            return
        self._executions.update_node_status(
            workflow_id,
            execution_id,
            node_id,
            "queued",
        )
        self._executions.append_event(workflow_id, execution_id, "node_queued", node_id=node_id)
        self._executions.update_node_status(
            workflow_id,
            execution_id,
            node_id,
            "running",
        )
        self._executions.append_event(workflow_id, execution_id, "node_started", node_id=node_id)

    def record_node_completed(
        self,
        workflow_id: str,
        execution_id: str | None,
        node_id: str,
        *,
        result: dict[str, Any],
    ) -> None:
        if not execution_id:
            return
        self._executions.update_node_status(
            workflow_id,
            execution_id,
            node_id,
            "completed",
            node_run_id=node_run_id(result),
            output_status=output_status_from_result(result),
            has_active_output=has_active_output_from_result(result),
        )
        self._executions.append_event(
            workflow_id,
            execution_id,
            "node_completed",
            node_id=node_id,
            payload={
                "node_run_id": node_run_id(result),
                "output_status": output_status_from_result(result),
            },
        )

    def record_node_waiting(
        self,
        workflow_id: str,
        execution_id: str | None,
        node_id: str,
        *,
        result: dict[str, Any],
    ) -> None:
        if not execution_id:
            return
        waiting_reason = waiting_reason_from_result(result)
        self._executions.update_node_status(
            workflow_id,
            execution_id,
            node_id,
            "waiting",
            node_run_id=node_run_id(result),
            output_status=output_status_from_result(result),
            waiting_reason=waiting_reason,
            has_active_output=has_active_output_from_result(result),
        )
        self._executions.append_event(
            workflow_id,
            execution_id,
            "node_waiting",
            node_id=node_id,
            payload={
                "node_run_id": node_run_id(result),
                "output_status": output_status_from_result(result),
                "waiting_reason": waiting_reason,
            },
        )

    def record_node_failed(
        self,
        workflow_id: str,
        execution_id: str | None,
        node_id: str,
        *,
        error: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        if not execution_id:
            return
        payload = result or {}
        self._executions.update_node_status(
            workflow_id,
            execution_id,
            node_id,
            "failed",
            node_run_id=node_run_id(payload),
            output_status=output_status_from_result(payload),
            error=error,
            has_active_output=has_active_output_from_result(payload),
        )
        self._executions.append_event(
            workflow_id,
            execution_id,
            "node_failed",
            node_id=node_id,
            payload={"error": error, "node_run_id": node_run_id(payload)},
        )

    def record_node_blocked(
        self,
        workflow_id: str,
        execution_id: str | None,
        node_id: str,
        *,
        reason: str,
    ) -> None:
        if not execution_id:
            return
        self._executions.update_node_status(
            workflow_id,
            execution_id,
            node_id,
            "blocked",
            waiting_reason=reason,
            error=reason,
        )
        self._executions.append_event(
            workflow_id,
            execution_id,
            "node_blocked",
            node_id=node_id,
            payload={"blocked_reason": reason},
        )

    def record_node_skipped(
        self,
        workflow_id: str,
        execution_id: str | None,
        node_id: str,
        *,
        reason: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        if not execution_id:
            return
        payload = result or {}
        self._executions.update_node_status(
            workflow_id,
            execution_id,
            node_id,
            "skipped",
            skipped_reason=reason,
            node_run_id=node_run_id(payload),
            output_status=output_status_from_result(payload),
            has_active_output=has_active_output_from_result(payload),
        )
        self._executions.append_event(
            workflow_id,
            execution_id,
            "node_skipped",
            node_id=node_id,
            payload={"skipped_reason": reason},
        )
