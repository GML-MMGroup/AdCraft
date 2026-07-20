import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services.agent_trace import utc_now
from app.services.v2_data_boundary import validate_v2_data_path
from app.services.v2_execution_state import (
    clear_active_execution,
    load_active_execution,
    load_execution_state,
    new_execution_id,
    save_active_execution,
    save_execution_state,
)
from app.services.v2_workflow_store import workflow_v2_runtime_dir

TERMINAL_EXECUTION_STATUSES = {"completed", "partial_failed", "failed", "cancelled"}
SLOT_RUNTIME_ARRAY_FIELDS = {
    "running": "running_slot_ids",
    "waiting": "waiting_slot_ids",
    "completed": "completed_slot_ids",
    "failed": "failed_slot_ids",
    "blocked": "blocked_slot_ids",
    "skipped": "skipped_slot_ids",
}


class V2ExecutionService:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def new_execution_id(self) -> str:
        return new_execution_id()

    def load_state(self, workflow_id: str, execution_id: str) -> dict[str, Any] | None:
        return load_execution_state(self._data_dir, workflow_id, execution_id)

    def save_state(
        self,
        workflow_id: str,
        execution_id: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        return save_execution_state(self._data_dir, workflow_id, execution_id, state)

    def load_active(
        self,
        workflow_id: str,
        *,
        include_terminal: bool = False,
    ) -> dict[str, Any] | None:
        return load_active_execution(
            self._data_dir,
            workflow_id,
            include_terminal=include_terminal,
        )

    def load_latest_terminal(self, workflow_id: str) -> dict[str, Any] | None:
        executions_dir = workflow_v2_runtime_dir(self._data_dir, workflow_id) / "executions"
        if not executions_dir.exists():
            return None
        candidates: list[dict[str, Any]] = []
        for path in executions_dir.glob("*/state.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if payload.get("status") in TERMINAL_EXECUTION_STATUSES:
                candidates.append(payload)
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda payload: str(payload.get("finished_at") or payload.get("updated_at") or ""),
        )

    def set_active(self, workflow_id: str, execution_id: str) -> None:
        save_active_execution(self._data_dir, workflow_id, execution_id)

    def clear_active(self, workflow_id: str, *, execution_id: str | None = None) -> None:
        clear_active_execution(self._data_dir, workflow_id, execution_id=execution_id)

    def finish(
        self,
        workflow_id: str,
        execution_id: str,
        *,
        status: str,
        completed_slot_ids: list[str] | None = None,
        failed_slot_ids: list[str] | None = None,
        waiting_slot_ids: list[str] | None = None,
        running_slot_ids: list[str] | None = None,
        state_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = self.load_state(workflow_id, execution_id) or {
            "workflow_id": workflow_id,
            "execution_id": execution_id,
        }
        merged_state = {
            **current,
            **(state_updates or {}),
            "status": status,
            "running_slot_ids": list(running_slot_ids or []),
            "waiting_slot_ids": list(waiting_slot_ids or []),
            "completed_slot_ids": list(completed_slot_ids or []),
            "failed_slot_ids": list(failed_slot_ids or []),
            "finished_at": None
            if status == "waiting"
            else (current.get("finished_at") or utc_now().isoformat()),
        }
        if isinstance(merged_state.get("slot_runtime"), dict):
            merged_state.update(_slot_id_arrays_from_runtime(merged_state["slot_runtime"]))
        finished = self.save_state(
            workflow_id,
            execution_id,
            merged_state,
        )
        if status in TERMINAL_EXECUTION_STATUSES:
            self.clear_active(workflow_id, execution_id=execution_id)
        return finished

    def update_slot_runtime(
        self,
        workflow_id: str,
        execution_id: str,
        slot_runtime: dict[str, Any],
        *,
        events_cursor: int | None = None,
    ) -> dict[str, Any]:
        current = self.load_state(workflow_id, execution_id) or {
            "workflow_id": workflow_id,
            "execution_id": execution_id,
        }
        slot_id = str(slot_runtime.get("slot_id") or "")
        if not slot_id:
            return current
        runtime_entries = {
            str(existing_slot_id): dict(runtime)
            for existing_slot_id, runtime in dict(current.get("slot_runtime") or {}).items()
            if isinstance(runtime, dict)
        }
        merged_runtime = {
            **runtime_entries.get(slot_id, {}),
            **slot_runtime,
            "slot_id": slot_id,
            "execution_id": execution_id,
        }
        if merged_runtime.get("status") in {"completed", "failed", "skipped"}:
            merged_runtime.pop("waiting_reason", None)
        if merged_runtime.get("status") and not merged_runtime.get("runtime_status"):
            merged_runtime["runtime_status"] = merged_runtime["status"]
        runtime_entries[slot_id] = merged_runtime
        next_events_cursor = _max_int(current.get("events_cursor"), events_cursor)
        updated_state = {
            **current,
            "slot_runtime": runtime_entries,
            "events_cursor": next_events_cursor,
        }
        updated_state.update(_slot_id_arrays_from_runtime(runtime_entries))
        return self.save_state(workflow_id, execution_id, updated_state)

    def write_record(
        self,
        workflow_id: str,
        *,
        mode: str,
        status: str,
        completed_slot_ids: list[str] | None = None,
        failed_slot_ids: list[str] | None = None,
        waiting_slot_ids: list[str] | None = None,
        running_slot_ids: list[str] | None = None,
        slot_transitions: list[dict[str, Any]] | None = None,
        events_cursor: int = 0,
        source_execution_id: str | None = None,
    ) -> None:
        now = utc_now().isoformat()
        path = (
            workflow_v2_runtime_dir(self._data_dir, workflow_id)
            / "executions"
            / f"exec_{uuid4().hex}.json"
        )
        validate_v2_data_path(self._data_dir, path, operation="v2-execution-record-write")
        path.parent.mkdir(parents=True, exist_ok=True)
        summary_id = path.stem
        payload = {
            "record_type": "execution_summary",
            "summary_id": summary_id,
            "execution_id": summary_id,
            "workflow_id": workflow_id,
            "mode": mode,
            "status": status,
            "started_at": now,
            "finished_at": utc_now().isoformat(),
            "running_slot_ids": list(running_slot_ids or []),
            "completed_slot_ids": list(completed_slot_ids or []),
            "failed_slot_ids": list(failed_slot_ids or []),
            "waiting_slot_ids": list(waiting_slot_ids or []),
            "events_cursor": events_cursor,
            "slot_transitions": list(slot_transitions or []),
        }
        if source_execution_id:
            payload["source_execution_id"] = source_execution_id
        tmp_path = path.with_name(f"{path.stem}.{uuid4().hex}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)


def _slot_id_arrays_from_runtime(
    slot_runtime: dict[str, Any],
) -> dict[str, list[str]]:
    arrays: dict[str, list[str]] = {field: [] for field in SLOT_RUNTIME_ARRAY_FIELDS.values()}
    for slot_id, runtime in slot_runtime.items():
        if not isinstance(runtime, dict):
            continue
        status = str(runtime.get("status") or runtime.get("runtime_status") or "")
        field = SLOT_RUNTIME_ARRAY_FIELDS.get(status)
        if field is None:
            continue
        arrays[field].append(str(slot_id))
    return {field: list(dict.fromkeys(slot_ids)) for field, slot_ids in arrays.items()}


def _max_int(left: Any, right: Any) -> int:
    values: list[int] = []
    for value in (left, right):
        try:
            values.append(int(value))
        except (TypeError, ValueError):
            continue
    return max(values) if values else 0
