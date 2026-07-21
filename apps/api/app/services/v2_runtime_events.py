from pathlib import Path
from typing import Any

from app.schemas.workflow_v2 import (
    V2ProviderTask,
    WorkflowV2,
    WorkflowV2Event,
    WorkflowV2EventListResponse,
    WorkflowV2RuntimeSnapshot,
)
from app.services.v2_event_store import V2EventStore
from app.services.v2_execution_service import V2ExecutionService
from app.services.v2_runtime_snapshot_service import V2RuntimeSnapshotService

__all__ = ["V2RuntimeEventService"]


class V2RuntimeEventService:
    """Compatibility facade for older callers during runtime service extraction."""

    def __init__(self, data_dir: Path) -> None:
        self._event_store = V2EventStore(data_dir)
        self._execution_service = V2ExecutionService(data_dir)
        self._snapshot_service = V2RuntimeSnapshotService(
            data_dir,
            event_store=self._event_store,
        )

    def append_event(
        self,
        workflow_id: str,
        event_type: str,
        *,
        node_id: str | None = None,
        item_id: str | None = None,
        slot_id: str | None = None,
        asset_id: str | None = None,
        version_id: str | None = None,
        execution_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> WorkflowV2Event:
        return self._event_store.append_event(
            workflow_id,
            event_type,
            node_id=node_id,
            item_id=item_id,
            slot_id=slot_id,
            asset_id=asset_id,
            version_id=version_id,
            execution_id=execution_id,
            payload=payload,
        )

    def load_events(self, workflow_id: str) -> list[WorkflowV2Event]:
        return self._event_store.load_events(workflow_id)

    def list_events(self, workflow_id: str, after_seq: int = 0) -> WorkflowV2EventListResponse:
        return self._event_store.list_events(workflow_id, after_seq=after_seq)

    def events_cursor(self, workflow_id: str) -> int:
        return self._event_store.events_cursor(workflow_id)

    def runtime_snapshot(
        self,
        workflow: WorkflowV2,
        *,
        active_execution: dict[str, Any] | None = None,
        provider_tasks: list[V2ProviderTask] | None = None,
    ) -> WorkflowV2RuntimeSnapshot:
        return self._snapshot_service.build_snapshot(
            workflow,
            active_execution=active_execution,
            provider_tasks=provider_tasks,
        )

    def write_execution_record(
        self,
        workflow_id: str,
        *,
        mode: str,
        status: str,
        completed_slot_ids: list[str] | None = None,
        failed_slot_ids: list[str] | None = None,
        waiting_slot_ids: list[str] | None = None,
        running_slot_ids: list[str] | None = None,
        slot_transitions: list[dict[str, Any]] | None = None,
        source_execution_id: str | None = None,
    ) -> None:
        self._execution_service.write_record(
            workflow_id,
            mode=mode,
            status=status,
            completed_slot_ids=completed_slot_ids,
            failed_slot_ids=failed_slot_ids,
            waiting_slot_ids=waiting_slot_ids,
            running_slot_ids=running_slot_ids,
            slot_transitions=slot_transitions,
            events_cursor=self.events_cursor(workflow_id),
            source_execution_id=source_execution_id,
        )
