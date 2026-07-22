"""Focused SQLite persistence for V2 Project metadata."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import cast

from sqlalchemy import and_, insert, or_, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.models import ProjectRow
from app.schemas.workflow_v2_projects import (
    ProjectCreate,
    ProjectRecord,
    ProjectRecordPage,
    ProjectStatusV2,
)


class ProjectRepository:
    """Own only Project SQL; authoring transactions own cross-table commits."""

    def __init__(self, database: V2Database) -> None:
        self._database = database

    @property
    def database(self) -> V2Database:
        """Return the database identity used to enforce transaction ownership."""

        return self._database

    def insert(self, project: ProjectCreate) -> ProjectRecord:
        """Insert one Project through a short Project-only transaction."""

        try:
            with self._database.engine.begin() as connection:
                self.insert_in_transaction(connection, project)
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return self.get(project.project_id)

    def insert_in_transaction(self, connection: Connection, project: ProjectCreate) -> None:
        """Insert without committing a caller-owned transaction."""

        connection.execute(
            insert(ProjectRow).values(
                project_id=project.project_id,
                name=project.name,
                description=project.description,
                status=project.status,
                is_favorite=project.is_favorite,
                cover_asset_id=project.cover_asset_id,
                project_version=1,
                created_at=project.created_at,
                updated_at=project.updated_at,
                deleted_at=None,
            )
        )

    def get(self, project_id: str) -> ProjectRecord:
        """Return one Project or raise a stable not-found error."""

        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(_project_select().where(ProjectRow.project_id == project_id))
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        if row is None:
            raise _not_found_error()
        return _project_from_row(row)

    def list(
        self,
        *,
        status: ProjectStatusV2 = "active",
        limit: int = 50,
        cursor: str | None = None,
    ) -> ProjectRecordPage:
        """List Projects in a bounded deterministic order."""

        if not 1 <= limit <= 100:
            raise V2PersistenceError(
                "project_page_invalid",
                "Project page bounds are invalid.",
                stage="project_repository",
            )
        cursor_values = _decode_cursor(cursor) if cursor is not None else None
        try:
            with self._database.engine.connect() as connection:
                query = _project_select().where(ProjectRow.status == status)
                if cursor_values is not None:
                    cursor_updated_at, cursor_project_id = cursor_values
                    query = query.where(
                        or_(
                            ProjectRow.updated_at < cursor_updated_at,
                            and_(
                                ProjectRow.updated_at == cursor_updated_at,
                                ProjectRow.project_id > cursor_project_id,
                            ),
                        )
                    )
                rows = (
                    connection.execute(
                        query.order_by(
                            ProjectRow.updated_at.desc(), ProjectRow.project_id.asc()
                        ).limit(limit + 1)
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        items = tuple(_project_from_row(row) for row in rows[:limit])
        next_cursor = None
        if len(rows) > limit:
            last = items[-1]
            next_cursor = _encode_cursor(last.updated_at, last.project_id)
        return ProjectRecordPage(items=items, next_cursor=next_cursor)

    def update(
        self,
        project_id: str,
        *,
        expected_version: int,
        changes: dict[str, object],
    ) -> ProjectRecord:
        """Apply a validated Project metadata edit with optimistic concurrency."""

        allowed_keys = {"name", "description", "is_favorite", "cover_asset_id", "status"}
        if not changes or not set(changes) <= allowed_keys:
            raise V2PersistenceError(
                "project_update_invalid",
                "Project changes are invalid.",
                stage="project_repository",
            )
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    current = _get_project_in_transaction(connection, project_id)
                    _require_project_version(current, expected_version)
                    values = {
                        key: value
                        for key, value in changes.items()
                        if getattr(_project_from_row(current), key) != value
                    }
                    if values:
                        values["project_version"] = int(current["project_version"]) + 1
                        values["updated_at"] = _utc_now()
                        connection.execute(
                            update(ProjectRow)
                            .where(ProjectRow.project_id == project_id)
                            .values(**values)
                        )
                        current = _get_project_in_transaction(connection, project_id)
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return _project_from_row(current)

    def trash(self, project_id: str, *, expected_version: int) -> ProjectRecord:
        """Soft-delete one Project without touching Workflow or asset records."""

        return self._change_lifecycle(
            project_id,
            expected_version=expected_version,
            expected_status=None,
            status="trashed",
            deleted=True,
        )

    def restore(self, project_id: str, *, expected_version: int) -> ProjectRecord:
        """Restore one trashed Project to active state."""

        return self._change_lifecycle(
            project_id,
            expected_version=expected_version,
            expected_status="trashed",
            status="active",
            deleted=False,
        )

    def _change_lifecycle(
        self,
        project_id: str,
        *,
        expected_version: int,
        expected_status: ProjectStatusV2 | None,
        status: ProjectStatusV2,
        deleted: bool,
    ) -> ProjectRecord:
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    current = _get_project_in_transaction(connection, project_id)
                    _require_project_version(current, expected_version)
                    current_status = str(current["status"])
                    if expected_status is not None and current_status != expected_status:
                        raise V2PersistenceError(
                            "project_not_trashed",
                            "Project is not trashed.",
                            stage="project_repository",
                        )
                    if current_status != status:
                        now = _utc_now()
                        connection.execute(
                            update(ProjectRow)
                            .where(ProjectRow.project_id == project_id)
                            .values(
                                status=status,
                                deleted_at=now if deleted else None,
                                project_version=int(current["project_version"]) + 1,
                                updated_at=now,
                            )
                        )
                        current = _get_project_in_transaction(connection, project_id)
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return _project_from_row(current)


def _project_select():
    return select(
        ProjectRow.project_id,
        ProjectRow.name,
        ProjectRow.description,
        ProjectRow.status,
        ProjectRow.is_favorite,
        ProjectRow.cover_asset_id,
        ProjectRow.project_version,
        ProjectRow.created_at,
        ProjectRow.updated_at,
        ProjectRow.deleted_at,
    )


def _get_project_in_transaction(connection: Connection, project_id: str) -> RowMapping:
    row = (
        connection.execute(_project_select().where(ProjectRow.project_id == project_id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _not_found_error()
    return row


def _project_from_row(row: RowMapping) -> ProjectRecord:
    return ProjectRecord(
        project_id=str(row["project_id"]),
        name=str(row["name"]),
        description=str(row["description"]),
        status=cast(ProjectStatusV2, str(row["status"])),
        is_favorite=bool(row["is_favorite"]),
        cover_asset_id=_optional_string(row["cover_asset_id"]),
        project_version=int(row["project_version"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        deleted_at=_optional_string(row["deleted_at"]),
    )


def _require_project_version(row: RowMapping, expected_version: int) -> None:
    if int(row["project_version"]) != expected_version:
        raise V2PersistenceError(
            "project_state_conflict",
            "Project state has changed.",
            stage="project_repository",
        )


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _encode_cursor(updated_at: str, project_id: str) -> str:
    payload = json.dumps([updated_at, project_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(isinstance(item, str) and item for item in value)
        ):
            raise ValueError
        return value[0], value[1]
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise V2PersistenceError(
            "project_cursor_invalid",
            "Project cursor is invalid.",
            stage="project_repository",
        ) from error


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _not_found_error() -> V2PersistenceError:
    return V2PersistenceError(
        "project_not_found", "Project was not found.", stage="project_repository"
    )


def _persistence_error() -> V2PersistenceError:
    return V2PersistenceError(
        "v2_project_persistence_failed",
        "V2 Project persistence failed.",
        stage="project_repository",
    )
