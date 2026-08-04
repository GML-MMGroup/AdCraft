"""Publish one execution-owned selection overlay at terminalization."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.schemas.workflow_v2 import WorkflowSlotV2, WorkflowV2
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_execution_service import V2ExecutionService
from app.services.v2_runtime_events import V2RuntimeEventService
from app.services.v2_workflow_authoring import create_workflow_authoring_runtime


class V2ExecutionResultPublicationService:
    """Keep generated selections pending, then commit at most one terminal revision."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._executions = V2ExecutionService(data_dir)
        self._events = V2RuntimeEventService(data_dir)
        self._assets = V2AssetStoreService(data_dir)

    def record_pending_selection(
        self,
        workflow_id: str,
        execution_id: str,
        *,
        slot_id: str,
        asset_id: str,
        version_id: str,
    ) -> dict[str, Any] | None:
        """Durably record one generated selection without changing public authoring."""

        state = self._executions.load_state(workflow_id, execution_id)
        if state is None:
            return None
        selections = dict(state.get("pending_selections") or {})
        selections[slot_id] = {
            "slot_id": slot_id,
            "asset_id": asset_id,
            "version_id": version_id,
        }
        return self._executions.save_state(
            workflow_id,
            execution_id,
            {**state, "pending_selections": selections},
        )

    def uses_pending_publication(self, workflow_id: str, execution_id: str | None) -> bool:
        """Return whether an execution owns a versioned authoring overlay."""

        if not execution_id:
            return False
        state = self._executions.load_state(workflow_id, execution_id)
        return (
            state is not None
            and _positive_int(state.get("authoring_base_state_version")) is not None
        )

    def apply_pending_selections(
        self,
        workflow: WorkflowV2,
        execution_id: str,
    ) -> WorkflowV2:
        """Hydrate an execution-local copy for downstream scheduling only."""

        state = self._executions.load_state(workflow.workflow_id, execution_id) or {}
        hydrated = workflow.model_copy(deep=True)
        for slot_id, selection in _pending_selections(state).items():
            slot = _slot_by_id(hydrated, slot_id)
            if slot is None:
                continue
            slot.selected_asset_id = str(selection["asset_id"])
            slot.selected_version_id = str(selection["version_id"])
        return hydrated

    def publish_terminal(
        self,
        *,
        workflow_id: str,
        execution_id: str,
        candidate_workflow: WorkflowV2 | None = None,
    ) -> WorkflowV2:
        """Publish all pending selections once, or defer on a concurrent authoring edit."""

        state = self._executions.load_state(workflow_id, execution_id) or {}
        runtime = create_workflow_authoring_runtime(self._data_dir)
        try:
            current = runtime.read_model.assemble(workflow_id)
            existing = runtime.repository.get_execution_result_revision(
                workflow_id,
                execution_id,
            )
            if existing is not None:
                self._publish_selected_relations(
                    current,
                    _pending_selections(state),
                    execution_id=execution_id,
                )
                self._save_publication_state(
                    state,
                    workflow_id,
                    execution_id,
                    status="published",
                    revision_no=existing.revision_no,
                )
                return current
            pending = _pending_selections(state)
            if not pending:
                self._save_publication_state(
                    state,
                    workflow_id,
                    execution_id,
                    status="no_change",
                )
                return current
            base_version = _positive_int(state.get("authoring_base_state_version"))
            if base_version is None or current.state_version != base_version:
                self._defer(state, workflow_id, execution_id, current)
                return current
            candidate = (
                candidate_workflow.model_copy(deep=True)
                if candidate_workflow is not None
                else current.model_copy(deep=True)
            )
            changed = candidate_workflow is not None
            for slot_id, selection in pending.items():
                slot = _slot_by_id(candidate, slot_id)
                if slot is None:
                    continue
                asset_id = str(selection["asset_id"])
                version_id = str(selection["version_id"])
                if (slot.selected_asset_id, slot.selected_version_id) == (
                    asset_id,
                    version_id,
                ):
                    continue
                slot.selected_asset_id = asset_id
                slot.selected_version_id = version_id
                changed = True
            if not changed:
                self._save_publication_state(
                    state,
                    workflow_id,
                    execution_id,
                    status="no_change",
                )
                return current
            published = runtime.service.commit_execution_result(
                candidate,
                expected_version=base_version,
                source_execution_id=execution_id,
            )
            self._publish_selected_relations(
                published,
                pending,
                execution_id=execution_id,
            )
            self._save_publication_state(
                state,
                workflow_id,
                execution_id,
                status="published",
                revision_no=published.semantic_revision_no,
            )
            return published
        finally:
            runtime.database.dispose()

    def _publish_selected_relations(
        self,
        workflow: WorkflowV2,
        pending: dict[str, dict[str, str]],
        *,
        execution_id: str,
    ) -> None:
        for slot_id, selection in pending.items():
            slot = _slot_by_id(workflow, slot_id)
            if slot is None:
                continue
            asset_id = str(selection["asset_id"])
            version_id = str(selection["version_id"])
            existing = self._assets.list_relations(
                target_workflow_id=workflow.workflow_id,
                target_slot_id=slot_id,
                relation_type="selected_for_slot",
            )
            if any(
                relation.source_asset_id == asset_id
                and relation.metadata.get("version_id") == version_id
                for relation in existing
            ):
                continue
            self._assets.delete_slot_relations(
                target_workflow_id=workflow.workflow_id,
                target_slot_id=slot_id,
                relation_type="selected_for_slot",
            )
            relation = self._assets.create_relation(
                relation_type="selected_for_slot",
                source_asset_id=asset_id,
                target_workflow_id=workflow.workflow_id,
                target_node_id=slot.node_id,
                target_item_id=slot.item_id,
                target_slot_id=slot.slot_id,
                metadata={
                    "version_id": version_id,
                    "slot_type": slot.slot_type,
                    "media_type": slot.media_type,
                    "source_action": "execution_result",
                    "source_execution_id": execution_id,
                },
            )
            self._events.append_event(
                workflow.workflow_id,
                "slot_selected_version_updated",
                node_id=slot.node_id,
                item_id=slot.item_id,
                slot_id=slot.slot_id,
                asset_id=asset_id,
                version_id=version_id,
                payload={
                    "relation_id": relation.relation_id,
                    "relation_type": relation.relation_type,
                    "source_action": "execution_result",
                },
            )

    def _defer(
        self,
        state: dict[str, Any],
        workflow_id: str,
        execution_id: str,
        current: WorkflowV2,
    ) -> None:
        if state.get("execution_result_revision_status") != "deferred":
            event = self._events.append_event(
                workflow_id,
                "execution_result_revision_deferred",
                execution_id=execution_id,
                payload={
                    "execution_id": execution_id,
                    "authoring_base_state_version": state.get("authoring_base_state_version"),
                    "current_state_version": current.state_version,
                    "pending_slot_ids": list(_pending_selections(state)),
                    "reason": "authoring_advanced_during_execution",
                },
            )
            state = {**state, "events_cursor": event.seq}
        self._save_publication_state(
            state,
            workflow_id,
            execution_id,
            status="deferred",
        )

    def _save_publication_state(
        self,
        state: dict[str, Any],
        workflow_id: str,
        execution_id: str,
        *,
        status: str,
        revision_no: int | None = None,
    ) -> None:
        payload = {
            **state,
            "workflow_id": workflow_id,
            "execution_id": execution_id,
            "execution_result_revision_status": status,
        }
        if revision_no is not None:
            payload["execution_result_revision_no"] = revision_no
        self._executions.save_state(workflow_id, execution_id, payload)


def _pending_selections(state: dict[str, Any]) -> dict[str, dict[str, str]]:
    value = state.get("pending_selections")
    if not isinstance(value, dict):
        return {}
    return {
        str(slot_id): selection
        for slot_id, selection in value.items()
        if isinstance(selection, dict)
        and isinstance(selection.get("asset_id"), str)
        and isinstance(selection.get("version_id"), str)
    }


def _slot_by_id(workflow: WorkflowV2, slot_id: str) -> WorkflowSlotV2 | None:
    return next(
        (
            slot
            for node in workflow.nodes
            for item in node.items
            for slot in item.slots
            if slot.slot_id == slot_id
        ),
        None,
    )


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
