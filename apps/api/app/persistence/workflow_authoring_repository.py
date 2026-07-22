"""Atomic SQLite persistence for immutable V2 Workflow authoring revisions."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from typing import cast

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import WorkflowRevisionRow, WorkflowRow
from app.persistence.project_repository import ProjectRepository
from app.schemas.v2_persistence import DataMigrationCompletion, V2EventInsert
from app.schemas.workflow_v2_authoring import (
    CurrentWorkflowAuthoringState,
    WorkflowAuthoringDocumentV2,
    WorkflowProjectionState,
    WorkflowRevisionChangeSource,
    WorkflowRevisionCommitStatus,
    WorkflowRevisionCommitRequest,
    WorkflowRevisionCommitResult,
    WorkflowRevisionPage,
    WorkflowRevisionV2Detail,
    WorkflowRevisionV2Summary,
)
from app.schemas.workflow_v2_projects import ProjectCreate
from app.services.v2_workflow_authoring_projector import WorkflowAuthoringProjector


class WorkflowAuthoringRepository:
    """Own immutable revision transactions without provider or filesystem I/O."""

    def __init__(
        self,
        database: V2Database,
        project_repository: ProjectRepository,
        event_repository: EventRepository,
    ) -> None:
        if project_repository.database is not database or event_repository.database is not database:
            raise ValueError("V2 authoring repositories must share one V2Database instance.")
        self._database = database
        self._projects = project_repository
        self._events = event_repository

    @property
    def database(self) -> V2Database:
        """Return the shared database identity for boundary validation."""

        return self._database

    @property
    def event_repository(self) -> EventRepository:
        """Expose the shared event repository for import marker checks only."""

        return self._events

    def create_initial(
        self,
        *,
        project: ProjectCreate,
        workflow_id: str,
        document: WorkflowAuthoringDocumentV2,
        content_hash: str,
        change_source: WorkflowRevisionChangeSource,
        source_execution_id: str | None = None,
        migration_completion: DataMigrationCompletion | None = None,
    ) -> WorkflowRevisionCommitResult:
        """Atomically create Project, Workflow, Revision 1, and its event."""

        if document.workflow_id != workflow_id:
            raise _invalid_document_error()
        now = _utc_now()
        revision_id = _revision_id()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    self._projects.insert_in_transaction(connection, project)
                    connection.execute(
                        insert(WorkflowRow).values(
                            workflow_id=workflow_id,
                            project_id=project.project_id,
                            current_revision_id=None,
                            semantic_revision_no=0,
                            state_version=1,
                            projection_state="dirty",
                            projection_revision_no=None,
                            projection_error_code=None,
                            projection_error_summary=None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    self._insert_revision(
                        connection,
                        revision_id=revision_id,
                        workflow_id=workflow_id,
                        revision_no=1,
                        state_version=1,
                        document=document,
                        content_hash=content_hash,
                        change_source=change_source,
                        restored_from_revision_no=None,
                        source_execution_id=source_execution_id,
                        created_at=now,
                    )
                    connection.execute(
                        update(WorkflowRow)
                        .where(WorkflowRow.workflow_id == workflow_id)
                        .values(
                            current_revision_id=revision_id,
                            semantic_revision_no=1,
                            updated_at=now,
                        )
                    )
                    self._append_revision_event(
                        connection,
                        project_id=project.project_id,
                        workflow_id=workflow_id,
                        revision_id=revision_id,
                        revision_no=1,
                        state_version=1,
                        change_source=change_source,
                        restored_from_revision_no=None,
                        source_execution_id=source_execution_id,
                        created_at=now,
                    )
                    if migration_completion is not None:
                        self._events.complete_migration_in_transaction(
                            connection,
                            migration_completion.model_copy(
                                update={
                                    "details": {
                                        **migration_completion.details,
                                        "revision_id": revision_id,
                                    }
                                }
                            ),
                        )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return WorkflowRevisionCommitResult(
            status="committed",
            project_id=project.project_id,
            workflow_id=workflow_id,
            revision_id=revision_id,
            revision_no=1,
            state_version=1,
            content_hash=content_hash,
            change_source=change_source,
            projection_state="dirty",
        )

    def load_current(self, workflow_id: str) -> CurrentWorkflowAuthoringState:
        """Read the current immutable authoring revision and projection diagnostics."""

        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(_current_state_select(workflow_id)).mappings().one_or_none()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        if row is None:
            raise _workflow_not_found_error()
        return _current_state_from_row(row)

    def list_revisions(
        self,
        workflow_id: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> WorkflowRevisionPage:
        """List immutable revision summaries newest first with bounded pagination."""

        if not 1 <= limit <= 100:
            raise V2PersistenceError(
                "workflow_revision_page_invalid",
                "Workflow revision page bounds are invalid.",
                stage="workflow_authoring_repository",
            )
        cursor_revision_no = _decode_revision_cursor(cursor) if cursor is not None else None
        try:
            with self._database.engine.connect() as connection:
                query = _revision_select().where(WorkflowRevisionRow.workflow_id == workflow_id)
                if cursor_revision_no is not None:
                    query = query.where(WorkflowRevisionRow.revision_no < cursor_revision_no)
                rows = (
                    connection.execute(
                        query.order_by(WorkflowRevisionRow.revision_no.desc()).limit(limit + 1)
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        if not rows:
            self.load_current(workflow_id)
        items = tuple(_revision_summary_from_row(row) for row in rows[:limit])
        return WorkflowRevisionPage(
            items=items,
            next_cursor=_encode_revision_cursor(items[-1].revision_no)
            if len(rows) > limit
            else None,
        )

    def get_revision(self, workflow_id: str, revision_no: int) -> WorkflowRevisionV2Detail:
        """Return a validated immutable document by its Workflow-local revision number."""

        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        _revision_select().where(
                            WorkflowRevisionRow.workflow_id == workflow_id,
                            WorkflowRevisionRow.revision_no == revision_no,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        if row is None:
            raise V2PersistenceError(
                "workflow_revision_not_found",
                "Workflow revision was not found.",
                stage="workflow_authoring_repository",
            )
        return _revision_detail_from_row(row)

    def commit_revision(
        self, request: WorkflowRevisionCommitRequest
    ) -> WorkflowRevisionCommitResult:
        """Commit one semantic revision after a same-transaction version check."""

        return self._commit_document(
            workflow_id=request.workflow_id,
            expected_state_version=request.expected_state_version,
            document=request.document,
            content_hash=request.content_hash,
            change_source=request.change_source,
            source_execution_id=request.source_execution_id,
            restored_from_revision_no=request.restored_from_revision_no,
            project_id=request.project_id,
            allow_no_change=True,
        )

    def restore_revision(
        self,
        workflow_id: str,
        revision_no: int,
        expected_state_version: int,
    ) -> WorkflowRevisionCommitResult:
        """Restore historical authoring into the next immutable revision."""

        historical = self.get_revision(workflow_id, revision_no)
        current = self.load_current(workflow_id)
        return self._commit_document(
            workflow_id=workflow_id,
            expected_state_version=expected_state_version,
            document=historical.document,
            content_hash=historical.content_hash,
            change_source="restore",
            source_execution_id=None,
            restored_from_revision_no=revision_no,
            project_id=current.project_id,
            allow_no_change=False,
        )

    def mark_projection_clean(self, workflow_id: str, revision_no: int) -> None:
        """Mark the current projection clean without creating a semantic revision."""

        self._set_projection_state(
            workflow_id,
            state="clean",
            revision_no=revision_no,
            error_code=None,
            error_summary=None,
        )

    def mark_projection_dirty(
        self,
        workflow_id: str,
        *,
        error_code: str,
        error_summary: str,
    ) -> None:
        """Persist bounded projection diagnostics without changing revision identity."""

        self._set_projection_state(
            workflow_id,
            state="dirty",
            revision_no=None,
            error_code=error_code[:128],
            error_summary=error_summary[:512],
        )

    def _commit_document(
        self,
        *,
        workflow_id: str,
        expected_state_version: int,
        document: WorkflowAuthoringDocumentV2,
        content_hash: str,
        change_source: WorkflowRevisionChangeSource,
        source_execution_id: str | None,
        restored_from_revision_no: int | None,
        project_id: str,
        allow_no_change: bool,
    ) -> WorkflowRevisionCommitResult:
        if document.workflow_id != workflow_id:
            raise _invalid_document_error()
        now = _utc_now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    current = _workflow_row_for_update(connection, workflow_id)
                    if str(current["project_id"]) != project_id:
                        raise _workflow_not_found_error()
                    _require_state_version(current, expected_state_version)
                    current_revision = _current_revision_for_workflow(connection, current)
                    if source_execution_id is not None:
                        existing = _revision_by_execution(
                            connection, workflow_id, source_execution_id
                        )
                        if existing is not None:
                            connection.commit()
                            return _commit_result_from_row(
                                existing,
                                project_id=project_id,
                                status="already_committed",
                                projection_state=str(current["projection_state"]),
                            )
                    if allow_no_change and str(current_revision["content_hash"]) == content_hash:
                        connection.commit()
                        return _commit_result_from_row(
                            current_revision,
                            project_id=project_id,
                            status="no_change",
                            projection_state=str(current["projection_state"]),
                        )
                    revision_no = int(current["semantic_revision_no"]) + 1
                    state_version = int(current["state_version"]) + 1
                    revision_id = _revision_id()
                    self._insert_revision(
                        connection,
                        revision_id=revision_id,
                        workflow_id=workflow_id,
                        revision_no=revision_no,
                        state_version=state_version,
                        document=document,
                        content_hash=content_hash,
                        change_source=change_source,
                        restored_from_revision_no=restored_from_revision_no,
                        source_execution_id=source_execution_id,
                        created_at=now,
                    )
                    connection.execute(
                        update(WorkflowRow)
                        .where(WorkflowRow.workflow_id == workflow_id)
                        .values(
                            current_revision_id=revision_id,
                            semantic_revision_no=revision_no,
                            state_version=state_version,
                            projection_state="dirty",
                            projection_revision_no=None,
                            projection_error_code=None,
                            projection_error_summary=None,
                            updated_at=now,
                        )
                    )
                    self._append_revision_event(
                        connection,
                        project_id=project_id,
                        workflow_id=workflow_id,
                        revision_id=revision_id,
                        revision_no=revision_no,
                        state_version=state_version,
                        change_source=change_source,
                        restored_from_revision_no=restored_from_revision_no,
                        source_execution_id=source_execution_id,
                        created_at=now,
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _persistence_error() from error
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return WorkflowRevisionCommitResult(
            status="committed",
            project_id=project_id,
            workflow_id=workflow_id,
            revision_id=revision_id,
            revision_no=revision_no,
            state_version=state_version,
            content_hash=content_hash,
            change_source=change_source,
            projection_state="dirty",
        )

    @staticmethod
    def _insert_revision(
        connection: Connection,
        *,
        revision_id: str,
        workflow_id: str,
        revision_no: int,
        state_version: int,
        document: WorkflowAuthoringDocumentV2,
        content_hash: str,
        change_source: WorkflowRevisionChangeSource,
        restored_from_revision_no: int | None,
        source_execution_id: str | None,
        created_at: str,
    ) -> None:
        connection.execute(
            insert(WorkflowRevisionRow).values(
                revision_id=revision_id,
                workflow_id=workflow_id,
                revision_no=revision_no,
                state_version=state_version,
                document_schema_version=document.document_schema_version,
                document_json=WorkflowAuthoringProjector.canonical_bytes(document).decode("utf-8"),
                content_hash=content_hash,
                change_source=change_source,
                restored_from_revision_no=restored_from_revision_no,
                source_execution_id=source_execution_id,
                created_at=created_at,
            )
        )

    def _append_revision_event(
        self,
        connection: Connection,
        *,
        project_id: str,
        workflow_id: str,
        revision_id: str,
        revision_no: int,
        state_version: int,
        change_source: WorkflowRevisionChangeSource,
        restored_from_revision_no: int | None,
        source_execution_id: str | None,
        created_at: str,
    ) -> None:
        self._events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=workflow_id,
                event_type="workflow_revision_created",
                execution_id=source_execution_id,
                created_at=created_at,
                payload={
                    "project_id": project_id,
                    "workflow_id": workflow_id,
                    "revision_id": revision_id,
                    "revision_no": revision_no,
                    "state_version": state_version,
                    "change_source": change_source,
                    "restored_from_revision_no": restored_from_revision_no,
                    "source_execution_id": source_execution_id,
                    "refresh": ["workflow", "project"],
                },
            ),
        )

    def _set_projection_state(
        self,
        workflow_id: str,
        *,
        state: WorkflowProjectionState,
        revision_no: int | None,
        error_code: str | None,
        error_summary: str | None,
    ) -> None:
        try:
            with self._database.engine.begin() as connection:
                result = connection.execute(
                    update(WorkflowRow)
                    .where(WorkflowRow.workflow_id == workflow_id)
                    .values(
                        projection_state=state,
                        projection_revision_no=revision_no,
                        projection_error_code=error_code,
                        projection_error_summary=error_summary,
                    )
                )
                if result.rowcount != 1:
                    raise _workflow_not_found_error()
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error


def _current_state_select(workflow_id: str):
    return (
        select(
            WorkflowRow.project_id,
            WorkflowRow.workflow_id,
            WorkflowRow.semantic_revision_no,
            WorkflowRow.state_version,
            WorkflowRow.created_at.label("workflow_created_at"),
            WorkflowRow.updated_at.label("workflow_updated_at"),
            WorkflowRow.projection_state,
            WorkflowRow.projection_revision_no,
            WorkflowRow.projection_error_code,
            WorkflowRow.projection_error_summary,
            WorkflowRevisionRow.revision_id,
            WorkflowRevisionRow.revision_no,
            WorkflowRevisionRow.document_json,
            WorkflowRevisionRow.content_hash,
            WorkflowRevisionRow.change_source,
            WorkflowRevisionRow.restored_from_revision_no,
            WorkflowRevisionRow.source_execution_id,
            WorkflowRevisionRow.created_at.label("revision_created_at"),
        )
        .join(
            WorkflowRevisionRow,
            WorkflowRow.current_revision_id == WorkflowRevisionRow.revision_id,
        )
        .where(WorkflowRow.workflow_id == workflow_id)
    )


def _revision_select():
    return select(
        WorkflowRevisionRow.revision_id,
        WorkflowRevisionRow.workflow_id,
        WorkflowRevisionRow.revision_no,
        WorkflowRevisionRow.state_version,
        WorkflowRevisionRow.document_json,
        WorkflowRevisionRow.content_hash,
        WorkflowRevisionRow.change_source,
        WorkflowRevisionRow.restored_from_revision_no,
        WorkflowRevisionRow.source_execution_id,
        WorkflowRevisionRow.created_at,
    )


def _workflow_row_for_update(connection: Connection, workflow_id: str) -> RowMapping:
    row = (
        connection.execute(
            select(
                WorkflowRow.workflow_id,
                WorkflowRow.project_id,
                WorkflowRow.current_revision_id,
                WorkflowRow.semantic_revision_no,
                WorkflowRow.state_version,
                WorkflowRow.projection_state,
            ).where(WorkflowRow.workflow_id == workflow_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["current_revision_id"] is None:
        raise _workflow_not_found_error()
    return row


def _current_revision_for_workflow(connection: Connection, workflow: RowMapping) -> RowMapping:
    row = (
        connection.execute(
            _revision_select().where(
                WorkflowRevisionRow.revision_id == workflow["current_revision_id"]
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or str(row["workflow_id"]) != str(workflow["workflow_id"]):
        raise _persistence_error()
    return row


def _revision_by_execution(
    connection: Connection,
    workflow_id: str,
    source_execution_id: str,
) -> RowMapping | None:
    return (
        connection.execute(
            _revision_select().where(
                WorkflowRevisionRow.workflow_id == workflow_id,
                WorkflowRevisionRow.source_execution_id == source_execution_id,
            )
        )
        .mappings()
        .one_or_none()
    )


def _current_state_from_row(row: RowMapping) -> CurrentWorkflowAuthoringState:
    detail = WorkflowRevisionV2Detail(
        revision_id=str(row["revision_id"]),
        workflow_id=str(row["workflow_id"]),
        revision_no=int(row["revision_no"]),
        state_version=int(row["state_version"]),
        content_hash=str(row["content_hash"]),
        change_source=str(row["change_source"]),
        restored_from_revision_no=_optional_int(row["restored_from_revision_no"]),
        source_execution_id=_optional_string(row["source_execution_id"]),
        created_at=str(row["revision_created_at"]),
        document=WorkflowAuthoringDocumentV2.model_validate_json(str(row["document_json"])),
    )
    return CurrentWorkflowAuthoringState(
        project_id=str(row["project_id"]),
        workflow_id=str(row["workflow_id"]),
        semantic_revision_no=int(row["semantic_revision_no"]),
        state_version=int(row["state_version"]),
        created_at=str(row["workflow_created_at"]),
        updated_at=str(row["workflow_updated_at"]),
        projection_state=str(row["projection_state"]),
        projection_revision_no=_optional_int(row["projection_revision_no"]),
        projection_error_code=_optional_string(row["projection_error_code"]),
        projection_error_summary=_optional_string(row["projection_error_summary"]),
        revision=detail,
    )


def _revision_summary_from_row(row: RowMapping) -> WorkflowRevisionV2Summary:
    return WorkflowRevisionV2Summary(
        revision_id=str(row["revision_id"]),
        workflow_id=str(row["workflow_id"]),
        revision_no=int(row["revision_no"]),
        state_version=int(row["state_version"]),
        content_hash=str(row["content_hash"]),
        change_source=str(row["change_source"]),
        restored_from_revision_no=_optional_int(row["restored_from_revision_no"]),
        source_execution_id=_optional_string(row["source_execution_id"]),
        created_at=str(row["created_at"]),
    )


def _revision_detail_from_row(row: RowMapping) -> WorkflowRevisionV2Detail:
    return WorkflowRevisionV2Detail(
        **_revision_summary_from_row(row).model_dump(),
        document=WorkflowAuthoringDocumentV2.model_validate_json(str(row["document_json"])),
    )


def _commit_result_from_row(
    row: RowMapping,
    *,
    project_id: str,
    status: WorkflowRevisionCommitStatus,
    projection_state: WorkflowProjectionState,
) -> WorkflowRevisionCommitResult:
    return WorkflowRevisionCommitResult(
        status=status,
        project_id=project_id,
        workflow_id=str(row["workflow_id"]),
        revision_id=str(row["revision_id"]),
        revision_no=int(row["revision_no"]),
        state_version=int(row["state_version"]),
        content_hash=str(row["content_hash"]),
        change_source=cast(WorkflowRevisionChangeSource, str(row["change_source"])),
        projection_state=projection_state,
    )


def _require_state_version(row: RowMapping, expected_state_version: int) -> None:
    if int(row["state_version"]) != expected_state_version:
        raise V2PersistenceError(
            "workflow_state_conflict",
            "Workflow state has changed.",
            stage="workflow_authoring_repository",
        )


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)


def _encode_revision_cursor(revision_no: int) -> str:
    return base64.urlsafe_b64encode(str(revision_no).encode("ascii")).decode("ascii")


def _decode_revision_cursor(cursor: str) -> int:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        revision_no = int(base64.urlsafe_b64decode(padded).decode("ascii"))
    except (UnicodeDecodeError, ValueError) as error:
        raise V2PersistenceError(
            "workflow_revision_cursor_invalid",
            "Workflow revision cursor is invalid.",
            stage="workflow_authoring_repository",
        ) from error
    if revision_no < 1:
        raise V2PersistenceError(
            "workflow_revision_cursor_invalid",
            "Workflow revision cursor is invalid.",
            stage="workflow_authoring_repository",
        )
    return revision_no


def _revision_id() -> str:
    return f"wfrev_{uuid.uuid4().hex[:12]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _invalid_document_error() -> V2PersistenceError:
    return V2PersistenceError(
        "workflow_authoring_document_invalid",
        "Workflow authoring document does not match its Workflow.",
        stage="workflow_authoring_repository",
    )


def _workflow_not_found_error() -> V2PersistenceError:
    return V2PersistenceError(
        "workflow_not_found",
        "Workflow was not found.",
        stage="workflow_authoring_repository",
    )


def _persistence_error() -> V2PersistenceError:
    return V2PersistenceError(
        "v2_workflow_authoring_persistence_failed",
        "V2 Workflow authoring persistence failed.",
        stage="workflow_authoring_repository",
    )
