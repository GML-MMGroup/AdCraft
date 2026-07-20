from pathlib import Path
from datetime import datetime, timezone

from app.schemas.workflow_v2 import V2ProviderTask
from app.services.agent_trace import utc_now
from app.services.v2_provider_tasks import V2ProviderTaskStore
from app.services.v2_workflow_lock import v2_workflow_lock

TERMINAL_PROVIDER_TASK_STATUSES = {"completed", "failed", "cancelled"}
POLLABLE_PROVIDER_TASK_STATUSES = {"submitted", "running", "waiting"}


class V2ProviderTaskService(V2ProviderTaskStore):
    def __init__(
        self,
        data_dir: Path,
        *,
        poll_interval_seconds: int = 8,
        timeout_seconds: int = 3600,
    ) -> None:
        super().__init__(
            data_dir,
            poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds,
        )

    def list_nonterminal_tasks(
        self,
        workflow_id: str,
        *,
        execution_id: str | None = None,
    ) -> list[V2ProviderTask]:
        tasks = [
            task
            for task in self.list_tasks(workflow_id)
            if task.status not in TERMINAL_PROVIDER_TASK_STATUSES
        ]
        if execution_id is None:
            return tasks
        return [task for task in tasks if task.execution_id in {None, execution_id}]

    def list_due_tasks(
        self,
        workflow_id: str,
        *,
        execution_id: str | None = None,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> list[V2ProviderTask]:
        current_time = now or datetime.now(timezone.utc)
        tasks = [
            task
            for task in self.list_nonterminal_tasks(workflow_id, execution_id=execution_id)
            if task.status in POLLABLE_PROVIDER_TASK_STATUSES and _task_is_due(task, current_time)
        ]
        tasks.sort(key=lambda task: task.next_poll_at or task.updated_at)
        return tasks[:limit] if limit is not None else tasks

    def find_nonterminal_task_by_callback(
        self,
        workflow_id: str,
        *,
        provider: str,
        callback_id: str,
        remote_task_id: str,
    ) -> V2ProviderTask | None:
        normalized_provider = provider.strip().lower()
        for task in self.list_nonterminal_tasks(workflow_id):
            if str(task.provider or "").strip().lower() != normalized_provider:
                continue
            if task.remote_task_id != remote_task_id:
                continue
            if task.metadata.get("callback_id") != callback_id:
                continue
            return task
        return None

    def wake_task_for_callback(
        self,
        workflow_id: str,
        *,
        provider: str,
        callback_id: str,
        remote_task_id: str,
    ) -> V2ProviderTask | None:
        """Atomically make one matching nonterminal task eligible for authenticated polling."""

        with v2_workflow_lock(self._data_dir, workflow_id):
            task = self.find_nonterminal_task_by_callback(
                workflow_id,
                provider=provider,
                callback_id=callback_id,
                remote_task_id=remote_task_id,
            )
            if task is None:
                return None
            current_wake = task.metadata.get("callback_wake")
            if (
                isinstance(current_wake, dict)
                and current_wake.get("callback_id") == callback_id
                and current_wake.get("remote_task_id") == remote_task_id
            ):
                return task
            now = utc_now().isoformat()
            return self.save_task(
                task.model_copy(
                    update={
                        "updated_at": now,
                        "next_poll_at": now,
                        "metadata": {
                            **task.metadata,
                            "callback_wake": {
                                "callback_id": callback_id,
                                "remote_task_id": remote_task_id,
                                "received_at": now,
                            },
                            "waiting_reason": "provider_callback_received",
                        },
                    }
                )
            )


def _task_is_due(task: V2ProviderTask, now: datetime) -> bool:
    if not task.next_poll_at:
        return True
    try:
        due_at = datetime.fromisoformat(task.next_poll_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    return due_at <= now
