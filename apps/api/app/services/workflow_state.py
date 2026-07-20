import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.schemas.ad_workflow import AdWorkflowResponse
from app.services.agent_trace import utc_now


class WorkflowStatePersistenceError(RuntimeError):
    """Raised when workflow state cannot be persisted."""


def persist_workflow_response_as_node_runs(
    workflow: AdWorkflowResponse,
    settings: Settings,
) -> None:
    for node in workflow.nodes:
        persist_node_run(
            workflow_id=workflow.workflow_id,
            node_id=node.id,
            node_type=node.id,
            status=_node_run_status(node.status),
            output=node.content,
            input_assets=node.input_assets,
            output_assets=node.output_assets,
            input_context={},
            error=None if node.status == "completed" else node.metadata.get("error"),
            source="ad-workflows/generate",
            data_dir=settings.media_data_dir,
        )


def persist_node_run(
    *,
    workflow_id: str,
    node_id: str,
    node_type: str,
    status: str,
    output: dict[str, Any],
    input_assets: list[dict[str, Any]],
    output_assets: list[dict[str, Any]],
    input_context: dict[str, Any],
    error: str | None,
    source: str,
    data_dir: Path,
) -> dict[str, Any]:
    node_run_id = f"nrun_{uuid4().hex[:12]}"
    relative_path = Path("runs") / workflow_id / "nodes" / node_id / f"{node_run_id}.json"
    node_dir = data_dir / "runs" / workflow_id / "nodes" / node_id
    node_dir.mkdir(parents=True, exist_ok=True)

    for existing_path in node_dir.glob("nrun_*.json"):
        payload = json.loads(existing_path.read_text(encoding="utf-8"))
        payload["active"] = False
        _write_json_atomic(existing_path, payload)

    now = utc_now().isoformat()
    payload = {
        "workflow_id": workflow_id,
        "node_id": node_id,
        "node_run_id": node_run_id,
        "node_type": node_type,
        "status": status,
        "output": output,
        "input_assets": input_assets,
        "output_assets": output_assets,
        "trace_path": relative_path.as_posix(),
        "metadata_path": relative_path.as_posix(),
        "error": error,
        "input_context": input_context,
        "override_prompt": None,
        "run_downstream": False,
        "started_at": now,
        "finished_at": now,
        "duration_ms": 0,
        "active": True,
        "source": source,
        "trace": {
            "source": source,
            "input_context": input_context,
            "input_assets": input_assets,
            "output": output,
            "output_assets": output_assets,
            "error": error,
        },
    }
    run_path = data_dir / relative_path
    _write_json_atomic(run_path, payload)
    _write_json_atomic(node_dir / "active.json", payload)
    return payload


def workflow_plan_path(data_dir: Path, workflow_id: str) -> Path:
    return data_dir / "runs" / workflow_id / "workflow-plan.json"


def planning_context_path(data_dir: Path, workflow_id: str) -> Path:
    return data_dir / "workflows" / workflow_id / "planning_context.json"


def save_workflow_plan(
    *,
    workflow: AdWorkflowResponse,
    ad_request: dict[str, Any],
    audio_mode: str,
    data_dir: Path,
) -> str:
    path = workflow_plan_path(data_dir, workflow.workflow_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "workflow_id": workflow.workflow_id,
        "workflow": workflow.model_dump(mode="json"),
        "ad_request": ad_request,
        "audio_mode": audio_mode,
        "status": "planned",
        "source": "ad-workflows/plan",
        "created_at": utc_now().isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path.relative_to(data_dir).as_posix()


def save_planning_context(
    *,
    workflow_id: str,
    planning_context: dict[str, Any],
    data_dir: Path,
) -> str:
    path = planning_context_path(data_dir, workflow_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(planning_context, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path.relative_to(data_dir).as_posix()


def load_workflow_plan(data_dir: Path, workflow_id: str) -> dict[str, Any] | None:
    path = workflow_plan_path(data_dir, workflow_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_active_node_results(data_dir: Path, workflow_id: str) -> dict[str, dict[str, Any]]:
    return load_active_node_results_by_id(data_dir, workflow_id)


def load_active_node_results_by_id(data_dir: Path, workflow_id: str) -> dict[str, dict[str, Any]]:
    nodes_dir = data_dir / "runs" / workflow_id / "nodes"
    active: dict[str, dict[str, Any]] = {}
    if not nodes_dir.exists():
        return active
    for active_path in nodes_dir.glob("*/active.json"):
        payload = json.loads(active_path.read_text(encoding="utf-8"))
        node_id = str(payload.get("node_id") or active_path.parent.name)
        node_type = str(payload.get("node_type") or node_id)
        payload["node_id"] = node_id
        payload["node_type"] = node_type
        active[node_id] = payload
    return active


def load_active_node_results_by_type(
    data_dir: Path, workflow_id: str
) -> dict[str, list[dict[str, Any]]]:
    active_by_type: dict[str, list[dict[str, Any]]] = {}
    for payload in load_active_node_results_by_id(data_dir, workflow_id).values():
        node_type = str(payload.get("node_type") or payload.get("node_id") or "")
        if not node_type:
            continue
        active_by_type.setdefault(node_type, []).append(payload)
    for payloads in active_by_type.values():
        payloads.sort(key=lambda item: str(item.get("node_id") or ""))
    return active_by_type


def resolve_active_result(
    data_dir: Path,
    workflow_id: str,
    node_id: str,
    node_type: str | None = None,
) -> dict[str, Any] | None:
    node_path = data_dir / "runs" / workflow_id / "nodes" / node_id / "active.json"
    if node_path.exists():
        return _load_active_payload(node_path, node_id=node_id, node_type=node_type)
    if node_type and node_type != node_id:
        legacy_path = data_dir / "runs" / workflow_id / "nodes" / node_type / "active.json"
        if legacy_path.exists():
            return _load_active_payload(legacy_path, node_id=node_id, node_type=node_type)
    return None


def _load_active_payload(
    path: Path,
    *,
    node_id: str,
    node_type: str | None,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("node_id", node_id)
    payload.setdefault("node_type", node_type or node_id)
    return payload


def _node_run_status(status: str) -> str:
    if status in {"completed", "failed"}:
        return status
    return "failed"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)
