"""SQLite persistence for Agent Canvas Editing export attempts."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import cast
from uuid import uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasEditingExportRow,
    AgentCanvasNodeRow,
    AgentCanvasWorkflowRow,
    AssetVersionRow,
    WorkflowEventRow,
)
from app.schemas.agent_canvas import CanvasNodeErrorV2
from app.schemas.agent_canvas_editing import (
    EditingExportRuntimeV2,
    EditingManifestV2,
    EditingNodeContentV2,
    EditingSkippedInputV2,
)
from app.schemas.agent_canvas_editing_authority import (
    EditingExportStartCommandV2,
    EditingExportStartResultV2,
    FencedLeaseTokenV2,
)
from app.schemas.v2_persistence import V2EventInsert


FaultInjector = Callable[[str], None]


class AgentCanvasEditingExportRepository:
    """Persist idempotent exports without owning rendering."""

    def __init__(
        self,
        database: V2Database,
        *,
        events: EventRepository | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self._database = database
        self._events = events or EventRepository(database)
        self._fault = fault_injector or (lambda _boundary: None)

    @property
    def database(self) -> V2Database:
        return self._database

    def start_or_reuse(
        self,
        command: EditingExportStartCommandV2,
    ) -> EditingExportStartResultV2:
        """Admit one Export and its Working projection under one write lock."""

        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    replay = self._start_replay(connection, command)
                    if replay is not None:
                        connection.commit()
                        return replay
                    self._assert_start_authority(connection, command)
                    reusable = self._verified_completed_reuse(connection, command)
                    if reusable is not None:
                        connection.commit()
                        return reusable
                    active = connection.execute(
                        select(AgentCanvasEditingExportRow.export_id).where(
                            AgentCanvasEditingExportRow.workflow_id == command.workflow_id,
                            AgentCanvasEditingExportRow.node_id == command.node_id,
                            AgentCanvasEditingExportRow.status.in_(("queued", "exporting")),
                        )
                    ).scalar_one_or_none()
                    if active is not None:
                        raise _error(
                            "editing_export_already_active",
                            "An Editing export is already active for this node.",
                        )
                    export_id = f"export_{uuid4().hex}"
                    timestamp = command.created_at.isoformat()
                    connection.execute(
                        insert(AgentCanvasEditingExportRow).values(
                            export_id=export_id,
                            workflow_id=command.workflow_id,
                            node_id=command.node_id,
                            status="queued",
                            manifest_revision=command.manifest_revision,
                            manifest_json=command.manifest.model_dump_json(),
                            fingerprint=command.fingerprint,
                            idempotency_key=command.idempotency_key,
                            ready_video_node_ids_json=json.dumps(
                                list(command.ready_video_node_ids)
                            ),
                            skipped_inputs_json=json.dumps(
                                [item.model_dump(mode="json") for item in command.skipped_inputs]
                            ),
                            bgm_node_id=command.bgm_node_id,
                            output_asset_id=None,
                            error_json=None,
                            cancel_requested=False,
                            lease_owner_id=None,
                            lease_generation=0,
                            lease_heartbeat_at=None,
                            lease_expires_at=None,
                            created_at=timestamp,
                            started_at=None,
                            finished_at=None,
                            updated_at=timestamp,
                        )
                    )
                    runtime = _runtime(
                        connection.execute(
                            select(AgentCanvasEditingExportRow).where(
                                AgentCanvasEditingExportRow.export_id == export_id
                            )
                        )
                        .mappings()
                        .one()
                    )
                    node = (
                        connection.execute(
                            select(AgentCanvasNodeRow).where(
                                AgentCanvasNodeRow.workflow_id == command.workflow_id,
                                AgentCanvasNodeRow.node_id == command.node_id,
                            )
                        )
                        .mappings()
                        .one()
                    )
                    content = EditingNodeContentV2.model_validate_json(
                        str(node["structured_content_json"])
                    ).model_copy(update={"active_export": runtime})
                    changed = connection.execute(
                        update(AgentCanvasNodeRow)
                        .where(
                            AgentCanvasNodeRow.workflow_id == command.workflow_id,
                            AgentCanvasNodeRow.node_id == command.node_id,
                            AgentCanvasNodeRow.revision == command.expected_node_revision,
                        )
                        .values(
                            status="working",
                            structured_content_json=content.model_dump_json(),
                            error_json=None,
                            updated_at=timestamp,
                        )
                    )
                    if changed.rowcount != 1:
                        raise _error(
                            "editing_export_stale",
                            "Editing Node changed before export admission.",
                        )
                    self._fault("after_node")
                    event = self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=command.workflow_id,
                            execution_id=export_id,
                            node_id=command.node_id,
                            transition_key=f"editing:{export_id}:queued",
                            event_type="editing_export_queued",
                            created_at=timestamp,
                            payload={
                                "export_id": export_id,
                                "manifest_revision": command.manifest_revision,
                                "refresh": ["workflow", "runtime", "events"],
                            },
                        ),
                    )
                    self._fault("after_event")
                    result = EditingExportStartResultV2(
                        export=runtime,
                        disposition="created",
                        event_cursor=event.seq,
                    )
                    self._fault("before_commit")
                    connection.commit()
                    return result
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            message = str(error)
            if (
                "agent_canvas_editing_exports.workflow_id" in message
                and "agent_canvas_editing_exports.node_id" in message
            ):
                raise _error(
                    "editing_export_already_active",
                    "An Editing export is already active for this node.",
                ) from error
            raise _error(
                "editing_export_persistence_failed",
                "Editing export conflicts with an existing attempt.",
            ) from error
        except SQLAlchemyError as error:
            raise _error(
                "editing_export_persistence_failed",
                "Editing export storage is unavailable.",
            ) from error

    def _start_replay(
        self,
        connection: Connection,
        command: EditingExportStartCommandV2,
    ) -> EditingExportStartResultV2 | None:
        row = (
            connection.execute(
                select(AgentCanvasEditingExportRow).where(
                    AgentCanvasEditingExportRow.workflow_id == command.workflow_id,
                    AgentCanvasEditingExportRow.node_id == command.node_id,
                    AgentCanvasEditingExportRow.idempotency_key == command.idempotency_key,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        runtime = _runtime(row)
        if runtime.fingerprint != command.fingerprint:
            raise _error(
                "idempotency_conflict",
                "Idempotency key was reused with another Editing export.",
            )
        return EditingExportStartResultV2(
            export=runtime,
            disposition="replayed",
            event_cursor=self._event_cursor(connection, command.workflow_id),
        )

    @staticmethod
    def _assert_start_authority(
        connection: Connection,
        command: EditingExportStartCommandV2,
    ) -> None:
        workflow_revision = connection.execute(
            select(AgentCanvasWorkflowRow.revision).where(
                AgentCanvasWorkflowRow.workflow_id == command.workflow_id
            )
        ).scalar_one_or_none()
        if workflow_revision != command.expected_workflow_revision:
            raise _error(
                "editing_export_stale",
                "Workflow revision changed before Editing export admission.",
            )
        node = (
            connection.execute(
                select(
                    AgentCanvasNodeRow.node_type,
                    AgentCanvasNodeRow.revision,
                    AgentCanvasNodeRow.structured_content_json,
                ).where(
                    AgentCanvasNodeRow.workflow_id == command.workflow_id,
                    AgentCanvasNodeRow.node_id == command.node_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if node is None or str(node["node_type"]) != "editing":
            raise _error("editing_node_not_found", "Editing node was not found.")
        if int(node["revision"]) != command.expected_node_revision:
            raise _error(
                "editing_export_stale",
                "Editing Node revision changed before export admission.",
            )
        manifest = EditingNodeContentV2.model_validate_json(
            str(node["structured_content_json"])
        ).manifest
        if (
            manifest.manifest_revision != command.manifest_revision or manifest != command.manifest
        ) and not _legacy_manifest_matches(manifest, command.manifest):
            raise _error(
                "editing_manifest_revision_conflict",
                "Editing manifest changed before export admission.",
            )
        for assertion in command.source_asset_assertions:
            found = connection.execute(
                select(AssetVersionRow.version_id).where(
                    AssetVersionRow.asset_id == assertion.asset_id,
                    AssetVersionRow.sha256 == assertion.sha256,
                    AssetVersionRow.status == "ready",
                )
            ).scalar_one_or_none()
            if found is None:
                raise _error(
                    "editing_export_stale",
                    "An Editing source Asset changed before export admission.",
                )

    def _verified_completed_reuse(
        self,
        connection: Connection,
        command: EditingExportStartCommandV2,
    ) -> EditingExportStartResultV2 | None:
        if command.verified_reusable_export_id is None:
            return None
        row = (
            connection.execute(
                select(AgentCanvasEditingExportRow).where(
                    AgentCanvasEditingExportRow.export_id == command.verified_reusable_export_id,
                    AgentCanvasEditingExportRow.workflow_id == command.workflow_id,
                    AgentCanvasEditingExportRow.node_id == command.node_id,
                    AgentCanvasEditingExportRow.fingerprint == command.fingerprint,
                    AgentCanvasEditingExportRow.status == "completed",
                    AgentCanvasEditingExportRow.output_asset_id.is_not(None),
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise _error(
                "editing_export_stale",
                "The reusable Editing output changed before admission.",
            )
        return EditingExportStartResultV2(
            export=_runtime(row),
            disposition="completed_reuse",
            event_cursor=self._event_cursor(connection, command.workflow_id),
        )

    @staticmethod
    def _event_cursor(connection: Connection, workflow_id: str) -> int:
        return int(
            connection.execute(
                select(func.coalesce(func.max(WorkflowEventRow.seq), 0)).where(
                    WorkflowEventRow.workflow_id == workflow_id
                )
            ).scalar_one()
        )

    def claim_lease(
        self,
        export_id: str,
        *,
        owner_id: str,
        now: datetime,
        ttl: timedelta,
    ) -> FencedLeaseTokenV2:
        if ttl <= timedelta(0):
            raise ValueError("Lease TTL must be positive.")
        timestamp = now.isoformat()
        expires_at = now + ttl
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    row = (
                        connection.execute(
                            select(AgentCanvasEditingExportRow).where(
                                AgentCanvasEditingExportRow.export_id == export_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None:
                        raise _error(
                            "editing_export_not_found",
                            "Editing export was not found.",
                        )
                    if str(row["status"]) not in {"queued", "exporting"}:
                        raise _error(
                            "editing_export_already_terminal",
                            "Editing export is already terminal.",
                        )
                    current_owner = cast(str | None, row["lease_owner_id"])
                    current_expiry = cast(str | None, row["lease_expires_at"])
                    if (
                        current_owner is not None
                        and current_expiry is not None
                        and current_expiry > timestamp
                    ):
                        if current_owner != owner_id:
                            raise _error(
                                "editing_export_lease_unavailable",
                                "Editing export lease is owned by another worker.",
                            )
                        lease = _lease(row)
                        connection.commit()
                        return lease
                    generation = int(row["lease_generation"] or 0) + 1
                    connection.execute(
                        update(AgentCanvasEditingExportRow)
                        .where(AgentCanvasEditingExportRow.export_id == export_id)
                        .values(
                            status="exporting",
                            lease_owner_id=owner_id,
                            lease_generation=generation,
                            lease_heartbeat_at=timestamp,
                            lease_expires_at=expires_at.isoformat(),
                            started_at=row["started_at"] or timestamp,
                            updated_at=timestamp,
                        )
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=str(row["workflow_id"]),
                            execution_id=export_id,
                            node_id=str(row["node_id"]),
                            transition_key=f"editing:{export_id}:lease:{generation}",
                            event_type="editing_export_started",
                            created_at=timestamp,
                            payload={
                                "export_id": export_id,
                                "lease_generation": generation,
                                "refresh": ["runtime", "events"],
                            },
                        ),
                    )
                    connection.commit()
                    return FencedLeaseTokenV2(
                        resource_type="editing_export",
                        resource_id=export_id,
                        owner_id=owner_id,
                        generation=generation,
                        heartbeat_at=now,
                        expires_at=expires_at,
                    )
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "editing_export_persistence_failed",
                "Editing export lease storage is unavailable.",
            ) from error

    def renew_lease(
        self,
        lease: FencedLeaseTokenV2,
        *,
        now: datetime,
        ttl: timedelta,
    ) -> FencedLeaseTokenV2:
        if ttl <= timedelta(0):
            raise ValueError("Lease TTL must be positive.")
        expires_at = now + ttl
        try:
            with self._database.engine.begin() as connection:
                changed = connection.execute(
                    update(AgentCanvasEditingExportRow)
                    .where(
                        AgentCanvasEditingExportRow.export_id == lease.resource_id,
                        AgentCanvasEditingExportRow.status.in_(("queued", "exporting")),
                        AgentCanvasEditingExportRow.lease_owner_id == lease.owner_id,
                        AgentCanvasEditingExportRow.lease_generation == lease.generation,
                        AgentCanvasEditingExportRow.lease_expires_at > now.isoformat(),
                    )
                    .values(
                        lease_heartbeat_at=now.isoformat(),
                        lease_expires_at=expires_at.isoformat(),
                        updated_at=now.isoformat(),
                    )
                )
                if changed.rowcount != 1:
                    raise _stale_lease_error()
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "editing_export_persistence_failed",
                "Editing export lease could not be renewed.",
            ) from error
        return lease.model_copy(update={"heartbeat_at": now, "expires_at": expires_at})

    def assert_current_lease(
        self,
        lease: FencedLeaseTokenV2,
        *,
        now: datetime,
    ) -> None:
        try:
            with self._database.engine.connect() as connection:
                current = connection.execute(
                    select(AgentCanvasEditingExportRow.export_id).where(
                        AgentCanvasEditingExportRow.export_id == lease.resource_id,
                        AgentCanvasEditingExportRow.status.in_(("queued", "exporting")),
                        AgentCanvasEditingExportRow.lease_owner_id == lease.owner_id,
                        AgentCanvasEditingExportRow.lease_generation == lease.generation,
                        AgentCanvasEditingExportRow.lease_expires_at > now.isoformat(),
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise _error(
                "editing_export_persistence_failed",
                "Editing export lease could not be checked.",
            ) from error
        if current is None:
            raise _stale_lease_error()

    def append_progress(
        self,
        lease: FencedLeaseTokenV2,
        *,
        now: datetime,
        stage: str,
        progress: float,
    ) -> int:
        """Append progress only while the caller owns the current lease."""

        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    row = (
                        connection.execute(
                            select(AgentCanvasEditingExportRow).where(
                                AgentCanvasEditingExportRow.export_id == lease.resource_id,
                                AgentCanvasEditingExportRow.status.in_(("queued", "exporting")),
                                AgentCanvasEditingExportRow.lease_owner_id == lease.owner_id,
                                AgentCanvasEditingExportRow.lease_generation == lease.generation,
                                AgentCanvasEditingExportRow.lease_expires_at > now.isoformat(),
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None:
                        raise _stale_lease_error()
                    event = self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=str(row["workflow_id"]),
                            execution_id=lease.resource_id,
                            node_id=str(row["node_id"]),
                            transition_key=(
                                f"editing:{lease.resource_id}:lease:{lease.generation}:"
                                f"progress:{stage}"
                            ),
                            event_type="editing_export_progress",
                            created_at=now.isoformat(),
                            payload={
                                "export_id": lease.resource_id,
                                "lease_generation": lease.generation,
                                "stage": stage,
                                "progress": progress,
                                "refresh": ["events"],
                            },
                        ),
                    )
                    connection.commit()
                    return event.seq
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "editing_export_persistence_failed",
                "Editing export progress could not be persisted.",
            ) from error

    def create(
        self,
        *,
        workflow_id: str,
        node_id: str,
        manifest: EditingManifestV2,
        fingerprint: str,
        idempotency_key: str,
        ready_video_node_ids: tuple[str, ...],
        skipped_inputs: tuple[EditingSkippedInputV2, ...],
        bgm_node_id: str | None,
        now: datetime,
    ) -> EditingExportRuntimeV2:
        existing = self.find_by_idempotency(workflow_id, node_id, idempotency_key)
        if existing is not None:
            if existing.fingerprint != fingerprint:
                raise _error(
                    "idempotency_conflict",
                    "Idempotency key was reused with another Editing export.",
                )
            return existing
        export_id = f"export_{uuid4().hex}"
        timestamp = now.isoformat()
        try:
            with self._database.engine.begin() as connection:
                connection.execute(
                    insert(AgentCanvasEditingExportRow).values(
                        export_id=export_id,
                        workflow_id=workflow_id,
                        node_id=node_id,
                        status="queued",
                        manifest_revision=manifest.manifest_revision,
                        manifest_json=manifest.model_dump_json(),
                        fingerprint=fingerprint,
                        idempotency_key=idempotency_key,
                        ready_video_node_ids_json=json.dumps(list(ready_video_node_ids)),
                        skipped_inputs_json=json.dumps(
                            [item.model_dump(mode="json") for item in skipped_inputs]
                        ),
                        bgm_node_id=bgm_node_id,
                        output_asset_id=None,
                        error_json=None,
                        cancel_requested=False,
                        created_at=timestamp,
                        started_at=None,
                        finished_at=None,
                        updated_at=timestamp,
                    )
                )
        except IntegrityError as error:
            raise _error(
                "editing_export_persistence_failed",
                "Editing export conflicts with an existing attempt.",
            ) from error
        except SQLAlchemyError as error:
            raise _error(
                "editing_export_persistence_failed",
                "Editing export storage is unavailable.",
            ) from error
        return self.get(export_id)

    def get(self, export_id: str) -> EditingExportRuntimeV2:
        row = self._one(
            select(AgentCanvasEditingExportRow).where(
                AgentCanvasEditingExportRow.export_id == export_id
            )
        )
        if row is None:
            raise _error("editing_export_not_found", "Editing export was not found.")
        return _runtime(row)

    def identity(self, export_id: str) -> tuple[str, str]:
        row = self._one(
            select(
                AgentCanvasEditingExportRow.workflow_id,
                AgentCanvasEditingExportRow.node_id,
            ).where(AgentCanvasEditingExportRow.export_id == export_id)
        )
        if row is None:
            raise _error("editing_export_not_found", "Editing export was not found.")
        return str(row["workflow_id"]), str(row["node_id"])

    def manifest(self, export_id: str) -> EditingManifestV2:
        row = self._one(
            select(AgentCanvasEditingExportRow.manifest_json).where(
                AgentCanvasEditingExportRow.export_id == export_id
            )
        )
        if row is None:
            raise _error("editing_export_not_found", "Editing export was not found.")
        return EditingManifestV2.model_validate_json(str(row["manifest_json"]))

    def find_by_idempotency(
        self,
        workflow_id: str,
        node_id: str,
        idempotency_key: str,
    ) -> EditingExportRuntimeV2 | None:
        row = self._one(
            select(AgentCanvasEditingExportRow).where(
                AgentCanvasEditingExportRow.workflow_id == workflow_id,
                AgentCanvasEditingExportRow.node_id == node_id,
                AgentCanvasEditingExportRow.idempotency_key == idempotency_key,
            )
        )
        return _runtime(row) if row is not None else None

    def find_completed(
        self,
        workflow_id: str,
        node_id: str,
        fingerprint: str,
    ) -> EditingExportRuntimeV2 | None:
        row = self._one(
            select(AgentCanvasEditingExportRow)
            .where(
                AgentCanvasEditingExportRow.workflow_id == workflow_id,
                AgentCanvasEditingExportRow.node_id == node_id,
                AgentCanvasEditingExportRow.fingerprint == fingerprint,
                AgentCanvasEditingExportRow.status == "completed",
                AgentCanvasEditingExportRow.output_asset_id.is_not(None),
            )
            .order_by(AgentCanvasEditingExportRow.created_at.desc())
            .limit(1)
        )
        return _runtime(row) if row is not None else None

    def find_active(
        self,
        workflow_id: str,
        node_id: str,
    ) -> EditingExportRuntimeV2 | None:
        row = self._one(
            select(AgentCanvasEditingExportRow)
            .where(
                AgentCanvasEditingExportRow.workflow_id == workflow_id,
                AgentCanvasEditingExportRow.node_id == node_id,
                AgentCanvasEditingExportRow.status.in_(("queued", "exporting")),
            )
            .order_by(AgentCanvasEditingExportRow.created_at.desc())
            .limit(1)
        )
        return _runtime(row) if row is not None else None

    def list_active(self) -> tuple[EditingExportRuntimeV2, ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasEditingExportRow)
                        .where(AgentCanvasEditingExportRow.status.in_(("queued", "exporting")))
                        .order_by(AgentCanvasEditingExportRow.created_at.asc())
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _error(
                "editing_export_persistence_failed",
                "Editing export storage is unavailable.",
            ) from error
        return tuple(_runtime(row) for row in rows)

    def list_completed(
        self,
        workflow_id: str,
        node_id: str,
    ) -> tuple[EditingExportRuntimeV2, ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasEditingExportRow)
                        .where(
                            AgentCanvasEditingExportRow.workflow_id == workflow_id,
                            AgentCanvasEditingExportRow.node_id == node_id,
                            AgentCanvasEditingExportRow.status == "completed",
                        )
                        .order_by(AgentCanvasEditingExportRow.created_at.asc())
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _error(
                "editing_export_persistence_failed",
                "Editing export storage is unavailable.",
            ) from error
        return tuple(_runtime(row) for row in rows)

    def list_completed_all(self) -> tuple[EditingExportRuntimeV2, ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasEditingExportRow)
                        .where(AgentCanvasEditingExportRow.status == "completed")
                        .order_by(AgentCanvasEditingExportRow.created_at.asc())
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _error(
                "editing_export_persistence_failed",
                "Editing export storage is unavailable.",
            ) from error
        return tuple(_runtime(row) for row in rows)

    def lease_generation(self, export_id: str) -> int:
        row = self._one(
            select(AgentCanvasEditingExportRow).where(
                AgentCanvasEditingExportRow.export_id == export_id
            )
        )
        if row is None:
            raise _error("editing_export_not_found", "Editing export was not found.")
        return int(row["lease_generation"])

    def update(
        self,
        export_id: str,
        *,
        status: str,
        now: datetime,
        output_asset_id: str | None = None,
        error: CanvasNodeErrorV2 | None = None,
    ) -> EditingExportRuntimeV2:
        values: dict[str, object] = {
            "status": status,
            "updated_at": now.isoformat(),
            "error_json": error.model_dump_json() if error else None,
        }
        if status == "exporting":
            values["started_at"] = now.isoformat()
        if status in {"completed", "failed", "cancelled"}:
            values["finished_at"] = now.isoformat()
        if output_asset_id is not None:
            values["output_asset_id"] = output_asset_id
        try:
            with self._database.engine.begin() as connection:
                changed = connection.execute(
                    update(AgentCanvasEditingExportRow)
                    .where(AgentCanvasEditingExportRow.export_id == export_id)
                    .values(**values)
                )
                if changed.rowcount != 1:
                    raise _error(
                        "editing_export_not_found",
                        "Editing export was not found.",
                    )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "editing_export_persistence_failed",
                "Editing export storage is unavailable.",
            ) from error
        return self.get(export_id)

    def request_cancel(self, export_id: str, *, now: datetime) -> EditingExportRuntimeV2:
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                changed = connection.execute(
                    update(AgentCanvasEditingExportRow)
                    .where(
                        AgentCanvasEditingExportRow.export_id == export_id,
                        AgentCanvasEditingExportRow.status.in_(("queued", "exporting")),
                    )
                    .values(cancel_requested=True, updated_at=now.isoformat())
                )
                if changed.rowcount != 1:
                    exists = connection.execute(
                        select(AgentCanvasEditingExportRow.export_id).where(
                            AgentCanvasEditingExportRow.export_id == export_id
                        )
                    ).scalar_one_or_none()
                    connection.rollback()
                    if exists is None:
                        raise _error("editing_export_not_found", "Editing export was not found.")
                    raise _error(
                        "editing_export_already_terminal",
                        "Editing export is already terminal.",
                    )
                connection.commit()
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "editing_export_cancel_failed",
                "Editing export cancellation could not be persisted.",
            ) from error
        return self.get(export_id)

    def is_cancel_requested(self, export_id: str) -> bool:
        try:
            with self._database.engine.connect() as connection:
                value = connection.execute(
                    select(AgentCanvasEditingExportRow.cancel_requested).where(
                        AgentCanvasEditingExportRow.export_id == export_id
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise _error(
                "editing_export_persistence_failed",
                "Editing export storage is unavailable.",
            ) from error
        if value is None:
            raise _error("editing_export_not_found", "Editing export was not found.")
        return bool(value)

    def _one(self, statement) -> RowMapping | None:
        try:
            with self._database.engine.connect() as connection:
                return connection.execute(statement).mappings().one_or_none()
        except SQLAlchemyError as error:
            raise _error(
                "editing_export_persistence_failed",
                "Editing export storage is unavailable.",
            ) from error


def _runtime(row: RowMapping) -> EditingExportRuntimeV2:
    error_json = cast(str | None, row["error_json"])
    return EditingExportRuntimeV2(
        export_id=str(row["export_id"]),
        status=cast(str, row["status"]),
        manifest_revision=int(row["manifest_revision"]),
        fingerprint=str(row["fingerprint"]),
        ready_video_node_ids=tuple(json.loads(str(row["ready_video_node_ids_json"]))),
        skipped_inputs=tuple(
            EditingSkippedInputV2.model_validate(item)
            for item in json.loads(str(row["skipped_inputs_json"]))
        ),
        bgm_node_id=cast(str | None, row["bgm_node_id"]),
        output_asset_id=cast(str | None, row["output_asset_id"]),
        error=CanvasNodeErrorV2.model_validate_json(error_json) if error_json else None,
        started_at=cast(str | None, row["started_at"]),
        finished_at=cast(str | None, row["finished_at"]),
    )


def _lease(row: RowMapping) -> FencedLeaseTokenV2:
    return FencedLeaseTokenV2(
        resource_type="editing_export",
        resource_id=str(row["export_id"]),
        owner_id=str(row["lease_owner_id"]),
        generation=int(row["lease_generation"]),
        heartbeat_at=str(row["lease_heartbeat_at"]),
        expires_at=str(row["lease_expires_at"]),
    )


def _stale_lease_error() -> V2PersistenceError:
    return _error(
        "stale_editing_export_lease",
        "Editing export lease ownership was lost.",
    )


def _legacy_manifest_matches(
    stored: EditingManifestV2,
    canonical: EditingManifestV2,
) -> bool:
    """Allow a read-only canonical projection to pass raw legacy admission checks."""

    if stored.timeline_duration_seconds is not None or any(
        entry.timeline_start_seconds is not None for entry in stored.video_entries
    ):
        return False
    stored_payload = stored.model_dump(mode="json")
    canonical_payload = canonical.model_dump(mode="json")
    stored_payload.pop("timeline_duration_seconds", None)
    canonical_payload.pop("timeline_duration_seconds", None)
    for payload in (stored_payload, canonical_payload):
        for entry in payload["video_entries"]:
            entry.pop("timeline_start_seconds", None)
    return stored_payload == canonical_payload


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_editing_repository")
