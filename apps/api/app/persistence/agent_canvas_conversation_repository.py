"""SQLite authority for Agent Canvas chat, proposals, and Video Skill Runs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal, Mapping, cast
from uuid import uuid4

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.agent_canvas_auto_run_repository import (
    AgentCanvasAutomaticRunRepository,
)
from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.agent_canvas_guidance_authority_repository import (
    GuidanceAdvanceAuthoritySnapshotRepository,
    guidance_advance_stale_error,
    require_guidance_advance_eligible,
)
from app.persistence.agent_canvas_operation_envelope_repository import (
    AgentCanvasOperationEnvelopeRepository,
)
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.event_repository import EventRepository
from app.persistence.agent_canvas_expert_activity_terminal_publication import (
    publish_expert_activity_terminal_in_transaction,
)
from app.persistence.agent_canvas_guided_interaction_repository import (
    guidance_awaiting_from_row,
    guided_interaction_from_row,
)
from app.persistence.models import (
    AgentCanvasActionReceiptRow,
    AgentCanvasChatEntryRow,
    AgentCanvasChatTurnRow,
    AgentCanvasContinuationOutboxRow,
    AgentCanvasCreativeMemoryRow,
    AgentCanvasConceptOptionRow,
    AgentCanvasConceptProposalRow,
    AgentCanvasConversationRow,
    AgentCanvasCreativeDirectionSnapshotRow,
    AgentCanvasExpertActivityRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasGuidanceTopicRow,
    AgentCanvasGuidanceAwaitingRow,
    AgentCanvasGuidedInteractionRow,
    AgentCanvasGuidedActionRow,
    AgentCanvasIdempotencyRow,
    AgentCanvasRequirementLedgerRow,
    AgentCanvasNodeRow,
    AgentCanvasSkillRunRow,
    AgentCanvasWorkflowRow,
    WorkflowEventRow,
)
from app.schemas.agent_canvas_requirements import CharacterOccurrenceV1
from app.schemas.agent_canvas_conversation import (
    AgentActionReceiptV2,
    ChatTimelineEntryV2,
    ChatTimelineListResponseV2,
    ChatTurnAcceptedV2,
    ChatTurnV2,
    ConceptOptionRecordV2,
    ConceptProposalV2,
    ContinuationCommitV2,
    ContinuationDeliveryV2,
    ProposalApplicationSummaryV2,
    ProposalMaterializationErrorV2,
    ProposalMaterializationProjectionV2,
    ProposalActionDescriptorV2,
    ProposalActionRequestV2,
    VideoSkillRunV2,
)
from app.schemas.agent_canvas_creative_session import (
    CreationModeDecisionV2,
    CreativeAuthorityStateV2,
    CreativeDirectionSnapshotV2,
    CreativeElementDecisionV2,
    CreativeGoalV2,
    ExpertActivityV2,
    GuidanceCompletionProjectionV2,
    GuidanceTopicStateV2,
    canonical_guidance_topic_kind,
    GuidedStepCheckpointV2,
    GuidedSessionStateV2,
    GuidanceSessionActionV2,
    ProjectCreativeMemoryV2,
    ProposedDraftReferenceV2,
)
from app.schemas.agent_canvas_capabilities import (
    CapabilityCommandEnvelopeV2,
    CharacterProposalTargetV1,
    NextActionEnvelopeV1,
)
from app.schemas.agent_canvas_capability_identity import (
    CAPABILITY_DISPLAY_NAMES,
)
from app.schemas.agent_canvas_production_journey import GuidedProductionJourneyV2
from app.schemas.agent_canvas_guidance import (
    ContinuationTurnRetrySnapshotV1,
    GuidanceAdvanceAuthorityPlanV1,
    GuidanceAdvanceCommitReceiptV1,
)
from app.schemas.agent_canvas_guided_checkpoint import GuidedCheckpointOriginV1
from app.schemas.agent_canvas_guided_interactions import (
    GuidanceAwaitingV2,
    GuidedChoiceOptionV1,
    GuidedInteractionV1,
    GuidedQuestionnaireV1,
    GuidedQuestionV1,
)
from app.schemas.agent_canvas_video_skills import VideoSkillPublicDetailV2
from app.schemas.agent_operation_recovery import AgentOperationFailureV2
from app.schemas.language import BCP47Tag, canonicalize_bcp47_tag
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_user_presentation import build_presentation_metadata
from app.services.agent_canvas_production_journey import (
    FIXED_JOURNEY_STAGE_DESCRIPTORS,
    initial_production_journey,
    parse_production_journey,
)


class AgentCanvasConversationRepository:
    """Persist observable Agent conversation state on the canonical V2 database."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Conversation and event repositories must share one database.")
        self._database = database
        self._events = events
        self._automatic_runs = AgentCanvasAutomaticRunRepository(database, events)
        self._requirements = AgentCanvasRequirementRepository(database)
        self._guidance_authority = GuidanceAdvanceAuthoritySnapshotRepository(self._requirements)

    @property
    def database(self) -> V2Database:
        return self._database

    @property
    def events(self) -> EventRepository:
        return self._events

    def get_guidance_session(self, workflow_id: str) -> GuidedSessionStateV2:
        session = self.get_guidance_session_or_none(workflow_id)
        if session is None:
            raise _error(
                "guidance_session_not_found",
                "Guidance session was not found.",
            )
        return session

    def get_guidance_session_or_none(
        self,
        workflow_id: str,
    ) -> GuidedSessionStateV2 | None:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasGuidanceSessionRow).where(
                            AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    return None
                return _guidance_session(connection, row)
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "conversation_persistence_unavailable",
                "Conversation storage failed.",
            ) from error

    def create_guidance_session(
        self,
        workflow_id: str,
        *,
        goal: CreativeGoalV2,
        element_decisions: tuple[CreativeElementDecisionV2, ...],
        character_occurrences: tuple[CharacterOccurrenceV1, ...] | None = None,
        active_style_skill_run_id: str | None,
        response_locale: BCP47Tag = "und",
    ) -> GuidedSessionStateV2:
        now = _now()
        locale = canonicalize_bcp47_tag(response_locale)
        session_id = f"guidance_{uuid4().hex}"
        completion = GuidanceCompletionProjectionV2()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    _require_workflow(connection, workflow_id)
                    existing = (
                        connection.execute(
                            select(AgentCanvasGuidanceSessionRow).where(
                                AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is not None:
                        result = _guidance_session(connection, existing)
                        connection.commit()
                        return result
                    connection.execute(
                        insert(AgentCanvasGuidanceSessionRow).values(
                            session_id=session_id,
                            workflow_id=workflow_id,
                            status="active",
                            response_locale=locale,
                            creative_goal_json=goal.model_dump_json(),
                            element_decisions_json=_dump(
                                [item.model_dump(mode="json") for item in element_decisions]
                            ),
                            creative_authority_json=None,
                            current_checkpoint_json=None,
                            narrative_direction=None,
                            current_topic_id=None,
                            active_proposal_id=None,
                            active_style_skill_run_id=active_style_skill_run_id,
                            completion_json=completion.model_dump_json(),
                            journey_state_json=initial_production_journey(
                                element_decisions,
                                character_occurrences=character_occurrences,
                            ).model_dump_json(),
                            revision=1,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            event_type="guidance_session_created",
                            created_at=now,
                            payload={
                                "session_id": session_id,
                                "session_revision": 1,
                            },
                        ),
                    )
                    row = (
                        connection.execute(
                            select(AgentCanvasGuidanceSessionRow).where(
                                AgentCanvasGuidanceSessionRow.session_id == session_id
                            )
                        )
                        .mappings()
                        .one()
                    )
                    result = _guidance_session(connection, row)
                    connection.commit()
                    return result
                except Exception:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "conversation_persistence_unavailable",
                "Conversation storage failed.",
            ) from error

    def replace_guidance_journey(
        self,
        session_id: str,
        *,
        journey: GuidedProductionJourneyV2,
        expected_session_revision: int,
        idempotency_key: str,
        event_type: str,
        event_payload: dict[str, object],
    ) -> GuidedSessionStateV2:
        if not idempotency_key or len(idempotency_key) > 256:
            raise _error("journey_evidence_invalid", "Journey idempotency key is invalid.")
        transition_key = f"journey:{session_id}:{idempotency_key}"
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    row = _require_guidance_session_row(connection, session_id)
                    existing_event = connection.execute(
                        select(WorkflowEventRow.id).where(
                            WorkflowEventRow.transition_key == transition_key
                        )
                    ).scalar_one_or_none()
                    if existing_event is not None:
                        result = _guidance_session(connection, row)
                        connection.commit()
                        return result
                    if int(row["revision"]) != expected_session_revision:
                        raise _error(
                            "journey_revision_conflict",
                            "Journey state changed before this transition.",
                        )
                    next_revision = expected_session_revision + 1
                    updated = connection.execute(
                        update(AgentCanvasGuidanceSessionRow)
                        .where(
                            AgentCanvasGuidanceSessionRow.session_id == session_id,
                            AgentCanvasGuidanceSessionRow.revision == expected_session_revision,
                        )
                        .values(
                            journey_state_json=journey.model_dump_json(),
                            revision=next_revision,
                            updated_at=now,
                        )
                    )
                    if updated.rowcount != 1:
                        raise _error(
                            "journey_revision_conflict",
                            "Journey state changed before this transition.",
                        )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=str(row["workflow_id"]),
                            event_type=event_type,
                            transition_key=transition_key,
                            created_at=now,
                            payload={
                                "session_id": session_id,
                                "session_revision": next_revision,
                                "stage": journey.stage,
                                "stage_revision": journey.stage_revision,
                                **event_payload,
                            },
                        ),
                    )
                    result = _guidance_session(
                        connection,
                        _require_guidance_session_row(connection, session_id),
                    )
                    connection.commit()
                    return result
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "conversation_persistence_unavailable",
                "Conversation storage failed.",
            ) from error

    def complete_turn_with_clarification(
        self,
        turn_id: str,
        *,
        expected_session_revision: int,
        journey: GuidedProductionJourneyV2,
        assistant_message: str,
        transition_key: str,
        questionnaire: GuidedQuestionnaireV1 | None = None,
        checkpoint_id: str | None = None,
        interaction_title: str | None = None,
        interaction_context: str | None = None,
        expected_requirement_revision: int | None = None,
    ) -> ChatTurnV2:
        """Atomically publish clarification authority and complete its source Turn."""

        if not transition_key or len(transition_key) > 256 or turn_id not in transition_key:
            raise _error(
                "journey_evidence_invalid",
                "Clarification transition identity is invalid.",
            )
        if journey.stage not in {"intake", "character"} or journey.stage_status != "waiting_user":
            raise _error(
                "journey_transition_invalid",
                "Clarification completion requires a waiting intake or Character journey.",
            )
        now = _now()
        journey_payload = journey.model_dump(mode="json")
        journey_digest = _sha256_json(journey_payload)
        assistant_digest = hashlib.sha256(assistant_message.encode("utf-8")).hexdigest()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    turn = _require_turn(connection, turn_id)
                    workflow_id = str(turn["workflow_id"])
                    session_row = _require_guidance_session_row_by_workflow(
                        connection,
                        workflow_id,
                    )
                    session_id = str(session_row["session_id"])
                    if expected_requirement_revision is not None:
                        requirement_row = (
                            connection.execute(
                                select(AgentCanvasRequirementLedgerRow).where(
                                    AgentCanvasRequirementLedgerRow.workflow_id == workflow_id
                                )
                            )
                            .mappings()
                            .one_or_none()
                        )
                        if (
                            requirement_row is None
                            or int(requirement_row["current_revision_no"])
                            != expected_requirement_revision
                        ):
                            raise _error(
                                "journey_revision_conflict",
                                "Requirements changed before this clarification transition.",
                            )
                    event_transition_key = f"journey:{session_id}:{transition_key}"
                    existing_event = (
                        connection.execute(
                            select(WorkflowEventRow).where(
                                WorkflowEventRow.transition_key == event_transition_key
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing_event is not None:
                        payload = json.loads(str(existing_event["payload_json"]))
                        if (
                            str(turn["status"]) != "completed"
                            or payload.get("turn_id") != turn_id
                            or payload.get("journey_digest") != journey_digest
                            or payload.get("assistant_digest") != assistant_digest
                        ):
                            raise _error(
                                "journey_transition_conflict",
                                "Clarification transition identity was reused with different content.",
                            )
                        result = _turn(turn)
                        connection.commit()
                        return result

                    if int(session_row["revision"]) != expected_session_revision:
                        raise _error(
                            "journey_revision_conflict",
                            "Journey state changed before this transition.",
                        )
                    current_journey = parse_production_journey(
                        str(session_row["journey_state_json"])
                    )
                    _validate_clarification_target(
                        current=current_journey,
                        target=journey,
                        turn_id=turn_id,
                    )
                    next_revision = expected_session_revision + 1
                    updated = connection.execute(
                        update(AgentCanvasGuidanceSessionRow)
                        .where(
                            AgentCanvasGuidanceSessionRow.session_id == session_id,
                            AgentCanvasGuidanceSessionRow.revision == expected_session_revision,
                        )
                        .values(
                            journey_state_json=journey.model_dump_json(),
                            revision=next_revision,
                            updated_at=now,
                        )
                    )
                    if updated.rowcount != 1:
                        raise _error(
                            "journey_revision_conflict",
                            "Journey state changed before this transition.",
                        )
                    _upsert_clarification_authority(
                        connection,
                        events=self._events,
                        workflow_id=workflow_id,
                        session_id=session_id,
                        response_locale=str(session_row["response_locale"]),
                        expected_session_revision=next_revision,
                        journey=journey,
                        assistant_message=assistant_message,
                        questionnaire=questionnaire,
                        checkpoint_id=checkpoint_id,
                        interaction_title=interaction_title,
                        interaction_context=interaction_context,
                        now=now,
                    )
                    evidence = next(
                        (
                            item
                            for item in reversed(journey.transition_evidence)
                            if item.source_id == turn_id
                        ),
                        None,
                    )
                    event_type = (
                        "journey_stage_changed"
                        if current_journey.stage != journey.stage
                        else "journey_stage_waiting_user"
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            conversation_id=str(turn["conversation_id"]),
                            turn_id=turn_id,
                            event_type=event_type,
                            transition_key=event_transition_key,
                            created_at=now,
                            payload={
                                "session_id": session_id,
                                "session_revision": next_revision,
                                "turn_id": turn_id,
                                "previous_stage": current_journey.stage,
                                "next_stage": journey.stage,
                                "stage": journey.stage,
                                "stage_status": journey.stage_status,
                                "stage_revision": journey.stage_revision,
                                "evidence_id": evidence.evidence_id if evidence else None,
                                "evidence_kind": evidence.evidence_kind if evidence else None,
                                "journey_digest": journey_digest,
                                "assistant_digest": assistant_digest,
                            },
                        ),
                    )
                    _complete_turn_in_transaction(
                        connection,
                        events=self._events,
                        turn=turn,
                        assistant_message=assistant_message,
                        now=now,
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "conversation_persistence_unavailable",
                "Conversation storage failed.",
            ) from error
        return self.get_turn(turn_id)

    def close_current_clarification(
        self,
        workflow_id: str,
        *,
        source_turn_id: str,
        expected_session_revision: int,
    ) -> bool:
        """Close the current typed clarification from exact user Turn evidence."""

        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    session = _require_guidance_session_row_by_workflow(
                        connection,
                        workflow_id,
                    )
                    _require_guidance_revision(session, expected_session_revision)
                    interaction_row = (
                        connection.execute(
                            select(AgentCanvasGuidedInteractionRow).where(
                                AgentCanvasGuidedInteractionRow.workflow_id == workflow_id,
                                AgentCanvasGuidedInteractionRow.kind
                                == "clarification_questionnaire",
                                AgentCanvasGuidedInteractionRow.status == "open",
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    awaiting_row = (
                        connection.execute(
                            select(AgentCanvasGuidanceAwaitingRow).where(
                                AgentCanvasGuidanceAwaitingRow.workflow_id == workflow_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if interaction_row is None and awaiting_row is None:
                        connection.rollback()
                        return False
                    if (
                        interaction_row is None
                        or awaiting_row is None
                        or str(awaiting_row["kind"]) != "clarification"
                        or awaiting_row["interaction_id"] != interaction_row["interaction_id"]
                    ):
                        raise _error(
                            "guidance_resume_evidence_missing",
                            "Clarification authority is incomplete and cannot be resumed.",
                        )
                    interaction_id = str(interaction_row["interaction_id"])
                    awaiting_id = str(awaiting_row["awaiting_id"])
                    connection.execute(
                        update(AgentCanvasGuidedInteractionRow)
                        .where(
                            AgentCanvasGuidedInteractionRow.interaction_id == interaction_id,
                            AgentCanvasGuidedInteractionRow.status == "open",
                        )
                        .values(
                            status="closed",
                            revision=int(interaction_row["revision"]) + 1,
                            updated_at=now,
                        )
                    )
                    connection.execute(
                        delete(AgentCanvasGuidanceAwaitingRow).where(
                            AgentCanvasGuidanceAwaitingRow.awaiting_id == awaiting_id
                        )
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            turn_id=source_turn_id,
                            event_type="guided_interaction_closed",
                            transition_key=(
                                f"guided-interaction:{interaction_id}:closed:{source_turn_id}"
                            ),
                            action_id=interaction_id,
                            created_at=now,
                            payload={
                                "interaction_id": interaction_id,
                                "source_turn_id": source_turn_id,
                                "reason": "clarification_completed",
                            },
                        ),
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            turn_id=source_turn_id,
                            event_type="guidance_awaiting_resumed",
                            transition_key=f"guidance-awaiting:{awaiting_id}:resumed",
                            action_id=interaction_id,
                            created_at=now,
                            payload={
                                "awaiting_id": awaiting_id,
                                "checkpoint_id": str(awaiting_row["checkpoint_id"]),
                                "kind": "clarification",
                                "resume_policy": "submit_interaction",
                                "resume_evidence": "user_turn_requirement_update",
                                "interaction_id": interaction_id,
                                "source_turn_id": source_turn_id,
                            },
                        ),
                    )
                    connection.commit()
                    return True
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "conversation_persistence_unavailable",
                "Conversation storage failed.",
            ) from error

    def set_creative_authority(
        self,
        session_id: str,
        authority: CreativeAuthorityStateV2,
        *,
        expected_session_revision: int,
    ) -> GuidedSessionStateV2:
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    row = _require_guidance_session_row(connection, session_id)
                    _require_guidance_revision(row, expected_session_revision)
                    next_revision = expected_session_revision + 1
                    connection.execute(
                        update(AgentCanvasGuidanceSessionRow)
                        .where(
                            AgentCanvasGuidanceSessionRow.session_id == session_id,
                            AgentCanvasGuidanceSessionRow.revision == expected_session_revision,
                        )
                        .values(
                            creative_authority_json=authority.model_dump_json(),
                            revision=next_revision,
                            updated_at=now,
                        )
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=str(row["workflow_id"]),
                            event_type="guidance_authority_updated",
                            created_at=now,
                            payload={
                                "session_id": session_id,
                                "session_revision": next_revision,
                                "authority": authority.authority,
                                "source": authority.source,
                            },
                        ),
                    )
                    updated = _require_guidance_session_row(connection, session_id)
                    result = _guidance_session(connection, updated)
                    connection.commit()
                    return result
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "conversation_persistence_unavailable",
                "Conversation storage failed.",
            ) from error

    def set_narrative_direction(
        self,
        session_id: str,
        narrative_direction: str,
        *,
        element_decisions: tuple[CreativeElementDecisionV2, ...],
        expected_session_revision: int,
    ) -> GuidedSessionStateV2:
        narrative = narrative_direction.strip()
        if not narrative or len(narrative) > 4_096:
            raise _error(
                "guidance_narrative_invalid",
                "Narrative direction must be a bounded non-empty summary.",
            )
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    row = _require_guidance_session_row(connection, session_id)
                    _require_guidance_revision(row, expected_session_revision)
                    next_revision = expected_session_revision + 1
                    connection.execute(
                        update(AgentCanvasGuidanceSessionRow)
                        .where(
                            AgentCanvasGuidanceSessionRow.session_id == session_id,
                            AgentCanvasGuidanceSessionRow.revision == expected_session_revision,
                        )
                        .values(
                            narrative_direction=narrative,
                            element_decisions_json=_dump(
                                [item.model_dump(mode="json") for item in element_decisions]
                            ),
                            revision=next_revision,
                            updated_at=now,
                        )
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=str(row["workflow_id"]),
                            event_type="guidance_narrative_updated",
                            created_at=now,
                            payload={
                                "session_id": session_id,
                                "session_revision": next_revision,
                            },
                        ),
                    )
                    updated = _require_guidance_session_row(connection, session_id)
                    result = _guidance_session(connection, updated)
                    connection.commit()
                    return result
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "conversation_persistence_unavailable",
                "Conversation storage failed.",
            ) from error

    def create_guidance_topic(
        self,
        session_id: str,
        topic: GuidanceTopicStateV2,
        *,
        expected_session_revision: int,
    ) -> GuidedSessionStateV2:
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    session_row = _require_guidance_session_row(connection, session_id)
                    _require_guidance_revision(session_row, expected_session_revision)
                    connection.execute(
                        insert(AgentCanvasGuidanceTopicRow).values(
                            session_id=session_id,
                            topic_id=topic.topic_id,
                            topic_kind=topic.topic_kind,
                            title=topic.title,
                            status=topic.status,
                            capability_id=topic.capability_id,
                            related_node_ids_json=_dump(list(topic.related_node_ids)),
                            source_proposal_id=topic.source_proposal_id,
                            revision=topic.revision,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    next_revision = expected_session_revision + 1
                    connection.execute(
                        update(AgentCanvasGuidanceSessionRow)
                        .where(AgentCanvasGuidanceSessionRow.session_id == session_id)
                        .values(
                            current_topic_id=topic.topic_id,
                            revision=next_revision,
                            updated_at=now,
                        )
                    )
                    workflow_id = str(session_row["workflow_id"])
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            event_type="guidance_topic_created",
                            created_at=now,
                            payload={
                                "session_id": session_id,
                                "session_revision": next_revision,
                                "topic_id": topic.topic_id,
                                "topic_kind": topic.topic_kind,
                            },
                        ),
                    )
                    row = _require_guidance_session_row(connection, session_id)
                    result = _guidance_session(connection, row)
                    connection.commit()
                    return result
                except Exception:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _error("guidance_topic_conflict", "Guidance topic already exists.") from error
        except SQLAlchemyError as error:
            raise _error(
                "conversation_persistence_unavailable",
                "Conversation storage failed.",
            ) from error

    def complete_guidance_session(
        self,
        session_id: str,
        *,
        expected_session_revision: int,
        completion: GuidanceCompletionProjectionV2,
        journey: GuidedProductionJourneyV2 | None = None,
    ) -> GuidedSessionStateV2:
        now = _now()
        with self._database.engine.begin() as connection:
            row = _require_guidance_session_row(connection, session_id)
            _require_guidance_revision(row, expected_session_revision)
            values: dict[str, object] = {
                "status": "completed",
                "completion_json": completion.model_dump_json(),
                "current_topic_id": None,
                "active_proposal_id": None,
                "revision": expected_session_revision + 1,
                "updated_at": now,
            }
            if journey is not None:
                values["journey_state_json"] = journey.model_dump_json()
            connection.execute(
                update(AgentCanvasGuidanceSessionRow)
                .where(AgentCanvasGuidanceSessionRow.session_id == session_id)
                .values(**values)
            )
        return self.get_guidance_session(str(row["workflow_id"]))

    def update_guidance_completion(
        self,
        session_id: str,
        *,
        expected_session_revision: int,
        completion: GuidanceCompletionProjectionV2,
    ) -> GuidedSessionStateV2:
        """Update delivery evidence without completing the Guidance session."""

        now = _now()
        with self._database.engine.begin() as connection:
            row = _require_guidance_session_row(connection, session_id)
            _require_guidance_revision(row, expected_session_revision)
            connection.execute(
                update(AgentCanvasGuidanceSessionRow)
                .where(
                    AgentCanvasGuidanceSessionRow.session_id == session_id,
                    AgentCanvasGuidanceSessionRow.revision == expected_session_revision,
                )
                .values(
                    completion_json=completion.model_dump_json(),
                    revision=expected_session_revision + 1,
                    updated_at=now,
                )
            )
        return self.get_guidance_session(str(row["workflow_id"]))

    def set_guidance_checkpoint(
        self,
        session_id: str,
        checkpoint: GuidedStepCheckpointV2,
        *,
        expected_session_revision: int,
    ) -> GuidedSessionStateV2:
        """Persist one bounded checkpoint without advancing semantic session state."""

        now = _now()
        with self._database.engine.begin() as connection:
            row = _require_guidance_session_row(connection, session_id)
            _require_guidance_revision(row, expected_session_revision)
            if (
                checkpoint.workflow_id != str(row["workflow_id"])
                or checkpoint.session_revision != expected_session_revision
            ):
                raise _error(
                    "guided_continuation_invalid",
                    "Guidance checkpoint does not match the current session.",
                )
            connection.execute(
                update(AgentCanvasGuidanceSessionRow)
                .where(
                    AgentCanvasGuidanceSessionRow.session_id == session_id,
                    AgentCanvasGuidanceSessionRow.revision == expected_session_revision,
                )
                .values(
                    current_checkpoint_json=checkpoint.model_dump_json(),
                    updated_at=now,
                )
            )
            self._events.append_in_transaction(
                connection,
                V2EventInsert(
                    workflow_id=checkpoint.workflow_id,
                    action_id=checkpoint.action_id,
                    event_type="guidance_state_updated",
                    created_at=now,
                    payload={
                        "session_id": session_id,
                        "session_revision": expected_session_revision,
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "checkpoint_status": checkpoint.status,
                    },
                ),
            )
        return self.get_guidance_session(str(row["workflow_id"]))

    def create_skill_run(
        self,
        workflow_id: str,
        *,
        skill_id: str,
        skill_version: str,
        idempotency_key: str,
        source_skill_run_id: str | None = None,
    ) -> VideoSkillRunV2:
        now = _now()
        try:
            with self._database.engine.begin() as connection:
                existing = (
                    connection.execute(
                        select(AgentCanvasSkillRunRow).where(
                            AgentCanvasSkillRunRow.idempotency_key == idempotency_key
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if (
                        str(existing["workflow_id"]) != workflow_id
                        or str(existing["skill_id"]) != skill_id
                        or str(existing["skill_version"]) != skill_version
                    ):
                        raise _error("idempotency_conflict", "Idempotency key was reused.")
                    return _skill_run(existing)
                _require_workflow(connection, workflow_id)
                skill_run_id = f"skill_run_{uuid4().hex}"
                connection.execute(
                    update(AgentCanvasSkillRunRow)
                    .where(
                        AgentCanvasSkillRunRow.workflow_id == workflow_id,
                        AgentCanvasSkillRunRow.status == "active",
                    )
                    .values(status="superseded", updated_at=now)
                )
                connection.execute(
                    insert(AgentCanvasSkillRunRow).values(
                        skill_run_id=skill_run_id,
                        workflow_id=workflow_id,
                        skill_id=skill_id,
                        skill_version=skill_version,
                        source_skill_run_id=source_skill_run_id,
                        status="active",
                        active_creative_direction_snapshot_id=None,
                        idempotency_key=idempotency_key,
                        created_at=now,
                        updated_at=now,
                    )
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        event_type="video_skill_run_created",
                        created_at=now,
                        payload={
                            "skill_run_id": skill_run_id,
                            "skill_id": skill_id,
                            "skill_version": skill_version,
                        },
                    ),
                )
                return self._get_skill_run_in_transaction(connection, skill_run_id)
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error

    def activate_style_skill(
        self,
        *,
        workflow_id: str,
        skill_run: VideoSkillRunV2,
        snapshot: CreativeDirectionSnapshotV2,
        public_skill: VideoSkillPublicDetailV2,
        request_fingerprint: str,
        idempotency_key: str,
    ) -> VideoSkillRunV2:
        """Atomically activate one verified package and its frozen snapshot."""

        if (
            skill_run.workflow_id != workflow_id
            or snapshot.workflow_id != workflow_id
            or snapshot.skill_run_id != skill_run.skill_run_id
            or snapshot.snapshot_id != skill_run.active_creative_direction_snapshot_id
            or snapshot.source_skill_id != skill_run.skill_id
            or snapshot.source_skill_version != skill_run.skill_version
            or public_skill.skill_id != skill_run.skill_id
            or public_skill.version != skill_run.skill_version
        ):
            raise _error(
                "style_skill_snapshot_invalid",
                "Style Skill activation state is inconsistent.",
            )
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    replay = _load_style_activation_idempotency(
                        connection,
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_fingerprint,
                    )
                    if replay is not None:
                        connection.commit()
                        return VideoSkillRunV2.model_validate_json(replay)

                    _require_workflow(connection, workflow_id)
                    active = (
                        connection.execute(
                            select(AgentCanvasSkillRunRow).where(
                                AgentCanvasSkillRunRow.workflow_id == workflow_id,
                                AgentCanvasSkillRunRow.status == "active",
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    active_id = str(active["skill_run_id"]) if active is not None else None
                    if (
                        skill_run.source_skill_run_id is not None
                        and skill_run.source_skill_run_id != active_id
                    ):
                        raise _error(
                            "style_skill_activation_conflict",
                            "The active Style Skill changed before activation.",
                        )
                    if active is not None and (
                        str(active["skill_id"]) == skill_run.skill_id
                        and str(active["skill_version"]) == skill_run.skill_version
                        and active["active_creative_direction_snapshot_id"] is not None
                    ):
                        result = _skill_run_with_public(connection, active)
                        _store_style_activation_idempotency(
                            connection,
                            idempotency_key=idempotency_key,
                            request_fingerprint=request_fingerprint,
                            response_json=result.model_dump_json(),
                            created_at=now,
                        )
                        connection.commit()
                        return result

                    connection.execute(
                        update(AgentCanvasSkillRunRow)
                        .where(
                            AgentCanvasSkillRunRow.workflow_id == workflow_id,
                            AgentCanvasSkillRunRow.status == "active",
                        )
                        .values(status="superseded", updated_at=now)
                    )
                    connection.execute(
                        insert(AgentCanvasSkillRunRow).values(
                            skill_run_id=skill_run.skill_run_id,
                            workflow_id=workflow_id,
                            skill_id=skill_run.skill_id,
                            skill_version=skill_run.skill_version,
                            source_skill_run_id=skill_run.source_skill_run_id,
                            status="active",
                            active_creative_direction_snapshot_id=snapshot.snapshot_id,
                            idempotency_key=idempotency_key,
                            created_at=skill_run.created_at.isoformat(),
                            updated_at=now,
                        )
                    )
                    connection.execute(
                        insert(AgentCanvasCreativeDirectionSnapshotRow).values(
                            snapshot_id=snapshot.snapshot_id,
                            workflow_id=workflow_id,
                            skill_run_id=skill_run.skill_run_id,
                            version=snapshot.version,
                            source_skill_id=snapshot.source_skill_id,
                            source_skill_version=snapshot.source_skill_version,
                            source_skill_digest=snapshot.source_skill_digest,
                            global_direction_json=_dump(snapshot.global_direction),
                            role_projections_json=_dump(snapshot.role_projections),
                            source_message_id=snapshot.source_message_id,
                            source_proposal_id=snapshot.source_proposal_id,
                            content_digest=snapshot.content_digest,
                            created_at=snapshot.created_at.isoformat(),
                        )
                    )
                    event_payload = {
                        "workflow_id": workflow_id,
                        "skill_run_id": skill_run.skill_run_id,
                        "skill_id": skill_run.skill_id,
                        "skill_version": skill_run.skill_version,
                        "creative_direction_snapshot_id": snapshot.snapshot_id,
                        "package_digest": snapshot.source_skill_digest,
                    }
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            event_type="creative_direction_snapshot_created",
                            created_at=snapshot.created_at.isoformat(),
                            payload=event_payload,
                        ),
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            event_type="style_skill_activated",
                            created_at=snapshot.created_at.isoformat(),
                            payload=event_payload,
                        ),
                    )
                    result = self._get_skill_run_in_transaction(connection, skill_run.skill_run_id)
                    _store_style_activation_idempotency(
                        connection,
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_fingerprint,
                        response_json=result.model_dump_json(),
                        created_at=now,
                    )
                    connection.commit()
                    return result
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error

    def get_skill_run(self, skill_run_id: str) -> VideoSkillRunV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasSkillRunRow).where(
                            AgentCanvasSkillRunRow.skill_run_id == skill_run_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is not None:
                    return _skill_run_with_public(connection, row)
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        if row is None:
            raise _error("creative_session_not_found", "Creative session was not found.")
        raise AssertionError("Unreachable skill run lookup state.")

    def get_active_style_skill_run(self, workflow_id: str) -> VideoSkillRunV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasSkillRunRow).where(
                            AgentCanvasSkillRunRow.workflow_id == workflow_id,
                            AgentCanvasSkillRunRow.status == "active",
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is not None:
                    return _skill_run_with_public(connection, row)
        except SQLAlchemyError as error:
            raise _error(
                "conversation_persistence_unavailable",
                "Conversation storage failed.",
            ) from error
        if row is None:
            raise _error("style_skill_run_not_found", "Style Skill Run was not found.")
        raise AssertionError("Unreachable active skill run lookup state.")

    @staticmethod
    def _get_skill_run_in_transaction(
        connection: Connection,
        skill_run_id: str,
    ) -> VideoSkillRunV2:
        row = (
            connection.execute(
                select(AgentCanvasSkillRunRow).where(
                    AgentCanvasSkillRunRow.skill_run_id == skill_run_id
                )
            )
            .mappings()
            .one()
        )
        return _skill_run_with_public(connection, row)

    def persist_creation_mode(
        self,
        turn_id: str,
        decision: CreationModeDecisionV2,
    ) -> CreationModeDecisionV2:
        now = _now()
        serialized = decision.model_dump_json()
        try:
            with self._database.engine.begin() as connection:
                turn = _require_turn(connection, turn_id)
                connection.execute(
                    update(AgentCanvasChatTurnRow)
                    .where(AgentCanvasChatTurnRow.turn_id == turn_id)
                    .values(creation_mode_json=serialized, updated_at=now)
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=str(turn["workflow_id"]),
                        event_type="creation_mode_resolved",
                        created_at=now,
                        payload={
                            "workflow_id": str(turn["workflow_id"]),
                            "conversation_id": str(turn["conversation_id"]),
                            "turn_id": turn_id,
                            "creation_mode": decision.mode,
                            "target_node_id": decision.target_node_id,
                            "target_asset_id": decision.target_asset_id,
                        },
                    ),
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable",
                "Conversation storage failed.",
            ) from error
        return decision

    def create_creative_direction_snapshot(
        self,
        snapshot: CreativeDirectionSnapshotV2,
    ) -> CreativeDirectionSnapshotV2:
        try:
            with self._database.engine.begin() as connection:
                session = (
                    connection.execute(
                        select(AgentCanvasSkillRunRow).where(
                            AgentCanvasSkillRunRow.skill_run_id == snapshot.skill_run_id,
                            AgentCanvasSkillRunRow.workflow_id == snapshot.workflow_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if session is None:
                    raise _error(
                        "creative_session_not_found",
                        "Creative session was not found.",
                    )
                connection.execute(
                    insert(AgentCanvasCreativeDirectionSnapshotRow).values(
                        snapshot_id=snapshot.snapshot_id,
                        workflow_id=snapshot.workflow_id,
                        skill_run_id=snapshot.skill_run_id,
                        version=snapshot.version,
                        source_skill_id=snapshot.source_skill_id,
                        source_skill_version=snapshot.source_skill_version,
                        source_skill_digest=snapshot.source_skill_digest,
                        global_direction_json=_dump(snapshot.global_direction),
                        role_projections_json=_dump(snapshot.role_projections),
                        source_message_id=snapshot.source_message_id,
                        source_proposal_id=snapshot.source_proposal_id,
                        content_digest=snapshot.content_digest,
                        created_at=snapshot.created_at.isoformat(),
                    )
                )
                connection.execute(
                    update(AgentCanvasSkillRunRow)
                    .where(AgentCanvasSkillRunRow.skill_run_id == snapshot.skill_run_id)
                    .values(active_creative_direction_snapshot_id=snapshot.snapshot_id)
                )
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _error(
                "creative_direction_version_conflict",
                "Creative Direction snapshot version already exists.",
            ) from error
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable",
                "Conversation storage failed.",
            ) from error
        return snapshot

    def get_creative_direction_snapshot(
        self,
        snapshot_id: str,
    ) -> CreativeDirectionSnapshotV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasCreativeDirectionSnapshotRow).where(
                            AgentCanvasCreativeDirectionSnapshotRow.snapshot_id == snapshot_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable",
                "Conversation storage failed.",
            ) from error
        if row is None:
            raise _error(
                "creative_direction_snapshot_not_found",
                "Creative Direction snapshot was not found.",
            )
        return _creative_direction_snapshot(row)

    def get_active_creative_direction_snapshot(
        self,
        workflow_id: str,
    ) -> CreativeDirectionSnapshotV2:
        try:
            with self._database.engine.connect() as connection:
                snapshot_id = connection.execute(
                    select(AgentCanvasSkillRunRow.active_creative_direction_snapshot_id).where(
                        AgentCanvasSkillRunRow.workflow_id == workflow_id,
                        AgentCanvasSkillRunRow.status == "active",
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable",
                "Conversation storage failed.",
            ) from error
        if snapshot_id is None:
            raise _error(
                "creative_direction_snapshot_not_found",
                "Creative Direction snapshot was not found.",
            )
        return self.get_creative_direction_snapshot(str(snapshot_id))

    def get_creative_memory(self, workflow_id: str) -> ProjectCreativeMemoryV2:
        try:
            with self._database.engine.connect() as connection:
                _require_workflow(connection, workflow_id)
                row = (
                    connection.execute(
                        select(AgentCanvasCreativeMemoryRow).where(
                            AgentCanvasCreativeMemoryRow.workflow_id == workflow_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return _creative_memory(row, workflow_id)

    def upsert_creative_memory(
        self,
        memory: ProjectCreativeMemoryV2,
    ) -> ProjectCreativeMemoryV2:
        now = _now()
        try:
            with self._database.engine.begin() as connection:
                _require_workflow(connection, memory.workflow_id)
                current = (
                    connection.execute(
                        select(AgentCanvasCreativeMemoryRow).where(
                            AgentCanvasCreativeMemoryRow.workflow_id == memory.workflow_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                next_revision = (int(current["memory_revision"]) if current else 0) + 1
                values = _creative_memory_values(
                    memory,
                    next_revision,
                    created_at=str(current["created_at"]) if current else now,
                    updated_at=now,
                )
                if current is None:
                    connection.execute(insert(AgentCanvasCreativeMemoryRow).values(**values))
                else:
                    connection.execute(
                        update(AgentCanvasCreativeMemoryRow)
                        .where(AgentCanvasCreativeMemoryRow.workflow_id == memory.workflow_id)
                        .values(**values)
                    )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=memory.workflow_id,
                        event_type="workflow_projection_updated",
                        created_at=now,
                        payload={
                            "memory_revision": next_revision,
                            "refresh": ["conversation"],
                        },
                    ),
                )
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_creative_memory(memory.workflow_id)

    def reconcile_deleted_memory_nodes(self, workflow_id: str) -> ProjectCreativeMemoryV2:
        now = _now()
        try:
            with self._database.engine.begin() as connection:
                _require_workflow(connection, workflow_id)
                row = (
                    connection.execute(
                        select(AgentCanvasCreativeMemoryRow).where(
                            AgentCanvasCreativeMemoryRow.workflow_id == workflow_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                memory = _creative_memory(row, workflow_id)
                existing_node_ids = {
                    str(node_id)
                    for node_id in connection.execute(
                        select(AgentCanvasNodeRow.node_id).where(
                            AgentCanvasNodeRow.workflow_id == workflow_id
                        )
                    ).scalars()
                }
                approved_node_ids = {
                    role: tuple(node_id for node_id in node_ids if node_id in existing_node_ids)
                    for role, node_ids in memory.approved_node_ids.items()
                }
                approved_node_ids = {
                    role: node_ids for role, node_ids in approved_node_ids.items() if node_ids
                }
                if approved_node_ids == memory.approved_node_ids:
                    return memory
                next_revision = memory.memory_revision + 1
                values = _creative_memory_values(
                    memory.model_copy(update={"approved_node_ids": approved_node_ids}),
                    next_revision,
                    created_at=str(row["created_at"]) if row else now,
                    updated_at=now,
                )
                if row is None:
                    connection.execute(insert(AgentCanvasCreativeMemoryRow).values(**values))
                else:
                    connection.execute(
                        update(AgentCanvasCreativeMemoryRow)
                        .where(AgentCanvasCreativeMemoryRow.workflow_id == workflow_id)
                        .values(**values)
                    )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        event_type="workflow_projection_updated",
                        created_at=now,
                        payload={
                            "memory_revision": next_revision,
                            "reconciled_deleted_node_references": True,
                            "refresh": ["conversation"],
                        },
                    ),
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_creative_memory(workflow_id)

    def create_user_turn(
        self,
        workflow_id: str,
        *,
        text: str,
        mentioned_node_ids: tuple[str, ...],
        mentioned_image_asset_ids: tuple[str, ...],
        video_skill_run_id: str | None,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        request = {
            "text": text,
            "mentioned_node_ids": list(mentioned_node_ids),
            "mentioned_image_asset_ids": list(mentioned_image_asset_ids),
            "video_skill_run_id": video_skill_run_id,
        }
        return self._create_turn(
            workflow_id,
            turn_kind="message",
            request=request,
            idempotency_key=idempotency_key,
            user_message=text,
        )

    def create_media_review_wait_turn(
        self,
        workflow_id: str,
        *,
        text: str,
        mentioned_node_ids: tuple[str, ...],
        mentioned_image_asset_ids: tuple[str, ...],
        video_skill_run_id: str | None,
        idempotency_key: str,
        interaction: GuidedInteractionV1,
        awaiting: GuidanceAwaitingV2,
        expected_session_revision: int,
    ) -> ChatTurnAcceptedV2:
        """Persist one informational message while typed media review owns progress."""

        request = {
            "text": text,
            "mentioned_node_ids": list(mentioned_node_ids),
            "mentioned_image_asset_ids": list(mentioned_image_asset_ids),
            "video_skill_run_id": video_skill_run_id,
        }
        request_json = _dump(request)
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    existing = (
                        connection.execute(
                            select(AgentCanvasChatTurnRow).where(
                                AgentCanvasChatTurnRow.idempotency_key == idempotency_key
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is not None:
                        if (
                            str(existing["workflow_id"]) != workflow_id
                            or str(existing["request_json"]) != request_json
                        ):
                            raise _error("idempotency_conflict", "Idempotency key was reused.")
                        cursor = int(
                            connection.execute(
                                select(func.coalesce(func.max(WorkflowEventRow.seq), 0)).where(
                                    WorkflowEventRow.workflow_id == workflow_id,
                                )
                            ).scalar_one()
                        )
                        result = ChatTurnAcceptedV2(
                            workflow_id=workflow_id,
                            conversation_id=str(existing["conversation_id"]),
                            message_id=self._message_id_for_turn(
                                connection, str(existing["turn_id"])
                            ),
                            turn_id=str(existing["turn_id"]),
                            events_cursor=cursor,
                            replayed=True,
                        )
                        connection.commit()
                        return result

                    session = _require_guidance_session_row_by_workflow(
                        connection,
                        workflow_id,
                    )
                    current_interaction = (
                        connection.execute(
                            select(AgentCanvasGuidedInteractionRow).where(
                                AgentCanvasGuidedInteractionRow.workflow_id == workflow_id,
                                AgentCanvasGuidedInteractionRow.status == "open",
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    current_awaiting = (
                        connection.execute(
                            select(AgentCanvasGuidanceAwaitingRow).where(
                                AgentCanvasGuidanceAwaitingRow.workflow_id == workflow_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if (
                        int(session["revision"]) != expected_session_revision
                        or current_interaction is None
                        or str(current_interaction["interaction_id"]) != interaction.interaction_id
                        or int(current_interaction["revision"]) != interaction.revision
                        or str(current_interaction["kind"]) != "media_review"
                        or current_awaiting is None
                        or str(current_awaiting["awaiting_id"]) != awaiting.awaiting_id
                        or str(current_awaiting["interaction_id"]) != interaction.interaction_id
                        or str(current_awaiting["kind"]) != "media_review"
                    ):
                        raise _error(
                            "guided_interaction_stale",
                            "Media review authority changed before the message was recorded.",
                        )

                    conversation_id = _ensure_conversation(connection, workflow_id, now)
                    turn_id = f"turn_{uuid4().hex}"
                    message_id = f"msg_{uuid4().hex}"
                    connection.execute(
                        insert(AgentCanvasChatEntryRow).values(
                            entry_id=message_id,
                            conversation_id=conversation_id,
                            workflow_id=workflow_id,
                            sequence_no=_next_chat_sequence(connection, conversation_id),
                            entry_type="message",
                            speaker="user",
                            content=text,
                            metadata_json=_dump({"turn_id": turn_id}),
                            created_at=now,
                        )
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            conversation_id=conversation_id,
                            turn_id=turn_id,
                            event_type="chat_message_created",
                            created_at=now,
                            payload={
                                "message_id": message_id,
                                "turn_id": turn_id,
                                "speaker": "user",
                            },
                        ),
                    )
                    connection.execute(
                        insert(AgentCanvasChatTurnRow).values(
                            turn_id=turn_id,
                            conversation_id=conversation_id,
                            workflow_id=workflow_id,
                            turn_kind="message",
                            status="completed",
                            request_json=request_json,
                            idempotency_key=idempotency_key,
                            retry_of_turn_id=None,
                            retry_attempt_no=1,
                            retryable=False,
                            operation_stage="completed",
                            operation_failure_json=None,
                            retry_snapshot_json="{}",
                            error_code=None,
                            error_message=None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    turn = _require_turn(connection, turn_id)
                    allowed_actions = list(interaction.allowed_actions)
                    fallback = (
                        f"{interaction.title} is waiting for review. "
                        f"Use {', '.join(allowed_actions)} to continue."
                    )
                    _publish_assistant_message_in_transaction(
                        connection,
                        events=self._events,
                        turn=turn,
                        assistant_message=fallback,
                        now=now,
                        entry_id=f"msg_{uuid4().hex}",
                        metadata=build_presentation_metadata(
                            message_key="media_review.pending_action",
                            message_args={
                                "allowed_actions": allowed_actions,
                                "media_title": interaction.title,
                            },
                            response_locale=str(session["response_locale"]),
                            presentation_key=f"turn:{turn_id}:media-review-wait",
                        ),
                    )
                    completed = self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            conversation_id=conversation_id,
                            turn_id=turn_id,
                            event_type="chat_turn_completed",
                            transition_key=f"conversation:{turn_id}:chat_turn_completed",
                            created_at=now,
                            payload={
                                "turn_id": turn_id,
                                "completion_kind": "typed_wait_information",
                            },
                        ),
                    )
                    connection.commit()
                    return ChatTurnAcceptedV2(
                        workflow_id=workflow_id,
                        conversation_id=conversation_id,
                        message_id=message_id,
                        turn_id=turn_id,
                        events_cursor=completed.seq,
                        replayed=False,
                    )
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error

    def create_action_turn(
        self,
        workflow_id: str,
        *,
        proposal_id: str,
        action: ProposalActionRequestV2,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        self.get_proposal(proposal_id)
        return self._create_turn(
            workflow_id,
            turn_kind="proposal_action",
            request={
                "proposal_id": proposal_id,
                "action": action.model_dump(mode="json", exclude_none=True),
            },
            idempotency_key=idempotency_key,
            user_message=None,
        )

    def create_command_action_turn(
        self,
        workflow_id: str,
        *,
        plan_id: str,
        action: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        return self._create_turn(
            workflow_id,
            turn_kind="command_action",
            request={
                "plan_id": plan_id,
                "action": action,
                "expected_revision": expected_revision,
            },
            idempotency_key=idempotency_key,
            user_message=None,
        )

    def create_guided_action_turn(
        self,
        workflow_id: str,
        *,
        action_id: str,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        action = self.reserve_guided_action(
            action_id,
            workflow_id=workflow_id,
            idempotency_key=idempotency_key,
        )
        if action.state == "applied":
            raise _error(
                "guided_action_already_applied",
                "Guided action was already applied.",
            )
        accepted = self._create_turn(
            workflow_id,
            turn_kind="guided_action",
            request={"action_id": action_id},
            idempotency_key=idempotency_key,
            user_message=None,
        )
        self.attach_guided_action_turn(action_id, accepted.turn_id)
        return accepted

    def create_continuation_turn(
        self,
        workflow_id: str,
        *,
        source_action_id: str,
        workflow_revision: int,
        video_skill_run_id: str | None,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        accepted = self._create_turn(
            workflow_id,
            turn_kind="guidance_advance",
            request={
                "schema_version": "1",
                "video_skill_run_id": video_skill_run_id,
                "source_action_id": source_action_id,
                "workflow_revision": workflow_revision,
            },
            idempotency_key=idempotency_key,
            user_message=None,
        )
        return accepted

    def create_guidance_advance_turn(
        self,
        workflow_id: str,
        *,
        request: dict[str, object],
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        """Persist an internal typed control Turn without user-message semantics."""

        return self._create_turn(
            workflow_id,
            turn_kind="guidance_advance",
            request=request,
            idempotency_key=idempotency_key,
            user_message=None,
        )

    def create_guidance_advance_delivery(
        self,
        plan: GuidanceAdvanceAuthorityPlanV1,
    ) -> ChatTurnAcceptedV2:
        """Commit one Guidance command only while its complete authority is current."""

        workflow_id = plan.workflow_id
        request = plan.request.model_dump(mode="json")
        persisted_request = {
            **request,
            "target": plan.target.model_dump(mode="json"),
            "executable_turn_id": plan.executable_turn_id,
            "guidance_request_digest": plan.request_digest,
        }
        request_json = _dump(persisted_request)
        now = _now()
        outbox = AgentCanvasContinuationOutboxRepository(self._database, self._events)
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    existing = (
                        connection.execute(
                            select(AgentCanvasChatTurnRow).where(
                                AgentCanvasChatTurnRow.idempotency_key == plan.idempotency_key
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is not None:
                        receipt = _guidance_replay_receipt(
                            connection,
                            existing=existing,
                            plan=plan,
                        )
                        connection.commit()
                        return _guidance_accepted(connection, receipt)

                    _validate_guidance_advance_authority(
                        connection,
                        plan=plan,
                        requirements=self._requirements,
                        continuations=outbox,
                    )
                    conversation_id = plan.conversation_id or _ensure_conversation(
                        connection,
                        workflow_id,
                        now,
                    )
                    connection.execute(
                        insert(AgentCanvasChatTurnRow).values(
                            turn_id=plan.command_turn_id,
                            conversation_id=conversation_id,
                            workflow_id=workflow_id,
                            turn_kind="guidance_advance",
                            status="completed",
                            request_json=request_json,
                            creation_mode_json=None,
                            guidance_session_revision=(plan.request.precondition.session_revision),
                            idempotency_key=plan.idempotency_key,
                            retry_of_turn_id=None,
                            retry_attempt_no=1,
                            retryable=False,
                            operation_stage="completed",
                            operation_failure_json=None,
                            retry_snapshot_json=_dump(
                                _turn_retry_snapshot(connection, workflow_id, request)
                            ),
                            error_code=None,
                            error_message=None,
                            created_at=now,
                            updated_at=now,
                        )
                    )

                    continuation = ContinuationCommitV2(
                        continuation_id=plan.continuation_id,
                        continuation_turn_id=plan.executable_turn_id,
                        source_turn_id=plan.command_turn_id,
                        source_action_id=plan.target.source_id,
                        idempotency_key=plan.continuation_idempotency_key,
                    )
                    self.insert_continuation_in_transaction(
                        connection,
                        workflow_id=workflow_id,
                        conversation_id=conversation_id,
                        continuation=continuation,
                        now=now,
                    )

                    accepted_event = self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            conversation_id=conversation_id,
                            turn_id=plan.executable_turn_id,
                            action_id=plan.target.source_id,
                            event_type="guidance_advance_accepted",
                            transition_key=f"guidance-advance:{plan.command_turn_id}",
                            created_at=now,
                            payload={
                                "command_turn_id": plan.command_turn_id,
                                "executable_turn_id": plan.executable_turn_id,
                                "source_kind": plan.target.source_kind,
                                "source_id": plan.target.source_id,
                                "guidance_session_revision": (
                                    plan.request.precondition.session_revision
                                ),
                                "request_digest": plan.request_digest,
                            },
                        ),
                    )
                    receipt = GuidanceAdvanceCommitReceiptV1(
                        workflow_id=workflow_id,
                        command_turn_id=plan.command_turn_id,
                        executable_turn_id=plan.executable_turn_id,
                        continuation_id=plan.continuation_id,
                        event_cursor=accepted_event.seq,
                        request_digest=plan.request_digest,
                        retry_of_turn_id=None,
                        retry_attempt_no=1,
                        replayed=False,
                    )
                    connection.commit()
                    return _guidance_accepted(connection, receipt)
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error

    def replay_guidance_advance(
        self,
        *,
        workflow_id: str,
        idempotency_key: str,
        request_digest: str,
    ) -> ChatTurnAcceptedV2 | None:
        """Return an exact committed Guidance command before mutable authority reads."""

        try:
            with self._database.engine.connect() as connection:
                existing = (
                    connection.execute(
                        select(AgentCanvasChatTurnRow).where(
                            AgentCanvasChatTurnRow.idempotency_key == idempotency_key
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is None:
                    return None
                receipt = _guidance_replay_receipt_for_identity(
                    connection,
                    existing=existing,
                    workflow_id=workflow_id,
                    request_digest=request_digest,
                )
                return _guidance_accepted(connection, receipt)
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error

    def _create_turn(
        self,
        workflow_id: str,
        *,
        turn_kind: str,
        request: dict[str, object],
        idempotency_key: str,
        user_message: str | None,
        retry_of_turn_id: str | None = None,
        retry_attempt_no: int = 1,
        retry_snapshot: dict[str, object] | None = None,
    ) -> ChatTurnAcceptedV2:
        now = _now()
        request_json = _dump(request)
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    existing = (
                        connection.execute(
                            select(AgentCanvasChatTurnRow).where(
                                AgentCanvasChatTurnRow.idempotency_key == idempotency_key
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is not None:
                        if (
                            str(existing["workflow_id"]) != workflow_id
                            or str(existing["request_json"]) != request_json
                        ):
                            raise _error("idempotency_conflict", "Idempotency key was reused.")
                        message_id = self._message_id_for_turn(connection, str(existing["turn_id"]))
                        cursor = self._queued_event_seq(
                            connection,
                            workflow_id,
                            str(existing["turn_id"]),
                        )
                        connection.commit()
                        return ChatTurnAcceptedV2(
                            workflow_id=workflow_id,
                            conversation_id=str(existing["conversation_id"]),
                            message_id=message_id,
                            turn_id=str(existing["turn_id"]),
                            events_cursor=cursor,
                            retry_of_turn_id=(
                                str(existing["retry_of_turn_id"])
                                if existing["retry_of_turn_id"]
                                else None
                            ),
                            retry_attempt_no=int(existing["retry_attempt_no"]),
                            replayed=True,
                        )
                    if retry_of_turn_id is not None:
                        active_retry = connection.execute(
                            select(AgentCanvasChatTurnRow.turn_id).where(
                                AgentCanvasChatTurnRow.retry_of_turn_id == retry_of_turn_id,
                                AgentCanvasChatTurnRow.status.in_(("queued", "running")),
                            )
                        ).scalar_one_or_none()
                        if active_retry is not None:
                            raise _error(
                                "chat_turn_retry_in_progress",
                                "A retry for this chat turn is already in progress.",
                            )
                    conversation_id = _ensure_conversation(connection, workflow_id, now)
                    turn_id = f"turn_{uuid4().hex}"
                    message_id = None
                    if user_message is not None:
                        message_id = f"msg_{uuid4().hex}"
                        connection.execute(
                            insert(AgentCanvasChatEntryRow).values(
                                entry_id=message_id,
                                conversation_id=conversation_id,
                                workflow_id=workflow_id,
                                sequence_no=_next_chat_sequence(connection, conversation_id),
                                entry_type="message",
                                speaker="user",
                                content=user_message,
                                metadata_json=_dump({"turn_id": turn_id}),
                                created_at=now,
                            )
                        )
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=workflow_id,
                                event_type="chat_message_created",
                                created_at=now,
                                payload={
                                    "message_id": message_id,
                                    "turn_id": turn_id,
                                    "speaker": "user",
                                },
                            ),
                        )
                    connection.execute(
                        insert(AgentCanvasChatTurnRow).values(
                            turn_id=turn_id,
                            conversation_id=conversation_id,
                            workflow_id=workflow_id,
                            turn_kind=turn_kind,
                            status="queued",
                            request_json=request_json,
                            idempotency_key=idempotency_key,
                            retry_of_turn_id=retry_of_turn_id,
                            retry_attempt_no=retry_attempt_no,
                            retryable=False,
                            operation_stage="queued",
                            operation_failure_json=None,
                            retry_snapshot_json=_dump(
                                retry_snapshot
                                if retry_snapshot is not None
                                else _turn_retry_snapshot(connection, workflow_id, request)
                            ),
                            error_code=None,
                            error_message=None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    queued_payload: dict[str, object] = {
                        "turn_id": turn_id,
                        "turn_kind": turn_kind,
                    }
                    source_action_id = request.get("source_action_id")
                    if isinstance(source_action_id, str) and source_action_id:
                        queued_payload["source_action_id"] = source_action_id
                    queued = self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            conversation_id=conversation_id,
                            turn_id=turn_id,
                            action_id=(
                                source_action_id if isinstance(source_action_id, str) else None
                            ),
                            event_type="agent_turn_queued",
                            created_at=now,
                            payload=queued_payload,
                        ),
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            conversation_id=conversation_id,
                            turn_id=turn_id,
                            event_type="agent_operation_queued",
                            transition_key=f"conversation:{turn_id}:agent_operation_queued",
                            created_at=now,
                            payload={
                                **queued_payload,
                                "operation_stage": "queued",
                                "retry_of_turn_id": retry_of_turn_id,
                                "retry_attempt_no": retry_attempt_no,
                            },
                        ),
                    )
                    if retry_of_turn_id is not None:
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=workflow_id,
                                conversation_id=conversation_id,
                                turn_id=turn_id,
                                event_type="chat_turn_retry_accepted",
                                transition_key=f"conversation:{turn_id}:retry_accepted",
                                created_at=now,
                                payload={
                                    "turn_id": turn_id,
                                    "retry_of_turn_id": retry_of_turn_id,
                                    "retry_attempt_no": retry_attempt_no,
                                },
                            ),
                        )
                    connection.commit()
                    return ChatTurnAcceptedV2(
                        workflow_id=workflow_id,
                        conversation_id=conversation_id,
                        message_id=message_id,
                        turn_id=turn_id,
                        events_cursor=queued.seq,
                        retry_of_turn_id=retry_of_turn_id,
                        retry_attempt_no=retry_attempt_no,
                        replayed=False,
                    )
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error

    def mark_turn_running(self, turn_id: str) -> ChatTurnV2:
        return self._set_turn_status(turn_id, "running", "chat_turn_started")

    def mark_turn_provider_waiting(
        self,
        turn_id: str,
        *,
        operation: str,
        deadline_at: datetime,
        model_ref: str,
        frozen_agent_request_digest: str | None = None,
        response_locale: BCP47Tag = "und",
    ) -> ChatTurnV2:
        now = _now()
        try:
            with self._database.engine.begin() as connection:
                turn = _require_turn(connection, turn_id)
                if str(turn["status"]) not in {"queued", "running"}:
                    return _turn(turn)
                connection.execute(
                    update(AgentCanvasChatTurnRow)
                    .where(AgentCanvasChatTurnRow.turn_id == turn_id)
                    .values(
                        status="running",
                        operation_stage="provider_waiting",
                        retry_snapshot_json=_dump(
                            {
                                **json.loads(str(turn["retry_snapshot_json"])),
                                "source_message_id": self._message_id_for_turn(connection, turn_id),
                                "frozen_agent_request_digest": frozen_agent_request_digest,
                                "response_locale": response_locale,
                            }
                        ),
                        updated_at=now,
                    )
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=str(turn["workflow_id"]),
                        conversation_id=str(turn["conversation_id"]),
                        turn_id=turn_id,
                        event_type="agent_turn_waiting",
                        transition_key=f"conversation:{turn_id}:agent_turn_waiting",
                        created_at=now,
                        payload={
                            "turn_id": turn_id,
                            "operation": operation,
                            "deadline_at": deadline_at.isoformat(),
                            "model_ref": model_ref,
                        },
                    ),
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_turn(turn_id)

    def update_guidance_response_locale(
        self,
        workflow_id: str,
        *,
        expected_revision: int,
        response_locale: str,
    ) -> GuidedSessionStateV2:
        locale = canonicalize_bcp47_tag(response_locale)
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    row = _require_guidance_session_row_by_workflow(connection, workflow_id)
                    _require_guidance_revision(row, expected_revision)
                    if str(row["response_locale"]) == locale:
                        result = _guidance_session(connection, row)
                        connection.commit()
                        return result
                    next_revision = expected_revision + 1
                    connection.execute(
                        update(AgentCanvasGuidanceSessionRow)
                        .where(AgentCanvasGuidanceSessionRow.workflow_id == workflow_id)
                        .values(
                            response_locale=locale,
                            revision=next_revision,
                            updated_at=now,
                        )
                    )
                    updated = _require_guidance_session_row_by_workflow(connection, workflow_id)
                    result = _guidance_session(connection, updated)
                    connection.commit()
                    return result
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "conversation_persistence_unavailable",
                "Conversation storage failed.",
            ) from error

    def complete_turn(
        self,
        turn_id: str,
        *,
        assistant_message: str | None = None,
        guided_actions: tuple[GuidanceSessionActionV2, ...] = (),
    ) -> ChatTurnV2:
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    turn = _require_turn(connection, turn_id)
                    if str(turn["status"]) == "completed":
                        connection.commit()
                        return _turn(turn)
                    if guided_actions:
                        action_ids = tuple(action.action_id for action in guided_actions)
                        if len(set(action_ids)) != len(action_ids):
                            raise _error(
                                "guided_action_invalid",
                                "Guided action identifiers must be unique.",
                            )
                        for action in guided_actions:
                            expected_revision = getattr(
                                action,
                                "expected_session_revision",
                                getattr(action, "expected_semantic_revision", None),
                            )
                            if (
                                action.workflow_id != turn["workflow_id"]
                                or action.creating_turn_id != turn_id
                                or expected_revision is None
                            ):
                                raise _error(
                                    "guided_action_invalid",
                                    "Guided action identity does not match the completed turn.",
                                )
                            existing = (
                                connection.execute(
                                    select(AgentCanvasGuidedActionRow).where(
                                        AgentCanvasGuidedActionRow.workflow_id
                                        == action.workflow_id,
                                        AgentCanvasGuidedActionRow.logical_key
                                        == action.logical_key,
                                    )
                                )
                                .mappings()
                                .one_or_none()
                            )
                            if existing is None:
                                connection.execute(
                                    insert(AgentCanvasGuidedActionRow).values(
                                        action_id=action.action_id,
                                        logical_key=action.logical_key,
                                        workflow_id=action.workflow_id,
                                        creating_turn_id=turn_id,
                                        action_type=action.action,
                                        state=action.state,
                                        expected_session_revision=expected_revision,
                                        action_json=action.model_dump_json(),
                                        apply_idempotency_key=None,
                                        apply_turn_id=None,
                                        receipt_id=None,
                                        error_code=None,
                                        created_at=now,
                                        updated_at=now,
                                    )
                                )
                                self._events.append_in_transaction(
                                    connection,
                                    V2EventInsert(
                                        workflow_id=action.workflow_id,
                                        event_type="guided_action_created",
                                        created_at=now,
                                        payload={
                                            "action_id": action.action_id,
                                            "turn_id": turn_id,
                                            "action": action.action,
                                            "state": action.state,
                                        },
                                    ),
                                )
                            elif str(existing["state"]) == "pending":
                                reconciled = action.model_copy(
                                    update={"action_id": str(existing["action_id"])}
                                )
                                connection.execute(
                                    update(AgentCanvasGuidedActionRow)
                                    .where(
                                        AgentCanvasGuidedActionRow.action_id
                                        == existing["action_id"]
                                    )
                                    .values(
                                        creating_turn_id=turn_id,
                                        expected_session_revision=expected_revision,
                                        action_json=reconciled.model_dump_json(),
                                        updated_at=now,
                                    )
                                )
                        current_keys = {action.logical_key for action in guided_actions}
                        stale_actions = (
                            connection.execute(
                                select(AgentCanvasGuidedActionRow).where(
                                    AgentCanvasGuidedActionRow.workflow_id == turn["workflow_id"],
                                    AgentCanvasGuidedActionRow.state == "pending",
                                    AgentCanvasGuidedActionRow.logical_key.not_in(current_keys),
                                )
                            )
                            .mappings()
                            .all()
                        )
                        for stale_action in stale_actions:
                            connection.execute(
                                update(AgentCanvasGuidedActionRow)
                                .where(
                                    AgentCanvasGuidedActionRow.action_id
                                    == stale_action["action_id"],
                                    AgentCanvasGuidedActionRow.state == "pending",
                                )
                                .values(state="superseded", updated_at=now)
                            )
                            self._events.append_in_transaction(
                                connection,
                                V2EventInsert(
                                    workflow_id=str(turn["workflow_id"]),
                                    turn_id=turn_id,
                                    action_id=str(stale_action["action_id"]),
                                    event_type="guided_action_superseded",
                                    created_at=now,
                                    payload={
                                        "action_id": str(stale_action["action_id"]),
                                        "logical_key": str(stale_action["logical_key"]),
                                    },
                                ),
                            )
                    _complete_turn_in_transaction(
                        connection,
                        events=self._events,
                        turn=turn,
                        assistant_message=assistant_message,
                        now=now,
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_turn(turn_id)

    def get_guided_action(self, action_id: str) -> GuidanceSessionActionV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasGuidedActionRow).where(
                            AgentCanvasGuidedActionRow.action_id == action_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable",
                "Conversation storage failed.",
            ) from error
        if row is None:
            raise _error("guided_action_not_found", "Guided action was not found.")
        return _guidance_session_action(row)

    def reserve_guided_action(
        self,
        action_id: str,
        *,
        workflow_id: str,
        idempotency_key: str,
    ) -> GuidanceSessionActionV2:
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    row = (
                        connection.execute(
                            select(AgentCanvasGuidedActionRow).where(
                                AgentCanvasGuidedActionRow.action_id == action_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None or str(row["workflow_id"]) != workflow_id:
                        raise _error(
                            "guided_action_not_found",
                            "Guided action was not found.",
                        )
                    if str(row["state"]) != "pending":
                        if str(row["apply_idempotency_key"] or "") == idempotency_key:
                            connection.commit()
                            return _guidance_session_action(row)
                        raise _error(
                            "guided_action_already_applied",
                            "Guided action is no longer pending.",
                        )
                    workflow_exists = connection.execute(
                        select(AgentCanvasWorkflowRow.workflow_id).where(
                            AgentCanvasWorkflowRow.workflow_id == workflow_id
                        )
                    ).scalar_one_or_none()
                    if workflow_exists is None:
                        raise _error("workflow_not_found", "Workflow was not found.")
                    connection.execute(
                        update(AgentCanvasGuidedActionRow)
                        .where(AgentCanvasGuidedActionRow.action_id == action_id)
                        .values(
                            state="applying",
                            apply_idempotency_key=idempotency_key,
                            action_json=_guidance_session_action(row)
                            .model_copy(update={"state": "applying"})
                            .model_dump_json(),
                            updated_at=now,
                        )
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_conversation_unavailable",
                "Conversation storage failed.",
            ) from error
        return self.get_guided_action(action_id)

    def attach_guided_action_turn(self, action_id: str, turn_id: str) -> None:
        try:
            with self._database.engine.begin() as connection:
                updated = connection.execute(
                    update(AgentCanvasGuidedActionRow)
                    .where(
                        AgentCanvasGuidedActionRow.action_id == action_id,
                        AgentCanvasGuidedActionRow.state == "applying",
                    )
                    .values(apply_turn_id=turn_id, updated_at=_now())
                )
                if updated.rowcount != 1:
                    raise _error(
                        "guided_action_invalid",
                        "Guided action is not awaiting application.",
                    )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable",
                "Conversation storage failed.",
            ) from error

    def complete_guided_action(
        self,
        action_id: str,
        *,
        receipt_id: str,
        state: Literal["applied", "superseded"] = "applied",
    ) -> GuidanceSessionActionV2:
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    row = (
                        connection.execute(
                            select(AgentCanvasGuidedActionRow).where(
                                AgentCanvasGuidedActionRow.action_id == action_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None:
                        raise _error(
                            "guided_action_not_found",
                            "Guided action was not found.",
                        )
                    if str(row["state"]) in {"applied", "superseded"}:
                        connection.commit()
                        return _guidance_session_action(row)
                    if str(row["state"]) != "applying":
                        raise _error(
                            "guided_action_invalid",
                            "Guided action is not being applied.",
                        )
                    applied = _guidance_session_action(row).model_copy(update={"state": state})
                    connection.execute(
                        update(AgentCanvasGuidedActionRow)
                        .where(AgentCanvasGuidedActionRow.action_id == action_id)
                        .values(
                            state=state,
                            receipt_id=receipt_id,
                            action_json=applied.model_dump_json(),
                            updated_at=now,
                        )
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=applied.workflow_id,
                            event_type="guided_action_applied",
                            created_at=now,
                            payload={
                                "action_id": action_id,
                                "turn_id": str(row["apply_turn_id"] or ""),
                                "action": applied.action,
                                "receipt_id": receipt_id,
                            },
                        ),
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable",
                "Conversation storage failed.",
            ) from error
        return self.get_guided_action(action_id)

    def apply_guidance_session_action(
        self,
        action_id: str,
        *,
        source_turn_id: str,
        continuation: ContinuationCommitV2 | None,
    ) -> AgentActionReceiptV2:
        now = _now()
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                turn = _require_turn(connection, source_turn_id)
                action_row = (
                    connection.execute(
                        select(AgentCanvasGuidedActionRow).where(
                            AgentCanvasGuidedActionRow.action_id == action_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if action_row is None:
                    raise _error("guided_action_not_found", "Guided action was not found.")
                action = _guidance_session_action(action_row)
                if action.state == "applied":
                    receipt_row = connection.execute(
                        select(AgentCanvasActionReceiptRow).where(
                            AgentCanvasActionReceiptRow.receipt_id == action_row["receipt_id"]
                        )
                    ).scalar_one()
                    connection.commit()
                    return AgentActionReceiptV2.model_validate_json(str(receipt_row.receipt_json))
                if action.state != "applying" or str(action_row["apply_turn_id"]) != source_turn_id:
                    raise _error(
                        "guided_action_invalid",
                        "Guided action is not awaiting this application.",
                    )
                session = (
                    connection.execute(
                        select(AgentCanvasGuidanceSessionRow).where(
                            AgentCanvasGuidanceSessionRow.workflow_id == action.workflow_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if session is None:
                    raise _error(
                        "guidance_session_not_found",
                        "Guidance session was not found.",
                    )
                _require_guidance_revision(session, action.expected_session_revision)
                authority = None
                if action.action == "set_creative_authority":
                    if action.authority is None or session["creative_authority_json"] is not None:
                        raise _error(
                            "guided_action_stale",
                            "Creative authority is already resolved.",
                        )
                    expected_status = "active"
                    next_status = "active"
                    authority = CreativeAuthorityStateV2(
                        authority=action.authority,
                        source=(
                            "explicit_user" if action.authority == "user" else "explicit_delegation"
                        ),
                        decided_at_turn_id=source_turn_id,
                        revision=1,
                    )
                else:
                    expected_status = "active" if action.action == "stop_guidance" else "paused"
                    next_status = "paused" if action.action == "stop_guidance" else "active"
                if str(session["status"]) != expected_status:
                    raise _error(
                        "guided_action_stale",
                        "Guidance session state no longer matches this action.",
                    )
                next_revision = action.expected_session_revision + 1
                values = {
                    "status": next_status,
                    "revision": next_revision,
                    "updated_at": now,
                }
                if authority is not None:
                    values["creative_authority_json"] = authority.model_dump_json()
                updated = connection.execute(
                    update(AgentCanvasGuidanceSessionRow)
                    .where(
                        AgentCanvasGuidanceSessionRow.session_id == session["session_id"],
                        AgentCanvasGuidanceSessionRow.revision == action.expected_session_revision,
                    )
                    .values(**values)
                )
                if updated.rowcount != 1:
                    raise _error(
                        "guidance_revision_conflict",
                        "Guidance session revision is stale.",
                    )
                applied = action.model_copy(update={"state": "applied"})
                receipt = AgentActionReceiptV2(
                    receipt_id=f"receipt_{source_turn_id}",
                    workflow_id=action.workflow_id,
                    action_id=action.action_id,
                    actor_kind="user",
                    idempotency_key=source_turn_id,
                    status="applied",
                    summary=(
                        "Guidance was paused."
                        if action.action == "stop_guidance"
                        else (
                            "Guidance was resumed."
                            if action.action == "resume_guidance"
                            else (
                                "You will provide the creative direction."
                                if action.authority == "user"
                                else "The Director will lead the creative direction."
                            )
                        )
                    ),
                    workflow_revision=int(
                        connection.execute(
                            select(AgentCanvasWorkflowRow.revision).where(
                                AgentCanvasWorkflowRow.workflow_id == action.workflow_id
                            )
                        ).scalar_one()
                    ),
                    continuation_turn_id=(
                        continuation.continuation_turn_id if continuation is not None else None
                    ),
                )
                connection.execute(
                    insert(AgentCanvasActionReceiptRow).values(
                        receipt_id=receipt.receipt_id,
                        workflow_id=receipt.workflow_id,
                        plan_id=None,
                        action_id=receipt.action_id,
                        proposal_id=None,
                        proposal_option_id=None,
                        proposal_action=None,
                        receipt_json=receipt.model_dump_json(),
                        created_at=now,
                    )
                )
                connection.execute(
                    update(AgentCanvasGuidedActionRow)
                    .where(AgentCanvasGuidedActionRow.action_id == action_id)
                    .values(
                        state="applied",
                        receipt_id=receipt.receipt_id,
                        action_json=applied.model_dump_json(),
                        updated_at=now,
                    )
                )
                connection.execute(
                    update(AgentCanvasGuidedActionRow)
                    .where(
                        AgentCanvasGuidedActionRow.workflow_id == action.workflow_id,
                        AgentCanvasGuidedActionRow.action_id != action_id,
                        AgentCanvasGuidedActionRow.state == "pending",
                    )
                    .values(state="superseded", updated_at=now)
                )
                _append_timeline_entry(
                    connection,
                    conversation_id=str(turn["conversation_id"]),
                    workflow_id=action.workflow_id,
                    entry_type="action_receipt",
                    content=receipt.summary,
                    metadata={"action_receipt": receipt.model_dump(mode="json")},
                    created_at=now,
                )
                if continuation is not None:
                    self.insert_continuation_in_transaction(
                        connection,
                        workflow_id=action.workflow_id,
                        conversation_id=str(turn["conversation_id"]),
                        continuation=continuation,
                        now=now,
                    )
                for event_type in ("guided_action_applied", "guidance_state_updated"):
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=action.workflow_id,
                            conversation_id=str(turn["conversation_id"]),
                            turn_id=source_turn_id,
                            action_id=action_id,
                            event_type=event_type,
                            created_at=now,
                            payload={
                                "action_id": action_id,
                                "action": action.action,
                                "session_id": str(session["session_id"]),
                                "session_revision": next_revision,
                                "status": next_status,
                                "authority": (
                                    authority.authority if authority is not None else None
                                ),
                            },
                        ),
                    )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return receipt

    def create_retry_turn(
        self,
        source: ChatTurnV2,
        *,
        idempotency_key: str,
        retry_snapshot: dict[str, object],
    ) -> ChatTurnAcceptedV2:
        now = _now()
        request_json = _dump(dict(source.request))
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    existing = (
                        connection.execute(
                            select(AgentCanvasChatTurnRow).where(
                                AgentCanvasChatTurnRow.idempotency_key == idempotency_key
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is not None:
                        if (
                            str(existing["workflow_id"]) != source.workflow_id
                            or str(existing["request_json"]) != request_json
                            or str(existing["retry_of_turn_id"] or "") != source.turn_id
                        ):
                            raise _error("idempotency_conflict", "Idempotency key was reused.")
                        connection.commit()
                        return ChatTurnAcceptedV2(
                            workflow_id=source.workflow_id,
                            conversation_id=str(existing["conversation_id"]),
                            message_id=None,
                            turn_id=str(existing["turn_id"]),
                            events_cursor=self._queued_event_seq(
                                connection,
                                source.workflow_id,
                                str(existing["turn_id"]),
                            ),
                            retry_of_turn_id=source.turn_id,
                            retry_attempt_no=int(existing["retry_attempt_no"]),
                            replayed=True,
                        )
                    active_retry = connection.execute(
                        select(AgentCanvasChatTurnRow.turn_id).where(
                            AgentCanvasChatTurnRow.retry_of_turn_id == source.turn_id,
                            AgentCanvasChatTurnRow.status.in_(("queued", "running")),
                        )
                    ).scalar_one_or_none()
                    if active_retry is not None:
                        raise _error(
                            "chat_turn_retry_in_progress",
                            "A retry for this chat turn is already in progress.",
                        )
                    turn_id = f"turn_{uuid4().hex}"
                    queued = _insert_retry_turn_in_transaction(
                        connection,
                        events=self._events,
                        source=source,
                        turn_id=turn_id,
                        conversation_id=source.conversation_id,
                        idempotency_key=idempotency_key,
                        guidance_session_revision=source.guidance_session_revision,
                        retry_snapshot=retry_snapshot,
                        now=now,
                    )
                    connection.commit()
                    return ChatTurnAcceptedV2(
                        workflow_id=source.workflow_id,
                        conversation_id=source.conversation_id,
                        message_id=None,
                        turn_id=turn_id,
                        events_cursor=queued.seq,
                        retry_of_turn_id=source.turn_id,
                        retry_attempt_no=source.retry_attempt_no + 1,
                        replayed=False,
                    )
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error

    def create_typed_retry_turn(
        self,
        source: ChatTurnV2,
        *,
        source_envelope: CapabilityCommandEnvelopeV2 | NextActionEnvelopeV1,
        operation: Literal["next_action", "capability_command"],
        idempotency_key: str,
        retry_snapshot: ContinuationTurnRetrySnapshotV1,
    ) -> ChatTurnAcceptedV2:
        """Atomically create a typed retry attempt and durable delivery."""

        now = _now()
        identity = hashlib.sha256(
            f"{source.workflow_id}:{source.turn_id}:{idempotency_key}".encode("utf-8")
        ).hexdigest()
        turn_id = f"turn_{identity[:32]}"
        envelope_id = f"envelope_{identity[32:]}"
        continuation_id = f"continuation_{identity[:24]}"
        timestamp = datetime.fromisoformat(now)
        if isinstance(source_envelope, CapabilityCommandEnvelopeV2):
            if operation != "capability_command":
                raise _error(
                    "guidance_action_lineage_invalid",
                    "Capability retry operation does not match its envelope.",
                )
            envelope = source_envelope.model_copy(
                update={
                    "envelope_id": envelope_id,
                    "source_turn_id": source.turn_id,
                    "capability_turn_id": turn_id,
                    "agent_request_identity": f"capability-retry:{identity}",
                    "created_at": timestamp,
                    **(
                        {"result_contract_name": "GuidedScriptCheckpointDraftV1"}
                        if (
                            source_envelope.publication_kind == "internal_document"
                            and source_envelope.capability_id == "script_authoring"
                            and source_envelope.result_contract_name
                            == "ScriptMaterializationResultV1"
                        )
                        else {}
                    ),
                }
            )
        else:
            if operation != "next_action":
                raise _error(
                    "guidance_action_lineage_invalid",
                    "Next Action retry operation does not match its envelope.",
                )
            envelope = source_envelope.model_copy(
                update={
                    "envelope_id": envelope_id,
                    "source_turn_id": source.turn_id,
                    "next_action_turn_id": turn_id,
                    "created_at": timestamp,
                }
            )
        next_snapshot = retry_snapshot.model_copy(
            update={
                "envelope_id": envelope_id,
                "envelope_digest": hashlib.sha256(
                    envelope.model_dump_json().encode("utf-8")
                ).hexdigest(),
            }
        )
        request = {"schema_version": "1", "envelope_id": envelope_id}
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    existing = (
                        connection.execute(
                            select(AgentCanvasChatTurnRow).where(
                                AgentCanvasChatTurnRow.idempotency_key == idempotency_key
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is not None:
                        if (
                            str(existing["workflow_id"]) != source.workflow_id
                            or str(existing["retry_of_turn_id"] or "") != source.turn_id
                            or json.loads(str(existing["request_json"])) != request
                        ):
                            raise _error("idempotency_conflict", "Idempotency key was reused.")
                        delivery = AgentCanvasContinuationOutboxRepository(
                            self._database, self._events
                        ).get_for_turn(turn_id)
                        if delivery is None:
                            raise _error(
                                "guidance_action_lineage_invalid",
                                "Typed retry replay is missing its Continuation.",
                            )
                        connection.commit()
                        return ChatTurnAcceptedV2(
                            workflow_id=source.workflow_id,
                            conversation_id=source.conversation_id,
                            message_id=None,
                            turn_id=turn_id,
                            events_cursor=self._queued_event_seq(
                                connection, source.workflow_id, turn_id
                            ),
                            retry_of_turn_id=source.turn_id,
                            retry_attempt_no=int(existing["retry_attempt_no"]),
                            replayed=True,
                        )
                    active_retry = connection.execute(
                        select(AgentCanvasChatTurnRow.turn_id).where(
                            AgentCanvasChatTurnRow.retry_of_turn_id == source.turn_id,
                            AgentCanvasChatTurnRow.status.in_(("queued", "running")),
                        )
                    ).scalar_one_or_none()
                    if active_retry is not None:
                        raise _error(
                            "chat_turn_retry_in_progress",
                            "A retry for this chat turn is already in progress.",
                        )
                    queued = _insert_retry_turn_in_transaction(
                        connection,
                        events=self._events,
                        source=source,
                        turn_id=turn_id,
                        conversation_id=source.conversation_id,
                        idempotency_key=idempotency_key,
                        guidance_session_revision=source.guidance_session_revision,
                        retry_snapshot=next_snapshot.model_dump(mode="json"),
                        now=now,
                        request=request,
                    )
                    AgentCanvasOperationEnvelopeRepository(self._database).create_in_transaction(
                        connection, envelope
                    )
                    AgentCanvasContinuationOutboxRepository(
                        self._database, self._events
                    ).enqueue_in_transaction(
                        connection,
                        continuation_id=continuation_id,
                        workflow_id=source.workflow_id,
                        conversation_id=source.conversation_id,
                        source_turn_id=source.turn_id,
                        continuation_turn_id=turn_id,
                        operation=operation,
                        payload={"schema_version": "1", "envelope_id": envelope_id},
                        max_attempts=5,
                        now=timestamp,
                    )
                    connection.commit()
                    return ChatTurnAcceptedV2(
                        workflow_id=source.workflow_id,
                        conversation_id=source.conversation_id,
                        message_id=None,
                        turn_id=turn_id,
                        events_cursor=queued.seq,
                        retry_of_turn_id=source.turn_id,
                        retry_attempt_no=source.retry_attempt_no + 1,
                        replayed=False,
                    )
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error

    def get_retry_snapshot(self, turn_id: str) -> dict[str, object]:
        try:
            with self._database.engine.connect() as connection:
                value = connection.execute(
                    select(AgentCanvasChatTurnRow.retry_snapshot_json).where(
                        AgentCanvasChatTurnRow.turn_id == turn_id
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        if value is None:
            raise _error("chat_turn_not_found", "Chat turn was not found.")
        loaded = json.loads(str(value))
        return loaded if isinstance(loaded, dict) else {}

    def list_retry_children(self, turn_id: str) -> tuple[ChatTurnV2, ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasChatTurnRow)
                        .where(AgentCanvasChatTurnRow.retry_of_turn_id == turn_id)
                        .order_by(
                            AgentCanvasChatTurnRow.retry_attempt_no.asc(),
                            AgentCanvasChatTurnRow.created_at.asc(),
                            AgentCanvasChatTurnRow.turn_id.asc(),
                        )
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return tuple(_turn(row) for row in rows)

    def fail_turn(
        self,
        turn_id: str,
        *,
        code: str,
        message: str,
        retryable: bool = False,
        operation_stage: str = "failed",
        operation_failure: AgentOperationFailureV2 | None = None,
        frozen_agent_request_digest: str | None = None,
        response_locale: BCP47Tag | None = None,
    ) -> ChatTurnV2:
        now = _now()
        try:
            with self._database.engine.begin() as connection:
                turn = _require_turn(connection, turn_id)
                retry_snapshot = json.loads(str(turn["retry_snapshot_json"]))
                is_typed_continuation_snapshot = retry_snapshot.get(
                    "schema_version"
                ) == "1" and retry_snapshot.get("operation") in {
                    "next_action",
                    "capability_command",
                }
                if not is_typed_continuation_snapshot:
                    retry_snapshot["source_message_id"] = self._message_id_for_turn(
                        connection, turn_id
                    )
                    if frozen_agent_request_digest is not None:
                        retry_snapshot["frozen_agent_request_digest"] = frozen_agent_request_digest
                    else:
                        retry_snapshot.setdefault("frozen_agent_request_digest", None)
                    if response_locale is not None:
                        retry_snapshot["response_locale"] = response_locale
                    else:
                        retry_snapshot.setdefault("response_locale", "und")
                connection.execute(
                    update(AgentCanvasChatTurnRow)
                    .where(AgentCanvasChatTurnRow.turn_id == turn_id)
                    .values(
                        status="failed",
                        retryable=retryable,
                        operation_stage=operation_stage,
                        operation_failure_json=(
                            operation_failure.model_dump_json()
                            if operation_failure is not None
                            else None
                        ),
                        retry_snapshot_json=_dump(retry_snapshot),
                        error_code=code,
                        error_message=message,
                        updated_at=now,
                    )
                )
                timeline_rows = (
                    connection.execute(
                        select(AgentCanvasChatEntryRow).where(
                            AgentCanvasChatEntryRow.conversation_id == turn["conversation_id"]
                        )
                    )
                    .mappings()
                    .all()
                )
                for timeline_row in timeline_rows:
                    metadata = json.loads(str(timeline_row["metadata_json"]))
                    if metadata.get("turn_id") != turn_id:
                        continue
                    connection.execute(
                        update(AgentCanvasChatEntryRow)
                        .where(AgentCanvasChatEntryRow.entry_id == timeline_row["entry_id"])
                        .values(
                            metadata_json=_dump(
                                {
                                    **metadata,
                                    "status": "failed",
                                    "error_code": code,
                                    "retryable": retryable,
                                    "operation_stage": operation_stage,
                                    "operation_failure": (
                                        operation_failure.model_dump(mode="json")
                                        if operation_failure is not None
                                        else None
                                    ),
                                }
                            )
                        )
                    )
                activity = (
                    connection.execute(
                        select(AgentCanvasExpertActivityRow).where(
                            AgentCanvasExpertActivityRow.turn_id == turn_id,
                            AgentCanvasExpertActivityRow.status == "working",
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if activity is not None:
                    connection.execute(
                        update(AgentCanvasExpertActivityRow)
                        .where(AgentCanvasExpertActivityRow.activity_id == activity["activity_id"])
                        .values(
                            status="failed",
                            error_code=code,
                            error_message=message,
                            updated_at=now,
                        )
                    )
                    activity_payload = {
                        "activity_id": str(activity["activity_id"]),
                        "turn_id": turn_id,
                        "capability_id": str(activity["capability_id"]),
                        "capability_display_name": str(activity["display_name"]),
                        "operation": str(activity["operation"]),
                        "status": "failed",
                        "error_code": code,
                    }
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=str(turn["workflow_id"]),
                            conversation_id=str(turn["conversation_id"]),
                            turn_id=turn_id,
                            event_type="expert_activity_failed",
                            transition_key=(f"conversation:{turn_id}:expert_activity_failed"),
                            created_at=now,
                            payload=activity_payload,
                        ),
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=str(turn["workflow_id"]),
                            conversation_id=str(turn["conversation_id"]),
                            turn_id=turn_id,
                            event_type="agent_command_failed",
                            transition_key=f"conversation:{turn_id}:agent_command_failed",
                            created_at=now,
                            payload={
                                "turn_id": turn_id,
                                "capability_id": str(activity["capability_id"]),
                                "error_code": code,
                            },
                        ),
                    )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=str(turn["workflow_id"]),
                        event_type="chat_turn_failed",
                        created_at=now,
                        payload={"turn_id": turn_id, "code": code},
                    ),
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=str(turn["workflow_id"]),
                        conversation_id=str(turn["conversation_id"]),
                        turn_id=turn_id,
                        event_type="agent_operation_failed",
                        transition_key=f"conversation:{turn_id}:agent_operation_failed",
                        created_at=now,
                        payload={
                            "turn_id": turn_id,
                            "code": code,
                            "retryable": retryable,
                            "operation_stage": operation_stage,
                        },
                    ),
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_turn(turn_id)

    def get_turn(self, turn_id: str) -> ChatTurnV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasChatTurnRow).where(
                            AgentCanvasChatTurnRow.turn_id == turn_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                continuation_row = (
                    connection.execute(
                        select(AgentCanvasContinuationOutboxRow).where(
                            AgentCanvasContinuationOutboxRow.continuation_turn_id == turn_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        if row is None:
            raise _error("chat_turn_not_found", "Chat turn was not found.")
        return _turn(
            row,
            continuation=(
                _continuation_delivery(continuation_row) if continuation_row is not None else None
            ),
        )

    def get_turn_by_idempotency_key(self, idempotency_key: str) -> ChatTurnV2 | None:
        try:
            with self._database.engine.connect() as connection:
                turn_id = connection.execute(
                    select(AgentCanvasChatTurnRow.turn_id).where(
                        AgentCanvasChatTurnRow.idempotency_key == idempotency_key
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_turn(str(turn_id)) if turn_id is not None else None

    def get_proposal(self, proposal_id: str) -> ConceptProposalV2:
        try:
            with self._database.engine.connect() as connection:
                proposal = (
                    connection.execute(
                        select(AgentCanvasConceptProposalRow).where(
                            AgentCanvasConceptProposalRow.proposal_id == proposal_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if proposal is None:
                    raise _error("proposal_not_found", "Concept proposal was not found.")
                options = (
                    connection.execute(
                        select(AgentCanvasConceptOptionRow)
                        .where(AgentCanvasConceptOptionRow.proposal_id == proposal_id)
                        .order_by(AgentCanvasConceptOptionRow.display_order.asc())
                    )
                    .mappings()
                    .all()
                )
                applications = (
                    connection.execute(
                        select(AgentCanvasActionReceiptRow)
                        .where(AgentCanvasActionReceiptRow.proposal_id == proposal_id)
                        .order_by(
                            AgentCanvasActionReceiptRow.created_at.desc(),
                            AgentCanvasActionReceiptRow.receipt_id.desc(),
                        )
                    )
                    .mappings()
                    .all()
                )
                current_session_revision = connection.execute(
                    select(AgentCanvasGuidanceSessionRow.revision).where(
                        AgentCanvasGuidanceSessionRow.session_id == proposal["guidance_session_id"]
                    )
                ).scalar_one()
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return _proposal(
            proposal,
            options,
            applications,
            current_session_revision=int(current_session_revision),
        )

    def get_private_proposal(self, proposal_id: str) -> ConceptProposalV2:
        """Read the complete private Proposal authority for materialization paths."""

        return self.get_proposal(proposal_id)

    def get_proposal_character_target(
        self,
        proposal_id: str,
    ) -> CharacterProposalTargetV1 | None:
        """Read the immutable Character scope stored with one Proposal."""

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
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        if row is None:
            raise _error("proposal_not_found", "Concept proposal was not found.")
        return _proposal_character_target(row)

    def list_open_proposals(self, workflow_id: str) -> tuple[ConceptProposalV2, ...]:
        try:
            with self._database.engine.connect() as connection:
                ids = list(
                    connection.execute(
                        select(AgentCanvasConceptProposalRow.proposal_id)
                        .where(
                            AgentCanvasConceptProposalRow.workflow_id == workflow_id,
                            AgentCanvasConceptProposalRow.availability == "open",
                        )
                        .order_by(AgentCanvasConceptProposalRow.created_at.asc())
                    ).scalars()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return tuple(self.get_proposal(str(proposal_id)) for proposal_id in ids)

    def list_active_materialization_capability_ids(
        self,
        workflow_id: str,
    ) -> tuple[str, ...]:
        try:
            with self._database.engine.connect() as connection:
                values = tuple(
                    connection.execute(
                        select(AgentCanvasConceptProposalRow.capability_id)
                        .where(
                            AgentCanvasConceptProposalRow.workflow_id == workflow_id,
                            AgentCanvasConceptProposalRow.materialization_status.in_(
                                ("queued", "working")
                            ),
                        )
                        .order_by(
                            AgentCanvasConceptProposalRow.created_at.asc(),
                            AgentCanvasConceptProposalRow.proposal_id.asc(),
                        )
                    ).scalars()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return tuple(dict.fromkeys(str(value) for value in values))

    def insert_continuation_in_transaction(
        self,
        connection: Connection,
        *,
        workflow_id: str,
        conversation_id: str,
        continuation: ContinuationCommitV2,
        now: str,
    ) -> None:
        _require_turn(connection, continuation.source_turn_id)
        session = (
            connection.execute(
                select(AgentCanvasGuidanceSessionRow).where(
                    AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
                )
            )
            .mappings()
            .one()
        )
        goal = CreativeGoalV2.model_validate_json(str(session["creative_goal_json"]))
        timestamp = datetime.fromisoformat(now)
        envelope_digest = hashlib.sha256(continuation.idempotency_key.encode("utf-8")).hexdigest()
        envelope_id = f"envelope_{envelope_digest[:32]}"
        context_digest = hashlib.sha256(
            _dump(
                {
                    "workflow_id": workflow_id,
                    "session_revision": int(session["revision"]),
                    "objective": goal.summary,
                }
            ).encode("utf-8")
        ).hexdigest()
        envelope = NextActionEnvelopeV1(
            envelope_id=envelope_id,
            workflow_id=workflow_id,
            conversation_id=conversation_id,
            source_turn_id=continuation.source_turn_id,
            next_action_turn_id=continuation.continuation_turn_id,
            session_id=str(session["session_id"]),
            expected_session_revision=int(session["revision"]),
            objective=goal.summary,
            context_snapshot_id=f"snapshot_{context_digest[:32]}",
            context_snapshot_digest=context_digest,
            occurrence_id=continuation.occurrence_id,
            character_phase=continuation.character_phase,
            action_owner=continuation.action_owner,
            created_at=timestamp,
        )
        journey = parse_production_journey(str(session["journey_state_json"]))
        requirement = self._requirements.get_current_in_transaction(connection, workflow_id)
        workflow_revision = int(
            connection.execute(
                select(AgentCanvasWorkflowRow.revision).where(
                    AgentCanvasWorkflowRow.workflow_id == workflow_id
                )
            ).scalar_one()
        )
        node_revisions = {
            str(node_id): int(revision)
            for node_id, revision in connection.execute(
                select(AgentCanvasNodeRow.node_id, AgentCanvasNodeRow.revision).where(
                    AgentCanvasNodeRow.workflow_id == workflow_id
                )
            ).all()
        }
        retry_snapshot = ContinuationTurnRetrySnapshotV1(
            workflow_id=workflow_id,
            conversation_id=conversation_id,
            session_id=str(session["session_id"]),
            workflow_revision=workflow_revision,
            session_revision=int(session["revision"]),
            journey_stage=journey.stage,
            journey_stage_revision=journey.stage_revision,
            logical_action_id=continuation.source_action_id,
            root_turn_id=continuation.continuation_turn_id,
            operation="next_action",
            envelope_id=envelope_id,
            envelope_digest=hashlib.sha256(envelope.model_dump_json().encode("utf-8")).hexdigest(),
            requirement_revision_id=requirement.revision_id,
            requirement_digest=requirement.digest,
            node_revisions=node_revisions,
            asset_ids=(),
            response_locale=str(session["response_locale"]),
        )
        connection.execute(
            insert(AgentCanvasChatTurnRow).values(
                turn_id=continuation.continuation_turn_id,
                conversation_id=conversation_id,
                workflow_id=workflow_id,
                turn_kind="next_action",
                status="queued",
                request_json=_dump({"schema_version": "1", "envelope_id": envelope_id}),
                creation_mode_json=None,
                guidance_session_revision=int(session["revision"]),
                idempotency_key=continuation.idempotency_key,
                retry_snapshot_json=retry_snapshot.model_dump_json(),
                error_code=None,
                error_message=None,
                created_at=now,
                updated_at=now,
            )
        )
        AgentCanvasOperationEnvelopeRepository(self._database).create_in_transaction(
            connection,
            envelope,
        )
        AgentCanvasContinuationOutboxRepository(
            self._database,
            self._events,
        ).enqueue_in_transaction(
            connection,
            continuation_id=continuation.continuation_id,
            workflow_id=workflow_id,
            conversation_id=conversation_id,
            source_turn_id=continuation.source_turn_id,
            continuation_turn_id=continuation.continuation_turn_id,
            operation="next_action",
            payload={
                "schema_version": "1",
                "envelope_id": envelope_id,
                "occurrence_id": continuation.occurrence_id,
                "character_phase": continuation.character_phase,
                "action_owner": continuation.action_owner,
            },
            max_attempts=continuation.max_attempts,
            now=timestamp,
        )
        _append_timeline_entry(
            connection,
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            entry_type="planning_progress",
            content="Planning the next creative action.",
            metadata=build_presentation_metadata(
                message_key="planning_progress.next_action",
                message_args={},
                response_locale=str(session["response_locale"]),
                presentation_key=f"planning:{envelope_id}",
                base={"envelope_id": envelope_id, "operation": "next_action"},
            ),
            created_at=now,
        )
        self._events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=workflow_id,
                conversation_id=conversation_id,
                turn_id=continuation.continuation_turn_id,
                event_type="agent_command_queued",
                transition_key=(
                    f"conversation:{continuation.continuation_turn_id}:agent_command_queued"
                ),
                created_at=now,
                payload={"envelope_id": envelope_id, "operation": "next_action"},
            ),
        )

    def apply_guidance_state_action(
        self,
        proposal_id: str,
        *,
        source_turn_id: str,
        action_id: str,
        action: Literal["defer_topic", "exclude_element"],
        expected_session_revision: int,
        continuation: ContinuationCommitV2 | None,
    ) -> AgentActionReceiptV2:
        proposal = self.get_proposal(proposal_id)
        now = _now()
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                turn = _require_turn(connection, source_turn_id)
                proposal_row = (
                    connection.execute(
                        select(AgentCanvasConceptProposalRow).where(
                            AgentCanvasConceptProposalRow.proposal_id == proposal_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if proposal_row is None or str(proposal_row["availability"]) != "open":
                    raise _error(
                        "proposal_action_stale",
                        "Proposal action is no longer available.",
                    )
                session = _require_guidance_session_row(
                    connection,
                    proposal.guidance_session_id,
                )
                _require_guidance_revision(session, expected_session_revision)
                if str(session["active_proposal_id"]) != proposal_id:
                    raise _error(
                        "proposal_action_stale",
                        "Proposal is not the current Guidance checkpoint.",
                    )
                topic = (
                    connection.execute(
                        select(AgentCanvasGuidanceTopicRow).where(
                            AgentCanvasGuidanceTopicRow.session_id == session["session_id"],
                            AgentCanvasGuidanceTopicRow.topic_id == proposal.topic_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if topic is None:
                    raise _error("guidance_topic_not_found", "Guidance topic was not found.")
                if action == "defer_topic" and str(topic["status"]) != "proposed":
                    raise _error(
                        "guidance_defer_conflict",
                        "Guidance topic is no longer available for deferral.",
                    )
                goal = CreativeGoalV2.model_validate_json(str(session["creative_goal_json"]))
                topic_kind = canonical_guidance_topic_kind(str(topic["topic_kind"]))
                if action == "exclude_element" and topic_kind == goal.requested_output:
                    raise _error(
                        "guidance_decision_invalid",
                        "The requested output cannot be excluded.",
                    )
                element_decisions = tuple(
                    CreativeElementDecisionV2.model_validate(item)
                    for item in json.loads(str(session["element_decisions_json"]))
                )
                if action == "exclude_element":
                    replacement = CreativeElementDecisionV2(
                        element_kind=cast(str, topic_kind),
                        presence="exclude",
                        authority="user",
                        requirements={},
                        source="explicit_user",
                    )
                    element_decisions = tuple(
                        item for item in element_decisions if item.element_kind != topic_kind
                    ) + (replacement,)
                topic_status = "deferred" if action == "defer_topic" else "excluded"
                connection.execute(
                    update(AgentCanvasGuidanceTopicRow)
                    .where(
                        AgentCanvasGuidanceTopicRow.session_id == session["session_id"],
                        AgentCanvasGuidanceTopicRow.topic_id == proposal.topic_id,
                    )
                    .values(
                        status=topic_status,
                        source_proposal_id=proposal_id,
                        revision=int(topic["revision"]) + 1,
                        updated_at=now,
                    )
                )
                connection.execute(
                    update(AgentCanvasConceptProposalRow)
                    .where(AgentCanvasConceptProposalRow.proposal_id == proposal_id)
                    .values(
                        availability=("superseded" if action == "defer_topic" else "applied"),
                        updated_at=now,
                    )
                )
                next_revision = expected_session_revision + 1
                connection.execute(
                    update(AgentCanvasGuidanceSessionRow)
                    .where(
                        AgentCanvasGuidanceSessionRow.session_id == session["session_id"],
                        AgentCanvasGuidanceSessionRow.revision == expected_session_revision,
                    )
                    .values(
                        element_decisions_json=_dump(
                            [item.model_dump(mode="json") for item in element_decisions]
                        ),
                        current_topic_id=None,
                        active_proposal_id=None,
                        revision=next_revision,
                        updated_at=now,
                    )
                )
                workflow_revision = int(
                    connection.execute(
                        select(AgentCanvasWorkflowRow.revision).where(
                            AgentCanvasWorkflowRow.workflow_id == proposal.workflow_id
                        )
                    ).scalar_one()
                )
                receipt = AgentActionReceiptV2(
                    receipt_id=f"receipt_{source_turn_id}",
                    workflow_id=proposal.workflow_id,
                    action_id=source_turn_id,
                    proposal_id=proposal_id,
                    proposal_action=action,
                    actor_kind="user",
                    idempotency_key=source_turn_id,
                    status="applied",
                    summary=(
                        "The topic was deferred."
                        if action == "defer_topic"
                        else "The creative element was excluded."
                    ),
                    workflow_revision=workflow_revision,
                    continuation_turn_id=(
                        continuation.continuation_turn_id if continuation is not None else None
                    ),
                )
                connection.execute(
                    insert(AgentCanvasActionReceiptRow).values(
                        receipt_id=receipt.receipt_id,
                        workflow_id=receipt.workflow_id,
                        plan_id=None,
                        action_id=receipt.action_id,
                        proposal_id=receipt.proposal_id,
                        proposal_option_id=None,
                        proposal_action=receipt.proposal_action,
                        receipt_json=receipt.model_dump_json(),
                        created_at=now,
                    )
                )
                _append_timeline_entry(
                    connection,
                    conversation_id=str(turn["conversation_id"]),
                    workflow_id=proposal.workflow_id,
                    entry_type="action_receipt",
                    content=receipt.summary,
                    metadata=build_presentation_metadata(
                        message_key=(
                            "action.topic_deferred"
                            if action == "defer_topic"
                            else "action.element_excluded"
                        ),
                        message_args={},
                        response_locale=str(session["response_locale"]),
                        presentation_key=f"receipt:{receipt.receipt_id}",
                        base={"action_receipt": receipt.model_dump(mode="json")},
                    ),
                    created_at=now,
                )
                if continuation is not None:
                    self.insert_continuation_in_transaction(
                        connection,
                        workflow_id=proposal.workflow_id,
                        conversation_id=str(turn["conversation_id"]),
                        continuation=continuation,
                        now=now,
                    )
                common_payload = {
                    "session_id": str(session["session_id"]),
                    "session_revision": next_revision,
                    "proposal_id": proposal_id,
                    "action_id": action_id,
                    "topic_id": proposal.topic_id,
                }
                for event_type in ("proposal_action_applied", "guidance_state_updated"):
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=proposal.workflow_id,
                            conversation_id=str(turn["conversation_id"]),
                            turn_id=source_turn_id,
                            action_id=action_id,
                            event_type=event_type,
                            created_at=now,
                            payload={**common_payload, "action": action},
                        ),
                    )
                _complete_turn_in_transaction(
                    connection,
                    events=self._events,
                    turn=turn,
                    assistant_message=receipt.summary,
                    now=now,
                )
                connection.commit()
                return receipt
            except BaseException:
                connection.rollback()
                raise

    def update_publication_receipt(
        self,
        receipt: AgentActionReceiptV2,
    ) -> AgentActionReceiptV2 | None:
        """Update the one post-commit queue outcome for a published Draft receipt."""

        try:
            with self._database.engine.begin() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasActionReceiptRow).where(
                            AgentCanvasActionReceiptRow.receipt_id == receipt.receipt_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    return None
                if str(row["workflow_id"]) != receipt.workflow_id or str(
                    row["action_id"] or ""
                ) != str(receipt.action_id or ""):
                    raise _error(
                        "draft_publication_receipt_invalid",
                        "Draft publication receipt identity does not match.",
                    )
                persisted = AgentActionReceiptV2.model_validate_json(str(row["receipt_json"]))
                receipt = receipt.model_copy(
                    update={
                        "continuation_turn_id": (
                            receipt.continuation_turn_id or persisted.continuation_turn_id
                        ),
                        "created_binding_ids": (
                            receipt.created_binding_ids or persisted.created_binding_ids
                        ),
                        "proposal_id": receipt.proposal_id or persisted.proposal_id,
                        "proposal_option_id": (
                            receipt.proposal_option_id or persisted.proposal_option_id
                        ),
                        "proposal_action": receipt.proposal_action or persisted.proposal_action,
                        "created_at": persisted.created_at,
                    }
                )
                connection.execute(
                    update(AgentCanvasActionReceiptRow)
                    .where(AgentCanvasActionReceiptRow.receipt_id == receipt.receipt_id)
                    .values(receipt_json=receipt.model_dump_json())
                )
                entries = (
                    connection.execute(
                        select(AgentCanvasChatEntryRow).where(
                            AgentCanvasChatEntryRow.workflow_id == receipt.workflow_id,
                            AgentCanvasChatEntryRow.entry_type == "action_receipt",
                        )
                    )
                    .mappings()
                    .all()
                )
                for entry in entries:
                    metadata = json.loads(str(entry["metadata_json"]))
                    existing = metadata.get("action_receipt")
                    if (
                        not isinstance(existing, dict)
                        or existing.get("receipt_id") != receipt.receipt_id
                    ):
                        continue
                    connection.execute(
                        update(AgentCanvasChatEntryRow)
                        .where(AgentCanvasChatEntryRow.entry_id == entry["entry_id"])
                        .values(
                            content=receipt.summary,
                            metadata_json=_dump(
                                {
                                    **metadata,
                                    "action_receipt": receipt.model_dump(mode="json"),
                                }
                            ),
                        )
                    )
                    break
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return receipt

    def get_publication_receipt_for_action(
        self,
        action_id: str,
    ) -> AgentActionReceiptV2 | None:
        try:
            with self._database.engine.connect() as connection:
                value = connection.execute(
                    select(AgentCanvasActionReceiptRow.receipt_json).where(
                        AgentCanvasActionReceiptRow.action_id == action_id,
                        AgentCanvasActionReceiptRow.plan_id.is_(None),
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable",
                "Conversation storage failed.",
            ) from error
        if value is None:
            return None
        return AgentActionReceiptV2.model_validate_json(str(value))

    def list_publication_receipts_requiring_recovery(
        self,
    ) -> tuple[tuple[AgentActionReceiptV2, ChatTurnV2], ...]:
        """Progressive Proposal actions commit atomically and need no post-commit repair."""

        return ()

    def start_expert_activity(
        self,
        turn_id: str,
        *,
        capability_id: str,
        operation: str,
        display_name: str,
        event_details: Mapping[str, object] | None = None,
    ) -> ExpertActivityV2:
        now = _now()
        activity_id = _expert_activity_id(turn_id, capability_id, operation)
        try:
            with self._database.engine.begin() as connection:
                turn = _require_turn(connection, turn_id)
                existing = (
                    connection.execute(
                        select(AgentCanvasExpertActivityRow).where(
                            AgentCanvasExpertActivityRow.activity_id == activity_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    return _expert_activity(existing)
                connection.execute(
                    insert(AgentCanvasExpertActivityRow).values(
                        activity_id=activity_id,
                        turn_id=turn_id,
                        workflow_id=str(turn["workflow_id"]),
                        capability_id=capability_id,
                        operation=operation,
                        status="working",
                        display_name=display_name,
                        error_code=None,
                        error_message=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=str(turn["workflow_id"]),
                        event_type="expert_activity_started",
                        created_at=now,
                        payload={
                            "activity_id": activity_id,
                            "workflow_id": str(turn["workflow_id"]),
                            "turn_id": turn_id,
                            "capability_id": capability_id,
                            "operation": operation,
                            "capability_display_name": display_name,
                            "status": "working",
                            "conversation_id": str(turn["conversation_id"]),
                            "created_at": now,
                            **(event_details or {}),
                        },
                    ),
                )
                _append_timeline_entry(
                    connection,
                    conversation_id=str(turn["conversation_id"]),
                    workflow_id=str(turn["workflow_id"]),
                    entry_type="expert_activity",
                    content=display_name,
                    metadata=build_presentation_metadata(
                        message_key="expert_activity.working",
                        message_args={"capability_display_name": display_name},
                        response_locale=_guidance_response_locale(
                            connection,
                            str(turn["workflow_id"]),
                        ),
                        presentation_key=f"activity:{activity_id}",
                        base={
                            "activity_id": activity_id,
                            "capability_id": capability_id,
                            "operation": operation,
                            "capability_display_name": display_name,
                            "status": "working",
                            "conversation_id": str(turn["conversation_id"]),
                            "created_at": now,
                            **(event_details or {}),
                        },
                    ),
                    created_at=now,
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_expert_activity(activity_id)

    def transition_expert_activity(
        self,
        activity_id: str,
        *,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
        event_details: Mapping[str, object] | None = None,
    ) -> ExpertActivityV2:
        if status not in {"completed", "failed"}:
            raise _error("expert_activity_status_invalid", "Expert activity status is invalid.")
        now = _now()
        try:
            with self._database.engine.begin() as connection:
                publication = publish_expert_activity_terminal_in_transaction(
                    connection,
                    self._events,
                    activity_id=activity_id,
                    status=status,
                    error_code=error_code,
                    error_message=error_message,
                    event_details=event_details,
                    now=now,
                )
                if not publication.changed:
                    return publication.activity
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_expert_activity(activity_id)

    def get_expert_activity(self, activity_id: str) -> ExpertActivityV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasExpertActivityRow).where(
                            AgentCanvasExpertActivityRow.activity_id == activity_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        if row is None:
            raise _error("expert_activity_not_found", "Expert activity was not found.")
        return _expert_activity(row)

    def list_expert_activities(self, turn_id: str) -> tuple[ExpertActivityV2, ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasExpertActivityRow)
                        .where(AgentCanvasExpertActivityRow.turn_id == turn_id)
                        .order_by(AgentCanvasExpertActivityRow.created_at.asc())
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return tuple(_expert_activity(row) for row in rows)

    def list_working_activities_with_terminal_turns(
        self,
    ) -> tuple[tuple[ExpertActivityV2, ChatTurnV2], ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = connection.execute(
                    select(
                        AgentCanvasExpertActivityRow.activity_id,
                        AgentCanvasChatTurnRow.turn_id,
                    )
                    .join(
                        AgentCanvasChatTurnRow,
                        AgentCanvasChatTurnRow.turn_id == AgentCanvasExpertActivityRow.turn_id,
                    )
                    .where(
                        AgentCanvasExpertActivityRow.status == "working",
                        AgentCanvasChatTurnRow.status.in_(("completed", "failed")),
                    )
                    .order_by(AgentCanvasExpertActivityRow.created_at.asc())
                ).all()
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return tuple(
            (
                self.get_expert_activity(str(row.activity_id)),
                self.get_turn(str(row.turn_id)),
            )
            for row in rows
        )

    def record_expert_activity(
        self,
        turn_id: str,
        *,
        capability_id: str,
        operation: str,
        status: str,
        display_name: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> ExpertActivityV2:
        activity = self.start_expert_activity(
            turn_id,
            capability_id=capability_id,
            operation=operation,
            display_name=display_name,
        )
        if status == "working":
            return activity
        return self.transition_expert_activity(
            activity.activity_id,
            status=status,
            error_code=error_code,
            error_message=error_message,
        )

    def list_recoverable_turn_ids(self) -> tuple[str, ...]:
        try:
            with self._database.engine.connect() as connection:
                return tuple(
                    str(value)
                    for value in connection.execute(
                        select(AgentCanvasChatTurnRow.turn_id)
                        .where(
                            AgentCanvasChatTurnRow.status.in_(("queued", "running")),
                            AgentCanvasChatTurnRow.turn_id.not_in(
                                select(AgentCanvasContinuationOutboxRow.continuation_turn_id)
                            ),
                        )
                        .order_by(AgentCanvasChatTurnRow.created_at.asc())
                    ).scalars()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error

    def list_timeline(
        self,
        workflow_id: str,
        *,
        after_seq: int = 0,
        limit: int = 100,
    ) -> ChatTimelineListResponseV2:
        try:
            with self._database.engine.connect() as connection:
                conversation_id = connection.execute(
                    select(AgentCanvasConversationRow.conversation_id).where(
                        AgentCanvasConversationRow.workflow_id == workflow_id
                    )
                ).scalar_one_or_none()
                if conversation_id is None:
                    return ChatTimelineListResponseV2(
                        workflow_id=workflow_id,
                        conversation_id=None,
                        creative_session=None,
                        next_cursor=after_seq,
                    )
                rows = (
                    connection.execute(
                        select(AgentCanvasChatEntryRow)
                        .where(
                            AgentCanvasChatEntryRow.conversation_id == conversation_id,
                            AgentCanvasChatEntryRow.sequence_no > after_seq,
                        )
                        .order_by(AgentCanvasChatEntryRow.sequence_no.asc())
                        .limit(limit)
                    )
                    .mappings()
                    .all()
                )
                continuation_rows = (
                    connection.execute(
                        select(AgentCanvasContinuationOutboxRow)
                        .where(AgentCanvasContinuationOutboxRow.conversation_id == conversation_id)
                        .order_by(
                            AgentCanvasContinuationOutboxRow.created_at.asc(),
                            AgentCanvasContinuationOutboxRow.continuation_id.asc(),
                        )
                    )
                    .mappings()
                    .all()
                )
                current_action_rows = (
                    connection.execute(
                        select(AgentCanvasGuidedActionRow)
                        .where(
                            AgentCanvasGuidedActionRow.workflow_id == workflow_id,
                            AgentCanvasGuidedActionRow.state == "pending",
                        )
                        .order_by(
                            AgentCanvasGuidedActionRow.created_at.asc(),
                            AgentCanvasGuidedActionRow.action_id.asc(),
                        )
                        .limit(2)
                    )
                    .mappings()
                    .all()
                )
                authority = self._guidance_authority.read_in_transaction(
                    connection,
                    workflow_id,
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        items = tuple(_timeline_entry(row) for row in rows)
        current_session_actions = (
            ()
            if authority.session is not None
            and authority.session.awaiting is not None
            and authority.session.awaiting.requires_user_action
            else tuple(
                sorted(
                    (_guidance_session_action(row) for row in current_action_rows),
                    key=lambda action: (
                        0 if action.authority == "user" else 1,
                        action.action_id,
                    ),
                )
            )
        )
        return ChatTimelineListResponseV2(
            workflow_id=workflow_id,
            conversation_id=str(conversation_id),
            guidance_session=authority.session,
            guidance_advance_precondition=authority.precondition,
            continuations=tuple(_continuation_delivery(row) for row in continuation_rows),
            current_session_actions=current_session_actions,
            items=items,
            next_cursor=items[-1].sequence_no if items else after_seq,
        )

    def publish_script_artifact(
        self,
        workflow_id: str,
        *,
        script_node_id: str,
        source_turn_id: str | None,
    ) -> ChatTimelineEntryV2:
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    conversation_id = _ensure_conversation(connection, workflow_id, now)
                    existing_rows = (
                        connection.execute(
                            select(AgentCanvasChatEntryRow).where(
                                AgentCanvasChatEntryRow.conversation_id == conversation_id,
                                AgentCanvasChatEntryRow.entry_type == "script_artifact",
                            )
                        )
                        .mappings()
                        .all()
                    )
                    for row in existing_rows:
                        metadata = json.loads(str(row["metadata_json"]))
                        if metadata.get("script_node_id") == script_node_id:
                            connection.commit()
                            return _timeline_entry(row)
                    entry_id = f"artifact_{uuid4().hex}"
                    metadata = {
                        "script_node_id": script_node_id,
                        "source_turn_id": source_turn_id,
                        "action_label": "View Script",
                    }
                    connection.execute(
                        insert(AgentCanvasChatEntryRow).values(
                            entry_id=entry_id,
                            conversation_id=conversation_id,
                            workflow_id=workflow_id,
                            sequence_no=_next_chat_sequence(connection, conversation_id),
                            entry_type="script_artifact",
                            speaker=None,
                            content="Script ready",
                            metadata_json=_dump(metadata),
                            created_at=now,
                        )
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            node_id=script_node_id,
                            event_type="script_artifact_created",
                            created_at=now,
                            payload={"entry_id": entry_id, **metadata},
                        ),
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return next(
            item for item in self.list_timeline(workflow_id).items if item.entry_id == entry_id
        )

    def _set_turn_status(self, turn_id: str, status: str, event_type: str) -> ChatTurnV2:
        now = _now()
        try:
            with self._database.engine.begin() as connection:
                turn = _require_turn(connection, turn_id)
                connection.execute(
                    update(AgentCanvasChatTurnRow)
                    .where(AgentCanvasChatTurnRow.turn_id == turn_id)
                    .values(status=status, operation_stage=status, updated_at=now)
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=str(turn["workflow_id"]),
                        event_type=event_type,
                        created_at=now,
                        payload={"turn_id": turn_id},
                    ),
                )
                if status == "running":
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=str(turn["workflow_id"]),
                            conversation_id=str(turn["conversation_id"]),
                            turn_id=turn_id,
                            event_type="agent_operation_started",
                            transition_key=f"conversation:{turn_id}:agent_operation_started",
                            created_at=now,
                            payload={"turn_id": turn_id, "operation_stage": "running"},
                        ),
                    )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_turn(turn_id)

    @staticmethod
    def _message_id_for_turn(connection: Connection, turn_id: str) -> str | None:
        rows = (
            connection.execute(
                select(
                    AgentCanvasChatEntryRow.entry_id, AgentCanvasChatEntryRow.metadata_json
                ).where(AgentCanvasChatEntryRow.speaker == "user")
            )
            .mappings()
            .all()
        )
        for row in rows:
            if json.loads(str(row["metadata_json"])).get("turn_id") == turn_id:
                return str(row["entry_id"])
        return None

    @staticmethod
    def _queued_event_seq(
        connection: Connection,
        workflow_id: str,
        turn_id: str,
    ) -> int:
        rows = (
            connection.execute(
                select(WorkflowEventRow.seq, WorkflowEventRow.payload_json).where(
                    WorkflowEventRow.workflow_id == workflow_id,
                    WorkflowEventRow.event_type == "agent_turn_queued",
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            if json.loads(str(row["payload_json"])).get("turn_id") == turn_id:
                return int(row["seq"])
        raise _error("agent_conversation_unavailable", "Queued turn event was not found.")


def _ensure_conversation(connection: Connection, workflow_id: str, now: str) -> str:
    existing = connection.execute(
        select(AgentCanvasConversationRow.conversation_id).where(
            AgentCanvasConversationRow.workflow_id == workflow_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        return str(existing)
    _require_workflow(connection, workflow_id)
    identity = hashlib.sha256(workflow_id.encode()).hexdigest()[:20]
    conversation_id = f"conv_{identity}"
    connection.execute(
        insert(AgentCanvasConversationRow).values(
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            created_at=now,
            updated_at=now,
        )
    )
    return conversation_id


def _require_workflow(connection: Connection, workflow_id: str) -> None:
    if (
        connection.execute(
            select(AgentCanvasWorkflowRow.workflow_id).where(
                AgentCanvasWorkflowRow.workflow_id == workflow_id
            )
        ).scalar_one_or_none()
        is None
    ):
        raise _error("workflow_not_found", "Workflow was not found.")


def _validate_guidance_advance_authority(
    connection: Connection,
    *,
    plan: GuidanceAdvanceAuthorityPlanV1,
    requirements: AgentCanvasRequirementRepository,
    continuations: AgentCanvasContinuationOutboxRepository,
) -> None:
    del continuations
    snapshot = GuidanceAdvanceAuthoritySnapshotRepository(requirements).read_in_transaction(
        connection, plan.workflow_id
    )
    require_guidance_advance_eligible(snapshot, check_orphaned_action=False)
    submitted = plan.request.precondition
    if snapshot.precondition != submitted:
        raise guidance_advance_stale_error(
            submitted,
            snapshot,
            stage="guidance_advance_commit",
        )
    require_guidance_advance_eligible(snapshot)
    if (
        plan.session_id != submitted.session_id
        or plan.session_status != submitted.session_status
        or plan.journey_active_action_digest != submitted.active_action_digest
        or plan.requirement_revision_id != submitted.requirement_revision_id
        or plan.requirement_digest != submitted.requirement_digest
        or plan.conversation_id != snapshot.conversation_id
        or plan.open_proposal_id != snapshot.open_proposal_id
        or plan.open_decision_bundle_id != snapshot.open_decision_bundle_id
        or plan.active_continuation_id != snapshot.active_continuation_id
        or plan.target.source_id != submitted.source_id
        or plan.target.journey_stage != submitted.journey_stage
        or plan.target.journey_stage_revision != submitted.journey_stage_revision
        or plan.target.guidance_session_revision != submitted.session_revision
        or plan.target.requirement_revision_id != submitted.requirement_revision_id
    ):
        raise guidance_advance_stale_error(
            submitted,
            snapshot,
            stage="guidance_advance_commit",
        )


def _guidance_replay_receipt(
    connection: Connection,
    *,
    existing: RowMapping,
    plan: GuidanceAdvanceAuthorityPlanV1,
) -> GuidanceAdvanceCommitReceiptV1:
    return _guidance_replay_receipt_for_identity(
        connection,
        existing=existing,
        workflow_id=plan.workflow_id,
        request_digest=plan.request_digest,
    )


def _guidance_replay_receipt_for_identity(
    connection: Connection,
    *,
    existing: RowMapping,
    workflow_id: str,
    request_digest: str,
) -> GuidanceAdvanceCommitReceiptV1:
    persisted = json.loads(str(existing["request_json"]))
    persisted_request = {"precondition": persisted.get("precondition")}
    persisted_digest = persisted.get("guidance_request_digest") or _sha256_json(persisted_request)
    executable_turn_id = persisted.get("executable_turn_id")
    if (
        str(existing["workflow_id"]) != workflow_id
        or str(existing["turn_kind"]) != "guidance_advance"
        or persisted_digest != request_digest
        or not isinstance(executable_turn_id, str)
    ):
        raise _error("idempotency_conflict", "Idempotency key was reused.")
    child = _require_turn(connection, executable_turn_id)
    event_cursor = connection.execute(
        select(WorkflowEventRow.seq).where(
            WorkflowEventRow.transition_key == f"guidance-advance:{existing['turn_id']}"
        )
    ).scalar_one_or_none()
    if event_cursor is None:
        raise _error(
            "agent_conversation_unavailable",
            "Guidance command replay metadata is incomplete.",
        )
    continuation_id = connection.execute(
        select(AgentCanvasContinuationOutboxRow.continuation_id).where(
            AgentCanvasContinuationOutboxRow.source_turn_id == existing["turn_id"]
        )
    ).scalar_one_or_none()
    return GuidanceAdvanceCommitReceiptV1(
        workflow_id=workflow_id,
        command_turn_id=str(existing["turn_id"]),
        executable_turn_id=executable_turn_id,
        continuation_id=(str(continuation_id) if continuation_id is not None else None),
        event_cursor=int(event_cursor),
        request_digest=request_digest,
        retry_of_turn_id=(str(child["retry_of_turn_id"]) if child["retry_of_turn_id"] else None),
        retry_attempt_no=int(child["retry_attempt_no"]),
        replayed=True,
    )


def _guidance_accepted(
    connection: Connection,
    receipt: GuidanceAdvanceCommitReceiptV1,
) -> ChatTurnAcceptedV2:
    child = _require_turn(connection, receipt.executable_turn_id)
    return ChatTurnAcceptedV2(
        workflow_id=receipt.workflow_id,
        conversation_id=str(child["conversation_id"]),
        message_id=None,
        turn_id=receipt.executable_turn_id,
        events_cursor=receipt.event_cursor,
        retry_of_turn_id=receipt.retry_of_turn_id,
        retry_attempt_no=receipt.retry_attempt_no,
        replayed=receipt.replayed,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_dump(value).encode("utf-8")).hexdigest()


def _guidance_advance_not_available(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "guidance_advance_not_available",
        message,
        stage="guidance_advance_commit",
    )


def _require_turn(connection: Connection, turn_id: str) -> RowMapping:
    row = (
        connection.execute(
            select(AgentCanvasChatTurnRow).where(AgentCanvasChatTurnRow.turn_id == turn_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _error("chat_turn_not_found", "Chat turn was not found.")
    return row


def _validate_clarification_target(
    *,
    current: GuidedProductionJourneyV2,
    target: GuidedProductionJourneyV2,
    turn_id: str,
) -> None:
    if current.stage in {"intake", "character"} and current.stage_status == "waiting_user":
        expected = current.model_copy(update={"stage_status": "waiting_user"})
        if target != expected:
            raise _error(
                "journey_transition_invalid",
                "Repeated clarification may only retain the current waiting journey.",
            )
        return
    if current.stage in {"intake", "character"}:
        evidence = target.transition_evidence[-1] if target.transition_evidence else None
        expected_evidence_kind = (
            "creative_goal_validated" if current.stage == "intake" else "clarification_completed"
        )
        if (
            target.stage_revision != current.stage_revision + 1
            or evidence is None
            or evidence.evidence_kind != expected_evidence_kind
            or evidence.source_id != turn_id
        ):
            raise _error(
                "journey_transition_invalid",
                "Clarification target does not match its source Turn.",
            )
        return
    raise _error(
        "journey_transition_invalid",
        "Only an intake or Character journey may publish clarification authority.",
    )


def _upsert_clarification_authority(
    connection: Connection,
    *,
    events: EventRepository,
    workflow_id: str,
    session_id: str,
    response_locale: str,
    expected_session_revision: int,
    journey: GuidedProductionJourneyV2,
    assistant_message: str,
    questionnaire: GuidedQuestionnaireV1 | None,
    checkpoint_id: str | None,
    interaction_title: str | None,
    interaction_context: str | None,
    now: str,
) -> None:
    checkpoint_id = checkpoint_id or f"clarification:{journey.stage_revision}"
    identity = hashlib.sha256(
        f"{workflow_id}:{session_id}:{checkpoint_id}".encode("utf-8")
    ).hexdigest()[:32]
    interaction_id = f"interaction_{identity}"
    awaiting_id = f"awaiting_{identity}"
    content = questionnaire or GuidedQuestionnaireV1(
        questions=(
            GuidedQuestionV1(
                question_id=f"question_{identity}",
                prompt=assistant_message.strip()[:512],
                options=(
                    GuidedChoiceOptionV1(
                        option_id=f"option_{identity}_details",
                        title="Provide more details",
                        summary="Use the additional campaign details I provide.",
                    ),
                    GuidedChoiceOptionV1(
                        option_id=f"option_{identity}_continue",
                        title="Continue with current details",
                        summary="Continue with the currently confirmed campaign requirements.",
                    ),
                ),
                allow_custom=True,
                allow_skip=True,
                required=False,
            ),
        )
    )
    current_row = (
        connection.execute(
            select(AgentCanvasGuidedInteractionRow).where(
                AgentCanvasGuidedInteractionRow.workflow_id == workflow_id,
                AgentCanvasGuidedInteractionRow.status == "open",
            )
        )
        .mappings()
        .one_or_none()
    )
    awaiting_row = (
        connection.execute(
            select(AgentCanvasGuidanceAwaitingRow).where(
                AgentCanvasGuidanceAwaitingRow.workflow_id == workflow_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if current_row is not None:
        if (
            str(current_row["interaction_id"]) != interaction_id
            or str(current_row["kind"]) != "clarification_questionnaire"
            or awaiting_row is None
            or str(awaiting_row["awaiting_id"]) != awaiting_id
        ):
            raise _error(
                "guided_interaction_conflict",
                "Another guided interaction owns the current Guidance checkpoint.",
            )
        connection.execute(
            update(AgentCanvasGuidedInteractionRow)
            .where(AgentCanvasGuidedInteractionRow.interaction_id == interaction_id)
            .values(
                response_locale=response_locale,
                expected_session_revision=expected_session_revision,
                revision=int(current_row["revision"]) + 1,
                content_json=content.model_dump_json(),
                updated_at=now,
            )
        )
        return
    if awaiting_row is not None:
        raise _error(
            "guidance_awaiting_conflict",
            "Another durable wait owns the current Guidance session.",
        )
    interaction = GuidedInteractionV1(
        interaction_id=interaction_id,
        workflow_id=workflow_id,
        session_id=session_id,
        checkpoint_id=checkpoint_id,
        kind="clarification_questionnaire",
        status="open",
        response_locale=response_locale,
        expected_session_revision=expected_session_revision,
        revision=1,
        title=interaction_title or "Clarify campaign requirements",
        context=(
            interaction_context
            or "Answer the current clarification before guided production continues."
        ),
        content=content,
        allowed_actions=(
            ("answer", "custom") if questionnaire is not None else ("answer", "custom", "skip")
        ),
        submit_path=(f"/api/v2/workflows/{workflow_id}/chat/interactions/{interaction_id}/submit"),
        created_at=now,
        updated_at=now,
    )
    awaiting = GuidanceAwaitingV2(
        awaiting_id=awaiting_id,
        workflow_id=workflow_id,
        session_id=session_id,
        checkpoint_id=checkpoint_id,
        kind="clarification",
        requires_user_action=True,
        resume_policy="submit_interaction",
        interaction_id=interaction_id,
        stage=journey.stage,
        stage_revision=journey.stage_revision,
        created_at=now,
    )
    connection.execute(
        insert(AgentCanvasGuidedInteractionRow).values(
            interaction_id=interaction.interaction_id,
            workflow_id=interaction.workflow_id,
            session_id=interaction.session_id,
            checkpoint_id=interaction.checkpoint_id,
            kind=interaction.kind,
            status=interaction.status,
            response_locale=interaction.response_locale,
            expected_session_revision=interaction.expected_session_revision,
            revision=interaction.revision,
            title=interaction.title,
            context=interaction.context,
            content_json=interaction.content.model_dump_json(),
            allowed_actions_json=_dump(list(interaction.allowed_actions)),
            submit_path=interaction.submit_path,
            created_at=now,
            updated_at=now,
        )
    )
    connection.execute(
        insert(AgentCanvasGuidanceAwaitingRow).values(
            awaiting_id=awaiting.awaiting_id,
            workflow_id=awaiting.workflow_id,
            session_id=awaiting.session_id,
            checkpoint_id=awaiting.checkpoint_id,
            kind=awaiting.kind,
            requires_user_action=awaiting.requires_user_action,
            resume_policy=awaiting.resume_policy,
            interaction_id=awaiting.interaction_id,
            node_ids_json="[]",
            stage=awaiting.stage,
            stage_revision=awaiting.stage_revision,
            created_at=now,
        )
    )
    events.append_in_transaction(
        connection,
        V2EventInsert(
            workflow_id=workflow_id,
            event_type="guided_interaction_opened",
            transition_key=f"guided-interaction:{interaction_id}:opened",
            action_id=interaction_id,
            created_at=now,
            payload={
                "interaction_id": interaction_id,
                "session_id": session_id,
                "checkpoint_id": checkpoint_id,
                "kind": interaction.kind,
                "interaction_revision": interaction.revision,
            },
        ),
    )
    events.append_in_transaction(
        connection,
        V2EventInsert(
            workflow_id=workflow_id,
            event_type="guidance_awaiting_entered",
            transition_key=f"guidance-awaiting:{awaiting_id}:entered",
            action_id=interaction_id,
            created_at=now,
            payload={
                "awaiting_id": awaiting_id,
                "session_id": session_id,
                "checkpoint_id": checkpoint_id,
                "kind": awaiting.kind,
                "resume_policy": awaiting.resume_policy,
                "interaction_id": interaction_id,
                "node_ids": [],
            },
        ),
    )


def _turn_skill_run_id(turn: RowMapping) -> str | None:
    value = json.loads(str(turn["request_json"])).get("video_skill_run_id")
    return str(value) if isinstance(value, str) else None


def _next_chat_sequence(connection: Connection, conversation_id: str) -> int:
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


def _complete_turn_in_transaction(
    connection: Connection,
    *,
    events: EventRepository,
    turn: RowMapping,
    assistant_message: str | None,
    now: str,
) -> None:
    if assistant_message:
        _publish_assistant_message_in_transaction(
            connection,
            events=events,
            turn=turn,
            assistant_message=assistant_message,
            now=now,
        )
    _complete_turn_state_in_transaction(
        connection,
        events=events,
        turn=turn,
        now=now,
    )


def _publish_assistant_message_in_transaction(
    connection: Connection,
    *,
    events: EventRepository,
    turn: RowMapping,
    assistant_message: str,
    now: str,
    entry_id: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> str:
    turn_id = str(turn["turn_id"])
    workflow_id = str(turn["workflow_id"])
    conversation_id = str(turn["conversation_id"])
    resolved_entry_id = entry_id or f"msg_{uuid4().hex}"
    deterministic_publication = entry_id is not None
    resolved_metadata: dict[str, object] = {"turn_id": turn_id}
    if metadata:
        resolved_metadata.update(metadata)
    connection.execute(
        insert(AgentCanvasChatEntryRow).values(
            entry_id=resolved_entry_id,
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            sequence_no=_next_chat_sequence(connection, conversation_id),
            entry_type="message",
            speaker="adcraft_video_agent",
            content=assistant_message,
            metadata_json=_dump(resolved_metadata),
            created_at=now,
        )
    )
    events.append_in_transaction(
        connection,
        V2EventInsert(
            workflow_id=workflow_id,
            conversation_id=(conversation_id if deterministic_publication else None),
            turn_id=(turn_id if deterministic_publication else None),
            event_type="chat_message_created",
            transition_key=(
                f"conversation:{turn_id}:chat_message_created"
                if deterministic_publication
                else None
            ),
            created_at=now,
            payload={
                "turn_id": turn_id,
                "speaker": "adcraft_video_agent",
            },
        ),
    )
    return resolved_entry_id


def _complete_turn_state_in_transaction(
    connection: Connection,
    *,
    events: EventRepository,
    turn: RowMapping,
    now: str,
    owned_events: bool = False,
) -> None:
    turn_id = str(turn["turn_id"])
    workflow_id = str(turn["workflow_id"])
    conversation_id = str(turn["conversation_id"])
    connection.execute(
        update(AgentCanvasChatTurnRow)
        .where(AgentCanvasChatTurnRow.turn_id == turn_id)
        .values(
            status="completed",
            retryable=False,
            operation_stage="completed",
            operation_failure_json=None,
            updated_at=now,
        )
    )
    events.append_in_transaction(
        connection,
        V2EventInsert(
            workflow_id=workflow_id,
            conversation_id=(conversation_id if owned_events else None),
            turn_id=(turn_id if owned_events else None),
            event_type="chat_turn_completed",
            transition_key=(
                f"conversation:{turn_id}:chat_turn_completed" if owned_events else None
            ),
            created_at=now,
            payload={"turn_id": turn_id},
        ),
    )
    retry_of_turn_id = turn["retry_of_turn_id"]
    if retry_of_turn_id:
        events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=workflow_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                event_type="journey_stage_recovered",
                transition_key=f"conversation:{turn_id}:journey_stage_recovered",
                created_at=now,
                payload={
                    "turn_id": turn_id,
                    "retry_of_turn_id": str(retry_of_turn_id),
                    "retry_attempt_no": int(turn["retry_attempt_no"]),
                },
            ),
        )
    events.append_in_transaction(
        connection,
        V2EventInsert(
            workflow_id=workflow_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            event_type="agent_operation_completed",
            transition_key=f"conversation:{turn_id}:agent_operation_completed",
            created_at=now,
            payload={"turn_id": turn_id, "operation_stage": "completed"},
        ),
    )


def _turn_retry_snapshot(
    connection: Connection,
    workflow_id: str,
    request: Mapping[str, object],
) -> dict[str, object]:
    workflow_revision = connection.execute(
        select(AgentCanvasWorkflowRow.revision).where(
            AgentCanvasWorkflowRow.workflow_id == workflow_id
        )
    ).scalar_one()
    session_row = (
        connection.execute(
            select(AgentCanvasGuidanceSessionRow).where(
                AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
            )
        )
        .mappings()
        .one_or_none()
    )
    mentioned_node_ids = tuple(
        str(item) for item in request.get("mentioned_node_ids", ()) if str(item)
    )
    node_rows = (
        connection.execute(
            select(AgentCanvasNodeRow.node_id, AgentCanvasNodeRow.revision).where(
                AgentCanvasNodeRow.workflow_id == workflow_id,
                AgentCanvasNodeRow.node_id.in_(mentioned_node_ids),
            )
        )
        .mappings()
        .all()
        if mentioned_node_ids
        else ()
    )
    journey = json.loads(str(session_row["journey_state_json"])) if session_row is not None else {}
    return {
        "workflow_revision": int(workflow_revision),
        "session_revision": int(session_row["revision"]) if session_row is not None else 0,
        "journey_stage": journey.get("stage"),
        "journey_stage_revision": journey.get("stage_revision"),
        "node_revisions": {str(row["node_id"]): int(row["revision"]) for row in node_rows},
        "asset_ids": sorted(
            str(item) for item in request.get("mentioned_image_asset_ids", ()) if str(item)
        ),
    }


def _append_timeline_entry(
    connection: Connection,
    *,
    conversation_id: str,
    workflow_id: str,
    entry_type: str,
    content: str,
    metadata: dict[str, object],
    created_at: str,
) -> None:
    connection.execute(
        insert(AgentCanvasChatEntryRow).values(
            entry_id=f"entry_{uuid4().hex}",
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            sequence_no=_next_chat_sequence(connection, conversation_id),
            entry_type=entry_type,
            speaker=None,
            content=content,
            metadata_json=_dump(metadata),
            created_at=created_at,
        )
    )


def _guidance_response_locale(connection: Connection, workflow_id: str) -> str:
    value = connection.execute(
        select(AgentCanvasGuidanceSessionRow.response_locale).where(
            AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
        )
    ).scalar_one_or_none()
    return str(value or "und")


def _skill_run(
    row: RowMapping,
    *,
    public_skill: VideoSkillPublicDetailV2 | None = None,
) -> VideoSkillRunV2:
    return VideoSkillRunV2(
        skill_run_id=str(row["skill_run_id"]),
        workflow_id=str(row["workflow_id"]),
        skill_id=str(row["skill_id"]),
        skill_version=str(row["skill_version"]),
        source_skill_run_id=(
            str(row["source_skill_run_id"]) if row["source_skill_run_id"] else None
        ),
        status=cast(str, row["status"]),
        active_creative_direction_snapshot_id=(
            str(row["active_creative_direction_snapshot_id"])
            if row["active_creative_direction_snapshot_id"]
            else None
        ),
        public_skill=public_skill,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _skill_run_with_public(
    connection: Connection,
    row: RowMapping,
) -> VideoSkillRunV2:
    snapshot_id = row["active_creative_direction_snapshot_id"]
    if snapshot_id is None:
        return _skill_run(row)
    global_direction_json = connection.execute(
        select(AgentCanvasCreativeDirectionSnapshotRow.global_direction_json).where(
            AgentCanvasCreativeDirectionSnapshotRow.snapshot_id == str(snapshot_id)
        )
    ).scalar_one_or_none()
    if global_direction_json is None:
        return _skill_run(row)
    global_direction = json.loads(str(global_direction_json))
    public_payload = global_direction.get("public_skill")
    if not isinstance(public_payload, dict):
        return _skill_run(row)
    return _skill_run(
        row,
        public_skill=VideoSkillPublicDetailV2.model_validate(public_payload),
    )


def _creative_direction_snapshot(
    row: RowMapping,
) -> CreativeDirectionSnapshotV2:
    return CreativeDirectionSnapshotV2(
        snapshot_id=str(row["snapshot_id"]),
        workflow_id=str(row["workflow_id"]),
        skill_run_id=str(row["skill_run_id"]),
        version=int(row["version"]),
        source_skill_id=(str(row["source_skill_id"]) if row["source_skill_id"] else None),
        source_skill_version=(
            str(row["source_skill_version"]) if row["source_skill_version"] else None
        ),
        source_skill_digest=(
            str(row["source_skill_digest"]) if row["source_skill_digest"] else None
        ),
        global_direction=json.loads(str(row["global_direction_json"])),
        role_projections=json.loads(str(row["role_projections_json"])),
        source_message_id=(str(row["source_message_id"]) if row["source_message_id"] else None),
        source_proposal_id=(str(row["source_proposal_id"]) if row["source_proposal_id"] else None),
        content_digest=str(row["content_digest"]),
        created_at=str(row["created_at"]),
    )


def _expert_activity(row: RowMapping) -> ExpertActivityV2:
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


def _expert_activity_id(turn_id: str, capability_id: str, operation: str) -> str:
    identity = f"{turn_id}:{capability_id}:{operation}".encode("utf-8")
    return f"activity_{hashlib.sha256(identity).hexdigest()[:32]}"


def _creative_memory(
    row: RowMapping | None,
    workflow_id: str,
) -> ProjectCreativeMemoryV2:
    if row is None:
        return ProjectCreativeMemoryV2(
            workflow_id=workflow_id,
            memory_revision=0,
            updated_at=_now(),
        )
    return ProjectCreativeMemoryV2(
        workflow_id=str(row["workflow_id"]),
        creative_goal=str(row["creative_goal"]),
        target_audience=str(row["target_audience"]),
        duration_format=str(row["duration_format"]),
        approved_style_summary=str(row["approved_style_summary"]),
        approved_node_ids={
            str(role): tuple(str(node_id) for node_id in node_ids)
            for role, node_ids in json.loads(str(row["approved_node_ids_json"])).items()
        },
        open_questions=tuple(json.loads(str(row["open_questions_json"]))),
        deferred_topics=tuple(json.loads(str(row["deferred_topics_json"]))),
        rejection_notes=tuple(json.loads(str(row["rejection_notes_json"]))),
        conversation_summary=str(row["conversation_summary"]),
        summary_through_sequence_no=int(row["summary_through_sequence_no"]),
        memory_revision=int(row["memory_revision"]),
        updated_at=str(row["updated_at"]),
    )


def _creative_memory_values(
    memory: ProjectCreativeMemoryV2,
    memory_revision: int,
    *,
    created_at: str,
    updated_at: str,
) -> dict[str, object]:
    return {
        "workflow_id": memory.workflow_id,
        "creative_goal": memory.creative_goal,
        "target_audience": memory.target_audience,
        "duration_format": memory.duration_format,
        "approved_style_summary": memory.approved_style_summary,
        "approved_node_ids_json": _dump(memory.approved_node_ids),
        "open_questions_json": _dump(list(memory.open_questions)),
        "deferred_topics_json": _dump(list(memory.deferred_topics)),
        "rejection_notes_json": _dump(list(memory.rejection_notes)),
        "conversation_summary": memory.conversation_summary,
        "summary_through_sequence_no": memory.summary_through_sequence_no,
        "memory_revision": memory_revision,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _memory_revision(connection: Connection, workflow_id: str) -> int:
    value = connection.execute(
        select(AgentCanvasCreativeMemoryRow.memory_revision).where(
            AgentCanvasCreativeMemoryRow.workflow_id == workflow_id
        )
    ).scalar_one_or_none()
    return int(value) if value is not None else 0


def _insert_retry_turn_in_transaction(
    connection: Connection,
    *,
    events: EventRepository,
    source: ChatTurnV2,
    turn_id: str,
    conversation_id: str,
    idempotency_key: str,
    guidance_session_revision: int | None,
    retry_snapshot: dict[str, object],
    now: str,
    request: dict[str, object] | None = None,
):
    """Persist the one canonical retry child shape in a caller transaction."""

    retry_attempt_no = source.retry_attempt_no + 1
    connection.execute(
        insert(AgentCanvasChatTurnRow).values(
            turn_id=turn_id,
            conversation_id=conversation_id,
            workflow_id=source.workflow_id,
            turn_kind=source.turn_kind,
            status="queued",
            request_json=_dump(request if request is not None else dict(source.request)),
            creation_mode_json=None,
            guidance_session_revision=guidance_session_revision,
            idempotency_key=idempotency_key,
            retry_of_turn_id=source.turn_id,
            retry_attempt_no=retry_attempt_no,
            retryable=False,
            operation_stage="queued",
            operation_failure_json=None,
            retry_snapshot_json=_dump(retry_snapshot),
            error_code=None,
            error_message=None,
            created_at=now,
            updated_at=now,
        )
    )
    payload = {
        "turn_id": turn_id,
        "turn_kind": source.turn_kind,
        "retry_of_turn_id": source.turn_id,
        "retry_attempt_no": retry_attempt_no,
    }
    command_turn_id = retry_snapshot.get("guidance_command_turn_id")
    if isinstance(command_turn_id, str):
        payload["guidance_command_turn_id"] = command_turn_id
    queued = events.append_in_transaction(
        connection,
        V2EventInsert(
            workflow_id=source.workflow_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            event_type="agent_turn_queued",
            created_at=now,
            payload=payload,
        ),
    )
    for event_type, transition_key in (
        ("agent_operation_queued", f"conversation:{turn_id}:agent_operation_queued"),
        ("chat_turn_retry_accepted", f"conversation:{turn_id}:retry_accepted"),
    ):
        events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=source.workflow_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                event_type=event_type,
                transition_key=transition_key,
                created_at=now,
                payload=payload,
            ),
        )
    return queued


def _turn(
    row: RowMapping,
    *,
    continuation: ContinuationDeliveryV2 | None = None,
) -> ChatTurnV2:
    return ChatTurnV2(
        turn_id=str(row["turn_id"]),
        workflow_id=str(row["workflow_id"]),
        conversation_id=str(row["conversation_id"]),
        status=cast(str, row["status"]),
        turn_kind=cast(str, row["turn_kind"]),
        request=json.loads(str(row["request_json"])),
        creation_mode=(
            CreationModeDecisionV2.model_validate_json(str(row["creation_mode_json"]))
            if row["creation_mode_json"]
            else None
        ),
        guidance_session_revision=(
            int(row["guidance_session_revision"])
            if row["guidance_session_revision"] is not None
            else None
        ),
        continuation=continuation,
        retry_of_turn_id=(str(row["retry_of_turn_id"]) if row["retry_of_turn_id"] else None),
        retry_attempt_no=int(row["retry_attempt_no"]),
        retryable=bool(row["retryable"]),
        operation_stage=(str(row["operation_stage"]) if row["operation_stage"] else None),
        operation_failure=(
            AgentOperationFailureV2.model_validate_json(str(row["operation_failure_json"]))
            if row["operation_failure_json"]
            else None
        ),
        error_code=str(row["error_code"]) if row["error_code"] else None,
        error_message=str(row["error_message"]) if row["error_message"] else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _continuation_delivery(row: RowMapping) -> ContinuationDeliveryV2:
    payload = json.loads(str(row["payload_json"]))
    return ContinuationDeliveryV2(
        continuation_id=str(row["continuation_id"]),
        workflow_id=str(row["workflow_id"]),
        conversation_id=str(row["conversation_id"]),
        source_turn_id=str(row["source_turn_id"]),
        continuation_turn_id=str(row["continuation_turn_id"]),
        operation=str(row["operation"]),
        envelope_id=str(payload["envelope_id"]),
        payload_digest=str(row["payload_digest"]),
        status=cast(str, row["status"]),
        attempt_count=int(row["attempt_count"]),
        max_attempts=int(row["max_attempts"]),
        next_attempt_at=str(row["next_attempt_at"]),
        lease_owner=str(row["lease_owner"]) if row["lease_owner"] else None,
        lease_generation=int(row["lease_generation"]),
        lease_expires_at=(str(row["lease_expires_at"]) if row["lease_expires_at"] else None),
        last_error_code=(str(row["last_error_code"]) if row["last_error_code"] else None),
        last_error_message=(str(row["last_error_message"]) if row["last_error_message"] else None),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _guidance_session_action(row: RowMapping) -> GuidanceSessionActionV2:
    payload = json.loads(str(row["action_json"]))
    payload["state"] = str(row["state"])
    return GuidanceSessionActionV2.model_validate(payload)


def _proposal(
    row: RowMapping,
    options: list[RowMapping],
    applications: list[RowMapping] | None = None,
    *,
    current_session_revision: int | None = None,
) -> ConceptProposalV2:
    applications = applications or []
    latest_application = None
    if applications:
        latest = applications[0]
        receipt = AgentActionReceiptV2.model_validate_json(str(latest["receipt_json"]))
        if (
            receipt.proposal_id is not None
            and receipt.proposal_option_id is not None
            and receipt.proposal_action in {"select_option", "delegate_choice", "reuse_direction"}
        ):
            latest_application = ProposalApplicationSummaryV2(
                application_id=str(receipt.action_id or receipt.receipt_id),
                option_id=receipt.proposal_option_id,
                action=receipt.proposal_action,
                receipt_id=receipt.receipt_id,
                created_node_ids=receipt.created_node_ids,
                queued_execution_ids=receipt.queued_execution_ids,
                created_at=receipt.created_at,
            )
    proposal_card_schema_version = int(row["proposal_card_schema_version"] or 1)
    if proposal_card_schema_version not in {1, 2, 3}:
        raise _error(
            "proposal_card_version_unsupported",
            "The persisted Proposal Card schema version is unsupported.",
        )
    availability = cast(str, row["availability"])
    character_target = _proposal_character_target(row)
    materialization = (
        ProposalMaterializationProjectionV2(
            materialization_id=str(row["materialization_id"]),
            option_id=str(row["materialization_option_id"]),
            turn_id=str(row["materialization_turn_id"]),
            status=cast(str, row["materialization_status"]),
            attempt_no=int(row["materialization_attempt_no"]),
            retryable=bool(row["materialization_retryable"]),
            error=(
                ProposalMaterializationErrorV2(
                    code=str(row["materialization_error_code"]),
                    message=str(row["materialization_error_message"]),
                )
                if row["materialization_error_code"] is not None
                and row["materialization_error_message"] is not None
                else None
            ),
            created_at=str(row["materialization_created_at"]),
            updated_at=str(row["materialization_updated_at"]),
        )
        if row["materialization_id"] is not None
        else None
    )
    actions = (
        _proposal_action_descriptors(
            proposal_id=str(row["proposal_id"]),
            expected_session_revision=int(row["guidance_session_revision"]),
            proposal_kind=str(row["proposal_kind"]),
        )
        if availability == "open" and len(options) == 3
        else (
            _historical_proposal_action_descriptors(
                proposal_id=str(row["proposal_id"]),
                option_ids=tuple(str(option["option_id"]) for option in options),
                expected_session_revision=(
                    current_session_revision or int(row["guidance_session_revision"])
                ),
            )
            if availability == "superseded" and proposal_card_schema_version == 3
            else ()
        )
    )
    if materialization is not None and materialization.status in {"queued", "working"}:
        actions = tuple(
            action.model_copy(
                update={
                    "enabled": False,
                    "disabled_reason": "The selected direction is being materialized.",
                }
            )
            for action in actions
        )
    return ConceptProposalV2(
        proposal_id=str(row["proposal_id"]),
        workflow_id=str(row["workflow_id"]),
        turn_id=str(row["turn_id"]),
        video_skill_run_id=(
            str(row["video_skill_run_id"]) if row["video_skill_run_id"] is not None else None
        ),
        topic_id=str(row["topic_id"]) if row["topic_id"] is not None else None,
        target_node_id=(str(row["target_node_id"]) if row["target_node_id"] is not None else None),
        target_node_revision=(
            int(row["target_node_revision"]) if row["target_node_revision"] is not None else None
        ),
        proposal_purpose=(
            str(row["proposal_purpose"]) if row["proposal_purpose"] is not None else None
        ),
        creative_direction_snapshot_id=(
            str(row["creative_direction_snapshot_id"])
            if row["creative_direction_snapshot_id"] is not None
            else None
        ),
        proposal_revision=int(row["proposal_revision"]),
        source_proposal_id=(
            str(row["source_proposal_id"]) if row["source_proposal_id"] is not None else None
        ),
        proposal_kind=cast(str, row["proposal_kind"]),
        capability_id=cast(str, row["capability_id"]),
        proposal_card_schema_version=proposal_card_schema_version,
        availability=availability,
        application_count=len(applications),
        latest_application=latest_application,
        materialization=materialization,
        guidance_session_id=str(row["guidance_session_id"]),
        guidance_session_revision=int(row["guidance_session_revision"]),
        occurrence_id=(character_target.occurrence_id if character_target is not None else None),
        occurrence_index=(
            character_target.occurrence_index if character_target is not None else None
        ),
        occurrence_count=(
            character_target.occurrence_count if character_target is not None else None
        ),
        character_phase=(
            character_target.character_phase if character_target is not None else None
        ),
        actions=actions,
        proposed_references=tuple(
            ProposedDraftReferenceV2.model_validate(item)
            for item in json.loads(str(row["proposed_references_json"]))
        ),
        options=tuple(
            ConceptOptionRecordV2(
                option_id=str(option["option_id"]),
                title=str(option["title"]),
                public_summary=str(option["description"]),
                key_decisions=(
                    tuple(json.loads(str(option["key_decisions_json"])))
                    if proposal_card_schema_version == 1
                    else ()
                ),
            )
            for option in options
        ),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _proposal_character_target(row: RowMapping) -> CharacterProposalTargetV1 | None:
    """Read and validate the immutable scope stored with a Character Proposal."""

    values = (
        row.get("character_occurrence_id"),
        row.get("character_occurrence_index"),
        row.get("character_occurrence_count"),
        row.get("character_phase"),
        row.get("character_scope_digest"),
    )
    if not any(value is not None for value in values):
        return None
    if not all(value is not None for value in values):
        raise _error(
            "character_proposal_scope_invalid",
            "Persisted Character Proposal scope is incomplete.",
        )
    if str(row["capability_id"]) != "character_design":
        raise _error(
            "character_proposal_scope_invalid",
            "Only Character Proposals may carry occurrence scope.",
        )
    try:
        return CharacterProposalTargetV1.model_validate(
            {
                "occurrence_id": values[0],
                "occurrence_index": values[1],
                "occurrence_count": values[2],
                "character_phase": values[3],
                "requirement_revision_id": row["requirement_revision_id"],
                "requirement_revision_no": row["requirement_revision_no"],
                "target_digest": values[4],
            }
        )
    except ValueError as error:
        raise _error(
            "character_proposal_scope_invalid",
            "Persisted Character Proposal scope is invalid.",
        ) from error


def _timeline_entry(row: RowMapping) -> ChatTimelineEntryV2:
    metadata = json.loads(str(row["metadata_json"]))
    return ChatTimelineEntryV2(
        entry_id=str(row["entry_id"]),
        workflow_id=str(row["workflow_id"]),
        conversation_id=str(row["conversation_id"]),
        sequence_no=int(row["sequence_no"]),
        entry_type=cast(str, row["entry_type"]),
        speaker=cast(str | None, row["speaker"]),
        content=str(row["content"]),
        metadata=metadata,
        command_plan=metadata.get("command_plan"),
        action_receipt=metadata.get("action_receipt"),
        created_at=str(row["created_at"]),
    )


def _proposal_action_descriptors(
    *,
    proposal_id: str,
    expected_session_revision: int,
    proposal_kind: str,
) -> tuple[ProposalActionDescriptorV2, ...]:
    stage_by_kind = {
        "world_setting": "world_view",
        "product": "product",
        "prop": "props",
        "character": "character",
        "scene": "scene",
        "script": "narrative_direction",
        "storyboard": "storyboard_plan",
        "video": "videos",
        "bgm": "bgm",
    }
    stage = stage_by_kind.get(proposal_kind)
    optional = bool(stage is not None and FIXED_JOURNEY_STAGE_DESCRIPTORS[stage].optional)
    definitions = (
        ("select_option", "Select option", True, "Publish one selected option as a Draft."),
        (
            "custom_direction",
            "Custom direction",
            True,
            "Publish the user's exact direction as a Draft.",
        ),
        ("revise_options", "Revise options", False, "Ask the Specialist for revised options."),
        ("defer_topic", "Defer topic", True, "Keep this topic available for later guidance."),
        ("delegate_choice", "Delegate choice", True, "Let the Director choose one option."),
    )
    if optional:
        definitions = (
            definitions[:4]
            + (("exclude_element", "Exclude element", True, "Exclude this optional element."),)
            + definitions[4:]
        )
    return tuple(
        ProposalActionDescriptorV2(
            action_id=f"{action}:{proposal_id}:{expected_session_revision}",
            action=cast(str, action),
            label=label,
            proposal_id=proposal_id,
            expected_session_revision=expected_session_revision,
            confirmation_required=confirmation_required,
            reason=reason,
        )
        for action, label, confirmation_required, reason in definitions
    )


def _historical_proposal_action_descriptors(
    *,
    proposal_id: str,
    option_ids: tuple[str, ...],
    expected_session_revision: int,
) -> tuple[ProposalActionDescriptorV2, ...]:
    descriptors: list[ProposalActionDescriptorV2] = []
    for option_id in option_ids:
        for action, label, reason in (
            (
                "reuse_direction",
                "Use this direction",
                "Publish this historical direction as a new sibling Draft.",
            ),
            (
                "revise_direction",
                "Revise this direction",
                "Ask the owning Specialist to revise this historical direction.",
            ),
        ):
            descriptors.append(
                ProposalActionDescriptorV2(
                    action_id=(f"{action}:{proposal_id}:{option_id}:{expected_session_revision}"),
                    action=cast(str, action),
                    label=label,
                    proposal_id=proposal_id,
                    option_id=option_id,
                    expected_session_revision=expected_session_revision,
                    confirmation_required=False,
                    reason=reason,
                )
            )
    return tuple(descriptors)


def _guidance_session(
    connection: Connection,
    row: RowMapping,
) -> GuidedSessionStateV2:
    topic_rows = (
        connection.execute(
            select(AgentCanvasGuidanceTopicRow)
            .where(AgentCanvasGuidanceTopicRow.session_id == row["session_id"])
            .order_by(
                AgentCanvasGuidanceTopicRow.created_at.asc(),
                AgentCanvasGuidanceTopicRow.topic_id.asc(),
            )
        )
        .mappings()
        .all()
    )
    interaction_row = (
        connection.execute(
            select(AgentCanvasGuidedInteractionRow)
            .where(
                AgentCanvasGuidedInteractionRow.workflow_id == row["workflow_id"],
                AgentCanvasGuidedInteractionRow.status == "open",
            )
            .order_by(
                AgentCanvasGuidedInteractionRow.updated_at.desc(),
                AgentCanvasGuidedInteractionRow.interaction_id.asc(),
            )
        )
        .mappings()
        .first()
    )
    awaiting_row = (
        connection.execute(
            select(AgentCanvasGuidanceAwaitingRow).where(
                AgentCanvasGuidanceAwaitingRow.workflow_id == row["workflow_id"]
            )
        )
        .mappings()
        .one_or_none()
    )
    journey = parse_production_journey(str(row["journey_state_json"]))
    awaiting = (
        guidance_awaiting_from_row(awaiting_row)
        if awaiting_row is not None
        else _derive_historical_manual_awaiting(connection, row, journey)
    )
    return GuidedSessionStateV2(
        session_id=str(row["session_id"]),
        workflow_id=str(row["workflow_id"]),
        status=cast(str, row["status"]),
        response_locale=str(row["response_locale"]),
        goal=CreativeGoalV2.model_validate_json(str(row["creative_goal_json"])),
        creative_authority=(
            CreativeAuthorityStateV2.model_validate_json(str(row["creative_authority_json"]))
            if row["creative_authority_json"] is not None
            else None
        ),
        current_checkpoint=(
            GuidedStepCheckpointV2.model_validate_json(str(row["current_checkpoint_json"]))
            if row["current_checkpoint_json"] is not None
            else None
        ),
        narrative_direction=(
            str(row["narrative_direction"]) if row["narrative_direction"] is not None else None
        ),
        element_decisions=tuple(
            CreativeElementDecisionV2.model_validate(item)
            for item in json.loads(str(row["element_decisions_json"]))
        ),
        current_topic_id=(
            str(row["current_topic_id"]) if row["current_topic_id"] is not None else None
        ),
        topics=tuple(
            GuidanceTopicStateV2(
                topic_id=str(topic["topic_id"]),
                topic_kind=canonical_guidance_topic_kind(str(topic["topic_kind"])),
                title=str(topic["title"]),
                status=cast(str, topic["status"]),
                capability_id=cast(str, topic["capability_id"]),
                related_node_ids=tuple(
                    str(item) for item in json.loads(str(topic["related_node_ids_json"]))
                ),
                source_proposal_id=(
                    str(topic["source_proposal_id"])
                    if topic["source_proposal_id"] is not None
                    else None
                ),
                revision=int(topic["revision"]),
            )
            for topic in topic_rows
        ),
        active_proposal_id=(
            str(row["active_proposal_id"]) if row["active_proposal_id"] is not None else None
        ),
        active_style_skill_run_id=(
            str(row["active_style_skill_run_id"])
            if row["active_style_skill_run_id"] is not None
            else None
        ),
        completion=GuidanceCompletionProjectionV2.model_validate_json(str(row["completion_json"])),
        interaction=(
            guided_interaction_from_row(interaction_row) if interaction_row is not None else None
        ),
        awaiting=awaiting,
        journey=journey,
        revision=int(row["revision"]),
        updated_at=str(row["updated_at"]),
    )


def guidance_session_from_row(
    connection: Connection,
    row: RowMapping,
) -> GuidedSessionStateV2:
    """Build one Guidance session through a caller-owned transaction."""

    return _guidance_session(connection, row)


def _derive_historical_manual_awaiting(
    connection: Connection,
    session_row: RowMapping,
    journey: GuidedProductionJourneyV2,
) -> GuidanceAwaitingV2 | None:
    if journey.stage_status != "waiting_user":
        return None
    node_rows = (
        connection.execute(
            select(AgentCanvasNodeRow).where(
                AgentCanvasNodeRow.workflow_id == session_row["workflow_id"],
                AgentCanvasNodeRow.status == "draft",
                AgentCanvasNodeRow.node_type.in_(("image", "video", "audio")),
            )
        )
        .mappings()
        .all()
    )
    matched: list[tuple[RowMapping, GuidedCheckpointOriginV1]] = []
    for node_row in node_rows:
        metadata = json.loads(str(node_row["metadata_json"]))
        raw_origin = metadata.get("guided_checkpoint")
        if not isinstance(raw_origin, dict):
            continue
        origin = GuidedCheckpointOriginV1.model_validate(raw_origin)
        if (
            origin.guidance_session_id == session_row["session_id"]
            and origin.stage_revision == journey.stage_revision
        ):
            matched.append((node_row, origin))
    if not matched:
        return None
    checkpoint_ids = {origin.checkpoint_id for _, origin in matched}
    if len(checkpoint_ids) != 1:
        raise _error(
            "guidance_awaiting_conflict",
            "Historical waiting Nodes disagree on their Guidance checkpoint.",
        )
    checkpoint_id = checkpoint_ids.pop()
    identity = hashlib.sha256(
        f"{session_row['workflow_id']}:{checkpoint_id}".encode("utf-8")
    ).hexdigest()[:32]
    return GuidanceAwaitingV2(
        awaiting_id=f"derived_awaiting_{identity}",
        workflow_id=str(session_row["workflow_id"]),
        session_id=str(session_row["session_id"]),
        checkpoint_id=checkpoint_id,
        kind="manual_node_run",
        requires_user_action=True,
        resume_policy="node_terminal",
        node_ids=tuple(sorted(str(node_row["node_id"]) for node_row, _ in matched)),
        stage=journey.stage,
        stage_revision=journey.stage_revision,
        created_at=min(str(node_row["created_at"]) for node_row, _ in matched),
    )


def _require_guidance_session_row(
    connection: Connection,
    session_id: str,
) -> RowMapping:
    row = (
        connection.execute(
            select(AgentCanvasGuidanceSessionRow).where(
                AgentCanvasGuidanceSessionRow.session_id == session_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _error("guidance_session_not_found", "Guidance session was not found.")
    return row


def _require_guidance_session_row_by_workflow(
    connection: Connection,
    workflow_id: str,
) -> RowMapping:
    row = (
        connection.execute(
            select(AgentCanvasGuidanceSessionRow).where(
                AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _error("guidance_session_not_found", "Guidance session was not found.")
    return row


def _require_guidance_revision(row: RowMapping, expected_revision: int) -> None:
    if int(row["revision"]) != expected_revision:
        raise _error("guidance_revision_conflict", "Guidance session revision is stale.")


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_style_activation_idempotency(
    connection: Connection,
    *,
    idempotency_key: str,
    request_fingerprint: str,
) -> str | None:
    row = (
        connection.execute(
            select(
                AgentCanvasIdempotencyRow.request_fingerprint,
                AgentCanvasIdempotencyRow.response_json,
            ).where(
                AgentCanvasIdempotencyRow.operation == "activate_style_skill",
                AgentCanvasIdempotencyRow.idempotency_key == idempotency_key,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    if str(row["request_fingerprint"]) != request_fingerprint:
        raise _error(
            "idempotency_conflict",
            "Idempotency key was reused with a different request.",
        )
    return str(row["response_json"])


def _store_style_activation_idempotency(
    connection: Connection,
    *,
    idempotency_key: str,
    request_fingerprint: str,
    response_json: str,
    created_at: str,
) -> None:
    connection.execute(
        insert(AgentCanvasIdempotencyRow).values(
            record_id=f"idem_{uuid4().hex}",
            operation="activate_style_skill",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            response_json=response_json,
            created_at=created_at,
        )
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_conversation_repository")
