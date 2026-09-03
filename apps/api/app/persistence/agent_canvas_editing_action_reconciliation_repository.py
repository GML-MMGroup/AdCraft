"""Atomic terminal reconciliation for reserved guided Editing actions."""

from __future__ import annotations

import json
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
from app.persistence.models import (
    AgentCanvasAutomaticRunCommandRow,
    AgentCanvasExecutionMemberRow,
    AgentCanvasGuidanceAwaitingRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasGuidedMediaResumeDeliveryRow,
    AgentCanvasGuidedProductionReceiptRow,
    AgentCanvasPostReadyEffectRow,
)
from app.schemas.agent_canvas_production_closure import (
    GuidedMediaConfirmationV1,
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
                    replay = self._receipts.find_action_reconciliation_in_transaction(
                        connection,
                        command.logical_identity,
                    )
                    if replay is not None:
                        self._require_replay_match(command, replay)
                        connection.commit()
                        return replay
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
                    if command.outcome == "superseded":
                        if self._is_current_action(command, session):
                            raise _error(
                                "guided_editing_action_identity_conflict",
                                "A current Guided Editing action cannot be superseded.",
                            )
                        receipt = self._persist_receipt_and_event(
                            connection,
                            command=command,
                            resulting_session_revision=session.revision,
                            stage=session.journey.stage,
                            stage_revision=session.journey.stage_revision,
                        )
                        connection.commit()
                        return receipt
                    self._require_current_action(command, session)
                    self._require_outcome_evidence(connection, command)
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
                    receipt = self._persist_receipt_and_event(
                        connection,
                        command=command,
                        resulting_session_revision=next_revision,
                        stage=session.journey.stage,
                        stage_revision=session.journey.stage_revision,
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
    def _is_current_action(command, session) -> bool:
        action = session.journey.active_action
        return bool(
            session.revision == command.expected_session_revision
            and session.journey.stage == "editing"
            and action is not None
            and action.action_id == command.action_id
            and action.turn_id == command.action_turn_id
            and action.stage_revision == command.action_stage_revision
            and action.action_kind == "prepare_editing"
            and action.status == "reserved"
        )

    @classmethod
    def _require_current_action(cls, command, session) -> None:
        if session.revision != command.expected_session_revision:
            raise _error(
                "guided_editing_action_revision_conflict",
                "Guided Editing action changed before reconciliation.",
            )
        if not cls._is_current_action(command, session):
            raise _error(
                "guided_editing_action_identity_conflict",
                "Guided Editing action identity changed before reconciliation.",
            )

    @staticmethod
    def _require_outcome_evidence(connection, command) -> None:
        if command.outcome == "prepared":
            receipt_id = connection.execute(
                select(AgentCanvasGuidedProductionReceiptRow.receipt_id).where(
                    AgentCanvasGuidedProductionReceiptRow.receipt_type == "editing_preparation",
                    AgentCanvasGuidedProductionReceiptRow.receipt_id
                    == command.preparation_receipt_id,
                    AgentCanvasGuidedProductionReceiptRow.workflow_id == command.workflow_id,
                )
            ).scalar_one_or_none()
            if receipt_id is None or str(receipt_id) not in command.evidence_ids:
                raise _evidence_error()
            return
        if command.outcome == "waiting_user":
            awaiting_id = connection.execute(
                select(AgentCanvasGuidanceAwaitingRow.awaiting_id).where(
                    AgentCanvasGuidanceAwaitingRow.awaiting_id == command.awaiting_id,
                    AgentCanvasGuidanceAwaitingRow.workflow_id == command.workflow_id,
                    AgentCanvasGuidanceAwaitingRow.session_id == command.session_id,
                    AgentCanvasGuidanceAwaitingRow.kind == command.awaiting_kind,
                    AgentCanvasGuidanceAwaitingRow.stage == "editing",
                    AgentCanvasGuidanceAwaitingRow.stage_revision == command.action_stage_revision,
                    AgentCanvasGuidanceAwaitingRow.requires_user_action.is_(True),
                )
            ).scalar_one_or_none()
            if awaiting_id is None or str(awaiting_id) not in command.evidence_ids:
                raise _evidence_error()
            return
        if command.outcome != "system_deferred":
            return
        table, identity_column, state_column, node_column, active_states = {
            "execution_member": (
                AgentCanvasExecutionMemberRow,
                AgentCanvasExecutionMemberRow.member_id,
                AgentCanvasExecutionMemberRow.state,
                AgentCanvasExecutionMemberRow.node_id,
                ("queued", "waiting", "running"),
            ),
            "automatic_run": (
                AgentCanvasAutomaticRunCommandRow,
                AgentCanvasAutomaticRunCommandRow.command_id,
                AgentCanvasAutomaticRunCommandRow.state,
                AgentCanvasAutomaticRunCommandRow.node_id,
                ("pending", "claimed"),
            ),
            "post_ready_effect": (
                AgentCanvasPostReadyEffectRow,
                AgentCanvasPostReadyEffectRow.effect_id,
                AgentCanvasPostReadyEffectRow.status,
                AgentCanvasPostReadyEffectRow.node_id,
                ("queued", "running"),
            ),
            "guided_media_resume": (
                AgentCanvasGuidedMediaResumeDeliveryRow,
                AgentCanvasGuidedMediaResumeDeliveryRow.delivery_id,
                AgentCanvasGuidedMediaResumeDeliveryRow.status,
                None,
                ("queued", "running"),
            ),
        }[command.system_owner_kind]
        columns = [identity_column]
        if node_column is not None:
            columns.append(node_column)
        owner = connection.execute(
            select(*columns).where(
                identity_column == command.system_owner_id,
                table.workflow_id == command.workflow_id,
                state_column.in_(active_states),
            )
        ).one_or_none()
        if owner is None or str(owner[0]) not in command.evidence_ids:
            raise _evidence_error()
        if node_column is not None:
            if str(owner[1]) != command.system_owner_node_id:
                raise _evidence_error()
            return
        confirmation_id = connection.execute(
            select(AgentCanvasGuidedMediaResumeDeliveryRow.confirmation_id).where(
                AgentCanvasGuidedMediaResumeDeliveryRow.delivery_id == command.system_owner_id
            )
        ).scalar_one()
        payload_json = connection.execute(
            select(AgentCanvasGuidedProductionReceiptRow.payload_json).where(
                AgentCanvasGuidedProductionReceiptRow.receipt_type == "media_confirmation",
                AgentCanvasGuidedProductionReceiptRow.receipt_id == confirmation_id,
                AgentCanvasGuidedProductionReceiptRow.workflow_id == command.workflow_id,
            )
        ).scalar_one_or_none()
        if payload_json is None:
            raise _evidence_error()
        confirmation = GuidedMediaConfirmationV1.model_validate(json.loads(str(payload_json)))
        if confirmation.node_id != command.system_owner_node_id:
            raise _evidence_error()

    def _persist_receipt_and_event(
        self,
        connection,
        *,
        command,
        resulting_session_revision: int,
        stage: str,
        stage_revision: int,
    ) -> GuidedEditingActionReconciliationReceiptV1:
        receipt = GuidedEditingActionReconciliationReceiptV1(
            **command.model_dump(),
            receipt_id=_receipt_id(command.logical_identity),
            resulting_session_revision=resulting_session_revision,
        )
        self._receipts.save_action_reconciliation_in_transaction(connection, receipt)
        self._events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=command.workflow_id,
                turn_id=command.action_turn_id,
                action_id=command.action_id,
                event_type="guided_editing_action_reconciled",
                transition_key=(f"guided-editing-action-reconciliation:{command.logical_identity}"),
                created_at=command.reconciled_at.isoformat(),
                payload={
                    "session_id": command.session_id,
                    "session_revision": resulting_session_revision,
                    "stage": stage,
                    "stage_revision": stage_revision,
                    "outcome": command.outcome,
                    "reason_code": command.reason_code,
                    "evidence_ids": list(command.evidence_ids),
                },
            ),
        )
        return receipt

    @staticmethod
    def _require_replay_match(command, receipt) -> None:
        expected = command.model_dump(mode="json", exclude={"reconciled_at"})
        actual = receipt.model_dump(
            mode="json",
            exclude={"receipt_id", "resulting_session_revision", "reconciled_at"},
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


def _evidence_error() -> V2PersistenceError:
    return _error(
        "guided_editing_action_evidence_invalid",
        "Guided Editing action outcome evidence is not current authority.",
    )
