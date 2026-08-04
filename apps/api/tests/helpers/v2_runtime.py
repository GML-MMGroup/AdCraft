import json
from pathlib import Path
from threading import Event
from typing import Any

from fastapi.testclient import TestClient


_SETTLED_EXECUTION_STATUSES = {
    "waiting",
    "completed",
    "partial_failed",
    "failed",
    "cancelled",
}


def wait_for_v2_execution_state(
    data_dir: Path,
    workflow_id: str,
    execution_id: str,
    *,
    attempts: int = 2_000,
) -> dict[str, Any]:
    state_path = data_dir / "v2" / "runs" / workflow_id / "executions" / execution_id / "state.json"
    last_state: dict[str, Any] | None = None
    poll_interval = Event()
    for _ in range(attempts):
        if state_path.exists():
            last_state = json.loads(state_path.read_text(encoding="utf-8"))
            if str(last_state.get("status") or "") in _SETTLED_EXECUTION_STATUSES:
                return last_state
        poll_interval.wait(0.05)
    raise AssertionError(
        f"execution {execution_id} did not settle after {attempts} observations: {last_state}"
    )


def wait_for_v2_execution_terminal(
    client: TestClient,
    data_dir: Path,
    workflow_id: str,
    execution_id: str,
    *,
    attempts: int = 2_000,
) -> dict[str, Any]:
    wait_for_v2_execution_state(
        data_dir,
        workflow_id,
        execution_id,
        attempts=attempts,
    )
    response = client.get(f"/api/v2/workflows/{workflow_id}/runtime")
    assert response.status_code == 200, response.json()
    return response.json()


def run_v2_workflow_until_settled(
    client: TestClient,
    data_dir: Path,
    workflow_id: str,
) -> dict[str, Any]:
    response = client.post(f"/api/v2/workflows/{workflow_id}/run?wait=true")
    assert response.status_code == 200, response.json()
    payload = response.json()
    if "workflow" in payload:
        return payload

    runtime = wait_for_v2_execution_terminal(
        client,
        data_dir,
        workflow_id,
        str(payload["execution_id"]),
    )
    workflow_response = client.get(f"/api/v2/workflows/{workflow_id}")
    assert workflow_response.status_code == 200, workflow_response.json()
    return {
        **payload,
        "status": runtime["execution_status"],
        "workflow": workflow_response.json(),
        "runtime": runtime,
    }
