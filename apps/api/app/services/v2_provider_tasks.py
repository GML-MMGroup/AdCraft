import json
from pathlib import Path
from datetime import timedelta
from uuid import uuid4

from app.schemas.workflow_v2 import (
    V2GenerationPlan,
    V2ProviderResult,
    V2ProviderTask,
    WorkflowItemV2,
    WorkflowSlotV2,
    WorkflowV2,
)
from app.services.agent_trace import utc_now
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_data_boundary import validate_v2_data_path
from app.services.v2_workflow_store import workflow_v2_runtime_dir


def v2_provider_tasks_dir(data_dir: Path, workflow_id: str) -> Path:
    return validate_v2_data_path(
        data_dir,
        workflow_v2_runtime_dir(data_dir, workflow_id) / "provider_tasks",
        operation="v2-provider-tasks-dir",
    )


def v2_provider_task_path(data_dir: Path, workflow_id: str, task_id: str) -> Path:
    return v2_provider_tasks_dir(data_dir, workflow_id) / f"{task_id}.json"


class V2ProviderTaskStore:
    def __init__(
        self,
        data_dir: Path,
        *,
        poll_interval_seconds: int = 8,
        timeout_seconds: int = 3600,
    ) -> None:
        self._data_dir = data_dir
        self._poll_interval_seconds = poll_interval_seconds
        self._timeout_seconds = timeout_seconds

    def create_waiting_task(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        plan: V2GenerationPlan,
        result: V2ProviderResult,
        *,
        select_generated: bool,
        source_action: str,
        execution_id: str | None = None,
        attempt_id: str | None = None,
        input_fingerprint: str | None = None,
    ) -> V2ProviderTask:
        now_dt = utc_now()
        now = now_dt.isoformat()
        next_poll_at = (now_dt + timedelta(seconds=self._poll_interval_seconds)).isoformat()
        timeout_at = (now_dt + timedelta(seconds=self._timeout_seconds)).isoformat()
        provider_payload = _merge_provider_payload_snapshots(
            plan.provider_payload,
            result.provider_payload_snapshot,
        )
        task_id = f"task_{uuid4().hex[:12]}"
        version_id = f"ver_{uuid4().hex[:12]}"
        asset_id = f"{workflow.workflow_id}_{slot.slot_id.replace(':', '_')}_{version_id}"
        task = V2ProviderTask(
            task_id=task_id,
            workflow_id=workflow.workflow_id,
            execution_id=execution_id,
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            asset_id=asset_id,
            version_id=version_id,
            provider=result.provider,
            provider_model=result.provider_model,
            remote_task_id=result.remote_task_id,
            status="submitted",
            submitted_at=now,
            updated_at=now,
            next_poll_at=next_poll_at,
            provider_payload_snapshot=provider_payload,
            metadata={
                **sanitize_context_for_llm_text(result.metadata),
                "canonical_provider_payload": sanitize_context_for_llm_text(
                    provider_payload.get("canonical_provider_payload") or provider_payload
                ),
                "media_type": slot.media_type,
                "slot_type": slot.slot_type,
                "reference_asset_ids": list(result.reference_asset_ids or plan.reference_asset_ids),
                "select_generated": select_generated,
                "source_action": source_action,
                "attempt_id": attempt_id,
                "input_fingerprint": input_fingerprint,
                "generation_plan_snapshot": plan.model_dump(mode="json"),
                "duration_seconds": item.duration_seconds or workflow.duration_seconds,
                "segment_order": item.shot_index or 1,
                "scene_id": item.item_id,
                "aspect_ratio": workflow.aspect_ratio,
                "timeout_at": timeout_at,
            },
        )
        return self.save_task(task)

    def save_task(self, task: V2ProviderTask) -> V2ProviderTask:
        path = v2_provider_task_path(self._data_dir, task.workflow_id, task.task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.stem}.{uuid4().hex}.tmp")
        tmp_path.write_text(
            json.dumps(task.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)
        return task

    def load_task(self, workflow_id: str, task_id: str) -> V2ProviderTask | None:
        path = v2_provider_task_path(self._data_dir, workflow_id, task_id)
        if not path.exists():
            return None
        return V2ProviderTask.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def list_tasks(
        self,
        workflow_id: str,
        *,
        slot_id: str | None = None,
    ) -> list[V2ProviderTask]:
        root = v2_provider_tasks_dir(self._data_dir, workflow_id)
        if not root.exists():
            return []
        tasks = [
            V2ProviderTask.model_validate(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(root.glob("*.json"))
        ]
        if slot_id is not None:
            tasks = [task for task in tasks if task.slot_id == slot_id]
        return tasks

    def mark_poll_result(
        self,
        task: V2ProviderTask,
        result: V2ProviderResult,
    ) -> V2ProviderTask:
        now = utc_now().isoformat()
        status = (
            "completed"
            if result.status == "completed"
            else ("failed" if result.status == "failed" else "waiting")
        )
        next_poll_at = None
        if status == "waiting":
            requested_delay = result.metadata.get("next_poll_delay_seconds")
            try:
                delay_seconds = max(0, min(60, int(requested_delay)))
            except (TypeError, ValueError):
                delay_seconds = self._poll_interval_seconds
            next_poll_at = (utc_now() + timedelta(seconds=delay_seconds)).isoformat()
        download_attempted = bool(result.metadata.get("download_attempted"))
        provider_retry = result.metadata.get("waiting_reason") == "retryable_provider_poll_error"
        task = task.model_copy(
            update={
                "status": status,
                "updated_at": now,
                "completed_at": now if status in {"completed", "failed"} else None,
                "poll_count": task.poll_count + 1,
                "attempt_count": task.attempt_count + 1,
                "retry_count": task.retry_count + (1 if provider_retry else 0),
                "download_attempt_count": task.download_attempt_count
                + (1 if download_attempted else 0),
                "last_polled_at": now,
                "next_poll_at": next_poll_at,
                "last_error_code": result.error_code,
                "last_error_message": result.error_message,
                "remote_task_id": result.remote_task_id or task.remote_task_id,
                "provider": result.provider or task.provider,
                "provider_model": result.provider_model or task.provider_model,
                "provider_payload_snapshot": _merge_provider_payload_snapshots(
                    task.provider_payload_snapshot,
                    result.provider_payload_snapshot,
                ),
                "metadata": {
                    **task.metadata,
                    **sanitize_context_for_llm_text(result.metadata),
                },
            }
        )
        return self.save_task(task)

    def mark_expired_remote_reconciliation_started(
        self,
        task: V2ProviderTask,
    ) -> V2ProviderTask:
        """Durably reserve the one final remote query allowed after expiry."""

        existing = task.metadata.get("expired_remote_reconciliation")
        if isinstance(existing, dict) and existing.get("started_at"):
            return task
        now = utc_now().isoformat()
        return self.save_task(
            task.model_copy(
                update={
                    "updated_at": now,
                    "metadata": {
                        **task.metadata,
                        "expired_remote_reconciliation": {
                            "started_at": now,
                            "original_timeout_at": task.metadata.get("timeout_at"),
                        },
                    },
                }
            )
        )

    def request_stale_recovery_reconciliation(
        self,
        task: V2ProviderTask,
    ) -> V2ProviderTask:
        """Make a stale nonterminal task due for the recovery poll loop once."""

        existing = task.metadata.get("stale_recovery_reconciliation")
        if isinstance(existing, dict) and existing.get("requested_at"):
            return task
        now = utc_now().isoformat()
        return self.save_task(
            task.model_copy(
                update={
                    "updated_at": now,
                    "next_poll_at": now,
                    "metadata": {
                        **task.metadata,
                        "stale_recovery_reconciliation": {
                            "requested_at": now,
                            "last_polled_at": task.last_polled_at,
                            "timeout_at": task.metadata.get("timeout_at"),
                        },
                        "waiting_reason": "stale_provider_task_reconciliation",
                    },
                }
            )
        )

    def reopen_for_result_retrieval(self, task: V2ProviderTask) -> V2ProviderTask:
        recovery = task.metadata.get("historical_result_recovery")
        recovery_metadata = dict(recovery) if isinstance(recovery, dict) else {}
        if recovery_metadata.get("exhausted") is True or recovery_metadata.get("started_at"):
            return task
        now_dt = utc_now()
        original_timeout = task.metadata.get("timeout_at")
        recovery_metadata.setdefault("original_timeout_at", original_timeout)
        recovery_metadata.setdefault("started_at", now_dt.isoformat())
        updated = task.model_copy(
            update={
                "status": "waiting",
                "updated_at": now_dt.isoformat(),
                "completed_at": None,
                "next_poll_at": now_dt.isoformat(),
                "download_attempt_count": 0,
                "last_error_code": None,
                "last_error_message": None,
                "metadata": {
                    **task.metadata,
                    "timeout_at": (now_dt + timedelta(seconds=self._timeout_seconds)).isoformat(),
                    "historical_result_recovery": recovery_metadata,
                    "waiting_reason": "historical_provider_result_recovery",
                    "recovery_source": "historical_provider_result",
                },
            }
        )
        return self.save_task(updated)

    def mark_historical_result_recovery_exhausted(self, task: V2ProviderTask) -> V2ProviderTask:
        recovery = task.metadata.get("historical_result_recovery")
        if not isinstance(recovery, dict):
            return task
        if recovery.get("exhausted") is True:
            return task
        return self.save_task(
            task.model_copy(
                update={
                    "metadata": {
                        **task.metadata,
                        "historical_result_recovery": {
                            **recovery,
                            "exhausted": True,
                        },
                    }
                }
            )
        )


def _merge_provider_payload_snapshots(
    *payloads: dict[str, object] | None,
) -> dict[str, object]:
    merged: dict[str, object] = {}
    canonical_lineage: dict[str, object] | None = None
    for payload in payloads:
        if payload:
            if canonical_lineage is None and isinstance(payload.get("generation_lineage"), dict):
                canonical_lineage = payload["generation_lineage"]
            merged.update(payload)
    if canonical_lineage is not None:
        merged["generation_lineage"] = canonical_lineage
    return sanitize_context_for_llm_text(merged)
