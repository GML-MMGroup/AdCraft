"""Fenced repair of the historical, pre-dispatch Brand Character admission defect."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.engine import Connection, RowMapping

from app.persistence.agent_canvas_conversation_repository import (
    publish_next_action_failure_in_transaction,
)
from app.persistence.agent_canvas_guidance_authority_repository import (
    GuidanceAdvanceAuthoritySnapshotRepository,
    require_guidance_advance_eligible,
)
from app.persistence.agent_canvas_requirement_repository import AgentCanvasRequirementRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasChatTurnRow,
    AgentCanvasConceptProposalRow,
    AgentCanvasContinuationOutboxRow,
    AgentCanvasExecutionRow,
    AgentCanvasExpertActivityRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasNodeRow,
    AgentCanvasProviderSubmissionIntentRow,
    AgentCanvasProviderTaskRow,
    AgentCanvasWorkflowRow,
    AgentRunRow,
    BrandJourneyRow,
    BrandRow,
    ProjectRow,
    WorkflowEventRow,
)
from app.schemas.agent_canvas_creative_session import GuidedSessionStateV2
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_production_journey import reconcile_character_occurrences
from app.services.agent_canvas_requirements import character_occurrence_authority_for_authoring
from app.services.brand_decision_document import BrandDecisionDocumentService


class BrandCharacterRecoveryRepository:
    """Repair only a proven malformed action; never retry or enqueue model work."""

    def __init__(self, database: V2Database) -> None:
        self._database = database
        self._events = EventRepository(database)
        self._authority = GuidanceAdvanceAuthoritySnapshotRepository(
            AgentCanvasRequirementRepository(database)
        )

    def recover(
        self,
        workflow_id: str,
        *,
        expected_session_revision: int,
        failed_turn_id: str,
        expected_requirement_revision_id: str,
        expected_content_digest: str,
        apply: bool = False,
    ) -> GuidedSessionStateV2:
        identity = f"brand-character-recovery:{workflow_id}:{failed_turn_id}"
        request = {
            "failed_turn_id": failed_turn_id,
            "expected_session_revision": expected_session_revision,
            "requirement_revision_id": expected_requirement_revision_id,
            "source_content_digest": expected_content_digest,
        }
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                snapshot = self._authority.read_in_transaction(connection, workflow_id)
                session = snapshot.session
                _require(session is not None, "A guided session is required.")
                assert session is not None
                recorded = connection.execute(
                    select(WorkflowEventRow.payload_json).where(
                        WorkflowEventRow.transition_key == identity
                    )
                ).scalar_one_or_none()
                if recorded is not None:
                    payload = json.loads(recorded)
                    _require(
                        all(payload.get(key) == value for key, value in request.items()),
                        "The recovery identity was reused with different authority.",
                    )
                    connection.rollback()
                    return session
                _require(
                    session.revision == expected_session_revision,
                    "The guided session changed before recovery.",
                )
                _require(
                    snapshot.requirements.revision_id == expected_requirement_revision_id,
                    "The requirements changed before recovery.",
                )
                _require_brand(connection, self._database, workflow_id, expected_content_digest)
                _require_malformed_action(session, failed_turn_id)
                turn = _require_failed_dispatch(connection, workflow_id, failed_turn_id)
                retry_snapshot = json.loads(turn["retry_snapshot_json"])
                _require(
                    retry_snapshot.get("requirement_revision_id")
                    == snapshot.requirements.revision_id
                    and retry_snapshot.get("requirement_digest") == snapshot.requirements.digest,
                    "The failed dispatch no longer matches the requirements.",
                )
                _require_idle(connection, workflow_id, failed_turn_id)
                roster = character_occurrence_authority_for_authoring(snapshot.requirements)
                _require(
                    roster.status == "resolved_positive",
                    "A confirmed Character roster is required.",
                )
                journey = reconcile_character_occurrences(
                    session.journey, roster.occurrences
                ).model_copy(update={"active_action": None, "stage_status": "ready"})
                now = datetime.now(timezone.utc)
                recovered = session.model_copy(
                    update={
                        "journey": journey,
                        "revision": session.revision + 1,
                        "updated_at": now,
                    }
                )
                # Keep the standard Advance gate authoritative, including proposal and awaiting owners.
                require_guidance_advance_eligible(
                    snapshot.model_copy(
                        update={
                            "session": recovered,
                            "execution_leaf": None,
                        }
                    )
                )
                if not apply:
                    connection.rollback()
                    return recovered
                connection.execute(
                    update(AgentCanvasGuidanceSessionRow)
                    .where(AgentCanvasGuidanceSessionRow.session_id == session.session_id)
                    .values(
                        journey_state_json=journey.model_dump_json(),
                        revision=recovered.revision,
                        updated_at=now.isoformat(),
                    )
                )
                _publish_historical_failure(connection, self._events, turn, now.isoformat())
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        event_type="journey_stage_recovered",
                        transition_key=identity,
                        created_at=now.isoformat(),
                        payload={
                            **request,
                            "session_id": session.session_id,
                            "session_revision": recovered.revision,
                            "stage": "character",
                            "stage_revision": journey.stage_revision,
                            "action_id": session.journey.active_action.action_id,
                            "recovery_kind": "canonical_character_roster",
                            "work_scheduled": False,
                        },
                    ),
                )
                connection.commit()
                return recovered
            except BaseException:
                connection.rollback()
                raise


def _require_malformed_action(session: GuidedSessionStateV2, failed_turn_id: str) -> None:
    journey = session.journey
    action = journey.active_action
    _require(
        session.status == "active"
        and journey.stage == "character"
        and journey.stage_status in {"ready", "failed"}
        and journey.suspended_action is None
        and journey.active_occurrence_id is None,
        "The session is not at the affected Character boundary.",
    )
    _require(
        action is not None
        and action.turn_id == failed_turn_id
        and action.stage == "character"
        and action.stage_revision == journey.stage_revision
        and action.action_kind == "invoke_capability:character_design"
        and action.status == "reserved"
        and action.occurrence_id is None
        and action.character_phase is None,
        "The current action does not match the malformed dispatch.",
    )
    characters = [item for item in journey.decisions if item.element_kind == "character"]
    _require(
        bool(characters)
        and all(
            item.outcome == "include"
            and not item.requirements
            and item.occurrence_id == f"occurrence:character:{item.occurrence_index}"
            for item in characters
        )
        and not any(item.stage == "character" for item in journey.transition_evidence),
        "Character work or a different roster projection already exists.",
    )


def _require_brand(
    connection: Connection, database: V2Database, workflow_id: str, digest: str
) -> None:
    brand_id = connection.execute(
        select(BrandRow.brand_id)
        .join(ProjectRow, ProjectRow.project_id == BrandRow.project_id)
        .join(AgentCanvasWorkflowRow, AgentCanvasWorkflowRow.project_id == ProjectRow.project_id)
        .join(BrandJourneyRow, BrandJourneyRow.brand_id == BrandRow.brand_id)
        .where(
            AgentCanvasWorkflowRow.workflow_id == workflow_id,
            ProjectRow.mode == "brand",
            BrandJourneyRow.stage == "production",
        )
    ).scalar_one_or_none()
    _require(brand_id is not None, "A locked Brand production workflow is required.")
    frozen = BrandDecisionDocumentService(database).frozen_in_transaction(connection, brand_id)
    _require(
        frozen is not None and frozen.content_digest == digest,
        "The frozen Treatment does not match the recovery request.",
    )


def _require_failed_dispatch(connection: Connection, workflow_id: str, turn_id: str) -> RowMapping:
    turn = (
        connection.execute(
            select(AgentCanvasChatTurnRow).where(
                AgentCanvasChatTurnRow.workflow_id == workflow_id,
                AgentCanvasChatTurnRow.turn_id == turn_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    _require(
        turn is not None
        and turn["turn_kind"] == "next_action"
        and turn["status"] == "failed"
        and turn["error_code"] == "character_proposal_scope_invalid"
        and not turn["retryable"],
        "The expected terminal Character scope failure is missing.",
    )
    delivery = (
        connection.execute(
            select(AgentCanvasContinuationOutboxRow).where(
                AgentCanvasContinuationOutboxRow.workflow_id == workflow_id,
                AgentCanvasContinuationOutboxRow.continuation_turn_id == turn_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    _require(
        delivery is not None
        and delivery["operation"] == "next_action"
        and delivery["status"] == "failed"
        and delivery["last_error_code"] == "character_proposal_scope_invalid",
        "The failed continuation does not match the dispatch.",
    )
    assert turn is not None
    return turn


def _require_idle(connection: Connection, workflow_id: str, failed_turn_id: str) -> None:
    active = (
        (AgentCanvasChatTurnRow, AgentCanvasChatTurnRow.status.in_(("queued", "running"))),
        (
            AgentCanvasContinuationOutboxRow,
            AgentCanvasContinuationOutboxRow.status.in_(("queued", "leased", "retry_wait")),
        ),
        (AgentRunRow, AgentRunRow.status.in_(("queued", "running"))),
        (
            AgentCanvasExecutionRow,
            AgentCanvasExecutionRow.status.in_(("queued", "running", "waiting")),
        ),
        (
            AgentCanvasProviderTaskRow,
            AgentCanvasProviderTaskRow.status.in_(("submitted", "waiting", "recovering")),
        ),
        (
            AgentCanvasProviderSubmissionIntentRow,
            AgentCanvasProviderSubmissionIntentRow.state != "completed",
        ),
        (AgentCanvasNodeRow, AgentCanvasNodeRow.creative_role == "character"),
        (AgentCanvasConceptProposalRow, AgentCanvasConceptProposalRow.proposal_kind == "character"),
        (AgentCanvasExpertActivityRow, AgentCanvasExpertActivityRow.turn_id == failed_turn_id),
        (
            AgentCanvasContinuationOutboxRow,
            AgentCanvasContinuationOutboxRow.source_turn_id == failed_turn_id,
        ),
        (AgentCanvasChatTurnRow, AgentCanvasChatTurnRow.retry_of_turn_id == failed_turn_id),
    )
    for model, condition in active:
        _require(
            connection.execute(
                select(model).where(model.workflow_id == workflow_id, condition).limit(1)
            ).first()
            is None,
            "Active work or Character dispatch evidence prevents this recovery.",
        )


def _publish_historical_failure(
    connection: Connection, events: EventRepository, turn: RowMapping, now: str
) -> None:
    from app.schemas.agent_canvas_errors import ActionableFailureV1
    from app.schemas.agent_operation_recovery import AgentOperationFailureV2

    operation_failure = (
        AgentOperationFailureV2.model_validate_json(turn["operation_failure_json"])
        if turn["operation_failure_json"]
        else None
    )
    disposition = operation_failure.actionable_failure if operation_failure else None
    publish_next_action_failure_in_transaction(
        connection,
        events=events,
        turn=turn,
        code="character_proposal_scope_invalid",
        retryable=False,
        actionable_failure=disposition
        or ActionableFailureV1(
            failure_class="deterministic",
            retry_scope="none",
            user_action="none",
        ),
        now=now,
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V2PersistenceError(
            "brand_character_recovery_conflict", message, stage="brand_character_recovery"
        )
