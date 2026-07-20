from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app.schemas.workflow_v2 import WorkflowSlotV2, WorkflowV2, WorkflowV2Event
from app.services.agent_trace import utc_now
from app.services.v2_event_store import V2EventStore
from app.services.v2_execution_service import V2ExecutionService
from app.services.v2_provider_task_service import V2ProviderTaskService
from app.services.v2_slot_scheduler import find_slot
from app.services.v2_workflow_lock import v2_workflow_lock
from app.services.v2_workflow_store import V2WorkflowStore

ACTIVE_RECOVERY_STATUSES = {"queued", "running", "waiting"}
ACTIVE_PROVIDER_TASK_STATUSES = {"queued", "running", "waiting"}
NONTERMINAL_PROVIDER_TASK_STATUSES = {"submitted", "waiting", "polling", "running"}
TERMINAL_EXECUTION_STATUSES = {"completed", "partial_failed", "failed", "cancelled"}
V2_RUNTIME_ACTIVITY_EVENTS = {
    "slot_queued",
    "slot_generation_started",
    "provider_execution_started",
    "provider_task_submitted",
    "provider_task_waiting",
    "provider_task_polled",
    "provider_execution_waiting",
    "asset_version_created",
    "slot_working_version_updated",
    "slot_selected_version_updated",
    "slot_generation_completed",
    "slot_generation_failed",
    "slot_recovered_ready",
}
TERMINAL_SLOT_EVENTS = {"slot_generation_completed", "slot_generation_failed"}
EXECUTION_INTERRUPTED_CODE = "execution_interrupted"
EXECUTION_INTERRUPTED_MESSAGE = (
    "Generation was interrupted before completion. Run again to continue."
)
RecoveryTrigger = Literal[
    "startup",
    "run_preflight",
    "explicit_resume",
    "provider_completion",
]


@dataclass
class V2ExecutionRecoveryResult:
    workflow: WorkflowV2
    recovered_slot_ids: list[str] = field(default_factory=list)
    execution_id: str | None = None
    active_execution_cleared: bool = False
    trigger: RecoveryTrigger = "startup"
    changed: bool = False
    transitioned_slot_ids: list[str] = field(default_factory=list)


class V2ExecutionRecoveryService:
    def __init__(self, data_dir: Path, *, stale_running_timeout_seconds: int) -> None:
        self._data_dir = data_dir
        self._timeout_seconds = stale_running_timeout_seconds
        self._workflow_store = V2WorkflowStore(data_dir)
        self._events = V2EventStore(data_dir)
        self._executions = V2ExecutionService(data_dir)
        self._provider_tasks = V2ProviderTaskService(data_dir)

    def recover_interrupted_execution(
        self,
        workflow_id: str,
        *,
        trigger: RecoveryTrigger,
    ) -> V2ExecutionRecoveryResult:
        with v2_workflow_lock(self._data_dir, workflow_id):
            return self._recover_interrupted_execution_locked(workflow_id, trigger=trigger)

    def _recover_interrupted_execution_locked(
        self,
        workflow_id: str,
        *,
        trigger: RecoveryTrigger,
    ) -> V2ExecutionRecoveryResult:
        workflow = self._workflow_store.load_workflow(workflow_id)
        active_execution = self._executions.load_active(workflow_id, include_terminal=True)
        if active_execution is None:
            return V2ExecutionRecoveryResult(workflow=workflow, trigger=trigger)
        execution_id = str(active_execution.get("execution_id") or "")
        if not execution_id:
            return V2ExecutionRecoveryResult(workflow=workflow, trigger=trigger)
        if str(active_execution.get("status") or "") in TERMINAL_EXECUTION_STATUSES:
            self._executions.clear_active(workflow_id, execution_id=execution_id)
            return V2ExecutionRecoveryResult(
                workflow=workflow,
                execution_id=execution_id,
                active_execution_cleared=True,
                trigger=trigger,
                changed=True,
            )

        nonterminal_tasks = self._provider_tasks.list_nonterminal_tasks(
            workflow_id,
            execution_id=execution_id,
        )
        latest_activity = latest_runtime_activity_by_slot(self._events.load_events(workflow_id))
        stale_task_ids = {
            task.task_id
            for task in nonterminal_tasks
            if _provider_task_needs_reconciliation(
                task,
                latest_activity.get(task.slot_id),
                stale_after_seconds=self._timeout_seconds,
            )
        }
        reconciliation_tasks = [
            task
            for task in nonterminal_tasks
            if task.task_id in stale_task_ids and task.remote_task_id
        ]
        if reconciliation_tasks:
            reconciled_task_ids = {task.task_id for task in reconciliation_tasks}
            nonterminal_tasks = [
                self._provider_tasks.request_stale_recovery_reconciliation(task)
                if task.task_id in reconciled_task_ids
                else task
                for task in nonterminal_tasks
            ]
        task_by_slot = {
            task.slot_id: task
            for task in nonterminal_tasks
            if task.status in NONTERMINAL_PROVIDER_TASK_STATUSES
            and (task.task_id not in stale_task_ids or bool(task.remote_task_id))
        }
        completed_slots = self._completed_active_slots(
            workflow,
            active_execution,
            latest_activity=latest_activity,
        )
        stale_slots = self._stale_slots(
            workflow,
            active_execution,
            task_by_slot=task_by_slot,
            latest_activity=latest_activity,
        )
        if not stale_slots and not completed_slots and not reconciliation_tasks:
            return V2ExecutionRecoveryResult(
                workflow=workflow,
                execution_id=execution_id,
                trigger=trigger,
            )

        now = utc_now().isoformat()
        state = dict(active_execution)
        slot_runtime = {
            str(slot_id): dict(runtime)
            for slot_id, runtime in dict(state.get("slot_runtime") or {}).items()
            if isinstance(runtime, dict)
        }
        pending_events: list[tuple[str, dict[str, Any]]] = []
        recovered_slot_ids: list[str] = []
        completed_recovery_slot_ids: list[str] = []
        reconciliation_slot_ids: list[str] = []
        reconciliation_task_ids = {task.task_id for task in reconciliation_tasks}
        for task in nonterminal_tasks:
            if task.task_id not in reconciliation_task_ids:
                continue
            slot = find_slot(workflow, task.slot_id)
            if slot is None:
                continue
            reconciliation_slot_ids.append(slot.slot_id)
            slot.status = "waiting"
            slot.metadata.update(
                {
                    "provider_task_id": task.task_id,
                    "remote_task_id": task.remote_task_id,
                    "waiting_reason": "stale_provider_task_reconciliation",
                }
            )
            slot_runtime[slot.slot_id] = {
                **slot_runtime.get(slot.slot_id, {}),
                "slot_id": slot.slot_id,
                "node_id": slot.node_id,
                "item_id": slot.item_id,
                "status": "waiting",
                "runtime_status": "waiting",
                "slot_type": slot.slot_type,
                "media_type": slot.media_type,
                "execution_id": execution_id,
                "provider_task_id": task.task_id,
                "remote_task_id": task.remote_task_id,
                "updated_at": now,
            }
            pending_events.append(
                (
                    "provider_task_waiting",
                    {
                        "execution_id": execution_id,
                        "node_id": slot.node_id,
                        "item_id": slot.item_id,
                        "slot_id": slot.slot_id,
                        "payload": {
                            "provider_task_id": task.task_id,
                            "remote_task_id": task.remote_task_id,
                            "waiting_reason": "stale_provider_task_reconciliation",
                        },
                    },
                )
            )
        for slot, activity in completed_slots:
            completed_recovery_slot_ids.append(slot.slot_id)
            slot.status = "completed"
            slot.metadata.pop("error", None)
            slot.metadata.pop("waiting_reason", None)
            slot_runtime[slot.slot_id] = {
                **slot_runtime.get(slot.slot_id, {}),
                "slot_id": slot.slot_id,
                "node_id": slot.node_id,
                "item_id": slot.item_id,
                "status": "completed",
                "runtime_status": "completed",
                "slot_type": slot.slot_type,
                "media_type": slot.media_type,
                "updated_at": now,
                "last_event_seq": activity.seq if activity else None,
                "last_event_type": activity.event_type if activity else None,
                "asset_id": slot.selected_asset_id,
                "version_id": slot.selected_version_id,
            }
            pending_events.append(
                (
                    "runtime_snapshot_updated",
                    {
                        "execution_id": execution_id,
                        "node_id": slot.node_id,
                        "item_id": slot.item_id,
                        "slot_id": slot.slot_id,
                        "asset_id": slot.selected_asset_id,
                        "version_id": slot.selected_version_id,
                        "payload": {
                            "status": "completed",
                            "recovered_from_selected_version": True,
                        },
                    },
                )
            )
        for slot, activity in stale_slots:
            recovered_slot_ids.append(slot.slot_id)
            self._reset_stale_slot(slot, execution_id=execution_id, activity=activity, now=now)
            runtime = {
                **slot_runtime.get(slot.slot_id, {}),
                "slot_id": slot.slot_id,
                "node_id": slot.node_id,
                "item_id": slot.item_id,
                "status": "ready",
                "runtime_status": "ready",
                "slot_type": slot.slot_type,
                "media_type": slot.media_type,
                "updated_at": now,
                "last_event_seq": activity.seq if activity else None,
                "last_event_type": activity.event_type if activity else None,
                "recoverable": True,
            }
            slot_runtime[slot.slot_id] = runtime
            pending_events.append(
                (
                    "slot_recovered_ready",
                    {
                        "execution_id": execution_id,
                        "node_id": slot.node_id,
                        "item_id": slot.item_id,
                        "slot_id": slot.slot_id,
                        "payload": {
                            "recoverable": True,
                            "interrupted_execution_id": execution_id,
                            "last_runtime_event_seq": activity.seq if activity else None,
                            "last_runtime_event_type": activity.event_type if activity else None,
                        },
                    },
                )
            )
            pending_events.append(
                (
                    "runtime_snapshot_updated",
                    {
                        "execution_id": execution_id,
                        "node_id": slot.node_id,
                        "item_id": slot.item_id,
                        "slot_id": slot.slot_id,
                        "payload": {
                            "status": "ready",
                            "recoverable": True,
                        },
                    },
                )
            )

        self._workflow_store.save_workflow(workflow)
        if recovered_slot_ids:
            pending_events.append(
                (
                    "execution_interrupted",
                    {
                        "execution_id": execution_id,
                        "payload": {
                            "execution_id": execution_id,
                            "interrupted_slot_ids": recovered_slot_ids,
                            "recoverable": True,
                        },
                    },
                )
            )
        events_cursor = self._events.events_cursor(workflow.workflow_id)
        remaining_active, running_slot_ids, waiting_slot_ids = self._remaining_state_slot_ids(
            state,
            slot_runtime,
            task_by_slot=task_by_slot,
            recovered_slot_ids=recovered_slot_ids,
        )
        completed_slot_ids = self._completed_slot_ids(workflow, slot_runtime)
        failed_slot_ids = list(
            dict.fromkeys(
                [
                    *[str(slot_id) for slot_id in state.get("failed_slot_ids", [])],
                ]
            )
        )
        state_updates = {
            "slot_runtime": slot_runtime,
            "events_cursor": events_cursor,
            "metadata": {
                **dict(state.get("metadata") or {}),
                "recovered_interrupted_slot_ids": recovered_slot_ids,
                "recovered_completed_slot_ids": completed_recovery_slot_ids,
                "stale_provider_task_reconciliation_slot_ids": reconciliation_slot_ids,
                "interrupted_at": now,
            },
        }
        if remaining_active:
            self._executions.save_state(
                workflow.workflow_id,
                execution_id,
                {
                    **state,
                    **state_updates,
                    "running_slot_ids": running_slot_ids,
                    "waiting_slot_ids": waiting_slot_ids,
                    "failed_slot_ids": failed_slot_ids,
                    "updated_at": now,
                },
            )
        else:
            final_status = (
                "partial_failed"
                if completed_slot_ids and failed_slot_ids
                else "completed"
                if completed_slot_ids
                else "cancelled"
            )
            self._executions.finish(
                workflow.workflow_id,
                execution_id,
                status=final_status,
                completed_slot_ids=completed_slot_ids,
                failed_slot_ids=failed_slot_ids,
                waiting_slot_ids=[],
                running_slot_ids=[],
                state_updates=state_updates,
            )

        for event_type, event_kwargs in pending_events:
            self._events.append_event(workflow.workflow_id, event_type, **event_kwargs)
        if pending_events:
            persisted_state = self._executions.load_state(workflow.workflow_id, execution_id)
            if persisted_state is not None:
                self._executions.save_state(
                    workflow.workflow_id,
                    execution_id,
                    {
                        **persisted_state,
                        "events_cursor": self._events.events_cursor(workflow.workflow_id),
                    },
                )

        if remaining_active:
            return V2ExecutionRecoveryResult(
                workflow=workflow,
                recovered_slot_ids=recovered_slot_ids,
                execution_id=execution_id,
                trigger=trigger,
                changed=True,
                transitioned_slot_ids=[
                    *completed_recovery_slot_ids,
                    *recovered_slot_ids,
                ],
            )
        return V2ExecutionRecoveryResult(
            workflow=workflow,
            recovered_slot_ids=recovered_slot_ids,
            execution_id=execution_id,
            active_execution_cleared=True,
            trigger=trigger,
            changed=True,
            transitioned_slot_ids=[
                *completed_recovery_slot_ids,
                *recovered_slot_ids,
            ],
        )

    def _completed_active_slots(
        self,
        workflow: WorkflowV2,
        active_execution: dict[str, Any],
        *,
        latest_activity: dict[str, WorkflowV2Event],
    ) -> list[tuple[WorkflowSlotV2, WorkflowV2Event | None]]:
        completed: list[tuple[WorkflowSlotV2, WorkflowV2Event | None]] = []
        for slot_id, runtime in dict(active_execution.get("slot_runtime") or {}).items():
            if not isinstance(runtime, dict):
                continue
            slot = find_slot(workflow, str(slot_id))
            if slot is None:
                continue
            status = str(runtime.get("runtime_status") or runtime.get("status") or slot.status)
            if status not in ACTIVE_RECOVERY_STATUSES:
                continue
            if not slot.selected_asset_id or not slot.selected_version_id:
                continue
            completed.append((slot, latest_activity.get(slot.slot_id)))
        return completed

    def _stale_slots(
        self,
        workflow: WorkflowV2,
        active_execution: dict[str, Any],
        *,
        task_by_slot: dict[str, Any],
        latest_activity: dict[str, WorkflowV2Event],
    ) -> list[tuple[WorkflowSlotV2, WorkflowV2Event | None]]:
        stale: list[tuple[WorkflowSlotV2, WorkflowV2Event | None]] = []
        for slot_id, runtime in dict(active_execution.get("slot_runtime") or {}).items():
            if not isinstance(runtime, dict):
                continue
            slot = find_slot(workflow, str(slot_id))
            if slot is None:
                continue
            status = str(runtime.get("runtime_status") or runtime.get("status") or slot.status)
            if (
                status not in ACTIVE_RECOVERY_STATUSES
                and slot.status not in ACTIVE_RECOVERY_STATUSES
            ):
                continue
            if slot.slot_id in task_by_slot:
                continue
            activity = latest_activity.get(slot.slot_id)
            if activity is not None and activity.event_type in TERMINAL_SLOT_EVENTS:
                continue
            last_activity_at = _event_time(activity) or _parse_datetime(
                str(runtime.get("updated_at") or "")
            )
            if last_activity_at is None:
                continue
            if (utc_now() - last_activity_at).total_seconds() < self._timeout_seconds:
                continue
            stale.append((slot, activity))
        return stale

    def _reset_stale_slot(
        self,
        slot: WorkflowSlotV2,
        *,
        execution_id: str,
        activity: WorkflowV2Event | None,
        now: str,
    ) -> None:
        slot.status = "ready"
        slot.metadata.pop("error", None)
        slot.metadata.pop("provider_task_id", None)
        slot.metadata.pop("remote_task_id", None)
        slot.metadata.pop("waiting_reason", None)
        slot.metadata["recoverable"] = True
        slot.metadata["interrupted_execution_id"] = execution_id
        slot.metadata["interrupted_at"] = now
        slot.metadata["last_runtime_event_seq"] = activity.seq if activity else None
        slot.metadata["last_runtime_event_type"] = activity.event_type if activity else None

    def _remaining_state_slot_ids(
        self,
        state: dict[str, Any],
        slot_runtime: dict[str, dict[str, Any]],
        *,
        task_by_slot: dict[str, Any],
        recovered_slot_ids: list[str],
    ) -> tuple[list[str], list[str], list[str]]:
        recovered = set(recovered_slot_ids)
        active = self._remaining_active_slot_ids(slot_runtime, task_by_slot=task_by_slot)
        running = [
            str(slot_id)
            for slot_id in state.get("running_slot_ids", [])
            if str(slot_id) not in recovered
        ]
        waiting = [
            str(slot_id)
            for slot_id in state.get("waiting_slot_ids", [])
            if str(slot_id) not in recovered
        ]
        for slot_id in active:
            runtime = slot_runtime.get(slot_id, {})
            status = str(runtime.get("runtime_status") or runtime.get("status") or "")
            if status == "waiting":
                waiting.append(slot_id)
            else:
                running.append(slot_id)
        return (
            list(dict.fromkeys(active)),
            list(dict.fromkeys(running)),
            list(dict.fromkeys(waiting)),
        )

    def _remaining_active_slot_ids(
        self,
        slot_runtime: dict[str, dict[str, Any]],
        *,
        task_by_slot: dict[str, Any],
    ) -> list[str]:
        active: list[str] = []
        for slot_id, runtime in slot_runtime.items():
            status = str(runtime.get("runtime_status") or runtime.get("status") or "")
            if status in {"queued", "running"}:
                active.append(slot_id)
                continue
            if status in ACTIVE_PROVIDER_TASK_STATUSES and slot_id in task_by_slot:
                active.append(slot_id)
        return active

    def _completed_slot_ids(
        self,
        workflow: WorkflowV2,
        slot_runtime: dict[str, dict[str, Any]],
    ) -> list[str]:
        completed = [
            str(slot_id)
            for slot_id, runtime in slot_runtime.items()
            if runtime.get("status") == "completed"
        ]
        completed.extend(
            slot.slot_id
            for node in workflow.nodes
            for item in node.items
            if item.lifecycle_state == "active"
            for slot in item.slots
            if slot.status == "completed" or bool(slot.selected_asset_id)
        )
        return list(dict.fromkeys(completed))


def latest_runtime_activity_by_slot(events: list[WorkflowV2Event]) -> dict[str, WorkflowV2Event]:
    activity: dict[str, WorkflowV2Event] = {}
    for event in events:
        if not event.slot_id or event.event_type not in V2_RUNTIME_ACTIVITY_EVENTS:
            continue
        activity[event.slot_id] = event
    return activity


def _event_time(event: WorkflowV2Event | None) -> datetime | None:
    if event is None:
        return None
    return _parse_datetime(event.created_at)


def _provider_task_needs_reconciliation(
    task: Any,
    activity: WorkflowV2Event | None,
    *,
    stale_after_seconds: int,
) -> bool:
    if _provider_task_timed_out(task):
        return True
    latest_activity = max(
        (
            candidate
            for candidate in (
                _event_time(activity),
                _parse_datetime(str(getattr(task, "last_polled_at", "") or "")),
                _parse_datetime(str(getattr(task, "updated_at", "") or "")),
                _parse_datetime(str(getattr(task, "submitted_at", "") or "")),
            )
            if candidate is not None
        ),
        default=None,
    )
    if latest_activity is None:
        return True
    return (utc_now() - latest_activity).total_seconds() >= stale_after_seconds


def _provider_task_timed_out(task: Any) -> bool:
    metadata = getattr(task, "metadata", {})
    timeout_at = metadata.get("timeout_at") if isinstance(metadata, dict) else None
    timeout = _parse_datetime(str(timeout_at or ""))
    return timeout is not None and timeout <= utc_now()


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
