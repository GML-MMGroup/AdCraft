"""Durable fenced authority for accepted guided media resume delivery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast

from pydantic import TypeAdapter
from sqlalchemy import and_, insert, or_, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasGuidedInteractionSubmissionRow,
    AgentCanvasGuidedMediaResumeDeliveryRow,
)
from app.schemas.agent_canvas_errors import CanvasNodeErrorV2
from app.schemas.agent_canvas_guided_interactions import (
    GuidedInteractionAcceptedV1,
    GuidedInteractionSubmitRequestV1,
    GuidedMediaReviewSubmitV1,
)
from app.schemas.agent_canvas_guided_media_resume import (
    GuidedMediaConfirmationResumeDeliveryV1,
    guided_media_resume_delivery_id,
)
from app.schemas.v2_persistence import V2EventInsert


class AgentCanvasGuidedMediaResumeRepository:
    """Publish, claim, and finish one private confirmation-resume delivery."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Guided media resume deliveries and events must share one database.")
        self._database = database
        self._events = events

    @property
    def database(self) -> V2Database:
        return self._database

    def enqueue_in_transaction(
        self,
        connection: Connection,
        delivery: GuidedMediaConfirmationResumeDeliveryV1,
    ) -> GuidedMediaConfirmationResumeDeliveryV1:
        existing = (
            connection.execute(
                select(AgentCanvasGuidedMediaResumeDeliveryRow).where(
                    or_(
                        AgentCanvasGuidedMediaResumeDeliveryRow.delivery_id == delivery.delivery_id,
                        AgentCanvasGuidedMediaResumeDeliveryRow.submission_id
                        == delivery.submission_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            persisted = _delivery(existing)
            if (
                persisted.delivery_id != delivery.delivery_id
                or persisted.workflow_id != delivery.workflow_id
                or persisted.submission_id != delivery.submission_id
                or persisted.confirmation_id != delivery.confirmation_id
            ):
                raise _error(
                    "guided_media_resume_delivery_conflict",
                    "Guided media resume identity conflicts with persisted evidence.",
                )
            return persisted
        connection.execute(
            insert(AgentCanvasGuidedMediaResumeDeliveryRow).values(**_row_values(delivery))
        )
        self._append_event(
            connection,
            delivery,
            event_type="guided_media_resume_queued",
            now=delivery.created_at,
        )
        return delivery

    def ensure_for_submission(
        self,
        submission_id: str,
        *,
        now: datetime | None = None,
    ) -> GuidedMediaConfirmationResumeDeliveryV1 | None:
        """Lazily adopt one exact pre-migration accepted media submission."""

        timestamp = _utc(now or datetime.now(timezone.utc))
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    submission = (
                        connection.execute(
                            select(AgentCanvasGuidedInteractionSubmissionRow).where(
                                AgentCanvasGuidedInteractionSubmissionRow.submission_id
                                == submission_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if submission is None:
                        raise _error(
                            "guided_media_resume_delivery_unavailable",
                            "Accepted guided interaction submission was not found.",
                        )
                    request = TypeAdapter(GuidedInteractionSubmitRequestV1).validate_json(
                        str(submission["request_json"])
                    )
                    result_json = submission["result_json"]
                    if not isinstance(request, GuidedMediaReviewSubmitV1) or (
                        request.action != "accept"
                    ):
                        connection.rollback()
                        return None
                    if result_json is None:
                        raise _error(
                            "guided_media_resume_delivery_conflict",
                            "Accepted media submission has no durable result.",
                        )
                    result = GuidedInteractionAcceptedV1.model_validate_json(str(result_json))
                    if result.submission_id != submission_id or not result.receipt_id:
                        raise _error(
                            "guided_media_resume_delivery_conflict",
                            "Accepted media submission result has conflicting evidence.",
                        )
                    delivery = queued_guided_media_resume_delivery(
                        workflow_id=str(submission["workflow_id"]),
                        submission_id=submission_id,
                        confirmation_id=result.receipt_id,
                        now=timestamp,
                    )
                    persisted = self.enqueue_in_transaction(connection, delivery)
                    connection.commit()
                    return persisted
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except Exception as error:
            raise _error(
                "guided_media_resume_delivery_unavailable",
                "Guided media resume delivery is temporarily unavailable.",
            ) from error

    def get(self, delivery_id: str) -> GuidedMediaConfirmationResumeDeliveryV1:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasGuidedMediaResumeDeliveryRow).where(
                            AgentCanvasGuidedMediaResumeDeliveryRow.delivery_id == delivery_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _unavailable() from error
        if row is None:
            raise _error(
                "guided_media_resume_delivery_unavailable",
                "Guided media resume delivery was not found.",
            )
        return _delivery(row)

    def get_for_submission(
        self,
        submission_id: str,
    ) -> GuidedMediaConfirmationResumeDeliveryV1 | None:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasGuidedMediaResumeDeliveryRow).where(
                            AgentCanvasGuidedMediaResumeDeliveryRow.submission_id == submission_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _unavailable() from error
        return _delivery(row) if row is not None else None

    def claim_due(
        self,
        *,
        worker_id: str,
        now: datetime,
        batch_limit: int,
        lease_duration: timedelta,
        delivery_id: str | None = None,
    ) -> tuple[GuidedMediaConfirmationResumeDeliveryV1, ...]:
        if batch_limit < 1 or lease_duration <= timedelta(0):
            raise _error(
                "guided_media_resume_lease_unavailable",
                "Guided media resume claim settings are invalid.",
            )
        timestamp = _utc(now)
        now_value = timestamp.isoformat()
        expires_at = (timestamp + lease_duration).isoformat()
        due = or_(
            and_(
                AgentCanvasGuidedMediaResumeDeliveryRow.status == "queued",
                AgentCanvasGuidedMediaResumeDeliveryRow.available_at <= now_value,
            ),
            and_(
                AgentCanvasGuidedMediaResumeDeliveryRow.status == "running",
                AgentCanvasGuidedMediaResumeDeliveryRow.lease_expires_at <= now_value,
            ),
        )
        conditions = [
            due,
            AgentCanvasGuidedMediaResumeDeliveryRow.attempt_no
            < AgentCanvasGuidedMediaResumeDeliveryRow.max_attempts,
        ]
        if delivery_id is not None:
            conditions.append(AgentCanvasGuidedMediaResumeDeliveryRow.delivery_id == delivery_id)
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    rows = (
                        connection.execute(
                            select(AgentCanvasGuidedMediaResumeDeliveryRow)
                            .where(*conditions)
                            .order_by(
                                AgentCanvasGuidedMediaResumeDeliveryRow.available_at.asc(),
                                AgentCanvasGuidedMediaResumeDeliveryRow.created_at.asc(),
                                AgentCanvasGuidedMediaResumeDeliveryRow.delivery_id.asc(),
                            )
                            .limit(batch_limit)
                        )
                        .mappings()
                        .all()
                    )
                    claimed: list[GuidedMediaConfirmationResumeDeliveryV1] = []
                    for row in rows:
                        generation = int(row["lease_generation"]) + 1
                        attempt_no = int(row["attempt_no"]) + 1
                        changed = connection.execute(
                            update(AgentCanvasGuidedMediaResumeDeliveryRow)
                            .where(
                                AgentCanvasGuidedMediaResumeDeliveryRow.delivery_id
                                == row["delivery_id"],
                                AgentCanvasGuidedMediaResumeDeliveryRow.status == row["status"],
                                AgentCanvasGuidedMediaResumeDeliveryRow.lease_generation
                                == row["lease_generation"],
                            )
                            .values(
                                status="running",
                                attempt_no=attempt_no,
                                lease_owner_id=worker_id,
                                lease_generation=generation,
                                lease_expires_at=expires_at,
                                error_json=None,
                                terminal_at=None,
                                updated_at=now_value,
                            )
                        )
                        if changed.rowcount != 1:
                            continue
                        claimed.append(
                            _delivery(
                                {
                                    **row,
                                    "status": "running",
                                    "attempt_no": attempt_no,
                                    "lease_owner_id": worker_id,
                                    "lease_generation": generation,
                                    "lease_expires_at": expires_at,
                                    "error_json": None,
                                    "terminal_at": None,
                                    "updated_at": now_value,
                                }
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
            raise _error(
                "guided_media_resume_lease_unavailable",
                "Guided media resume delivery could not be claimed.",
            ) from error

    def renew(
        self,
        delivery: GuidedMediaConfirmationResumeDeliveryV1,
        *,
        now: datetime,
        lease_duration: timedelta,
    ) -> GuidedMediaConfirmationResumeDeliveryV1:
        if lease_duration <= timedelta(0):
            raise _error(
                "guided_media_resume_lease_unavailable",
                "Guided media resume lease duration must be positive.",
            )
        timestamp = _utc(now)
        expires_at = timestamp + lease_duration
        try:
            with self._database.engine.begin() as connection:
                changed = connection.execute(
                    update(AgentCanvasGuidedMediaResumeDeliveryRow)
                    .where(*_lease_filter(delivery, timestamp))
                    .values(
                        lease_expires_at=expires_at.isoformat(),
                        updated_at=timestamp.isoformat(),
                    )
                )
                if changed.rowcount != 1:
                    raise _stale_lease()
            return delivery.model_copy(
                update={"lease_expires_at": expires_at, "updated_at": timestamp}
            )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _unavailable() from error

    def complete(
        self,
        delivery: GuidedMediaConfirmationResumeDeliveryV1,
        *,
        now: datetime,
    ) -> GuidedMediaConfirmationResumeDeliveryV1:
        return self._finish(delivery, status="completed", now=now, error=None)

    def defer(
        self,
        delivery: GuidedMediaConfirmationResumeDeliveryV1,
        *,
        now: datetime,
        retry_at: datetime,
    ) -> GuidedMediaConfirmationResumeDeliveryV1:
        if delivery.attempt_no >= delivery.max_attempts:
            return self.fail(
                delivery,
                now=now,
                error=CanvasNodeErrorV2(
                    code="guided_media_resume_failed",
                    message="Guided media resume exhausted its bounded attempts.",
                    retryable=False,
                ),
            )
        return self._finish(
            delivery,
            status="queued",
            now=now,
            error=None,
            available_at=retry_at,
        )

    def fail(
        self,
        delivery: GuidedMediaConfirmationResumeDeliveryV1,
        *,
        now: datetime,
        error: CanvasNodeErrorV2,
    ) -> GuidedMediaConfirmationResumeDeliveryV1:
        return self._finish(delivery, status="failed", now=now, error=error)

    def list_nonterminal(self) -> tuple[GuidedMediaConfirmationResumeDeliveryV1, ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasGuidedMediaResumeDeliveryRow)
                        .where(
                            AgentCanvasGuidedMediaResumeDeliveryRow.status.in_(
                                ("queued", "running")
                            )
                        )
                        .order_by(
                            AgentCanvasGuidedMediaResumeDeliveryRow.created_at.asc(),
                            AgentCanvasGuidedMediaResumeDeliveryRow.delivery_id.asc(),
                        )
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _unavailable() from error
        return tuple(_delivery(row) for row in rows)

    def _finish(
        self,
        delivery: GuidedMediaConfirmationResumeDeliveryV1,
        *,
        status: str,
        now: datetime,
        error: CanvasNodeErrorV2 | None,
        available_at: datetime | None = None,
    ) -> GuidedMediaConfirmationResumeDeliveryV1:
        timestamp = _utc(now)
        values = {
            "status": status,
            "available_at": _utc(available_at or timestamp).isoformat(),
            "lease_owner_id": None,
            "lease_expires_at": None,
            "error_json": error.model_dump_json() if error else None,
            "updated_at": timestamp.isoformat(),
            "terminal_at": timestamp.isoformat() if status in {"completed", "failed"} else None,
        }
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    changed = connection.execute(
                        update(AgentCanvasGuidedMediaResumeDeliveryRow)
                        .where(*_lease_filter(delivery, timestamp))
                        .values(**values)
                    )
                    if changed.rowcount != 1:
                        raise _stale_lease()
                    row = (
                        connection.execute(
                            select(AgentCanvasGuidedMediaResumeDeliveryRow).where(
                                AgentCanvasGuidedMediaResumeDeliveryRow.delivery_id
                                == delivery.delivery_id
                            )
                        )
                        .mappings()
                        .one()
                    )
                    persisted = _delivery(row)
                    if status in {"completed", "failed"}:
                        self._append_event(
                            connection,
                            persisted,
                            event_type=f"guided_media_resume_{status}",
                            now=timestamp,
                        )
                    connection.commit()
                    return persisted
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as sql_error:
            raise _unavailable() from sql_error

    def _append_event(
        self,
        connection: Connection,
        delivery: GuidedMediaConfirmationResumeDeliveryV1,
        *,
        event_type: str,
        now: datetime,
    ) -> None:
        payload: dict[str, object] = {
            "delivery_id": delivery.delivery_id,
            "submission_id": delivery.submission_id,
            "confirmation_id": delivery.confirmation_id,
            "status": delivery.status,
            "attempt_no": delivery.attempt_no,
        }
        if delivery.error is not None:
            payload["error_code"] = delivery.error.code
        self._events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=delivery.workflow_id,
                action_id=delivery.submission_id,
                event_type=event_type,
                transition_key=f"guided-media-resume:{delivery.delivery_id}:{event_type}",
                created_at=now.isoformat(),
                payload=payload,
            ),
        )


def queued_guided_media_resume_delivery(
    *,
    workflow_id: str,
    submission_id: str,
    confirmation_id: str,
    now: datetime,
) -> GuidedMediaConfirmationResumeDeliveryV1:
    timestamp = _utc(now)
    return GuidedMediaConfirmationResumeDeliveryV1(
        delivery_id=guided_media_resume_delivery_id(submission_id, confirmation_id),
        workflow_id=workflow_id,
        submission_id=submission_id,
        confirmation_id=confirmation_id,
        status="queued",
        attempt_no=0,
        max_attempts=2,
        available_at=timestamp,
        lease_generation=0,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _lease_filter(
    delivery: GuidedMediaConfirmationResumeDeliveryV1,
    now: datetime,
) -> tuple[object, ...]:
    return (
        AgentCanvasGuidedMediaResumeDeliveryRow.delivery_id == delivery.delivery_id,
        AgentCanvasGuidedMediaResumeDeliveryRow.status == "running",
        AgentCanvasGuidedMediaResumeDeliveryRow.lease_owner_id == delivery.lease_owner_id,
        AgentCanvasGuidedMediaResumeDeliveryRow.lease_generation == delivery.lease_generation,
        AgentCanvasGuidedMediaResumeDeliveryRow.lease_expires_at > now.isoformat(),
    )


def _row_values(delivery: GuidedMediaConfirmationResumeDeliveryV1) -> dict[str, object]:
    return {
        "delivery_id": delivery.delivery_id,
        "workflow_id": delivery.workflow_id,
        "submission_id": delivery.submission_id,
        "confirmation_id": delivery.confirmation_id,
        "status": delivery.status,
        "attempt_no": delivery.attempt_no,
        "max_attempts": delivery.max_attempts,
        "available_at": delivery.available_at.isoformat(),
        "lease_owner_id": delivery.lease_owner_id,
        "lease_generation": delivery.lease_generation,
        "lease_expires_at": (
            delivery.lease_expires_at.isoformat() if delivery.lease_expires_at else None
        ),
        "error_json": delivery.error.model_dump_json() if delivery.error else None,
        "created_at": delivery.created_at.isoformat(),
        "updated_at": delivery.updated_at.isoformat(),
        "terminal_at": delivery.terminal_at.isoformat() if delivery.terminal_at else None,
    }


def _delivery(
    row: RowMapping | dict[str, object],
) -> GuidedMediaConfirmationResumeDeliveryV1:
    error_json = row.get("error_json")
    return GuidedMediaConfirmationResumeDeliveryV1(
        delivery_id=str(row["delivery_id"]),
        workflow_id=str(row["workflow_id"]),
        submission_id=str(row["submission_id"]),
        confirmation_id=str(row["confirmation_id"]),
        status=cast(str, row["status"]),
        attempt_no=int(row["attempt_no"]),
        max_attempts=cast(int, row["max_attempts"]),
        available_at=datetime.fromisoformat(str(row["available_at"])),
        lease_owner_id=cast(str | None, row["lease_owner_id"]),
        lease_generation=int(row["lease_generation"]),
        lease_expires_at=(
            datetime.fromisoformat(str(row["lease_expires_at"]))
            if row["lease_expires_at"]
            else None
        ),
        error=(CanvasNodeErrorV2.model_validate_json(str(error_json)) if error_json else None),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
        terminal_at=(
            datetime.fromisoformat(str(row["terminal_at"])) if row["terminal_at"] else None
        ),
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _stale_lease() -> V2PersistenceError:
    return _error(
        "stale_guided_media_resume_lease",
        "Guided media resume delivery ownership was lost.",
    )


def _unavailable() -> V2PersistenceError:
    return _error(
        "guided_media_resume_delivery_unavailable",
        "Guided media resume delivery is temporarily unavailable.",
    )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(
        code,
        message,
        stage="agent_canvas_guided_media_resume_repository",
    )
