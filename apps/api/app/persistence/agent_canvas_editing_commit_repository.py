"""Atomic terminal authority for Agent Canvas Editing exports."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import cast

from sqlalchemy import insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasEditingExportCommitRow,
    AgentCanvasEditingExportRow,
    AgentCanvasNodeRow,
)
from app.schemas.agent_canvas_editing import EditingNodeContentV2
from app.schemas.agent_canvas_editing_authority import (
    EditingExportCommitCommandV2,
    EditingExportCommitReceiptV2,
)
from app.schemas.v2_asset_library import AssetRecordCreate, AssetVersionCreate
from app.schemas.v2_persistence import V2EventInsert


FaultInjector = Callable[[str], None]


class AgentCanvasEditingExportCommitRepository:
    """Commit one fenced Editing terminal transition and all projections."""

    def __init__(
        self,
        database: V2Database,
        assets: V2AssetLibraryRepository,
        events: EventRepository,
        *,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        if assets.database is not database or events.database is not database:
            raise ValueError("Editing authority repositories must share one database.")
        self._database = database
        self._assets = assets
        self._events = events
        self._fault = fault_injector or (lambda _boundary: None)

    def commit(
        self,
        command: EditingExportCommitCommandV2,
    ) -> EditingExportCommitReceiptV2:
        timestamp = command.committed_at.isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    existing = (
                        connection.execute(
                            select(AgentCanvasEditingExportCommitRow).where(
                                AgentCanvasEditingExportCommitRow.logical_commit_key
                                == command.logical_commit_key
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is not None:
                        receipt = EditingExportCommitReceiptV2.model_validate_json(
                            str(existing["receipt_json"])
                        )
                        if receipt.payload_digest != command.payload_digest:
                            raise _error(
                                "editing_export_commit_conflict",
                                "Editing Export terminal identity is immutable.",
                            )
                        connection.commit()
                        return receipt
                    prior_export_commit = connection.execute(
                        select(AgentCanvasEditingExportCommitRow.commit_id).where(
                            AgentCanvasEditingExportCommitRow.export_id == command.export_id
                        )
                    ).scalar_one_or_none()
                    if prior_export_commit is not None:
                        raise _error(
                            "editing_export_commit_conflict",
                            "Editing Export already has another terminal commit identity.",
                        )

                    export = self._current_export(connection, command)
                    node = (
                        connection.execute(
                            select(AgentCanvasNodeRow).where(
                                AgentCanvasNodeRow.workflow_id == command.workflow_id,
                                AgentCanvasNodeRow.node_id == command.node_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if node is None:
                        raise _error("editing_node_not_found", "Editing node was not found.")
                    content = EditingNodeContentV2.model_validate_json(
                        str(node["structured_content_json"])
                    )
                    asset_id, version_id = self._register_asset(connection, command)
                    self._fault("after_asset")

                    terminal = _terminal_runtime(export, command, asset_id)
                    changed = connection.execute(
                        update(AgentCanvasEditingExportRow)
                        .where(
                            AgentCanvasEditingExportRow.export_id == command.export_id,
                            AgentCanvasEditingExportRow.status.in_(("queued", "exporting")),
                            AgentCanvasEditingExportRow.lease_owner_id == command.lease.owner_id,
                            AgentCanvasEditingExportRow.lease_generation
                            == command.lease.generation,
                        )
                        .values(
                            status=command.outcome,
                            output_asset_id=asset_id,
                            error_json=command.error.model_dump_json() if command.error else None,
                            finished_at=timestamp,
                            updated_at=timestamp,
                            lease_heartbeat_at=timestamp,
                            lease_expires_at=timestamp,
                        )
                    )
                    if changed.rowcount != 1:
                        raise _stale_lease_error()
                    self._fault("after_export")

                    has_success = content.last_successful_export is not None
                    if command.outcome == "completed":
                        node_status = "ready"
                        output_asset_id = asset_id
                        node_error = None
                        next_content = content.model_copy(
                            update={
                                "dirty": False,
                                "active_export": None,
                                "last_successful_export": terminal,
                            }
                        )
                    else:
                        node_status = (
                            "ready"
                            if has_success
                            else ("draft" if command.outcome == "cancelled" else "failed")
                        )
                        output_asset_id = node["output_asset_id"] if has_success else None
                        node_error = None if has_success else command.error
                        next_content = content.model_copy(update={"active_export": None})
                    connection.execute(
                        update(AgentCanvasNodeRow)
                        .where(
                            AgentCanvasNodeRow.workflow_id == command.workflow_id,
                            AgentCanvasNodeRow.node_id == command.node_id,
                        )
                        .values(
                            status=node_status,
                            output_asset_id=output_asset_id,
                            structured_content_json=next_content.model_dump_json(),
                            error_json=node_error.model_dump_json() if node_error else None,
                            updated_at=timestamp,
                        )
                    )
                    self._fault("after_node")
                    event_cursor = self._append_events(
                        connection,
                        command,
                        asset_id=asset_id,
                        version_id=version_id,
                    )
                    self._fault("after_event")
                    commit_id = (
                        "editing_commit_"
                        + hashlib.sha256(command.logical_commit_key.encode("utf-8")).hexdigest()[
                            :32
                        ]
                    )
                    receipt = EditingExportCommitReceiptV2(
                        commit_id=commit_id,
                        export_id=command.export_id,
                        logical_commit_key=command.logical_commit_key,
                        payload_digest=command.payload_digest,
                        outcome=command.outcome,
                        asset_id=asset_id,
                        version_id=version_id,
                        node_revision=int(node["revision"]),
                        event_cursor=event_cursor,
                        committed_at=command.committed_at,
                    )
                    connection.execute(
                        insert(AgentCanvasEditingExportCommitRow).values(
                            commit_id=commit_id,
                            export_id=command.export_id,
                            logical_commit_key=command.logical_commit_key,
                            payload_digest=command.payload_digest,
                            outcome=command.outcome,
                            asset_id=asset_id,
                            version_id=version_id,
                            receipt_json=receipt.model_dump_json(),
                            committed_at=timestamp,
                        )
                    )
                    self._fault("before_commit")
                    connection.commit()
                    return receipt
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "editing_export_commit_failed",
                "Editing Export terminal state could not be committed.",
            ) from error

    def receipt_for_export(self, export_id: str) -> EditingExportCommitReceiptV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasEditingExportCommitRow.receipt_json).where(
                            AgentCanvasEditingExportCommitRow.export_id == export_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _error(
                "editing_export_commit_failed",
                "Editing Export receipt could not be read.",
            ) from error
        if row is None:
            raise _error("editing_export_commit_not_found", "Editing Export receipt was not found.")
        return EditingExportCommitReceiptV2.model_validate_json(str(row["receipt_json"]))

    @staticmethod
    def _current_export(connection, command):
        row = (
            connection.execute(
                select(AgentCanvasEditingExportRow).where(
                    AgentCanvasEditingExportRow.export_id == command.export_id,
                    AgentCanvasEditingExportRow.workflow_id == command.workflow_id,
                    AgentCanvasEditingExportRow.node_id == command.node_id,
                    AgentCanvasEditingExportRow.fingerprint == command.fingerprint,
                    AgentCanvasEditingExportRow.status.in_(("queued", "exporting")),
                    AgentCanvasEditingExportRow.lease_owner_id == command.lease.owner_id,
                    AgentCanvasEditingExportRow.lease_generation == command.lease.generation,
                    AgentCanvasEditingExportRow.lease_expires_at > command.committed_at.isoformat(),
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise _stale_lease_error()
        return row

    def _register_asset(self, connection, command):
        prepared = command.prepared_object
        if prepared is None:
            return None, None
        facts = prepared.media_facts
        version = self._assets.register_asset_version_in_transaction(
            connection,
            AssetRecordCreate(
                asset_id=cast(str, command.asset_id),
                media_type="video",
                source_type="generated",
                display_name=str(command.asset_metadata.get("display_name") or prepared.filename),
            ),
            AssetVersionCreate(
                version_id=cast(str, command.version_id),
                asset_id=cast(str, command.asset_id),
                storage_key=prepared.storage_key,
                sha256=prepared.sha256,
                size_bytes=prepared.size_bytes,
                mime_type=prepared.mime_type,
                width=cast(int | None, facts.get("width")),
                height=cast(int | None, facts.get("height")),
                duration_seconds=cast(float | None, facts.get("duration_seconds")),
                source_workflow_id=command.workflow_id,
                source_node_id=command.node_id,
                metadata=command.asset_metadata,
                created_at=command.committed_at.isoformat(),
            ),
        )
        return version.asset_id, version.version_id

    def _append_events(self, connection, command, *, asset_id, version_id) -> int:
        event_types = []
        if command.outcome == "completed" and asset_id is not None:
            event_types.append("asset_published")
        event_types.append(f"editing_export_{command.outcome}")
        last = None
        for ordinal, event_type in enumerate(event_types):
            last = self._events.append_in_transaction(
                connection,
                V2EventInsert(
                    workflow_id=command.workflow_id,
                    execution_id=command.export_id,
                    node_id=command.node_id,
                    asset_id=asset_id,
                    version_id=version_id,
                    transition_key=(f"editing:{command.logical_commit_key}:{ordinal}:{event_type}"),
                    event_type=event_type,
                    created_at=command.committed_at.isoformat(),
                    payload={
                        "export_id": command.export_id,
                        "asset_id": asset_id,
                        "version_id": version_id,
                        "refresh": ["workflow", "runtime", "events"],
                    },
                ),
            )
        assert last is not None
        return last.seq


def _terminal_runtime(row, command, asset_id):
    from app.schemas.agent_canvas_editing import EditingExportRuntimeV2, EditingSkippedInputV2

    import json

    return EditingExportRuntimeV2(
        export_id=command.export_id,
        status=command.outcome,
        manifest_revision=int(row["manifest_revision"]),
        fingerprint=str(row["fingerprint"]),
        ready_video_node_ids=tuple(json.loads(str(row["ready_video_node_ids_json"]))),
        skipped_inputs=tuple(
            EditingSkippedInputV2.model_validate(item)
            for item in json.loads(str(row["skipped_inputs_json"]))
        ),
        bgm_node_id=cast(str | None, row["bgm_node_id"]),
        output_asset_id=asset_id,
        error=command.error,
        started_at=cast(str | None, row["started_at"]),
        finished_at=command.committed_at.isoformat(),
    )


def _stale_lease_error() -> V2PersistenceError:
    return _error("stale_editing_export_lease", "Editing Export lease ownership was lost.")


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_editing_commit_repository")
