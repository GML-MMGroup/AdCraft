"""SQLite persistence for workflow-scoped Agent Canvas execution settings."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import AgentCanvasExecutionSettingsRow, WorkflowRow
from app.schemas.agent_canvas_execution_settings import (
    AgentExecutionSettingsV2,
    MediaExecutionModeV2,
)
from app.schemas.v2_persistence import V2EventInsert


class AgentCanvasExecutionSettingsRepository:
    """Own lazy settings creation and optimistic updates."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Execution settings and events must use the same database.")
        self._database = database
        self._events = events

    @property
    def database(self) -> V2Database:
        return self._database

    def get(self, workflow_id: str) -> AgentExecutionSettingsV2 | None:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasExecutionSettingsRow).where(
                            AgentCanvasExecutionSettingsRow.workflow_id == workflow_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return _settings(row) if row is not None else None

    def is_structured_workflow(self, workflow_id: str) -> bool:
        """Return whether the identifier belongs to a non-Agent-Canvas workflow."""

        try:
            with self._database.engine.connect() as connection:
                return (
                    connection.execute(
                        select(WorkflowRow.workflow_id).where(
                            WorkflowRow.workflow_id == workflow_id
                        )
                    ).scalar_one_or_none()
                    is not None
                )
        except SQLAlchemyError as error:
            raise _unavailable_error() from error

    def get_or_create_manual(
        self,
        workflow_id: str,
        *,
        now: datetime,
    ) -> AgentExecutionSettingsV2:
        existing = self.get(workflow_id)
        if existing is not None:
            return existing
        timestamp = _iso(now)
        try:
            with self._database.engine.begin() as connection:
                connection.execute(
                    insert(AgentCanvasExecutionSettingsRow).values(
                        workflow_id=workflow_id,
                        media_execution_mode="manual",
                        revision=1,
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
        except IntegrityError:
            replay = self.get(workflow_id)
            if replay is not None:
                return replay
            raise
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        created = self.get(workflow_id)
        if created is None:
            raise _unavailable_error()
        return created

    def update(
        self,
        workflow_id: str,
        *,
        media_execution_mode: MediaExecutionModeV2,
        expected_revision: int,
        now: datetime,
    ) -> AgentExecutionSettingsV2:
        timestamp = _iso(now)
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    current = (
                        connection.execute(
                            select(AgentCanvasExecutionSettingsRow).where(
                                AgentCanvasExecutionSettingsRow.workflow_id == workflow_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if current is None:
                        raise V2PersistenceError(
                            "agent_settings_not_found",
                            "Agent execution settings were not found.",
                            stage="agent_canvas_execution_settings",
                        )
                    current_revision = int(current["revision"])
                    if current_revision != expected_revision:
                        raise _revision_conflict(current_revision)
                    next_revision = current_revision + 1
                    result = connection.execute(
                        update(AgentCanvasExecutionSettingsRow)
                        .where(
                            AgentCanvasExecutionSettingsRow.workflow_id == workflow_id,
                            AgentCanvasExecutionSettingsRow.revision == expected_revision,
                        )
                        .values(
                            media_execution_mode=media_execution_mode,
                            revision=next_revision,
                            updated_at=timestamp,
                        )
                    )
                    if result.rowcount != 1:
                        raise _revision_conflict(current_revision)
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            event_type="agent_settings_updated",
                            transition_key=(f"agent-settings:{workflow_id}:{next_revision}"),
                            created_at=timestamp,
                            payload={
                                "media_execution_mode": media_execution_mode,
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
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        updated = self.get(workflow_id)
        if updated is None:
            raise _unavailable_error()
        return updated


def _settings(row: object) -> AgentExecutionSettingsV2:
    return AgentExecutionSettingsV2.model_validate(row)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Execution settings timestamps must include a timezone.")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


def _revision_conflict(current_revision: int) -> V2PersistenceError:
    return V2PersistenceError(
        "agent_settings_revision_conflict",
        "Agent execution settings changed before this update.",
        stage="agent_canvas_execution_settings",
        details={"current_revision": current_revision},
    )


def _unavailable_error() -> V2PersistenceError:
    return V2PersistenceError(
        "agent_settings_unavailable",
        "Agent execution settings storage is unavailable.",
        stage="agent_canvas_execution_settings",
    )
