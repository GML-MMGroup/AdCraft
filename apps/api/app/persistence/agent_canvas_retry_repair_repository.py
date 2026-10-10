"""Fenced, non-executing repair of an explicitly reviewed legacy retry digest."""

from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from app.persistence.agent_canvas_conversation_repository import (
    publish_capability_failure_in_transaction,
)
from app.persistence.agent_canvas_guidance_authority_repository import (
    GuidanceAdvanceAuthoritySnapshotRepository,
)
from app.persistence.agent_canvas_requirement_repository import AgentCanvasRequirementRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasAutomaticRunCommandRow,
    AgentCanvasChatTurnRow,
    AgentCanvasContinuationOutboxRow,
    AgentCanvasEditingExportRow,
    AgentCanvasExecutionRow,
    AgentCanvasPromptPreparationOutboxRow,
    AgentCanvasProviderTaskRow,
    AgentRunRow,
    WorkflowEventRow,
)
from app.schemas.agent_canvas_conversation import ChatTurnRetryRequestV1, ChatTurnV2
from app.schemas.agent_canvas_guidance import ContinuationTurnRetrySnapshotV1
from app.schemas.agent_canvas_retry_repair import (
    RetryEnvelopeDigestRepairReceiptV1,
    RetryEnvelopeDigestRepairV1,
)
from app.schemas.v2_persistence import V2EventInsert


RepairValidator = Callable[[str, str, ChatTurnRetryRequestV1, str], ChatTurnV2]


class RetryEnvelopeDigestRepairRepository:
    def __init__(self, database: V2Database, events: EventRepository) -> None:
        self._database = database
        self._events = events

    def repair(
        self, command: RetryEnvelopeDigestRepairV1, *, validate: RepairValidator
    ) -> RetryEnvelopeDigestRepairReceiptV1:
        """Pin all writers while existing retry validation checks the frozen scope."""

        identity = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
        transition_key = f"retry-envelope-digest-repaired:{identity}"
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                prior = connection.execute(
                    select(WorkflowEventRow.seq).where(
                        WorkflowEventRow.transition_key == transition_key,
                        WorkflowEventRow.workflow_id == command.workflow_id,
                    )
                ).scalar_one_or_none()
                if prior is not None:
                    connection.commit()
                    return _receipt(command, int(prior), replayed=True)
                turn = (
                    connection.execute(
                        select(AgentCanvasChatTurnRow).where(
                            AgentCanvasChatTurnRow.workflow_id == command.workflow_id,
                            AgentCanvasChatTurnRow.turn_id == command.turn_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if turn is None or turn["status"] != "failed" or turn["turn_kind"] != "capability":
                    raise _stale()
                raw = json.loads(str(turn["retry_snapshot_json"]))
                digest = hashlib.sha256(
                    json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                snapshot = ContinuationTurnRetrySnapshotV1.model_validate(raw)
                if digest != command.expected_snapshot_digest:
                    raise _stale()
                _require_idle(connection, command.workflow_id)
                authority = GuidanceAdvanceAuthoritySnapshotRepository(
                    AgentCanvasRequirementRepository(self._database)
                ).read_in_transaction(connection, command.workflow_id)
                leaf = authority.execution_leaf
                if (
                    leaf is None
                    or leaf.leaf_turn_id != command.turn_id
                    or leaf.leaf_status != "failed"
                    or leaf.continuation_status != "failed"
                    or authority.guided_media_resume_owner is not None
                    or authority.open_proposal_id is not None
                    or authority.open_decision_bundle_id is not None
                ):
                    raise _stale()
                # Separate read connections see the same committed state: this transaction
                # holds SQLite's reserved write lock until repair and audit commit together.
                source = validate(
                    command.workflow_id,
                    command.turn_id,
                    ChatTurnRetryRequestV1(
                        expected_workflow_revision=snapshot.workflow_revision,
                        expected_session_revision=snapshot.session_revision,
                    ),
                    command.expected_envelope_digest,
                )
                repaired = {**raw, "envelope_digest": command.expected_envelope_digest}
                connection.execute(
                    update(AgentCanvasChatTurnRow)
                    .where(AgentCanvasChatTurnRow.turn_id == command.turn_id)
                    .values(
                        retry_snapshot_json=json.dumps(
                            repaired, sort_keys=True, separators=(",", ":")
                        )
                    )
                )
                now = datetime.now(timezone.utc).isoformat()
                assert source.actionable_failure is not None
                publish_capability_failure_in_transaction(
                    connection,
                    events=self._events,
                    turn=turn,
                    code=source.error_code or "agent_operation_failed",
                    actionable_failure=source.actionable_failure,
                    now=now,
                )
                event = self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=command.workflow_id,
                        turn_id=command.turn_id,
                        event_type="chat_turn_retry_digest_repaired",
                        transition_key=transition_key,
                        created_at=now,
                        payload={
                            "turn_id": command.turn_id,
                            "before_snapshot_digest": command.expected_snapshot_digest,
                            "before_envelope_digest": snapshot.envelope_digest,
                            "envelope_digest": command.expected_envelope_digest,
                            "envelope_id": snapshot.envelope_id,
                        },
                    ),
                )
                connection.commit()
                return _receipt(command, event.seq, replayed=False)
            except BaseException:
                connection.rollback()
                raise


def _require_idle(connection: Connection, workflow_id: str) -> None:
    if (
        connection.execute(
            select(AgentCanvasAutomaticRunCommandRow.command_id)
            .where(
                AgentCanvasAutomaticRunCommandRow.workflow_id == workflow_id,
                AgentCanvasAutomaticRunCommandRow.state.in_(("pending", "claimed")),
            )
            .limit(1)
        ).first()
        is not None
    ):
        raise _stale()
    completed_dispatch = (
        select(AgentCanvasContinuationOutboxRow.continuation_id)
        .where(
            AgentCanvasContinuationOutboxRow.workflow_id == workflow_id,
            AgentCanvasContinuationOutboxRow.continuation_turn_id == AgentCanvasChatTurnRow.turn_id,
            AgentCanvasContinuationOutboxRow.status == "completed",
        )
        .exists()
    )
    if (
        connection.execute(
            select(AgentCanvasChatTurnRow.turn_id)
            .where(
                AgentCanvasChatTurnRow.workflow_id == workflow_id,
                AgentCanvasChatTurnRow.status.in_(("queued", "running")),
                ~completed_dispatch,
            )
            .limit(1)
        ).first()
        is not None
    ):
        raise _stale()
    for row, statuses in (
        (AgentCanvasContinuationOutboxRow, ("queued", "leased", "retry_wait")),
        (AgentCanvasPromptPreparationOutboxRow, ("queued", "leased", "retry_wait")),
        (AgentCanvasExecutionRow, ("queued", "running", "waiting")),
        (AgentCanvasEditingExportRow, ("queued", "exporting")),
        (AgentRunRow, ("queued", "running")),
    ):
        if (
            connection.execute(
                select(row.workflow_id)
                .where(row.workflow_id == workflow_id, row.status.in_(statuses))
                .limit(1)
            ).first()
            is not None
        ):
            raise _stale()
    if (
        connection.execute(
            select(AgentCanvasProviderTaskRow.workflow_id)
            .where(
                AgentCanvasProviderTaskRow.workflow_id == workflow_id,
                AgentCanvasProviderTaskRow.status.not_in(("succeeded", "failed", "cancelled")),
            )
            .limit(1)
        ).first()
        is not None
    ):
        raise _stale()


def _receipt(
    command: RetryEnvelopeDigestRepairV1, event_seq: int, *, replayed: bool
) -> RetryEnvelopeDigestRepairReceiptV1:
    return RetryEnvelopeDigestRepairReceiptV1(
        workflow_id=command.workflow_id,
        turn_id=command.turn_id,
        envelope_digest=command.expected_envelope_digest,
        event_seq=event_seq,
        replayed=replayed,
    )


def _stale() -> V2PersistenceError:
    return V2PersistenceError(
        "chat_turn_retry_repair_stale",
        "Retry digest repair no longer matches an idle failed operation.",
    )
