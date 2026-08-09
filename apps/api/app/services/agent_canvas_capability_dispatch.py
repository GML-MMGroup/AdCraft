"""Atomic accepted-command dispatch for Agent Canvas capabilities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import func, insert, select, update

from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.agent_canvas_operation_envelope_repository import (
    AgentCanvasOperationEnvelopeRepository,
)
from app.persistence.database import V2Database
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasChatEntryRow,
    AgentCanvasChatTurnRow,
    AgentCanvasExpertActivityRow,
)
from app.schemas.agent_canvas_capabilities import (
    CapabilityCommandEnvelopeV1,
    CapabilityContextSnapshotV1,
    CapabilityDispatchReceiptV1,
    ValidatedNextActionV1,
)
from app.schemas.agent_canvas_conversation import ChatTurnV2
from app.schemas.v2_persistence import V2EventInsert


class CapabilityDispatchService:
    """Persist one accepted capability command before waking its worker."""

    def __init__(
        self,
        *,
        database: V2Database,
        events: EventRepository,
        wake_worker: Callable[[], object] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._database = database
        self._events = events
        self._envelopes = AgentCanvasOperationEnvelopeRepository(database)
        self._outbox = AgentCanvasContinuationOutboxRepository(database, events)
        self._wake_worker = wake_worker
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def dispatch_next_action(
        self,
        source_turn: ChatTurnV2,
        command: ValidatedNextActionV1,
        context_snapshot: CapabilityContextSnapshotV1,
        *,
        session_id: str | None = None,
        expected_session_revision: int | None = None,
    ) -> CapabilityDispatchReceiptV1:
        if command.definition is None or command.command.capability_id is None:
            raise ValueError("Capability dispatch requires an invoke-capability command.")
        capability_id = command.command.capability_id
        objective = command.command.objective or ""
        identity = _digest(
            source_turn.turn_id,
            capability_id,
            objective,
            context_snapshot.digest,
            str(expected_session_revision or source_turn.guidance_session_revision or ""),
        )
        envelope_id = f"envelope_{identity[:32]}"
        capability_turn_id = f"turn_{identity[32:]}"
        continuation_id = f"continuation_{identity[:24]}"
        activity_id = f"activity_{identity[8:32]}"
        now = self._clock().astimezone(timezone.utc)
        envelope = CapabilityCommandEnvelopeV1(
            envelope_id=envelope_id,
            workflow_id=source_turn.workflow_id,
            conversation_id=source_turn.conversation_id,
            source_turn_id=source_turn.turn_id,
            capability_turn_id=capability_turn_id,
            session_id=session_id,
            expected_session_revision=(
                expected_session_revision or source_turn.guidance_session_revision
            ),
            capability_id=capability_id,
            source_action=command.source_action,
            objective=objective,
            context_snapshot_id=context_snapshot.snapshot_id,
            context_snapshot_digest=context_snapshot.digest,
            style_skill_run_id=_style_skill_run_id(context_snapshot),
            shared_summary=context_snapshot.shared_summary,
            capability_context=context_snapshot.capability_context,
            style_projection=context_snapshot.style_projection,
            result_contract_name=command.definition.result_contract_name,
            candidate_count=command.definition.default_candidate_count,
            reference_allowlist=context_snapshot.approved_reference_ids,
            agent_request_identity=f"capability:{identity}",
            created_at=now,
        )
        timestamp = now.isoformat()
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                current = (
                    connection.execute(
                        select(AgentCanvasChatTurnRow).where(
                            AgentCanvasChatTurnRow.turn_id == source_turn.turn_id
                        )
                    )
                    .mappings()
                    .one()
                )
                if str(current["status"]) == "completed":
                    existing = self._envelopes.get_in_transaction(connection, envelope_id)
                    if not isinstance(existing, CapabilityCommandEnvelopeV1):
                        raise ValueError(
                            "Operation envelope type conflicts with capability dispatch."
                        )
                    connection.commit()
                    return CapabilityDispatchReceiptV1(
                        envelope_id=existing.envelope_id,
                        continuation_id=continuation_id,
                        capability_turn_id=existing.capability_turn_id,
                        capability_id=existing.capability_id,
                        activity_id=activity_id,
                        queued_at=existing.created_at,
                    )
                connection.execute(
                    insert(AgentCanvasChatTurnRow).values(
                        turn_id=capability_turn_id,
                        conversation_id=source_turn.conversation_id,
                        workflow_id=source_turn.workflow_id,
                        turn_kind="capability",
                        status="queued",
                        request_json=json.dumps(
                            {"schema_version": "1", "envelope_id": envelope_id},
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        creation_mode_json=None,
                        guidance_session_revision=source_turn.guidance_session_revision,
                        idempotency_key=f"capability:{envelope_id}",
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
                    continuation_turn_id=capability_turn_id,
                    operation="capability_command",
                    payload={"schema_version": "1", "envelope_id": envelope_id},
                    max_attempts=5,
                    now=now,
                )
                connection.execute(
                    insert(AgentCanvasExpertActivityRow).values(
                        activity_id=activity_id,
                        turn_id=capability_turn_id,
                        workflow_id=source_turn.workflow_id,
                        capability_id=capability_id,
                        operation=command.definition.operation,
                        status="working",
                        display_name=command.definition.display_name,
                        error_code=None,
                        error_message=None,
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
                connection.execute(
                    update(AgentCanvasChatTurnRow)
                    .where(AgentCanvasChatTurnRow.turn_id == source_turn.turn_id)
                    .values(status="completed", updated_at=timestamp)
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
                        entry_id=f"entry_{identity[:32]}",
                        conversation_id=source_turn.conversation_id,
                        workflow_id=source_turn.workflow_id,
                        sequence_no=sequence_no,
                        entry_type="expert_activity",
                        speaker="adcraft_video_agent",
                        content=f"{command.definition.display_name} is working.",
                        metadata_json=json.dumps(
                            {
                                "activity_id": activity_id,
                                "turn_id": capability_turn_id,
                                "capability_id": capability_id,
                                "capability_display_name": command.definition.display_name,
                                "operation": command.definition.operation,
                                "status": "working",
                            },
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        created_at=timestamp,
                    )
                )
                for event_type, turn_id, payload in (
                    (
                        "expert_activity_started",
                        capability_turn_id,
                        {
                            "activity_id": activity_id,
                            "capability_id": capability_id,
                            "capability_display_name": command.definition.display_name,
                            "operation": command.definition.operation,
                            "status": "working",
                        },
                    ),
                    (
                        "agent_command_queued",
                        capability_turn_id,
                        {
                            "envelope_id": envelope_id,
                            "capability_id": capability_id,
                            "source_action": command.source_action,
                            "continuation_id": continuation_id,
                        },
                    ),
                    (
                        "chat_turn_completed",
                        source_turn.turn_id,
                        {"turn_id": source_turn.turn_id},
                    ),
                ):
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=source_turn.workflow_id,
                            conversation_id=source_turn.conversation_id,
                            turn_id=turn_id,
                            event_type=event_type,
                            transition_key=f"conversation:{turn_id}:{event_type}",
                            created_at=timestamp,
                            payload=payload,
                        ),
                    )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        if self._wake_worker is not None:
            self._wake_worker()
        return CapabilityDispatchReceiptV1(
            envelope_id=envelope_id,
            continuation_id=continuation_id,
            capability_turn_id=capability_turn_id,
            capability_id=capability_id,
            activity_id=activity_id,
            queued_at=now,
        )


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _style_skill_run_id(context_snapshot: CapabilityContextSnapshotV1) -> str | None:
    value = context_snapshot.style_projection.get("skill_run_id")
    return value if isinstance(value, str) and value else None
