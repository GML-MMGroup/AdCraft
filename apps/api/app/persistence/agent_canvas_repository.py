"""Transactional SQLite repositories for Agent Canvas V1 authoring."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import cast
from uuid import uuid4

from pydantic import JsonValue
from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.agent_canvas_prompt_preparation_dispatch_repository import (
    AgentCanvasPromptPreparationDispatchRepository,
    _parse_json_object,
    normalize_queued_node,
)
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasBindingRow,
    AgentCanvasConversationRow,
    AgentCanvasCreativeMemoryRow,
    AgentCanvasDocumentRow,
    AgentCanvasIdempotencyRow,
    AgentCanvasNodeRow,
    AgentCanvasPromptPreparationOutboxRow,
    AgentCanvasPromptContextSnapshotRow,
    AgentCanvasVariationDraftRow,
    AgentCanvasWorkflowRow,
)
from app.persistence.project_repository import ProjectRepository
from app.persistence.provider_model_repository import ProviderModelRepository
from app.schemas.agent_canvas import (
    AgentCanvasDocumentRecordV2,
    AgentCanvasPromptContextSnapshotV2,
    AgentCanvasWorkflowV2,
    CanvasBindingSourceImageAssetV2,
    CanvasBindingSourceNodeV2,
    CanvasBindingMutationResponseV2,
    CanvasBindingV2,
    CanvasConnectedNodeCreateResponseV2,
    CanvasNodeErrorV2,
    CanvasNodeV2,
    CanvasPositionV2,
    CanvasLayoutPatchResponseV2,
    CanvasLayoutPositionV2,
    CanvasModelSummaryV2,
    CanvasVariationDraftV2,
    ResolvedTextInputSnapshotV2,
)
from app.schemas.agent_canvas_video_parameters import CanvasParameterProvenanceV2
from app.schemas.agent_canvas_prompt_preparation import NodePromptPreparationV1
from app.schemas.agent_canvas_prompt_assertion import safe_prompt_assertion_metadata
from app.schemas.agent_canvas_editing import (
    EditingBgmEntryV2,
    EditingNodeContentV2,
    EditingVideoEntryV2,
)
from app.schemas.v2_persistence import V2EventInsert
from app.schemas.workflow_v2_projects import ProjectCreate
from app.services.agent_canvas_requirements import (
    update_requirement_compatibility_projection_in_transaction,
)


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
        self._requirements = AgentCanvasRequirementRepository(database)
        self._prompt_dispatch = AgentCanvasPromptPreparationDispatchRepository(database, events)

    @property
    def database(self) -> V2Database:
        return self._database

    def exists(self, workflow_id: str) -> bool:
        """Return whether SQLite owns the workflow without loading its graph."""

        try:
            with self._database.engine.connect() as connection:
                workflow = connection.execute(
                    select(AgentCanvasWorkflowRow.workflow_id)
                    .where(AgentCanvasWorkflowRow.workflow_id == workflow_id)
                    .limit(1)
                ).scalar_one_or_none()
        except SQLAlchemyError as exc:
            raise _unavailable_error() from exc
        return workflow is not None

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
                            layout_revision=1,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    self._requirements.initialize_in_transaction(
                        connection,
                        workflow_id=workflow_id,
                        created_at=now,
                    )
                    conversation_id = f"conversation_{workflow_id}"
                    connection.execute(
                        insert(AgentCanvasConversationRow).values(
                            conversation_id=conversation_id,
                            workflow_id=workflow_id,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    connection.execute(
                        insert(AgentCanvasCreativeMemoryRow).values(
                            workflow_id=workflow_id,
                            creative_goal="",
                            target_audience="",
                            duration_format="",
                            approved_style_summary="",
                            approved_node_ids_json="{}",
                            open_questions_json="[]",
                            deferred_topics_json="[]",
                            rejection_notes_json="[]",
                            conversation_summary="",
                            summary_through_sequence_no=0,
                            memory_revision=0,
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
                            AgentCanvasWorkflowRow.layout_revision,
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
                            AgentCanvasBindingRow.order_index.asc(),
                            AgentCanvasBindingRow.binding_id.asc(),
                        )
                    )
                    .mappings()
                    .all()
                )
                variation_rows = (
                    connection.execute(
                        select(AgentCanvasVariationDraftRow).where(
                            AgentCanvasVariationDraftRow.workflow_id == workflow_id
                        )
                    )
                    .mappings()
                    .all()
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        model_summaries = _load_model_summaries(
            self._database,
            node_rows,
        )
        return AgentCanvasWorkflowV2(
            workflow_id=str(workflow["workflow_id"]),
            project_id=str(workflow["project_id"]),
            workflow_schema_version=int(workflow["workflow_schema_version"]),
            canvas_model=cast(str, workflow["canvas_model"]),
            revision=int(workflow["revision"]),
            layout_revision=int(workflow["layout_revision"]),
            nodes=tuple(
                _node_from_row(
                    row,
                    variation=next(
                        (
                            item
                            for item in variation_rows
                            if str(item["source_node_id"]) == str(row["node_id"])
                        ),
                        None,
                    ),
                    model_summary=model_summaries.get(str(row["model_ref"])),
                )
                for row in node_rows
            ),
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
                variation = (
                    connection.execute(
                        select(AgentCanvasVariationDraftRow).where(
                            AgentCanvasVariationDraftRow.workflow_id == workflow_id,
                            AgentCanvasVariationDraftRow.source_node_id == node_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        if row is None:
            raise _node_not_found_error()
        model_summary = _load_model_summaries(self._database, (row,)).get(str(row["model_ref"]))
        return _node_from_row(row, variation=variation, model_summary=model_summary)

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

        node = normalize_queued_node(node)
        now = node.updated_at.isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    current_revision = _require_workflow_revision(
                        connection, node.workflow_id, expected_revision
                    )
                    connection.execute(insert(AgentCanvasNodeRow).values(**_node_values(node)))
                    self._prompt_dispatch.ensure_for_node_in_transaction(connection, node, now=node.updated_at)
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
                                "creative_role": node.creative_role,
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

    def update_layout(
        self,
        workflow_id: str,
        *,
        positions: dict[str, tuple[float, float]],
        expected_layout_revision: int,
    ) -> CanvasLayoutPatchResponseV2:
        """Atomically update positions without advancing semantic authoring."""

        if not positions or len(positions) > 200:
            raise V2PersistenceError(
                "layout_position_invalid",
                "Layout updates require between one and 200 nodes.",
                stage="agent_canvas_workflow_repository",
            )
        now = _utc_now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    workflow = (
                        connection.execute(
                            select(
                                AgentCanvasWorkflowRow.revision,
                                AgentCanvasWorkflowRow.layout_revision,
                            ).where(AgentCanvasWorkflowRow.workflow_id == workflow_id)
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if workflow is None:
                        raise _workflow_not_found_error()
                    current_layout_revision = int(workflow["layout_revision"])
                    if current_layout_revision != expected_layout_revision:
                        raise V2PersistenceError(
                            "layout_revision_conflict",
                            "Layout revision does not match the current revision.",
                            stage="agent_canvas_workflow_repository",
                        )
                    existing = set(
                        connection.execute(
                            select(AgentCanvasNodeRow.node_id).where(
                                AgentCanvasNodeRow.workflow_id == workflow_id,
                                AgentCanvasNodeRow.node_id.in_(tuple(positions)),
                            )
                        ).scalars()
                    )
                    missing = set(positions) - existing
                    if missing:
                        raise V2PersistenceError(
                            "layout_node_not_found",
                            "One or more layout nodes were not found.",
                            stage="agent_canvas_workflow_repository",
                        )
                    for node_id, (x, y) in positions.items():
                        connection.execute(
                            update(AgentCanvasNodeRow)
                            .where(
                                AgentCanvasNodeRow.workflow_id == workflow_id,
                                AgentCanvasNodeRow.node_id == node_id,
                            )
                            .values(position_x=x, position_y=y)
                        )
                    next_layout_revision = current_layout_revision + 1
                    connection.execute(
                        update(AgentCanvasWorkflowRow)
                        .where(
                            AgentCanvasWorkflowRow.workflow_id == workflow_id,
                            AgentCanvasWorkflowRow.layout_revision == current_layout_revision,
                        )
                        .values(
                            layout_revision=next_layout_revision,
                            updated_at=now,
                        )
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            event_type="canvas_layout_updated",
                            created_at=now,
                            payload={
                                "layout_revision": next_layout_revision,
                                "node_ids": list(positions),
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
        return CanvasLayoutPatchResponseV2(
            workflow_id=workflow_id,
            revision=int(workflow["revision"]),
            layout_revision=next_layout_revision,
            positions=tuple(
                CanvasLayoutPositionV2(node_id=node_id, x=x, y=y)
                for node_id, (x, y) in positions.items()
            ),
        )

    def add_node_with_bindings(
        self,
        node: CanvasNodeV2,
        bindings: tuple[CanvasBindingV2, ...],
        *,
        expected_revision: int,
    ) -> AgentCanvasWorkflowV2:
        """Insert one node and its copied inputs as one authoring revision."""

        node = normalize_queued_node(node, bindings=bindings)
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
                    self._prompt_dispatch.ensure_for_node_in_transaction(
                        connection,
                        node,
                        bindings=bindings,
                        now=node.updated_at,
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
                                "creative_role": node.creative_role,
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

    def upsert_guided_editing(
        self,
        node: CanvasNodeV2,
        bindings: tuple[CanvasBindingV2, ...],
        *,
        expected_revision: int,
    ) -> AgentCanvasWorkflowV2:
        """Atomically persist one guided Editing manifest and its explicit inputs."""

        if node.node_type != "editing" or node.creative_role != "editing":
            raise _invalid_binding_batch_error()
        now = node.updated_at.isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    current_revision = _require_workflow_revision(
                        connection,
                        node.workflow_id,
                        expected_revision,
                    )
                    existing_node = connection.execute(
                        select(AgentCanvasNodeRow.node_id).where(
                            AgentCanvasNodeRow.workflow_id == node.workflow_id,
                            AgentCanvasNodeRow.node_id == node.node_id,
                        )
                    ).scalar_one_or_none()
                    if existing_node is None:
                        connection.execute(insert(AgentCanvasNodeRow).values(**_node_values(node)))
                    else:
                        node_values = _node_values(node)
                        node_values.pop("node_id")
                        node_values.pop("workflow_id")
                        connection.execute(
                            update(AgentCanvasNodeRow)
                            .where(
                                AgentCanvasNodeRow.workflow_id == node.workflow_id,
                                AgentCanvasNodeRow.node_id == node.node_id,
                            )
                            .values(**node_values)
                        )
                    for binding in bindings:
                        if (
                            binding.workflow_id != node.workflow_id
                            or binding.target_node_id != node.node_id
                            or not isinstance(binding.source, CanvasBindingSourceNodeV2)
                        ):
                            raise _invalid_binding_batch_error()
                        _require_node(
                            connection,
                            binding.workflow_id,
                            binding.source.node_id,
                        )
                        existing_binding = connection.execute(
                            select(AgentCanvasBindingRow.binding_id).where(
                                AgentCanvasBindingRow.workflow_id == binding.workflow_id,
                                AgentCanvasBindingRow.binding_id == binding.binding_id,
                            )
                        ).scalar_one_or_none()
                        if existing_binding is None:
                            connection.execute(
                                insert(AgentCanvasBindingRow).values(**_binding_values(binding))
                            )
                        else:
                            binding_values = _binding_values(binding)
                            binding_values.pop("binding_id")
                            binding_values.pop("workflow_id")
                            connection.execute(
                                update(AgentCanvasBindingRow)
                                .where(
                                    AgentCanvasBindingRow.workflow_id == binding.workflow_id,
                                    AgentCanvasBindingRow.binding_id == binding.binding_id,
                                )
                                .values(**binding_values)
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
                            event_type="guided_editing_updated",
                            created_at=now,
                            payload={
                                "binding_ids": [binding.binding_id for binding in bindings],
                                "manifest_revision": node.structured_content.get(
                                    "manifest", {}
                                ).get("manifest_revision"),
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
        return self.get_workflow(node.workflow_id)

    def update_node(
        self,
        node: CanvasNodeV2,
        *,
        expected_revision: int,
    ) -> AgentCanvasWorkflowV2:
        """Replace one node record and advance authoring once."""

        bindings_for_node: tuple[CanvasBindingV2, ...] = ()
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
                    current_row = (
                        connection.execute(
                            select(AgentCanvasNodeRow).where(
                                AgentCanvasNodeRow.workflow_id == node.workflow_id,
                                AgentCanvasNodeRow.node_id == node.node_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if current_row is None:
                        raise _node_not_found_error()
                    current_node = _node_from_row(current_row)
                    requested_manual_prompt = (
                        node.prompt_preparation.status == "ready"
                        and not _has_managed_prompt_preparation(node)
                    )
                    current_preparation_status = current_node.prompt_preparation.status
                    current_preparation_managed = _has_managed_prompt_preparation(current_node)
                    if (
                        node.execution_mode == "generative"
                        and _prompt_input_changed(current_node, node)
                        and not requested_manual_prompt
                        and (
                            current_preparation_status
                            in {"queued", "working", "failed", "superseded"}
                            or (
                                current_preparation_status == "ready"
                                and current_preparation_managed
                            )
                        )
                    ):
                        # A changed prompt/input snapshot cannot reuse a
                        # completed operation identity.  Re-enter the normal
                        # queued authority and derive one successor below.
                        node = node.model_copy(
                            update={
                                "status": "draft",
                                "output_asset_id": None,
                                "prompt_context_snapshot_id": None,
                                "metadata": {
                                    key: value
                                    for key, value in node.metadata.items()
                                    if not key.startswith("prompt_")
                                    and key != "prepared_reference_snapshots"
                                },
                                "prompt_preparation": _queued_preparation_for_revision(
                                    node.prompt_preparation,
                                    node.updated_at,
                                ),
                            }
                        )
                    if node.prompt_preparation.status == "queued":
                        bindings_for_node = _load_target_bindings(
                            connection,
                            node.workflow_id,
                            node.node_id,
                        )
                        node = normalize_queued_node(node, bindings=bindings_for_node)
                        values = _node_values(node)
                        values.pop("node_id")
                        values.pop("workflow_id")
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
                    if node.prompt_preparation.status == "queued":
                        self._prompt_dispatch.supersede_and_enqueue_in_transaction(
                            connection,
                            node=node,
                            bindings=bindings_for_node,
                            reason="node_prompt_input_changed",
                            now=node.updated_at,
                        )
                    else:
                        self._prompt_dispatch.ensure_for_node_in_transaction(
                            connection,
                            node,
                            bindings=bindings_for_node,
                            now=node.updated_at,
                        )
                    _invalidate_prompt_preparations_for_source(
                        connection,
                        events=self._events,
                        prompt_dispatch=self._prompt_dispatch,
                        workflow_id=node.workflow_id,
                        source_node_id=node.node_id,
                        updated_at=now,
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

    def update_node_prompt_preparation(
        self,
        node: CanvasNodeV2,
        *,
        expected_node_revision: int,
        expected_workflow_revision: int,
    ) -> CanvasNodeV2:
        """Compare-and-swap one prompt operation while tolerating exact replay."""

        if node.revision != expected_node_revision + 1:
            raise _prompt_preparation_conflict()
        now = node.updated_at.isoformat()
        values = _node_values(node)
        values.pop("node_id")
        values.pop("workflow_id")
        replayed = False
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    row = (
                        connection.execute(
                            select(AgentCanvasNodeRow).where(
                                AgentCanvasNodeRow.workflow_id == node.workflow_id,
                                AgentCanvasNodeRow.node_id == node.node_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None:
                        raise _node_not_found_error()
                    current = _node_from_row(row)
                    if current.revision != expected_node_revision:
                        if _prompt_preparation_replays(current, node):
                            replayed = True
                            connection.commit()
                        else:
                            raise _prompt_preparation_conflict()
                    else:
                        current_workflow_revision = _require_workflow_revision_at_least(
                            connection,
                            node.workflow_id,
                            expected_workflow_revision,
                        )
                        updated = connection.execute(
                            update(AgentCanvasNodeRow)
                            .where(
                                AgentCanvasNodeRow.workflow_id == node.workflow_id,
                                AgentCanvasNodeRow.node_id == node.node_id,
                                AgentCanvasNodeRow.revision == expected_node_revision,
                            )
                            .values(**values)
                        )
                        if updated.rowcount != 1:
                            raise _prompt_preparation_conflict()
                        if node.prompt_preparation.status == "queued":
                            # Legacy callers may transition a queued Draft
                            # without having persisted its owner yet.  Keep
                            # the Node projection and dispatch intent in this
                            # same CAS transaction.
                            self._prompt_dispatch.ensure_for_node_in_transaction(
                                connection,
                                node,
                                now=node.updated_at,
                            )
                        elif node.prompt_preparation.status in {
                            "ready",
                            "failed",
                            "superseded",
                        }:
                            self._prompt_dispatch.reconcile_node_terminal_in_transaction(
                                connection,
                                node=node,
                                now=node.updated_at,
                            )
                        if node.prompt_preparation.status in {"ready", "failed", "superseded"}:
                            _invalidate_prompt_preparations_for_source(
                                connection,
                                events=self._events,
                                prompt_dispatch=self._prompt_dispatch,
                                workflow_id=node.workflow_id,
                                source_node_id=node.node_id,
                                updated_at=now,
                            )
                        _advance_workflow_revision(
                            connection,
                            workflow_id=node.workflow_id,
                            current_revision=current_workflow_revision,
                            updated_at=now,
                        )
                        event_type = {
                            "working": "node_prompt_preparation_started",
                            "ready": "node_prompt_preparation_ready",
                            "failed": "node_prompt_preparation_failed",
                            "queued": "node_prompt_preparation_queued",
                            "superseded": "node_prompt_preparation_superseded",
                        }[node.prompt_preparation.status]
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=node.workflow_id,
                                node_id=node.node_id,
                                event_type=event_type,
                                created_at=now,
                                payload={
                                    "node_revision": node.revision,
                                    "workflow_revision": current_workflow_revision + 1,
                                    "creative_role": node.creative_role,
                                    "prompt_preparation_status": (node.prompt_preparation.status),
                                    "operation_id": node.prompt_preparation.operation_id,
                                    "recipe_id": node.prompt_preparation.recipe_id,
                                    "recipe_version": node.prompt_preparation.recipe_version,
                                    "recipe_digest": node.prompt_preparation.recipe_digest,
                                    "prompt_digest": node.prompt_preparation.prompt_digest,
                                    "binding_digest": node.prompt_preparation.binding_digest,
                                    **(
                                        safe_prompt_assertion_metadata(
                                            node.prompt_preparation.assertion_evidence
                                        )
                                        if node.prompt_preparation.assertion_evidence is not None
                                        else {}
                                    ),
                                    "error_code": (
                                        node.prompt_preparation.error.code
                                        if node.prompt_preparation.error is not None
                                        else None
                                    ),
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
        restored = self.get_node(node.workflow_id, node.node_id)
        return restored if replayed else restored

    def invalidate_prompt_preparation_for_dependency_change(
        self,
        workflow_id: str,
        node_id: str,
        *,
        operation_id: str,
    ) -> CanvasNodeV2:
        """Supersede one preparation and enqueue its current successor atomically."""

        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
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
                        raise _node_not_found_error()
                    current = _node_from_row(row)
                    if current.prompt_preparation.operation_id != operation_id:
                        raise _prompt_preparation_conflict()
                    if current.prompt_preparation.status != "ready":
                        connection.commit()
                        return current
                    current_workflow_revision = int(
                        connection.execute(
                            select(AgentCanvasWorkflowRow.revision).where(
                                AgentCanvasWorkflowRow.workflow_id == workflow_id
                            )
                        ).scalar_one()
                    )
                    invalidated = _invalidate_target_prompt_preparation(
                        connection,
                        events=self._events,
                        prompt_dispatch=self._prompt_dispatch,
                        workflow_id=workflow_id,
                        target_node_id=node_id,
                        expected_operation_id=operation_id,
                        updated_at=_utc_now(),
                    )
                    if invalidated is None:
                        connection.commit()
                        return current
                    _advance_workflow_revision(
                        connection,
                        workflow_id=workflow_id,
                        current_revision=current_workflow_revision,
                        updated_at=invalidated.updated_at.isoformat(),
                    )
                    connection.commit()
                    return invalidated
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _unavailable_error() from error

    def replace_derived_video_parameters(
        self,
        workflow_id: str,
        node_id: str,
        *,
        expected_node_revision: int,
        derived_parameters: dict[str, JsonValue],
        derived_provenance: dict[str, CanvasParameterProvenanceV2],
        now: datetime,
    ) -> CanvasNodeV2:
        """Replace derived Video parameters without overwriting manual values."""

        if set(derived_parameters) != set(derived_provenance) or any(
            provenance.origin == "manual" for provenance in derived_provenance.values()
        ):
            raise V2PersistenceError(
                "node_parameter_compilation_failed",
                "Derived parameter values and provenance do not match.",
                stage="parameter_compilation",
                details={"reason": "invalid_derived_parameters"},
            )
        timestamp = now.isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
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
                        raise _node_not_found_error()
                    if int(row["revision"]) != expected_node_revision:
                        raise _parameter_authoring_changed_error()
                    current = _node_from_row(row)
                    if current.node_type != "video":
                        raise V2PersistenceError(
                            "node_parameter_compilation_failed",
                            "Derived Video parameters require a Video Node.",
                            stage="parameter_compilation",
                            details={"reason": "invalid_node_type"},
                        )
                    manual_parameters = {
                        field: value
                        for field, value in current.parameters.items()
                        if current.parameter_provenance.get(field) is not None
                        and current.parameter_provenance[field].origin == "manual"
                    }
                    manual_provenance = {
                        field: provenance
                        for field, provenance in current.parameter_provenance.items()
                        if provenance.origin == "manual" and field in manual_parameters
                    }
                    deterministic_parameters = {
                        field: value
                        for field, value in current.parameters.items()
                        if field not in current.parameter_provenance
                    }
                    parameters = {
                        **deterministic_parameters,
                        **derived_parameters,
                        **manual_parameters,
                    }
                    provenance = {**derived_provenance, **manual_provenance}
                    if (
                        parameters == current.parameters
                        and provenance == current.parameter_provenance
                    ):
                        connection.commit()
                        return current
                    updated_revision = expected_node_revision + 1
                    updated = connection.execute(
                        update(AgentCanvasNodeRow)
                        .where(
                            AgentCanvasNodeRow.workflow_id == workflow_id,
                            AgentCanvasNodeRow.node_id == node_id,
                            AgentCanvasNodeRow.revision == expected_node_revision,
                        )
                        .values(
                            parameters_json=_json_dump(parameters),
                            parameter_provenance_json=_json_dump(
                                {
                                    field: item.model_dump(mode="json")
                                    for field, item in provenance.items()
                                }
                            ),
                            revision=updated_revision,
                            updated_at=timestamp,
                        )
                    )
                    if updated.rowcount != 1:
                        raise _parameter_authoring_changed_error()
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            node_id=node_id,
                            event_type="canvas_node_updated",
                            created_at=timestamp,
                            payload={
                                "node_revision": updated_revision,
                                "updated_fields": ["parameters", "parameter_provenance"],
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
        return self.get_node(workflow_id, node_id)

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
                if str(current["status"]) == "ready" and status != "ready":
                    return _node_from_row(current)
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
                invalidate_prompt_preparations_for_source_in_transaction(
                    connection,
                    events=self._events,
                    prompt_dispatch=self._prompt_dispatch,
                    workflow_id=workflow_id,
                    source_node_id=node_id,
                    updated_at=timestamp,
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        execution_id=execution_id,
                        node_id=node_id,
                        asset_id=output_asset_id,
                        event_type="node_output_published",
                        created_at=timestamp,
                        payload={"asset_id": output_asset_id},
                    ),
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
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        execution_id=execution_id,
                        node_id=node_id,
                        asset_id=output_asset_id,
                        event_type="runtime_snapshot_updated",
                        created_at=timestamp,
                        payload={
                            "refresh": ["workflow", "runtime", "assets"],
                        },
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
                    requirement_head = self._requirements.get_current_in_transaction(
                        connection,
                        workflow_id,
                    )
                    retained_directives = []
                    requirement_changed = False
                    for directive in requirement_head.ledger.active_directives:
                        if directive.scope_kind != "node" or (
                            node_id not in directive.target_node_ids
                            and directive.source_node_id != node_id
                        ):
                            retained_directives.append(directive)
                            continue
                        requirement_changed = True
                        remaining_targets = tuple(
                            target_id
                            for target_id in directive.target_node_ids
                            if target_id != node_id
                        )
                        if remaining_targets and directive.source_node_id != node_id:
                            retained_directives.append(
                                directive.model_copy(update={"target_node_ids": remaining_targets})
                            )
                    connection.execute(
                        delete(AgentCanvasDocumentRow).where(
                            AgentCanvasDocumentRow.workflow_id == workflow_id,
                            AgentCanvasDocumentRow.node_id == node_id,
                        )
                    )
                    if requirement_changed:
                        requirement_revision = self._requirements.append_in_transaction(
                            connection,
                            workflow_id=workflow_id,
                            expected_revision_no=requirement_head.revision_no,
                            next_ledger=requirement_head.ledger.model_copy(
                                update={"active_directives": tuple(retained_directives)}
                            ),
                            source_kind="node_deletion",
                            source_node_id=node_id,
                            created_at=now,
                        )
                        update_requirement_compatibility_projection_in_transaction(
                            connection,
                            workflow_id,
                            requirement_revision.ledger,
                            now,
                        )
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=workflow_id,
                                node_id=node_id,
                                event_type="requirement_ledger_updated",
                                created_at=now,
                                payload={
                                    "revision_id": requirement_revision.revision_id,
                                    "revision_no": requirement_revision.revision_no,
                                    "digest": requirement_revision.digest,
                                    "source_kind": "node_deletion",
                                    "source_node_id": node_id,
                                    "refresh": ["requirements"],
                                },
                            ),
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
                    _normalize_target_binding_order(
                        connection,
                        workflow_id=binding.workflow_id,
                        target_node_id=binding.target_node_id,
                        prioritized_binding_id=binding.binding_id,
                        requested_order=binding.display_order,
                    )
                    _reconcile_editing_manifest_for_binding(
                        connection,
                        binding,
                        updated_at=now,
                    )
                    _invalidate_target_prompt_preparation(
                        connection,
                        events=self._events,
                        prompt_dispatch=self._prompt_dispatch,
                        workflow_id=binding.workflow_id,
                        target_node_id=binding.target_node_id,
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
                                "input_role": binding.input_role,
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
                    _normalize_target_binding_order(
                        connection,
                        workflow_id=workflow_id,
                        target_node_id=binding.target_node_id,
                    )
                    _reconcile_editing_manifest_for_binding(
                        connection,
                        binding,
                        updated_at=now,
                    )
                    _invalidate_target_prompt_preparation(
                        connection,
                        events=self._events,
                        prompt_dispatch=self._prompt_dispatch,
                        workflow_id=workflow_id,
                        target_node_id=binding.target_node_id,
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

    def add_connected_node(
        self,
        *,
        node: CanvasNodeV2,
        binding: CanvasBindingV2,
        expected_revision: int,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> CanvasConnectedNodeCreateResponseV2:
        """Persist a new Draft node and its real binding as one semantic operation."""

        operation = f"agent_canvas_connected_node:{node.workflow_id}"
        incoming_bindings = (binding,) if binding.target_node_id == node.node_id else ()
        node = normalize_queued_node(node, bindings=incoming_bindings)
        now = node.updated_at.isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    replay = _load_idempotency(
                        connection,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_fingerprint,
                    )
                    if replay is not None:
                        connection.commit()
                        return CanvasConnectedNodeCreateResponseV2.model_validate_json(replay)
                    current_revision = _require_workflow_revision(
                        connection, node.workflow_id, expected_revision
                    )
                    connection.execute(insert(AgentCanvasNodeRow).values(**_node_values(node)))
                    connection.execute(
                        insert(AgentCanvasBindingRow).values(**_binding_values(binding))
                    )
                    self._prompt_dispatch.ensure_for_node_in_transaction(
                        connection,
                        node,
                        bindings=incoming_bindings,
                        now=node.updated_at,
                    )
                    binding_order = _normalize_target_binding_order(
                        connection,
                        workflow_id=node.workflow_id,
                        target_node_id=binding.target_node_id,
                        prioritized_binding_id=binding.binding_id,
                        requested_order=binding.display_order,
                    )
                    if binding.target_node_id != node.node_id:
                        _invalidate_target_prompt_preparation(
                            connection,
                            events=self._events,
                            prompt_dispatch=self._prompt_dispatch,
                            workflow_id=binding.workflow_id,
                            target_node_id=binding.target_node_id,
                            updated_at=now,
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
                            payload={"node_type": node.node_type, "revision": current_revision + 1},
                        ),
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=node.workflow_id,
                            node_id=binding.target_node_id,
                            event_type="canvas_binding_created",
                            created_at=now,
                            payload={
                                "binding_id": binding.binding_id,
                                "input_role": binding.input_role,
                                "revision": current_revision + 1,
                            },
                        ),
                    )
                    revision_event = self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=node.workflow_id,
                            event_type="workflow_revision_created",
                            created_at=now,
                            payload={"revision": current_revision + 1},
                        ),
                    )
                    layout_revision = int(
                        connection.execute(
                            select(AgentCanvasWorkflowRow.layout_revision).where(
                                AgentCanvasWorkflowRow.workflow_id == node.workflow_id
                            )
                        ).scalar_one()
                    )
                    response = CanvasConnectedNodeCreateResponseV2(
                        workflow_id=node.workflow_id,
                        revision=current_revision + 1,
                        layout_revision=layout_revision,
                        node=node,
                        binding=binding.model_copy(update={"order": binding_order}),
                        events_cursor=revision_event.seq,
                    )
                    _store_idempotency(
                        connection,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_fingerprint,
                        response_json=response.model_dump_json(),
                        created_at=now,
                    )
                    connection.commit()
                    return response
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _conflict_error("canvas_binding_conflict") from error
        except SQLAlchemyError as error:
            raise _unavailable_error() from error

    def update_binding(
        self,
        *,
        binding: CanvasBindingV2,
        expected_revision: int,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> CanvasBindingMutationResponseV2:
        """Patch one binding and normalize its target inputs atomically."""

        operation = f"agent_canvas_binding_patch:{binding.workflow_id}"
        now = _utc_now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    replay = _load_idempotency(
                        connection,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_fingerprint,
                    )
                    if replay is not None:
                        connection.commit()
                        return CanvasBindingMutationResponseV2.model_validate_json(replay)
                    current_revision = _require_workflow_revision(
                        connection, binding.workflow_id, expected_revision
                    )
                    existing = (
                        connection.execute(
                            select(AgentCanvasBindingRow).where(
                                AgentCanvasBindingRow.workflow_id == binding.workflow_id,
                                AgentCanvasBindingRow.binding_id == binding.binding_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is None:
                        raise _binding_not_found_error()
                    updated = connection.execute(
                        update(AgentCanvasBindingRow)
                        .where(
                            AgentCanvasBindingRow.workflow_id == binding.workflow_id,
                            AgentCanvasBindingRow.binding_id == binding.binding_id,
                        )
                        .values(
                            input_role=binding.input_role,
                            required=binding.required,
                            enabled=binding.enabled,
                            label=binding.label,
                            metadata_json=_json_dump(binding.metadata),
                            updated_at=binding.updated_at.isoformat(),
                        )
                    )
                    if updated.rowcount != 1:
                        raise _binding_not_found_error()
                    binding_order = _normalize_target_binding_order(
                        connection,
                        workflow_id=binding.workflow_id,
                        target_node_id=binding.target_node_id,
                        prioritized_binding_id=binding.binding_id,
                        requested_order=binding.display_order,
                    )
                    _invalidate_target_prompt_preparation(
                        connection,
                        events=self._events,
                        prompt_dispatch=self._prompt_dispatch,
                        workflow_id=binding.workflow_id,
                        target_node_id=binding.target_node_id,
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
                            event_type="canvas_binding_updated",
                            created_at=now,
                            payload={
                                "binding_id": binding.binding_id,
                                "revision": current_revision + 1,
                            },
                        ),
                    )
                    revision_event = self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=binding.workflow_id,
                            event_type="workflow_revision_created",
                            created_at=now,
                            payload={"revision": current_revision + 1},
                        ),
                    )
                    rows = (
                        connection.execute(
                            select(AgentCanvasBindingRow)
                            .where(
                                AgentCanvasBindingRow.workflow_id == binding.workflow_id,
                                AgentCanvasBindingRow.target_node_id == binding.target_node_id,
                            )
                            .order_by(AgentCanvasBindingRow.order_index.asc())
                        )
                        .mappings()
                        .all()
                    )
                    incoming = tuple(_binding_from_row(row) for row in rows)
                    updated_binding = next(
                        item for item in incoming if item.binding_id == binding.binding_id
                    )
                    response = CanvasBindingMutationResponseV2(
                        workflow_id=binding.workflow_id,
                        revision=current_revision + 1,
                        binding=updated_binding.model_copy(update={"order": binding_order}),
                        incoming_bindings=incoming,
                        events_cursor=revision_event.seq,
                    )
                    _store_idempotency(
                        connection,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_fingerprint,
                        response_json=response.model_dump_json(),
                        created_at=now,
                    )
                    connection.commit()
                    return response
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _unavailable_error() from error


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
        turn_id: str | None = None,
        role: str | None = None,
        operation: str | None = None,
        target_asset_ids: tuple[str, ...] = (),
        binding_ids: tuple[str, ...] = (),
        creative_direction_snapshot_id: str | None = None,
        skill_refs: tuple[dict[str, str], ...] = (),
        memory_digest: str | None = None,
        upstream_summary_digest: str | None = None,
        requirement_revision_id: str | None = None,
        requirement_revision_no: int | None = None,
        requirement_digest: str | None = None,
        requirement_projection_digest: str | None = None,
        byte_estimate: int = 0,
        token_estimate: int = 0,
        content_digest: str | None = None,
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
                        turn_id=turn_id,
                        role=role,
                        operation=operation,
                        target_asset_ids_json=_json_dump(target_asset_ids),
                        binding_ids_json=_json_dump(binding_ids),
                        creative_direction_snapshot_id=creative_direction_snapshot_id,
                        skill_refs_json=_json_dump(skill_refs),
                        memory_digest=memory_digest,
                        upstream_summary_digest=upstream_summary_digest,
                        requirement_revision_id=requirement_revision_id,
                        requirement_revision_no=requirement_revision_no,
                        requirement_digest=requirement_digest,
                        requirement_projection_digest=requirement_projection_digest,
                        byte_estimate=byte_estimate,
                        token_estimate=token_estimate,
                        content_digest=content_digest,
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
            turn_id=turn_id,
            role=role,
            operation=operation,
            target_asset_ids=target_asset_ids,
            binding_ids=binding_ids,
            creative_direction_snapshot_id=creative_direction_snapshot_id,
            skill_refs=skill_refs,
            memory_digest=memory_digest,
            upstream_summary_digest=upstream_summary_digest,
            requirement_revision_id=requirement_revision_id,
            requirement_revision_no=requirement_revision_no,
            requirement_digest=requirement_digest,
            requirement_projection_digest=requirement_projection_digest,
            byte_estimate=byte_estimate,
            token_estimate=token_estimate,
            content_digest=content_digest,
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
            turn_id=cast(str | None, row["turn_id"]),
            role=cast(str | None, row["role"]),
            operation=cast(str | None, row["operation"]),
            target_asset_ids=tuple(json.loads(str(row["target_asset_ids_json"]))),
            binding_ids=tuple(json.loads(str(row["binding_ids_json"]))),
            creative_direction_snapshot_id=cast(
                str | None,
                row["creative_direction_snapshot_id"],
            ),
            skill_refs=tuple(json.loads(str(row["skill_refs_json"]))),
            memory_digest=cast(str | None, row["memory_digest"]),
            upstream_summary_digest=cast(str | None, row["upstream_summary_digest"]),
            requirement_revision_id=cast(str | None, row["requirement_revision_id"]),
            requirement_revision_no=(
                int(row["requirement_revision_no"])
                if row["requirement_revision_no"] is not None
                else None
            ),
            requirement_digest=cast(str | None, row["requirement_digest"]),
            requirement_projection_digest=cast(
                str | None,
                row["requirement_projection_digest"],
            ),
            byte_estimate=int(row["byte_estimate"]),
            token_estimate=int(row["token_estimate"]),
            content_digest=cast(str | None, row["content_digest"]),
            created_at=str(row["created_at"]),
        )

    def find_prompt_context_snapshot(
        self,
        *,
        workflow_id: str,
        target_node_id: str,
        operation: str,
    ) -> AgentCanvasPromptContextSnapshotV2 | None:
        try:
            with self._database.engine.connect() as connection:
                snapshot_id = connection.execute(
                    select(AgentCanvasPromptContextSnapshotRow.snapshot_id)
                    .where(
                        AgentCanvasPromptContextSnapshotRow.workflow_id == workflow_id,
                        AgentCanvasPromptContextSnapshotRow.target_node_id == target_node_id,
                        AgentCanvasPromptContextSnapshotRow.operation == operation,
                    )
                    .order_by(AgentCanvasPromptContextSnapshotRow.created_at.asc())
                    .limit(1)
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return self.get_prompt_context_snapshot(str(snapshot_id)) if snapshot_id else None


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


def _require_workflow_revision_at_least(
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
    if current < expected_revision:
        raise _prompt_preparation_conflict()
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
                AgentCanvasBindingRow.order_index.asc(),
                AgentCanvasBindingRow.created_at.asc(),
                AgentCanvasBindingRow.binding_id.asc(),
            )
        )
        .mappings()
        .all()
    )
    video_ids = [
        str(row["binding_id"]) for row in bindings if str(row["input_role"]) == "video_reference"
    ]
    audio_ids = [
        str(row["binding_id"]) for row in bindings if str(row["input_role"]) == "audio_reference"
    ]
    content = EditingNodeContentV2.model_validate_json(str(target["structured_content_json"]))
    video_entries = [
        entry
        for entry in content.manifest.video_entries
        if entry.binding_id is None or entry.binding_id in set(video_ids)
    ]
    selected_video_bindings = {
        entry.binding_id for entry in video_entries if entry.binding_id is not None
    }
    video_entries.extend(
        EditingVideoEntryV2(binding_id=binding_id)
        for binding_id in video_ids
        if binding_id not in selected_video_bindings
    )
    bgm = content.manifest.bgm
    if bgm is not None and bgm.binding_id is not None and bgm.binding_id not in audio_ids:
        bgm = None
    if bgm is None and audio_ids:
        bgm = EditingBgmEntryV2(binding_id=audio_ids[0])
    manifest = content.manifest.model_copy(
        update={
            "video_entries": tuple(video_entries),
            "bgm": bgm,
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
        "creative_role": node.creative_role,
        "role_contract_version": node.role_contract_version,
        "title": node.title,
        "status": node.status,
        "execution_mode": node.execution_mode,
        "summary_prompt": node.summary_prompt,
        "generation_prompt": node.generation_prompt,
        "structured_content_json": _json_dump(node.structured_content),
        "model_selection_mode": node.model_selection_mode,
        "model_ref": node.model_ref,
        "parameters_json": _json_dump(node.parameters),
        "metadata_json": _json_dump(node.metadata),
        "parameter_provenance_json": _json_dump(
            {
                field: provenance.model_dump(mode="json")
                for field, provenance in node.parameter_provenance.items()
            }
        ),
        "prompt_context_snapshot_id": node.prompt_context_snapshot_id,
        "output_asset_id": node.output_asset_id,
        "position_x": node.position.x,
        "position_y": node.position.y,
        "revision": node.revision,
        "error_json": node.error.model_dump_json() if node.error is not None else None,
        "prompt_preparation_json": node.prompt_preparation.model_dump_json(),
        "created_at": node.created_at.isoformat(),
        "updated_at": node.updated_at.isoformat(),
    }


def _prompt_input_changed(current: CanvasNodeV2, requested: CanvasNodeV2) -> bool:
    """Detect a new preparation input snapshot without comparing volatile fields."""

    return any(
        getattr(current, field) != getattr(requested, field)
        for field in (
            "node_type",
            "creative_role",
            "summary_prompt",
            "generation_prompt",
            "structured_content",
            "model_selection_mode",
            "model_ref",
            "parameters",
        )
    )


def _has_managed_prompt_preparation(node: CanvasNodeV2) -> bool:
    """Return whether a node's prompt is owned by the preparation authority."""

    preparation = node.prompt_preparation
    return bool(
        preparation.operation_id
        or preparation.context_snapshot_id
        or preparation.recipe_id
        or preparation.recipe_version
        or preparation.recipe_digest
        or preparation.requirement_revision_id
        or preparation.binding_digest
        or preparation.style_projection_digest
        or preparation.brief_digest
        or preparation.assertion_evidence
        or node.metadata.get("prompt_recipe_id")
    )


def _queued_preparation_for_revision(
    preparation: NodePromptPreparationV1,
    updated_at: datetime,
) -> NodePromptPreparationV1:
    return NodePromptPreparationV1(
        status="queued",
        operation_id=None,
        attempt_no=0,
        context_snapshot_id=None,
        occurrence_id=preparation.occurrence_id,
        character_phase=preparation.character_phase,
        role_variant=preparation.role_variant,
        prompt_digest=None,
        error=None,
        updated_at=updated_at,
    )


def _invalidate_target_prompt_preparation(
    connection: Connection,
    *,
    events: EventRepository,
    prompt_dispatch: AgentCanvasPromptPreparationDispatchRepository | None = None,
    workflow_id: str,
    target_node_id: str,
    updated_at: str,
    expected_operation_id: str | None = None,
) -> CanvasNodeV2 | None:
    row = (
        connection.execute(
            select(AgentCanvasNodeRow).where(
                AgentCanvasNodeRow.workflow_id == workflow_id,
                AgentCanvasNodeRow.node_id == target_node_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _node_not_found_error()
    node = _node_from_row(row)
    if (
        expected_operation_id is not None
        and node.prompt_preparation.operation_id != expected_operation_id
    ):
        raise _prompt_preparation_conflict()
    if node.status not in {"draft", "failed", "ready", "working"}:
        return None
    if node.status == "ready" and not _has_managed_prompt_preparation(node):
        # Legacy/manual Ready content has no immutable preparation owner to
        # supersede.  Do not turn a harmless first Binding into a queued
        # re-preparation or clear its existing context projection.
        return None
    if node.prompt_preparation.status == "ready" and not _has_managed_prompt_preparation(node):
        # A manually supplied generation prompt is already authoritative.  Its
        # provider references are compiled from the execution binding snapshot,
        # so a Binding/source publication must not turn this legacy-compatible
        # Draft into an ownerless queued preparation.
        return None
    if node.prompt_preparation.status == "not_applicable":
        return None
    bindings = _load_target_bindings(connection, workflow_id, target_node_id)
    frozen_context: dict[str, object] = {}
    if prompt_dispatch is not None and node.prompt_preparation.operation_id:
        dispatch_row = (
            connection.execute(
                select(AgentCanvasPromptPreparationOutboxRow.context_json).where(
                    AgentCanvasPromptPreparationOutboxRow.workflow_id == workflow_id,
                    AgentCanvasPromptPreparationOutboxRow.node_id == target_node_id,
                    AgentCanvasPromptPreparationOutboxRow.operation_id
                    == node.prompt_preparation.operation_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if dispatch_row is not None:
            frozen_context = _parse_json_object(dispatch_row["context_json"])
    # Invalidation creates a new immutable operation identity.  Keep the
    # occurrence and role metadata, but discard all evidence/digests derived
    # from the previous input snapshot.
    prepared_projection = (
        isinstance(node.generation_prompt, str)
        and isinstance(node.metadata.get("prompt_digest"), str)
        and node.metadata.get("prompt_digest") == sha256(
            node.generation_prompt.encode("utf-8")
        ).hexdigest()
    )
    queued = NodePromptPreparationV1(
        status="queued",
        operation_id=None,
        attempt_no=0,
        context_snapshot_id=None,
        occurrence_id=node.prompt_preparation.occurrence_id,
        character_phase=node.prompt_preparation.character_phase,
        role_variant=node.prompt_preparation.role_variant,
        prompt_digest=None,
        error=None,
        updated_at=updated_at,
    )
    queued_node = node.model_copy(
        update={
            "revision": node.revision + 1,
            "status": "draft",
            "error": None,
            "output_asset_id": (
                None if node.status in {"failed", "ready"} else node.output_asset_id
            ),
            "generation_prompt": None if prepared_projection else node.generation_prompt,
            "structured_content": {} if prepared_projection else node.structured_content,
            "prompt_context_snapshot_id": None,
            "metadata": {
                key: value
                for key, value in node.metadata.items()
                if not key.startswith("prompt_") and key != "prepared_reference_snapshots"
            },
            "prompt_preparation": queued,
            "updated_at": _parse_datetime(updated_at),
        }
    )
    queued_node = normalize_queued_node(queued_node, bindings=bindings)
    values: dict[str, object | None] = {
        "prompt_preparation_json": queued_node.prompt_preparation.model_dump_json(),
        "prompt_context_snapshot_id": None,
        "generation_prompt": queued_node.generation_prompt,
        "structured_content_json": _json_dump(queued_node.structured_content),
        "metadata_json": _json_dump(queued_node.metadata),
        "revision": queued_node.revision,
        "updated_at": updated_at,
    }
    if node.status in {"failed", "ready"}:
        values.update(
            status="draft",
            error_json=None,
            output_asset_id=None,
        )
    connection.execute(
        update(AgentCanvasNodeRow)
        .where(
            AgentCanvasNodeRow.workflow_id == workflow_id,
            AgentCanvasNodeRow.node_id == target_node_id,
            AgentCanvasNodeRow.revision == node.revision,
        )
        .values(**values)
    )
    safe_payload = {
        "node_revision": queued_node.revision,
        "creative_role": node.creative_role,
        "previous_operation_id": node.prompt_preparation.operation_id,
        "previous_prompt_digest": node.prompt_preparation.prompt_digest,
    }
    events.append_in_transaction(
        connection,
        V2EventInsert(
            workflow_id=workflow_id,
            node_id=target_node_id,
            event_type="node_prompt_preparation_superseded",
            created_at=updated_at,
            payload=safe_payload,
        ),
    )
    events.append_in_transaction(
        connection,
        V2EventInsert(
            workflow_id=workflow_id,
            node_id=target_node_id,
            event_type="node_prompt_preparation_queued",
            created_at=updated_at,
            payload={
                "node_revision": queued_node.revision,
                "creative_role": node.creative_role,
                "operation_id": queued_node.prompt_preparation.operation_id,
            },
        ),
    )
    if prompt_dispatch is not None:
        prompt_dispatch.supersede_and_enqueue_in_transaction(
            connection,
            node=queued_node,
            bindings=bindings,
            context=frozen_context,
            reason="dependency_or_binding_revision_changed",
            now=_parse_datetime(updated_at),
        )
    return queued_node


def _invalidate_prompt_preparations_for_source(
    connection: Connection,
    *,
    events: EventRepository,
    prompt_dispatch: AgentCanvasPromptPreparationDispatchRepository | None = None,
    workflow_id: str,
    source_node_id: str,
    updated_at: str,
) -> None:
    target_node_ids = tuple(
        connection.scalars(
            select(AgentCanvasBindingRow.target_node_id)
            .where(
                AgentCanvasBindingRow.workflow_id == workflow_id,
                AgentCanvasBindingRow.source_kind == "node_output",
                AgentCanvasBindingRow.source_node_id == source_node_id,
                AgentCanvasBindingRow.enabled.is_(True),
            )
            .distinct()
        )
    )
    for target_node_id in target_node_ids:
        _invalidate_target_prompt_preparation(
            connection,
            events=events,
            prompt_dispatch=prompt_dispatch,
            workflow_id=workflow_id,
            target_node_id=target_node_id,
            updated_at=updated_at,
        )


def invalidate_prompt_preparations_for_source_in_transaction(
    connection: Connection,
    *,
    events: EventRepository,
    prompt_dispatch: AgentCanvasPromptPreparationDispatchRepository | None = None,
    workflow_id: str,
    source_node_id: str,
    updated_at: str,
) -> None:
    """Invalidate all enabled Node-output dependents in a caller transaction."""

    _invalidate_prompt_preparations_for_source(
        connection,
        events=events,
        prompt_dispatch=prompt_dispatch,
        workflow_id=workflow_id,
        source_node_id=source_node_id,
        updated_at=updated_at,
    )


def _load_target_bindings(
    connection: Connection,
    workflow_id: str,
    target_node_id: str,
) -> tuple[CanvasBindingV2, ...]:
    rows = (
        connection.execute(
            select(AgentCanvasBindingRow)
            .where(
                AgentCanvasBindingRow.workflow_id == workflow_id,
                AgentCanvasBindingRow.target_node_id == target_node_id,
            )
            .order_by(
                AgentCanvasBindingRow.order_index.asc(),
                AgentCanvasBindingRow.binding_id.asc(),
            )
        )
        .mappings()
        .all()
    )
    return tuple(_binding_from_row(row) for row in rows)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _node_from_row(
    row: RowMapping,
    *,
    variation: RowMapping | None = None,
    model_summary: CanvasModelSummaryV2 | None = None,
) -> CanvasNodeV2:
    error_json = row["error_json"]
    return CanvasNodeV2(
        node_id=str(row["node_id"]),
        workflow_id=str(row["workflow_id"]),
        node_type=cast(str, row["node_type"]),
        creative_role=cast(str, row["creative_role"]),
        role_contract_version=cast(str, row["role_contract_version"]),
        title=str(row["title"]),
        status=cast(str, row["status"]),
        execution_mode=cast(str, row["execution_mode"]),
        summary_prompt=cast(str | None, row["summary_prompt"]),
        generation_prompt=cast(str | None, row["generation_prompt"]),
        structured_content=cast(
            dict[str, JsonValue], json.loads(str(row["structured_content_json"]))
        ),
        model_selection_mode=cast(str, row["model_selection_mode"]),
        model_ref=cast(str | None, row["model_ref"]),
        model_summary=model_summary,
        parameters=cast(dict[str, JsonValue], json.loads(str(row["parameters_json"]))),
        metadata=cast(dict[str, JsonValue], json.loads(str(row["metadata_json"]))),
        parameter_provenance=_parameter_provenance_from_row(row),
        prompt_context_snapshot_id=cast(str | None, row["prompt_context_snapshot_id"]),
        output_asset_id=cast(str | None, row["output_asset_id"]),
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
        prompt_preparation=NodePromptPreparationV1.model_validate_json(
            str(row["prompt_preparation_json"])
        ),
        variation_draft=(_variation_from_row(variation) if variation is not None else None),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _parameter_provenance_from_row(
    row: RowMapping,
) -> dict[str, CanvasParameterProvenanceV2]:
    parameters = cast(dict[str, JsonValue], json.loads(str(row["parameters_json"])))
    raw = json.loads(str(row["parameter_provenance_json"]))
    if raw:
        return {
            field: CanvasParameterProvenanceV2.model_validate(provenance)
            for field, provenance in raw.items()
        }
    return {
        field: CanvasParameterProvenanceV2(
            origin="manual",
            requested_value=value,
            effective_value=value,
        )
        for field, value in parameters.items()
        if isinstance(value, (str, int, float, bool))
    }


def _prompt_preparation_replays(current: CanvasNodeV2, requested: CanvasNodeV2) -> bool:
    return (
        current.revision == requested.revision
        and current.prompt_preparation == requested.prompt_preparation
        and current.generation_prompt == requested.generation_prompt
        and current.structured_content == requested.structured_content
        and current.parameters == requested.parameters
        and current.prompt_context_snapshot_id == requested.prompt_context_snapshot_id
    )


def _variation_from_row(row: RowMapping) -> CanvasVariationDraftV2:
    return CanvasVariationDraftV2(
        source_node_id=str(row["source_node_id"]),
        source_node_revision=int(row["source_node_revision"]),
        title=str(row["title"]),
        generation_prompt=str(row["generation_prompt"]),
        model_selection_mode=cast(str, row["model_selection_mode"]),
        model_ref=cast(str | None, row["model_ref"]),
        parameters=cast(
            dict[str, JsonValue],
            json.loads(str(row["parameters_json"])),
        ),
        variation_revision=int(row["variation_revision"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _load_model_summaries(
    database: V2Database,
    node_rows: tuple[RowMapping, ...] | list[RowMapping],
) -> dict[str, CanvasModelSummaryV2]:
    refs = {str(row["model_ref"]) for row in node_rows if row["model_ref"] is not None}
    if not refs:
        return {}
    repository = ProviderModelRepository(database)
    records = {record.model_ref: record for record in repository.list_models()}
    return {
        model_ref: CanvasModelSummaryV2(
            model_ref=record.model_ref,
            provider_id=record.provider_id,
            display_name=record.display_name,
            capability=cast("str", record.capability),
            availability=cast("str", record.availability),
            unavailable_reason=record.unavailable_reason,
            catalog_revision=record.catalog_revision,
        )
        for model_ref, record in records.items()
        if model_ref in refs
    }


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
        "source_asset_version_id": (
            binding.source.source_asset_version_id
            if isinstance(binding.source, CanvasBindingSourceImageAssetV2)
            else None
        ),
        "target_node_id": binding.target_node_id,
        "input_role": binding.input_role,
        "required": binding.required,
        "enabled": binding.enabled,
        "order_index": binding.order,
        "label": binding.label,
        "metadata_json": _json_dump(binding.metadata),
        "created_at": binding.created_at.isoformat(),
        "updated_at": binding.updated_at.isoformat(),
    }


def _normalize_target_binding_order(
    connection: Connection,
    *,
    workflow_id: str,
    target_node_id: str,
    prioritized_binding_id: str | None = None,
    requested_order: int | None = None,
) -> int:
    rows = (
        connection.execute(
            select(AgentCanvasBindingRow)
            .where(
                AgentCanvasBindingRow.workflow_id == workflow_id,
                AgentCanvasBindingRow.target_node_id == target_node_id,
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
    ordered = list(rows)
    requested_position = 0
    if prioritized_binding_id is not None:
        selected = next(
            (row for row in ordered if str(row["binding_id"]) == prioritized_binding_id),
            None,
        )
        if selected is None:
            raise _binding_not_found_error()
        ordered.remove(selected)
        requested_position = min(
            requested_order if requested_order is not None else len(ordered),
            len(ordered),
        )
        ordered.insert(requested_position, selected)
    for display_order, row in enumerate(ordered):
        connection.execute(
            update(AgentCanvasBindingRow)
            .where(AgentCanvasBindingRow.binding_id == str(row["binding_id"]))
            .values(order_index=display_order)
        )
    return requested_position


def _binding_from_row(row: RowMapping) -> CanvasBindingV2:
    source = (
        CanvasBindingSourceNodeV2(source_node_id=str(row["source_node_id"]))
        if row["source_kind"] == "node_output"
        else CanvasBindingSourceImageAssetV2(
            source_asset_id=str(row["source_asset_id"]),
            source_asset_version_id=(
                str(row["source_asset_version_id"])
                if row.get("source_asset_version_id") is not None
                else None
            ),
        )
    )
    return CanvasBindingV2(
        binding_id=str(row["binding_id"]),
        workflow_id=str(row["workflow_id"]),
        source=source,
        target_node_id=str(row["target_node_id"]),
        input_role=cast(str, row["input_role"]),
        required=bool(row["required"]),
        enabled=bool(row["enabled"]),
        order=int(row["order_index"]),
        label=cast(str | None, row["label"]),
        metadata=cast(dict[str, JsonValue], json.loads(str(row["metadata_json"]))),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
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


def _prompt_preparation_conflict() -> V2PersistenceError:
    return V2PersistenceError(
        "prompt_preparation_revision_conflict",
        "Node prompt preparation changed before this operation committed.",
        stage="prompt_preparation",
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


def _parameter_authoring_changed_error() -> V2PersistenceError:
    return V2PersistenceError(
        "node_parameter_compilation_failed",
        "Video parameter compilation lost an authoring revision race.",
        stage="parameter_compilation",
        details={"reason": "authoring_revision_changed", "retryable": True},
    )
