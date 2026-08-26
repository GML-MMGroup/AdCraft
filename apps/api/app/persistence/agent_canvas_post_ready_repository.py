"""Durable fenced persistence for Agent Canvas post-Ready effects."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import cast

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import AgentCanvasPostReadyEffectRow
from app.schemas.agent_canvas import CanvasNodeErrorV2
from app.schemas.agent_canvas_runtime_authority import CanvasPostReadyEffectV2
from app.schemas.agent_canvas_media_review_authority import (
    CanvasPostReadyEffectDispositionV1,
)
from app.schemas.v2_persistence import V2EventInsert


class AgentCanvasPostReadyEffectRepository:
    """Claim and finish typed post-Ready effects through renewable ownership."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Post-Ready effects and events must share one database.")
        self._database = database
        self._events = events

    def claim_due(
        self,
        *,
        worker_id: str,
        now: datetime,
        batch_limit: int,
        lease_duration: timedelta,
    ) -> tuple[CanvasPostReadyEffectV2, ...]:
        if batch_limit < 1 or lease_duration <= timedelta(0):
            raise _error("post_ready_claim_invalid", "Post-Ready claim settings are invalid.")
        timestamp = _utc(now)
        now_value = timestamp.isoformat()
        expires_at = (timestamp + lease_duration).isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    rows = (
                        connection.execute(
                            select(AgentCanvasPostReadyEffectRow)
                            .where(
                                or_(
                                    and_(
                                        AgentCanvasPostReadyEffectRow.status == "queued",
                                        AgentCanvasPostReadyEffectRow.updated_at <= now_value,
                                    ),
                                    and_(
                                        AgentCanvasPostReadyEffectRow.status == "running",
                                        AgentCanvasPostReadyEffectRow.lease_expires_at <= now_value,
                                    ),
                                )
                            )
                            .order_by(
                                AgentCanvasPostReadyEffectRow.updated_at.asc(),
                                AgentCanvasPostReadyEffectRow.effect_id.asc(),
                            )
                            .limit(batch_limit)
                        )
                        .mappings()
                        .all()
                    )
                    claimed: list[CanvasPostReadyEffectV2] = []
                    for row in rows:
                        generation = int(row["lease_generation"]) + 1
                        changed = connection.execute(
                            update(AgentCanvasPostReadyEffectRow)
                            .where(
                                AgentCanvasPostReadyEffectRow.effect_id == row["effect_id"],
                                AgentCanvasPostReadyEffectRow.status == row["status"],
                                AgentCanvasPostReadyEffectRow.lease_generation
                                == row["lease_generation"],
                            )
                            .values(
                                status="running",
                                lease_owner_id=worker_id,
                                lease_generation=generation,
                                lease_expires_at=expires_at,
                                updated_at=now_value,
                            )
                        )
                        if changed.rowcount != 1:
                            continue
                        updated = {
                            **row,
                            "status": "running",
                            "lease_owner_id": worker_id,
                            "lease_generation": generation,
                            "lease_expires_at": expires_at,
                            "updated_at": now_value,
                        }
                        self._append_event(
                            connection,
                            updated,
                            "post_ready_effect_started",
                            timestamp,
                        )
                        claimed.append(_effect(updated))
                    connection.commit()
                    return tuple(claimed)
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "post_ready_effect_unavailable",
                "Post-Ready effects are temporarily unavailable.",
            ) from error

    def complete(
        self,
        effect: CanvasPostReadyEffectV2,
        *,
        now: datetime,
        disposition: CanvasPostReadyEffectDispositionV1,
    ) -> CanvasPostReadyEffectV2:
        return self._finish(
            effect,
            status="completed",
            now=now,
            error=None,
            disposition=disposition,
        )

    def renew(
        self,
        effect: CanvasPostReadyEffectV2,
        *,
        now: datetime,
        lease_duration: timedelta,
    ) -> CanvasPostReadyEffectV2:
        if lease_duration <= timedelta(0):
            raise _error("post_ready_claim_invalid", "Post-Ready lease must be positive.")
        timestamp = _utc(now)
        expires_at = (timestamp + lease_duration).isoformat()
        try:
            with self._database.engine.begin() as connection:
                changed = connection.execute(
                    update(AgentCanvasPostReadyEffectRow)
                    .where(
                        AgentCanvasPostReadyEffectRow.effect_id == effect.effect_id,
                        AgentCanvasPostReadyEffectRow.status == "running",
                        AgentCanvasPostReadyEffectRow.lease_owner_id == effect.lease_owner_id,
                        AgentCanvasPostReadyEffectRow.lease_generation == effect.lease_generation,
                        AgentCanvasPostReadyEffectRow.lease_expires_at > timestamp.isoformat(),
                    )
                    .values(lease_expires_at=expires_at, updated_at=timestamp.isoformat())
                )
                if changed.rowcount != 1:
                    raise _error(
                        "post_ready_effect_lease_stale",
                        "Post-Ready effect ownership was lost.",
                    )
            return effect.model_copy(
                update={"lease_expires_at": timestamp + lease_duration, "updated_at": timestamp}
            )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "post_ready_effect_unavailable",
                "Post-Ready lease could not be renewed.",
            ) from error

    def retry(
        self,
        effect: CanvasPostReadyEffectV2,
        *,
        now: datetime,
        retry_at: datetime,
        error: CanvasNodeErrorV2,
    ) -> CanvasPostReadyEffectV2:
        return self._finish(
            effect,
            status="queued",
            now=now,
            error=error,
            available_at=retry_at,
            increment_attempt=True,
        )

    def defer(
        self,
        effect: CanvasPostReadyEffectV2,
        *,
        now: datetime,
        retry_at: datetime,
        error: CanvasNodeErrorV2,
    ) -> CanvasPostReadyEffectV2:
        return self._finish(
            effect,
            status="queued",
            now=now,
            error=error,
            available_at=retry_at,
        )

    def fail(
        self,
        effect: CanvasPostReadyEffectV2,
        *,
        now: datetime,
        error: CanvasNodeErrorV2,
    ) -> CanvasPostReadyEffectV2:
        return self._finish(
            effect,
            status="failed",
            now=now,
            error=error,
            increment_attempt=True,
        )

    def list_for_workflow(self, workflow_id: str) -> tuple[CanvasPostReadyEffectV2, ...]:
        with self._database.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(AgentCanvasPostReadyEffectRow)
                    .where(AgentCanvasPostReadyEffectRow.workflow_id == workflow_id)
                    .order_by(AgentCanvasPostReadyEffectRow.created_at.asc())
                )
                .mappings()
                .all()
            )
        return tuple(_effect(row) for row in rows)

    def _finish(
        self,
        effect: CanvasPostReadyEffectV2,
        *,
        status: str,
        now: datetime,
        error: CanvasNodeErrorV2 | None,
        disposition: CanvasPostReadyEffectDispositionV1 | None = None,
        available_at: datetime | None = None,
        increment_attempt: bool = False,
    ) -> CanvasPostReadyEffectV2:
        timestamp = _utc(now)
        updated_at = _utc(available_at).isoformat() if available_at else timestamp.isoformat()
        values = {
            "status": status,
            "attempt_no": effect.attempt_no + int(increment_attempt),
            "lease_owner_id": None,
            "lease_expires_at": None,
            "error_json": error.model_dump_json() if error else None,
            "updated_at": updated_at,
        }
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    changed = connection.execute(
                        update(AgentCanvasPostReadyEffectRow)
                        .where(
                            AgentCanvasPostReadyEffectRow.effect_id == effect.effect_id,
                            AgentCanvasPostReadyEffectRow.status == "running",
                            AgentCanvasPostReadyEffectRow.lease_owner_id == effect.lease_owner_id,
                            AgentCanvasPostReadyEffectRow.lease_generation
                            == effect.lease_generation,
                            AgentCanvasPostReadyEffectRow.lease_expires_at > timestamp.isoformat(),
                        )
                        .values(**values)
                    )
                    if changed.rowcount != 1:
                        raise _error(
                            "post_ready_effect_lease_stale",
                            "Post-Ready effect ownership was lost.",
                        )
                    row = (
                        connection.execute(
                            select(AgentCanvasPostReadyEffectRow).where(
                                AgentCanvasPostReadyEffectRow.effect_id == effect.effect_id
                            )
                        )
                        .mappings()
                        .one()
                    )
                    self._append_event(
                        connection,
                        row,
                        {
                            "completed": "post_ready_effect_completed",
                            "queued": "post_ready_effect_retry_scheduled",
                            "failed": "post_ready_effect_failed",
                        }[status],
                        timestamp,
                        disposition=disposition,
                    )
                    connection.commit()
                    return _effect(row)
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as sql_error:
            raise _error(
                "post_ready_effect_unavailable",
                "Post-Ready effect state could not be updated.",
            ) from sql_error

    def _append_event(
        self,
        connection,
        row: RowMapping | dict[str, object],
        event_type: str,
        now: datetime,
        disposition: CanvasPostReadyEffectDispositionV1 | None = None,
    ) -> None:
        error_code = None
        if row.get("error_json"):
            try:
                error_code = json.loads(str(row["error_json"])).get("code")
            except (TypeError, ValueError):
                error_code = None
        self._events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=str(row["workflow_id"]),
                node_id=str(row["node_id"]),
                transition_key=(
                    f"post-ready:{row['effect_id']}:{event_type}:"
                    f"{row['lease_generation']}:{row['attempt_no']}"
                ),
                event_type=event_type,
                created_at=now.isoformat(),
                payload={
                    "effect_id": str(row["effect_id"]),
                    "effect_type": str(row["effect_type"]),
                    "attempt_no": int(row["attempt_no"]),
                    **({"error_code": error_code} if error_code is not None else {}),
                    **(
                        {
                            "disposition": disposition.outcome,
                            "reason_code": disposition.reason_code,
                            **(
                                {"interaction_id": disposition.interaction_id}
                                if disposition.interaction_id is not None
                                else {}
                            ),
                        }
                        if disposition is not None
                        else {}
                    ),
                },
            ),
        )


def _effect(row: RowMapping | dict[str, object]) -> CanvasPostReadyEffectV2:
    error_json = row.get("error_json")
    return CanvasPostReadyEffectV2(
        effect_id=str(row["effect_id"]),
        effect_type=cast(str, row["effect_type"]),
        source_commit_id=str(row["source_commit_id"]),
        workflow_id=str(row["workflow_id"]),
        node_id=str(row["node_id"]),
        payload_digest=str(row["payload_digest"]),
        payload=json.loads(str(row["payload_json"])),
        status=cast(str, row["status"]),
        attempt_no=int(row["attempt_no"]),
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
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_post_ready_repository")
