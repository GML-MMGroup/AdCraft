"""Durable handoff authority for prepared Agent Canvas media results."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasExecutionMemberRow,
    AgentCanvasResultPublicationIntentRow,
)
from app.schemas.agent_canvas_runtime_authority import (
    CanvasResultPublicationIntentV1,
    PreparedNodeResultV2,
)
from app.schemas.v2_persistence import V2EventInsert


_RECOVERABLE_STATES = ("preparing", "prepared")


class AgentCanvasResultPublicationIntentRepository:
    """Persist one recoverable local publication identity per execution member."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Publication intent and event repositories must share one database.")
        self._database = database
        self._events = events

    @property
    def database(self) -> V2Database:
        return self._database

    def create_or_replay(
        self,
        intent: CanvasResultPublicationIntentV1,
    ) -> CanvasResultPublicationIntentV1:
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    existing = self._find_competing(connection, intent)
                    if existing is not None:
                        replay = _intent(existing)
                        _assert_same_publication(replay, intent)
                        connection.commit()
                        return replay
                    self._assert_member_identity(connection, intent)
                    connection.execute(
                        insert(AgentCanvasResultPublicationIntentRow).values(
                            **_insert_values(intent)
                        )
                    )
                    connection.commit()
                    return intent
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _conflict_error() from error
        except SQLAlchemyError as error:
            raise _unavailable_error() from error

    def get(self, intent_id: str) -> CanvasResultPublicationIntentV1 | None:
        try:
            with self._database.engine.connect() as connection:
                row = connection.execute(
                    select(AgentCanvasResultPublicationIntentRow).where(
                        AgentCanvasResultPublicationIntentRow.intent_id == intent_id
                    )
                ).mappings().one_or_none()
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return _intent(row) if row is not None else None

    def find_for_member(
        self,
        *,
        execution_id: str,
        member_id: str,
    ) -> CanvasResultPublicationIntentV1 | None:
        try:
            with self._database.engine.connect() as connection:
                row = connection.execute(
                    select(AgentCanvasResultPublicationIntentRow).where(
                        AgentCanvasResultPublicationIntentRow.execution_id == execution_id,
                        AgentCanvasResultPublicationIntentRow.member_id == member_id,
                    )
                ).mappings().one_or_none()
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return _intent(row) if row is not None else None

    def list_due(
        self,
        *,
        execution_id: str | None = None,
        now: datetime,
    ) -> tuple[CanvasResultPublicationIntentV1, ...]:
        statement = select(AgentCanvasResultPublicationIntentRow).where(
            AgentCanvasResultPublicationIntentRow.state.in_(_RECOVERABLE_STATES),
            AgentCanvasResultPublicationIntentRow.next_attempt_at <= now.isoformat(),
        )
        if execution_id is not None:
            statement = statement.where(
                AgentCanvasResultPublicationIntentRow.execution_id == execution_id
            )
        statement = statement.order_by(
            AgentCanvasResultPublicationIntentRow.next_attempt_at.asc(),
            AgentCanvasResultPublicationIntentRow.intent_id.asc(),
        )
        try:
            with self._database.engine.connect() as connection:
                rows = connection.execute(statement).mappings().all()
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return tuple(_intent(row) for row in rows)

    def promote_prepared(
        self,
        intent_id: str,
        *,
        prepared_result: PreparedNodeResultV2,
        now: datetime,
    ) -> CanvasResultPublicationIntentV1:
        current = self._require(intent_id)
        candidate = current.model_copy(
            update={
                "prepared_result": prepared_result,
                "state": "prepared",
                "updated_at": now,
            }
        )
        candidate = CanvasResultPublicationIntentV1.model_validate(
            candidate.model_dump(mode="python")
        )
        return self._transition(
            candidate,
            expected_states=("preparing", "prepared"),
            event_type="node_result_publication_prepared",
            retryable=True,
            reason_code="prepared_object_validated",
        )

    def defer(
        self,
        intent_id: str,
        *,
        expected_attempt_count: int,
        next_attempt_at: datetime,
        error_code: str,
        now: datetime,
    ) -> CanvasResultPublicationIntentV1:
        current = self._require(intent_id)
        if current.attempt_count != expected_attempt_count:
            raise _transition_error()
        candidate = current.model_copy(
            update={
                "attempt_count": expected_attempt_count + 1,
                "next_attempt_at": next_attempt_at,
                "last_error_code": error_code,
                "updated_at": now,
            }
        )
        candidate = CanvasResultPublicationIntentV1.model_validate(
            candidate.model_dump(mode="python")
        )
        return self._transition(
            candidate,
            expected_states=_RECOVERABLE_STATES,
            expected_attempt_count=expected_attempt_count,
            event_type="node_result_publication_recovery_scheduled",
            retryable=True,
            reason_code=error_code,
        )

    def abandon(
        self,
        intent_id: str,
        *,
        error_code: str,
        now: datetime,
    ) -> CanvasResultPublicationIntentV1:
        current = self._require(intent_id)
        if current.state == "abandoned":
            return current
        if current.state == "committed":
            raise _transition_error()
        candidate = current.model_copy(
            update={
                "state": "abandoned",
                "last_error_code": error_code,
                "updated_at": now,
            }
        )
        candidate = CanvasResultPublicationIntentV1.model_validate(
            candidate.model_dump(mode="python")
        )
        return self._transition(
            candidate,
            expected_states=_RECOVERABLE_STATES,
            event_type="node_result_publication_failed",
            retryable=False,
            reason_code=error_code,
        )

    def mark_committed(
        self,
        intent_id: str,
        *,
        receipt_id: str,
        now: datetime,
    ) -> CanvasResultPublicationIntentV1:
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    result = self.mark_committed_in_transaction(
                        connection,
                        intent_id=intent_id,
                        receipt_id=receipt_id,
                        now=now,
                    )
                    connection.commit()
                    return result
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _unavailable_error() from error

    def mark_committed_in_transaction(
        self,
        connection: Connection,
        *,
        intent_id: str,
        receipt_id: str,
        now: datetime,
    ) -> CanvasResultPublicationIntentV1:
        row = connection.execute(
            select(AgentCanvasResultPublicationIntentRow).where(
                AgentCanvasResultPublicationIntentRow.intent_id == intent_id
            )
        ).mappings().one_or_none()
        if row is None:
            raise _not_found_error()
        current = _intent(row)
        if current.state == "committed":
            if current.committed_receipt_id != receipt_id:
                raise _transition_error()
            return current
        if current.state != "prepared":
            raise _transition_error()
        changed = connection.execute(
            update(AgentCanvasResultPublicationIntentRow)
            .where(
                AgentCanvasResultPublicationIntentRow.intent_id == intent_id,
                AgentCanvasResultPublicationIntentRow.state == "prepared",
            )
            .values(
                state="committed",
                committed_receipt_id=receipt_id,
                updated_at=now.isoformat(),
            )
        )
        if changed.rowcount != 1:
            raise _transition_error()
        committed = current.model_copy(
            update={
                "state": "committed",
                "committed_receipt_id": receipt_id,
                "updated_at": now,
            }
        )
        return CanvasResultPublicationIntentV1.model_validate(
            committed.model_dump(mode="python")
        )

    def _transition(
        self,
        candidate: CanvasResultPublicationIntentV1,
        *,
        expected_states: tuple[str, ...],
        event_type: str,
        retryable: bool,
        reason_code: str,
        expected_attempt_count: int | None = None,
    ) -> CanvasResultPublicationIntentV1:
        values = {
            "prepared_result_json": (
                candidate.prepared_result.model_dump_json()
                if candidate.prepared_result is not None
                else None
            ),
            "state": candidate.state,
            "attempt_count": candidate.attempt_count,
            "next_attempt_at": candidate.next_attempt_at.isoformat(),
            "last_error_code": candidate.last_error_code,
            "updated_at": candidate.updated_at.isoformat(),
        }
        predicates = [
            AgentCanvasResultPublicationIntentRow.intent_id == candidate.intent_id,
            AgentCanvasResultPublicationIntentRow.state.in_(expected_states),
        ]
        if expected_attempt_count is not None:
            predicates.append(
                AgentCanvasResultPublicationIntentRow.attempt_count == expected_attempt_count
            )
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    existing = connection.execute(
                        select(AgentCanvasResultPublicationIntentRow).where(
                            AgentCanvasResultPublicationIntentRow.intent_id
                            == candidate.intent_id
                        )
                    ).mappings().one_or_none()
                    if existing is not None:
                        current = _intent(existing)
                        if current == candidate:
                            connection.commit()
                            return current
                    changed = connection.execute(
                        update(AgentCanvasResultPublicationIntentRow)
                        .where(*predicates)
                        .values(**values)
                    )
                    if changed.rowcount != 1:
                        raise _transition_error()
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=candidate.workflow_id,
                            execution_id=candidate.execution_id,
                            node_id=candidate.node_id,
                            event_type=event_type,
                            transition_key=(
                                f"publication:{candidate.intent_id}:{event_type}:"
                                f"{candidate.attempt_count}"
                            ),
                            created_at=candidate.updated_at.isoformat(),
                            payload={
                                "publication_intent_id": candidate.intent_id,
                                "node_id": candidate.node_id,
                                "execution_id": candidate.execution_id,
                                "attempt": candidate.attempt_count,
                                "retryable": retryable,
                                "reason_code": reason_code,
                            },
                        ),
                    )
                    connection.commit()
                    return candidate
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _unavailable_error() from error

    def _require(self, intent_id: str) -> CanvasResultPublicationIntentV1:
        intent = self.get(intent_id)
        if intent is None:
            raise _not_found_error()
        return intent

    @staticmethod
    def _find_competing(
        connection: Connection,
        intent: CanvasResultPublicationIntentV1,
    ) -> RowMapping | None:
        return connection.execute(
            select(AgentCanvasResultPublicationIntentRow).where(
                (
                    AgentCanvasResultPublicationIntentRow.logical_result_key
                    == intent.logical_result_key
                )
                | (
                    (
                        AgentCanvasResultPublicationIntentRow.execution_id
                        == intent.execution_id
                    )
                    & (AgentCanvasResultPublicationIntentRow.member_id == intent.member_id)
                )
            )
        ).mappings().one_or_none()

    @staticmethod
    def _assert_member_identity(
        connection: Connection,
        intent: CanvasResultPublicationIntentV1,
    ) -> None:
        member = connection.execute(
            select(AgentCanvasExecutionMemberRow).where(
                AgentCanvasExecutionMemberRow.member_id == intent.member_id,
                AgentCanvasExecutionMemberRow.execution_id == intent.execution_id,
                AgentCanvasExecutionMemberRow.workflow_id == intent.workflow_id,
                AgentCanvasExecutionMemberRow.node_id == intent.node_id,
            )
        ).mappings().one_or_none()
        if member is None:
            raise _conflict_error()
        snapshot_id = member["run_intent_snapshot_id"]
        snapshot_digest = member["run_intent_snapshot_digest"]
        if snapshot_id is not None and str(snapshot_id) != intent.source_snapshot_id:
            raise _conflict_error()
        if snapshot_digest is not None and str(snapshot_digest) != intent.source_snapshot_digest:
            raise _conflict_error()


def _insert_values(intent: CanvasResultPublicationIntentV1) -> dict[str, object]:
    return {
        "intent_id": intent.intent_id,
        "workflow_id": intent.workflow_id,
        "execution_id": intent.execution_id,
        "member_id": intent.member_id,
        "node_id": intent.node_id,
        "logical_result_key": intent.logical_result_key,
        "payload_digest": intent.payload_digest,
        "source_snapshot_id": intent.source_snapshot_id,
        "source_snapshot_digest": intent.source_snapshot_digest,
        "expected_storage_key": intent.expected_storage_key,
        "expected_object_sha256": intent.expected_object_sha256,
        "planned_result_json": intent.planned_result.model_dump_json(),
        "prepared_result_json": (
            intent.prepared_result.model_dump_json()
            if intent.prepared_result is not None
            else None
        ),
        "state": intent.state,
        "attempt_count": intent.attempt_count,
        "next_attempt_at": intent.next_attempt_at.isoformat(),
        "recovery_deadline": intent.recovery_deadline.isoformat(),
        "last_error_code": intent.last_error_code,
        "committed_receipt_id": intent.committed_receipt_id,
        "created_at": intent.created_at.isoformat(),
        "updated_at": intent.updated_at.isoformat(),
    }


def _intent(row: RowMapping) -> CanvasResultPublicationIntentV1:
    prepared_json = row["prepared_result_json"]
    return CanvasResultPublicationIntentV1(
        intent_id=str(row["intent_id"]),
        workflow_id=str(row["workflow_id"]),
        execution_id=str(row["execution_id"]),
        member_id=str(row["member_id"]),
        node_id=str(row["node_id"]),
        logical_result_key=str(row["logical_result_key"]),
        payload_digest=str(row["payload_digest"]),
        source_snapshot_id=str(row["source_snapshot_id"]),
        source_snapshot_digest=str(row["source_snapshot_digest"]),
        expected_storage_key=str(row["expected_storage_key"]),
        expected_object_sha256=str(row["expected_object_sha256"]),
        planned_result=PreparedNodeResultV2.model_validate_json(str(row["planned_result_json"])),
        prepared_result=(
            PreparedNodeResultV2.model_validate_json(str(prepared_json))
            if prepared_json is not None
            else None
        ),
        state=str(row["state"]),
        attempt_count=int(row["attempt_count"]),
        next_attempt_at=datetime.fromisoformat(str(row["next_attempt_at"])),
        recovery_deadline=datetime.fromisoformat(str(row["recovery_deadline"])),
        last_error_code=(str(row["last_error_code"]) if row["last_error_code"] else None),
        committed_receipt_id=(
            str(row["committed_receipt_id"]) if row["committed_receipt_id"] else None
        ),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def _assert_same_publication(
    existing: CanvasResultPublicationIntentV1,
    candidate: CanvasResultPublicationIntentV1,
) -> None:
    immutable_fields = (
        "intent_id",
        "workflow_id",
        "execution_id",
        "member_id",
        "node_id",
        "logical_result_key",
        "payload_digest",
        "source_snapshot_id",
        "source_snapshot_digest",
        "expected_storage_key",
        "expected_object_sha256",
        "planned_result",
        "recovery_deadline",
    )
    if any(getattr(existing, field) != getattr(candidate, field) for field in immutable_fields):
        raise _conflict_error()


def _conflict_error() -> V2PersistenceError:
    return V2PersistenceError(
        "node_result_publication_intent_conflict",
        "Result publication identity conflicts with durable state.",
        stage="agent_canvas_result_publication",
    )


def _transition_error() -> V2PersistenceError:
    return V2PersistenceError(
        "node_result_publication_transition_conflict",
        "Result publication state changed before this transition.",
        stage="agent_canvas_result_publication",
    )


def _not_found_error() -> V2PersistenceError:
    return V2PersistenceError(
        "node_result_publication_intent_not_found",
        "Result publication intent was not found.",
        stage="agent_canvas_result_publication",
    )


def _unavailable_error() -> V2PersistenceError:
    return V2PersistenceError(
        "node_result_publication_unavailable",
        "Result publication state is unavailable.",
        stage="agent_canvas_result_publication",
        details={"retryable": True},
    )
