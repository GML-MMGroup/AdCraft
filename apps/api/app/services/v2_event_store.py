import json
from pathlib import Path
import threading
from typing import Any

from app.schemas.workflow_v2 import WorkflowV2Event, WorkflowV2EventListResponse
from app.services.agent_trace import utc_now
from app.services.v2_data_boundary import validate_v2_data_path
from app.services.v2_workflow_store import workflow_v2_runtime_dir

_EVENTS_LOCK = threading.RLock()


def workflow_v2_events_path(data_dir: Path, workflow_id: str) -> Path:
    return workflow_v2_runtime_dir(data_dir, workflow_id) / "events.json"


def workflow_v2_execution_events_path(
    data_dir: Path,
    workflow_id: str,
    execution_id: str,
) -> Path:
    return validate_v2_data_path(
        data_dir,
        workflow_v2_runtime_dir(data_dir, workflow_id)
        / "executions"
        / execution_id
        / "events.ndjson",
        operation="v2-execution-event-write",
    )


class V2EventStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

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
        with _EVENTS_LOCK:
            events = self.load_events(workflow_id)
            event_payload = payload or {}
            resolved_execution_id = execution_id
            if resolved_execution_id is None and isinstance(event_payload.get("execution_id"), str):
                resolved_execution_id = event_payload["execution_id"]
            event = WorkflowV2Event(
                seq=(events[-1].seq + 1) if events else 1,
                event_type=event_type,
                workflow_id=workflow_id,
                execution_id=resolved_execution_id,
                node_id=node_id,
                item_id=item_id,
                slot_id=slot_id,
                asset_id=asset_id,
                version_id=version_id,
                created_at=utc_now().isoformat(),
                payload=event_payload,
            )
            events.append(event)
            path = workflow_v2_events_path(self._data_dir, workflow_id)
            validate_v2_data_path(self._data_dir, path, operation="v2-runtime-event-write")
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(
                    [item.model_dump(mode="json") for item in events],
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            tmp_path.replace(path)
            if resolved_execution_id:
                execution_events_path = workflow_v2_execution_events_path(
                    self._data_dir,
                    workflow_id,
                    resolved_execution_id,
                )
                execution_events_path.parent.mkdir(parents=True, exist_ok=True)
                with execution_events_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False))
                    handle.write("\n")
            return event

    def load_events(self, workflow_id: str) -> list[WorkflowV2Event]:
        with _EVENTS_LOCK:
            path = workflow_v2_events_path(self._data_dir, workflow_id)
            if not path.exists():
                return []
            content = path.read_text(encoding="utf-8")
            if not content.strip():
                return []
            return [WorkflowV2Event.model_validate(item) for item in json.loads(content)]

    def list_events(self, workflow_id: str, after_seq: int = 0) -> WorkflowV2EventListResponse:
        all_events = self.load_events(workflow_id)
        events_cursor = all_events[-1].seq if all_events else 0
        events = [event for event in all_events if event.seq > after_seq]
        return WorkflowV2EventListResponse(
            workflow_id=workflow_id,
            events=events,
            events_cursor=events_cursor,
            next_after_seq=events_cursor,
        )

    def events_cursor(self, workflow_id: str) -> int:
        events = self.load_events(workflow_id)
        return events[-1].seq if events else 0
