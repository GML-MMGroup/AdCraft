"""Domain facade for persisted V2 runtime events."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.persistence.database import create_v2_database
from app.persistence.event_repository import EventRepository
from app.schemas.v2_persistence import V2EventInsert
from app.schemas.workflow_v2 import WorkflowV2Event, WorkflowV2EventListResponse
from app.services.agent_trace import utc_now


class V2EventStore:
    """Preserves the V2 event contract while delegating persistence to SQLite."""

    def __init__(self, data_dir: Path) -> None:
        self._repository = EventRepository(create_v2_database(data_dir))

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
        event_payload = payload or {}
        resolved_execution_id = execution_id
        if resolved_execution_id is None and isinstance(event_payload.get("execution_id"), str):
            resolved_execution_id = event_payload["execution_id"]
        return self._repository.append(
            V2EventInsert(
                workflow_id=workflow_id,
                event_type=event_type,
                execution_id=resolved_execution_id,
                node_id=node_id,
                item_id=item_id,
                slot_id=slot_id,
                asset_id=asset_id,
                version_id=version_id,
                created_at=utc_now().isoformat(),
                payload=event_payload,
            )
        )

    def load_events(self, workflow_id: str) -> list[WorkflowV2Event]:
        return self._repository.list_after(workflow_id)

    def list_events(self, workflow_id: str, after_seq: int = 0) -> WorkflowV2EventListResponse:
        events = self._repository.list_after(workflow_id, after_seq=after_seq)
        events_cursor = self._repository.max_seq(workflow_id)
        return WorkflowV2EventListResponse(
            workflow_id=workflow_id,
            events=events,
            events_cursor=events_cursor,
            next_after_seq=events_cursor,
        )

    def events_cursor(self, workflow_id: str) -> int:
        return self._repository.max_seq(workflow_id)
