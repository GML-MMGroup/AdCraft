import json
from pathlib import Path
from typing import Any, Callable

from app.schemas.workflow_revisions import WorkflowRevisionState
from app.services.agent_trace import utc_now
from app.services.canvas_runtime_events import CanvasRuntimeEventService
from app.services.workflow_revision_acceptance import (
    active_asset_ids_for_revision_target,
    previous_active_asset_ids,
    revision_candidate_asset_ids,
    revision_error_code,
    revision_has_quality_warning,
    revision_quality_issue_count,
    revision_quality_status,
    revision_target_resource_id,
)


class WorkflowRevisionEventPublisher:
    def __init__(
        self,
        data_dir: Path,
        *,
        revision_states: Callable[[str, str], list[WorkflowRevisionState]],
    ) -> None:
        self._data_dir = data_dir
        self._canvas_events = CanvasRuntimeEventService(data_dir)
        self._revision_states = revision_states

    def emit_revision_status_changed(
        self,
        state: WorkflowRevisionState,
        *,
        waiting_reason: str | None = None,
    ) -> None:
        if state.generation_status == "waiting" and not waiting_reason:
            waiting_reason = "provider_task_pending"
        self.append_canvas_event(
            state,
            "revision_status_changed",
            {
                "generation_status": state.generation_status or state.status,
                "acceptance_status": state.acceptance_status,
                "visibility_status": state.visibility_status,
                "waiting_reason": waiting_reason,
                "error": state.error,
                "error_code": revision_error_code(state),
                "refresh": ["revision"],
            },
        )

    def emit_candidate_created(self, state: WorkflowRevisionState) -> None:
        self.append_canvas_event(
            state,
            "candidate_created",
            {
                "candidate_asset_ids": revision_candidate_asset_ids(state),
                "candidate_count": 1 if state.candidate_assets else 0,
                "candidate_warning_count": 1 if revision_has_quality_warning(state) else 0,
                "refresh": ["revision", "asset_history", "candidate_summary"],
            },
            resource_type="candidate",
        )

    def emit_candidate_quality_updated(self, state: WorkflowRevisionState) -> None:
        self.append_canvas_event(
            state,
            "candidate_quality_updated",
            {
                "quality_status": revision_quality_status(state),
                "issue_count": revision_quality_issue_count(state),
                "refresh": ["revision", "candidate_summary"],
            },
            resource_type="candidate",
        )

    def emit_candidate_accepted(self, state: WorkflowRevisionState) -> None:
        self.append_canvas_event(
            state,
            "candidate_accepted",
            {
                "active_asset_ids": revision_candidate_asset_ids(state),
                "candidate_asset_ids": revision_candidate_asset_ids(state),
                "previous_active_asset_ids": previous_active_asset_ids(state),
                "affected_downstream_node_ids": state.affected_downstream_nodes,
                "refresh": [
                    "revision",
                    "asset_history",
                    "node_assets",
                    "workflow_graph",
                    "resolved_inputs",
                ],
            },
            resource_type="candidate",
        )

    def emit_candidate_rejected(self, state: WorkflowRevisionState) -> None:
        self.append_canvas_event(
            state,
            "candidate_rejected",
            {
                "rejection_reason": state.rejection_reason,
                "refresh": ["revision", "asset_history", "candidate_summary"],
            },
            resource_type="candidate",
        )

    def emit_candidate_superseded(
        self,
        state: WorkflowRevisionState,
        *,
        superseded_by: WorkflowRevisionState,
    ) -> None:
        self.append_canvas_event(
            state,
            "candidate_superseded",
            {
                "superseded_by_revision_id": superseded_by.revision_id,
                "refresh": ["revision", "asset_history", "candidate_summary"],
            },
            resource_type="candidate",
        )

    def emit_asset_history_updated(
        self,
        state: WorkflowRevisionState,
        *,
        active_asset_ids: list[str] | None = None,
    ) -> None:
        self.append_canvas_event(
            state,
            "asset_history_updated",
            {
                "active_asset_ids": active_asset_ids
                if active_asset_ids is not None
                else active_asset_ids_for_revision_target(self._data_dir, state),
                "refresh": ["asset_history"],
            },
            resource_type="asset_history",
            resource_id=revision_target_resource_id(state),
        )

    def emit_node_candidate_summary_updated(self, state: WorkflowRevisionState) -> None:
        pending_visible = [
            item
            for item in self._revision_states(state.workflow_id, state.node_id)
            if item.acceptance_status == "pending" and item.visibility_status == "visible"
        ]
        self._canvas_events.append_event(
            state.workflow_id,
            "node_candidate_summary_updated",
            node_id=state.node_id,
            node_type=state.node_type,
            resource_type="node",
            resource_id=state.node_id,
            payload={
                "node_id": state.node_id,
                "node_type": state.node_type,
                "candidate_count": len(pending_visible),
                "candidate_warning_count": sum(
                    1 for item in pending_visible if revision_has_quality_warning(item)
                ),
                "pending_visible_candidate_count": len(pending_visible),
                "refresh": ["candidate_summary"],
            },
        )

    def emit_resolved_inputs_updated(self, state: WorkflowRevisionState) -> None:
        if not state.affected_downstream_nodes:
            return
        self._canvas_events.append_event(
            state.workflow_id,
            "resolved_inputs_updated",
            node_id=state.node_id,
            node_type=state.node_type,
            resource_type="resolved_inputs",
            resource_id=state.node_id,
            payload={
                "node_id": state.node_id,
                "node_type": state.node_type,
                "revision_id": state.revision_id,
                "source_node_id": state.node_id,
                "affected_node_ids": state.affected_downstream_nodes,
                "refresh": ["resolved_inputs"],
            },
        )

    def append_canvas_event(
        self,
        state: WorkflowRevisionState,
        event_type: str,
        payload: dict[str, Any],
        *,
        resource_type: str = "revision",
        resource_id: str | None = None,
    ) -> None:
        self._canvas_events.append_event(
            state.workflow_id,
            event_type,
            node_id=state.node_id,
            node_type=state.node_type,
            resource_type=resource_type,
            resource_id=resource_id or state.revision_id,
            payload={
                **revision_canvas_identity(state),
                **payload,
            },
        )


def revision_canvas_identity(state: WorkflowRevisionState) -> dict[str, Any]:
    return {
        "revision_id": state.revision_id,
        "node_id": state.node_id,
        "node_type": state.node_type,
        "entity_id": state.target_entity_id,
        "target_entity_id": state.target_entity_id,
        "semantic_type": state.semantic_type,
        "target_asset_id": state.target_asset_id,
    }


def sync_conversation_revision_action(
    data_dir: Path,
    state: WorkflowRevisionState,
    *,
    status: str,
) -> None:
    if state.metadata.get("source_type") != "agent_conversation_action":
        return
    conversation_id = str(state.metadata.get("source_conversation_id") or "")
    action_id = str(state.metadata.get("source_action_id") or "")
    if not conversation_id or not action_id:
        return
    path = data_dir / "agent_conversations" / f"{conversation_id}.json"
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    actions = payload.get("suggested_actions")
    if not isinstance(actions, list):
        return
    action = _conversation_action(actions, action_id)
    if action is None:
        return
    now = utc_now().isoformat()
    metadata = _updated_action_metadata(action, state, status=status, now=now)
    action["metadata"] = metadata
    action["updated_at"] = now
    payload["updated_at"] = now
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _conversation_action(actions: list[Any], action_id: str) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in actions
            if isinstance(item, dict) and str(item.get("action_id") or "") == action_id
        ),
        None,
    )


def _updated_action_metadata(
    action: dict[str, Any],
    state: WorkflowRevisionState,
    *,
    status: str,
    now: str,
) -> dict[str, Any]:
    candidate_asset_ids = revision_candidate_asset_ids(state)
    if not candidate_asset_ids:
        candidate_asset_ids = [
            str(asset_id) for asset_id in state.metadata.get("candidate_asset_ids", []) if asset_id
        ]
    metadata = dict(action.get("metadata") if isinstance(action.get("metadata"), dict) else {})
    metadata.update(
        {
            "revision_id": state.revision_id,
            "revision_acceptance_status": state.acceptance_status,
            "revision_generation_status": state.generation_status or state.status,
            "revision_visibility_status": state.visibility_status,
            "revision_updated_at": now,
            "candidate_asset_ids": candidate_asset_ids,
        }
    )
    if status == "accepted":
        metadata["accepted_asset_ids"] = [
            str(asset_id)
            for asset_id in state.metadata.get("accepted_asset_ids", candidate_asset_ids)
            if asset_id
        ]
        metadata["accepted_at"] = now
        metadata.pop("rejected_asset_ids", None)
        metadata.pop("rejected_at", None)
    elif status == "rejected":
        metadata["rejected_asset_ids"] = [
            str(asset_id)
            for asset_id in state.metadata.get("rejected_asset_ids", candidate_asset_ids)
            if asset_id
        ]
        metadata["rejected_at"] = now
        metadata.pop("accepted_asset_ids", None)
        metadata.pop("accepted_at", None)
    return metadata


_emit_revision_status_changed = WorkflowRevisionEventPublisher.emit_revision_status_changed
_emit_candidate_created = WorkflowRevisionEventPublisher.emit_candidate_created
_emit_candidate_quality_updated = WorkflowRevisionEventPublisher.emit_candidate_quality_updated
_emit_candidate_accepted = WorkflowRevisionEventPublisher.emit_candidate_accepted
_emit_candidate_rejected = WorkflowRevisionEventPublisher.emit_candidate_rejected
_emit_candidate_superseded = WorkflowRevisionEventPublisher.emit_candidate_superseded
_emit_asset_history_updated = WorkflowRevisionEventPublisher.emit_asset_history_updated
_emit_node_candidate_summary_updated = (
    WorkflowRevisionEventPublisher.emit_node_candidate_summary_updated
)
_emit_resolved_inputs_updated = WorkflowRevisionEventPublisher.emit_resolved_inputs_updated
_append_canvas_event = WorkflowRevisionEventPublisher.append_canvas_event
_sync_conversation_revision_action = sync_conversation_revision_action
