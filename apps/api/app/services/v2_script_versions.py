from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.schemas.workflow_v2 import WorkflowV2
from app.schemas.workflow_v2_screenplay import (
    V2LinkedContextSummary,
    V2ScriptConfirmRequest,
    V2ScriptConfirmResponse,
    V2ScriptPendingTransaction,
    V2ScriptReadResponse,
    V2ScriptSelectVersionResponse,
    V2ScriptStructuralDiff,
    V2ScriptTransactionEventIntent,
    V2ScriptVersionIndex,
    V2ScriptVersionListResponse,
    V2ScriptVersionRecord,
)
from app.services.agent_trace import utc_now
from app.services.v2_creative_inventory import creative_inventory_from_metadata
from app.services.v2_event_store import V2EventStore
from app.services.v2_generation_integrity import planning_constraints_from_metadata
from app.services.v2_linked_context import V2LinkedContextSynchronizer
from app.services.v2_script_editing import (
    V2ScriptContractValidator,
    V2ScriptEditError,
    V2ScriptEditReconciler,
    structural_diff,
)
from app.services.v2_script_persistence import (
    V2ScriptPersistenceAdapter,
    V2ScriptPersistenceError,
    V2ScriptTransactionStore,
    V2ScriptVersionStore,
    screenplay_content_hash,
    script_version_summary,
)
from app.services.v2_workflow_store import V2WorkflowStore


class V2ScriptVersionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        stage: str = "script_confirm",
        violations: list[dict[str, Any]] | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.stage = stage
        self.violations = violations or []
        super().__init__(message)

    def detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "stage": self.stage,
            "violations": self.violations,
        }


class V2ScriptVersionService:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._workflows = V2WorkflowStore(data_dir)
        self._events = V2EventStore(data_dir)
        self._versions = V2ScriptVersionStore(data_dir)
        self._transactions = V2ScriptTransactionStore(data_dir)
        self._adapter = V2ScriptPersistenceAdapter()
        self._reconciler = V2ScriptEditReconciler()
        self._validator = V2ScriptContractValidator()
        self._linked_context = V2LinkedContextSynchronizer()

    def read_selected(self, workflow_id: str) -> V2ScriptReadResponse:
        try:
            with self._versions.workflow_lock(workflow_id):
                workflow = self._load_workflow(workflow_id)
                workflow = self._transactions.recover(workflow_id, workflow)
                workflow, record = self._selected_or_bootstrap(workflow)
                return V2ScriptReadResponse(
                    workflow_id=workflow_id,
                    selected_script_version_id=record.script_version_id,
                    script=record.script,
                    events_cursor=self._events.events_cursor(workflow_id),
                )
        except V2ScriptVersionError:
            raise
        except V2ScriptPersistenceError as exc:
            raise _from_persistence(exc, stage="script_read") from exc

    def list_versions(self, workflow_id: str) -> V2ScriptVersionListResponse:
        try:
            with self._versions.workflow_lock(workflow_id):
                workflow = self._load_workflow(workflow_id)
                workflow = self._transactions.recover(workflow_id, workflow)
                workflow, _ = self._selected_or_bootstrap(workflow)
                index = self._versions.load_index(workflow_id)
                if index is None:
                    raise V2ScriptVersionError(
                        "script_plan_unavailable",
                        "The workflow does not contain a recoverable screenplay.",
                        status_code=409,
                        stage="script_versions",
                    )
                return V2ScriptVersionListResponse(
                    workflow_id=workflow_id,
                    selected_script_version_id=index.selected_script_version_id,
                    versions=index.versions,
                    events_cursor=self._events.events_cursor(workflow_id),
                )
        except V2ScriptVersionError:
            raise
        except V2ScriptPersistenceError as exc:
            raise _from_persistence(exc, stage="script_versions") from exc

    def confirm(
        self,
        workflow_id: str,
        request: V2ScriptConfirmRequest,
    ) -> V2ScriptConfirmResponse:
        try:
            with self._versions.workflow_lock(workflow_id):
                workflow = self._load_workflow(workflow_id)
                workflow = self._transactions.recover(workflow_id, workflow)
                workflow, selected_record = self._selected_or_bootstrap(workflow)
                if request.base_script_version_id != selected_record.script_version_id:
                    raise _conflict()
                try:
                    result = self._reconciler.reconcile(request.document, selected_record.script)
                    self._validator.validate(
                        result.script,
                        inventory=creative_inventory_from_metadata(workflow.metadata),
                        hard_constraints=planning_constraints_from_metadata(workflow.metadata),
                        explicit_constraints=_explicit_constraints(workflow),
                    )
                except V2ScriptEditError as exc:
                    raise _from_edit(exc) from exc
                script_version_id = f"script_ver_{uuid4().hex[:12]}"
                script = result.script.model_copy(
                    update={"script_version_id": script_version_id},
                    deep=True,
                )
                linked_result = self._linked_context.synchronize(
                    workflow,
                    selected_record.script,
                    script,
                    result.structural_diff,
                )
                record = V2ScriptVersionRecord(
                    script_version_id=script_version_id,
                    parent_script_version_id=selected_record.script_version_id,
                    created_at=utc_now().isoformat(),
                    source_action=request.source_action,
                    script=script,
                    structural_diff=linked_result.structural_diff,
                    content_hash=screenplay_content_hash(script),
                )
                linked = linked_result.summary
                index = self._next_index(workflow_id, record)
                updated_workflow = _select_script(linked_result.workflow, script)
                transaction_id = f"script_txn_{uuid4().hex[:16]}"
                intents = _confirm_event_intents(record, linked)
                pending = V2ScriptPendingTransaction(
                    transaction_id=transaction_id,
                    prior_selected_script_version_id=selected_record.script_version_id,
                    target_script_version_id=script_version_id,
                    prepared_at=utc_now().isoformat(),
                    event_intents=intents,
                )
                cursor = self._transactions.commit(
                    workflow=updated_workflow,
                    record=record,
                    index=index,
                    pending=pending,
                )
                return V2ScriptConfirmResponse(
                    workflow_id=workflow_id,
                    selected_script_version_id=script_version_id,
                    script=script,
                    structural_diff=linked_result.structural_diff,
                    linked_context=linked,
                    events_cursor=cursor,
                )
        except V2ScriptVersionError:
            raise
        except V2ScriptPersistenceError as exc:
            raise _from_persistence(exc, stage="script_confirm") from exc

    def select(
        self,
        workflow_id: str,
        script_version_id: str,
        *,
        base_selected_script_version_id: str,
    ) -> V2ScriptSelectVersionResponse:
        try:
            with self._versions.workflow_lock(workflow_id):
                workflow = self._load_workflow(workflow_id)
                workflow = self._transactions.recover(workflow_id, workflow)
                workflow, selected_record = self._selected_or_bootstrap(workflow)
                if base_selected_script_version_id != selected_record.script_version_id:
                    raise _conflict()
                target = self._versions.load_version(workflow_id, script_version_id)
                diff = structural_diff(selected_record.script, target.script)
                try:
                    self._validator.validate(
                        target.script,
                        inventory=creative_inventory_from_metadata(workflow.metadata),
                        hard_constraints=planning_constraints_from_metadata(workflow.metadata),
                        explicit_constraints=_explicit_constraints(workflow),
                    )
                except V2ScriptEditError as exc:
                    raise _from_edit(exc) from exc
                linked_result = self._linked_context.synchronize(
                    workflow,
                    selected_record.script,
                    target.script,
                    diff,
                )
                diff = linked_result.structural_diff
                linked = linked_result.summary
                index = self._versions.load_index(workflow_id)
                if index is None:
                    raise V2ScriptVersionError(
                        "script_plan_unavailable",
                        "The workflow does not contain a recoverable screenplay.",
                        status_code=409,
                        stage="script_select",
                    )
                index = index.model_copy(
                    update={"selected_script_version_id": script_version_id},
                    deep=True,
                )
                transaction_id = f"script_txn_{uuid4().hex[:16]}"
                pending = V2ScriptPendingTransaction(
                    transaction_id=transaction_id,
                    prior_selected_script_version_id=selected_record.script_version_id,
                    target_script_version_id=script_version_id,
                    prepared_at=utc_now().isoformat(),
                    event_intents=_selection_event_intents(target, diff, linked),
                )
                cursor = self._transactions.commit(
                    workflow=_select_script(linked_result.workflow, target.script),
                    record=None,
                    index=index,
                    pending=pending,
                )
                return V2ScriptSelectVersionResponse(
                    workflow_id=workflow_id,
                    selected_script_version_id=script_version_id,
                    script=target.script,
                    structural_diff=diff,
                    linked_context=linked,
                    events_cursor=cursor,
                )
        except V2ScriptVersionError:
            raise
        except V2ScriptPersistenceError as exc:
            raise _from_persistence(exc, stage="script_select") from exc

    def _selected_or_bootstrap(
        self,
        workflow: WorkflowV2,
    ) -> tuple[WorkflowV2, V2ScriptVersionRecord]:
        workflow_id = workflow.workflow_id
        selected_id = str(workflow.metadata.get("selected_script_version_id") or "")
        if selected_id:
            return workflow, self._versions.load_version(workflow_id, selected_id)
        payload = workflow.metadata.get("script_plan")
        try:
            script, migration_source = self._adapter.normalize_metadata_plan(payload)
        except V2ScriptPersistenceError as exc:
            raise _from_persistence(exc, stage="script_read") from exc
        record = V2ScriptVersionRecord(
            script_version_id=script.script_version_id,
            parent_script_version_id=None,
            created_at=utc_now().isoformat(),
            source_action="initial_planning",
            script=script,
            structural_diff=V2ScriptStructuralDiff(),
            content_hash=screenplay_content_hash(script),
            migration_source=migration_source,
        )
        index = V2ScriptVersionIndex(
            selected_script_version_id=record.script_version_id,
            versions=[script_version_summary(record)],
        )
        transaction_id = f"script_txn_{uuid4().hex[:16]}"
        pending = V2ScriptPendingTransaction(
            transaction_id=transaction_id,
            target_script_version_id=record.script_version_id,
            prepared_at=utc_now().isoformat(),
            event_intents=[
                V2ScriptTransactionEventIntent(
                    event_type="script_version_created",
                    payload={
                        "script_version_id": record.script_version_id,
                        "parent_script_version_id": None,
                        "source_action": "initial_planning",
                    },
                ),
                V2ScriptTransactionEventIntent(
                    event_type="script_selected_version_updated",
                    payload={
                        "script_version_id": record.script_version_id,
                        "previous_script_version_id": None,
                    },
                ),
            ],
        )
        linked_result = self._linked_context.synchronize(
            workflow,
            script,
            script,
            record.structural_diff,
        )
        pending = pending.model_copy(
            update={
                "event_intents": [
                    *pending.event_intents,
                    *_linked_event_intents(
                        script.script_version_id,
                        linked_result.structural_diff,
                        linked_result.summary,
                    ),
                ]
            },
            deep=True,
        )
        updated = _select_script(linked_result.workflow, script)
        self._transactions.commit(
            workflow=updated,
            record=record,
            index=index,
            pending=pending,
        )
        return updated, record

    def _next_index(
        self,
        workflow_id: str,
        record: V2ScriptVersionRecord,
    ) -> V2ScriptVersionIndex:
        current = self._versions.load_index(workflow_id)
        summaries = [script_version_summary(record), *(current.versions if current else [])]
        return V2ScriptVersionIndex(
            selected_script_version_id=record.script_version_id,
            versions=summaries,
        )

    def _load_workflow(self, workflow_id: str) -> WorkflowV2:
        try:
            return self._workflows.load_workflow(workflow_id)
        except Exception as exc:
            code = str(getattr(exc, "code", "workflow_not_found"))
            if code == "workflow_not_found":
                raise V2ScriptVersionError(
                    "workflow_not_found",
                    "The requested V2 workflow does not exist.",
                    status_code=404,
                    stage="script_read",
                ) from exc
            raise


def parse_confirm_request(payload: Any) -> V2ScriptConfirmRequest:
    try:
        return V2ScriptConfirmRequest.model_validate(payload)
    except ValidationError as exc:
        raise V2ScriptVersionError(
            "invalid_script_document",
            "The screenplay edit document is invalid.",
            status_code=422,
            violations=[
                {
                    "field": ".".join(str(part) for part in error["loc"]),
                    "message": error["msg"],
                    "type": error["type"],
                }
                for error in exc.errors(include_url=False)
            ],
        ) from exc


def _select_script(workflow: WorkflowV2, script: Any) -> WorkflowV2:
    return workflow.model_copy(
        update={
            "metadata": {
                **workflow.metadata,
                "selected_script_version_id": script.script_version_id,
                "script_plan": script.model_dump(mode="json"),
            }
        },
        deep=True,
    )


def _explicit_constraints(workflow: WorkflowV2) -> dict[str, Any]:
    value = workflow.metadata.get("explicit_constraints")
    return dict(value) if isinstance(value, dict) else {}


def _linked_summary(diff: V2ScriptStructuralDiff) -> V2LinkedContextSummary:
    item_ids = sorted(
        {
            *diff.added_character_ids,
            *diff.archived_character_ids,
            *diff.updated_character_ids,
            *diff.added_scene_ids,
            *diff.archived_scene_ids,
            *diff.updated_scene_ids,
            *diff.added_shot_ids,
            *diff.archived_shot_ids,
            *diff.updated_shot_ids,
        }
    )
    node_ids: list[str] = []
    if any("character" in value for value in item_ids):
        node_ids.append("character-generation")
    if any("scene" in value for value in item_ids):
        node_ids.append("scene-generation")
    if diff.added_shot_ids or diff.archived_shot_ids or diff.updated_shot_ids:
        node_ids.append("storyboard")
    return V2LinkedContextSummary(
        updated_node_ids=node_ids,
        updated_item_ids=item_ids,
        updated_fields=["system_suggested_prompt", "screenplay_slice"] if item_ids else [],
        refresh=["workflow", "script", "slot_prompts", "references"],
    )


def _confirm_event_intents(
    record: V2ScriptVersionRecord,
    linked: V2LinkedContextSummary,
) -> list[V2ScriptTransactionEventIntent]:
    intents = [
        V2ScriptTransactionEventIntent(
            event_type="script_version_created",
            payload={
                "script_version_id": record.script_version_id,
                "parent_script_version_id": record.parent_script_version_id,
                "source_action": record.source_action,
            },
        ),
        V2ScriptTransactionEventIntent(
            event_type="script_selected_version_updated",
            payload={
                "script_version_id": record.script_version_id,
                "previous_script_version_id": record.parent_script_version_id,
            },
        ),
    ]
    return [
        *intents,
        *_linked_event_intents(record.script_version_id, record.structural_diff, linked),
    ]


def _selection_event_intents(
    record: V2ScriptVersionRecord,
    diff: V2ScriptStructuralDiff,
    linked: V2LinkedContextSummary,
) -> list[V2ScriptTransactionEventIntent]:
    return [
        V2ScriptTransactionEventIntent(
            event_type="script_selected_version_updated",
            payload={"script_version_id": record.script_version_id},
        ),
        *_linked_event_intents(record.script_version_id, diff, linked),
    ]


def _linked_event_intents(
    script_version_id: str,
    diff: V2ScriptStructuralDiff,
    linked: V2LinkedContextSummary,
) -> list[V2ScriptTransactionEventIntent]:
    intents: list[V2ScriptTransactionEventIntent] = []
    if diff.structure_changed():
        intents.append(
            V2ScriptTransactionEventIntent(
                event_type="workflow_structure_updated",
                payload={
                    "script_version_id": script_version_id,
                    "item_ids": linked.updated_item_ids,
                    **_structure_event_payload(diff),
                    "refresh": ["workflow", "script"],
                },
            )
        )
    if linked.updated_item_ids:
        intents.append(
            V2ScriptTransactionEventIntent(
                event_type="linked_context_updated",
                payload={
                    "script_version_id": script_version_id,
                    "node_ids": linked.updated_node_ids,
                    "item_ids": linked.updated_item_ids,
                    "slot_ids": linked.updated_slot_ids,
                    "updated_fields": linked.updated_fields,
                    "selected_asset_versions_changed": False,
                    "provider_execution_started": False,
                    "refresh": linked.refresh,
                },
            )
        )
    return intents


def _structure_event_payload(diff: V2ScriptStructuralDiff) -> dict[str, list[str] | bool]:
    payload: dict[str, list[str] | bool] = {"order_changed": diff.order_changed}
    for action in ("added", "archived", "reactivated"):
        aggregate: list[str] = []
        for namespace in ("character", "location", "scene", "shot"):
            field = f"{action}_{namespace}_ids"
            values = list(getattr(diff, field))
            payload[field] = values
            aggregate.extend(values)
        payload[f"{action}_item_ids"] = list(dict.fromkeys(aggregate))
    return payload


def _conflict() -> V2ScriptVersionError:
    return V2ScriptVersionError(
        "script_version_conflict",
        "The selected screenplay changed before this edit was confirmed.",
        status_code=409,
    )


def _from_edit(exc: V2ScriptEditError) -> V2ScriptVersionError:
    return V2ScriptVersionError(
        exc.code,
        str(exc),
        status_code=422,
        violations=exc.violations,
    )


def _from_persistence(
    exc: V2ScriptPersistenceError,
    *,
    stage: str,
) -> V2ScriptVersionError:
    status_code = {
        "script_plan_unavailable": 409,
        "script_version_not_found": 404,
        "script_version_corrupt": 500,
        "script_persistence_failed": 500,
        "invalid_script_document": 422,
    }.get(exc.code, 500)
    return V2ScriptVersionError(
        exc.code,
        str(exc),
        status_code=status_code,
        stage=stage,
    )
