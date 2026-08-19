"""Durable automatic selected-node Run command persistence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from datetime import datetime, timezone

from sqlalchemy import and_, insert, or_, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import AgentCanvasAutomaticRunCommandRow
from app.schemas.agent_canvas import CanvasNodeErrorV2
from app.schemas.agent_canvas_execution_settings import AutomaticRunCommandV2
from app.schemas.v2_persistence import V2EventInsert


@dataclass(frozen=True)
class ClaimedAutomaticRun:
    command: AutomaticRunCommandV2
    lease_generation: int


class AgentCanvasAutomaticRunRepository:
    """Own automatic Run identity and persistence."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Automatic Run commands and events must share one database.")
        self._database = database
        self._events = events

    def enqueue(
        self,
        *,
        workflow_id: str,
        source_action_id: str,
        node_id: str,
        now: datetime,
        max_attempts: int = 3,
    ) -> AutomaticRunCommandV2:
        command_id = _command_id(workflow_id, source_action_id, node_id)
        try:
            with self._database.engine.begin() as connection:
                return self.enqueue_in_transaction(
                    connection,
                    workflow_id=workflow_id,
                    source_action_id=source_action_id,
                    node_id=node_id,
                    now=now,
                    max_attempts=max_attempts,
                )
        except IntegrityError:
            existing = self.get(command_id)
            if existing is not None:
                return existing
            raise
        except SQLAlchemyError as error:
            raise _unavailable_error() from error

    def enqueue_in_transaction(
        self,
        connection: Connection,
        *,
        workflow_id: str,
        source_action_id: str,
        node_id: str,
        now: datetime,
        max_attempts: int = 3,
    ) -> AutomaticRunCommandV2:
        """Insert one command into its owning publication transaction."""

        if max_attempts < 1:
            raise V2PersistenceError(
                "agent_auto_run_attempts_invalid",
                "Automatic Run maximum attempts must be positive.",
                stage="agent_canvas_auto_run",
            )
        timestamp = _iso(now)
        command_id = _command_id(workflow_id, source_action_id, node_id)
        existing = _select_identity(
            connection,
            workflow_id=workflow_id,
            source_action_id=source_action_id,
            node_id=node_id,
        )
        if existing is not None:
            return _command(existing)
        values = {
            "command_id": command_id,
            "workflow_id": workflow_id,
            "source_action_id": source_action_id,
            "node_id": node_id,
            "command_kind": "agent_auto_generate",
            "state": "pending",
            "execution_id": None,
            "attempt_count": 0,
            "max_attempts": max_attempts,
            "next_attempt_at": timestamp,
            "lease_owner": None,
            "lease_generation": 0,
            "lease_expires_at": None,
            "last_error_code": None,
            "last_error_message": None,
            "last_error_retryable": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        connection.execute(insert(AgentCanvasAutomaticRunCommandRow).values(**values))
        self._events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=workflow_id,
                node_id=node_id,
                action_id=source_action_id,
                event_type="agent_auto_run_requested",
                transition_key=f"agent-auto-run:{command_id}:requested",
                created_at=timestamp,
                payload={
                    "action_id": source_action_id,
                    "node_id": node_id,
                    "command_id": command_id,
                },
            ),
        )
        return _command(values)

    def get(self, command_id: str) -> AutomaticRunCommandV2 | None:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasAutomaticRunCommandRow).where(
                            AgentCanvasAutomaticRunCommandRow.command_id == command_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return _command(row) if row is not None else None

    def list_for_workflow(self, workflow_id: str) -> tuple[AutomaticRunCommandV2, ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasAutomaticRunCommandRow)
                        .where(AgentCanvasAutomaticRunCommandRow.workflow_id == workflow_id)
                        .order_by(
                            AgentCanvasAutomaticRunCommandRow.created_at.asc(),
                            AgentCanvasAutomaticRunCommandRow.command_id.asc(),
                        )
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return tuple(_command(row) for row in rows)

    def claim_due(
        self,
        *,
        worker_id: str,
        now: datetime,
        batch_limit: int,
        lease_duration: timedelta,
    ) -> tuple[ClaimedAutomaticRun, ...]:
        if batch_limit < 1 or lease_duration <= timedelta(0):
            raise V2PersistenceError(
                "agent_auto_run_claim_invalid",
                "Automatic Run claim settings are invalid.",
                stage="agent_canvas_auto_run",
            )
        now_value = _iso(now)
        lease_expires_at = _iso(_utc(now) + lease_duration)
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    rows = (
                        connection.execute(
                            select(AgentCanvasAutomaticRunCommandRow)
                            .where(
                                or_(
                                    and_(
                                        AgentCanvasAutomaticRunCommandRow.state == "pending",
                                        AgentCanvasAutomaticRunCommandRow.next_attempt_at
                                        <= now_value,
                                    ),
                                    and_(
                                        AgentCanvasAutomaticRunCommandRow.state == "claimed",
                                        AgentCanvasAutomaticRunCommandRow.lease_expires_at
                                        <= now_value,
                                    ),
                                )
                            )
                            .order_by(
                                AgentCanvasAutomaticRunCommandRow.next_attempt_at.asc(),
                                AgentCanvasAutomaticRunCommandRow.created_at.asc(),
                                AgentCanvasAutomaticRunCommandRow.command_id.asc(),
                            )
                            .limit(batch_limit)
                        )
                        .mappings()
                        .all()
                    )
                    claimed: list[ClaimedAutomaticRun] = []
                    for row in rows:
                        generation = int(row["lease_generation"]) + 1
                        result = connection.execute(
                            update(AgentCanvasAutomaticRunCommandRow)
                            .where(
                                AgentCanvasAutomaticRunCommandRow.command_id == row["command_id"],
                                AgentCanvasAutomaticRunCommandRow.state == row["state"],
                                AgentCanvasAutomaticRunCommandRow.lease_generation
                                == row["lease_generation"],
                            )
                            .values(
                                state="claimed",
                                lease_owner=worker_id,
                                lease_generation=generation,
                                lease_expires_at=lease_expires_at,
                                updated_at=now_value,
                            )
                        )
                        if result.rowcount != 1:
                            continue
                        claimed_row = {
                            **row,
                            "state": "claimed",
                            "lease_owner": worker_id,
                            "lease_generation": generation,
                            "lease_expires_at": lease_expires_at,
                            "updated_at": now_value,
                        }
                        claimed.append(
                            ClaimedAutomaticRun(
                                command=_command(claimed_row),
                                lease_generation=generation,
                            )
                        )
                    connection.commit()
                    return tuple(claimed)
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _unavailable_error() from error

    def mark_submitted(
        self,
        command_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        execution_id: str,
        now: datetime,
    ) -> AutomaticRunCommandV2:
        return self._finish_claim(
            command_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
            state="submitted",
            execution_id=execution_id,
            error=None,
            retry_at=None,
            now=now,
        )

    def record_failure(
        self,
        command_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        error: CanvasNodeErrorV2,
        retry_at: datetime,
        now: datetime,
    ) -> AutomaticRunCommandV2:
        row = self._claimed_row(command_id, worker_id, lease_generation)
        next_attempt = int(row["attempt_count"]) + 1
        state = (
            "pending" if error.retryable and next_attempt < int(row["max_attempts"]) else "failed"
        )
        return self._finish_claim(
            command_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
            state=state,
            execution_id=None,
            error=error,
            retry_at=retry_at if state == "pending" else None,
            now=now,
        )

    def defer(
        self,
        command_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        error: CanvasNodeErrorV2,
        retry_at: datetime,
        now: datetime,
    ) -> AutomaticRunCommandV2:
        return self._finish_claim(
            command_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
            state="pending",
            execution_id=None,
            error=error,
            retry_at=retry_at,
            now=now,
            increment_attempt=False,
        )

    def _claimed_row(
        self,
        command_id: str,
        worker_id: str,
        lease_generation: int,
    ):
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasAutomaticRunCommandRow).where(
                            AgentCanvasAutomaticRunCommandRow.command_id == command_id,
                            AgentCanvasAutomaticRunCommandRow.state == "claimed",
                            AgentCanvasAutomaticRunCommandRow.lease_owner == worker_id,
                            AgentCanvasAutomaticRunCommandRow.lease_generation == lease_generation,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        if row is None:
            raise V2PersistenceError(
                "agent_auto_run_claim_stale",
                "Automatic Run command claim is stale.",
                stage="agent_canvas_auto_run",
            )
        return row

    def _finish_claim(
        self,
        command_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        state: str,
        execution_id: str | None,
        error: CanvasNodeErrorV2 | None,
        retry_at: datetime | None,
        now: datetime,
        increment_attempt: bool = True,
    ) -> AutomaticRunCommandV2:
        timestamp = _iso(now)
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    row = (
                        connection.execute(
                            select(AgentCanvasAutomaticRunCommandRow).where(
                                AgentCanvasAutomaticRunCommandRow.command_id == command_id,
                                AgentCanvasAutomaticRunCommandRow.state == "claimed",
                                AgentCanvasAutomaticRunCommandRow.lease_owner == worker_id,
                                AgentCanvasAutomaticRunCommandRow.lease_generation
                                == lease_generation,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None:
                        raise V2PersistenceError(
                            "agent_auto_run_claim_stale",
                            "Automatic Run command claim is stale.",
                            stage="agent_canvas_auto_run",
                        )
                    attempt_count = int(row["attempt_count"]) + int(
                        error is not None and increment_attempt
                    )
                    values = {
                        "state": state,
                        "execution_id": execution_id,
                        "attempt_count": attempt_count,
                        "next_attempt_at": _iso(retry_at) if retry_at else None,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "last_error_code": error.code if error else None,
                        "last_error_message": error.message if error else None,
                        "last_error_retryable": error.retryable if error else None,
                        "updated_at": timestamp,
                    }
                    connection.execute(
                        update(AgentCanvasAutomaticRunCommandRow)
                        .where(
                            AgentCanvasAutomaticRunCommandRow.command_id == command_id,
                            AgentCanvasAutomaticRunCommandRow.state == "claimed",
                            AgentCanvasAutomaticRunCommandRow.lease_owner == worker_id,
                            AgentCanvasAutomaticRunCommandRow.lease_generation == lease_generation,
                        )
                        .values(**values)
                    )
                    event_type = (
                        "agent_auto_run_submitted"
                        if state == "submitted"
                        else "agent_auto_run_failed"
                        if state == "failed"
                        else None
                    )
                    if event_type is not None:
                        payload = {
                            "command_id": command_id,
                            "node_id": str(row["node_id"]),
                        }
                        if execution_id is not None:
                            payload["execution_id"] = execution_id
                        if error is not None:
                            payload["error"] = error.model_dump(mode="json")
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=str(row["workflow_id"]),
                                node_id=str(row["node_id"]),
                                action_id=str(row["source_action_id"]),
                                execution_id=execution_id,
                                event_type=event_type,
                                transition_key=(
                                    f"agent-auto-run:{command_id}:{state}:{lease_generation}"
                                ),
                                created_at=timestamp,
                                payload=payload,
                            ),
                        )
                    connection.commit()
                    return _command({**row, **values})
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as persistence_error:
            raise _unavailable_error() from persistence_error


def _select_identity(connection, *, workflow_id: str, source_action_id: str, node_id: str):
    return (
        connection.execute(
            select(AgentCanvasAutomaticRunCommandRow).where(
                AgentCanvasAutomaticRunCommandRow.workflow_id == workflow_id,
                AgentCanvasAutomaticRunCommandRow.source_action_id == source_action_id,
                AgentCanvasAutomaticRunCommandRow.node_id == node_id,
                AgentCanvasAutomaticRunCommandRow.command_kind == "agent_auto_generate",
            )
        )
        .mappings()
        .one_or_none()
    )


def is_automatic_run_eligible_node_type(node_type: str) -> bool:
    """Return whether a newly published Draft requires a media provider Run."""

    return node_type in {"image", "video", "audio"}


def _command_id(workflow_id: str, source_action_id: str, node_id: str) -> str:
    digest = hashlib.sha256(
        f"{workflow_id}:{source_action_id}:{node_id}:agent_auto_generate".encode()
    ).hexdigest()[:32]
    return f"auto_run_{digest}"


def _command(row: object) -> AutomaticRunCommandV2:
    values = dict(row)  # type: ignore[arg-type]
    error = None
    if values.get("last_error_code") and values.get("last_error_message"):
        error = CanvasNodeErrorV2(
            code=str(values["last_error_code"]),
            message=str(values["last_error_message"]),
            retryable=bool(values.get("last_error_retryable")),
        )
    return AutomaticRunCommandV2(
        command_id=str(values["command_id"]),
        workflow_id=str(values["workflow_id"]),
        source_action_id=str(values["source_action_id"]),
        node_id=str(values["node_id"]),
        command_kind="agent_auto_generate",
        state=str(values["state"]),
        execution_id=(str(values["execution_id"]) if values.get("execution_id") else None),
        attempt_count=int(values["attempt_count"]),
        next_attempt_at=values.get("next_attempt_at"),
        last_error=error,
        created_at=values["created_at"],
        updated_at=values["updated_at"],
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Automatic Run timestamps must include a timezone.")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


def _unavailable_error() -> V2PersistenceError:
    return V2PersistenceError(
        "agent_auto_run_persistence_unavailable",
        "Automatic Run command storage is unavailable.",
        stage="agent_canvas_auto_run",
    )
