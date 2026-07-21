from pathlib import Path
from datetime import datetime
from typing import Any

from app.schemas.workflow_v2 import V2ProviderTask, WorkflowV2, WorkflowV2RuntimeSnapshot
from app.services.agent_trace import utc_now
from app.services.v2_execution_recovery import latest_runtime_activity_by_slot
from app.services.v2_event_store import V2EventStore


class V2RuntimeSnapshotService:
    def __init__(
        self,
        data_dir: Path,
        *,
        event_store: V2EventStore | None = None,
    ) -> None:
        self._event_store = event_store or V2EventStore(data_dir)

    def build_snapshot(
        self,
        workflow: WorkflowV2,
        *,
        active_execution: dict[str, Any] | None = None,
        provider_tasks: list[V2ProviderTask] | None = None,
    ) -> WorkflowV2RuntimeSnapshot:
        active_execution = _nonterminal_active_execution(active_execution)
        running_slot_ids: list[str] = []
        waiting_slot_ids: list[str] = []
        failed_slot_ids: list[str] = []
        completed_slot_ids: list[str] = []
        node_runtime: dict[str, dict[str, Any]] = {}
        item_runtime: dict[str, dict[str, Any]] = {}
        slot_runtime: dict[str, dict[str, Any]] = {}
        latest_activity = latest_runtime_activity_by_slot(
            self._event_store.load_events(workflow.workflow_id)
        )
        for node in workflow.nodes:
            node_runtime[node.node_id] = {"status": node.status}
            for item in node.items:
                if item.lifecycle_state != "active":
                    continue
                item_runtime[item.item_id] = {"node_id": item.node_id, "status": item.status}
                for slot in item.slots:
                    slot_runtime[slot.slot_id] = {
                        "slot_id": slot.slot_id,
                        "node_id": slot.node_id,
                        "item_id": slot.item_id,
                        "status": slot.status,
                        "runtime_status": slot.status,
                        "slot_type": slot.slot_type,
                        "media_type": slot.media_type,
                        "selected_asset_id": slot.selected_asset_id,
                        "selected_version_id": slot.selected_version_id,
                        "current_working_asset_id": slot.current_working_asset_id,
                        "current_working_version_id": slot.current_working_version_id,
                    }
                    if slot.status == "running":
                        running_slot_ids.append(slot.slot_id)
                    elif slot.status == "waiting":
                        waiting_slot_ids.append(slot.slot_id)
                    elif slot.status == "failed":
                        failed_slot_ids.append(slot.slot_id)
                    elif slot.status == "completed":
                        completed_slot_ids.append(slot.slot_id)
                    elif slot.status == "blocked":
                        slot_runtime[slot.slot_id]["runtime_status"] = "blocked"
                    activity = latest_activity.get(slot.slot_id)
                    if activity is not None:
                        slot_runtime[slot.slot_id]["last_event_seq"] = activity.seq
                        slot_runtime[slot.slot_id]["last_event_type"] = activity.event_type
                        slot_runtime[slot.slot_id]["updated_at"] = activity.created_at
                    if slot.status in {"failed", "skipped"}:
                        error = slot.metadata.get("error")
                        if isinstance(error, dict):
                            slot_runtime[slot.slot_id]["error"] = dict(error)
                        generation_error_code = slot.metadata.get("generation_error_code")
                        if isinstance(generation_error_code, str) and generation_error_code:
                            slot_runtime[slot.slot_id]["generation_error_code"] = (
                                generation_error_code
                            )
                    if slot.metadata.get("recoverable") is not None:
                        slot_runtime[slot.slot_id]["recoverable"] = bool(
                            slot.metadata.get("recoverable")
                        )
        for task in _nonterminal_tasks_by_slot(provider_tasks or []).values():
            slot_runtime[task.slot_id] = _merge_slot_runtime(
                slot_runtime.get(task.slot_id, {}),
                {
                    "status": "waiting",
                    "runtime_status": "waiting",
                    "slot_id": task.slot_id,
                    "node_id": task.node_id,
                    "item_id": task.item_id,
                    "provider_task_id": task.task_id,
                    "remote_task_id": task.remote_task_id,
                    "waiting_reason": task.metadata.get("waiting_reason")
                    or "provider_task_submitted",
                    "updated_at": task.updated_at,
                },
            )
        if active_execution:
            for slot_id, runtime in dict(active_execution.get("slot_runtime") or {}).items():
                if isinstance(runtime, dict):
                    slot_runtime[str(slot_id)] = _merge_slot_runtime(
                        slot_runtime.get(str(slot_id), {}),
                        runtime,
                    )
        running_slot_ids = _ids_by_status(slot_runtime, "running")
        waiting_slot_ids = _ids_by_status(slot_runtime, "waiting")
        failed_slot_ids = _ids_by_status(slot_runtime, "failed")
        completed_slot_ids = _ids_by_status(slot_runtime, "completed")
        blocked_slot_ids = _ids_by_status(slot_runtime, "blocked")
        skipped_slot_ids = _ids_by_status(slot_runtime, "skipped")
        item_runtime = _aggregate_items(slot_runtime)
        node_runtime = _aggregate_nodes(slot_runtime)
        running_item_ids = _ids_by_status(item_runtime, "running")
        running_node_ids = _ids_by_status(node_runtime, "running")
        waiting_item_ids = _ids_by_status(item_runtime, "waiting")
        waiting_node_ids = _ids_by_status(node_runtime, "waiting")
        completed_item_ids = _ids_by_status(item_runtime, "completed")
        completed_node_ids = _ids_by_status(node_runtime, "completed")
        failed_item_ids = _ids_by_status(item_runtime, "failed")
        failed_node_ids = _ids_by_status(node_runtime, "failed")
        execution_status = _execution_status(
            active_execution,
            running_slot_ids=running_slot_ids,
            waiting_slot_ids=waiting_slot_ids,
            failed_slot_ids=failed_slot_ids,
            queued_slot_ids=_ids_by_status(slot_runtime, "queued"),
        )
        return WorkflowV2RuntimeSnapshot(
            workflow_id=workflow.workflow_id,
            active_execution_id=active_execution.get("execution_id") if active_execution else None,
            execution_status=execution_status,
            running_slot_ids=running_slot_ids,
            running_item_ids=running_item_ids,
            running_node_ids=running_node_ids,
            waiting_slot_ids=waiting_slot_ids,
            waiting_item_ids=waiting_item_ids,
            waiting_node_ids=waiting_node_ids,
            completed_item_ids=completed_item_ids,
            completed_node_ids=completed_node_ids,
            failed_slot_ids=failed_slot_ids,
            failed_item_ids=failed_item_ids,
            failed_node_ids=failed_node_ids,
            completed_slot_ids=completed_slot_ids,
            blocked_slot_ids=blocked_slot_ids,
            skipped_slot_ids=skipped_slot_ids,
            node_runtime=node_runtime,
            item_runtime=item_runtime,
            slot_runtime=slot_runtime,
            events_cursor=self._event_store.events_cursor(workflow.workflow_id),
            updated_at=utc_now().isoformat(),
        )


def _nonterminal_tasks_by_slot(tasks: list[V2ProviderTask]) -> dict[str, V2ProviderTask]:
    selected: dict[str, V2ProviderTask] = {}
    for task in sorted(tasks, key=lambda item: item.updated_at):
        if task.status in {"completed", "failed", "cancelled"}:
            continue
        selected[task.slot_id] = task
    return selected


def _nonterminal_active_execution(active_execution: dict[str, Any] | None) -> dict[str, Any] | None:
    if not active_execution:
        return None
    if active_execution.get("status") in {"completed", "partial_failed", "failed", "cancelled"}:
        return None
    return active_execution


def _merge_slot_runtime(
    existing: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    if not existing:
        merged = dict(candidate)
        if merged.get("status") and not merged.get("runtime_status"):
            merged["runtime_status"] = merged["status"]
        return merged
    if not candidate:
        return dict(existing)
    freshness = _compare_runtime_freshness(candidate, existing)
    candidate_status = str(candidate.get("status") or candidate.get("runtime_status") or "")
    existing_status = str(existing.get("status") or existing.get("runtime_status") or "")
    if freshness > 0 or (
        freshness == 0
        and existing_status == "queued"
        and candidate_status in {"running", "waiting", "completed", "failed", "blocked", "skipped"}
    ):
        merged = {**existing, **candidate}
        for key, value in existing.items():
            if key not in merged or _is_missing(merged.get(key)):
                merged[key] = value
        if merged.get("status") and not merged.get("runtime_status"):
            merged["runtime_status"] = merged["status"]
        return merged
    merged = dict(existing)
    if not (
        freshness == 0
        and candidate_status == "queued"
        and existing_status in {"running", "waiting", "completed", "failed", "blocked", "skipped"}
    ):
        for key in ("provider_task_id", "remote_task_id", "waiting_reason", "error"):
            if candidate.get(key) and not merged.get(key):
                merged[key] = candidate[key]
    for key, value in candidate.items():
        if key in {
            "status",
            "runtime_status",
            "last_event_seq",
            "last_event_type",
            "updated_at",
        }:
            continue
        if _is_missing(merged.get(key)) and not _is_missing(value):
            merged[key] = value
    return merged


def _is_missing(value: Any) -> bool:
    return value is None or value == ""


def _compare_runtime_freshness(candidate: dict[str, Any], existing: dict[str, Any]) -> int:
    candidate_seq = _int_or_none(candidate.get("last_event_seq"))
    existing_seq = _int_or_none(existing.get("last_event_seq"))
    if candidate_seq is not None and existing_seq is not None and candidate_seq != existing_seq:
        return 1 if candidate_seq > existing_seq else -1
    candidate_time = _datetime_or_none(candidate.get("updated_at"))
    existing_time = _datetime_or_none(existing.get("updated_at"))
    if candidate_time is not None and existing_time is None:
        return 1
    if candidate_time is None and existing_time is not None:
        return -1
    if candidate_time is not None and existing_time is not None and candidate_time != existing_time:
        return 1 if candidate_time > existing_time else -1
    return 0


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _datetime_or_none(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _ids_by_status(runtimes: dict[str, dict[str, Any]], status: str) -> list[str]:
    return [
        runtime_id for runtime_id, runtime in runtimes.items() if runtime.get("status") == status
    ]


def _aggregate_items(slot_runtime: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_item: dict[str, list[dict[str, Any]]] = {}
    for runtime in slot_runtime.values():
        item_id = str(runtime.get("item_id") or "")
        if not item_id:
            continue
        by_item.setdefault(item_id, []).append(runtime)
    return {
        item_id: {
            "item_id": item_id,
            "node_id": runtimes[0].get("node_id"),
            "slot_ids": [str(runtime.get("slot_id")) for runtime in runtimes],
            "status": _aggregate_status([str(runtime.get("status")) for runtime in runtimes]),
        }
        for item_id, runtimes in by_item.items()
    }


def _aggregate_nodes(slot_runtime: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_node: dict[str, list[dict[str, Any]]] = {}
    for runtime in slot_runtime.values():
        node_id = str(runtime.get("node_id") or "")
        if not node_id:
            continue
        by_node.setdefault(node_id, []).append(runtime)
    return {
        node_id: {
            "node_id": node_id,
            "slot_ids": [str(runtime.get("slot_id")) for runtime in runtimes],
            "status": _aggregate_status([str(runtime.get("status")) for runtime in runtimes]),
        }
        for node_id, runtimes in by_node.items()
    }


def _aggregate_status(statuses: list[str]) -> str:
    if not statuses:
        return "empty"
    if "running" in statuses:
        return "running"
    if "waiting" in statuses:
        return "waiting"
    if "failed" in statuses:
        return "failed"
    if "blocked" in statuses:
        return "blocked"
    if all(status in {"completed", "ready", "skipped"} for status in statuses):
        return "completed"
    if "queued" in statuses:
        return "queued"
    if "ready" in statuses:
        return "ready"
    return "empty"


def _execution_status(
    active_execution: dict[str, Any] | None,
    *,
    running_slot_ids: list[str],
    waiting_slot_ids: list[str],
    failed_slot_ids: list[str],
    queued_slot_ids: list[str],
) -> str:
    if running_slot_ids:
        return "running"
    if waiting_slot_ids:
        return "waiting"
    if active_execution and active_execution.get("status") == "running" and queued_slot_ids:
        return "running"
    if queued_slot_ids:
        return "queued"
    if active_execution and active_execution.get("status") in {
        "completed",
        "partial_failed",
        "failed",
        "cancelled",
    }:
        return str(active_execution["status"])
    if failed_slot_ids:
        return "partial_failed"
    return "completed"
