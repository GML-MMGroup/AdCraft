"""Immutable SQLite projection cache for Agent Canvas World Settings."""

from __future__ import annotations

import json

from sqlalchemy import and_, insert, or_, select
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.models import AgentCanvasWorldSettingProjectionRow
from app.schemas.agent_canvas_world_setting import WorldSettingProjectionSnapshotV1


class AgentCanvasWorldSettingRepository:
    """Persist immutable projections while supporting caller-owned transactions."""

    def __init__(self, database: V2Database) -> None:
        self._database = database

    @property
    def database(self) -> V2Database:
        return self._database

    def insert(
        self,
        snapshot: WorldSettingProjectionSnapshotV1,
        *,
        connection: Connection | None = None,
    ) -> WorldSettingProjectionSnapshotV1:
        if connection is not None:
            return self._insert_in_transaction(connection, snapshot)
        try:
            with self._database.engine.begin() as transaction:
                return self._insert_in_transaction(transaction, snapshot)
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _conflict_error() from error
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def find_matching(
        self,
        *,
        source_node_id: str,
        source_node_revision: int,
        source_content_digest: str,
        compiler_digest: str,
        connection: Connection | None = None,
    ) -> WorldSettingProjectionSnapshotV1 | None:
        if connection is not None:
            return self._find_matching_in_transaction(
                connection,
                source_node_id=source_node_id,
                source_node_revision=source_node_revision,
                source_content_digest=source_content_digest,
                compiler_digest=compiler_digest,
            )
        try:
            with self._database.engine.connect() as reader:
                return self._find_matching_in_transaction(
                    reader,
                    source_node_id=source_node_id,
                    source_node_revision=source_node_revision,
                    source_content_digest=source_content_digest,
                    compiler_digest=compiler_digest,
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def get(
        self,
        projection_snapshot_id: str,
        *,
        connection: Connection | None = None,
    ) -> WorldSettingProjectionSnapshotV1:
        if connection is not None:
            return self._get_in_transaction(connection, projection_snapshot_id)
        try:
            with self._database.engine.connect() as reader:
                return self._get_in_transaction(reader, projection_snapshot_id)
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def find_for_source(
        self,
        *,
        source_node_id: str,
        source_node_revision: int,
        connection: Connection | None = None,
    ) -> tuple[WorldSettingProjectionSnapshotV1, ...]:
        if connection is not None:
            return self._find_for_source_in_transaction(
                connection,
                source_node_id=source_node_id,
                source_node_revision=source_node_revision,
            )
        try:
            with self._database.engine.connect() as reader:
                return self._find_for_source_in_transaction(
                    reader,
                    source_node_id=source_node_id,
                    source_node_revision=source_node_revision,
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def list_for_workflow(
        self,
        workflow_id: str,
        *,
        connection: Connection | None = None,
    ) -> tuple[WorldSettingProjectionSnapshotV1, ...]:
        if connection is not None:
            return self._list_for_workflow_in_transaction(connection, workflow_id)
        try:
            with self._database.engine.connect() as reader:
                return self._list_for_workflow_in_transaction(reader, workflow_id)
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def _insert_in_transaction(
        self,
        connection: Connection,
        snapshot: WorldSettingProjectionSnapshotV1,
    ) -> WorldSettingProjectionSnapshotV1:
        identity = and_(
            AgentCanvasWorldSettingProjectionRow.source_node_id == snapshot.source_node_id,
            AgentCanvasWorldSettingProjectionRow.source_node_revision
            == snapshot.source_node_revision,
            AgentCanvasWorldSettingProjectionRow.source_content_digest
            == snapshot.source_content_digest,
            AgentCanvasWorldSettingProjectionRow.compiler_digest == snapshot.compiler_digest,
        )
        row = (
            connection.execute(
                select(AgentCanvasWorldSettingProjectionRow).where(
                    or_(
                        AgentCanvasWorldSettingProjectionRow.projection_snapshot_id
                        == snapshot.projection_snapshot_id,
                        identity,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is not None:
            existing = _snapshot_from_row(row)
            if existing == snapshot:
                return existing
            raise _conflict_error()
        connection.execute(
            insert(AgentCanvasWorldSettingProjectionRow).values(**_snapshot_values(snapshot))
        )
        return snapshot

    def _find_matching_in_transaction(
        self,
        connection: Connection,
        *,
        source_node_id: str,
        source_node_revision: int,
        source_content_digest: str,
        compiler_digest: str,
    ) -> WorldSettingProjectionSnapshotV1 | None:
        row = (
            connection.execute(
                select(AgentCanvasWorldSettingProjectionRow).where(
                    AgentCanvasWorldSettingProjectionRow.source_node_id == source_node_id,
                    AgentCanvasWorldSettingProjectionRow.source_node_revision
                    == source_node_revision,
                    AgentCanvasWorldSettingProjectionRow.source_content_digest
                    == source_content_digest,
                    AgentCanvasWorldSettingProjectionRow.compiler_digest == compiler_digest,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _snapshot_from_row(row)

    def _get_in_transaction(
        self,
        connection: Connection,
        projection_snapshot_id: str,
    ) -> WorldSettingProjectionSnapshotV1:
        row = (
            connection.execute(
                select(AgentCanvasWorldSettingProjectionRow).where(
                    AgentCanvasWorldSettingProjectionRow.projection_snapshot_id
                    == projection_snapshot_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise _not_found_error()
        return _snapshot_from_row(row)

    def _find_for_source_in_transaction(
        self,
        connection: Connection,
        *,
        source_node_id: str,
        source_node_revision: int,
    ) -> tuple[WorldSettingProjectionSnapshotV1, ...]:
        rows = (
            connection.execute(
                select(AgentCanvasWorldSettingProjectionRow)
                .where(
                    AgentCanvasWorldSettingProjectionRow.source_node_id == source_node_id,
                    AgentCanvasWorldSettingProjectionRow.source_node_revision
                    == source_node_revision,
                )
                .order_by(
                    AgentCanvasWorldSettingProjectionRow.created_at.asc(),
                    AgentCanvasWorldSettingProjectionRow.projection_snapshot_id.asc(),
                )
            )
            .mappings()
            .all()
        )
        return tuple(_snapshot_from_row(row) for row in rows)

    def _list_for_workflow_in_transaction(
        self,
        connection: Connection,
        workflow_id: str,
    ) -> tuple[WorldSettingProjectionSnapshotV1, ...]:
        rows = (
            connection.execute(
                select(AgentCanvasWorldSettingProjectionRow)
                .where(AgentCanvasWorldSettingProjectionRow.workflow_id == workflow_id)
                .order_by(
                    AgentCanvasWorldSettingProjectionRow.created_at.asc(),
                    AgentCanvasWorldSettingProjectionRow.projection_snapshot_id.asc(),
                )
            )
            .mappings()
            .all()
        )
        return tuple(_snapshot_from_row(row) for row in rows)


def _snapshot_values(snapshot: WorldSettingProjectionSnapshotV1) -> dict[str, object]:
    return {
        "projection_snapshot_id": snapshot.projection_snapshot_id,
        "workflow_id": snapshot.workflow_id,
        "source_node_id": snapshot.source_node_id,
        "source_node_revision": snapshot.source_node_revision,
        "source_content_digest": snapshot.source_content_digest,
        "projection_contract_version": snapshot.projection_contract_version,
        "projection_prompt_digest": snapshot.projection_prompt_digest,
        "projection_skill_digest": snapshot.projection_skill_digest,
        "model_ref": snapshot.model_ref,
        "compiler_digest": snapshot.compiler_digest,
        "projection_mode": snapshot.projection_mode,
        "shared_projection_json": json.dumps(
            snapshot.shared_projection.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ),
        "role_projections_json": json.dumps(
            [item.model_dump(mode="json") for item in snapshot.role_projections],
            sort_keys=True,
            separators=(",", ":"),
        ),
        "projection_digest": snapshot.projection_digest,
        "warning_code": snapshot.warning_code,
        "created_at": snapshot.created_at.isoformat(),
    }


def _snapshot_from_row(row: RowMapping) -> WorldSettingProjectionSnapshotV1:
    return WorldSettingProjectionSnapshotV1.model_validate(
        {
            "projection_snapshot_id": row["projection_snapshot_id"],
            "workflow_id": row["workflow_id"],
            "source_node_id": row["source_node_id"],
            "source_node_revision": row["source_node_revision"],
            "source_content_digest": row["source_content_digest"],
            "projection_contract_version": row["projection_contract_version"],
            "projection_prompt_digest": row["projection_prompt_digest"],
            "projection_skill_digest": row["projection_skill_digest"],
            "model_ref": row["model_ref"],
            "compiler_digest": row["compiler_digest"],
            "projection_mode": row["projection_mode"],
            "shared_projection": json.loads(str(row["shared_projection_json"])),
            "role_projections": json.loads(str(row["role_projections_json"])),
            "projection_digest": row["projection_digest"],
            "warning_code": row["warning_code"],
            "created_at": row["created_at"],
        }
    )


def _conflict_error() -> V2PersistenceError:
    return V2PersistenceError(
        "projection_snapshot_conflict",
        "projection_snapshot_conflict: World Setting projection snapshot conflicts "
        "with immutable cache state.",
        stage="agent_canvas_world_setting_repository",
    )


def _not_found_error() -> V2PersistenceError:
    return V2PersistenceError(
        "projection_snapshot_not_found",
        "World Setting projection snapshot was not found.",
        stage="agent_canvas_world_setting_repository",
    )


def _persistence_error() -> V2PersistenceError:
    return V2PersistenceError(
        "world_setting_projection_persistence_unavailable",
        "World Setting projection persistence is unavailable.",
        stage="agent_canvas_world_setting_repository",
    )
