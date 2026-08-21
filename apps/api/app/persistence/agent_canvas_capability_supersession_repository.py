"""Atomic terminal publication for provably superseded guided capability work."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from app.persistence.agent_canvas_expert_activity_terminal_publication import (
    publish_expert_activity_terminal_in_transaction,
)
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasChatTurnRow,
    AgentCanvasContinuationOutboxRow,
    AgentCanvasExpertActivityRow,
)
from app.schemas.agent_canvas_creative_session import ExpertActivityV2
from app.schemas.v2_persistence import V2EventInsert


@dataclass(frozen=True, slots=True)
class CapabilitySupersessionPublication:
    continuation_id: str
    turn_id: str
    activity: ExpertActivityV2
    changed: bool


class AgentCanvasCapabilitySupersessionRepository:
    """Publish all mutable supersession projections through one SQLite transaction."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Capability supersession and events must share one database.")
        self._database = database
        self._events = events

    def publish(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        now: datetime,
    ) -> CapabilitySupersessionPublication:
        timestamp = now.astimezone(timezone.utc).isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    delivery = (
                        connection.execute(
                            select(AgentCanvasContinuationOutboxRow).where(
                                AgentCanvasContinuationOutboxRow.continuation_id == continuation_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if delivery is None:
                        raise _error("continuation_not_found", "Continuation was not found.")
                    turn_id = str(delivery["continuation_turn_id"])
                    turn = (
                        connection.execute(
                            select(AgentCanvasChatTurnRow).where(
                                AgentCanvasChatTurnRow.turn_id == turn_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    activity = (
                        connection.execute(
                            select(AgentCanvasExpertActivityRow).where(
                                AgentCanvasExpertActivityRow.turn_id == turn_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if turn is None or activity is None:
                        raise _error(
                            "guided_capability_supersession_conflict",
                            "Guided capability terminal lineage is incomplete.",
                        )
                    statuses = (
                        str(delivery["status"]),
                        str(turn["status"]),
                        str(activity["status"]),
                    )
                    if statuses == ("superseded", "superseded", "superseded"):
                        connection.commit()
                        return CapabilitySupersessionPublication(
                            continuation_id=continuation_id,
                            turn_id=turn_id,
                            activity=_activity(activity),
                            changed=False,
                        )
                    if statuses[1:] != ("queued", "working") and statuses[1:] != (
                        "running",
                        "working",
                    ):
                        raise _error(
                            "guided_capability_supersession_conflict",
                            "Guided capability terminal state changed before supersession.",
                        )
                    changed = connection.execute(
                        update(AgentCanvasContinuationOutboxRow)
                        .where(
                            AgentCanvasContinuationOutboxRow.continuation_id == continuation_id,
                            AgentCanvasContinuationOutboxRow.status == "leased",
                            AgentCanvasContinuationOutboxRow.lease_owner == worker_id,
                            AgentCanvasContinuationOutboxRow.lease_generation == lease_generation,
                            AgentCanvasContinuationOutboxRow.lease_expires_at > timestamp,
                        )
                        .values(
                            status="superseded",
                            lease_owner=None,
                            lease_expires_at=None,
                            last_error_code="continuation_superseded",
                            last_error_message="Guided capability work was superseded.",
                            updated_at=timestamp,
                        )
                    )
                    if changed.rowcount != 1:
                        raise _error(
                            "continuation_lease_stale",
                            "Continuation lease has been superseded or expired.",
                        )
                    turn_changed = connection.execute(
                        update(AgentCanvasChatTurnRow)
                        .where(
                            AgentCanvasChatTurnRow.turn_id == turn_id,
                            AgentCanvasChatTurnRow.status.in_(("queued", "running")),
                        )
                        .values(
                            status="superseded",
                            retryable=False,
                            operation_stage="superseded",
                            operation_failure_json=None,
                            error_code=None,
                            error_message=None,
                            updated_at=timestamp,
                        )
                    )
                    if turn_changed.rowcount != 1:
                        raise _error(
                            "guided_capability_supersession_conflict",
                            "Guided capability Turn changed before supersession.",
                        )
                    expert = publish_expert_activity_terminal_in_transaction(
                        connection,
                        self._events,
                        turn_id=turn_id,
                        status="superseded",
                        now=timestamp,
                    )
                    payload = {
                        "continuation_id": continuation_id,
                        "turn_id": turn_id,
                        "activity_id": expert.activity.activity_id,
                        "capability_id": expert.activity.capability_id,
                        "operation": expert.activity.operation,
                        "status": "superseded",
                    }
                    workflow_id = str(delivery["workflow_id"])
                    conversation_id = str(delivery["conversation_id"])
                    for event_type in (
                        "continuation_superseded",
                        "agent_command_superseded",
                        "agent_turn_superseded",
                        "agent_operation_superseded",
                    ):
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=workflow_id,
                                conversation_id=conversation_id,
                                turn_id=turn_id,
                                event_type=event_type,
                                transition_key=f"conversation:{turn_id}:{event_type}",
                                created_at=timestamp,
                                payload=payload,
                            ),
                        )
                    connection.commit()
                    return CapabilitySupersessionPublication(
                        continuation_id=continuation_id,
                        turn_id=turn_id,
                        activity=expert.activity,
                        changed=True,
                    )
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "guided_capability_supersession_unavailable",
                "Guided capability supersession could not be persisted.",
            ) from error


def _activity(row) -> ExpertActivityV2:
    return ExpertActivityV2(
        activity_id=str(row["activity_id"]),
        workflow_id=str(row["workflow_id"]),
        turn_id=str(row["turn_id"]),
        capability_id=cast(str, row["capability_id"]),
        capability_display_name=str(row["display_name"]),
        operation=cast(str, row["operation"]),
        status=cast(str, row["status"]),
        error_code=str(row["error_code"]) if row["error_code"] else None,
        error_message=str(row["error_message"]) if row["error_message"] else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="guided_capability_supersession")
