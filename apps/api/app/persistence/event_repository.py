"""Transactional SQLite operations for V2 runtime events."""

from __future__ import annotations

import hashlib
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

        event = _canonical_event(event)
        if event.transition_key is not None:
            return self.append_transition(event)
        payload_json = serialize_event_payload(_event_payload_for_storage(event))
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

    def append_transition(self, event: V2EventInsert) -> WorkflowV2Event:
        """Append one idempotent business transition without advancing on replay."""

        event = _canonical_event(event)
        if event.transition_key is None:
            raise V2PersistenceError(
                "event_transition_key_required",
                "Transition events require a transition key.",
                stage="event_repository",
            )
        payload_json = serialize_event_payload(_event_payload_for_storage(event))
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    existing = _event_by_transition_key(
                        connection,
                        event.transition_key,
                    )
                    if existing is not None:
                        result = _workflow_event_from_row(existing)
                        if not _transition_matches(result, event):
                            raise V2PersistenceError(
                                "event_transition_conflict",
                                "Transition key was reused with different event content.",
                                stage="event_repository",
                            )
                    else:
                        result = self._insert_with_next_sequence(
                            connection,
                            event,
                            payload_json,
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

    def append_in_transaction(
        self,
        connection: Connection,
        event: V2EventInsert,
    ) -> WorkflowV2Event:
        """Append an event through a caller-owned transaction without committing it."""

        event = _canonical_event(event)
        if event.transition_key is not None:
            existing = _event_by_transition_key(connection, event.transition_key)
            if existing is not None:
                result = _workflow_event_from_row(existing)
                if not _transition_matches(result, event):
                    raise V2PersistenceError(
                        "event_transition_conflict",
                        "Transition key was reused with different event content.",
                        stage="event_repository",
                    )
                return result
        return self._insert_with_next_sequence(
            connection,
            event,
            serialize_event_payload(_event_payload_for_storage(event)),
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
                        WorkflowEventRow.transition_key,
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

    def min_seq(self, workflow_id: str) -> int:
        """Return the oldest retained workflow sequence, or zero when empty."""

        try:
            with self._database.engine.connect() as connection:
                value = connection.execute(
                    select(func.coalesce(func.min(WorkflowEventRow.seq), 0)).where(
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

        serialized_events = [_canonical_import_event(event) for event in events]
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
                transition_key=event.transition_key,
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
            transition_key=event.transition_key,
            workflow_id=event.workflow_id,
            project_id=event.project_id,
            execution_id=event.execution_id,
            node_id=event.node_id,
            binding_id=event.binding_id,
            item_id=event.item_id,
            slot_id=event.slot_id,
            asset_id=event.asset_id,
            version_id=event.version_id,
            conversation_id=event.conversation_id,
            turn_id=event.turn_id,
            action_id=event.action_id,
            trace_id=event.trace_id,
            span_id=event.span_id,
            created_at=event.created_at,
            payload=_public_event_payload(json.loads(payload_json)),
        )


def _workflow_event_from_row(row: RowMapping) -> WorkflowV2Event:
    stored_payload = json.loads(str(row["payload_json"]))
    envelope = _stored_event_envelope(stored_payload)
    payload = _public_event_payload(stored_payload)
    return WorkflowV2Event(
        seq=int(row["seq"]),
        event_type=str(row["event_type"]),
        transition_key=_optional_string(row["transition_key"]),
        workflow_id=str(row["workflow_id"]),
        project_id=_payload_id(envelope, "project_id"),
        execution_id=_optional_string(row["execution_id"]),
        node_id=_optional_string(row["node_id"]),
        binding_id=_payload_id(envelope, "binding_id"),
        item_id=_optional_string(row["item_id"]),
        slot_id=_optional_string(row["slot_id"]),
        asset_id=_optional_string(row["asset_id"]),
        version_id=_optional_string(row["version_id"]),
        conversation_id=_payload_id(envelope, "conversation_id"),
        turn_id=_payload_id(envelope, "turn_id"),
        action_id=_payload_id(envelope, "action_id"),
        trace_id=_payload_id(envelope, "trace_id"),
        span_id=_payload_id(envelope, "span_id"),
        created_at=str(row["created_at"]),
        payload=payload,
    )


def _canonical_import_event(event: WorkflowV2Event) -> tuple[WorkflowV2Event, str]:
    canonical = _canonical_event(
        V2EventInsert(
            workflow_id=event.workflow_id,
            event_type=event.event_type,
            transition_key=event.transition_key,
            project_id=event.project_id,
            execution_id=event.execution_id,
            node_id=event.node_id,
            binding_id=event.binding_id,
            item_id=event.item_id,
            slot_id=event.slot_id,
            asset_id=event.asset_id,
            version_id=event.version_id,
            conversation_id=event.conversation_id,
            turn_id=event.turn_id,
            action_id=event.action_id,
            trace_id=event.trace_id,
            span_id=event.span_id,
            created_at=event.created_at,
            payload=event.payload,
        )
    )
    public_event = WorkflowV2Event(
        seq=event.seq,
        **canonical.model_dump(mode="python"),
    )
    return public_event, serialize_event_payload(_event_payload_for_storage(canonical))


_CANONICAL_EVENT_TYPES = {
    "canvas_node_created": "node_created",
    "canvas_node_updated": "node_updated",
    "canvas_node_deleted": "node_deleted",
    "canvas_binding_created": "binding_created",
    "canvas_binding_updated": "binding_updated",
    "binding_removed": "binding_deleted",
    "canvas_layout_updated": "layout_updated",
    "canvas_variation_draft_saved": "node_updated",
    "canvas_variation_draft_discarded": "node_updated",
    "canvas_variation_materialized": "node_created",
    "chat_turn_queued": "agent_turn_queued",
    "chat_turn_started": "agent_turn_started",
    "chat_turn_completed": "agent_turn_completed",
    "chat_turn_failed": "agent_turn_failed",
    "concept_proposal_created": "creative_proposal_created",
    "proposal_selected": "creative_proposal_resolved",
    "proposal_revised": "creative_proposal_resolved",
    "proposal_skipped": "creative_proposal_resolved",
    "planning_topic_updated": "creative_topic_updated",
    "expert_activity_started": "specialist_activity_started",
    "expert_activity_completed": "specialist_activity_completed",
    "expert_activity_failed": "specialist_activity_failed",
    "video_skill_run_created": "creative_direction_updated",
    "agent_command_plan_created": "command_plan_created",
    "agent_command_plan_applied": "command_plan_committed",
    "agent_command_plan_rejected": "command_plan_rejected",
    "agent_command_plan_failed": "command_plan_rejected",
    "agent_action_receipt_created": "action_receipt_created",
    "node_run_queued": "node_queued",
    "node_run_started": "node_generation_started",
    "provider_execution_started": "node_generation_started",
    "node_run_cancelled": "node_cancelled",
    "node_waiting_for_input": "node_blocked",
    "provider_task_recovering": "provider_task_waiting",
    "script_artifact_created": "node_output_published",
    "workflow_revision_created": "workflow_projection_updated",
}


def _canonical_event(event: V2EventInsert) -> V2EventInsert:
    event_type = _CANONICAL_EVENT_TYPES.get(event.event_type, event.event_type)
    promoted = {
        field: getattr(event, field) or _payload_id(event.payload, field)
        for field in (
            "project_id",
            "binding_id",
            "conversation_id",
            "turn_id",
            "action_id",
        )
    }
    correlation_id = next(
        (
            value
            for value in (
                promoted["turn_id"],
                promoted["action_id"],
                event.execution_id,
                promoted["conversation_id"],
                event.node_id,
                event.workflow_id,
            )
            if value
        ),
        event.workflow_id,
    )
    trace_id = (
        event.trace_id
        or _payload_id(event.payload, "trace_id")
        or hashlib.sha256(
            f"agent-canvas-trace:{event.workflow_id}:{correlation_id}".encode()
        ).hexdigest()[:32]
    )
    transition_key = event.transition_key or _derived_transition_key(
        event,
        event_type=event_type,
        promoted=promoted,
    )
    span_id = (
        event.span_id
        or _payload_id(event.payload, "span_id")
        or hashlib.sha256(
            (
                f"agent-canvas-span:{transition_key or event.created_at}:"
                f"{event.node_id or ''}:{promoted['action_id'] or ''}"
            ).encode()
        ).hexdigest()[:16]
    )
    return event.model_copy(
        update={
            "event_type": event_type,
            "transition_key": transition_key,
            **promoted,
            "trace_id": trace_id,
            "span_id": span_id,
        }
    )


def _derived_transition_key(
    event: V2EventInsert,
    *,
    event_type: str,
    promoted: dict[str, str | None],
) -> str | None:
    payload = event.payload
    identity: tuple[str, str] | None = None
    if event_type.startswith("provider_task_"):
        task_id = _payload_id(payload, "task_id") or _payload_id(payload, "provider_task_id")
        if task_id:
            identity = ("provider-task", task_id)
    elif event_type.startswith("continuation_") or event_type.startswith("agent_turn_"):
        turn_id = promoted["turn_id"] or _payload_id(payload, "turn_id")
        continuation_id = _payload_id(payload, "continuation_id")
        if turn_id or continuation_id:
            identity = ("conversation", turn_id or continuation_id or "")
    elif event_type.startswith("node_"):
        node_run_id = _payload_id(payload, "node_run_id")
        if node_run_id:
            identity = ("node-run", node_run_id)
    elif event.event_type in {
        "slot_queued",
        "slot_generation_started",
        "slot_generation_waiting",
        "slot_generation_completed",
        "slot_generation_failed",
        "slot_recovered_ready",
        "slot_skipped",
    }:
        if event.execution_id is not None:
            runtime_id = ":".join(
                value for value in (event.execution_id, event.node_id, event.slot_id) if value
            )
            identity = ("node-run", runtime_id)
    elif event_type in {
        "asset_published",
        "project_asset_published",
        "node_output_published",
        "publication_completed",
        "publication_failed",
    }:
        publication_id = (
            _payload_id(payload, "publication_id") or event.version_id or event.asset_id
        )
        if publication_id:
            identity = ("publication", publication_id)
    elif "recovery" in event_type and event.execution_id:
        identity = ("recovery", event.execution_id)
    elif promoted["action_id"] and event_type in {
        "action_receipt_created",
        "command_plan_committed",
        "command_plan_rejected",
        "guided_action_applied",
    }:
        identity = ("action", promoted["action_id"])
    if identity is None:
        return None
    attempt = next(
        (
            payload[key]
            for key in (
                "attempt",
                "attempt_no",
                "poll_count",
                "lease_generation",
                "generation",
                "revision",
            )
            if key in payload and isinstance(payload[key], (int, str))
        ),
        0,
    )
    transition = event.event_type
    if event_type == "node_blocked":
        blocked_by = payload.get("blocked_by_node_ids")
        transition = (
            "node_blocked"
            if isinstance(blocked_by, list) and blocked_by
            else "node_waiting_for_input"
        )
    return f"{identity[0]}:{identity[1]}:{transition}:{attempt}"


def _payload_id(payload: object, key: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


_EVENT_ENVELOPE_KEY = "_agent_canvas_event_envelope"


def _event_payload_for_storage(event: V2EventInsert) -> dict[str, Any]:
    payload = dict(event.payload)
    envelope = {
        field: getattr(event, field)
        for field in (
            "project_id",
            "binding_id",
            "conversation_id",
            "turn_id",
            "action_id",
            "trace_id",
            "span_id",
        )
        if getattr(event, field) is not None
    }
    if envelope:
        payload[_EVENT_ENVELOPE_KEY] = envelope
    return payload


def _stored_event_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    envelope = payload.get(_EVENT_ENVELOPE_KEY)
    return envelope if isinstance(envelope, dict) else payload


def _public_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != _EVENT_ENVELOPE_KEY}


def _event_row_select() -> Any:
    return select(
        WorkflowEventRow.seq,
        WorkflowEventRow.event_type,
        WorkflowEventRow.transition_key,
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


def _event_by_transition_key(
    connection: Connection,
    transition_key: str,
) -> RowMapping | None:
    return (
        connection.execute(
            _event_row_select().where(WorkflowEventRow.transition_key == transition_key)
        )
        .mappings()
        .one_or_none()
    )


def _transition_matches(
    existing: WorkflowV2Event,
    candidate: V2EventInsert,
) -> bool:
    replay = WorkflowV2Event(
        seq=existing.seq,
        **candidate.model_dump(mode="python"),
    )
    ignored = {"seq", "created_at", "trace_id", "span_id"}
    return existing.model_dump(exclude=ignored) == replay.model_dump(exclude=ignored)


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
