"""Transactional SQLite operations for V2 runtime events."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.event_payload import serialize_event_payload
from app.persistence.errors import V2PersistenceError
from app.persistence.models import DataMigrationRow, WorkflowEventRow
from app.schemas.v2_persistence import (
    DataMigrationCompletion,
    V2EventInsert,
    V2EventMigrationReport,
    V2EventSourceStats,
)
from app.schemas.workflow_v2 import WorkflowV2Event


class EventRepository:
    """Owns V2 event persistence without exposing SQLAlchemy state to callers."""

    def __init__(
        self,
        database: V2Database,
        *,
        retry_delays: tuple[float, float] = (0.01, 0.05),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._database = database
        self._retry_delays = retry_delays
        self._sleep = sleep

    @property
    def database(self) -> V2Database:
        """Return the database identity used by this repository."""

        return self._database

    def append(self, event: V2EventInsert) -> WorkflowV2Event:
        """Persist one validated event with a workflow-scoped contiguous sequence."""

        payload_json = serialize_event_payload(event.payload)
        for attempt in range(len(self._retry_delays) + 1):
            try:
                return self._append_once(event, payload_json)
            except OperationalError as error:
                if not _is_sqlite_busy(error):
                    raise _unavailable_error() from error
            except IntegrityError as error:
                if not _is_workflow_sequence_conflict(error):
                    raise _unavailable_error() from error
            except SQLAlchemyError as error:
                raise _unavailable_error() from error

            if attempt == len(self._retry_delays):
                raise _busy_error()
            self._sleep(self._retry_delays[attempt])

        raise AssertionError("The append retry loop must either return or raise.")

    def append_in_transaction(
        self,
        connection: Connection,
        event: V2EventInsert,
    ) -> WorkflowV2Event:
        """Append an event through a caller-owned transaction without committing it."""

        return self._insert_with_next_sequence(
            connection, event, serialize_event_payload(event.payload)
        )

    def complete_migration_in_transaction(
        self,
        connection: Connection,
        completion: DataMigrationCompletion,
    ) -> None:
        """Record a completed migration through a caller-owned transaction."""

        values = {
            "status": "completed",
            "source_count": completion.source_count,
            "imported_count": completion.imported_count,
            "started_at": completion.completed_at,
            "completed_at": completion.completed_at,
            "details_json": json.dumps(
                completion.details,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        }
        existing = connection.execute(
            select(DataMigrationRow.migration_name).where(
                DataMigrationRow.migration_name == completion.migration_name
            )
        ).scalar_one_or_none()
        if existing is None:
            connection.execute(
                insert(DataMigrationRow).values(
                    migration_name=completion.migration_name,
                    **values,
                )
            )
            return
        connection.execute(
            update(DataMigrationRow)
            .where(DataMigrationRow.migration_name == completion.migration_name)
            .values(**values)
        )

    def list_after(self, workflow_id: str, after_seq: int = 0) -> list[WorkflowV2Event]:
        """Return committed workflow events after a cursor in ascending sequence order."""

        try:
            with self._database.engine.connect() as connection:
                rows = connection.execute(
                    select(
                        WorkflowEventRow.seq,
                        WorkflowEventRow.event_type,
                        WorkflowEventRow.workflow_id,
                        WorkflowEventRow.execution_id,
                        WorkflowEventRow.node_id,
                        WorkflowEventRow.item_id,
                        WorkflowEventRow.slot_id,
                        WorkflowEventRow.asset_id,
                        WorkflowEventRow.version_id,
                        WorkflowEventRow.created_at,
                        WorkflowEventRow.payload_json,
                    )
                    .where(
                        WorkflowEventRow.workflow_id == workflow_id,
                        WorkflowEventRow.seq > after_seq,
                    )
                    .order_by(WorkflowEventRow.seq.asc())
                ).mappings()
                return [_workflow_event_from_row(row) for row in rows]
        except SQLAlchemyError as error:
            raise _unavailable_error() from error

    def max_seq(self, workflow_id: str) -> int:
        """Return the committed cursor for one workflow, or zero when it has no events."""

        try:
            with self._database.engine.connect() as connection:
                value = connection.execute(
                    select(func.coalesce(func.max(WorkflowEventRow.seq), 0)).where(
                        WorkflowEventRow.workflow_id == workflow_id
                    )
                ).scalar_one()
                return int(value)
        except SQLAlchemyError as error:
            raise _unavailable_error() from error

    def count(self, workflow_id: str) -> int:
        """Return the number of committed events for one workflow."""

        try:
            with self._database.engine.connect() as connection:
                value = connection.execute(
                    select(func.count())
                    .select_from(WorkflowEventRow)
                    .where(WorkflowEventRow.workflow_id == workflow_id)
                ).scalar_one()
                return int(value)
        except SQLAlchemyError as error:
            raise _unavailable_error() from error

    def workflow_ids(self) -> list[str]:
        """Return event workflow IDs in deterministic order."""

        try:
            with self._database.engine.connect() as connection:
                return list(
                    connection.execute(
                        select(WorkflowEventRow.workflow_id)
                        .distinct()
                        .order_by(WorkflowEventRow.workflow_id.asc())
                    ).scalars()
                )
        except SQLAlchemyError as error:
            raise _unavailable_error() from error

    def completed_migration_report(self, migration_name: str) -> V2EventMigrationReport | None:
        """Return a completed migration report without exposing its ORM row."""

        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(DataMigrationRow.status, DataMigrationRow.details_json).where(
                            DataMigrationRow.migration_name == migration_name
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _unavailable_error() from error

        if row is None or row["status"] != "completed":
            return None
        try:
            return V2EventMigrationReport.model_validate_json(str(row["details_json"]))
        except ValueError as error:
            raise _import_failed_error() from error

    def migration_status(self, migration_name: str) -> str | None:
        """Return a migration marker status without interpreting its details payload."""

        try:
            with self._database.engine.connect() as connection:
                return connection.execute(
                    select(DataMigrationRow.status).where(
                        DataMigrationRow.migration_name == migration_name
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise _unavailable_error() from error

    def migration_details(self, migration_name: str) -> dict[str, Any] | None:
        """Return generic migration details for another canonical V2 import boundary."""

        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(DataMigrationRow.details_json).where(
                            DataMigrationRow.migration_name == migration_name
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        if row is None:
            return None
        try:
            details = json.loads(str(row["details_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise _import_failed_error() from error
        if not isinstance(details, dict):
            raise _import_failed_error()
        return details

    def record_migration_failure(
        self,
        migration_name: str,
        *,
        details: dict[str, object],
    ) -> None:
        """Persist a bounded failed migration marker in its own short transaction."""

        details_json = json.dumps(
            details,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            with self._database.engine.begin() as connection:
                existing = connection.execute(
                    select(DataMigrationRow.migration_name).where(
                        DataMigrationRow.migration_name == migration_name
                    )
                ).scalar_one_or_none()
                values = {
                    "status": "failed",
                    "source_count": None,
                    "imported_count": None,
                    "started_at": _utc_now_isoformat(),
                    "completed_at": None,
                    "details_json": details_json,
                }
                if existing is None:
                    connection.execute(
                        insert(DataMigrationRow).values(migration_name=migration_name, **values)
                    )
                else:
                    connection.execute(
                        update(DataMigrationRow)
                        .where(DataMigrationRow.migration_name == migration_name)
                        .values(**values)
                    )
        except SQLAlchemyError as error:
            raise _import_failed_error() from error

    def import_verified_events(
        self,
        events: Sequence[WorkflowV2Event],
        source_stats: dict[str, V2EventSourceStats],
        migration_name: str,
    ) -> V2EventMigrationReport:
        """Import a parsed canonical corpus atomically and mark it completed."""

        completed_report = self.completed_migration_report(migration_name)
        if completed_report is not None:
            return completed_report

        serialized_events = [(event, serialize_event_payload(event.payload)) for event in events]
        self._record_running_migration(migration_name, source_count=len(events))
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    inserted_event_count = 0
                    idempotent_event_count = 0
                    for event, payload_json in serialized_events:
                        existing_row = (
                            connection.execute(
                                _event_row_select().where(
                                    WorkflowEventRow.workflow_id == event.workflow_id,
                                    WorkflowEventRow.seq == event.seq,
                                )
                            )
                            .mappings()
                            .one_or_none()
                        )
                        if existing_row is None:
                            connection.execute(
                                insert(WorkflowEventRow).values(
                                    workflow_id=event.workflow_id,
                                    execution_id=event.execution_id,
                                    seq=event.seq,
                                    event_type=event.event_type,
                                    node_id=event.node_id,
                                    item_id=event.item_id,
                                    slot_id=event.slot_id,
                                    asset_id=event.asset_id,
                                    version_id=event.version_id,
                                    payload_json=payload_json,
                                    created_at=event.created_at,
                                )
                            )
                            inserted_event_count += 1
                        elif _workflow_event_from_row(existing_row) == event:
                            idempotent_event_count += 1
                        else:
                            raise _import_conflict_error()

                    self._verify_source_stats(connection, source_stats)
                    report = V2EventMigrationReport(
                        migration_name=migration_name,
                        source_file_count=len(source_stats),
                        source_event_count=len(events),
                        inserted_event_count=inserted_event_count,
                        idempotent_event_count=idempotent_event_count,
                        workflow_count=len(source_stats),
                    )
                    connection.execute(
                        update(DataMigrationRow)
                        .where(DataMigrationRow.migration_name == migration_name)
                        .values(
                            status="completed",
                            source_count=len(events),
                            imported_count=inserted_event_count,
                            completed_at=_utc_now_isoformat(),
                            details_json=report.model_dump_json(),
                        )
                    )
                    connection.commit()
                    return report
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _import_failed_error() from error

    def _record_running_migration(self, migration_name: str, *, source_count: int) -> None:
        details_json = json.dumps({"status": "running"}, separators=(",", ":"), sort_keys=True)
        try:
            with self._database.engine.begin() as connection:
                existing = connection.execute(
                    select(DataMigrationRow.migration_name).where(
                        DataMigrationRow.migration_name == migration_name
                    )
                ).scalar_one_or_none()
                values = {
                    "status": "running",
                    "source_count": source_count,
                    "imported_count": None,
                    "started_at": _utc_now_isoformat(),
                    "completed_at": None,
                    "details_json": details_json,
                }
                if existing is None:
                    connection.execute(
                        insert(DataMigrationRow).values(
                            migration_name=migration_name,
                            **values,
                        )
                    )
                else:
                    connection.execute(
                        update(DataMigrationRow)
                        .where(DataMigrationRow.migration_name == migration_name)
                        .values(**values)
                    )
        except SQLAlchemyError as error:
            raise _import_failed_error() from error

    def _verify_source_stats(
        self,
        connection: Connection,
        source_stats: dict[str, V2EventSourceStats],
    ) -> None:
        for workflow_id, source_stat in source_stats.items():
            count = connection.execute(
                select(func.count())
                .select_from(WorkflowEventRow)
                .where(WorkflowEventRow.workflow_id == workflow_id)
            ).scalar_one()
            max_seq = connection.execute(
                select(func.coalesce(func.max(WorkflowEventRow.seq), 0)).where(
                    WorkflowEventRow.workflow_id == workflow_id
                )
            ).scalar_one()
            if int(count) != source_stat.source_count or int(max_seq) != source_stat.max_seq:
                raise _import_verification_error()

    def _append_once(self, event: V2EventInsert, payload_json: str) -> WorkflowV2Event:
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                result = self._insert_with_next_sequence(connection, event, payload_json)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

        return result

    @staticmethod
    def _insert_with_next_sequence(
        connection: Connection,
        event: V2EventInsert,
        payload_json: str,
    ) -> WorkflowV2Event:
        next_seq = int(
            connection.execute(
                select(func.coalesce(func.max(WorkflowEventRow.seq), 0) + 1).where(
                    WorkflowEventRow.workflow_id == event.workflow_id
                )
            ).scalar_one()
        )
        connection.execute(
            insert(WorkflowEventRow).values(
                workflow_id=event.workflow_id,
                execution_id=event.execution_id,
                seq=next_seq,
                event_type=event.event_type,
                node_id=event.node_id,
                item_id=event.item_id,
                slot_id=event.slot_id,
                asset_id=event.asset_id,
                version_id=event.version_id,
                payload_json=payload_json,
                created_at=event.created_at,
            )
        )
        return WorkflowV2Event(
            seq=next_seq,
            event_type=event.event_type,
            workflow_id=event.workflow_id,
            execution_id=event.execution_id,
            node_id=event.node_id,
            item_id=event.item_id,
            slot_id=event.slot_id,
            asset_id=event.asset_id,
            version_id=event.version_id,
            created_at=event.created_at,
            payload=json.loads(payload_json),
        )


def _workflow_event_from_row(row: RowMapping) -> WorkflowV2Event:
    return WorkflowV2Event(
        seq=int(row["seq"]),
        event_type=str(row["event_type"]),
        workflow_id=str(row["workflow_id"]),
        execution_id=_optional_string(row["execution_id"]),
        node_id=_optional_string(row["node_id"]),
        item_id=_optional_string(row["item_id"]),
        slot_id=_optional_string(row["slot_id"]),
        asset_id=_optional_string(row["asset_id"]),
        version_id=_optional_string(row["version_id"]),
        created_at=str(row["created_at"]),
        payload=json.loads(str(row["payload_json"])),
    )


def _event_row_select() -> Any:
    return select(
        WorkflowEventRow.seq,
        WorkflowEventRow.event_type,
        WorkflowEventRow.workflow_id,
        WorkflowEventRow.execution_id,
        WorkflowEventRow.node_id,
        WorkflowEventRow.item_id,
        WorkflowEventRow.slot_id,
        WorkflowEventRow.asset_id,
        WorkflowEventRow.version_id,
        WorkflowEventRow.created_at,
        WorkflowEventRow.payload_json,
    )


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _is_sqlite_busy(error: OperationalError) -> bool:
    message = f"{error} {getattr(error, 'orig', '')}".lower()
    return "locked" in message or "busy" in message


def _is_workflow_sequence_conflict(error: IntegrityError) -> bool:
    message = f"{error} {getattr(error, 'orig', '')}".lower()
    return "workflow_events.workflow_id" in message and "workflow_events.seq" in message


def _busy_error() -> V2PersistenceError:
    return V2PersistenceError(
        "v2_event_store_busy",
        "V2 event persistence is temporarily busy.",
        stage="event_store",
    )


def _unavailable_error() -> V2PersistenceError:
    return V2PersistenceError(
        "v2_event_store_unavailable",
        "V2 event persistence is unavailable.",
        stage="event_store",
    )


def _import_failed_error() -> V2PersistenceError:
    return V2PersistenceError(
        "v2_event_import_failed",
        "V2 event import failed.",
        stage="event_import",
    )


def _import_conflict_error() -> V2PersistenceError:
    return V2PersistenceError(
        "v2_event_import_conflict",
        "V2 event import conflicts with persisted event history.",
        stage="event_import",
    )


def _import_verification_error() -> V2PersistenceError:
    return V2PersistenceError(
        "v2_event_import_verification_failed",
        "V2 event import verification failed.",
        stage="event_import",
    )


def _utc_now_isoformat() -> str:
    return datetime.now(timezone.utc).isoformat()
