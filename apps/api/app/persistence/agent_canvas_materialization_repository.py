"""Atomic persistence for selected capability Materialization attempts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
import json

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.agent_canvas_operation_envelope_repository import (
    AgentCanvasOperationEnvelopeRepository,
)
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasChatEntryRow,
    AgentCanvasChatTurnRow,
    AgentCanvasContinuationOutboxRow,
    AgentCanvasConceptOptionRow,
    AgentCanvasConceptProposalRow,
    AgentCanvasExpertActivityRow,
    AgentCanvasGuidanceSessionRow,
)
from app.schemas.agent_canvas_conversation import ProposalMaterializationProjectionV2
from app.schemas.agent_canvas_materialization import CapabilityMaterializationEnvelopeV1
from app.schemas.v2_persistence import V2EventInsert


class AgentCanvasMaterializationRepository:
    """Queue and project one immutable selected-option Materialization attempt."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Materialization and event repositories must share one database.")
        self._database = database
        self._events = events
        self._envelopes = AgentCanvasOperationEnvelopeRepository(database)
        self._outbox = AgentCanvasContinuationOutboxRepository(database, events)

    def queue(
        self,
        envelope: CapabilityMaterializationEnvelopeV1,
        *,
        max_attempts: int = 5,
        action_request: Mapping[str, object] | None = None,
        idempotency_key: str | None = None,
    ) -> ProposalMaterializationProjectionV2:
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat()
        continuation_id = "continuation_" + _digest(envelope.materialization_id)[:32]
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    if action_request is not None:
                        if not idempotency_key:
                            raise _error(
                                "idempotency_key_required",
                                "Materialization action requires an idempotency key.",
                            )
                        request_json = json.dumps(
                            action_request,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                        existing_turn = (
                            connection.execute(
                                select(AgentCanvasChatTurnRow).where(
                                    AgentCanvasChatTurnRow.idempotency_key == idempotency_key
                                )
                            )
                            .mappings()
                            .one_or_none()
                        )
                        if existing_turn is None:
                            connection.execute(
                                insert(AgentCanvasChatTurnRow).values(
                                    turn_id=envelope.action_turn_id,
                                    conversation_id=envelope.conversation_id,
                                    workflow_id=envelope.workflow_id,
                                    turn_kind="proposal_action",
                                    status="queued",
                                    request_json=request_json,
                                    idempotency_key=idempotency_key,
                                    error_code=None,
                                    error_message=None,
                                    created_at=timestamp,
                                    updated_at=timestamp,
                                )
                            )
                            self._events.append_in_transaction(
                                connection,
                                V2EventInsert(
                                    workflow_id=envelope.workflow_id,
                                    conversation_id=envelope.conversation_id,
                                    turn_id=envelope.action_turn_id,
                                    event_type="agent_turn_queued",
                                    transition_key=(
                                        f"conversation:{envelope.action_turn_id}:queued"
                                    ),
                                    created_at=timestamp,
                                    payload={
                                        "turn_id": envelope.action_turn_id,
                                        "turn_kind": "proposal_action",
                                    },
                                ),
                            )
                        elif (
                            str(existing_turn["turn_id"]) != envelope.action_turn_id
                            or str(existing_turn["workflow_id"]) != envelope.workflow_id
                            or str(existing_turn["request_json"]) != request_json
                        ):
                            raise _error(
                                "idempotency_conflict",
                                "Idempotency key was reused.",
                            )
                    proposal = (
                        connection.execute(
                            select(AgentCanvasConceptProposalRow).where(
                                AgentCanvasConceptProposalRow.proposal_id == envelope.proposal_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if proposal is None or str(proposal["workflow_id"]) != envelope.workflow_id:
                        raise _error("proposal_not_found", "Concept proposal was not found.")
                    existing_id = proposal["materialization_id"]
                    if existing_id is not None:
                        if str(existing_id) == envelope.materialization_id:
                            connection.commit()
                            return _projection(proposal)
                        if str(proposal["materialization_status"]) in {"queued", "working"}:
                            raise _error(
                                "proposal_materialization_conflict",
                                "Another Materialization attempt is active for this Proposal.",
                            )
                    allowed_availability = str(proposal["availability"]) == "open" or (
                        envelope.action == "reuse_direction"
                        and str(proposal["availability"]) == "superseded"
                    )
                    if not allowed_availability:
                        raise _error(
                            "proposal_action_stale",
                            "Concept proposal is not available for Materialization.",
                        )
                    if int(proposal["proposal_revision"]) != envelope.proposal_revision:
                        raise _error(
                            "proposal_action_stale",
                            "Concept proposal revision is stale.",
                        )
                    session_revision = connection.execute(
                        select(AgentCanvasGuidanceSessionRow.revision).where(
                            AgentCanvasGuidanceSessionRow.session_id
                            == proposal["guidance_session_id"]
                        )
                    ).scalar_one()
                    if int(session_revision) != envelope.expected_session_revision:
                        raise _error(
                            "guidance_revision_conflict",
                            "Guidance session revision is stale.",
                        )
                    option_exists = connection.execute(
                        select(AgentCanvasConceptOptionRow.option_id).where(
                            AgentCanvasConceptOptionRow.proposal_id == envelope.proposal_id,
                            AgentCanvasConceptOptionRow.option_id
                            == envelope.selected_option.option_id,
                        )
                    ).scalar_one_or_none()
                    if option_exists is None:
                        raise _error(
                            "proposal_option_not_found",
                            "Concept option was not found.",
                        )
                    turn = (
                        connection.execute(
                            select(AgentCanvasChatTurnRow).where(
                                AgentCanvasChatTurnRow.turn_id == envelope.action_turn_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if turn is None or str(turn["workflow_id"]) != envelope.workflow_id:
                        raise _error(
                            "chat_turn_not_found",
                            "Materialization action turn was not found.",
                        )

                    self._envelopes.create_in_transaction(connection, envelope)
                    self._outbox.enqueue_in_transaction(
                        connection,
                        continuation_id=continuation_id,
                        workflow_id=envelope.workflow_id,
                        conversation_id=envelope.conversation_id,
                        source_turn_id=str(proposal["turn_id"]),
                        continuation_turn_id=envelope.action_turn_id,
                        operation="capability_materialization",
                        payload={"schema_version": "1", "envelope_id": envelope.envelope_id},
                        max_attempts=max_attempts,
                        now=now,
                    )
                    connection.execute(
                        insert(AgentCanvasExpertActivityRow).values(
                            activity_id="activity_" + _digest(envelope.materialization_id)[:32],
                            turn_id=envelope.action_turn_id,
                            workflow_id=envelope.workflow_id,
                            capability_id=envelope.capability_id,
                            operation="capability_materialization",
                            status="working",
                            display_name="Capability Materialization",
                            error_code=None,
                            error_message=None,
                            created_at=timestamp,
                            updated_at=timestamp,
                        )
                    )
                    connection.execute(
                        update(AgentCanvasConceptProposalRow)
                        .where(AgentCanvasConceptProposalRow.proposal_id == envelope.proposal_id)
                        .values(
                            materialization_id=envelope.materialization_id,
                            materialization_option_id=envelope.selected_option.option_id,
                            materialization_turn_id=envelope.action_turn_id,
                            materialization_attempt_no=envelope.attempt_no,
                            materialization_status="queued",
                            materialization_retryable=True,
                            materialization_error_code=None,
                            materialization_error_message=None,
                            materialization_created_at=timestamp,
                            materialization_updated_at=timestamp,
                            updated_at=timestamp,
                        )
                    )
                    sequence_no = (
                        int(
                            connection.execute(
                                select(
                                    func.coalesce(func.max(AgentCanvasChatEntryRow.sequence_no), 0)
                                ).where(
                                    AgentCanvasChatEntryRow.conversation_id
                                    == envelope.conversation_id
                                )
                            ).scalar_one()
                        )
                        + 1
                    )
                    connection.execute(
                        insert(AgentCanvasChatEntryRow).values(
                            entry_id="entry_" + _digest(envelope.materialization_id)[:32],
                            conversation_id=envelope.conversation_id,
                            workflow_id=envelope.workflow_id,
                            sequence_no=sequence_no,
                            entry_type="planning_progress",
                            speaker="adcraft_video_agent",
                            content="The selected direction is being prepared as an editable Draft.",
                            metadata_json=json.dumps(
                                {
                                    "proposal_id": envelope.proposal_id,
                                    "materialization_id": envelope.materialization_id,
                                    "option_id": envelope.selected_option.option_id,
                                    "capability_id": envelope.capability_id,
                                    "status": "queued",
                                },
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                            created_at=timestamp,
                        )
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=envelope.workflow_id,
                            conversation_id=envelope.conversation_id,
                            turn_id=envelope.action_turn_id,
                            action_id=envelope.action_turn_id,
                            event_type="proposal_materialization_queued",
                            created_at=timestamp,
                            payload={
                                "proposal_id": envelope.proposal_id,
                                "materialization_id": envelope.materialization_id,
                                "option_id": envelope.selected_option.option_id,
                                "capability_id": envelope.capability_id,
                                "turn_id": envelope.action_turn_id,
                            },
                        ),
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "capability_materialization_failed",
                "Materialization submission could not be persisted.",
            ) from error
        return self.get_projection(envelope.proposal_id)

    def mark_working(
        self,
        envelope: CapabilityMaterializationEnvelopeV1,
    ) -> ProposalMaterializationProjectionV2:
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._database.engine.begin() as connection:
                result = connection.execute(
                    update(AgentCanvasConceptProposalRow)
                    .where(
                        AgentCanvasConceptProposalRow.proposal_id == envelope.proposal_id,
                        AgentCanvasConceptProposalRow.materialization_id
                        == envelope.materialization_id,
                        AgentCanvasConceptProposalRow.materialization_status.in_(
                            ("queued", "working")
                        ),
                    )
                    .values(materialization_status="working", materialization_updated_at=now)
                )
                if result.rowcount != 1:
                    raise _error(
                        "proposal_materialization_conflict",
                        "Materialization attempt is no longer active.",
                    )
                connection.execute(
                    update(AgentCanvasChatTurnRow)
                    .where(AgentCanvasChatTurnRow.turn_id == envelope.action_turn_id)
                    .values(status="running", updated_at=now)
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=envelope.workflow_id,
                        conversation_id=envelope.conversation_id,
                        turn_id=envelope.action_turn_id,
                        action_id=envelope.action_turn_id,
                        event_type="proposal_materialization_started",
                        transition_key=(f"materialization:{envelope.materialization_id}:started"),
                        created_at=now,
                        payload={
                            "proposal_id": envelope.proposal_id,
                            "materialization_id": envelope.materialization_id,
                            "option_id": envelope.selected_option.option_id,
                            "capability_id": envelope.capability_id,
                            "turn_id": envelope.action_turn_id,
                        },
                    ),
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "capability_materialization_failed",
                "Materialization state could not be updated.",
            ) from error
        return self.get_projection(envelope.proposal_id)

    def fail_for_turn(
        self,
        turn_id: str,
        *,
        error_code: str,
        error_message: str,
        retryable: bool = True,
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._database.engine.begin() as connection:
            proposal = (
                connection.execute(
                    select(AgentCanvasConceptProposalRow).where(
                        AgentCanvasConceptProposalRow.materialization_turn_id == turn_id,
                        AgentCanvasConceptProposalRow.materialization_status.in_(
                            ("queued", "working")
                        ),
                    )
                )
                .mappings()
                .one_or_none()
            )
            if proposal is None:
                return False
            connection.execute(
                update(AgentCanvasConceptProposalRow)
                .where(AgentCanvasConceptProposalRow.proposal_id == proposal["proposal_id"])
                .values(
                    availability="open",
                    materialization_status="failed",
                    materialization_retryable=retryable,
                    materialization_error_code=error_code[:160],
                    materialization_error_message=error_message[:2_048],
                    materialization_updated_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                update(AgentCanvasChatTurnRow)
                .where(AgentCanvasChatTurnRow.turn_id == turn_id)
                .values(
                    status="failed",
                    error_code=error_code[:160],
                    error_message=error_message[:2_048],
                    updated_at=now,
                )
            )
            connection.execute(
                update(AgentCanvasExpertActivityRow)
                .where(AgentCanvasExpertActivityRow.turn_id == turn_id)
                .values(
                    status="failed",
                    error_code=error_code[:160],
                    error_message=error_message[:2_048],
                    updated_at=now,
                )
            )
            connection.execute(
                update(AgentCanvasContinuationOutboxRow)
                .where(
                    AgentCanvasContinuationOutboxRow.continuation_turn_id == turn_id,
                    AgentCanvasContinuationOutboxRow.operation == "capability_materialization",
                    AgentCanvasContinuationOutboxRow.status.in_(("queued", "retry_wait", "leased")),
                )
                .values(
                    status="failed",
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_code=error_code[:160],
                    last_error_message=error_message[:2_048],
                    updated_at=now,
                )
            )
            self._events.append_in_transaction(
                connection,
                V2EventInsert(
                    workflow_id=str(proposal["workflow_id"]),
                    conversation_id=None,
                    turn_id=turn_id,
                    action_id=turn_id,
                    event_type="proposal_materialization_failed",
                    transition_key=(f"materialization:{proposal['materialization_id']}:failed"),
                    created_at=now,
                    payload={
                        "proposal_id": str(proposal["proposal_id"]),
                        "materialization_id": str(proposal["materialization_id"]),
                        "option_id": str(proposal["materialization_option_id"]),
                        "capability_id": str(proposal["capability_id"]),
                        "turn_id": turn_id,
                        "error_code": error_code[:160],
                        "retryable": retryable,
                    },
                ),
            )
        return True

    def get_projection(self, proposal_id: str) -> ProposalMaterializationProjectionV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasConceptProposalRow).where(
                            AgentCanvasConceptProposalRow.proposal_id == proposal_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _error(
                "capability_materialization_failed",
                "Materialization state could not be loaded.",
            ) from error
        if row is None or row["materialization_id"] is None:
            raise _error("proposal_not_found", "Concept proposal was not found.")
        return _projection(row)

    def get_envelope(self, envelope_id: str) -> CapabilityMaterializationEnvelopeV1:
        envelope = self._envelopes.get(envelope_id)
        if not isinstance(envelope, CapabilityMaterializationEnvelopeV1):
            raise _error(
                "capability_materialization_invalid",
                "Operation envelope is not a capability Materialization.",
            )
        return envelope

    def events_cursor(self, workflow_id: str) -> int:
        return self._events.max_seq(workflow_id)


def _projection(row) -> ProposalMaterializationProjectionV2:
    error = None
    if row["materialization_error_code"] is not None:
        error = {
            "code": str(row["materialization_error_code"]),
            "message": str(row["materialization_error_message"]),
        }
    return ProposalMaterializationProjectionV2(
        materialization_id=str(row["materialization_id"]),
        option_id=str(row["materialization_option_id"]),
        turn_id=str(row["materialization_turn_id"]),
        status=str(row["materialization_status"]),
        attempt_no=int(row["materialization_attempt_no"]),
        retryable=bool(row["materialization_retryable"]),
        error=error,
        created_at=str(row["materialization_created_at"]),
        updated_at=str(row["materialization_updated_at"]),
    )


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="capability_materialization_repository")
