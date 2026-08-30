"""Durable continuation delivery with recoverable compare-and-set leases."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, insert, or_, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasContinuationOutboxRow,
    AgentCanvasOperationEnvelopeRow,
)
from app.schemas.agent_canvas_capabilities import CapabilityIdV1
from app.schemas.agent_canvas_continuation import CONTINUATION_OPERATIONS_V2
from app.schemas.agent_canvas_conversation import ContinuationDeliveryV2
from app.schemas.v2_persistence import V2EventInsert


class AgentCanvasContinuationOutboxRepository:
    """Own durable continuation dispatch identities and worker leases."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Continuation outbox and events must use the same database.")
        self._database = database
        self._events = events

    @property
    def database(self) -> V2Database:
        return self._database

    def enqueue(
        self,
        *,
        continuation_id: str,
        workflow_id: str,
        conversation_id: str,
        source_turn_id: str,
        continuation_turn_id: str,
        operation: str,
        payload: Mapping[str, object],
        max_attempts: int,
        now: datetime,
    ) -> ContinuationDeliveryV2:
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    delivery = self.enqueue_in_transaction(
                        connection,
                        continuation_id=continuation_id,
                        workflow_id=workflow_id,
                        conversation_id=conversation_id,
                        source_turn_id=source_turn_id,
                        continuation_turn_id=continuation_turn_id,
                        operation=operation,
                        payload=payload,
                        max_attempts=max_attempts,
                        now=now,
                    )
                    connection.commit()
                    return delivery
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _error(
                "idempotency_conflict",
                "Continuation identity conflicts with an existing delivery.",
            ) from error
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def enqueue_in_transaction(
        self,
        connection: Connection,
        *,
        continuation_id: str,
        workflow_id: str,
        conversation_id: str,
        source_turn_id: str,
        continuation_turn_id: str,
        operation: str,
        payload: Mapping[str, object],
        max_attempts: int,
        now: datetime,
    ) -> ContinuationDeliveryV2:
        if max_attempts < 1:
            raise _error("continuation_attempts_invalid", "Maximum attempts must be positive.")
        payload_keys = set(payload)
        required_payload_keys = {"schema_version", "envelope_id"}
        allowed_payload_keys = {
            *required_payload_keys,
            "occurrence_id",
            "character_phase",
            "action_owner",
        }
        if (
            operation not in CONTINUATION_OPERATIONS_V2
            or not required_payload_keys <= payload_keys
            or not payload_keys <= allowed_payload_keys
        ):
            raise _error(
                "continuation_payload_invalid",
                "Continuation delivery requires one typed operation envelope reference.",
            )
        if (
            payload.get("schema_version") != "1"
            or not str(payload.get("envelope_id") or "").strip()
            or (payload.get("occurrence_id") is None) != (payload.get("character_phase") is None)
            or payload.get("character_phase") not in {None, "main", "turnaround"}
            or payload.get("action_owner")
            not in {None, "guided_journey", "targeted_authoring", "quick_media"}
        ):
            raise _error(
                "continuation_payload_invalid",
                "Continuation delivery envelope reference is invalid.",
            )
        payload_json = _json(payload)
        payload_digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        timestamp = _utc(now)
        values = {
            "continuation_id": continuation_id,
            "workflow_id": workflow_id,
            "conversation_id": conversation_id,
            "source_turn_id": source_turn_id,
            "continuation_turn_id": continuation_turn_id,
            "operation": operation,
            "payload_json": payload_json,
            "payload_digest": payload_digest,
            "status": "queued",
            "attempt_count": 0,
            "max_attempts": max_attempts,
            "next_attempt_at": _iso(timestamp),
            "lease_owner": None,
            "lease_generation": 0,
            "lease_expires_at": None,
            "last_error_code": None,
            "last_error_message": None,
            "created_at": _iso(timestamp),
            "updated_at": _iso(timestamp),
        }
        existing = _select_one(connection, continuation_id)
        if existing is not None:
            _require_same_enqueue(existing, values)
            return _delivery(existing)
        active_row = _select_active_for_workflow(connection, workflow_id)
        if active_row is not None:
            if str(active_row["continuation_turn_id"]) != source_turn_id:
                raise _error(
                    "active_continuation_conflict",
                    "Another continuation already owns this workflow.",
                )
            completed = {
                **active_row,
                "status": "completed",
                "lease_owner": None,
                "lease_expires_at": None,
                "updated_at": _iso(timestamp),
            }
            changed = connection.execute(
                update(AgentCanvasContinuationOutboxRow)
                .where(
                    AgentCanvasContinuationOutboxRow.continuation_id
                    == active_row["continuation_id"],
                    AgentCanvasContinuationOutboxRow.status.in_(("queued", "leased", "retry_wait")),
                )
                .values(
                    status="completed",
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=_iso(timestamp),
                )
            )
            if changed.rowcount != 1:
                raise _error(
                    "active_continuation_conflict",
                    "Continuation handoff authority changed before commit.",
                )
            self._append_lifecycle_event(
                connection,
                completed,
                event_type="continuation_completed",
                transition_key=(
                    "conversation:"
                    f"{active_row['continuation_turn_id']}:"
                    f"continuation_completed:{active_row['lease_generation']}"
                ),
                created_at=timestamp,
            )
        try:
            connection.execute(insert(AgentCanvasContinuationOutboxRow).values(**values))
        except IntegrityError as error:
            replay = _select_one(connection, continuation_id)
            if replay is not None:
                _require_same_enqueue(replay, values)
                return _delivery(replay)
            active = self.get_active_for_workflow_in_transaction(connection, workflow_id)
            if active is not None:
                raise _error(
                    "active_continuation_conflict",
                    "Another continuation already owns this workflow.",
                ) from error
            raise _error(
                "idempotency_conflict",
                "Continuation identity conflicts with an existing delivery.",
            ) from error
        self._append_lifecycle_event(
            connection,
            values,
            event_type="continuation_queued",
            transition_key=f"conversation:{continuation_turn_id}:continuation_queued:0",
            created_at=timestamp,
        )
        return _delivery(values)

    def get_active_for_workflow_in_transaction(
        self,
        connection: Connection,
        workflow_id: str,
    ) -> ContinuationDeliveryV2 | None:
        """Read the single active owner through a caller-owned transaction."""

        row = _select_active_for_workflow(connection, workflow_id)
        return _delivery(row) if row is not None else None

    def get(self, continuation_id: str) -> ContinuationDeliveryV2:
        try:
            with self._database.engine.connect() as connection:
                row = _select_one(connection, continuation_id)
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        if row is None:
            raise _error("continuation_not_found", "Continuation delivery was not found.")
        return _delivery(row)

    def list_nonterminal_for_workflow(
        self,
        workflow_id: str,
    ) -> tuple[ContinuationDeliveryV2, ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasContinuationOutboxRow)
                        .where(
                            AgentCanvasContinuationOutboxRow.workflow_id == workflow_id,
                            AgentCanvasContinuationOutboxRow.status.in_(
                                ("queued", "leased", "retry_wait")
                            ),
                        )
                        .order_by(
                            AgentCanvasContinuationOutboxRow.created_at.asc(),
                            AgentCanvasContinuationOutboxRow.continuation_id.asc(),
                        )
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return tuple(_delivery(row) for row in rows)

    def list_for_workflow(self, workflow_id: str) -> tuple[ContinuationDeliveryV2, ...]:
        """Return causal delivery records without filtering terminal history."""

        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasContinuationOutboxRow)
                        .where(AgentCanvasContinuationOutboxRow.workflow_id == workflow_id)
                        .order_by(
                            AgentCanvasContinuationOutboxRow.created_at.asc(),
                            AgentCanvasContinuationOutboxRow.continuation_id.asc(),
                        )
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return tuple(_delivery(row) for row in rows)

    def get_for_turn(self, turn_id: str) -> ContinuationDeliveryV2 | None:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasContinuationOutboxRow).where(
                            AgentCanvasContinuationOutboxRow.continuation_turn_id == turn_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return _delivery(row) if row is not None else None

    def list_nonterminal_capability_ids(
        self,
        workflow_id: str,
    ) -> tuple[CapabilityIdV1, ...]:
        """Return capability commands that still own a pending delivery."""

        try:
            with self._database.engine.connect() as connection:
                rows = tuple(
                    connection.execute(
                        select(AgentCanvasOperationEnvelopeRow.envelope_json)
                        .join(
                            AgentCanvasContinuationOutboxRow,
                            AgentCanvasContinuationOutboxRow.continuation_turn_id
                            == AgentCanvasOperationEnvelopeRow.turn_id,
                        )
                        .where(
                            AgentCanvasContinuationOutboxRow.workflow_id == workflow_id,
                            AgentCanvasContinuationOutboxRow.operation == "capability_command",
                            AgentCanvasContinuationOutboxRow.status.in_(
                                ("queued", "leased", "retry_wait")
                            ),
                        )
                        .order_by(AgentCanvasContinuationOutboxRow.created_at.asc())
                    ).scalars()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return tuple(
            dict.fromkeys(json.loads(str(envelope_json))["capability_id"] for envelope_json in rows)
        )

    def claim_due(
        self,
        *,
        worker_id: str,
        now: datetime,
        batch_limit: int,
        lease_duration: timedelta,
    ) -> tuple[ContinuationDeliveryV2, ...]:
        if batch_limit < 1 or lease_duration <= timedelta(0):
            raise _error("continuation_claim_invalid", "Continuation claim settings are invalid.")
        timestamp = _utc(now)
        now_value = _iso(timestamp)
        lease_expires_at = _iso(timestamp + lease_duration)
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    rows = list(
                        connection.execute(
                            select(AgentCanvasContinuationOutboxRow)
                            .where(
                                or_(
                                    and_(
                                        AgentCanvasContinuationOutboxRow.status.in_(
                                            ("queued", "retry_wait")
                                        ),
                                        AgentCanvasContinuationOutboxRow.next_attempt_at
                                        <= now_value,
                                    ),
                                    and_(
                                        AgentCanvasContinuationOutboxRow.status == "leased",
                                        AgentCanvasContinuationOutboxRow.lease_expires_at
                                        <= now_value,
                                    ),
                                )
                            )
                            .order_by(
                                AgentCanvasContinuationOutboxRow.next_attempt_at.asc(),
                                AgentCanvasContinuationOutboxRow.created_at.asc(),
                                AgentCanvasContinuationOutboxRow.continuation_id.asc(),
                            )
                            .limit(batch_limit)
                        ).mappings()
                    )
                    claimed = []
                    for row in rows:
                        generation = int(row["lease_generation"]) + 1
                        result = connection.execute(
                            update(AgentCanvasContinuationOutboxRow)
                            .where(
                                AgentCanvasContinuationOutboxRow.continuation_id
                                == row["continuation_id"],
                                AgentCanvasContinuationOutboxRow.status == row["status"],
                                AgentCanvasContinuationOutboxRow.lease_generation
                                == row["lease_generation"],
                            )
                            .values(
                                status="leased",
                                lease_owner=worker_id,
                                lease_generation=generation,
                                lease_expires_at=lease_expires_at,
                                updated_at=now_value,
                            )
                        )
                        if result.rowcount != 1:
                            continue
                        updated = {
                            **row,
                            "status": "leased",
                            "lease_owner": worker_id,
                            "lease_generation": generation,
                            "lease_expires_at": lease_expires_at,
                            "updated_at": now_value,
                        }
                        self._append_lifecycle_event(
                            connection,
                            updated,
                            event_type="continuation_started",
                            transition_key=(
                                "conversation:"
                                f"{row['continuation_turn_id']}:"
                                f"continuation_started:{generation}"
                            ),
                            created_at=timestamp,
                        )
                        claimed.append(_delivery(updated))
                    connection.commit()
                    return tuple(claimed)
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def complete(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        now: datetime,
    ) -> ContinuationDeliveryV2:
        return self._finish_owned(
            continuation_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
            status="completed",
            now=now,
        )

    def renew_lease(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        now: datetime,
        lease_duration: timedelta,
    ) -> ContinuationDeliveryV2:
        timestamp = _utc(now)
        if lease_duration <= timedelta(0):
            raise _error("continuation_claim_invalid", "Lease duration must be positive.")
        try:
            with self._database.engine.begin() as connection:
                row = _select_one(connection, continuation_id)
                if row is None:
                    raise _error("continuation_not_found", "Continuation delivery was not found.")
                _require_owned(row, worker_id, lease_generation, timestamp)
                expires_at = _iso(timestamp + lease_duration)
                result = connection.execute(
                    update(AgentCanvasContinuationOutboxRow)
                    .where(
                        AgentCanvasContinuationOutboxRow.continuation_id == continuation_id,
                        AgentCanvasContinuationOutboxRow.status == "leased",
                        AgentCanvasContinuationOutboxRow.lease_owner == worker_id,
                        AgentCanvasContinuationOutboxRow.lease_generation == lease_generation,
                    )
                    .values(lease_expires_at=expires_at, updated_at=_iso(timestamp))
                )
                if result.rowcount != 1:
                    raise _stale_lease_error()
                return _delivery(
                    {**row, "lease_expires_at": expires_at, "updated_at": _iso(timestamp)}
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def assert_owned(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        now: datetime,
    ) -> None:
        delivery = self.get(continuation_id)
        if (
            delivery.status != "leased"
            or delivery.lease_owner != worker_id
            or delivery.lease_generation != lease_generation
            or delivery.lease_expires_at is None
            or delivery.lease_expires_at < _utc(now)
        ):
            raise _stale_lease_error()

    def schedule_retry(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        next_attempt_at: datetime,
        error_code: str,
        error_message: str,
        now: datetime,
    ) -> ContinuationDeliveryV2:
        timestamp = _utc(now)
        available_at = _utc(next_attempt_at)
        if available_at < timestamp:
            raise _error(
                "continuation_retry_invalid",
                "Continuation retry time cannot precede the current time.",
            )
        return self._finish_owned(
            continuation_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
            status="retry_wait",
            now=timestamp,
            next_attempt_at=available_at,
            increment_attempt=True,
            error_code=error_code,
            error_message=error_message,
        )

    def fail(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        error_code: str,
        error_message: str,
        now: datetime,
    ) -> ContinuationDeliveryV2:
        return self._finish_owned(
            continuation_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
            status="failed",
            now=now,
            increment_attempt=True,
            error_code=error_code,
            error_message=error_message,
        )

    def supersede(
        self,
        continuation_id: str,
        *,
        reason: str,
        now: datetime,
    ) -> ContinuationDeliveryV2:
        """Terminally supersede one queued delivery without dispatching it."""

        timestamp = _utc(now)
        try:
            with self._database.engine.begin() as connection:
                row = _select_one(connection, continuation_id)
                if row is None:
                    raise _error(
                        "continuation_not_found",
                        "Continuation delivery was not found.",
                    )
                if row["status"] == "superseded":
                    return _delivery(row)
                if row["status"] in {"completed", "failed"}:
                    raise _error(
                        "continuation_already_terminal",
                        "Continuation delivery is already terminal.",
                    )
                values = {
                    "status": "superseded",
                    "next_attempt_at": _iso(timestamp),
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error_code": "continuation_superseded",
                    "last_error_message": _bounded(reason, 1_024),
                    "updated_at": _iso(timestamp),
                }
                result = connection.execute(
                    update(AgentCanvasContinuationOutboxRow)
                    .where(
                        AgentCanvasContinuationOutboxRow.continuation_id == continuation_id,
                        AgentCanvasContinuationOutboxRow.status.in_(
                            ("queued", "leased", "retry_wait")
                        ),
                    )
                    .values(**values)
                )
                if result.rowcount != 1:
                    raise _error(
                        "continuation_state_conflict",
                        "Continuation delivery changed before supersession.",
                    )
                updated = {**row, **values}
                self._append_lifecycle_event(
                    connection,
                    updated,
                    event_type="continuation_superseded",
                    transition_key=(
                        "conversation:"
                        f"{row['continuation_turn_id']}:"
                        f"continuation_superseded:{row['lease_generation']}"
                    ),
                    created_at=timestamp,
                )
                return _delivery(updated)
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def supersede_owned(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        reason: str,
        now: datetime,
    ) -> ContinuationDeliveryV2:
        """Supersede only the delivery generation currently owned by a worker."""

        return self._finish_owned(
            continuation_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
            status="superseded",
            now=now,
            error_code="continuation_superseded",
            error_message=reason,
        )

    def _finish_owned(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        status: str,
        now: datetime,
        next_attempt_at: datetime | None = None,
        increment_attempt: bool = False,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> ContinuationDeliveryV2:
        timestamp = _utc(now)
        try:
            with self._database.engine.begin() as connection:
                row = _select_one(connection, continuation_id)
                if row is None:
                    raise _error(
                        "continuation_not_found",
                        "Continuation delivery was not found.",
                    )
                _require_owned(row, worker_id, lease_generation, timestamp)
                values = {
                    "status": status,
                    "attempt_count": int(row["attempt_count"]) + (1 if increment_attempt else 0),
                    "next_attempt_at": _iso(next_attempt_at or timestamp),
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error_code": _bounded(error_code, 160),
                    "last_error_message": _bounded(error_message, 1_024),
                    "updated_at": _iso(timestamp),
                }
                result = connection.execute(
                    update(AgentCanvasContinuationOutboxRow)
                    .where(
                        AgentCanvasContinuationOutboxRow.continuation_id == continuation_id,
                        AgentCanvasContinuationOutboxRow.status == "leased",
                        AgentCanvasContinuationOutboxRow.lease_owner == worker_id,
                        AgentCanvasContinuationOutboxRow.lease_generation == lease_generation,
                    )
                    .values(**values)
                )
                if result.rowcount != 1:
                    raise _stale_lease_error()
                updated = {**row, **values}
                event_type = {
                    "completed": "continuation_completed",
                    "retry_wait": "continuation_retry_scheduled",
                    "failed": "continuation_failed",
                    "superseded": "continuation_superseded",
                }[status]
                self._append_lifecycle_event(
                    connection,
                    updated,
                    event_type=event_type,
                    transition_key=(
                        "conversation:"
                        f"{row['continuation_turn_id']}:"
                        f"{event_type}:{lease_generation}"
                    ),
                    created_at=timestamp,
                )
                return _delivery(updated)
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def _append_lifecycle_event(
        self,
        connection: Connection,
        delivery: Mapping[str, Any],
        *,
        event_type: str,
        transition_key: str,
        created_at: datetime,
    ) -> None:
        payload = json.loads(str(delivery["payload_json"]))
        self._events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=str(delivery["workflow_id"]),
                conversation_id=str(delivery["conversation_id"]),
                turn_id=str(delivery["continuation_turn_id"]),
                event_type=event_type,
                transition_key=transition_key,
                created_at=_iso(created_at),
                payload={
                    "continuation_id": str(delivery["continuation_id"]),
                    "status": str(delivery["status"]),
                    "attempt": int(delivery["attempt_count"]),
                    "lease_generation": int(delivery["lease_generation"]),
                    "next_attempt_at": str(delivery["next_attempt_at"]),
                    "error_code": delivery["last_error_code"],
                    "occurrence_id": payload.get("occurrence_id"),
                    "character_phase": payload.get("character_phase"),
                    "action_owner": payload.get("action_owner"),
                },
            ),
        )


def _select_one(connection: Connection, continuation_id: str) -> RowMapping | None:
    return (
        connection.execute(
            select(AgentCanvasContinuationOutboxRow).where(
                AgentCanvasContinuationOutboxRow.continuation_id == continuation_id
            )
        )
        .mappings()
        .one_or_none()
    )


def _select_active_for_workflow(
    connection: Connection,
    workflow_id: str,
) -> RowMapping | None:
    return (
        connection.execute(
            select(AgentCanvasContinuationOutboxRow)
            .where(
                AgentCanvasContinuationOutboxRow.workflow_id == workflow_id,
                AgentCanvasContinuationOutboxRow.status.in_(("queued", "leased", "retry_wait")),
            )
            .order_by(
                AgentCanvasContinuationOutboxRow.created_at.asc(),
                AgentCanvasContinuationOutboxRow.continuation_id.asc(),
            )
        )
        .mappings()
        .first()
    )


def _require_same_enqueue(existing: RowMapping, expected: Mapping[str, Any]) -> None:
    identity_fields = (
        "workflow_id",
        "conversation_id",
        "source_turn_id",
        "continuation_turn_id",
        "operation",
        "payload_digest",
        "max_attempts",
    )
    if any(existing[field] != expected[field] for field in identity_fields):
        raise _error("idempotency_conflict", "Continuation identity was reused.")


def _require_owned(
    row: RowMapping,
    worker_id: str,
    lease_generation: int,
    now: datetime,
) -> None:
    if (
        row["status"] != "leased"
        or row["lease_owner"] != worker_id
        or int(row["lease_generation"]) != lease_generation
    ):
        raise _stale_lease_error()
    expires_at = _datetime(row["lease_expires_at"])
    if expires_at is None or expires_at < now:
        raise _stale_lease_error()


def _delivery(row: Mapping[str, Any]) -> ContinuationDeliveryV2:
    payload = json.loads(str(row["payload_json"]))
    return ContinuationDeliveryV2(
        continuation_id=str(row["continuation_id"]),
        workflow_id=str(row["workflow_id"]),
        conversation_id=str(row["conversation_id"]),
        source_turn_id=str(row["source_turn_id"]),
        continuation_turn_id=str(row["continuation_turn_id"]),
        operation=str(row["operation"]),
        envelope_id=str(payload["envelope_id"]),
        occurrence_id=payload.get("occurrence_id"),
        character_phase=payload.get("character_phase"),
        action_owner=payload.get("action_owner"),
        payload_digest=str(row["payload_digest"]),
        status=row["status"],
        attempt_count=int(row["attempt_count"]),
        max_attempts=int(row["max_attempts"]),
        next_attempt_at=_datetime(row["next_attempt_at"]),
        lease_owner=row["lease_owner"],
        lease_generation=int(row["lease_generation"]),
        lease_expires_at=_datetime(row["lease_expires_at"]),
        last_error_code=row["last_error_code"],
        last_error_message=row["last_error_message"],
        created_at=_datetime(row["created_at"]),
        updated_at=_datetime(row["updated_at"]),
    )


def _json(value: Mapping[str, object]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as error:
        raise _error(
            "continuation_payload_invalid",
            "Continuation payload must be JSON serializable.",
        ) from error


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise _error("continuation_time_invalid", "Continuation time must include a timezone.")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


def _datetime(value: object) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value))
    return _utc(parsed)


def _bounded(value: str | None, maximum: int) -> str | None:
    if value is None:
        return None
    return value[:maximum]


def _stale_lease_error() -> V2PersistenceError:
    return _error(
        "continuation_lease_stale",
        "Continuation lease has been superseded or expired.",
    )


def _persistence_error() -> V2PersistenceError:
    return _error(
        "continuation_persistence_unavailable",
        "Continuation persistence is temporarily unavailable.",
    )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message)
