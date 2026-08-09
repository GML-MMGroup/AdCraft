"""Durable dispatch of a post-publication Agent Canvas Next Action."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import func, insert, select

from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.agent_canvas_operation_envelope_repository import (
    AgentCanvasOperationEnvelopeRepository,
)
from app.persistence.database import V2Database
from app.persistence.event_repository import EventRepository
from app.persistence.models import AgentCanvasChatEntryRow, AgentCanvasChatTurnRow
from app.schemas.agent_canvas_capabilities import NextActionEnvelopeV1
from app.schemas.agent_canvas_conversation import ChatTurnV2
from app.schemas.v2_persistence import V2EventInsert


class NextActionDispatchService:
    """Persist one immutable post-selection Next Action delivery."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        self._database = database
        self._events = events
        self._envelopes = AgentCanvasOperationEnvelopeRepository(database)
        self._outbox = AgentCanvasContinuationOutboxRepository(database, events)

    def dispatch(
        self,
        source_turn: ChatTurnV2,
        *,
        session_id: str,
        expected_session_revision: int,
        objective: str,
    ) -> NextActionEnvelopeV1:
        digest = hashlib.sha256(
            (f"{source_turn.turn_id}:{session_id}:{expected_session_revision}:{objective}").encode(
                "utf-8"
            )
        ).hexdigest()
        envelope_id = f"envelope_{digest[:32]}"
        child_turn_id = f"turn_{digest[32:]}"
        continuation_id = f"continuation_{digest[:24]}"
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat()
        context_digest = hashlib.sha256(
            json.dumps(
                {
                    "workflow_id": source_turn.workflow_id,
                    "session_revision": expected_session_revision,
                    "objective": objective,
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        envelope = NextActionEnvelopeV1(
            envelope_id=envelope_id,
            workflow_id=source_turn.workflow_id,
            conversation_id=source_turn.conversation_id,
            source_turn_id=source_turn.turn_id,
            next_action_turn_id=child_turn_id,
            session_id=session_id,
            expected_session_revision=expected_session_revision,
            objective=objective,
            context_snapshot_id=f"snapshot_{context_digest[:32]}",
            context_snapshot_digest=context_digest,
            created_at=now,
        )
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    select(AgentCanvasChatTurnRow.turn_id).where(
                        AgentCanvasChatTurnRow.turn_id == child_turn_id
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    persisted = self._envelopes.get_in_transaction(connection, envelope_id)
                    if not isinstance(persisted, NextActionEnvelopeV1):
                        raise ValueError("Operation envelope type conflicts with Next Action.")
                    connection.commit()
                    return persisted
                connection.execute(
                    insert(AgentCanvasChatTurnRow).values(
                        turn_id=child_turn_id,
                        conversation_id=source_turn.conversation_id,
                        workflow_id=source_turn.workflow_id,
                        turn_kind="next_action",
                        status="queued",
                        request_json=json.dumps(
                            {"schema_version": "1", "envelope_id": envelope_id},
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        creation_mode_json=None,
                        guidance_session_revision=expected_session_revision,
                        idempotency_key=f"next-action:{envelope_id}",
                        error_code=None,
                        error_message=None,
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
                self._envelopes.create_in_transaction(connection, envelope)
                self._outbox.enqueue_in_transaction(
                    connection,
                    continuation_id=continuation_id,
                    workflow_id=source_turn.workflow_id,
                    conversation_id=source_turn.conversation_id,
                    source_turn_id=source_turn.turn_id,
                    continuation_turn_id=child_turn_id,
                    operation="next_action",
                    payload={"schema_version": "1", "envelope_id": envelope_id},
                    max_attempts=5,
                    now=now,
                )
                sequence_no = (
                    int(
                        connection.execute(
                            select(
                                func.coalesce(func.max(AgentCanvasChatEntryRow.sequence_no), 0)
                            ).where(
                                AgentCanvasChatEntryRow.conversation_id
                                == source_turn.conversation_id
                            )
                        ).scalar_one()
                    )
                    + 1
                )
                connection.execute(
                    insert(AgentCanvasChatEntryRow).values(
                        entry_id=f"entry_{digest[:32]}",
                        conversation_id=source_turn.conversation_id,
                        workflow_id=source_turn.workflow_id,
                        sequence_no=sequence_no,
                        entry_type="planning_progress",
                        speaker="adcraft_video_agent",
                        content="Planning the next creative action.",
                        metadata_json=json.dumps(
                            {"envelope_id": envelope_id, "operation": "next_action"},
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        created_at=timestamp,
                    )
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=source_turn.workflow_id,
                        conversation_id=source_turn.conversation_id,
                        turn_id=child_turn_id,
                        event_type="agent_command_queued",
                        transition_key=f"conversation:{child_turn_id}:agent_command_queued",
                        created_at=timestamp,
                        payload={"envelope_id": envelope_id, "operation": "next_action"},
                    ),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return envelope
