import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.schemas.workflow_executions import (
    WorkflowExecutionEvent,
    WorkflowExecutionState,
    WorkflowExecutionStatus,
    WorkflowNodeExecutionState,
    WorkflowNodeExecutionStatus,
)
from app.services.canvas_runtime_events import CanvasRuntimeEventService
from app.services.agent_trace import utc_now


TERMINAL_EXECUTION_STATUSES = {"completed", "partial_failed", "failed", "cancelled"}
ACTIVE_BLOCKING_EXECUTION_STATUSES = {"queued", "running"}


class WorkflowExecutionError(ValueError):
    code = "workflow_execution_invalid_state"
    status_code = 422


class WorkflowExecutionNotFoundError(WorkflowExecutionError):
    code = "workflow_execution_not_found"
    status_code = 404


class WorkflowExecutionAlreadyRunningError(WorkflowExecutionError):
    code = "workflow_execution_already_running"
    status_code = 409


class WorkflowExecutionService:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._canvas_events = CanvasRuntimeEventService(data_dir)

    def create_execution(
        self,
        workflow_id: str,
        request: Any,
        *,
        selected_node_ids: list[str],
        frontier_node_id: str,
        graph_nodes: list[Any],
        mode: str | None = None,
    ) -> WorkflowExecutionState:
        active = self.load_active_execution(workflow_id)
        if active is not None and active.status in ACTIVE_BLOCKING_EXECUTION_STATUSES:
            raise WorkflowExecutionAlreadyRunningError(
                f"Workflow execution already running: {active.execution_id}"
            )
        if active is not None:
            self.clear_active_execution(workflow_id, active.execution_id)

        execution_id = f"exec_{uuid4().hex[:12]}"
        mode = mode or str(getattr(request, "mode", "") or "run_from_frontier")
        selected = set(selected_node_ids)
        first_queued_node_id = selected_node_ids[0] if selected_node_ids else None
        nodes: dict[str, WorkflowNodeExecutionState] = {}
        for raw_node in graph_nodes:
            node_id = _node_value(raw_node, "id") or _node_value(raw_node, "node_id")
            if not node_id:
                continue
            node_type = _node_value(raw_node, "node_type") or node_id
            is_selected = node_id in selected
            nodes[node_id] = WorkflowNodeExecutionState(
                node_id=node_id,
                node_type=node_type,
                selected=is_selected,
                status="queued"
                if is_selected and node_id == first_queued_node_id
                else "pending"
                if is_selected
                else "skipped",
                skipped_reason=None if is_selected else "not_selected",
            )

        for node_id in selected_node_ids:
            if node_id not in nodes:
                nodes[node_id] = WorkflowNodeExecutionState(
                    node_id=node_id,
                    node_type=node_id,
                    selected=True,
                    status="queued" if node_id == first_queued_node_id else "pending",
                )

        state = WorkflowExecutionState(
            workflow_id=workflow_id,
            execution_id=execution_id,
            request=request.model_dump(mode="json") if hasattr(request, "model_dump") else {},
            mode=mode,
            status="queued",
            frontier_node_id=frontier_node_id,
            selected_node_ids=selected_node_ids,
            nodes=nodes,
        )
        state = _refresh_state_indexes(state)
        self._write_state(state)
        self._write_active_execution(workflow_id, execution_id)
        self.append_event(
            workflow_id,
            execution_id,
            "execution_queued",
            payload={
                "mode": mode,
                "frontier_node_id": frontier_node_id,
                "selected_node_ids": selected_node_ids,
            },
        )
        self._canvas_events.append_event(
            workflow_id,
            "canvas_runtime_snapshot_updated",
            execution_id=execution_id,
            resource_type="execution",
            resource_id=execution_id,
            payload={
                "status": "queued",
                "mode": mode,
                "frontier_node_id": frontier_node_id,
                "selected_node_ids": selected_node_ids,
            },
        )
        return self.load_execution(workflow_id, execution_id)

    def load_execution(self, workflow_id: str, execution_id: str) -> WorkflowExecutionState:
        path = self._state_path(workflow_id, execution_id)
        if not path.exists():
            raise WorkflowExecutionNotFoundError(
                f"workflow execution not found: {workflow_id}/{execution_id}"
            )
        return _refresh_state_indexes(
            WorkflowExecutionState.model_validate_json(path.read_text(encoding="utf-8"))
        )

    def load_active_execution(self, workflow_id: str) -> WorkflowExecutionState | None:
        path = self._active_path(workflow_id)
        if not path.exists():
            return None
        try:
            active = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        execution_id = active.get("execution_id")
        if not isinstance(execution_id, str) or not execution_id:
            return None
        try:
            return self.load_execution(workflow_id, execution_id)
        except WorkflowExecutionNotFoundError:
            return None

    def update_execution(
        self,
        workflow_id: str,
        execution_id: str,
        **fields: Any,
    ) -> WorkflowExecutionState:
        state = self.load_execution(workflow_id, execution_id)
        state = state.model_copy(update=fields)
        state = _refresh_state_indexes(state)
        self._write_state(state)
        return state

    def update_node_status(
        self,
        workflow_id: str,
        execution_id: str,
        node_id: str,
        status: WorkflowNodeExecutionStatus,
        **fields: Any,
    ) -> WorkflowExecutionState:
        state = self.load_execution(workflow_id, execution_id)
        node = state.nodes.get(node_id)
        previous_status = node.status if node is not None else None
        if node is None:
            node = WorkflowNodeExecutionState(
                node_id=node_id,
                node_type=str(fields.pop("node_type", None) or node_id),
                selected=node_id in state.selected_node_ids,
            )
        updates: dict[str, Any] = {"status": status}
        updates.update(fields)
        if status == "running" and not updates.get("started_at"):
            updates["started_at"] = utc_now().isoformat()
        if status in {
            "blocked",
            "completed",
            "failed",
            "skipped",
            "waiting",
            "cancelled",
        } and not updates.get("finished_at"):
            updates["finished_at"] = utc_now().isoformat()
        if status != "waiting" and "waiting_reason" not in updates:
            updates["waiting_reason"] = None
        if status != "failed" and "error" not in updates:
            updates["error"] = None
        state.nodes[node_id] = node.model_copy(update=updates)
        state = _refresh_state_indexes(state)
        self._write_state(state)
        updated_node = state.nodes[node_id]
        self._canvas_events.append_node_status_changed(
            workflow_id,
            execution_id=execution_id,
            node_id=node_id,
            node_type=updated_node.node_type,
            status=updated_node.status,
            previous_status=previous_status,
            error=updated_node.error,
            error_code=_metadata_string(updated_node.metadata, "error_code"),
            waiting_reason=updated_node.waiting_reason,
            started_at=updated_node.started_at,
            finished_at=updated_node.finished_at,
            node_run_id=updated_node.node_run_id,
            output_status=updated_node.output_status,
            has_active_output=updated_node.has_active_output,
        )
        return state

    def append_event(
        self,
        workflow_id: str,
        execution_id: str,
        event_type: str,
        *,
        node_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> WorkflowExecutionEvent:
        state = self.load_execution(workflow_id, execution_id)
        node_type = state.nodes[node_id].node_type if node_id in state.nodes else None
        event = WorkflowExecutionEvent(
            seq=self._next_event_seq(workflow_id, execution_id),
            event_type=event_type,
            workflow_id=workflow_id,
            execution_id=execution_id,
            node_id=node_id,
            node_type=node_type,
            created_at=utc_now().isoformat(),
            payload=payload or {},
        )
        path = self._events_path(workflow_id, execution_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n")
        if event_type in {
            "execution_started",
            "execution_completed",
            "execution_partial_failed",
            "execution_failed",
            "execution_cancelled",
        }:
            self._canvas_events.append_event(
                workflow_id,
                event_type,
                execution_id=execution_id,
                node_id=node_id,
                node_type=node_type,
                resource_type="execution",
                resource_id=execution_id,
                payload=payload or {},
            )
        return event

    def list_events(
        self,
        workflow_id: str,
        execution_id: str,
        *,
        after_seq: int = 0,
    ) -> list[WorkflowExecutionEvent]:
        self.load_execution(workflow_id, execution_id)
        path = self._events_path(workflow_id, execution_id)
        if not path.exists():
            return []
        events: list[WorkflowExecutionEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = WorkflowExecutionEvent.model_validate_json(line)
            if event.seq > after_seq:
                events.append(event)
        return events

    def finish_execution(
        self,
        workflow_id: str,
        execution_id: str,
        status: WorkflowExecutionStatus,
        *,
        final_result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> WorkflowExecutionState:
        state = self.update_execution(
            workflow_id,
            execution_id,
            status=status,
            final_result=final_result,
            error=error,
            finished_at=utc_now().isoformat(),
        )
        event_type = {
            "completed": "execution_completed",
            "partial_failed": "execution_partial_failed",
            "failed": "execution_failed",
            "cancelled": "execution_cancelled",
            "waiting": "execution_waiting",
        }.get(status)
        if event_type:
            self.append_event(
                workflow_id,
                execution_id,
                event_type,
                payload={"status": status, "error": error} if error else {"status": status},
            )
        return state

    def clear_active_execution(self, workflow_id: str, execution_id: str) -> None:
        path = self._active_path(workflow_id)
        if not path.exists():
            return
        try:
            active = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            active = {}
        if active.get("execution_id") == execution_id:
            path.unlink()

    def _write_active_execution(self, workflow_id: str, execution_id: str) -> None:
        path = self._active_path(workflow_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(path, {"workflow_id": workflow_id, "execution_id": execution_id})

    def _write_state(self, state: WorkflowExecutionState) -> None:
        path = self._state_path(state.workflow_id, state.execution_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(path, state.model_dump(mode="json"))

    def _next_event_seq(self, workflow_id: str, execution_id: str) -> int:
        path = self._events_path(workflow_id, execution_id)
        if not path.exists():
            return 1
        seq = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw_seq = payload.get("seq")
            if isinstance(raw_seq, int):
                seq = max(seq, raw_seq)
        return seq + 1

    def _execution_dir(self, workflow_id: str, execution_id: str) -> Path:
        return self._data_dir / "runs" / workflow_id / "executions" / execution_id

    def _state_path(self, workflow_id: str, execution_id: str) -> Path:
        return self._execution_dir(workflow_id, execution_id) / "state.json"

    def _events_path(self, workflow_id: str, execution_id: str) -> Path:
        return self._execution_dir(workflow_id, execution_id) / "events.ndjson"

    def _active_path(self, workflow_id: str) -> Path:
        return self._data_dir / "runs" / workflow_id / "executions" / "active.json"


def _refresh_state_indexes(state: WorkflowExecutionState) -> WorkflowExecutionState:
    status_map = {
        "queued": "queued_node_ids",
        "running": "running_node_ids",
        "waiting": "waiting_node_ids",
        "completed": "completed_node_ids",
        "failed": "failed_node_ids",
        "skipped": "skipped_node_ids",
    }
    updates: dict[str, list[str]] = {field: [] for field in status_map.values()}
    for node_id, node in state.nodes.items():
        field = status_map.get(node.status)
        if field is not None:
            updates[field].append(node_id)
    return state.model_copy(update=updates)


def _node_value(raw_node: Any, field: str) -> str | None:
    if isinstance(raw_node, dict):
        value = raw_node.get(field)
    else:
        value = getattr(raw_node, field, None)
    return str(value) if value not in (None, "") else None


def _metadata_string(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return str(value) if value not in (None, "") else None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)
