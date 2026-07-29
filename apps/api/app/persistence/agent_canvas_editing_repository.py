"""SQLite persistence for Agent Canvas Editing export attempts."""

from __future__ import annotations

import json
from datetime import datetime
from typing import cast
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.models import AgentCanvasEditingExportRow
from app.schemas.agent_canvas import CanvasNodeErrorV2
from app.schemas.agent_canvas_editing import (
    EditingExportRuntimeV2,
    EditingManifestV2,
    EditingSkippedInputV2,
)


class AgentCanvasEditingExportRepository:
    """Persist idempotent exports without owning rendering."""

    def __init__(self, database: V2Database) -> None:
        self._database = database

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
        current = self.get(export_id)
        if current.status not in {"queued", "exporting"}:
            raise _error(
                "editing_export_already_terminal",
                "Editing export is already terminal.",
            )
        try:
            with self._database.engine.begin() as connection:
                connection.execute(
                    update(AgentCanvasEditingExportRow)
                    .where(AgentCanvasEditingExportRow.export_id == export_id)
                    .values(cancel_requested=True, updated_at=now.isoformat())
                )
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


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_editing_repository")
