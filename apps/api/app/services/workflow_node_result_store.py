import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.schemas.workflow_nodes import WorkflowNodeRunRequest, WorkflowNodeRunResponse
from app.services.media_paths import with_public_urls
from app.services.output_assets import dedupe_output_assets
from app.services.workflow_asset_history import persist_node_asset_history
from app.services.workflow_state import resolve_active_result


class WorkflowNodeResultStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get_active_result(
        self,
        workflow_id: str,
        node_id: str,
        node_type: str,
    ) -> WorkflowNodeRunResponse | None:
        payload = resolve_active_result(
            self._settings.media_data_dir,
            workflow_id,
            node_id,
            node_type,
        )
        if payload is None:
            return None
        result = WorkflowNodeRunResponse.model_validate(payload)
        result.output_assets = with_public_urls(dedupe_output_assets(result.output_assets))
        return result

    def list_results(self, workflow_id: str) -> list[WorkflowNodeRunResponse]:
        nodes_dir = self._settings.media_data_dir / "runs" / workflow_id / "nodes"
        if not nodes_dir.exists():
            return []
        results = []
        for run_path in sorted(nodes_dir.glob("*/*.json")):
            if run_path.name == "active.json":
                continue
            result = WorkflowNodeRunResponse.model_validate_json(
                run_path.read_text(encoding="utf-8")
            )
            result.output_assets = with_public_urls(dedupe_output_assets(result.output_assets))
            results.append(result)
        return results

    def save_result(
        self,
        result: WorkflowNodeRunResponse,
        request: WorkflowNodeRunRequest,
        started_at: str,
        finished_at: str,
        duration_ms: int,
        *,
        active: bool = True,
    ) -> str:
        node_dir = (
            self._settings.media_data_dir / "runs" / result.workflow_id / "nodes" / result.node_id
        )
        node_dir.mkdir(parents=True, exist_ok=True)
        if active:
            for existing_path in node_dir.glob("nrun_*.json"):
                payload = json.loads(existing_path.read_text(encoding="utf-8"))
                payload["active"] = False
                write_json_atomic(existing_path, payload)
        relative_path = (
            Path("runs")
            / result.workflow_id
            / "nodes"
            / result.node_id
            / f"{result.node_run_id}.json"
        )
        result.trace_path = relative_path.as_posix()
        result.metadata_path = relative_path.as_posix()
        self.write_payload(
            result,
            request,
            started_at,
            finished_at,
            duration_ms,
            active=active,
            path=relative_path,
        )
        if active and result.status == "completed" and result.output_assets:
            persist_node_asset_history(
                data_dir=self._settings.media_data_dir,
                workflow_id=result.workflow_id,
                node_id=result.node_id,
                run_id=result.node_run_id,
                output_assets=result.output_assets,
            )
        return relative_path.as_posix()

    def write_payload(
        self,
        result: WorkflowNodeRunResponse,
        request: WorkflowNodeRunRequest,
        started_at: str,
        finished_at: str,
        duration_ms: int,
        *,
        active: bool,
        path: Path | None = None,
    ) -> None:
        relative_path = path or Path(result.trace_path or "")
        if not relative_path:
            return
        payload = node_result_payload(
            result,
            request,
            started_at,
            finished_at,
            duration_ms,
            active=active,
        )
        output_path = self._settings.media_data_dir / relative_path
        write_json_atomic(output_path, payload)
        if active:
            write_json_atomic(output_path.parent / "active.json", payload)

    def annotate_preserved_active_failure(
        self,
        workflow_id: str,
        node_id: str,
        failed_result: WorkflowNodeRunResponse,
    ) -> None:
        active_path = (
            self._settings.media_data_dir / "runs" / workflow_id / "nodes" / node_id / "active.json"
        )
        if not active_path.exists():
            return
        payload = json.loads(active_path.read_text(encoding="utf-8"))
        payload["active"] = True
        payload["last_run_id"] = failed_result.node_run_id
        payload["last_failed_run_id"] = failed_result.node_run_id
        payload["has_active_output"] = bool(payload.get("output") or payload.get("output_assets"))
        payload["last_error"] = failed_result.error
        write_json_atomic(active_path, payload)

    def preserved_override_prompt(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        node_id: str,
        node_type: str | None = None,
    ) -> str | None:
        if request.override_prompt is not None:
            return request.override_prompt
        payload = resolve_active_result(
            self._settings.media_data_dir,
            workflow_id,
            node_id,
            node_type,
        )
        if payload is None:
            return None
        override_prompt = payload.get("override_prompt")
        return override_prompt if isinstance(override_prompt, str) else None

    def latest_run_is_optimize_only(
        self,
        workflow_id: str,
        node_id: str,
        active_run_id: str,
    ) -> bool:
        node_dir = self._settings.media_data_dir / "runs" / workflow_id / "nodes" / node_id
        if not node_dir.exists():
            return False
        latest: tuple[str, str, dict[str, Any]] | None = None
        for path in node_dir.glob("nrun_*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            run_id = str(payload.get("node_run_id") or path.stem)
            sort_key = str(payload.get("started_at") or payload.get("finished_at") or "")
            candidate = (sort_key, run_id, payload)
            if latest is None or candidate[:2] > latest[:2]:
                latest = candidate
        if latest is None:
            return False
        payload = latest[2]
        if str(payload.get("node_run_id") or "") == active_run_id:
            return False
        output = payload.get("output")
        return (
            isinstance(output, dict)
            and str(output.get("status") or "").lower() == "optimized"
            and payload.get("active") is False
        )

    def existing_result_is_terminal(
        self,
        existing_result: WorkflowNodeRunResponse,
        node_type: str,
    ) -> bool:
        if existing_result.status != "completed":
            return False
        if str(existing_result.output.get("status") or "").lower() == "optimized":
            return False
        if node_type != "final-composition":
            return True
        local_path = existing_result.output.get("local_path")
        return (
            existing_result.output.get("status") == "ready"
            and isinstance(local_path, str)
            and bool(local_path)
            and (self._settings.media_data_dir / local_path).exists()
        )

    @staticmethod
    def preserve_existing_prompt_state(
        result: WorkflowNodeRunResponse,
        existing_result: WorkflowNodeRunResponse | None,
    ) -> None:
        if existing_result is None:
            return
        for field_name in (
            "materialized_prompt",
            "materialized_assets",
            "source_mappings",
            "resolved_prompt_preview",
            "resolved_prompt_with_assets",
            "effective_prompt",
            "missing_inputs",
            "stale_upstream_nodes",
            "locked_upstream_nodes",
        ):
            value = getattr(existing_result, field_name)
            if value not in (None, [], {}):
                setattr(result, field_name, value)

    @staticmethod
    def result_has_active_output(result: WorkflowNodeRunResponse | None) -> bool:
        if result is None or result.status != "completed":
            return False
        return bool(result.output or result.output_assets)

    @staticmethod
    def defer_graph_updates(request: WorkflowNodeRunRequest) -> bool:
        return bool(getattr(request, "defer_graph_updates", False))

    @staticmethod
    def failed_graph_result_preserving_active(
        existing_result: WorkflowNodeRunResponse | None,
        failed_result: WorkflowNodeRunResponse,
    ) -> dict[str, Any]:
        if existing_result is None:
            return failed_result.model_dump(mode="json")
        payload = existing_result.model_dump(mode="json")
        payload["status"] = "failed"
        payload["error"] = failed_result.error
        payload["last_run_id"] = failed_result.node_run_id
        payload["last_failed_run_id"] = failed_result.node_run_id
        payload["has_active_output"] = bool(payload.get("output") or payload.get("output_assets"))
        return payload


def node_result_payload(
    result: WorkflowNodeRunResponse,
    request: WorkflowNodeRunRequest,
    started_at: str,
    finished_at: str,
    duration_ms: int,
    *,
    active: bool,
) -> dict[str, Any]:
    return {
        **result.model_dump(mode="json"),
        "input_context": request.input_context,
        "override_prompt": request.override_prompt,
        "run_downstream": request.run_downstream,
        "revision": request.revision.model_dump(mode="json") if request.revision else None,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "active": active,
        "trace": {
            "override_prompt": request.override_prompt,
            "input_context": request.input_context,
            "input_assets": result.input_assets,
            "output": result.output,
            "error": result.error,
        },
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)
