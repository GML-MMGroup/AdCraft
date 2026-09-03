"""Atomic terminal reconciliation for reserved guided Editing actions."""

from __future__ import annotations

from hashlib import sha256

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.agent_canvas_conversation_repository import (
    guidance_session_from_row,
)
from app.persistence.agent_canvas_production_closure_repository import (
    AgentCanvasProductionClosureRepository,
)
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import AgentCanvasGuidanceSessionRow
from app.schemas.agent_canvas_production_closure import (
    GuidedEditingActionReconciliationCommandV1,
    GuidedEditingActionReconciliationReceiptV1,
)
from app.schemas.v2_persistence import V2EventInsert


class AgentCanvasEditingActionReconciliationRepository:
    """Commit one terminal outcome and clear its reserved action exactly once."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        self._database = database
        self._events = events
        self._receipts = AgentCanvasProductionClosureRepository(database)

    def reconcile(
        self,
        command: GuidedEditingActionReconciliationCommandV1,
    ) -> GuidedEditingActionReconciliationReceiptV1:
        replay = self._receipts.find_action_reconciliation(command.logical_identity)
        if replay is not None:
            self._require_replay_match(command, replay)
            return replay

        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    row = (
                        connection.execute(
                            select(AgentCanvasGuidanceSessionRow).where(
                                AgentCanvasGuidanceSessionRow.session_id == command.session_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None or str(row["workflow_id"]) != command.workflow_id:
                        raise _error(
                            "guided_editing_action_authority_not_found",
                            "Guided Editing action authority was not found.",
                        )
                    session = guidance_session_from_row(connection, row)
                    self._require_current_action(command, session)
                    next_revision = command.expected_session_revision + 1
                    next_journey = session.journey.model_copy(
                        update={
                            "active_action": None,
                            "stage_status": _stage_status(command.outcome),
                        }
                    )
                    updated = connection.execute(
                        update(AgentCanvasGuidanceSessionRow)
                        .where(
                            AgentCanvasGuidanceSessionRow.session_id == command.session_id,
                            AgentCanvasGuidanceSessionRow.revision
                            == command.expected_session_revision,
                        )
                        .values(
                            journey_state_json=next_journey.model_dump_json(),
                            revision=next_revision,
                            updated_at=command.reconciled_at.isoformat(),
                        )
                    )
                    if updated.rowcount != 1:
                        raise _error(
                            "guided_editing_action_revision_conflict",
                            "Guided Editing action changed before reconciliation.",
                        )
                    receipt = GuidedEditingActionReconciliationReceiptV1(
                        **command.model_dump(),
                        receipt_id=_receipt_id(command.logical_identity),
                        resulting_session_revision=next_revision,
                    )
                    self._receipts.save_action_reconciliation_in_transaction(
                        connection,
                        receipt,
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=command.workflow_id,
                            turn_id=command.action_turn_id,
                            action_id=command.action_id,
                            event_type="guided_editing_action_reconciled",
                            transition_key=(
                                f"guided-editing-action-reconciliation:{command.logical_identity}"
                            ),
                            created_at=command.reconciled_at.isoformat(),
                            payload={
                                "session_id": command.session_id,
                                "session_revision": next_revision,
                                "stage": session.journey.stage,
                                "stage_revision": session.journey.stage_revision,
                                "outcome": command.outcome,
                                "reason_code": command.reason_code,
                                "evidence_ids": list(command.evidence_ids),
                            },
                        ),
                    )
                    connection.commit()
                    return receipt
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            replay = self._receipts.find_action_reconciliation(command.logical_identity)
            if replay is not None:
                self._require_replay_match(command, replay)
                return replay
            raise _error(
                "guided_editing_action_reconciliation_conflict",
                "Guided Editing action reconciliation conflicted with another writer.",
            ) from error
        except SQLAlchemyError as error:
            raise _error(
                "guided_editing_action_reconciliation_unavailable",
                "Guided Editing action reconciliation storage is unavailable.",
            ) from error

    @staticmethod
    def _require_current_action(command, session) -> None:
        if session.revision != command.expected_session_revision:
            raise _error(
                "guided_editing_action_revision_conflict",
                "Guided Editing action changed before reconciliation.",
            )
        action = session.journey.active_action
        if (
            session.journey.stage != "editing"
            or action is None
            or action.action_id != command.action_id
            or action.turn_id != command.action_turn_id
            or action.stage_revision != command.action_stage_revision
            or action.action_kind != "prepare_editing"
            or action.status != "reserved"
        ):
            raise _error(
                "guided_editing_action_identity_conflict",
                "Guided Editing action identity changed before reconciliation.",
            )

    @staticmethod
    def _require_replay_match(command, receipt) -> None:
        expected = command.model_dump(mode="json")
        actual = receipt.model_dump(
            mode="json", exclude={"receipt_id", "resulting_session_revision"}
        )
        if actual != expected:
            raise _error(
                "guided_editing_action_reconciliation_conflict",
                "Guided Editing action identity was reused with different evidence.",
            )


def _stage_status(outcome: str) -> str:
    return {
        "prepared": "ready",
        "waiting_user": "waiting_user",
        "system_deferred": "working",
        "failed": "failed",
        "superseded": "ready",
    }[outcome]


def _receipt_id(logical_identity: str) -> str:
    return f"editing_action_reconciliation_{sha256(logical_identity.encode()).hexdigest()[:24]}"


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="editing_action_reconciliation")
