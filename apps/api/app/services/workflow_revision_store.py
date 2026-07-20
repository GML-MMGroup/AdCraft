import json
from pathlib import Path
from typing import Any

from app.schemas.workflow_revisions import WorkflowRevisionState
from app.services.agent_trace import utc_now

RESERVED_REVISION_METADATA_KEYS = {
    "source_type",
    "source_conversation_id",
    "source_action_id",
    "agent_conversation_id",
    "agent_action_id",
}


class WorkflowRevisionStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def revision_states(self, workflow_id: str, node_id: str) -> list[WorkflowRevisionState]:
        revision_root = self.revision_root(workflow_id, node_id)
        if not revision_root.exists():
            return []
        states = []
        for state_path in sorted(revision_root.glob("rev_*/state.json")):
            try:
                states.append(
                    WorkflowRevisionState.model_validate_json(
                        state_path.read_text(encoding="utf-8")
                    )
                )
            except ValueError:
                continue
        return sorted(states, key=lambda item: item.started_at, reverse=True)

    def write_state(self, state: WorkflowRevisionState) -> None:
        path = self.state_path(state.workflow_id, state.node_id, state.revision_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)

    def append_event(
        self, state: WorkflowRevisionState, event_type: str, payload: dict[str, Any]
    ) -> None:
        path = self.events_path(state.workflow_id, state.node_id, state.revision_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(
                json.dumps(
                    {
                        "event_type": event_type,
                        "workflow_id": state.workflow_id,
                        "node_id": state.node_id,
                        "node_type": state.node_type,
                        "revision_id": state.revision_id,
                        "created_at": utc_now().isoformat(),
                        "payload": payload,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    def revision_root(self, workflow_id: str, node_id: str) -> Path:
        return self._data_dir / "runs" / workflow_id / "nodes" / node_id / "revisions"

    def state_path(self, workflow_id: str, node_id: str, revision_id: str) -> Path:
        return self.revision_root(workflow_id, node_id) / revision_id / "state.json"

    def events_path(self, workflow_id: str, node_id: str, revision_id: str) -> Path:
        return self.revision_root(workflow_id, node_id) / revision_id / "events.ndjson"

    def relative_state_path(self, workflow_id: str, node_id: str, revision_id: str) -> str:
        return (
            Path("runs")
            / workflow_id
            / "nodes"
            / node_id
            / "revisions"
            / revision_id
            / "state.json"
        ).as_posix()

    def relative_events_path(self, workflow_id: str, node_id: str, revision_id: str) -> str:
        return (
            Path("runs")
            / workflow_id
            / "nodes"
            / node_id
            / "revisions"
            / revision_id
            / "events.ndjson"
        ).as_posix()


def public_revision_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in metadata.items()
        if str(key) not in RESERVED_REVISION_METADATA_KEYS
    }


def server_revision_source_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    allowed = {
        "source_type",
        "source_conversation_id",
        "source_action_id",
        "source_item_id",
        "source_item_prompt",
    }
    return {
        key: value for key, value in metadata.items() if key in allowed and value not in (None, "")
    }


_revision_states = WorkflowRevisionStore.revision_states
_write_state = WorkflowRevisionStore.write_state
_append_event = WorkflowRevisionStore.append_event
_revision_root = WorkflowRevisionStore.revision_root
_state_path = WorkflowRevisionStore.state_path
_events_path = WorkflowRevisionStore.events_path
_relative_state_path = WorkflowRevisionStore.relative_state_path
_relative_events_path = WorkflowRevisionStore.relative_events_path
_public_revision_metadata = public_revision_metadata
_server_revision_source_metadata = server_revision_source_metadata
