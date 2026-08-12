"""Atomic SQLite persistence for Agent Canvas command control."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, cast
from uuid import uuid4

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasActionReceiptRow,
    AgentCanvasBindingRow,
    AgentCanvasChatEntryRow,
    AgentCanvasChatTurnRow,
    AgentCanvasCommandOperationResultRow,
    AgentCanvasCommandPlanRow,
    AgentCanvasGuidedActionRow,
    AgentCanvasIdempotencyRow,
    AgentCanvasNodeRow,
    AgentCanvasVariationDraftRow,
    AgentCanvasWorkflowRow,
)
from app.schemas.agent_canvas import (
    CanvasNodeV2,
    CanvasPositionV2,
    CanvasVariationDraftResponseV2,
    CanvasVariationDraftUpsertV2,
    CanvasVariationDraftV2,
    CanvasVariationMaterializeRequestV2,
    CanvasVariationMaterializeResponseV2,
)
from app.schemas.agent_canvas_commands import AgentPlacementHintV2
from app.schemas.agent_canvas_conversation import AgentActionReceiptV2
from app.schemas.agent_runtime import (
    AgentCommandPlanCreateV2,
    AgentCommandPlanV2,
    AgentCommandTransactionResultV2,
    AgentOperationResultV2,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_authoring_validation import (
    BindingValidationState,
    validate_node_binding,
    validate_node_patch,
)
from app.services.agent_canvas_capability_draft_bundle import (
    character_turnaround_prompt,
)
from app.services.agent_canvas_reference_semantics import AgentCanvasReferenceSemanticPolicy


ModelSelectionValidator = Callable[[str, str, str | None], object]


class AgentCanvasCommandRepository:
    """Own immutable command plans and all-or-nothing semantic application."""

    def __init__(
        self,
        database: V2Database,
        events: EventRepository,
        *,
        model_selection_validator: ModelSelectionValidator | None = None,
    ) -> None:
        if events.database is not database:
            raise ValueError("Command and event repositories must share one database.")
        self._database = database
        self._events = events
        self._model_selection_validator = model_selection_validator

    @property
    def database(self) -> V2Database:
        return self._database

    def _validate_model_selection(
        self,
        node_type: str,
        model_selection_mode: str,
        model_ref: str | None,
    ) -> None:
        if self._model_selection_validator is not None:
            self._model_selection_validator(node_type, model_selection_mode, model_ref)

    def create_or_get_plan(
        self,
        plan: AgentCommandPlanCreateV2,
        *,
        idempotency_key: str,
    ) -> tuple[AgentCommandPlanV2, bool]:
        if not idempotency_key:
            raise _error("idempotency_key_required", "Idempotency-Key is required.")
        request_json = _dump(plan.model_dump(mode="json"))
        request_fingerprint = _digest(request_json)
        operation_fingerprint = _digest(
            _dump([operation.model_dump(mode="json") for operation in plan.operations])
        )
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    existing = (
                        connection.execute(
                            select(AgentCanvasCommandPlanRow).where(
                                AgentCanvasCommandPlanRow.workflow_id == plan.workflow_id,
                                AgentCanvasCommandPlanRow.idempotency_key == idempotency_key,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is not None:
                        if str(existing["request_fingerprint"]) != request_fingerprint:
                            raise _error(
                                "idempotency_conflict",
                                "Idempotency key was reused with a different plan.",
                            )
                        connection.commit()
                        return _plan_from_row(existing), False
                    _require_workflow_revision(
                        connection,
                        plan.workflow_id,
                        plan.base_workflow_revision,
                    )
                    plan_id = f"plan_{uuid4().hex}"
                    status = "pending_confirmation" if plan.confirmation_required else "applying"
                    values = {
                        "plan_id": plan_id,
                        "workflow_id": plan.workflow_id,
                        "conversation_id": plan.conversation_id,
                        "source_turn_id": plan.source_turn_id,
                        "context_snapshot_id": plan.context_snapshot_id,
                        "base_workflow_revision": plan.base_workflow_revision,
                        "expires_at": plan.expires_at.isoformat(),
                        "operations_json": _dump(
                            [operation.model_dump(mode="json") for operation in plan.operations]
                        ),
                        "operation_fingerprint": operation_fingerprint,
                        "risk": plan.risk,
                        "confirmation_required": plan.confirmation_required,
                        "status": status,
                        "continuation_requested": plan.continuation_requested,
                        "target_summary": plan.target_summary,
                        "supersedes_plan_id": None,
                        "replacement_plan_id": None,
                        "actor": "agent",
                        "idempotency_key": idempotency_key,
                        "request_fingerprint": request_fingerprint,
                        "created_at": now,
                        "updated_at": now,
                    }
                    connection.execute(insert(AgentCanvasCommandPlanRow).values(**values))
                    stored = _plan_from_mapping(values)
                    self._append_timeline(
                        connection,
                        conversation_id=plan.conversation_id,
                        workflow_id=plan.workflow_id,
                        entry_type="command_plan",
                        content=plan.target_summary or "Agent command plan",
                        metadata={"command_plan": stored.model_dump(mode="json")},
                        created_at=now,
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=plan.workflow_id,
                            event_type="agent_command_plan_created",
                            created_at=now,
                            payload={
                                "plan_id": plan_id,
                                "risk": plan.risk,
                                "status": status,
                            },
                        ),
                    )
                    connection.commit()
                    return stored, True
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_command_storage_unavailable",
                "Agent command storage failed.",
            ) from error

    def get_plan(self, plan_id: str) -> AgentCommandPlanV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasCommandPlanRow).where(
                            AgentCanvasCommandPlanRow.plan_id == plan_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_command_storage_unavailable",
                "Agent command storage failed.",
            ) from error
        if row is None:
            raise _error(
                "agent_command_plan_not_found",
                "Agent command plan was not found.",
            )
        return _plan_from_row(row)

    def list_plans_by_status(
        self,
        status: str,
    ) -> tuple[AgentCommandPlanV2, ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasCommandPlanRow)
                        .where(AgentCanvasCommandPlanRow.status == status)
                        .order_by(
                            AgentCanvasCommandPlanRow.created_at.asc(),
                            AgentCanvasCommandPlanRow.plan_id.asc(),
                        )
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_command_storage_unavailable",
                "Agent command storage failed.",
            ) from error
        return tuple(_plan_from_row(row) for row in rows)

    def fail_applying_plan(
        self,
        plan_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> AgentActionReceiptV2:
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    plan_row = (
                        connection.execute(
                            select(AgentCanvasCommandPlanRow).where(
                                AgentCanvasCommandPlanRow.plan_id == plan_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if plan_row is None:
                        raise _error(
                            "agent_command_plan_not_found",
                            "Agent command plan was not found.",
                        )
                    existing_payload = connection.execute(
                        select(AgentCanvasActionReceiptRow.receipt_json).where(
                            AgentCanvasActionReceiptRow.plan_id == plan_id
                        )
                    ).scalar_one_or_none()
                    if existing_payload is not None:
                        connection.commit()
                        return AgentActionReceiptV2.model_validate_json(str(existing_payload))
                    if str(plan_row["status"]) != "applying":
                        raise _error(
                            "agent_command_plan_already_resolved",
                            "Agent command plan is already resolved.",
                        )
                    workflow_revision = connection.execute(
                        select(AgentCanvasWorkflowRow.revision).where(
                            AgentCanvasWorkflowRow.workflow_id == plan_row["workflow_id"]
                        )
                    ).scalar_one_or_none()
                    if workflow_revision is None:
                        raise _error("workflow_not_found", "Workflow was not found.")
                    receipt = AgentActionReceiptV2(
                        receipt_id=f"receipt_{uuid4().hex}",
                        workflow_id=str(plan_row["workflow_id"]),
                        plan_id=plan_id,
                        status="failed",
                        summary="The requested canvas changes could not be recovered.",
                        workflow_revision=int(workflow_revision),
                        error_code=error_code,
                        error_message=error_message,
                    )
                    connection.execute(
                        update(AgentCanvasCommandPlanRow)
                        .where(AgentCanvasCommandPlanRow.plan_id == plan_id)
                        .values(status="failed", updated_at=now)
                    )
                    connection.execute(
                        insert(AgentCanvasActionReceiptRow).values(
                            receipt_id=receipt.receipt_id,
                            workflow_id=receipt.workflow_id,
                            plan_id=receipt.plan_id,
                            action_id=None,
                            receipt_json=receipt.model_dump_json(),
                            created_at=now,
                        )
                    )
                    self._append_timeline(
                        connection,
                        conversation_id=str(plan_row["conversation_id"]),
                        workflow_id=receipt.workflow_id,
                        entry_type="action_receipt",
                        content=receipt.summary,
                        metadata={"action_receipt": receipt.model_dump(mode="json")},
                        created_at=now,
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=receipt.workflow_id,
                            event_type="agent_command_plan_failed",
                            created_at=now,
                            payload={
                                "plan_id": plan_id,
                                "error_code": error_code,
                            },
                        ),
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=receipt.workflow_id,
                            event_type="agent_action_receipt_created",
                            created_at=now,
                            payload={
                                "receipt_id": receipt.receipt_id,
                                "plan_id": plan_id,
                                "revision": receipt.workflow_revision,
                            },
                        ),
                    )
                    connection.commit()
                    return receipt
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_command_storage_unavailable",
                "Agent command recovery failure could not be stored.",
            ) from error

    def begin_confirmed_plan(
        self,
        plan_id: str,
        *,
        expected_revision: int,
    ) -> AgentCommandPlanV2:
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    row = (
                        connection.execute(
                            select(AgentCanvasCommandPlanRow).where(
                                AgentCanvasCommandPlanRow.plan_id == plan_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None:
                        raise _error(
                            "agent_command_plan_not_found",
                            "Agent command plan was not found.",
                        )
                    plan = _plan_from_row(row)
                    if plan.status == "applied":
                        connection.commit()
                        return plan
                    if plan.status != "pending_confirmation":
                        raise _error(
                            "agent_command_plan_already_resolved",
                            "Agent command plan is already resolved.",
                        )
                    if plan.expires_at <= datetime.now(timezone.utc):
                        raise _error(
                            "agent_command_plan_expired",
                            "Agent command plan has expired.",
                        )
                    _require_workflow_revision(
                        connection,
                        plan.workflow_id,
                        expected_revision,
                    )
                    connection.execute(
                        update(AgentCanvasCommandPlanRow)
                        .where(AgentCanvasCommandPlanRow.plan_id == plan_id)
                        .values(status="applying", actor="user", updated_at=now)
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_command_storage_unavailable",
                "Agent command storage failed.",
            ) from error
        return self.get_plan(plan_id)

    def reject_plan(
        self,
        plan_id: str,
        *,
        expected_revision: int,
    ) -> AgentCommandPlanV2:
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    row = (
                        connection.execute(
                            select(AgentCanvasCommandPlanRow).where(
                                AgentCanvasCommandPlanRow.plan_id == plan_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None:
                        raise _error(
                            "agent_command_plan_not_found",
                            "Agent command plan was not found.",
                        )
                    plan = _plan_from_row(row)
                    if plan.status == "rejected":
                        connection.commit()
                        return plan
                    if plan.status != "pending_confirmation":
                        raise _error(
                            "agent_command_plan_already_resolved",
                            "Agent command plan is already resolved.",
                        )
                    _require_workflow_revision(
                        connection,
                        plan.workflow_id,
                        expected_revision,
                    )
                    connection.execute(
                        update(AgentCanvasCommandPlanRow)
                        .where(AgentCanvasCommandPlanRow.plan_id == plan_id)
                        .values(status="rejected", actor="user", updated_at=now)
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=plan.workflow_id,
                            event_type="agent_command_plan_rejected",
                            created_at=now,
                            payload={"plan_id": plan_id},
                        ),
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_command_storage_unavailable",
                "Agent command storage failed.",
            ) from error
        return self.get_plan(plan_id)

    def link_replacement_plan(
        self,
        original_plan_id: str,
        replacement_plan_id: str,
        *,
        transfer_confirmation: bool,
    ) -> AgentCommandPlanV2:
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    original = (
                        connection.execute(
                            select(AgentCanvasCommandPlanRow).where(
                                AgentCanvasCommandPlanRow.plan_id == original_plan_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    replacement = (
                        connection.execute(
                            select(AgentCanvasCommandPlanRow).where(
                                AgentCanvasCommandPlanRow.plan_id == replacement_plan_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if original is None or replacement is None:
                        raise _error(
                            "agent_command_plan_not_found",
                            "Agent command plan was not found.",
                        )
                    existing_replacement = original["replacement_plan_id"]
                    if (
                        existing_replacement is not None
                        and str(existing_replacement) != replacement_plan_id
                    ):
                        raise _error(
                            "agent_command_replan_exhausted",
                            "Agent command conflict replan was already used.",
                        )
                    connection.execute(
                        update(AgentCanvasCommandPlanRow)
                        .where(AgentCanvasCommandPlanRow.plan_id == original_plan_id)
                        .values(
                            status="superseded",
                            replacement_plan_id=replacement_plan_id,
                            updated_at=now,
                        )
                    )
                    replacement_status = (
                        "applying" if transfer_confirmation else str(replacement["status"])
                    )
                    connection.execute(
                        update(AgentCanvasCommandPlanRow)
                        .where(AgentCanvasCommandPlanRow.plan_id == replacement_plan_id)
                        .values(
                            status=replacement_status,
                            supersedes_plan_id=original_plan_id,
                            actor="user" if transfer_confirmation else "agent",
                            updated_at=now,
                        )
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=str(original["workflow_id"]),
                            event_type=(
                                "agent_command_plan_replanned"
                                if transfer_confirmation
                                else "agent_command_confirmation_invalidated"
                            ),
                            created_at=now,
                            payload={
                                "original_plan_id": original_plan_id,
                                "replacement_plan_id": replacement_plan_id,
                                "confirmation_transferred": transfer_confirmation,
                            },
                        ),
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_command_storage_unavailable",
                "Agent command storage failed.",
            ) from error
        return self.get_plan(replacement_plan_id)

    def get_receipt_for_plan(
        self,
        plan_id: str,
        *,
        required: bool = True,
    ) -> AgentActionReceiptV2 | None:
        try:
            with self._database.engine.connect() as connection:
                payload = connection.execute(
                    select(AgentCanvasActionReceiptRow.receipt_json).where(
                        AgentCanvasActionReceiptRow.plan_id == plan_id
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise _error(
                "agent_command_storage_unavailable",
                "Agent command storage failed.",
            ) from error
        if payload is None:
            if required:
                raise _error(
                    "agent_action_receipt_not_found",
                    "Agent action receipt was not found.",
                )
            return None
        return AgentActionReceiptV2.model_validate_json(str(payload))

    def apply_plan_transaction(
        self,
        plan: AgentCommandPlanV2,
        *,
        expected_revision: int,
    ) -> AgentCommandTransactionResultV2:
        now = _now()
        operation_results: list[AgentOperationResultV2] = []
        created_node_ids: list[str] = []
        updated_node_ids: list[str] = []
        deleted_node_ids: list[str] = []
        created_binding_ids: list[str] = []
        deleted_binding_ids: list[str] = []
        run_node_ids: list[str] = []
        resolved_nodes: dict[str, str] = {}
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    stored_status = connection.execute(
                        select(AgentCanvasCommandPlanRow.status).where(
                            AgentCanvasCommandPlanRow.plan_id == plan.plan_id
                        )
                    ).scalar_one_or_none()
                    if stored_status is None:
                        raise _error(
                            "agent_command_plan_not_found",
                            "Agent command plan was not found.",
                        )
                    if stored_status == "applied":
                        replayed = _applied_transaction_result(connection, plan)
                        connection.commit()
                        return replayed
                    current_revision = _require_workflow_revision(
                        connection,
                        plan.workflow_id,
                        expected_revision,
                    )
                    for operation in plan.operations:
                        operation_type = operation.operation_type
                        if operation_type == "create_draft_node":
                            self._validate_model_selection(
                                operation.node_type,
                                operation.model_selection_mode,
                                operation.model_ref,
                            )
                            node_id = f"node_{uuid4().hex}"
                            connection.execute(
                                insert(AgentCanvasNodeRow).values(
                                    node_id=node_id,
                                    workflow_id=plan.workflow_id,
                                    node_type=operation.node_type,
                                    creative_role=operation.creative_role,
                                    role_contract_version="ad-media-role-v1",
                                    title=operation.title,
                                    status=("ready" if operation.node_type == "text" else "draft"),
                                    summary_prompt=operation.summary_prompt,
                                    generation_prompt=operation.generation_prompt,
                                    structured_content_json=_dump(operation.structured_content),
                                    model_selection_mode=operation.model_selection_mode,
                                    model_ref=operation.model_ref,
                                    parameters_json=_dump(operation.parameters),
                                    prompt_context_snapshot_id=None,
                                    output_asset_id=None,
                                    position_x=0.0,
                                    position_y=0.0,
                                    revision=1,
                                    error_json=None,
                                    created_at=now,
                                    updated_at=now,
                                )
                            )
                            resolved_nodes[operation.operation_id] = node_id
                            created_node_ids.append(node_id)
                            result = AgentOperationResultV2(
                                operation_id=operation.operation_id,
                                node_id=node_id,
                                status="applied",
                            )
                        elif operation_type == "patch_editable_node":
                            node_id = _resolve_node_ref(
                                connection,
                                plan.workflow_id,
                                operation.node,
                                resolved_nodes,
                            )
                            current = _require_node(
                                connection,
                                plan.workflow_id,
                                node_id,
                            )
                            changes = operation.model_dump(
                                mode="python",
                                exclude_unset=True,
                                exclude={"operation_id", "operation_type", "node"},
                            )
                            current_values = {
                                "title": current["title"],
                                "summary_prompt": current["summary_prompt"],
                                "generation_prompt": current["generation_prompt"],
                                "structured_content": json.loads(
                                    str(current["structured_content_json"])
                                ),
                                "model_selection_mode": current["model_selection_mode"],
                                "model_ref": current["model_ref"],
                                "parameters": json.loads(str(current["parameters_json"])),
                            }
                            next_status = validate_node_patch(
                                status=str(current["status"]),
                                node_type=str(current["node_type"]),
                                current=current_values,
                                changes=changes,
                            )
                            values = {
                                **{
                                    field: value
                                    for field, value in changes.items()
                                    if field
                                    in {
                                        "title",
                                        "summary_prompt",
                                        "generation_prompt",
                                        "model_selection_mode",
                                        "model_ref",
                                    }
                                },
                                "status": next_status,
                                "revision": int(current["revision"]) + 1,
                                "updated_at": now,
                            }
                            if "structured_content" in changes:
                                values["structured_content_json"] = _dump(
                                    changes["structured_content"]
                                )
                            if "parameters" in changes:
                                values["parameters_json"] = _dump(changes["parameters"])
                            self._validate_model_selection(
                                str(current["node_type"]),
                                cast(
                                    str,
                                    values.get(
                                        "model_selection_mode",
                                        current["model_selection_mode"],
                                    ),
                                ),
                                cast(
                                    str | None,
                                    values.get("model_ref", current["model_ref"]),
                                ),
                            )
                            connection.execute(
                                update(AgentCanvasNodeRow)
                                .where(
                                    AgentCanvasNodeRow.workflow_id == plan.workflow_id,
                                    AgentCanvasNodeRow.node_id == node_id,
                                )
                                .values(**values)
                            )
                            updated_node_ids.append(node_id)
                            result = AgentOperationResultV2(
                                operation_id=operation.operation_id,
                                node_id=node_id,
                                status="applied",
                            )
                        elif operation_type == "materialize_sibling_draft":
                            source_node_id = _resolve_node_ref(
                                connection,
                                plan.workflow_id,
                                operation.source_node,
                                resolved_nodes,
                            )
                            source = _require_node(
                                connection,
                                plan.workflow_id,
                                source_node_id,
                            )
                            if (
                                str(source["status"]) != "ready"
                                or str(source["node_type"]) not in {"image", "video", "audio"}
                                or source["output_asset_id"] is None
                            ):
                                raise _error(
                                    "variation_source_not_ready",
                                    "Variation source must be Ready media.",
                                )
                            self._validate_model_selection(
                                str(source["node_type"]),
                                operation.model_selection_mode,
                                operation.model_ref,
                            )
                            node_id = f"node_{uuid4().hex}"
                            connection.execute(
                                insert(AgentCanvasNodeRow).values(
                                    node_id=node_id,
                                    workflow_id=plan.workflow_id,
                                    node_type=source["node_type"],
                                    creative_role=source["creative_role"],
                                    role_contract_version=source["role_contract_version"],
                                    title=operation.title,
                                    status="draft",
                                    summary_prompt=source["summary_prompt"],
                                    generation_prompt=operation.generation_prompt,
                                    structured_content_json=source["structured_content_json"],
                                    model_selection_mode=operation.model_selection_mode,
                                    model_ref=operation.model_ref,
                                    parameters_json=_dump(operation.parameters),
                                    prompt_context_snapshot_id=source["prompt_context_snapshot_id"],
                                    output_asset_id=None,
                                    position_x=0.0,
                                    position_y=0.0,
                                    revision=1,
                                    error_json=None,
                                    created_at=now,
                                    updated_at=now,
                                )
                            )
                            incoming = list(
                                connection.execute(
                                    select(AgentCanvasBindingRow).where(
                                        AgentCanvasBindingRow.workflow_id == plan.workflow_id,
                                        AgentCanvasBindingRow.target_node_id == source_node_id,
                                    )
                                ).mappings()
                            )
                            for binding in incoming:
                                copied_binding_id = f"binding_{uuid4().hex}"
                                connection.execute(
                                    insert(AgentCanvasBindingRow).values(
                                        binding_id=copied_binding_id,
                                        workflow_id=plan.workflow_id,
                                        source_kind=binding["source_kind"],
                                        source_node_id=binding["source_node_id"],
                                        source_asset_id=binding["source_asset_id"],
                                        target_node_id=node_id,
                                        input_role=binding["input_role"],
                                        required=binding["required"],
                                        enabled=binding["enabled"],
                                        order_index=binding["order_index"],
                                        label=binding["label"],
                                        metadata_json=binding["metadata_json"],
                                        created_at=now,
                                        updated_at=now,
                                    )
                                )
                                created_binding_ids.append(copied_binding_id)
                            resolved_nodes[operation.operation_id] = node_id
                            created_node_ids.append(node_id)
                            result = AgentOperationResultV2(
                                operation_id=operation.operation_id,
                                node_id=node_id,
                                status="applied",
                            )
                        elif operation_type == "create_binding":
                            source_kind, source_node_id, source_asset_id = _resolve_binding_source(
                                connection,
                                plan.workflow_id,
                                operation.source,
                                resolved_nodes,
                            )
                            target_node_id = _resolve_node_ref(
                                connection,
                                plan.workflow_id,
                                operation.target,
                                resolved_nodes,
                            )
                            target_node = _require_node(
                                connection,
                                plan.workflow_id,
                                target_node_id,
                            )
                            if source_kind == "image_asset":
                                if operation.binding_kind != "image_reference":
                                    raise _error(
                                        "binding_media_incompatible",
                                        "Binding kind is incompatible with the source media.",
                                    )
                            else:
                                source_node = _require_node(
                                    connection,
                                    plan.workflow_id,
                                    cast(str, source_node_id),
                                )
                                binding_rows = connection.execute(
                                    select(AgentCanvasBindingRow).where(
                                        AgentCanvasBindingRow.workflow_id == plan.workflow_id
                                    )
                                ).mappings()
                                validate_node_binding(
                                    bindings=tuple(
                                        BindingValidationState(
                                            source_node_id=cast(
                                                str | None,
                                                row["source_node_id"],
                                            ),
                                            target_node_id=str(row["target_node_id"]),
                                            binding_kind=str(row["input_role"]),
                                        )
                                        for row in binding_rows
                                    ),
                                    source_node_id=cast(str, source_node_id),
                                    source_node_type=str(source_node["node_type"]),
                                    source_semantic_role=str(source_node["creative_role"]),
                                    target_node_id=target_node_id,
                                    target_node_type=str(target_node["node_type"]),
                                    binding_kind=_input_role_for_binding_kind(
                                        operation.binding_kind
                                    ),
                                )
                            self._validate_model_selection(
                                str(target_node["node_type"]),
                                str(target_node["model_selection_mode"]),
                                cast(str | None, target_node["model_ref"]),
                            )
                            binding_id = f"binding_{uuid4().hex}"
                            connection.execute(
                                insert(AgentCanvasBindingRow).values(
                                    binding_id=binding_id,
                                    workflow_id=plan.workflow_id,
                                    source_kind=source_kind,
                                    source_node_id=source_node_id,
                                    source_asset_id=source_asset_id,
                                    target_node_id=target_node_id,
                                    input_role=_input_role_for_binding_kind(operation.binding_kind),
                                    required=operation.required,
                                    enabled=True,
                                    order_index=operation.display_order,
                                    label=None,
                                    metadata_json="{}",
                                    created_at=now,
                                    updated_at=now,
                                )
                            )
                            created_binding_ids.append(binding_id)
                            result = AgentOperationResultV2(
                                operation_id=operation.operation_id,
                                binding_id=binding_id,
                                status="applied",
                            )
                        elif operation_type == "patch_binding":
                            current = (
                                connection.execute(
                                    select(AgentCanvasBindingRow).where(
                                        AgentCanvasBindingRow.workflow_id == plan.workflow_id,
                                        AgentCanvasBindingRow.binding_id == operation.binding_id,
                                    )
                                )
                                .mappings()
                                .one_or_none()
                            )
                            if current is None:
                                raise _error(
                                    "canvas_binding_not_found",
                                    "Canvas binding was not found.",
                                )
                            values: dict[str, object] = {"updated_at": now}
                            if operation.required is not None:
                                values["required"] = operation.required
                            if operation.enabled is not None:
                                values["enabled"] = operation.enabled
                            if operation.display_order is not None:
                                values["order_index"] = operation.display_order
                            connection.execute(
                                update(AgentCanvasBindingRow)
                                .where(
                                    AgentCanvasBindingRow.workflow_id == plan.workflow_id,
                                    AgentCanvasBindingRow.binding_id == operation.binding_id,
                                )
                                .values(**values)
                            )
                            result = AgentOperationResultV2(
                                operation_id=operation.operation_id,
                                binding_id=operation.binding_id,
                                status="applied",
                            )
                        elif operation_type == "delete_binding":
                            deleted = connection.execute(
                                delete(AgentCanvasBindingRow).where(
                                    AgentCanvasBindingRow.workflow_id == plan.workflow_id,
                                    AgentCanvasBindingRow.binding_id == operation.binding_id,
                                )
                            )
                            if deleted.rowcount != 1:
                                raise _error(
                                    "canvas_binding_not_found",
                                    "Canvas binding was not found.",
                                )
                            deleted_binding_ids.append(operation.binding_id)
                            result = AgentOperationResultV2(
                                operation_id=operation.operation_id,
                                binding_id=operation.binding_id,
                                status="applied",
                            )
                        elif operation_type == "delete_node":
                            node_id = _resolve_node_ref(
                                connection,
                                plan.workflow_id,
                                operation.node,
                                resolved_nodes,
                            )
                            connection.execute(
                                delete(AgentCanvasBindingRow).where(
                                    AgentCanvasBindingRow.workflow_id == plan.workflow_id,
                                    (AgentCanvasBindingRow.source_node_id == node_id)
                                    | (AgentCanvasBindingRow.target_node_id == node_id),
                                )
                            )
                            connection.execute(
                                delete(AgentCanvasVariationDraftRow).where(
                                    AgentCanvasVariationDraftRow.source_node_id == node_id
                                )
                            )
                            deleted = connection.execute(
                                delete(AgentCanvasNodeRow).where(
                                    AgentCanvasNodeRow.workflow_id == plan.workflow_id,
                                    AgentCanvasNodeRow.node_id == node_id,
                                )
                            )
                            if deleted.rowcount != 1:
                                raise _error(
                                    "canvas_node_not_found",
                                    "Canvas node was not found.",
                                )
                            deleted_node_ids.append(node_id)
                            result = AgentOperationResultV2(
                                operation_id=operation.operation_id,
                                node_id=node_id,
                                status="applied",
                            )
                        elif operation_type == "request_node_run":
                            node_id = _resolve_node_ref(
                                connection,
                                plan.workflow_id,
                                operation.node,
                                resolved_nodes,
                            )
                            run_node_ids.append(node_id)
                            result = AgentOperationResultV2(
                                operation_id=operation.operation_id,
                                node_id=node_id,
                                status="queued",
                            )
                        else:
                            raise _error(
                                "agent_command_operation_not_supported",
                                f"Operation {operation_type} is not implemented.",
                            )
                        operation_results.append(result)
                    next_revision = current_revision + 1
                    connection.execute(
                        update(AgentCanvasWorkflowRow)
                        .where(
                            AgentCanvasWorkflowRow.workflow_id == plan.workflow_id,
                            AgentCanvasWorkflowRow.revision == current_revision,
                        )
                        .values(revision=next_revision, updated_at=now)
                    )
                    for result in operation_results:
                        connection.execute(
                            insert(AgentCanvasCommandOperationResultRow).values(
                                plan_id=plan.plan_id,
                                operation_id=result.operation_id,
                                result_json=result.model_dump_json(),
                                created_at=now,
                            )
                        )
                    receipt = AgentActionReceiptV2(
                        receipt_id=f"receipt_{plan.plan_id}",
                        workflow_id=plan.workflow_id,
                        plan_id=plan.plan_id,
                        actor_kind=plan.actor,
                        idempotency_key=plan.idempotency_key,
                        status="applied",
                        summary=_receipt_summary(created_node_ids),
                        created_node_ids=tuple(created_node_ids),
                        updated_node_ids=tuple(updated_node_ids),
                        deleted_node_ids=tuple(deleted_node_ids),
                        created_binding_ids=tuple(created_binding_ids),
                        deleted_binding_ids=tuple(deleted_binding_ids),
                        operation_results=tuple(operation_results),
                        workflow_revision=next_revision,
                        before_workflow_revision=current_revision,
                        placement_hints=_placement_hints_for(
                            plan.operations,
                            operation_results,
                        ),
                    )
                    connection.execute(
                        insert(AgentCanvasActionReceiptRow).values(
                            receipt_id=receipt.receipt_id,
                            workflow_id=receipt.workflow_id,
                            plan_id=receipt.plan_id,
                            action_id=None,
                            receipt_json=receipt.model_dump_json(),
                            created_at=now,
                        )
                    )
                    self._append_timeline(
                        connection,
                        conversation_id=plan.conversation_id,
                        workflow_id=plan.workflow_id,
                        entry_type="action_receipt",
                        content=receipt.summary,
                        metadata={"action_receipt": receipt.model_dump(mode="json")},
                        created_at=now,
                    )
                    connection.execute(
                        update(AgentCanvasCommandPlanRow)
                        .where(AgentCanvasCommandPlanRow.plan_id == plan.plan_id)
                        .values(status="applied", updated_at=now)
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=plan.workflow_id,
                            event_type="agent_command_plan_applied",
                            created_at=now,
                            payload={
                                "plan_id": plan.plan_id,
                                "revision": next_revision,
                            },
                        ),
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=plan.workflow_id,
                            event_type="agent_action_receipt_created",
                            created_at=now,
                            payload={
                                "receipt_id": receipt.receipt_id,
                                "plan_id": plan.plan_id,
                                "revision": next_revision,
                            },
                        ),
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_command_transaction_failed",
                "Agent command transaction failed.",
            ) from error
        return AgentCommandTransactionResultV2(
            workflow_id=plan.workflow_id,
            workflow_revision=next_revision,
            operation_results=tuple(operation_results),
            created_node_ids=tuple(created_node_ids),
            updated_node_ids=tuple(updated_node_ids),
            deleted_node_ids=tuple(deleted_node_ids),
            created_binding_ids=tuple(created_binding_ids),
            deleted_binding_ids=tuple(deleted_binding_ids),
            post_commit_run_node_ids=tuple(run_node_ids),
        )

    def update_receipt_run_outcome(
        self,
        plan_id: str,
        *,
        queued_execution_ids: tuple[str, ...],
        run_errors: tuple[str, ...],
    ) -> AgentActionReceiptV2:
        receipt = self.get_receipt_for_plan(plan_id)
        updated = receipt.model_copy(
            update={
                "status": ("applied_with_run_error" if run_errors else "applied"),
                "queued_execution_ids": queued_execution_ids,
                "run_queue_errors": run_errors,
            }
        )
        try:
            with self._database.engine.begin() as connection:
                changed = connection.execute(
                    update(AgentCanvasActionReceiptRow)
                    .where(AgentCanvasActionReceiptRow.plan_id == plan_id)
                    .values(receipt_json=updated.model_dump_json())
                )
                if changed.rowcount != 1:
                    raise _error(
                        "agent_action_receipt_not_found",
                        "Agent action receipt was not found.",
                    )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_command_storage_unavailable",
                "Receipt storage failed.",
            ) from error
        return updated

    def upsert_variation_draft(
        self,
        workflow_id: str,
        source_node_id: str,
        request: CanvasVariationDraftUpsertV2,
        *,
        expected_revision: int,
    ) -> CanvasVariationDraftResponseV2:
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    current_revision = _require_workflow_revision(
                        connection,
                        workflow_id,
                        expected_revision,
                    )
                    source = _require_node(connection, workflow_id, source_node_id)
                    _validate_variation_source(source)
                    existing = (
                        connection.execute(
                            select(AgentCanvasVariationDraftRow).where(
                                AgentCanvasVariationDraftRow.source_node_id == source_node_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    variation_revision = (
                        int(existing["variation_revision"]) + 1 if existing is not None else 1
                    )
                    created_at = str(existing["created_at"]) if existing is not None else now
                    values = {
                        "workflow_id": workflow_id,
                        "source_node_revision": int(source["revision"]),
                        "title": request.title,
                        "generation_prompt": request.generation_prompt,
                        "model_selection_mode": request.model_selection_mode,
                        "model_ref": request.model_ref,
                        "parameters_json": _dump(request.parameters),
                        "variation_revision": variation_revision,
                        "created_at": created_at,
                        "updated_at": now,
                    }
                    self._validate_model_selection(
                        str(source["node_type"]),
                        request.model_selection_mode,
                        request.model_ref,
                    )
                    if existing is None:
                        connection.execute(
                            insert(AgentCanvasVariationDraftRow).values(
                                source_node_id=source_node_id,
                                **values,
                            )
                        )
                    else:
                        connection.execute(
                            update(AgentCanvasVariationDraftRow)
                            .where(AgentCanvasVariationDraftRow.source_node_id == source_node_id)
                            .values(**values)
                        )
                    next_revision = current_revision + 1
                    connection.execute(
                        update(AgentCanvasWorkflowRow)
                        .where(
                            AgentCanvasWorkflowRow.workflow_id == workflow_id,
                            AgentCanvasWorkflowRow.revision == current_revision,
                        )
                        .values(revision=next_revision, updated_at=now)
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            node_id=source_node_id,
                            event_type="canvas_variation_draft_saved",
                            created_at=now,
                            payload={
                                "source_node_id": source_node_id,
                                "revision": next_revision,
                                "variation_revision": variation_revision,
                            },
                        ),
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_command_storage_unavailable",
                "Variation storage failed.",
            ) from error
        return CanvasVariationDraftResponseV2(
            workflow_id=workflow_id,
            workflow_revision=next_revision,
            node_id=source_node_id,
            variation_draft=CanvasVariationDraftV2(
                source_node_id=source_node_id,
                source_node_revision=int(source["revision"]),
                title=request.title,
                generation_prompt=request.generation_prompt,
                model_selection_mode=request.model_selection_mode,
                model_ref=request.model_ref,
                parameters=request.parameters,
                variation_revision=variation_revision,
                created_at=created_at,
                updated_at=now,
            ),
        )

    def discard_variation_draft(
        self,
        workflow_id: str,
        source_node_id: str,
        *,
        expected_revision: int,
    ) -> int:
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    current_revision = _require_workflow_revision(
                        connection,
                        workflow_id,
                        expected_revision,
                    )
                    _require_node(connection, workflow_id, source_node_id)
                    deleted = connection.execute(
                        delete(AgentCanvasVariationDraftRow).where(
                            AgentCanvasVariationDraftRow.workflow_id == workflow_id,
                            AgentCanvasVariationDraftRow.source_node_id == source_node_id,
                        )
                    )
                    if deleted.rowcount != 1:
                        raise _error(
                            "variation_draft_not_found",
                            "Variation draft was not found.",
                        )
                    next_revision = current_revision + 1
                    connection.execute(
                        update(AgentCanvasWorkflowRow)
                        .where(
                            AgentCanvasWorkflowRow.workflow_id == workflow_id,
                            AgentCanvasWorkflowRow.revision == current_revision,
                        )
                        .values(revision=next_revision, updated_at=now)
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            node_id=source_node_id,
                            event_type="canvas_variation_draft_discarded",
                            created_at=now,
                            payload={
                                "source_node_id": source_node_id,
                                "revision": next_revision,
                            },
                        ),
                    )
                    connection.commit()
                    return next_revision
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_command_storage_unavailable",
                "Variation storage failed.",
            ) from error

    def materialize_variation_draft(
        self,
        workflow_id: str,
        source_node_id: str,
        request: CanvasVariationMaterializeRequestV2,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> tuple[CanvasVariationMaterializeResponseV2, bool]:
        if not idempotency_key:
            raise _error("idempotency_key_required", "Idempotency-Key is required.")
        operation = "agent_canvas_variation_materialize"
        request_fingerprint = _digest(
            _dump(
                {
                    "workflow_id": workflow_id,
                    "source_node_id": source_node_id,
                    "request": request.model_dump(mode="json"),
                }
            )
        )
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    replay = _load_idempotency_response(
                        connection,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_fingerprint,
                    )
                    if replay is not None:
                        connection.commit()
                        return (
                            CanvasVariationMaterializeResponseV2.model_validate_json(replay),
                            False,
                        )
                    current_revision = _require_workflow_revision(
                        connection,
                        workflow_id,
                        expected_revision,
                    )
                    source = _require_node(connection, workflow_id, source_node_id)
                    _validate_variation_source(source)
                    source_content = json.loads(str(source["structured_content_json"]))
                    source_metadata = json.loads(str(source["metadata_json"]))
                    character_pair_variation = (
                        str(source["creative_role"]) == "character"
                        and source_content.get("character_asset_kind") == "identity_master"
                    )
                    variation = (
                        connection.execute(
                            select(AgentCanvasVariationDraftRow).where(
                                AgentCanvasVariationDraftRow.workflow_id == workflow_id,
                                AgentCanvasVariationDraftRow.source_node_id == source_node_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if variation is None:
                        raise _error(
                            "variation_draft_not_found",
                            "Variation draft was not found.",
                        )
                    sibling_node_id = f"node_{uuid4().hex}"
                    character_pair_id = f"pair_{uuid4().hex}" if character_pair_variation else None
                    position = request.position or CanvasPositionV2(
                        x=float(source["position_x"]) + 360.0,
                        y=float(source["position_y"]),
                    )
                    sibling = CanvasNodeV2(
                        node_id=sibling_node_id,
                        workflow_id=workflow_id,
                        node_type=str(source["node_type"]),
                        creative_role=str(source["creative_role"]),
                        role_contract_version=str(source["role_contract_version"]),
                        title=str(variation["title"]),
                        status="draft",
                        summary_prompt=cast(str | None, source["summary_prompt"]),
                        generation_prompt=str(variation["generation_prompt"]),
                        structured_content=source_content,
                        model_selection_mode=cast(str, variation["model_selection_mode"]),
                        model_ref=cast(str | None, variation["model_ref"]),
                        parameters=json.loads(str(variation["parameters_json"])),
                        metadata=(
                            {**source_metadata, "character_pair_id": character_pair_id}
                            if character_pair_id is not None
                            else {}
                        ),
                        prompt_context_snapshot_id=None,
                        output_asset_id=None,
                        position=position,
                        revision=1,
                        error=None,
                        variation_draft=None,
                        created_at=now,
                        updated_at=now,
                    )
                    self._validate_model_selection(
                        sibling.node_type,
                        sibling.model_selection_mode,
                        sibling.model_ref,
                    )
                    connection.execute(
                        insert(AgentCanvasNodeRow).values(
                            node_id=sibling.node_id,
                            workflow_id=sibling.workflow_id,
                            node_type=sibling.node_type,
                            creative_role=sibling.creative_role,
                            role_contract_version=sibling.role_contract_version,
                            title=sibling.title,
                            status=sibling.status,
                            summary_prompt=sibling.summary_prompt,
                            generation_prompt=sibling.generation_prompt,
                            structured_content_json=_dump(sibling.structured_content),
                            model_selection_mode=sibling.model_selection_mode,
                            model_ref=sibling.model_ref,
                            parameters_json=_dump(sibling.parameters),
                            metadata_json=_dump(sibling.metadata),
                            parameter_provenance_json=_dump({}),
                            prompt_context_snapshot_id=None,
                            output_asset_id=None,
                            position_x=sibling.position.x,
                            position_y=sibling.position.y,
                            revision=1,
                            error_json=None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    incoming = (
                        connection.execute(
                            select(AgentCanvasBindingRow)
                            .where(
                                AgentCanvasBindingRow.workflow_id == workflow_id,
                                AgentCanvasBindingRow.target_node_id == source_node_id,
                            )
                            .order_by(
                                AgentCanvasBindingRow.order_index.asc(),
                                AgentCanvasBindingRow.created_at.asc(),
                                AgentCanvasBindingRow.binding_id.asc(),
                            )
                        )
                        .mappings()
                        .all()
                    )
                    copied_binding_ids: list[str] = []
                    for binding in incoming:
                        binding_id = f"binding_{uuid4().hex}"
                        connection.execute(
                            insert(AgentCanvasBindingRow).values(
                                binding_id=binding_id,
                                workflow_id=workflow_id,
                                source_kind=binding["source_kind"],
                                source_node_id=binding["source_node_id"],
                                source_asset_id=binding["source_asset_id"],
                                target_node_id=sibling_node_id,
                                input_role=binding["input_role"],
                                required=binding["required"],
                                enabled=binding["enabled"],
                                order_index=binding["order_index"],
                                label=binding["label"],
                                metadata_json=binding["metadata_json"],
                                created_at=now,
                                updated_at=now,
                            )
                        )
                        copied_binding_ids.append(binding_id)
                    created_nodes = [sibling]
                    created_binding_ids = list(copied_binding_ids)
                    placement_hints = [
                        AgentPlacementHintV2(
                            intent="right_sibling",
                            anchor_node_id=source_node_id,
                            group_key=character_pair_id,
                        )
                    ]
                    if character_pair_id is not None:
                        turnaround_node_id = f"node_{uuid4().hex}"
                        turnaround_content = {
                            **source_content,
                            "character_asset_kind": "turnaround",
                        }
                        turnaround = CanvasNodeV2(
                            node_id=turnaround_node_id,
                            workflow_id=workflow_id,
                            node_type="image",
                            creative_role="character",
                            role_contract_version=str(source["role_contract_version"]),
                            title=f"{variation['title']} Turnaround",
                            status="draft",
                            summary_prompt=(
                                f"Front, side, and back identity sheet for {variation['title']}."
                            ),
                            generation_prompt=character_turnaround_prompt(
                                subject_identity=str(source_content["subject_identity"]),
                                design_summary=str(source_content["design_summary"]),
                            ),
                            structured_content=turnaround_content,
                            model_selection_mode=cast(str, variation["model_selection_mode"]),
                            model_ref=cast(str | None, variation["model_ref"]),
                            parameters=json.loads(str(variation["parameters_json"])),
                            metadata={
                                **source_metadata,
                                "character_pair_id": character_pair_id,
                            },
                            prompt_context_snapshot_id=None,
                            output_asset_id=None,
                            position=CanvasPositionV2(
                                x=sibling.position.x + 360.0,
                                y=sibling.position.y,
                            ),
                            revision=1,
                            error=None,
                            variation_draft=None,
                            created_at=now,
                            updated_at=now,
                        )
                        self._validate_model_selection(
                            turnaround.node_type,
                            turnaround.model_selection_mode,
                            turnaround.model_ref,
                        )
                        connection.execute(
                            insert(AgentCanvasNodeRow).values(
                                node_id=turnaround.node_id,
                                workflow_id=turnaround.workflow_id,
                                node_type=turnaround.node_type,
                                creative_role=turnaround.creative_role,
                                role_contract_version=turnaround.role_contract_version,
                                title=turnaround.title,
                                status=turnaround.status,
                                summary_prompt=turnaround.summary_prompt,
                                generation_prompt=turnaround.generation_prompt,
                                structured_content_json=_dump(turnaround.structured_content),
                                model_selection_mode=turnaround.model_selection_mode,
                                model_ref=turnaround.model_ref,
                                parameters_json=_dump(turnaround.parameters),
                                metadata_json=_dump(turnaround.metadata),
                                parameter_provenance_json=_dump({}),
                                prompt_context_snapshot_id=None,
                                output_asset_id=None,
                                position_x=turnaround.position.x,
                                position_y=turnaround.position.y,
                                revision=1,
                                error_json=None,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                        internal_binding_id = f"binding_{uuid4().hex}"
                        connection.execute(
                            insert(AgentCanvasBindingRow).values(
                                binding_id=internal_binding_id,
                                workflow_id=workflow_id,
                                source_kind="node_output",
                                source_node_id=sibling.node_id,
                                source_asset_id=None,
                                target_node_id=turnaround.node_id,
                                input_role="image_reference",
                                required=True,
                                enabled=True,
                                order_index=0,
                                label="Character identity master",
                                metadata_json=_dump(
                                    AgentCanvasReferenceSemanticPolicy.character_pair_metadata(
                                        character_pair_id
                                    )
                                ),
                                created_at=now,
                                updated_at=now,
                            )
                        )
                        created_nodes.append(turnaround)
                        created_binding_ids.append(internal_binding_id)
                        placement_hints.append(
                            AgentPlacementHintV2(
                                intent="right_sibling",
                                anchor_node_id=sibling.node_id,
                                group_key=character_pair_id,
                            )
                        )
                    connection.execute(
                        delete(AgentCanvasVariationDraftRow).where(
                            AgentCanvasVariationDraftRow.workflow_id == workflow_id,
                            AgentCanvasVariationDraftRow.source_node_id == source_node_id,
                        )
                    )
                    next_revision = current_revision + 1
                    connection.execute(
                        update(AgentCanvasWorkflowRow)
                        .where(
                            AgentCanvasWorkflowRow.workflow_id == workflow_id,
                            AgentCanvasWorkflowRow.revision == current_revision,
                        )
                        .values(revision=next_revision, updated_at=now)
                    )
                    placement_hint = placement_hints[0]
                    response = CanvasVariationMaterializeResponseV2(
                        workflow_id=workflow_id,
                        workflow_revision=next_revision,
                        source_node_id=source_node_id,
                        sibling_node=sibling,
                        copied_binding_ids=tuple(copied_binding_ids),
                        placement_hint=placement_hint,
                        created_node_ids=tuple(node.node_id for node in created_nodes),
                        created_binding_ids=tuple(created_binding_ids),
                        placement_hints=tuple(placement_hints),
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            node_id=sibling_node_id,
                            event_type="canvas_variation_materialized",
                            created_at=now,
                            payload={
                                "source_node_id": source_node_id,
                                "sibling_node_id": sibling_node_id,
                                "created_node_ids": list(response.created_node_ids),
                                "created_binding_ids": list(response.created_binding_ids),
                                "copied_binding_ids": copied_binding_ids,
                                "revision": next_revision,
                                "placement_hint": placement_hint.model_dump(mode="json"),
                                "placement_hints": [
                                    hint.model_dump(mode="json")
                                    for hint in response.placement_hints
                                ],
                            },
                        ),
                    )
                    _store_idempotency_response(
                        connection,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_fingerprint,
                        response_json=response.model_dump_json(),
                        created_at=now,
                    )
                    connection.commit()
                    return response, True
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "variation_materialization_conflict",
                "Variation materialization failed.",
            ) from error

    def update_variation_materialization_response(
        self,
        *,
        idempotency_key: str,
        response: CanvasVariationMaterializeResponseV2,
    ) -> None:
        try:
            with self._database.engine.begin() as connection:
                updated = connection.execute(
                    update(AgentCanvasIdempotencyRow)
                    .where(
                        AgentCanvasIdempotencyRow.operation == "agent_canvas_variation_materialize",
                        AgentCanvasIdempotencyRow.idempotency_key == idempotency_key,
                    )
                    .values(response_json=response.model_dump_json())
                )
                if updated.rowcount != 1:
                    raise _error(
                        "variation_materialization_conflict",
                        "Variation materialization result was not found.",
                    )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_command_storage_unavailable",
                "Variation materialization result storage failed.",
            ) from error

    def store_receipt(self, receipt: AgentActionReceiptV2) -> AgentActionReceiptV2:
        now = _now()
        payload = receipt.model_dump_json()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    existing = (
                        connection.execute(
                            select(AgentCanvasActionReceiptRow).where(
                                AgentCanvasActionReceiptRow.receipt_id == receipt.receipt_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is not None:
                        stored = AgentActionReceiptV2.model_validate_json(
                            str(existing["receipt_json"])
                        )
                        if stored != receipt:
                            raise _error(
                                "idempotency_conflict",
                                "Receipt identifier was reused.",
                            )
                        connection.commit()
                        return stored
                    connection.execute(
                        insert(AgentCanvasActionReceiptRow).values(
                            receipt_id=receipt.receipt_id,
                            workflow_id=receipt.workflow_id,
                            plan_id=receipt.plan_id,
                            action_id=receipt.action_id,
                            receipt_json=payload,
                            created_at=now,
                        )
                    )
                    plan_row = (
                        connection.execute(
                            select(AgentCanvasCommandPlanRow).where(
                                AgentCanvasCommandPlanRow.plan_id == receipt.plan_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                        if receipt.plan_id is not None
                        else None
                    )
                    conversation_id = (
                        str(plan_row["conversation_id"]) if plan_row is not None else None
                    )
                    if conversation_id is None and receipt.action_id is not None:
                        conversation_id = connection.execute(
                            select(AgentCanvasChatTurnRow.conversation_id).where(
                                AgentCanvasChatTurnRow.turn_id == receipt.action_id
                            )
                        ).scalar_one_or_none()
                    if conversation_id is None and receipt.action_id is not None:
                        conversation_id = connection.execute(
                            select(AgentCanvasChatTurnRow.conversation_id)
                            .join(
                                AgentCanvasGuidedActionRow,
                                AgentCanvasGuidedActionRow.creating_turn_id
                                == AgentCanvasChatTurnRow.turn_id,
                            )
                            .where(AgentCanvasGuidedActionRow.action_id == receipt.action_id)
                        ).scalar_one_or_none()
                    if conversation_id is not None:
                        self._append_timeline(
                            connection,
                            conversation_id=str(conversation_id),
                            workflow_id=receipt.workflow_id,
                            entry_type="action_receipt",
                            content=receipt.summary,
                            metadata={"action_receipt": receipt.model_dump(mode="json")},
                            created_at=now,
                        )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=receipt.workflow_id,
                            event_type="agent_action_receipt_created",
                            created_at=now,
                            payload={
                                "receipt_id": receipt.receipt_id,
                                "plan_id": receipt.plan_id,
                                "revision": receipt.workflow_revision,
                            },
                        ),
                    )
                    connection.commit()
                    return receipt
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_command_storage_unavailable",
                "Receipt storage failed.",
            ) from error

    @staticmethod
    def _append_timeline(
        connection: Connection,
        *,
        conversation_id: str,
        workflow_id: str,
        entry_type: str,
        content: str,
        metadata: dict[str, Any],
        created_at: str,
    ) -> None:
        next_sequence = (
            int(
                connection.execute(
                    select(func.coalesce(func.max(AgentCanvasChatEntryRow.sequence_no), 0)).where(
                        AgentCanvasChatEntryRow.conversation_id == conversation_id
                    )
                ).scalar_one()
            )
            + 1
        )
        connection.execute(
            insert(AgentCanvasChatEntryRow).values(
                entry_id=f"entry_{uuid4().hex}",
                conversation_id=conversation_id,
                workflow_id=workflow_id,
                sequence_no=next_sequence,
                entry_type=entry_type,
                speaker=None,
                content=content,
                metadata_json=_dump(metadata),
                created_at=created_at,
            )
        )


def _resolve_node_ref(
    connection: Connection,
    workflow_id: str,
    reference: Any,
    operation_results: dict[str, str],
) -> str:
    if reference.kind == "operation_result":
        node_id = operation_results.get(reference.operation_id)
        if node_id is None:
            raise _error(
                "agent_command_operation_reference_invalid",
                "Operation result does not resolve to a node.",
            )
        return node_id
    _require_node(connection, workflow_id, reference.node_id)
    return str(reference.node_id)


def _input_role_for_binding_kind(binding_kind: object) -> str:
    return {
        "brief_context": "text_context",
        "script_context": "text_context",
        "text_context": "text_context",
        "image_reference": "image_reference",
        "video_reference": "video_reference",
        "audio_reference": "audio_reference",
    }.get(str(binding_kind), "text_context")


def _resolve_binding_source(
    connection: Connection,
    workflow_id: str,
    reference: Any,
    operation_results: dict[str, str],
) -> tuple[str, str | None, str | None]:
    if reference.kind == "image_asset":
        return "image_asset", None, str(reference.asset_id)
    return (
        "node_output",
        _resolve_node_ref(connection, workflow_id, reference, operation_results),
        None,
    )


def _creative_role(value: object) -> str:
    return {
        "generation_brief": "creative_brief",
        "generic_text": "general_text",
        "advertising_script": "script",
        "generic_image": "general_image",
        "uploaded_image": "general_image",
        "product_main": "product",
        "product_view_board": "product",
        "prop_main": "prop",
        "character_main": "character",
        "character_turnaround": "character",
        "scene_design_board": "scene",
        "storyboard_grid": "storyboard_sequence",
        "generic_video": "general_video",
        "uploaded_video": "general_video",
        "storyboard_video_segment": "storyboard_video",
        "generic_audio": "general_audio",
        "uploaded_audio": "general_audio",
        "final_composition": "editing",
    }.get(str(value), str(value))


def _require_node(
    connection: Connection,
    workflow_id: str,
    node_id: str,
) -> RowMapping:
    row = (
        connection.execute(
            select(AgentCanvasNodeRow).where(
                AgentCanvasNodeRow.workflow_id == workflow_id,
                AgentCanvasNodeRow.node_id == node_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _error("canvas_node_not_found", "Canvas node was not found.")
    return row


def _require_workflow_revision(
    connection: Connection,
    workflow_id: str,
    expected_revision: int,
) -> int:
    revision = connection.execute(
        select(AgentCanvasWorkflowRow.revision).where(
            AgentCanvasWorkflowRow.workflow_id == workflow_id
        )
    ).scalar_one_or_none()
    if revision is None:
        raise _error("workflow_not_found", "Workflow was not found.")
    if int(revision) != expected_revision:
        raise _error(
            "workflow_revision_conflict",
            "Workflow revision does not match the current revision.",
        )
    return int(revision)


def _applied_transaction_result(
    connection: Connection,
    plan: AgentCommandPlanV2,
) -> AgentCommandTransactionResultV2:
    rows = list(
        connection.execute(
            select(AgentCanvasCommandOperationResultRow).where(
                AgentCanvasCommandOperationResultRow.plan_id == plan.plan_id
            )
        ).mappings()
    )
    results_by_id = {
        str(row["operation_id"]): AgentOperationResultV2.model_validate_json(
            str(row["result_json"])
        )
        for row in rows
    }
    if set(results_by_id) != {operation.operation_id for operation in plan.operations}:
        raise _error(
            "agent_command_result_incomplete",
            "Applied Agent command results are incomplete.",
        )

    operation_results = tuple(
        results_by_id[operation.operation_id] for operation in plan.operations
    )
    operation_types = {
        operation.operation_id: operation.operation_type for operation in plan.operations
    }

    def node_ids(*types: str) -> tuple[str, ...]:
        return tuple(
            result.node_id
            for result in operation_results
            if operation_types[result.operation_id] in types and result.node_id is not None
        )

    def binding_ids(*types: str) -> tuple[str, ...]:
        return tuple(
            result.binding_id
            for result in operation_results
            if operation_types[result.operation_id] in types and result.binding_id is not None
        )

    return AgentCommandTransactionResultV2(
        workflow_id=plan.workflow_id,
        workflow_revision=plan.base_workflow_revision + 1,
        operation_results=operation_results,
        created_node_ids=node_ids(
            "create_draft_node",
            "materialize_sibling_draft",
        ),
        updated_node_ids=node_ids(
            "patch_editable_node",
        ),
        deleted_node_ids=node_ids("delete_node"),
        created_binding_ids=binding_ids("create_binding"),
        deleted_binding_ids=binding_ids("delete_binding"),
        post_commit_run_node_ids=node_ids("request_node_run"),
    )


def _plan_from_row(row: RowMapping) -> AgentCommandPlanV2:
    return _plan_from_mapping(cast(dict[str, Any], row))


def _plan_from_mapping(row: dict[str, Any] | RowMapping) -> AgentCommandPlanV2:
    return AgentCommandPlanV2(
        plan_id=str(row["plan_id"]),
        workflow_id=str(row["workflow_id"]),
        conversation_id=str(row["conversation_id"]),
        source_turn_id=str(row["source_turn_id"]),
        context_snapshot_id=str(row["context_snapshot_id"]),
        base_workflow_revision=int(row["base_workflow_revision"]),
        expires_at=str(row["expires_at"]),
        operations=tuple(json.loads(str(row["operations_json"]))),
        operation_fingerprint=str(row["operation_fingerprint"]),
        idempotency_key=str(row["idempotency_key"]),
        risk=cast(str, row["risk"]),
        confirmation_required=bool(row["confirmation_required"]),
        status=cast(str, row["status"]),
        continuation_requested=bool(row["continuation_requested"]),
        target_summary=str(row["target_summary"]),
        supersedes_plan_id=(str(row["supersedes_plan_id"]) if row["supersedes_plan_id"] else None),
        replacement_plan_id=(
            str(row["replacement_plan_id"]) if row["replacement_plan_id"] else None
        ),
        actor=cast(str, row["actor"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _receipt_summary(created_node_ids: list[str]) -> str:
    if created_node_ids:
        return f"Created {len(created_node_ids)} canvas node(s)."
    return "Applied the requested canvas changes."


def _placement_hints_for(
    operations: tuple[Any, ...],
    results: list[AgentOperationResultV2],
) -> tuple[AgentPlacementHintV2, ...]:
    node_operations = {result.operation_id for result in results if result.node_id is not None}
    return tuple(
        placement_hint
        for operation in operations
        if operation.operation_id in node_operations
        and (placement_hint := getattr(operation, "placement_hint", None)) is not None
    )


def _load_idempotency_response(
    connection: Connection,
    *,
    operation: str,
    idempotency_key: str,
    request_fingerprint: str,
) -> str | None:
    row = (
        connection.execute(
            select(
                AgentCanvasIdempotencyRow.request_fingerprint,
                AgentCanvasIdempotencyRow.response_json,
            ).where(
                AgentCanvasIdempotencyRow.operation == operation,
                AgentCanvasIdempotencyRow.idempotency_key == idempotency_key,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    if str(row["request_fingerprint"]) != request_fingerprint:
        raise _error(
            "idempotency_conflict",
            "Idempotency key was reused with a different request.",
        )
    return str(row["response_json"])


def _store_idempotency_response(
    connection: Connection,
    *,
    operation: str,
    idempotency_key: str,
    request_fingerprint: str,
    response_json: str,
    created_at: str,
) -> None:
    connection.execute(
        insert(AgentCanvasIdempotencyRow).values(
            record_id=f"idem_{uuid4().hex}",
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            response_json=response_json,
            created_at=created_at,
        )
    )


def _validate_variation_source(source: RowMapping) -> None:
    if str(source["status"]) != "ready" or source["output_asset_id"] is None:
        raise _error(
            "variation_source_not_ready",
            "Variation source must be Ready media.",
        )
    if str(source["node_type"]) not in {"image", "video", "audio"}:
        raise _error(
            "variation_source_media_type_unsupported",
            "Variation source media type is not supported.",
        )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_command_repository")
