import json
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4

from app.services.agent_trace import utc_now
from app.services.v2_data_boundary import validate_v2_data_path
from app.services.v2_workflow_store import workflow_v2_runtime_dir

TERMINAL_EXECUTION_STATUSES = {"completed", "partial_failed", "failed", "cancelled"}
_LOCK = threading.RLock()


def new_execution_id() -> str:
    return f"exec_{uuid4().hex[:16]}"


def execution_state_path(data_dir: Path, workflow_id: str, execution_id: str) -> Path:
    return validate_v2_data_path(
        data_dir,
        workflow_v2_runtime_dir(data_dir, workflow_id) / "executions" / execution_id / "state.json",
        operation="v2-execution-state-path",
    )


def active_execution_path(data_dir: Path, workflow_id: str) -> Path:
    return validate_v2_data_path(
        data_dir,
        workflow_v2_runtime_dir(data_dir, workflow_id) / "executions" / "active.json",
        operation="v2-active-execution-path",
    )


def is_terminal_execution(status: str | None) -> bool:
    return status in TERMINAL_EXECUTION_STATUSES


def load_execution_state(
    data_dir: Path,
    workflow_id: str,
    execution_id: str,
) -> dict[str, Any] | None:
    path = execution_state_path(data_dir, workflow_id, execution_id)
    with _LOCK:
        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            return None
        return json.loads(content)


def save_execution_state(
    data_dir: Path,
    workflow_id: str,
    execution_id: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    with _LOCK:
        path = execution_state_path(data_dir, workflow_id, execution_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**state, "updated_at": utc_now().isoformat()}
        tmp_path = path.with_name(f"{path.stem}.{uuid4().hex}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)
        return payload


def load_active_execution(
    data_dir: Path,
    workflow_id: str,
    *,
    include_terminal: bool = False,
) -> dict[str, Any] | None:
    path = active_execution_path(data_dir, workflow_id)
    with _LOCK:
        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            return None
        pointer = json.loads(content)
        execution_id = pointer.get("execution_id")
        if not isinstance(execution_id, str) or not execution_id:
            return None
        state = load_execution_state(data_dir, workflow_id, execution_id)
        if state is None:
            return None
        if is_terminal_execution(str(state.get("status"))) and not include_terminal:
            return None
        return state


def save_active_execution(data_dir: Path, workflow_id: str, execution_id: str) -> None:
    path = active_execution_path(data_dir, workflow_id)
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "workflow_id": workflow_id,
            "execution_id": execution_id,
            "updated_at": utc_now().isoformat(),
        }
        tmp_path = path.with_name(f"{path.stem}.{uuid4().hex}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)


def clear_active_execution(
    data_dir: Path,
    workflow_id: str,
    *,
    execution_id: str | None = None,
) -> None:
    path = active_execution_path(data_dir, workflow_id)
    with _LOCK:
        if not path.exists():
            return
        if execution_id is not None:
            try:
                pointer = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pointer = {}
            if pointer.get("execution_id") != execution_id:
                return
        path.unlink(missing_ok=True)
