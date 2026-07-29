"""Transactional SQLite repositories for Agent Canvas V1 authoring."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import cast
from uuid import uuid4

from pydantic import JsonValue
from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasBindingRow,
    AgentCanvasDocumentRow,
    AgentCanvasIdempotencyRow,
    AgentCanvasNodeRow,
    AgentCanvasPromptContextSnapshotRow,
    AgentCanvasWorkflowRow,
    WorkflowRow,
)
from app.persistence.project_repository import ProjectRepository
from app.schemas.agent_canvas import (
    AgentCanvasDocumentRecordV2,
    AgentCanvasPromptContextSnapshotV2,
    AgentCanvasWorkflowV2,
    CanvasBindingSourceImageAssetV2,
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    CanvasNodeErrorV2,
    CanvasNodeV2,
    CanvasPositionV2,
    ResolvedTextInputSnapshotV2,
)
from app.schemas.agent_canvas_editing import EditingNodeContentV2
from app.schemas.v2_persistence import V2EventInsert
from app.schemas.workflow_v2_projects import ProjectCreate


class AgentCanvasWorkflowRepository:
    """Own Agent Canvas workflow, node, binding, and revision transactions."""

    def __init__(
        self,
        database: V2Database,
        projects: ProjectRepository,
        events: EventRepository,
    ) -> None:
        if projects.database is not database or events.database is not database:
            raise ValueError("Agent Canvas repositories must share one V2Database.")
        self._database = database
        self._projects = projects
        self._events = events

    @property
    def database(self) -> V2Database:
        return self._database

    def create_empty(
        self,
        *,
        project: ProjectCreate,
        workflow_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> AgentCanvasWorkflowV2:
        """Atomically create one Project and its empty Agent Canvas workflow."""

        if not idempotency_key or not request_fingerprint:
            raise _invalid_idempotency_error()
        now = project.created_at
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    replay = _load_idempotency(
                        connection,
                        operation="create_project",
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_fingerprint,
                    )
                    if replay is not None:
                        connection.commit()
                        return AgentCanvasWorkflowV2.model_validate_json(replay)

                    self._projects.insert_in_transaction(connection, project)
                    connection.execute(
                        insert(AgentCanvasWorkflowRow).values(
                            workflow_id=workflow_id,
                            project_id=project.project_id,
                            workflow_schema_version=2,
                            canvas_model="agent_canvas_v1",
                            revision=1,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    created = AgentCanvasWorkflowV2(
                        workflow_id=workflow_id,
                        project_id=project.project_id,
                        revision=1,
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            event_type="project_created",
                            created_at=now,
                            payload={
                                "project_id": project.project_id,
                                "canvas_model": "agent_canvas_v1",
                                "revision": 1,
                            },
                        ),
                    )
                    _store_idempotency(
                        connection,
                        operation="create_project",
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_fingerprint,
                        response_json=created.model_dump_json(),
                        created_at=now,
                    )
                    connection.commit()
                    return created
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _conflict_error("agent_canvas_create_conflict") from error
        except SQLAlchemyError as error:
            raise _unavailable_error() from error

    def get_workflow(self, workflow_id: str) -> AgentCanvasWorkflowV2:
        """Load the complete Agent Canvas authoring read model from SQLite."""

        try:
            with self._database.engine.connect() as connection:
                workflow = (
                    connection.execute(
                        select(
                            AgentCanvasWorkflowRow.workflow_id,
                            AgentCanvasWorkflowRow.project_id,
                            AgentCanvasWorkflowRow.workflow_schema_version,
                            AgentCanvasWorkflowRow.canvas_model,
                            AgentCanvasWorkflowRow.revision,
                        ).where(AgentCanvasWorkflowRow.workflow_id == workflow_id)
                    )
                    .mappings()
                    .one_or_none()
                )
                if workflow is None:
                    raise _workflow_not_found_error()
                node_rows = (
                    connection.execute(
                        select(AgentCanvasNodeRow)
                        .where(AgentCanvasNodeRow.workflow_id == workflow_id)
                        .order_by(
                            AgentCanvasNodeRow.created_at.asc(),
                            AgentCanvasNodeRow.node_id.asc(),
                        )
                    )
                    .mappings()
                    .all()
                )
                binding_rows = (
                    connection.execute(
                        select(AgentCanvasBindingRow)
                        .where(AgentCanvasBindingRow.workflow_id == workflow_id)
                        .order_by(
                            AgentCanvasBindingRow.target_node_id.asc(),
                            AgentCanvasBindingRow.display_order.asc(),
                            AgentCanvasBindingRow.binding_id.asc(),
                        )
                    )
                    .mappings()
                    .all()
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return AgentCanvasWorkflowV2(
            workflow_id=str(workflow["workflow_id"]),
            project_id=str(workflow["project_id"]),
            workflow_schema_version=int(workflow["workflow_schema_version"]),
            canvas_model=cast(str, workflow["canvas_model"]),
            revision=int(workflow["revision"]),
            nodes=tuple(_node_from_row(row) for row in node_rows),
            bindings=tuple(_binding_from_row(row) for row in binding_rows),
            assets=(),
        )

    def workflow_id_for_project(self, project_id: str) -> str:
        try:
            with self._database.engine.connect() as connection:
                workflow_id = connection.execute(
                    select(AgentCanvasWorkflowRow.workflow_id).where(
                        AgentCanvasWorkflowRow.project_id == project_id
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        if workflow_id is None:
            raise _workflow_not_found_error()
        return str(workflow_id)

    def legacy_workflow_exists(self, workflow_id: str) -> bool:
        try:
            with self._database.engine.connect() as connection:
                existing = connection.execute(
                    select(WorkflowRow.workflow_id).where(WorkflowRow.workflow_id == workflow_id)
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return existing is not None

    def get_node(self, workflow_id: str, node_id: str) -> CanvasNodeV2:
        try:
            with self._database.engine.connect() as connection:
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
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        if row is None:
            raise _node_not_found_error()
        return _node_from_row(row)

    def asset_is_referenced(self, asset_id: str) -> bool:
        """Return whether active canvas authoring points at one asset."""

        try:
            with self._database.engine.connect() as connection:
                node_reference = connection.execute(
                    select(AgentCanvasNodeRow.node_id).where(
                        AgentCanvasNodeRow.output_asset_id == asset_id
                    )
                ).first()
                binding_reference = connection.execute(
                    select(AgentCanvasBindingRow.binding_id).where(
                        AgentCanvasBindingRow.source_asset_id == asset_id
                    )
                ).first()
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return node_reference is not None or binding_reference is not None

    def add_node(
        self,
        node: CanvasNodeV2,
        *,
        expected_revision: int,
    ) -> AgentCanvasWorkflowV2:
        """Insert one node and advance the workflow revision exactly once."""

        now = node.updated_at.isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    current_revision = _require_workflow_revision(
                        connection, node.workflow_id, expected_revision
                    )
                    connection.execute(insert(AgentCanvasNodeRow).values(**_node_values(node)))
                    _advance_workflow_revision(
                        connection,
                        workflow_id=node.workflow_id,
                        current_revision=current_revision,
                        updated_at=now,
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=node.workflow_id,
                            node_id=node.node_id,
                            event_type="canvas_node_created",
                            created_at=now,
                            payload={
                                "node_type": node.node_type,
                                "semantic_role": node.semantic_role,
                                "revision": current_revision + 1,
                            },
                        ),
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _conflict_error("canvas_node_conflict") from error
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return self.get_workflow(node.workflow_id)

    def add_node_with_bindings(
        self,
        node: CanvasNodeV2,
        bindings: tuple[CanvasBindingV2, ...],
        *,
        expected_revision: int,
    ) -> AgentCanvasWorkflowV2:
        """Insert one node and its copied inputs as one authoring revision."""

        now = node.updated_at.isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    current_revision = _require_workflow_revision(
                        connection, node.workflow_id, expected_revision
                    )
                    connection.execute(insert(AgentCanvasNodeRow).values(**_node_values(node)))
                    for binding in bindings:
                        if (
                            binding.workflow_id != node.workflow_id
                            or binding.target_node_id != node.node_id
                        ):
                            raise _invalid_binding_batch_error()
                        if isinstance(binding.source, CanvasBindingSourceNodeV2):
                            _require_node(
                                connection,
                                binding.workflow_id,
                                binding.source.node_id,
                            )
                        connection.execute(
                            insert(AgentCanvasBindingRow).values(**_binding_values(binding))
                        )
                    _advance_workflow_revision(
                        connection,
                        workflow_id=node.workflow_id,
                        current_revision=current_revision,
                        updated_at=now,
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=node.workflow_id,
                            node_id=node.node_id,
                            event_type="canvas_node_created",
                            created_at=now,
                            payload={
                                "node_type": node.node_type,
                                "semantic_role": node.semantic_role,
                                "copied_binding_ids": [binding.binding_id for binding in bindings],
                                "revision": current_revision + 1,
                            },
                        ),
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _conflict_error("canvas_node_conflict") from error
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return self.get_workflow(node.workflow_id)

    def update_node(
        self,
        node: CanvasNodeV2,
        *,
        expected_revision: int,
    ) -> AgentCanvasWorkflowV2:
        """Replace one node record and advance authoring once."""

        now = node.updated_at.isoformat()
        values = _node_values(node)
        values.pop("node_id")
        values.pop("workflow_id")
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    current_revision = _require_workflow_revision(
                        connection, node.workflow_id, expected_revision
                    )
                    updated = connection.execute(
                        update(AgentCanvasNodeRow)
                        .where(
                            AgentCanvasNodeRow.workflow_id == node.workflow_id,
                            AgentCanvasNodeRow.node_id == node.node_id,
                        )
                        .values(**values)
                    )
                    if updated.rowcount != 1:
                        raise _node_not_found_error()
                    _advance_workflow_revision(
                        connection,
                        workflow_id=node.workflow_id,
                        current_revision=current_revision,
                        updated_at=now,
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=node.workflow_id,
                            node_id=node.node_id,
                            event_type="canvas_node_updated",
                            created_at=now,
                            payload={
                                "node_revision": node.revision,
                                "revision": current_revision + 1,
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
            raise _unavailable_error() from error
        return self.get_workflow(node.workflow_id)

    def set_node_runtime_state(
        self,
        workflow_id: str,
        node_id: str,
        *,
        status: str,
        updated_at: datetime,
        error: CanvasNodeErrorV2 | None = None,
        event_type: str,
        execution_id: str,
        event_payload: dict[str, object] | None = None,
    ) -> CanvasNodeV2:
        """Update operational node state without advancing authoring revision."""

        timestamp = updated_at.isoformat()
        try:
            with self._database.engine.begin() as connection:
                changed = connection.execute(
                    update(AgentCanvasNodeRow)
                    .where(
                        AgentCanvasNodeRow.workflow_id == workflow_id,
                        AgentCanvasNodeRow.node_id == node_id,
                    )
                    .values(
                        status=status,
                        error_json=error.model_dump_json() if error else None,
                        updated_at=timestamp,
                    )
                )
                if changed.rowcount != 1:
                    raise _node_not_found_error()
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        execution_id=execution_id,
                        node_id=node_id,
                        event_type=event_type,
                        created_at=timestamp,
                        payload=event_payload or {},
                    ),
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return self.get_node(workflow_id, node_id)

    def publish_node_output(
        self,
        workflow_id: str,
        node_id: str,
        *,
        execution_id: str,
        updated_at: datetime,
        output_asset_id: str | None = None,
        structured_content: dict[str, object] | None = None,
    ) -> CanvasNodeV2:
        """Publish a validated output and terminal node event monotonically."""

        timestamp = updated_at.isoformat()
        try:
            with self._database.engine.begin() as connection:
                current = (
                    connection.execute(
                        select(AgentCanvasNodeRow).where(
                            AgentCanvasNodeRow.workflow_id == workflow_id,
                            AgentCanvasNodeRow.node_id == node_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if current is None:
                    raise _node_not_found_error()
                if str(current["status"]) == "ready":
                    return _node_from_row(current)
                values: dict[str, object] = {
                    "status": "ready",
                    "error_json": None,
                    "updated_at": timestamp,
                }
                if output_asset_id is not None:
                    values["output_asset_id"] = output_asset_id
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            execution_id=execution_id,
                            node_id=node_id,
                            asset_id=output_asset_id,
                            event_type="asset_published",
                            created_at=timestamp,
                            payload={"asset_id": output_asset_id},
                        ),
                    )
                if structured_content is not None:
                    values["structured_content_json"] = _json_dump(structured_content)
                connection.execute(
                    update(AgentCanvasNodeRow)
                    .where(
                        AgentCanvasNodeRow.workflow_id == workflow_id,
                        AgentCanvasNodeRow.node_id == node_id,
                    )
                    .values(**values)
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        execution_id=execution_id,
                        node_id=node_id,
                        asset_id=output_asset_id,
                        event_type="node_ready",
                        created_at=timestamp,
                        payload={"asset_id": output_asset_id},
                    ),
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return self.get_node(workflow_id, node_id)

    def set_editing_runtime_state(
        self,
        workflow_id: str,
        node_id: str,
        *,
        status: str,
        structured_content: dict[str, object],
        updated_at: datetime,
        event_type: str,
        export_id: str,
        output_asset_id: str | None = None,
        error: CanvasNodeErrorV2 | None = None,
    ) -> CanvasNodeV2:
        """Persist Editing operational state without an authoring revision."""

        timestamp = updated_at.isoformat()
        try:
            with self._database.engine.begin() as connection:
                current = (
                    connection.execute(
                        select(AgentCanvasNodeRow).where(
                            AgentCanvasNodeRow.workflow_id == workflow_id,
                            AgentCanvasNodeRow.node_id == node_id,
                            AgentCanvasNodeRow.node_type == "editing",
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if current is None:
                    raise _node_not_found_error()
                values: dict[str, object] = {
                    "status": status,
                    "structured_content_json": _json_dump(structured_content),
                    "error_json": error.model_dump_json() if error else None,
                    "updated_at": timestamp,
                }
                if output_asset_id is not None:
                    values["output_asset_id"] = output_asset_id
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            execution_id=export_id,
                            node_id=node_id,
                            asset_id=output_asset_id,
                            event_type="asset_published",
                            created_at=timestamp,
                            payload={
                                "asset_id": output_asset_id,
                                "source": "editing_export",
                            },
                        ),
                    )
                connection.execute(
                    update(AgentCanvasNodeRow)
                    .where(
                        AgentCanvasNodeRow.workflow_id == workflow_id,
                        AgentCanvasNodeRow.node_id == node_id,
                    )
                    .values(**values)
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        execution_id=export_id,
                        node_id=node_id,
                        asset_id=output_asset_id,
                        event_type=event_type,
                        created_at=timestamp,
                        payload={
                            "export_id": export_id,
                            "output_asset_id": output_asset_id,
                        },
                    ),
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return self.get_node(workflow_id, node_id)

    def delete_node(
        self,
        workflow_id: str,
        node_id: str,
        *,
        expected_revision: int,
    ) -> AgentCanvasWorkflowV2:
        """Delete authoring records for a node without deleting its assets."""

        now = _utc_now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    current_revision = _require_workflow_revision(
                        connection, workflow_id, expected_revision
                    )
                    _require_node(connection, workflow_id, node_id)
                    connection.execute(
                        delete(AgentCanvasDocumentRow).where(
                            AgentCanvasDocumentRow.workflow_id == workflow_id,
                            AgentCanvasDocumentRow.node_id == node_id,
                        )
                    )
                    removed_bindings = connection.execute(
                        delete(AgentCanvasBindingRow).where(
                            AgentCanvasBindingRow.workflow_id == workflow_id,
                            (
                                (AgentCanvasBindingRow.source_node_id == node_id)
                                | (AgentCanvasBindingRow.target_node_id == node_id)
                            ),
                        )
                    ).rowcount
                    connection.execute(
                        delete(AgentCanvasNodeRow).where(
                            AgentCanvasNodeRow.workflow_id == workflow_id,
                            AgentCanvasNodeRow.node_id == node_id,
                        )
                    )
                    _advance_workflow_revision(
                        connection,
                        workflow_id=workflow_id,
                        current_revision=current_revision,
                        updated_at=now,
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            node_id=node_id,
                            event_type="canvas_node_deleted",
                            created_at=now,
                            payload={
                                "removed_binding_count": removed_bindings,
                                "revision": current_revision + 1,
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
            raise _unavailable_error() from error
        return self.get_workflow(workflow_id)

    def add_binding(
        self,
        binding: CanvasBindingV2,
        *,
        expected_revision: int,
    ) -> AgentCanvasWorkflowV2:
        """Insert one real binding and advance the workflow revision once."""

        now = binding.created_at.isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    current_revision = _require_workflow_revision(
                        connection, binding.workflow_id, expected_revision
                    )
                    _require_node(connection, binding.workflow_id, binding.target_node_id)
                    if isinstance(binding.source, CanvasBindingSourceNodeV2):
                        _require_node(
                            connection,
                            binding.workflow_id,
                            binding.source.node_id,
                        )
                    connection.execute(
                        insert(AgentCanvasBindingRow).values(**_binding_values(binding))
                    )
                    _reconcile_editing_manifest_for_binding(
                        connection,
                        binding,
                        updated_at=now,
                    )
                    _advance_workflow_revision(
                        connection,
                        workflow_id=binding.workflow_id,
                        current_revision=current_revision,
                        updated_at=now,
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=binding.workflow_id,
                            node_id=binding.target_node_id,
                            event_type="binding_created",
                            created_at=now,
                            payload={
                                "binding_id": binding.binding_id,
                                "binding_kind": binding.binding_kind,
                                "revision": current_revision + 1,
                            },
                        ),
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _conflict_error("canvas_binding_conflict") from error
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return self.get_workflow(binding.workflow_id)

    def remove_binding(
        self,
        workflow_id: str,
        binding_id: str,
        *,
        expected_revision: int,
    ) -> AgentCanvasWorkflowV2:
        """Delete one binding without deleting either source."""

        now = _utc_now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    current_revision = _require_workflow_revision(
                        connection, workflow_id, expected_revision
                    )
                    existing = (
                        connection.execute(
                            select(AgentCanvasBindingRow).where(
                                AgentCanvasBindingRow.workflow_id == workflow_id,
                                AgentCanvasBindingRow.binding_id == binding_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is None:
                        raise _binding_not_found_error()
                    binding = _binding_from_row(existing)
                    deleted = connection.execute(
                        delete(AgentCanvasBindingRow).where(
                            AgentCanvasBindingRow.workflow_id == workflow_id,
                            AgentCanvasBindingRow.binding_id == binding_id,
                        )
                    )
                    if deleted.rowcount != 1:
                        raise _binding_not_found_error()
                    _reconcile_editing_manifest_for_binding(
                        connection,
                        binding,
                        updated_at=now,
                    )
                    _advance_workflow_revision(
                        connection,
                        workflow_id=workflow_id,
                        current_revision=current_revision,
                        updated_at=now,
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            event_type="binding_removed",
                            created_at=now,
                            payload={
                                "binding_id": binding_id,
                                "revision": current_revision + 1,
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
            raise _unavailable_error() from error
        return self.get_workflow(workflow_id)


class AgentCanvasDocumentRepository:
    """Own typed Text, Script, and Editing document records."""

    def __init__(self, database: V2Database) -> None:
        self._database = database

    def put(
        self,
        *,
        workflow_id: str,
        node_id: str,
        document_kind: str,
        content: dict[str, JsonValue],
        content_hash: str,
        node_revision: int,
    ) -> AgentCanvasDocumentRecordV2:
        now = _utc_now()
        try:
            with self._database.engine.begin() as connection:
                existing = connection.execute(
                    select(AgentCanvasDocumentRow.node_id).where(
                        AgentCanvasDocumentRow.node_id == node_id
                    )
                ).scalar_one_or_none()
                values = {
                    "workflow_id": workflow_id,
                    "document_kind": document_kind,
                    "content_json": _json_dump(content),
                    "content_hash": content_hash,
                    "node_revision": node_revision,
                    "updated_at": now,
                }
                if existing is None:
                    connection.execute(
                        insert(AgentCanvasDocumentRow).values(
                            node_id=node_id,
                            created_at=now,
                            **values,
                        )
                    )
                else:
                    connection.execute(
                        update(AgentCanvasDocumentRow)
                        .where(AgentCanvasDocumentRow.node_id == node_id)
                        .values(**values)
                    )
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return self.get(node_id)

    def get(self, node_id: str) -> AgentCanvasDocumentRecordV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasDocumentRow).where(
                            AgentCanvasDocumentRow.node_id == node_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        if row is None:
            raise V2PersistenceError(
                "canvas_document_not_found",
                "Canvas document was not found.",
                stage="agent_canvas_document_repository",
            )
        return AgentCanvasDocumentRecordV2(
            workflow_id=str(row["workflow_id"]),
            node_id=str(row["node_id"]),
            document_kind=cast(str, row["document_kind"]),
            content=cast(dict[str, JsonValue], json.loads(str(row["content_json"]))),
            content_hash=str(row["content_hash"]),
            node_revision=int(row["node_revision"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def put_prompt_context_snapshot(
        self,
        *,
        workflow_id: str,
        target_node_id: str,
        inputs: tuple[ResolvedTextInputSnapshotV2, ...],
    ) -> AgentCanvasPromptContextSnapshotV2:
        snapshot_id = f"snapshot_{uuid4().hex}"
        now = _utc_now()
        try:
            with self._database.engine.begin() as connection:
                _require_node(connection, workflow_id, target_node_id)
                connection.execute(
                    insert(AgentCanvasPromptContextSnapshotRow).values(
                        snapshot_id=snapshot_id,
                        workflow_id=workflow_id,
                        target_node_id=target_node_id,
                        inputs_json=_json_dump([item.model_dump(mode="json") for item in inputs]),
                        created_at=now,
                    )
                )
                connection.execute(
                    update(AgentCanvasNodeRow)
                    .where(
                        AgentCanvasNodeRow.workflow_id == workflow_id,
                        AgentCanvasNodeRow.node_id == target_node_id,
                    )
                    .values(prompt_context_snapshot_id=snapshot_id)
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return AgentCanvasPromptContextSnapshotV2(
            snapshot_id=snapshot_id,
            workflow_id=workflow_id,
            target_node_id=target_node_id,
            inputs=inputs,
            created_at=now,
        )

    def get_prompt_context_snapshot(self, snapshot_id: str) -> AgentCanvasPromptContextSnapshotV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasPromptContextSnapshotRow).where(
                            AgentCanvasPromptContextSnapshotRow.snapshot_id == snapshot_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        if row is None:
            raise V2PersistenceError(
                "prompt_context_snapshot_not_found",
                "Prompt context snapshot was not found.",
                stage="agent_canvas_document_repository",
            )
        raw_inputs = cast(list[dict[str, JsonValue]], json.loads(str(row["inputs_json"])))
        return AgentCanvasPromptContextSnapshotV2(
            snapshot_id=str(row["snapshot_id"]),
            workflow_id=str(row["workflow_id"]),
            target_node_id=str(row["target_node_id"]),
            inputs=tuple(ResolvedTextInputSnapshotV2.model_validate(item) for item in raw_inputs),
            created_at=str(row["created_at"]),
        )


def _load_idempotency(
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
        raise _idempotency_conflict_error()
    return str(row["response_json"])


def _store_idempotency(
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
        raise _workflow_not_found_error()
    current = int(revision)
    if current != expected_revision:
        raise V2PersistenceError(
            "workflow_revision_conflict",
            "Workflow revision does not match the current revision.",
            stage="agent_canvas_workflow_repository",
        )
    return current


def _advance_workflow_revision(
    connection: Connection,
    *,
    workflow_id: str,
    current_revision: int,
    updated_at: str,
) -> None:
    connection.execute(
        update(AgentCanvasWorkflowRow)
        .where(
            AgentCanvasWorkflowRow.workflow_id == workflow_id,
            AgentCanvasWorkflowRow.revision == current_revision,
        )
        .values(revision=current_revision + 1, updated_at=updated_at)
    )


def _require_node(connection: Connection, workflow_id: str, node_id: str) -> None:
    exists = connection.execute(
        select(AgentCanvasNodeRow.node_id).where(
            AgentCanvasNodeRow.workflow_id == workflow_id,
            AgentCanvasNodeRow.node_id == node_id,
        )
    ).scalar_one_or_none()
    if exists is None:
        raise _node_not_found_error()


def _reconcile_editing_manifest_for_binding(
    connection: Connection,
    binding: CanvasBindingV2,
    *,
    updated_at: str,
) -> None:
    target = (
        connection.execute(
            select(AgentCanvasNodeRow).where(
                AgentCanvasNodeRow.workflow_id == binding.workflow_id,
                AgentCanvasNodeRow.node_id == binding.target_node_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if target is None or str(target["node_type"]) != "editing":
        return
    bindings = (
        connection.execute(
            select(AgentCanvasBindingRow)
            .where(
                AgentCanvasBindingRow.workflow_id == binding.workflow_id,
                AgentCanvasBindingRow.target_node_id == binding.target_node_id,
            )
            .order_by(
                AgentCanvasBindingRow.display_order.asc(),
                AgentCanvasBindingRow.created_at.asc(),
                AgentCanvasBindingRow.binding_id.asc(),
            )
        )
        .mappings()
        .all()
    )
    video_ids = tuple(
        str(row["binding_id"]) for row in bindings if str(row["binding_kind"]) == "video_reference"
    )
    audio_ids = tuple(
        str(row["binding_id"]) for row in bindings if str(row["binding_kind"]) == "audio_reference"
    )
    content = EditingNodeContentV2.model_validate_json(str(target["structured_content_json"]))
    manifest = content.manifest.model_copy(
        update={
            "ordered_video_binding_ids": video_ids,
            "bgm_audio_binding_id": audio_ids[0] if audio_ids else None,
            "manifest_revision": content.manifest.manifest_revision + 1,
        }
    )
    connection.execute(
        update(AgentCanvasNodeRow)
        .where(
            AgentCanvasNodeRow.workflow_id == binding.workflow_id,
            AgentCanvasNodeRow.node_id == binding.target_node_id,
        )
        .values(
            structured_content_json=_json_dump(
                content.model_copy(update={"manifest": manifest, "dirty": True}).model_dump(
                    mode="json"
                )
            ),
            revision=int(target["revision"]) + 1,
            updated_at=updated_at,
        )
    )


def _node_values(node: CanvasNodeV2) -> dict[str, object]:
    return {
        "node_id": node.node_id,
        "workflow_id": node.workflow_id,
        "node_type": node.node_type,
        "semantic_role": node.semantic_role,
        "role_contract_version": node.role_contract_version,
        "title": node.title,
        "status": node.status,
        "summary_prompt": node.summary_prompt,
        "generation_prompt": node.generation_prompt,
        "structured_content_json": _json_dump(node.structured_content),
        "model_id": node.model_id,
        "parameters_json": _json_dump(node.parameters),
        "prompt_context_snapshot_id": node.prompt_context_snapshot_id,
        "output_asset_id": node.output_asset_id,
        "video_skill_run_id": node.video_skill_run_id,
        "position_x": node.position.x,
        "position_y": node.position.y,
        "revision": node.revision,
        "error_json": node.error.model_dump_json() if node.error is not None else None,
        "created_at": node.created_at.isoformat(),
        "updated_at": node.updated_at.isoformat(),
    }


def _node_from_row(row: RowMapping) -> CanvasNodeV2:
    error_json = row["error_json"]
    return CanvasNodeV2(
        node_id=str(row["node_id"]),
        workflow_id=str(row["workflow_id"]),
        node_type=cast(str, row["node_type"]),
        semantic_role=str(row["semantic_role"]),
        role_contract_version=cast(str, row["role_contract_version"]),
        title=str(row["title"]),
        status=cast(str, row["status"]),
        summary_prompt=cast(str | None, row["summary_prompt"]),
        generation_prompt=cast(str | None, row["generation_prompt"]),
        structured_content=cast(
            dict[str, JsonValue], json.loads(str(row["structured_content_json"]))
        ),
        model_id=cast(str | None, row["model_id"]),
        parameters=cast(dict[str, JsonValue], json.loads(str(row["parameters_json"]))),
        prompt_context_snapshot_id=cast(str | None, row["prompt_context_snapshot_id"]),
        output_asset_id=cast(str | None, row["output_asset_id"]),
        video_skill_run_id=cast(str | None, row["video_skill_run_id"]),
        position=CanvasPositionV2(
            x=float(row["position_x"]),
            y=float(row["position_y"]),
        ),
        revision=int(row["revision"]),
        error=(
            CanvasNodeErrorV2.model_validate_json(str(error_json))
            if error_json is not None
            else None
        ),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _binding_values(binding: CanvasBindingV2) -> dict[str, object]:
    return {
        "binding_id": binding.binding_id,
        "workflow_id": binding.workflow_id,
        "source_kind": binding.source.kind,
        "source_node_id": (
            binding.source.node_id
            if isinstance(binding.source, CanvasBindingSourceNodeV2)
            else None
        ),
        "source_asset_id": (
            binding.source.asset_id
            if isinstance(binding.source, CanvasBindingSourceImageAssetV2)
            else None
        ),
        "target_node_id": binding.target_node_id,
        "binding_kind": binding.binding_kind,
        "required": binding.required,
        "display_order": binding.display_order,
        "created_at": binding.created_at.isoformat(),
    }


def _binding_from_row(row: RowMapping) -> CanvasBindingV2:
    source = (
        CanvasBindingSourceNodeV2(node_id=str(row["source_node_id"]))
        if row["source_kind"] == "node"
        else CanvasBindingSourceImageAssetV2(asset_id=str(row["source_asset_id"]))
    )
    return CanvasBindingV2(
        binding_id=str(row["binding_id"]),
        workflow_id=str(row["workflow_id"]),
        source=source,
        target_node_id=str(row["target_node_id"]),
        binding_kind=cast(str, row["binding_kind"]),
        required=bool(row["required"]),
        display_order=int(row["display_order"]),
        created_at=str(row["created_at"]),
    )


def _json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unavailable_error() -> V2PersistenceError:
    return V2PersistenceError(
        "agent_canvas_persistence_unavailable",
        "Agent Canvas persistence is unavailable.",
        stage="agent_canvas_repository",
    )


def _workflow_not_found_error() -> V2PersistenceError:
    return V2PersistenceError(
        "workflow_not_found",
        "Workflow was not found.",
        stage="agent_canvas_workflow_repository",
    )


def _node_not_found_error() -> V2PersistenceError:
    return V2PersistenceError(
        "node_not_found",
        "Canvas node was not found.",
        stage="agent_canvas_workflow_repository",
    )


def _binding_not_found_error() -> V2PersistenceError:
    return V2PersistenceError(
        "binding_not_found",
        "Canvas binding was not found.",
        stage="agent_canvas_workflow_repository",
    )


def _invalid_binding_batch_error() -> V2PersistenceError:
    return V2PersistenceError(
        "binding_batch_invalid",
        "Copied bindings must target the new node in the same workflow.",
        stage="agent_canvas_workflow_repository",
    )


def _invalid_idempotency_error() -> V2PersistenceError:
    return V2PersistenceError(
        "idempotency_key_invalid",
        "Idempotency key is invalid.",
        stage="agent_canvas_workflow_repository",
    )


def _idempotency_conflict_error() -> V2PersistenceError:
    return V2PersistenceError(
        "idempotency_conflict",
        "Idempotency key was reused with different input.",
        stage="agent_canvas_workflow_repository",
    )


def _conflict_error(code: str) -> V2PersistenceError:
    return V2PersistenceError(
        code,
        "Agent Canvas persistence conflict.",
        stage="agent_canvas_workflow_repository",
    )
