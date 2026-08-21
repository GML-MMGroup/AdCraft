"""Transaction-scoped terminal publication for one expert activity."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Literal, Mapping, cast
from uuid import uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, RowMapping

from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasChatEntryRow,
    AgentCanvasChatTurnRow,
    AgentCanvasExpertActivityRow,
    AgentCanvasGuidanceSessionRow,
)
from app.schemas.agent_canvas_capability_identity import CAPABILITY_DISPLAY_NAMES
from app.schemas.agent_canvas_creative_session import ExpertActivityV2
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_user_presentation import build_presentation_metadata


TerminalExpertActivityStatus = Literal["completed", "failed", "superseded"]


@dataclass(frozen=True, slots=True)
class ExpertActivityTerminalPublication:
    activity: ExpertActivityV2
    changed: bool


def publish_expert_activity_terminal_in_transaction(
    connection: Connection,
    events: EventRepository,
    *,
    status: TerminalExpertActivityStatus,
    now: str,
    activity_id: str | None = None,
    turn_id: str | None = None,
    response_locale: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    event_details: Mapping[str, object] | None = None,
) -> ExpertActivityTerminalPublication:
    """Publish terminal row, event, and Timeline state through the caller's transaction."""

    if (activity_id is None) == (turn_id is None):
        raise ValueError("Exactly one expert activity identity is required.")
    selector = (
        AgentCanvasExpertActivityRow.activity_id == activity_id
        if activity_id is not None
        else AgentCanvasExpertActivityRow.turn_id == turn_id
    )
    row = (
        connection.execute(select(AgentCanvasExpertActivityRow).where(selector))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _error("expert_activity_not_found", "Expert activity was not found.")
    current_status = str(row["status"])
    if current_status in {"completed", "failed", "superseded"}:
        if current_status == status:
            return ExpertActivityTerminalPublication(
                activity=_activity(row),
                changed=False,
            )
        raise _error(
            "expert_activity_terminal",
            "Expert activity already reached a terminal state.",
        )
    if current_status != "working":
        raise _error(
            "expert_activity_status_invalid",
            "Expert activity status is invalid.",
        )

    activity_identity = str(row["activity_id"])
    workflow_id = str(row["workflow_id"])
    activity_turn_id = str(row["turn_id"])
    turn = (
        connection.execute(
            select(AgentCanvasChatTurnRow).where(AgentCanvasChatTurnRow.turn_id == activity_turn_id)
        )
        .mappings()
        .one_or_none()
    )
    if turn is None:
        raise _error("agent_turn_not_found", "Agent turn was not found.")
    conversation_id = str(turn["conversation_id"])
    capability_id = cast(str, row["capability_id"])
    display_name = str(row["display_name"]).strip() or CAPABILITY_DISPLAY_NAMES[capability_id]
    locale = response_locale or _guidance_response_locale(connection, workflow_id)
    canonical = {
        **dict(event_details or {}),
        "activity_id": activity_identity,
        "workflow_id": workflow_id,
        "turn_id": activity_turn_id,
        "capability_id": capability_id,
        "operation": str(row["operation"]),
        "capability_display_name": display_name,
        "status": status,
        "error_code": error_code,
        "conversation_id": conversation_id,
        "created_at": now,
    }

    connection.execute(
        update(AgentCanvasExpertActivityRow)
        .where(AgentCanvasExpertActivityRow.activity_id == activity_identity)
        .values(
            status=status,
            error_code=error_code,
            error_message=error_message,
            updated_at=now,
        )
    )
    events.append_in_transaction(
        connection,
        V2EventInsert(
            workflow_id=workflow_id,
            conversation_id=conversation_id,
            turn_id=activity_turn_id,
            event_type=f"expert_activity_{status}",
            transition_key=f"conversation:{activity_turn_id}:expert_activity_{status}",
            created_at=now,
            payload=canonical,
        ),
    )
    connection.execute(
        insert(AgentCanvasChatEntryRow).values(
            entry_id=f"entry_{uuid4().hex}",
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            sequence_no=_next_sequence(connection, conversation_id),
            entry_type="expert_activity",
            speaker=None,
            content=display_name,
            metadata_json=json.dumps(
                build_presentation_metadata(
                    message_key=f"expert_activity.{status}",
                    message_args={"capability_display_name": display_name},
                    response_locale=locale,
                    presentation_key=f"activity:{activity_identity}",
                    base=canonical,
                ),
                separators=(",", ":"),
                sort_keys=True,
            ),
            created_at=now,
        )
    )
    return ExpertActivityTerminalPublication(
        activity=ExpertActivityV2(
            activity_id=activity_identity,
            workflow_id=workflow_id,
            turn_id=activity_turn_id,
            capability_id=capability_id,
            capability_display_name=display_name,
            operation=cast(str, row["operation"]),
            status=status,
            error_code=error_code,
            error_message=error_message,
            created_at=str(row["created_at"]),
            updated_at=now,
        ),
        changed=True,
    )


def _next_sequence(connection: Connection, conversation_id: str) -> int:
    return (
        int(
            connection.execute(
                select(func.coalesce(func.max(AgentCanvasChatEntryRow.sequence_no), 0)).where(
                    AgentCanvasChatEntryRow.conversation_id == conversation_id
                )
            ).scalar_one()
        )
        + 1
    )


def _guidance_response_locale(connection: Connection, workflow_id: str) -> str:
    value = connection.execute(
        select(AgentCanvasGuidanceSessionRow.response_locale).where(
            AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
        )
    ).scalar_one_or_none()
    return str(value or "und")


def _activity(row: RowMapping) -> ExpertActivityV2:
    capability_id = cast(str, row["capability_id"])
    display_name = str(row["display_name"]).strip() or CAPABILITY_DISPLAY_NAMES[capability_id]
    return ExpertActivityV2(
        activity_id=str(row["activity_id"]),
        workflow_id=str(row["workflow_id"]),
        turn_id=str(row["turn_id"]),
        capability_id=capability_id,
        capability_display_name=display_name,
        operation=cast(str, row["operation"]),
        status=cast(str, row["status"]),
        error_code=str(row["error_code"]) if row["error_code"] else None,
        error_message=str(row["error_message"]) if row["error_message"] else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_conversation_repository")
