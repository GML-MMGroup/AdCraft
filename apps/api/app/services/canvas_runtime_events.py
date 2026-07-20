from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import json
import threading
import time
from typing import Any

from app.core.config import Settings
from app.schemas.canvas_runtime import (
    CanvasNodeRuntimeState,
    CanvasRuntimeEvent,
    CanvasRuntimeEventsResponse,
    CanvasRuntimeSnapshotResponse,
)
from app.schemas.workflow_executions import WorkflowExecutionState, WorkflowNodeExecutionState
from app.schemas.workflow_graph import WorkflowGraph, WorkflowGraphNode
from app.services.agent_trace import utc_now
from app.services.media_tasks import MediaTaskService


class CanvasRuntimeError(Exception):
    code = "canvas_runtime_error"
    status_code = 500

    @property
    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self)}


class CanvasRuntimeNotFoundError(CanvasRuntimeError):
    code = "workflow_not_found"
    status_code = 404


_LOCKS_GUARD = threading.Lock()
_WORKFLOW_LOCKS: dict[str, threading.Lock] = {}


class CanvasRuntimeEventService:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def append_event(
        self,
        workflow_id: str,
        event_type: str,
        *,
        execution_id: str | None = None,
        node_id: str | None = None,
        node_type: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        version: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> CanvasRuntimeEvent:
        with _workflow_lock(workflow_id):
            event = CanvasRuntimeEvent(
                seq=self._next_seq_unlocked(workflow_id),
                event_type=event_type,
                workflow_id=workflow_id,
                execution_id=execution_id,
                node_id=node_id,
                node_type=node_type,
                resource_type=resource_type,
                resource_id=resource_id,
                version=version,
                created_at=utc_now().isoformat(),
                payload=payload or {},
            )
            path = self._events_path(workflow_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n")
            return event

    def append_node_status_changed(
        self,
        workflow_id: str,
        *,
        execution_id: str | None,
        node_id: str,
        node_type: str,
        status: str,
        previous_status: str | None = None,
        error: str | None = None,
        error_code: str | None = None,
        waiting_reason: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        node_run_id: str | None = None,
        output_status: str | None = None,
        has_active_output: bool | None = None,
        failure_stage: str | None = None,
        user_explainable_reason: str | None = None,
        asset_flow_debug: dict[str, Any] | None = None,
    ) -> CanvasRuntimeEvent:
        payload: dict[str, Any] = {
            "status": status,
            "previous_status": previous_status,
            "error": error,
            "error_code": error_code,
            "waiting_reason": waiting_reason,
            "started_at": started_at,
            "finished_at": finished_at,
        }
        if node_run_id:
            payload["node_run_id"] = node_run_id
        if output_status is not None:
            payload["output_status"] = output_status
        if has_active_output is not None:
            payload["has_active_output"] = has_active_output
        if failure_stage:
            payload["failure_stage"] = failure_stage
        if user_explainable_reason:
            payload["user_explainable_reason"] = user_explainable_reason
        if asset_flow_debug:
            payload["asset_flow_debug"] = _asset_flow_debug_summary(asset_flow_debug)
        return self.append_event(
            workflow_id,
            "node_status_changed",
            execution_id=execution_id,
            node_id=node_id,
            node_type=node_type,
            resource_type="node",
            resource_id=node_id,
            payload=payload,
        )

    def append_provider_strategy_updated(
        self,
        workflow_id: str,
        *,
        execution_id: str | None,
        node_id: str,
        node_type: str,
        node_run_id: str | None,
        provider_strategy: dict[str, Any],
    ) -> CanvasRuntimeEvent:
        return self.append_event(
            workflow_id,
            "provider_strategy_updated",
            execution_id=execution_id,
            node_id=node_id,
            node_type=node_type,
            resource_type="node",
            resource_id=node_id,
            payload={
                "node_run_id": node_run_id,
                "selected_provider": provider_strategy.get("selected_provider"),
                "status": provider_strategy.get("status"),
                "attempted_providers": provider_strategy.get("attempted_providers") or [],
                "fallback_used": provider_strategy.get("fallback_used"),
                "warnings": provider_strategy.get("warnings") or [],
                "refresh": ["workflow_nodes", "workflow_graph"],
            },
        )

    def append_reference_policy_updated(
        self,
        workflow_id: str,
        *,
        execution_id: str | None,
        node_id: str,
        node_type: str,
        node_run_id: str | None,
        reference_policy: dict[str, Any],
    ) -> CanvasRuntimeEvent:
        return self.append_event(
            workflow_id,
            "reference_policy_updated",
            execution_id=execution_id,
            node_id=node_id,
            node_type=node_type,
            resource_type="node",
            resource_id=node_id,
            payload={
                "node_run_id": node_run_id,
                "provider": reference_policy.get("provider"),
                "reference_mode": reference_policy.get("reference_mode"),
                "accepted_reference_count": len(reference_policy.get("accepted_assets") or []),
                "prompt_only_reference_count": len(
                    reference_policy.get("prompt_only_assets") or []
                ),
                "rejected_reference_count": len(reference_policy.get("rejected_assets") or []),
                "warnings": reference_policy.get("warnings") or [],
                "errors": reference_policy.get("errors") or [],
                "refresh": ["workflow_nodes", "workflow_graph"],
            },
        )

    def append_asset_flow_debug_updated(
        self,
        workflow_id: str,
        *,
        execution_id: str | None,
        node_id: str,
        node_type: str,
        node_run_id: str | None,
        asset_flow_debug: dict[str, Any],
    ) -> CanvasRuntimeEvent:
        return self.append_event(
            workflow_id,
            "asset_flow_debug_updated",
            execution_id=execution_id,
            node_id=node_id,
            node_type=node_type,
            resource_type="node",
            resource_id=node_id,
            payload={
                "node_run_id": node_run_id,
                **_asset_flow_debug_summary(asset_flow_debug),
                "refresh": ["workflow_nodes", "workflow_graph"],
            },
        )

    def append_node_output_updated(
        self,
        workflow_id: str,
        *,
        execution_id: str | None,
        node_id: str,
        node_type: str,
        node_run_id: str | None,
        output_status: str | None = None,
    ) -> CanvasRuntimeEvent:
        return self.append_event(
            workflow_id,
            "node_output_updated",
            execution_id=execution_id,
            node_id=node_id,
            node_type=node_type,
            resource_type="node",
            resource_id=node_id,
            payload={
                "node_run_id": node_run_id,
                "output_status": output_status,
                "refresh": ["workflow_nodes", "workflow_graph"],
            },
        )

    def append_node_assets_updated(
        self,
        workflow_id: str,
        *,
        execution_id: str | None,
        node_id: str,
        node_type: str,
        node_run_id: str | None,
    ) -> CanvasRuntimeEvent:
        return self.append_event(
            workflow_id,
            "node_assets_updated",
            execution_id=execution_id,
            node_id=node_id,
            node_type=node_type,
            resource_type="node",
            resource_id=node_id,
            payload={
                "node_run_id": node_run_id,
                "refresh": ["workflow_nodes", "workflow_graph", "media_status"],
            },
        )

    def list_events(self, workflow_id: str, *, after_seq: int = 0) -> list[CanvasRuntimeEvent]:
        with _workflow_lock(workflow_id):
            return self._list_events_unlocked(workflow_id, after_seq=after_seq)

    def response(self, workflow_id: str, *, after_seq: int = 0) -> CanvasRuntimeEventsResponse:
        events = self.list_events(workflow_id, after_seq=after_seq)
        return CanvasRuntimeEventsResponse(
            workflow_id=workflow_id,
            events=events,
            last_event_seq=self.last_event_seq(workflow_id),
        )

    def last_event_seq(self, workflow_id: str) -> int:
        with _workflow_lock(workflow_id):
            return self._last_event_seq_unlocked(workflow_id)

    def stream_events(
        self,
        workflow_id: str,
        *,
        after_seq: int = 0,
        heartbeat_interval_seconds: int = 15,
    ) -> Iterator[str]:
        cursor = after_seq
        while True:
            events = self.list_events(workflow_id, after_seq=cursor)
            if events:
                for event in events:
                    cursor = event.seq
                    yield _format_sse(event)
                continue
            heartbeat = self.append_event(
                workflow_id,
                "heartbeat",
                resource_type="workflow",
                resource_id=workflow_id,
                payload={"status": "alive"},
            )
            cursor = heartbeat.seq
            yield _format_sse(heartbeat)
            time.sleep(heartbeat_interval_seconds)

    def _events_path(self, workflow_id: str) -> Path:
        return self._data_dir / "runs" / workflow_id / "canvas_events.ndjson"

    def _next_seq_unlocked(self, workflow_id: str) -> int:
        return self._last_event_seq_unlocked(workflow_id) + 1

    def _last_event_seq_unlocked(self, workflow_id: str) -> int:
        seq = 0
        path = self._events_path(workflow_id)
        if not path.exists():
            return seq
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
        return seq

    def _list_events_unlocked(
        self,
        workflow_id: str,
        *,
        after_seq: int,
    ) -> list[CanvasRuntimeEvent]:
        path = self._events_path(workflow_id)
        if not path.exists():
            return []
        events: list[CanvasRuntimeEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = CanvasRuntimeEvent.model_validate_json(line)
            if event.seq > after_seq:
                events.append(event)
        events.sort(key=lambda event: event.seq)
        return events


@dataclass(frozen=True)
class CanvasRuntimeRecoveryResult:
    workflow_id: str
    execution_id: str | None = None
    changed_node_ids: list[str] = field(default_factory=list)
    waiting_node_ids: list[str] = field(default_factory=list)
    completed_node_ids: list[str] = field(default_factory=list)
    failed_node_ids: list[str] = field(default_factory=list)
    status_by_node_id: dict[str, str] = field(default_factory=dict)
    error_code_by_node_id: dict[str, str] = field(default_factory=dict)


class CanvasRuntimeRecoveryService:
    _DEFAULT_TIMEOUT_MINUTES = 30
    _TIMEOUT_MINUTES_BY_NODE_TYPE = {
        "script": 10,
        "requirements-analysis": 10,
        "product-design": 10,
        "creative-direction": 10,
        "agent_text": 10,
        "character-generation": 30,
        "scene-generation": 30,
        "storyboard": 30,
        "storyboard-generation": 30,
        "bgm": 30,
        "audio_generation": 30,
        "image_generation": 30,
        "final-composition": 30,
        "storyboard-video-generation": 120,
        "video_generation": 120,
    }

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._media_tasks = MediaTaskService(settings=settings)

    def recover_workflow(self, workflow_id: str) -> WorkflowExecutionState | None:
        result = self.recover_workflow_runtime(workflow_id)
        if result.execution_id is None:
            return None
        from app.services.workflow_executions import WorkflowExecutionService

        return WorkflowExecutionService(self._settings.media_data_dir).load_execution(
            workflow_id,
            result.execution_id,
        )

    def recover_workflow_runtime(self, workflow_id: str) -> CanvasRuntimeRecoveryResult:
        from app.services.workflow_executions import WorkflowExecutionService

        executions = WorkflowExecutionService(self._settings.media_data_dir)
        active_execution = executions.load_active_execution(workflow_id)
        if active_execution is None:
            return CanvasRuntimeRecoveryResult(workflow_id=workflow_id)

        before = _node_state_snapshots(active_execution)
        touched = False
        for node in active_execution.nodes.values():
            if node.status == "running":
                touched = self._recover_running_node(executions, active_execution, node) or touched
                continue
            if node.status == "waiting":
                touched = self._recover_waiting_node(executions, active_execution, node) or touched

        if touched:
            active_execution = self._refresh_execution_status(
                workflow_id,
                active_execution.execution_id,
            )
        return _recovery_result_from_state(active_execution, before)

    def _recover_running_node(
        self,
        executions: Any,
        execution: WorkflowExecutionState,
        node: WorkflowNodeExecutionState,
    ) -> bool:
        metadata = self._runtime_metadata(node)
        if not _recoverable_task_id(metadata):
            metadata["error_code"] = "execution_lost_after_restart"
            metadata["recovery_status"] = "failed"
            self._update_node(
                executions,
                execution,
                node,
                "failed",
                metadata=metadata,
                error="Execution was running before restart and has no recoverable provider task.",
                output_status="failed",
                has_active_output=False,
            )
            self._sync_graph_node_runtime_status(
                execution.workflow_id,
                node,
                "failed",
                metadata=metadata,
                error="Execution was running before restart and has no recoverable provider task.",
            )
            return True

        metadata["recovery_status"] = "checking"
        metadata.pop("last_check_error", None)
        self._update_node(
            executions,
            execution,
            node,
            "waiting",
            metadata=metadata,
            waiting_reason="provider_task_pending",
            output_status=node.output_status or "submitted",
            has_active_output=False,
        )
        return (
            self._query_and_apply_provider_status(
                executions,
                execution,
                node.model_copy(update={"status": "waiting", "metadata": metadata}),
            )
            or True
        )

    def _recover_waiting_node(
        self,
        executions: Any,
        execution: WorkflowExecutionState,
        node: WorkflowNodeExecutionState,
    ) -> bool:
        metadata = self._runtime_metadata(node)
        task_id = _recoverable_task_id(metadata)
        if not task_id and node.node_type != "storyboard-video-generation":
            return False
        return self._query_and_apply_provider_status(executions, execution, node)

    def _query_and_apply_provider_status(
        self,
        executions: Any,
        execution: WorkflowExecutionState,
        node: WorkflowNodeExecutionState,
    ) -> bool:
        metadata = self._runtime_metadata(node)
        metadata["recovery_status"] = "checking"
        metadata["last_checked_at"] = utc_now().isoformat()
        metadata.pop("last_check_error", None)
        metadata.pop("error_code", None)
        try:
            provider_result = self._query_provider_task(execution.workflow_id, node)
        except Exception as exc:  # noqa: BLE001 - provider/media refresh errors are transient.
            metadata["last_check_error"] = str(exc)
            self._update_node(
                executions,
                execution,
                node,
                "waiting",
                metadata=metadata,
                waiting_reason="provider_task_pending",
                output_status=node.output_status or "submitted",
                has_active_output=False,
            )
            self._sync_graph_node_runtime_status(
                execution.workflow_id,
                node,
                "waiting",
                metadata=metadata,
                waiting_reason="provider_task_pending",
            )
            return True

        status = _provider_result_status(provider_result)
        if status in {"completed", "succeeded", "success", "ready", "downloaded"}:
            metadata["recovery_status"] = "completed"
            self._update_node(
                executions,
                execution,
                node,
                "completed",
                metadata=metadata,
                output_status="ready",
                has_active_output=True,
            )
            self._sync_graph_node_runtime_status(
                execution.workflow_id,
                node,
                "completed",
                metadata=metadata,
            )
            return True

        if status in {"missing", "expired", "unrecoverable", "not_found"}:
            error = (
                _provider_result_error(provider_result) or "Provider task is no longer recoverable."
            )
            metadata["error_code"] = "provider_task_unrecoverable"
            metadata["recovery_status"] = "failed"
            self._update_node(
                executions,
                execution,
                node,
                "failed",
                metadata=metadata,
                error=error,
                output_status="failed",
                has_active_output=False,
            )
            self._sync_graph_node_runtime_status(
                execution.workflow_id,
                node,
                "failed",
                metadata=metadata,
                error=error,
            )
            return True

        if status in {"failed", "failure", "error", "cancelled", "canceled"}:
            error = _provider_result_error(provider_result) or "Provider task failed."
            metadata["error_code"] = (
                _provider_result_error_code(provider_result) or "provider_task_failed"
            )
            metadata["recovery_status"] = "failed"
            self._update_node(
                executions,
                execution,
                node,
                "failed",
                metadata=metadata,
                error=error,
                output_status="failed",
                has_active_output=False,
            )
            self._sync_graph_node_runtime_status(
                execution.workflow_id,
                node,
                "failed",
                metadata=metadata,
                error=error,
            )
            return True

        self._update_node(
            executions,
            execution,
            node,
            "waiting",
            metadata=metadata,
            waiting_reason="provider_task_pending",
            output_status=node.output_status or "submitted",
            has_active_output=False,
        )
        self._sync_graph_node_runtime_status(
            execution.workflow_id,
            node,
            "waiting",
            metadata=metadata,
            waiting_reason="provider_task_pending",
        )
        return True

    def _query_provider_task(
        self,
        workflow_id: str,
        node: WorkflowNodeExecutionState,
    ) -> dict[str, Any]:
        metadata_status = node.metadata.get("provider_task_status")
        if isinstance(metadata_status, str) and metadata_status.strip():
            return {"status": metadata_status}
        if node.node_type == "storyboard-video-generation":
            media_status = self._media_tasks.media_status(workflow_id)
            if media_status.storyboard_video_status in {"ready", "downloaded", "completed"}:
                return {"status": "completed"}
            if media_status.storyboard_video_status == "failed":
                return {"status": "failed", "error": "Storyboard video task failed."}
        return {"status": "running"}

    def _runtime_metadata(self, node: WorkflowNodeExecutionState) -> dict[str, Any]:
        metadata = dict(node.metadata or {})
        submitted_at = (
            _parse_datetime(_metadata_string(metadata, "submitted_at") or node.started_at)
            or utc_now()
        )
        metadata.setdefault("submitted_at", submitted_at.isoformat())
        metadata.setdefault(
            "deadline_at",
            (submitted_at + timedelta(minutes=self._timeout_minutes(node))).isoformat(),
        )
        for key in (
            "provider",
            "provider_task_id",
            "last_checked_at",
            "recovery_status",
            "last_check_error",
        ):
            metadata.setdefault(key, None)
        return metadata

    def _timeout_minutes(self, node: WorkflowNodeExecutionState) -> int:
        return self._TIMEOUT_MINUTES_BY_NODE_TYPE.get(
            node.node_type,
            self._DEFAULT_TIMEOUT_MINUTES,
        )

    def _update_node(
        self,
        executions: Any,
        execution: WorkflowExecutionState,
        node: WorkflowNodeExecutionState,
        status: str,
        *,
        metadata: dict[str, Any],
        error: str | None = None,
        waiting_reason: str | None = None,
        output_status: str | None = None,
        has_active_output: bool | None = None,
    ) -> None:
        executions.update_node_status(
            execution.workflow_id,
            execution.execution_id,
            node.node_id,
            status,
            metadata=metadata,
            error=error,
            waiting_reason=waiting_reason,
            output_status=output_status,
            has_active_output=has_active_output,
        )

    def _refresh_execution_status(
        self,
        workflow_id: str,
        execution_id: str,
    ) -> WorkflowExecutionState:
        from app.services.workflow_executions import WorkflowExecutionService

        executions = WorkflowExecutionService(self._settings.media_data_dir)
        state = executions.load_execution(workflow_id, execution_id)
        selected_nodes = [
            node
            for node in state.nodes.values()
            if node.selected or node.node_id in state.selected_node_ids
        ]
        nodes = selected_nodes or list(state.nodes.values())
        if any(node.status in {"queued", "running"} for node in nodes):
            return executions.update_execution(workflow_id, execution_id, status="running")
        if any(node.status == "waiting" for node in nodes):
            return executions.update_execution(workflow_id, execution_id, status="waiting")
        if any(node.status == "failed" for node in nodes):
            error = next(
                (node.error for node in nodes if node.status == "failed" and node.error), None
            )
            return executions.finish_execution(workflow_id, execution_id, "failed", error=error)
        if nodes and all(node.status in {"completed", "skipped"} for node in nodes):
            return executions.finish_execution(workflow_id, execution_id, "completed")
        return state

    def _sync_graph_node_runtime_status(
        self,
        workflow_id: str,
        node: WorkflowNodeExecutionState,
        status: str,
        *,
        metadata: dict[str, Any],
        error: str | None = None,
        waiting_reason: str | None = None,
    ) -> None:
        from app.services.workflow_graph import load_graph, save_graph

        graph = load_graph(self._settings.media_data_dir, workflow_id)
        if graph is None:
            return
        graph_node = next((item for item in graph.nodes if item.id == node.node_id), None)
        if graph_node is None:
            return
        graph_node.status = status
        graph_node.stale = status == "waiting"
        graph_node.stale_reason = waiting_reason if status == "waiting" else None
        graph_node.metadata = dict(graph_node.metadata or {})
        graph_node.metadata.update(_public_runtime_metadata(metadata))
        if error:
            graph_node.metadata["last_error"] = error
        elif status != "failed":
            graph_node.metadata.pop("last_error", None)
        saved_graph = save_graph(self._settings.media_data_dir, graph)
        CanvasRuntimeEventService(self._settings.media_data_dir).append_event(
            workflow_id,
            "graph_updated",
            node_id=node.node_id,
            node_type=node.node_type,
            resource_type="graph",
            resource_id=workflow_id,
            version=saved_graph.version,
            payload={
                "node_id": node.node_id,
                "status": status,
                "refresh": ["workflow_graph", "canvas_runtime"],
            },
        )


class CanvasRuntimeService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._events = CanvasRuntimeEventService(settings.media_data_dir)
        self._media_tasks = MediaTaskService(settings=settings)
        self._recovery = CanvasRuntimeRecoveryService(settings)

    def recover(self, workflow_id: str) -> WorkflowExecutionState | None:
        return self._recovery.recover_workflow(workflow_id)

    def snapshot(self, workflow_id: str) -> CanvasRuntimeSnapshotResponse:
        from app.services.workflow_executions import WorkflowExecutionService
        from app.services.workflow_graph import load_graph

        graph = load_graph(self._settings.media_data_dir, workflow_id)
        if graph is None:
            raise CanvasRuntimeNotFoundError(f"workflow not found: {workflow_id}")
        self.recover(workflow_id)
        graph = load_graph(self._settings.media_data_dir, workflow_id) or graph
        active_execution = WorkflowExecutionService(
            self._settings.media_data_dir
        ).load_active_execution(workflow_id)
        node_runtime = _build_node_runtime(graph, active_execution)
        return CanvasRuntimeSnapshotResponse(
            workflow_id=workflow_id,
            graph=graph,
            active_execution=active_execution,
            node_runtime=node_runtime,
            queued_node_ids=_ids_by_status(node_runtime, "queued", source="execution"),
            running_node_ids=_ids_by_status(node_runtime, "running", source="execution"),
            waiting_node_ids=_ids_by_status(node_runtime, "waiting", source="execution"),
            completed_node_ids=_ids_by_status(node_runtime, "completed"),
            failed_node_ids=_ids_by_status(node_runtime, "failed"),
            skipped_node_ids=_ids_by_status(node_runtime, "skipped", source="execution"),
            media_status=self._media_tasks.media_status(workflow_id),
            last_event_seq=self._events.last_event_seq(workflow_id),
        )


def _build_node_runtime(
    graph: WorkflowGraph,
    active_execution: WorkflowExecutionState | None,
) -> dict[str, CanvasNodeRuntimeState]:
    runtime: dict[str, CanvasNodeRuntimeState] = {}
    execution_nodes = active_execution.nodes if active_execution is not None else {}
    for graph_node in graph.nodes:
        execution_node = execution_nodes.get(graph_node.id)
        runtime[graph_node.id] = (
            _runtime_from_execution_node(graph_node, active_execution, execution_node)
            if execution_node is not None and active_execution is not None
            else _runtime_from_graph_node(graph, graph_node)
        )
    if active_execution is not None:
        for node_id, execution_node in active_execution.nodes.items():
            if node_id in runtime:
                continue
            runtime[node_id] = _runtime_from_execution_node(None, active_execution, execution_node)
    return runtime


def _runtime_from_execution_node(
    graph_node: WorkflowGraphNode | None,
    execution: WorkflowExecutionState,
    node: WorkflowNodeExecutionState,
) -> CanvasNodeRuntimeState:
    metadata = dict(node.metadata)
    if node.skipped_reason:
        metadata["skipped_reason"] = node.skipped_reason
    return CanvasNodeRuntimeState(
        node_id=node.node_id,
        node_type=node.node_type,
        status=node.status,
        status_source="execution",
        execution_id=execution.execution_id,
        started_at=node.started_at,
        updated_at=node.finished_at or node.started_at or execution.started_at,
        finished_at=node.finished_at,
        error=node.error,
        error_code=_metadata_string(metadata, "error_code"),
        waiting_reason=node.waiting_reason,
        has_active_output=bool(
            node.has_active_output
            if node.has_active_output is not None
            else _graph_node_has_active_output(graph_node)
        ),
        output_status=node.output_status or _graph_output_status(graph_node),
        metadata=metadata,
    )


def _runtime_from_graph_node(
    graph: WorkflowGraph,
    node: WorkflowGraphNode,
) -> CanvasNodeRuntimeState:
    metadata = {
        **node.metadata,
        "stale": node.stale,
        "stale_reason": node.stale_reason,
        "locked": node.locked,
    }
    return CanvasNodeRuntimeState(
        node_id=node.id,
        node_type=node.node_type,
        status=_runtime_status_from_graph_status(node.status, node.metadata),
        status_source="graph",
        updated_at=graph.updated_at,
        error=_graph_error(node),
        error_code=_metadata_string(node.metadata, "error_code"),
        waiting_reason=node.stale_reason if node.status == "stale" else None,
        has_active_output=_graph_node_has_active_output(node),
        output_status=_graph_output_status(node),
        metadata=metadata,
    )


def _runtime_status_from_graph_status(
    status: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    if status == "stale":
        return "pending"
    if status == "waiting" and (metadata or {}).get("stage") == "planned":
        return "pending"
    if status in {
        "pending",
        "queued",
        "running",
        "waiting",
        "completed",
        "failed",
        "skipped",
        "cancelled",
        "blocked",
    }:
        return status
    return "pending"


def _graph_node_has_active_output(node: WorkflowGraphNode | None) -> bool:
    if node is None:
        return False
    return bool(node.output or node.output_assets)


def _graph_output_status(node: WorkflowGraphNode | None) -> str | None:
    if node is None:
        return None
    status = node.output.get("status")
    if status not in (None, ""):
        return str(status)
    return node.status if node.status in {"completed", "failed", "waiting"} else None


def _graph_error(node: WorkflowGraphNode) -> str | None:
    error = node.output.get("error")
    if error not in (None, ""):
        return str(error)
    metadata_error = node.metadata.get("error")
    if metadata_error not in (None, ""):
        return str(metadata_error)
    return None


def _metadata_string(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return str(value) if value not in (None, "") else None


def _node_state_snapshots(state: WorkflowExecutionState) -> dict[str, dict[str, Any]]:
    return {node_id: node.model_dump(mode="json") for node_id, node in state.nodes.items()}


def _recovery_result_from_state(
    state: WorkflowExecutionState,
    before: dict[str, dict[str, Any]],
) -> CanvasRuntimeRecoveryResult:
    changed_node_ids = [
        node_id
        for node_id, node in state.nodes.items()
        if before.get(node_id) != node.model_dump(mode="json")
    ]
    status_by_node_id = {node_id: state.nodes[node_id].status for node_id in changed_node_ids}
    error_code_by_node_id = {
        node_id: str(state.nodes[node_id].metadata.get("error_code"))
        for node_id in changed_node_ids
        if state.nodes[node_id].metadata.get("error_code") not in (None, "")
    }
    return CanvasRuntimeRecoveryResult(
        workflow_id=state.workflow_id,
        execution_id=state.execution_id,
        changed_node_ids=changed_node_ids,
        waiting_node_ids=[
            node_id for node_id in changed_node_ids if state.nodes[node_id].status == "waiting"
        ],
        completed_node_ids=[
            node_id for node_id in changed_node_ids if state.nodes[node_id].status == "completed"
        ],
        failed_node_ids=[
            node_id for node_id in changed_node_ids if state.nodes[node_id].status == "failed"
        ],
        status_by_node_id=status_by_node_id,
        error_code_by_node_id=error_code_by_node_id,
    )


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _recoverable_task_id(metadata: dict[str, Any]) -> str | None:
    for key in ("provider_task_id", "task_id", "media_task_id"):
        value = metadata.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _provider_result_status(result: dict[str, Any]) -> str:
    return str(result.get("status") or result.get("state") or "running").strip().lower()


def _provider_result_error(result: dict[str, Any]) -> str | None:
    value = result.get("error") or result.get("message") or result.get("failure_reason")
    return str(value) if value not in (None, "") else None


def _provider_result_error_code(result: dict[str, Any]) -> str | None:
    value = result.get("error_code") or result.get("code")
    return str(value) if value not in (None, "") else None


def _public_runtime_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: metadata.get(key)
        for key in (
            "provider",
            "provider_task_id",
            "submitted_at",
            "last_checked_at",
            "deadline_at",
            "recovery_status",
            "last_check_error",
            "error_code",
        )
        if metadata.get(key) not in (None, "")
    }


def _ids_by_status(
    runtime: dict[str, CanvasNodeRuntimeState],
    status: str,
    *,
    source: str | None = None,
) -> list[str]:
    return [
        node_id
        for node_id, node in runtime.items()
        if node.status == status and (source is None or node.status_source == source)
    ]


def _asset_flow_debug_summary(debug: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "input_reference_count",
        "display_asset_count",
        "prompt_context_asset_count",
        "provider_reference_asset_count",
        "prompt_only_asset_count",
        "rejected_reference_count",
        "provider_attempt_count",
        "selected_provider",
        "failure_stage",
        "user_explainable_reason",
        "warnings",
    )
    return {key: debug.get(key) for key in keys if key in debug}


def _workflow_lock(workflow_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _WORKFLOW_LOCKS.get(workflow_id)
        if lock is None:
            lock = threading.Lock()
            _WORKFLOW_LOCKS[workflow_id] = lock
        return lock


def _format_sse(event: CanvasRuntimeEvent) -> str:
    data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
    return f"id: {event.seq}\nevent: {event.event_type}\ndata: {data}\n\n"
