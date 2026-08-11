"""Lease-safe provider polling, download recovery, and output publication."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.persistence.agent_canvas_runtime_repository import (
    AgentCanvasRuntimeRepository,
)
from app.persistence.event_repository import EventRepository
from app.schemas.agent_canvas import CanvasNodeErrorV2, CanvasNodeV2
from app.schemas.agent_canvas_runtime import (
    CanvasProviderTaskV2,
    NodeExecutionLeaseV2,
    ResolvedModelExecutionV1,
    EffectiveMediaParameterSnapshotV2,
)
from app.services.agent_canvas_node_execution import (
    GeneratedMediaPayload,
    NodeExecutionContext,
)
from app.services.agent_canvas_execution_state import AgentCanvasExecutionStateMachine
from app.schemas.v2_persistence import V2EventInsert


@dataclass(frozen=True, slots=True)
class ProviderPollResult:
    status: str
    remote_task_id: str | None = None
    result_descriptor: dict[str, object] | None = None
    error_code: str | None = None
    error_message: str | None = None


Poller = Callable[[CanvasProviderTaskV2], ProviderPollResult]
Downloader = Callable[[CanvasProviderTaskV2], GeneratedMediaPayload]
Publisher = Callable[[NodeExecutionContext, GeneratedMediaPayload, str], str]
BatchCallback = Callable[[tuple[str, ...]], None]
NodeReadyCallback = Callable[[CanvasNodeV2], tuple[str, ...] | None]


class ProviderTaskRecoveryService:
    """Reconcile recoverable tasks independently, then advance schedulers once."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        runtime: AgentCanvasRuntimeRepository,
        *,
        poller: Poller,
        downloader: Downloader,
        media_publisher: Publisher,
        on_batch_reconciled: BatchCallback | None = None,
        on_node_ready: NodeReadyCallback | None = None,
        state_machine: AgentCanvasExecutionStateMachine | None = None,
        owner_id: str = "provider-recovery",
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._workflows = workflows
        self._runtime = runtime
        self._poller = poller
        self._downloader = downloader
        self._media_publisher = media_publisher
        self._on_batch_reconciled = on_batch_reconciled
        self._on_node_ready = on_node_ready
        self._state_machine = state_machine or AgentCanvasExecutionStateMachine()
        self._owner_id = owner_id
        self._clock = clock

    def recover_due_tasks(self) -> tuple[str, ...]:
        reconciled: list[str] = []
        execution_ids: set[str] = set()
        for task in self._runtime.list_recoverable_tasks():
            now = self._clock()
            if task.next_poll_at is not None and task.next_poll_at > now:
                continue
            try:
                if self._recover_one(task):
                    reconciled.append(task.task_id)
                    execution_ids.add(task.execution_id)
            except Exception as error:
                self._record_retryable_error(task, error)
                execution_ids.add(task.execution_id)
        for execution_id in execution_ids:
            self._state_machine.reconcile(self._runtime, execution_id, now=self._clock())
        if execution_ids and self._on_batch_reconciled is not None:
            self._on_batch_reconciled(tuple(sorted(execution_ids)))
        return tuple(reconciled)

    def _recover_one(self, task: CanvasProviderTaskV2) -> bool:
        now = self._clock()
        lease = self._runtime.claim_lease(
            task.execution_id,
            task.node_id,
            owner_id=self._owner_id,
            now=now,
            ttl=timedelta(seconds=60),
        )
        if lease is None:
            return False
        poll = self._poller(task)
        remote_task_id = poll.remote_task_id or task.remote_task_id
        result_descriptor = _merge_result_descriptor(task, poll)
        if poll.status in {"submitted", "waiting", "running"}:
            if task.recovery_deadline <= now:
                self._fail_task(
                    task,
                    lease,
                    status="failed",
                    remote_task_id=remote_task_id,
                    code="provider_recovery_exhausted",
                    message="Provider task recovery deadline was exhausted.",
                )
                return True
            waiting = task.model_copy(
                update={
                    "remote_task_id": remote_task_id,
                    "status": "waiting",
                    "lease_generation": lease.generation,
                    "next_poll_at": now + timedelta(seconds=8),
                    "result_descriptor": result_descriptor,
                    "error": None,
                }
            )
            if not self._runtime.put_provider_task(waiting, now=now):
                self._runtime.complete_lease(lease, now=now)
                return False
            self._runtime.update_member(
                task.execution_id,
                task.node_id,
                state="running",
                phase="waiting_provider",
                provider_task_id=task.task_id,
                now=now,
                event_type="provider_task_waiting",
            )
            self._runtime.complete_lease(lease, now=now)
            return True
        if poll.status in {"failed", "cancelled"}:
            self._fail_task(
                task,
                lease,
                status=poll.status,
                remote_task_id=remote_task_id,
                code=poll.error_code or "provider_task_failed",
                message=poll.error_message or "Provider task failed.",
            )
            return True
        if poll.status != "succeeded":
            raise RuntimeError("provider_poll_status_invalid")
        current = task.model_copy(
            update={
                "remote_task_id": remote_task_id,
                "status": "recovering",
                "lease_generation": lease.generation,
                "result_descriptor": result_descriptor,
                "error": None,
            }
        )
        if not self._runtime.put_provider_task(current, now=now):
            self._runtime.complete_lease(lease, now=now)
            return False
        self._runtime.record_provider_task_event(
            current,
            event_type="provider_result_download_waiting",
            now=now,
            payload={"status": "recovering"},
        )
        try:
            payload = self._downloader(current)
        except Exception as error:
            source_code = getattr(error, "code", None)
            code = "provider_result_download_failed"
            if isinstance(error, TimeoutError) or source_code == (
                "provider_result_download_timeout"
            ):
                code = "provider_result_download_timeout"
            raise V2PersistenceError(
                code,
                "Provider result download did not complete.",
                stage="provider_result_download",
                details={"source_code": str(source_code)} if source_code else None,
            ) from error
        node = self._workflows.get_node(task.workflow_id, task.node_id)
        member = next(
            item
            for item in self._runtime.list_members(task.execution_id)
            if item.node_id == task.node_id
        )
        stored_resolution = current.result_descriptor.get("model_resolution")
        resolution = (
            ResolvedModelExecutionV1.model_validate(stored_resolution)
            if isinstance(stored_resolution, dict)
            else None
        )
        effective_parameters = member.effective_parameters
        snapshot_id = (
            member.parameter_compilation_snapshot_id
            or str(current.result_descriptor.get("parameter_compilation_snapshot_id") or "")
            or None
        )
        if effective_parameters is None and snapshot_id is not None:
            snapshot = self._runtime.get_parameter_compilation_snapshot(snapshot_id)
            effective_parameters = EffectiveMediaParameterSnapshotV2(
                requested=snapshot.requested_parameters,
                effective=snapshot.effective_parameters,
                normalizations=snapshot.normalizations,
                parameter_compilation_snapshot_id=snapshot.snapshot_id,
                provider=(resolution.provider_id if resolution is not None else task.provider),
                model_id=(
                    resolution.provider_model_id if resolution is not None else snapshot.model_ref
                ),
                capability_revision=snapshot.capability_revision,
            )
        if effective_parameters is not None:
            node = node.model_copy(update={"parameters": effective_parameters.requested})
        context = NodeExecutionContext(
            execution_id=task.execution_id,
            node=node,
            inputs=(),
            model_id=resolution.provider_model_id if resolution is not None else None,
            provider_id=resolution.provider_id if resolution is not None else None,
            model_resolution=resolution,
            effective_parameters=effective_parameters,
        )
        fingerprint = f"provider-task:{task.task_id}"
        asset_id = self._media_publisher(context, payload, fingerprint)
        if not self._state_machine.transition_member(
            self._runtime,
            member,
            state="succeeded",
            phase=None,
            provider_task_id=task.task_id,
            now=now,
            expected_lease_generation=lease.generation,
        ):
            self._runtime.complete_lease(lease, now=now)
            return False
        published_node = self._workflows.publish_node_output(
            task.workflow_id,
            task.node_id,
            execution_id=task.execution_id,
            updated_at=now,
            output_asset_id=asset_id,
        )
        if self._on_node_ready is not None:
            created_node_ids = self._on_node_ready(published_node) or ()
            self._runtime.add_members(task.execution_id, created_node_ids, now=now)
        completed = current.model_copy(
            update={
                "status": "succeeded",
                "next_poll_at": None,
                "error": None,
            }
        )
        if not self._runtime.put_provider_task(completed, now=now):
            self._runtime.complete_lease(lease, now=now)
            return False
        self._runtime.record_provider_task_event(
            completed,
            event_type="provider_result_download_completed",
            now=now,
            payload={"asset_id": asset_id},
        )
        self._runtime.complete_lease(lease, now=now)
        return True

    def _fail_task(
        self,
        task: CanvasProviderTaskV2,
        lease: NodeExecutionLeaseV2,
        *,
        status: str,
        remote_task_id: str | None,
        code: str,
        message: str,
    ) -> None:
        now = self._clock()
        error = CanvasNodeErrorV2(
            code=code,
            message=message,
            retryable=False,
        )
        failed = task.model_copy(
            update={
                "remote_task_id": remote_task_id,
                "status": status,
                "lease_generation": lease.generation,
                "next_poll_at": None,
                "error": error,
            }
        )
        if not self._runtime.put_provider_task(failed, now=now):
            self._runtime.complete_lease(lease, now=now)
            return
        member = next(
            item
            for item in self._runtime.list_members(task.execution_id)
            if item.node_id == task.node_id
        )
        if member.state == "succeeded" or not self._state_machine.transition_member(
            self._runtime,
            member,
            state="failed",
            phase=None,
            provider_task_id=task.task_id,
            now=now,
            error=error,
            expected_lease_generation=lease.generation,
        ):
            self._runtime.complete_lease(lease, now=now)
            return
        self._workflows.set_node_runtime_state(
            task.workflow_id,
            task.node_id,
            status="failed",
            updated_at=now,
            error=error,
            execution_id=task.execution_id,
            event_type="node_failed",
            event_payload={"code": error.code},
        )
        self._runtime.complete_lease(lease, now=now)

    def _record_retryable_error(
        self,
        task: CanvasProviderTaskV2,
        error: Exception,
    ) -> None:
        now = self._clock()
        current = self._runtime.get_provider_task(task.task_id)
        if current.status in {"succeeded", "failed", "cancelled"}:
            return
        detail = CanvasNodeErrorV2(
            code=getattr(error, "code", "provider_recovery_failed"),
            message=str(error),
            retryable=True,
        )
        recovering = current.model_copy(
            update={
                "status": "recovering",
                "next_poll_at": now + timedelta(seconds=8),
                "error": detail,
            }
        )
        if not self._runtime.put_provider_task(recovering, now=now):
            return
        if detail.code.startswith("provider_result_download_"):
            self._runtime.record_provider_task_event(
                recovering,
                event_type="provider_result_download_failed",
                now=now,
                payload={
                    "code": detail.code,
                    "retryable": True,
                },
            )
        self._runtime.update_member(
            task.execution_id,
            task.node_id,
            state="running",
            phase="recovering",
            provider_task_id=task.task_id,
            now=now,
            error=detail,
            event_type="provider_task_recovering",
            event_payload={"code": detail.code},
        )


def _merge_result_descriptor(
    task: CanvasProviderTaskV2,
    poll: ProviderPollResult,
) -> dict[str, object]:
    """Merge remote progress without replacing the attempt's frozen model."""

    merged = dict(task.result_descriptor)
    merged.update(poll.result_descriptor or {})
    if "model_resolution" in task.result_descriptor:
        merged["model_resolution"] = task.result_descriptor["model_resolution"]
    return merged


class AgentCanvasProviderPollLoop:
    """Keep later poll cycles available after one unexpected batch failure."""

    def __init__(
        self,
        runtime: AgentCanvasRuntimeRepository,
        events: EventRepository,
        recover: Callable[[], tuple[str, ...]],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._runtime = runtime
        self._events = events
        self._recover = recover
        self._clock = clock

    def run_cycle(self) -> bool:
        try:
            self._recover()
            return True
        except Exception as error:
            now = self._clock()
            for execution in self._runtime.list_active_executions():
                self._events.append(
                    V2EventInsert(
                        workflow_id=execution.workflow_id,
                        execution_id=execution.execution_id,
                        event_type="provider_poll_loop_error",
                        created_at=now.isoformat(),
                        payload={
                            "code": getattr(error, "code", "provider_poll_loop_failed"),
                            "retryable": True,
                        },
                    )
                )
            return False
