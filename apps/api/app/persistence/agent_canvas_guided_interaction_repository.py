"""SQLite authority for guided interactions and durable awaiting state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal, Mapping, cast

from pydantic import TypeAdapter
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.models import (
    AgentCanvasActionReceiptRow,
    AgentCanvasConceptProposalRow,
    AgentCanvasGuidanceAwaitingRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasGuidanceTopicRow,
    AgentCanvasGuidedInteractionRow,
    AgentCanvasGuidedInteractionSubmissionRow,
    AgentCanvasWorkflowRow,
)
from app.schemas.agent_canvas_conversation import AgentActionReceiptV2
from app.schemas.agent_canvas_creative_session import (
    CreativeElementDecisionV2,
    CreativeGoalV2,
    canonical_guidance_topic_kind,
)
from app.schemas.agent_canvas_guided_interactions import (
    GuidanceAwaitingResumeProofV1,
    GuidanceAwaitingV1,
    GuidedConceptChoiceV1,
    GuidedConceptSubmitV1,
    GuidedInteractionSubmissionRecordV1,
    GuidedInteractionSubmitRequestV1,
    GuidedInteractionV1,
    GuidedCustomAnswerV1,
    GuidedQuestionAnswerV1,
    GuidedQuestionnaireSubmitV1,
    GuidedQuestionnaireV1,
    GuidedMediaReviewSubmitV1,
    GuidedSkipAnswerV1,
    GuidedInteractionAcceptedV1,
)
from app.schemas.agent_canvas_production_journey import (
    GuidedProductionJourneyV1,
    JourneyElementDecisionV1,
    JourneyEvidenceV1,
    JourneyPolicyContextV1,
)
from app.schemas.agent_canvas_requirements import (
    RequirementDirectiveV1,
    RequirementElementPresenceV1,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_production_journey import (
    GuidedProductionJourneyPolicyService,
)
from app.services.agent_canvas_requirement_directives import (
    canonicalize_requirement_directives,
)
from app.services.agent_canvas_requirements import (
    update_requirement_compatibility_projection_in_transaction,
)


class AgentCanvasGuidedInteractionRepository:
    """Persist one current interaction and awaiting descriptor per workflow."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        self._database = database
        self._events = events

    @property
    def database(self) -> V2Database:
        return self._database

    def open_with_awaiting(
        self,
        interaction: GuidedInteractionV1,
        awaiting: GuidanceAwaitingV1,
    ) -> GuidedInteractionV1:
        self._validate_pair(interaction, awaiting)
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    existing_row = (
                        connection.execute(
                            select(AgentCanvasGuidedInteractionRow).where(
                                AgentCanvasGuidedInteractionRow.interaction_id
                                == interaction.interaction_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing_row is not None:
                        existing = guided_interaction_from_row(existing_row)
                        persisted_awaiting = _awaiting_for_workflow(
                            connection, interaction.workflow_id
                        )
                        if existing != interaction or persisted_awaiting != awaiting:
                            raise _error(
                                "guided_interaction_conflict",
                                "Guided interaction identity was reused with different content.",
                            )
                        connection.rollback()
                        return existing

                    competing = (
                        connection.execute(
                            select(AgentCanvasGuidedInteractionRow.interaction_id).where(
                                AgentCanvasGuidedInteractionRow.workflow_id
                                == interaction.workflow_id,
                                AgentCanvasGuidedInteractionRow.session_id
                                == interaction.session_id,
                                AgentCanvasGuidedInteractionRow.checkpoint_id
                                == interaction.checkpoint_id,
                                AgentCanvasGuidedInteractionRow.status == "open",
                            )
                        )
                        .scalars()
                        .one_or_none()
                    )
                    if competing is not None:
                        raise _error(
                            "guided_interaction_conflict",
                            "Another guided interaction is open for this checkpoint.",
                        )
                    session = (
                        connection.execute(
                            select(AgentCanvasGuidanceSessionRow).where(
                                AgentCanvasGuidanceSessionRow.session_id == interaction.session_id,
                                AgentCanvasGuidanceSessionRow.workflow_id
                                == interaction.workflow_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if session is None:
                        raise _error(
                            "guided_interaction_not_found",
                            "The Guidance session for this interaction was not found.",
                        )
                    if int(session["revision"]) != interaction.expected_session_revision:
                        raise _error(
                            "guidance_revision_conflict",
                            "Guidance session changed before the interaction opened.",
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
                            created_at=interaction.created_at.isoformat(),
                            updated_at=interaction.updated_at.isoformat(),
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
                            node_ids_json=_dump(list(awaiting.node_ids)),
                            stage=awaiting.stage,
                            stage_revision=awaiting.stage_revision,
                            created_at=awaiting.created_at.isoformat(),
                        )
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=interaction.workflow_id,
                            event_type="guided_interaction_opened",
                            transition_key=f"guided-interaction:{interaction.interaction_id}:opened",
                            action_id=interaction.interaction_id,
                            created_at=interaction.created_at.isoformat(),
                            payload={
                                "interaction_id": interaction.interaction_id,
                                "session_id": interaction.session_id,
                                "checkpoint_id": interaction.checkpoint_id,
                                "kind": interaction.kind,
                                "interaction_revision": interaction.revision,
                            },
                        ),
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=awaiting.workflow_id,
                            event_type="guidance_awaiting_entered",
                            transition_key=f"guidance-awaiting:{awaiting.awaiting_id}:entered",
                            action_id=interaction.interaction_id,
                            created_at=awaiting.created_at.isoformat(),
                            payload={
                                "awaiting_id": awaiting.awaiting_id,
                                "session_id": awaiting.session_id,
                                "checkpoint_id": awaiting.checkpoint_id,
                                "kind": awaiting.kind,
                                "resume_policy": awaiting.resume_policy,
                                "interaction_id": awaiting.interaction_id,
                                "node_ids": list(awaiting.node_ids),
                            },
                        ),
                    )
                    connection.commit()
                    return interaction
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _error(
                "guided_interaction_conflict",
                "Guided interaction authority conflicts with current state.",
            ) from error
        except SQLAlchemyError as error:
            raise _error(
                "guided_interaction_persistence_unavailable",
                "Guided interaction storage failed.",
            ) from error

    def get(self, interaction_id: str) -> GuidedInteractionV1:
        with self._database.engine.connect() as connection:
            row = (
                connection.execute(
                    select(AgentCanvasGuidedInteractionRow).where(
                        AgentCanvasGuidedInteractionRow.interaction_id == interaction_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise _error(
                "guided_interaction_not_found",
                "Guided interaction was not found.",
            )
        return guided_interaction_from_row(row)

    def get_current(self, workflow_id: str) -> GuidedInteractionV1 | None:
        with self._database.engine.connect() as connection:
            row = (
                connection.execute(
                    select(AgentCanvasGuidedInteractionRow)
                    .where(
                        AgentCanvasGuidedInteractionRow.workflow_id == workflow_id,
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
        return guided_interaction_from_row(row) if row is not None else None

    def get_awaiting(self, workflow_id: str) -> GuidanceAwaitingV1 | None:
        with self._database.engine.connect() as connection:
            return _awaiting_for_workflow(connection, workflow_id)

    def get_submission(self, submission_id: str) -> GuidedInteractionSubmissionRecordV1:
        with self._database.engine.connect() as connection:
            row = (
                connection.execute(
                    select(AgentCanvasGuidedInteractionSubmissionRow).where(
                        AgentCanvasGuidedInteractionSubmissionRow.submission_id == submission_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise _error(
                "guided_interaction_submission_not_found",
                "Guided interaction submission was not found.",
            )
        return GuidedInteractionSubmissionRecordV1(
            submission_id=str(row["submission_id"]),
            workflow_id=str(row["workflow_id"]),
            interaction_id=str(row["interaction_id"]),
            idempotency_key=str(row["idempotency_key"]),
            request=TypeAdapter(GuidedInteractionSubmitRequestV1).validate_json(
                str(row["request_json"])
            ),
            result=(
                json.loads(str(row["result_json"])) if row["result_json"] is not None else None
            ),
            created_at=str(row["created_at"]),
        )

    def get_submission_or_none(
        self,
        submission_id: str,
    ) -> GuidedInteractionSubmissionRecordV1 | None:
        try:
            return self.get_submission(submission_id)
        except V2PersistenceError as error:
            if error.code == "guided_interaction_submission_not_found":
                return None
            raise

    def get_submission_by_idempotency_key(
        self,
        workflow_id: str,
        idempotency_key: str,
    ) -> GuidedInteractionSubmissionRecordV1 | None:
        with self._database.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(AgentCanvasGuidedInteractionSubmissionRow).where(
                        AgentCanvasGuidedInteractionSubmissionRow.workflow_id == workflow_id,
                        AgentCanvasGuidedInteractionSubmissionRow.idempotency_key
                        == idempotency_key,
                    )
                )
                .mappings()
                .all()
            )
        if not rows:
            return None
        if len(rows) != 1:
            raise _error(
                "idempotency_conflict",
                "Idempotency key was reused for multiple guided interactions.",
            )
        row = rows[0]
        return GuidedInteractionSubmissionRecordV1(
            submission_id=str(row["submission_id"]),
            workflow_id=str(row["workflow_id"]),
            interaction_id=str(row["interaction_id"]),
            idempotency_key=str(row["idempotency_key"]),
            request=TypeAdapter(GuidedInteractionSubmitRequestV1).validate_json(
                str(row["request_json"])
            ),
            result=(
                json.loads(str(row["result_json"])) if row["result_json"] is not None else None
            ),
            created_at=str(row["created_at"]),
        )

    def submit_questionnaire(
        self,
        interaction: GuidedInteractionV1,
        request: GuidedQuestionnaireSubmitV1,
        *,
        submission_id: str,
        idempotency_key: str,
    ) -> GuidedInteractionAcceptedV1:
        if not isinstance(interaction.content, GuidedQuestionnaireV1):
            raise _error(
                "guided_interaction_action_not_allowed",
                "This guided interaction is not a questionnaire.",
            )
        directives = _questionnaire_directives(
            interaction,
            request,
            submission_id=submission_id,
        )
        request_json = request.model_dump_json()
        request_digest = sha256(request_json.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        requirements = AgentCanvasRequirementRepository(self._database)
        policy = GuidedProductionJourneyPolicyService()
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                existing = (
                    connection.execute(
                        select(AgentCanvasGuidedInteractionSubmissionRow).where(
                            AgentCanvasGuidedInteractionSubmissionRow.submission_id == submission_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if str(existing["request_digest"]) != request_digest:
                        raise _error(
                            "guided_interaction_submission_conflict",
                            "Submission identity was reused with different answers.",
                        )
                    connection.rollback()
                    result = GuidedInteractionAcceptedV1.model_validate_json(
                        str(existing["result_json"])
                    )
                    return result.model_copy(update={"replayed": True})
                row = (
                    connection.execute(
                        select(AgentCanvasGuidedInteractionRow).where(
                            AgentCanvasGuidedInteractionRow.interaction_id
                            == interaction.interaction_id,
                            AgentCanvasGuidedInteractionRow.workflow_id == interaction.workflow_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    row is None
                    or str(row["status"]) != "open"
                    or int(row["revision"]) != request.expected_interaction_revision
                ):
                    raise _error(
                        "guided_interaction_stale",
                        "Guided interaction changed before Submit.",
                    )
                session = _require_session(
                    connection,
                    workflow_id=interaction.workflow_id,
                    session_id=interaction.session_id,
                    expected_revision=request.expected_session_revision,
                )
                awaiting = _awaiting_for_workflow(connection, interaction.workflow_id)
                if (
                    awaiting is None
                    or awaiting.interaction_id != interaction.interaction_id
                    or awaiting.kind != "clarification"
                ):
                    raise _error(
                        "guidance_resume_evidence_missing",
                        "Questionnaire Submit does not match current awaiting authority.",
                    )
                requirement_head = requirements.get_current_in_transaction(
                    connection,
                    interaction.workflow_id,
                )
                revision_no = requirement_head.revision_no + 1
                stored = tuple(
                    directive.model_copy(update={"created_revision_no": revision_no})
                    for directive in directives
                )
                canonical = canonicalize_requirement_directives(
                    requirement_head.ledger.active_directives,
                    stored,
                )
                next_ledger = requirement_head.ledger.model_copy(
                    update={
                        "active_directives": canonical.active_directives,
                        "unresolved_conflicts": (),
                    }
                )
                requirement_revision = requirements.append_in_transaction(
                    connection,
                    workflow_id=interaction.workflow_id,
                    expected_revision_no=requirement_head.revision_no,
                    next_ledger=next_ledger,
                    source_kind="decision_bundle_answer",
                    source_bundle_id=interaction.interaction_id,
                    created_at=now,
                )
                update_requirement_compatibility_projection_in_transaction(
                    connection,
                    interaction.workflow_id,
                    requirement_revision.ledger,
                    now,
                    advance_session_revision=False,
                )
                journey = _journey(session)
                next_journey = policy.apply_evidence(
                    JourneyPolicyContextV1(
                        journey=journey,
                        element_decisions=tuple(
                            JourneyElementDecisionV1.model_validate(item)
                            for item in json.loads(str(session["element_decisions_json"]))
                        ),
                    ),
                    JourneyEvidenceV1(
                        evidence_id=f"questionnaire-submitted:{submission_id}",
                        evidence_kind="clarification_completed",
                        source_id=submission_id,
                        source_revision=requirement_revision.revision_no,
                    ),
                )
                next_session_revision = request.expected_session_revision + 1
                connection.execute(
                    update(AgentCanvasGuidedInteractionRow)
                    .where(
                        AgentCanvasGuidedInteractionRow.interaction_id
                        == interaction.interaction_id,
                        AgentCanvasGuidedInteractionRow.status == "open",
                    )
                    .values(
                        status="closed",
                        revision=interaction.revision + 1,
                        updated_at=now,
                    )
                )
                connection.execute(
                    delete(AgentCanvasGuidanceAwaitingRow).where(
                        AgentCanvasGuidanceAwaitingRow.awaiting_id == awaiting.awaiting_id
                    )
                )
                updated_session = connection.execute(
                    update(AgentCanvasGuidanceSessionRow)
                    .where(
                        AgentCanvasGuidanceSessionRow.session_id == interaction.session_id,
                        AgentCanvasGuidanceSessionRow.revision == request.expected_session_revision,
                    )
                    .values(
                        journey_state_json=next_journey.model_dump_json(),
                        revision=next_session_revision,
                        updated_at=now,
                    )
                )
                if updated_session.rowcount != 1:
                    raise _error(
                        "guidance_revision_conflict",
                        "Guidance session changed before questionnaire Submit.",
                    )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=interaction.workflow_id,
                        event_type="guided_interaction_submitted",
                        transition_key=f"guided-submission:{submission_id}:submitted",
                        action_id=interaction.interaction_id,
                        created_at=now,
                        payload={
                            "interaction_id": interaction.interaction_id,
                            "submission_id": submission_id,
                            "kind": interaction.kind,
                            "answer_count": len(request.answers),
                        },
                    ),
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=interaction.workflow_id,
                        event_type="requirement_ledger_updated",
                        transition_key=f"guided-submission:{submission_id}:requirements",
                        action_id=interaction.interaction_id,
                        created_at=now,
                        payload={
                            "revision_id": requirement_revision.revision_id,
                            "revision_no": requirement_revision.revision_no,
                            "digest": requirement_revision.digest,
                            "source_kind": "decision_bundle_answer",
                            "added_directive_ids": list(canonical.added_directive_ids),
                            "refresh": ["requirements"],
                        },
                    ),
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=interaction.workflow_id,
                        event_type="guidance_awaiting_resumed",
                        transition_key=f"guidance-awaiting:{awaiting.awaiting_id}:resumed",
                        action_id=interaction.interaction_id,
                        created_at=now,
                        payload={
                            "awaiting_id": awaiting.awaiting_id,
                            "checkpoint_id": awaiting.checkpoint_id,
                            "kind": awaiting.kind,
                            "resume_policy": awaiting.resume_policy,
                            "resume_evidence": "submit_interaction",
                            "interaction_id": interaction.interaction_id,
                        },
                    ),
                )
                final_event = self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=interaction.workflow_id,
                        event_type="journey_stage_changed",
                        transition_key=f"guided-submission:{submission_id}:journey",
                        action_id=interaction.interaction_id,
                        created_at=now,
                        payload={
                            "previous_stage": journey.stage,
                            "next_stage": next_journey.stage,
                            "stage_revision": next_journey.stage_revision,
                            "source_submission_id": submission_id,
                        },
                    ),
                )
                accepted = GuidedInteractionAcceptedV1(
                    workflow_id=interaction.workflow_id,
                    interaction_id=interaction.interaction_id,
                    submission_id=submission_id,
                    receipt_id=f"receipt_{submission_id}",
                    resulting_session_revision=next_session_revision,
                    events_cursor=final_event.seq,
                )
                connection.execute(
                    insert(AgentCanvasGuidedInteractionSubmissionRow).values(
                        submission_id=submission_id,
                        workflow_id=interaction.workflow_id,
                        interaction_id=interaction.interaction_id,
                        idempotency_key=idempotency_key,
                        request_digest=request_digest,
                        request_json=request_json,
                        result_json=accepted.model_dump_json(),
                        created_at=now,
                    )
                )
                connection.commit()
                return accepted
            except BaseException:
                connection.rollback()
                raise

    def submit_concept_state_action(
        self,
        interaction: GuidedInteractionV1,
        request: GuidedConceptSubmitV1,
        *,
        submission_id: str,
        idempotency_key: str,
        action_id: str,
        proposal_action: Literal["defer_topic", "exclude_element"],
    ) -> GuidedInteractionAcceptedV1:
        """Apply a non-materializing concept action without an Agent action Turn."""

        if not isinstance(interaction.content, GuidedConceptChoiceV1):
            raise _error(
                "guided_interaction_action_not_allowed",
                "This guided interaction is not a concept choice.",
            )
        request_json = request.model_dump_json()
        request_digest = sha256(request_json.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        requirements = AgentCanvasRequirementRepository(self._database)
        policy = GuidedProductionJourneyPolicyService()
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                existing = _submission_row(connection, submission_id)
                if existing is not None:
                    if str(existing["request_digest"]) != request_digest:
                        raise _error(
                            "guided_interaction_submission_conflict",
                            "Submission identity was reused with different content.",
                        )
                    connection.rollback()
                    result = GuidedInteractionAcceptedV1.model_validate_json(
                        str(existing["result_json"])
                    )
                    return result.model_copy(update={"replayed": True})
                _require_open_interaction(connection, interaction, request)
                session = _require_session(
                    connection,
                    workflow_id=interaction.workflow_id,
                    session_id=interaction.session_id,
                    expected_revision=request.expected_session_revision,
                )
                awaiting = _awaiting_for_workflow(connection, interaction.workflow_id)
                if (
                    awaiting is None
                    or awaiting.interaction_id != interaction.interaction_id
                    or awaiting.kind != "concept_selection"
                ):
                    raise _error(
                        "guidance_resume_evidence_missing",
                        "Concept Submit does not match current awaiting authority.",
                    )
                proposal = (
                    connection.execute(
                        select(AgentCanvasConceptProposalRow).where(
                            AgentCanvasConceptProposalRow.proposal_id
                            == interaction.content.proposal_id,
                            AgentCanvasConceptProposalRow.workflow_id == interaction.workflow_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if proposal is None or str(proposal["availability"]) != "open":
                    raise _error("guided_interaction_stale", "Concept Proposal is not current.")
                if str(session["active_proposal_id"]) != str(proposal["proposal_id"]):
                    raise _error("guided_interaction_stale", "Concept Proposal is not current.")
                topic = (
                    connection.execute(
                        select(AgentCanvasGuidanceTopicRow).where(
                            AgentCanvasGuidanceTopicRow.session_id == interaction.session_id,
                            AgentCanvasGuidanceTopicRow.topic_id == proposal["topic_id"],
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if topic is None:
                    raise _error("guidance_topic_not_found", "Guidance topic was not found.")
                if proposal_action == "defer_topic" and str(topic["status"]) != "proposed":
                    raise _error(
                        "guided_interaction_stale",
                        "Guidance topic is no longer available for deferral.",
                    )
                topic_kind = canonical_guidance_topic_kind(str(topic["topic_kind"]))
                goal = CreativeGoalV2.model_validate_json(str(session["creative_goal_json"]))
                if proposal_action == "exclude_element" and topic_kind == goal.requested_output:
                    raise _error(
                        "guided_interaction_action_not_allowed",
                        "The requested output cannot be excluded.",
                    )

                element_decisions = tuple(
                    CreativeElementDecisionV2.model_validate(item)
                    for item in json.loads(str(session["element_decisions_json"]))
                )
                if proposal_action == "exclude_element":
                    requirement_head = requirements.get_current_in_transaction(
                        connection,
                        interaction.workflow_id,
                    )
                    next_requirement_revision = requirement_head.revision_no + 1
                    presence = RequirementElementPresenceV1(
                        element_kind=cast(str, topic_kind),
                        presence="exclude",
                        source_kind="decision_bundle_answer",
                        source_bundle_id=interaction.interaction_id,
                        source_text="Exclude this creative element.",
                        created_revision_no=next_requirement_revision,
                    )
                    next_ledger = requirement_head.ledger.model_copy(
                        update={
                            "element_presence": tuple(
                                item
                                for item in requirement_head.ledger.element_presence
                                if item.element_kind != topic_kind
                            )
                            + (presence,),
                            "unresolved_conflicts": (),
                        }
                    )
                    requirement_revision = requirements.append_in_transaction(
                        connection,
                        workflow_id=interaction.workflow_id,
                        expected_revision_no=requirement_head.revision_no,
                        next_ledger=next_ledger,
                        source_kind="decision_bundle_answer",
                        source_bundle_id=interaction.interaction_id,
                        created_at=now,
                    )
                    update_requirement_compatibility_projection_in_transaction(
                        connection,
                        interaction.workflow_id,
                        requirement_revision.ledger,
                        now,
                        advance_session_revision=False,
                    )
                    element_decisions = tuple(
                        item for item in element_decisions if item.element_kind != topic_kind
                    ) + (
                        CreativeElementDecisionV2(
                            element_kind=cast(str, topic_kind),
                            presence="exclude",
                            authority="user",
                            requirements={},
                            source="explicit_user",
                        ),
                    )

                next_journey = _journey_after_state_action(
                    policy,
                    _journey(session),
                    element_decisions,
                    proposal_action,
                    submission_id=submission_id,
                )
                topic_status = "deferred" if proposal_action == "defer_topic" else "excluded"
                connection.execute(
                    update(AgentCanvasGuidanceTopicRow)
                    .where(
                        AgentCanvasGuidanceTopicRow.session_id == interaction.session_id,
                        AgentCanvasGuidanceTopicRow.topic_id == proposal["topic_id"],
                    )
                    .values(
                        status=topic_status,
                        source_proposal_id=proposal["proposal_id"],
                        revision=int(topic["revision"]) + 1,
                        updated_at=now,
                    )
                )
                connection.execute(
                    update(AgentCanvasConceptProposalRow)
                    .where(AgentCanvasConceptProposalRow.proposal_id == proposal["proposal_id"])
                    .values(
                        availability=(
                            "superseded" if proposal_action == "defer_topic" else "applied"
                        ),
                        updated_at=now,
                    )
                )
                _close_interaction_and_awaiting(
                    connection,
                    interaction,
                    awaiting,
                    updated_at=now,
                )
                next_session_revision = request.expected_session_revision + 1
                updated_session = connection.execute(
                    update(AgentCanvasGuidanceSessionRow)
                    .where(
                        AgentCanvasGuidanceSessionRow.session_id == interaction.session_id,
                        AgentCanvasGuidanceSessionRow.revision == request.expected_session_revision,
                    )
                    .values(
                        element_decisions_json=_dump(
                            [item.model_dump(mode="json") for item in element_decisions]
                        ),
                        current_topic_id=None,
                        active_proposal_id=None,
                        journey_state_json=next_journey.model_dump_json(),
                        revision=next_session_revision,
                        updated_at=now,
                    )
                )
                if updated_session.rowcount != 1:
                    raise _error(
                        "guidance_revision_conflict",
                        "Guidance session changed before concept Submit.",
                    )
                workflow_revision = int(
                    connection.execute(
                        select(AgentCanvasWorkflowRow.revision).where(
                            AgentCanvasWorkflowRow.workflow_id == interaction.workflow_id
                        )
                    ).scalar_one()
                )
                summary = (
                    "The topic was deferred."
                    if proposal_action == "defer_topic"
                    else "The creative element was excluded."
                )
                receipt_id = f"receipt_{submission_id}"
                receipt = AgentActionReceiptV2(
                    receipt_id=receipt_id,
                    workflow_id=interaction.workflow_id,
                    action_id=action_id,
                    proposal_id=str(proposal["proposal_id"]),
                    proposal_action=proposal_action,
                    actor_kind="user",
                    idempotency_key=idempotency_key,
                    status="applied",
                    summary=summary,
                    workflow_revision=workflow_revision,
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
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=interaction.workflow_id,
                        event_type="guided_interaction_submitted",
                        transition_key=f"guided-submission:{submission_id}:submitted",
                        action_id=action_id,
                        created_at=now,
                        payload={
                            "interaction_id": interaction.interaction_id,
                            "submission_id": submission_id,
                            "kind": interaction.kind,
                            "action": request.action,
                        },
                    ),
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=interaction.workflow_id,
                        event_type="guidance_awaiting_resumed",
                        transition_key=f"guidance-awaiting:{awaiting.awaiting_id}:resumed",
                        action_id=action_id,
                        created_at=now,
                        payload={
                            "awaiting_id": awaiting.awaiting_id,
                            "checkpoint_id": awaiting.checkpoint_id,
                            "kind": awaiting.kind,
                            "resume_policy": awaiting.resume_policy,
                            "resume_evidence": "submit_interaction",
                            "interaction_id": interaction.interaction_id,
                        },
                    ),
                )
                final_event = self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=interaction.workflow_id,
                        event_type="guidance_state_updated",
                        transition_key=f"guided-submission:{submission_id}:state",
                        action_id=action_id,
                        created_at=now,
                        payload={
                            "session_id": interaction.session_id,
                            "session_revision": next_session_revision,
                            "proposal_id": proposal["proposal_id"],
                            "topic_id": proposal["topic_id"],
                            "action": proposal_action,
                            "refresh": ["conversation", "requirements"],
                        },
                    ),
                )
                accepted = GuidedInteractionAcceptedV1(
                    workflow_id=interaction.workflow_id,
                    interaction_id=interaction.interaction_id,
                    submission_id=submission_id,
                    receipt_id=receipt_id,
                    resulting_session_revision=next_session_revision,
                    events_cursor=final_event.seq,
                )
                connection.execute(
                    insert(AgentCanvasGuidedInteractionSubmissionRow).values(
                        submission_id=submission_id,
                        workflow_id=interaction.workflow_id,
                        interaction_id=interaction.interaction_id,
                        idempotency_key=idempotency_key,
                        request_digest=request_digest,
                        request_json=request_json,
                        result_json=accepted.model_dump_json(),
                        created_at=now,
                    )
                )
                connection.commit()
                return accepted
            except BaseException:
                connection.rollback()
                raise

    def enter_awaiting(
        self,
        awaiting: GuidanceAwaitingV1,
        *,
        expected_session_revision: int,
    ) -> GuidanceAwaitingV1:
        if awaiting.interaction_id is not None:
            raise _error(
                "guidance_awaiting_conflict",
                "Interaction waits must open with their guided interaction.",
            )
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                existing = _awaiting_for_workflow(connection, awaiting.workflow_id)
                if existing is not None:
                    if existing == awaiting:
                        connection.rollback()
                        return existing
                    raise _error(
                        "guidance_awaiting_conflict",
                        "Another Guidance wait is current for this Workflow.",
                    )
                session = _require_session(
                    connection,
                    workflow_id=awaiting.workflow_id,
                    session_id=awaiting.session_id,
                    expected_revision=expected_session_revision,
                )
                journey = _journey(session)
                if (
                    journey.stage != awaiting.stage
                    or journey.stage_revision != awaiting.stage_revision
                ):
                    raise _error(
                        "guidance_revision_conflict",
                        "Guidance checkpoint changed before entering the wait.",
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
                        interaction_id=None,
                        node_ids_json=_dump(list(awaiting.node_ids)),
                        stage=awaiting.stage,
                        stage_revision=awaiting.stage_revision,
                        created_at=awaiting.created_at.isoformat(),
                    )
                )
                connection.execute(
                    update(AgentCanvasGuidanceSessionRow)
                    .where(
                        AgentCanvasGuidanceSessionRow.session_id == awaiting.session_id,
                        AgentCanvasGuidanceSessionRow.revision == expected_session_revision,
                    )
                    .values(
                        journey_state_json=journey.model_copy(
                            update={"stage_status": "waiting_user"}
                        ).model_dump_json(),
                        revision=expected_session_revision + 1,
                        updated_at=awaiting.created_at.isoformat(),
                    )
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=awaiting.workflow_id,
                        event_type="guidance_awaiting_entered",
                        transition_key=f"guidance-awaiting:{awaiting.awaiting_id}:entered",
                        created_at=awaiting.created_at.isoformat(),
                        payload={
                            "awaiting_id": awaiting.awaiting_id,
                            "session_id": awaiting.session_id,
                            "checkpoint_id": awaiting.checkpoint_id,
                            "kind": awaiting.kind,
                            "resume_policy": awaiting.resume_policy,
                            "interaction_id": None,
                            "node_ids": list(awaiting.node_ids),
                        },
                    ),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return awaiting

    def submit_media_review(
        self,
        interaction: GuidedInteractionV1,
        request: GuidedMediaReviewSubmitV1,
        *,
        submission_id: str,
        idempotency_key: str,
        receipt_id: str,
        post_action_session_revision: int,
        created_node_ids: tuple[str, ...] = (),
        created_binding_ids: tuple[str, ...] = (),
        automatic_run_command_ids: tuple[str, ...] = (),
    ) -> GuidedInteractionAcceptedV1:
        """Close one exact media review after its deterministic action commits."""

        request_json = request.model_dump_json()
        request_digest = sha256(request_json.encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                existing = (
                    connection.execute(
                        select(AgentCanvasGuidedInteractionSubmissionRow).where(
                            AgentCanvasGuidedInteractionSubmissionRow.submission_id == submission_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if (
                        str(existing["request_digest"]) != request_digest
                        or str(existing["idempotency_key"]) != idempotency_key
                    ):
                        raise _error(
                            "guided_interaction_submission_conflict",
                            "Submission identity was reused with different content.",
                        )
                    result_json = cast(str | None, existing["result_json"])
                    if result_json is None:
                        raise _error(
                            "guided_interaction_incomplete",
                            "Media review submission has no durable result.",
                        )
                    connection.rollback()
                    return GuidedInteractionAcceptedV1.model_validate_json(result_json).model_copy(
                        update={"replayed": True}
                    )

                awaiting = _awaiting_for_workflow(connection, interaction.workflow_id)
                if (
                    awaiting is None
                    or awaiting.interaction_id != interaction.interaction_id
                    or awaiting.kind != "media_review"
                ):
                    raise _error(
                        "guided_interaction_stale",
                        "Media review is no longer the current Guidance wait.",
                    )
                _require_open_interaction(connection, interaction, request)
                session = _require_session(
                    connection,
                    workflow_id=interaction.workflow_id,
                    session_id=interaction.session_id,
                    expected_revision=post_action_session_revision,
                )
                next_session_revision = post_action_session_revision + 1
                journey = _journey(session).model_copy(
                    update={"stage_status": "working", "active_action": None}
                )
                _close_interaction_and_awaiting(
                    connection,
                    interaction,
                    awaiting,
                    updated_at=now,
                )
                changed = connection.execute(
                    update(AgentCanvasGuidanceSessionRow)
                    .where(
                        AgentCanvasGuidanceSessionRow.session_id == interaction.session_id,
                        AgentCanvasGuidanceSessionRow.revision == post_action_session_revision,
                    )
                    .values(
                        journey_state_json=journey.model_dump_json(),
                        revision=next_session_revision,
                        updated_at=now,
                    )
                )
                if changed.rowcount != 1:
                    raise _error(
                        "guidance_revision_conflict",
                        "Guidance session changed before media review Submit.",
                    )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=interaction.workflow_id,
                        node_id=interaction.content.node_id,
                        event_type="guided_interaction_submitted",
                        transition_key=f"guided-submission:{submission_id}:submitted",
                        action_id=submission_id,
                        created_at=now,
                        payload={
                            "interaction_id": interaction.interaction_id,
                            "submission_id": submission_id,
                            "kind": interaction.kind,
                            "action": request.action,
                            "receipt_id": receipt_id,
                        },
                    ),
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=interaction.workflow_id,
                        node_id=interaction.content.node_id,
                        event_type="guidance_awaiting_resumed",
                        transition_key=f"guidance-awaiting:{awaiting.awaiting_id}:resumed",
                        action_id=submission_id,
                        created_at=now,
                        payload={
                            "awaiting_id": awaiting.awaiting_id,
                            "checkpoint_id": awaiting.checkpoint_id,
                            "kind": awaiting.kind,
                            "resume_policy": awaiting.resume_policy,
                            "resume_evidence": "submit_interaction",
                            "interaction_id": interaction.interaction_id,
                        },
                    ),
                )
                final_event = self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=interaction.workflow_id,
                        node_id=interaction.content.node_id,
                        event_type="guidance_state_updated",
                        transition_key=f"guided-submission:{submission_id}:state",
                        action_id=submission_id,
                        created_at=now,
                        payload={
                            "session_id": interaction.session_id,
                            "session_revision": next_session_revision,
                            "action": request.action,
                            "refresh": ["conversation", "workflow", "runtime", "events"],
                        },
                    ),
                )
                accepted = GuidedInteractionAcceptedV1(
                    workflow_id=interaction.workflow_id,
                    interaction_id=interaction.interaction_id,
                    submission_id=submission_id,
                    receipt_id=receipt_id,
                    created_node_ids=created_node_ids,
                    created_binding_ids=created_binding_ids,
                    automatic_run_command_ids=automatic_run_command_ids,
                    resulting_session_revision=next_session_revision,
                    events_cursor=final_event.seq,
                )
                connection.execute(
                    insert(AgentCanvasGuidedInteractionSubmissionRow).values(
                        submission_id=submission_id,
                        workflow_id=interaction.workflow_id,
                        interaction_id=interaction.interaction_id,
                        idempotency_key=idempotency_key,
                        request_digest=request_digest,
                        request_json=request_json,
                        result_json=accepted.model_dump_json(),
                        created_at=now,
                    )
                )
                connection.commit()
                return accepted
            except BaseException:
                connection.rollback()
                raise

    def resume_awaiting(
        self,
        workflow_id: str,
        proof: GuidanceAwaitingResumeProofV1,
    ) -> None:
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                awaiting = _awaiting_for_workflow(connection, workflow_id)
                if awaiting is None or awaiting.awaiting_id != proof.awaiting_id:
                    raise _error(
                        "guidance_resume_evidence_missing",
                        "Current Guidance wait does not match the resume proof.",
                    )
                session = _require_session(
                    connection,
                    workflow_id=workflow_id,
                    session_id=awaiting.session_id,
                    expected_revision=proof.expected_session_revision,
                )
                _validate_resume_proof(awaiting, proof)
                journey = _journey(session)
                resumed_at = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    delete(AgentCanvasGuidanceAwaitingRow).where(
                        AgentCanvasGuidanceAwaitingRow.awaiting_id == awaiting.awaiting_id
                    )
                )
                connection.execute(
                    update(AgentCanvasGuidanceSessionRow)
                    .where(
                        AgentCanvasGuidanceSessionRow.session_id == awaiting.session_id,
                        AgentCanvasGuidanceSessionRow.revision == proof.expected_session_revision,
                    )
                    .values(
                        journey_state_json=journey.model_copy(
                            update={"stage_status": "working"}
                        ).model_dump_json(),
                        revision=proof.expected_session_revision + 1,
                        updated_at=resumed_at,
                    )
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        event_type="guidance_awaiting_resumed",
                        transition_key=f"guidance-awaiting:{awaiting.awaiting_id}:resumed",
                        created_at=resumed_at,
                        payload={
                            "awaiting_id": awaiting.awaiting_id,
                            "checkpoint_id": awaiting.checkpoint_id,
                            "kind": awaiting.kind,
                            "resume_policy": awaiting.resume_policy,
                            "resume_evidence": proof.evidence_kind,
                            "node_ids": list(proof.node_ids),
                            "source_turn_id": proof.source_turn_id,
                        },
                    ),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _validate_pair(
        interaction: GuidedInteractionV1,
        awaiting: GuidanceAwaitingV1,
    ) -> None:
        if interaction.status != "open" or (
            interaction.workflow_id,
            interaction.session_id,
            interaction.checkpoint_id,
            interaction.interaction_id,
        ) != (
            awaiting.workflow_id,
            awaiting.session_id,
            awaiting.checkpoint_id,
            awaiting.interaction_id,
        ):
            raise _error(
                "guided_interaction_invalid",
                "Guided interaction and awaiting authority do not match.",
            )
        expected_awaiting_kind = {
            "clarification_questionnaire": "clarification",
            "concept_choice": "concept_selection",
            "media_review": "media_review",
        }[interaction.kind]
        if awaiting.kind != expected_awaiting_kind:
            raise _error(
                "guided_interaction_invalid",
                "Guided interaction kind does not match its awaiting authority.",
            )


def guided_interaction_from_row(row: Mapping[str, object]) -> GuidedInteractionV1:
    return GuidedInteractionV1.model_validate(
        {
            "interaction_id": row["interaction_id"],
            "workflow_id": row["workflow_id"],
            "session_id": row["session_id"],
            "checkpoint_id": row["checkpoint_id"],
            "kind": row["kind"],
            "status": row["status"],
            "response_locale": row["response_locale"],
            "expected_session_revision": row["expected_session_revision"],
            "revision": row["revision"],
            "title": row["title"],
            "context": row["context"],
            "content": json.loads(str(row["content_json"])),
            "allowed_actions": json.loads(str(row["allowed_actions_json"])),
            "submit_path": row["submit_path"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )


def _awaiting_for_workflow(connection, workflow_id: str) -> GuidanceAwaitingV1 | None:
    row = (
        connection.execute(
            select(AgentCanvasGuidanceAwaitingRow).where(
                AgentCanvasGuidanceAwaitingRow.workflow_id == workflow_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return guidance_awaiting_from_row(row)


def guidance_awaiting_from_row(row: Mapping[str, object]) -> GuidanceAwaitingV1:
    return GuidanceAwaitingV1.model_validate(
        {
            "awaiting_id": row["awaiting_id"],
            "workflow_id": row["workflow_id"],
            "session_id": row["session_id"],
            "checkpoint_id": row["checkpoint_id"],
            "kind": row["kind"],
            "requires_user_action": row["requires_user_action"],
            "resume_policy": row["resume_policy"],
            "interaction_id": row["interaction_id"],
            "node_ids": json.loads(str(row["node_ids_json"])),
            "stage": row["stage"],
            "stage_revision": row["stage_revision"],
            "created_at": row["created_at"],
        }
    )


def _require_session(
    connection,
    *,
    workflow_id: str,
    session_id: str,
    expected_revision: int,
) -> Mapping[str, object]:
    row = (
        connection.execute(
            select(AgentCanvasGuidanceSessionRow).where(
                AgentCanvasGuidanceSessionRow.workflow_id == workflow_id,
                AgentCanvasGuidanceSessionRow.session_id == session_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _error(
            "guidance_session_not_found",
            "Guidance session was not found.",
        )
    if int(row["revision"]) != expected_revision:
        raise _error(
            "guidance_revision_conflict",
            "Guidance session revision is stale.",
        )
    return row


def _journey(session: Mapping[str, object]) -> GuidedProductionJourneyV1:
    return GuidedProductionJourneyV1.model_validate_json(str(session["journey_state_json"]))


def _submission_row(connection, submission_id: str):
    return (
        connection.execute(
            select(AgentCanvasGuidedInteractionSubmissionRow).where(
                AgentCanvasGuidedInteractionSubmissionRow.submission_id == submission_id
            )
        )
        .mappings()
        .one_or_none()
    )


def _require_open_interaction(
    connection,
    interaction: GuidedInteractionV1,
    request: GuidedInteractionSubmitRequestV1,
) -> None:
    row = (
        connection.execute(
            select(AgentCanvasGuidedInteractionRow).where(
                AgentCanvasGuidedInteractionRow.interaction_id == interaction.interaction_id,
                AgentCanvasGuidedInteractionRow.workflow_id == interaction.workflow_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        row is None
        or str(row["status"]) != "open"
        or int(row["revision"]) != request.expected_interaction_revision
    ):
        raise _error("guided_interaction_stale", "Guided interaction changed before Submit.")


def _close_interaction_and_awaiting(
    connection,
    interaction: GuidedInteractionV1,
    awaiting: GuidanceAwaitingV1,
    *,
    updated_at: str,
) -> None:
    connection.execute(
        update(AgentCanvasGuidedInteractionRow)
        .where(
            AgentCanvasGuidedInteractionRow.interaction_id == interaction.interaction_id,
            AgentCanvasGuidedInteractionRow.status == "open",
        )
        .values(
            status="closed",
            revision=interaction.revision + 1,
            updated_at=updated_at,
        )
    )
    connection.execute(
        delete(AgentCanvasGuidanceAwaitingRow).where(
            AgentCanvasGuidanceAwaitingRow.awaiting_id == awaiting.awaiting_id
        )
    )


def _journey_after_state_action(
    policy: GuidedProductionJourneyPolicyService,
    journey: GuidedProductionJourneyV1,
    element_decisions: tuple[CreativeElementDecisionV2, ...],
    proposal_action: Literal["defer_topic", "exclude_element"],
    *,
    submission_id: str,
) -> GuidedProductionJourneyV1:
    suffix = "deferred" if proposal_action == "defer_topic" else "excluded"
    evidence_kind = {
        "world_setting": f"world_setting_{suffix}",
        "foundation_design": f"foundation_item_{suffix}",
        "bgm": f"bgm_{suffix}",
    }.get(journey.stage)
    if evidence_kind is None:
        return journey.model_copy(update={"stage_status": "ready", "active_action": None})
    return policy.apply_evidence(
        JourneyPolicyContextV1(
            journey=journey,
            element_decisions=tuple(
                JourneyElementDecisionV1.model_validate(item.model_dump())
                for item in element_decisions
            ),
        ),
        JourneyEvidenceV1(
            evidence_id=f"guided-state-action:{submission_id}",
            evidence_kind=cast(str, evidence_kind),
            source_id=submission_id,
            foundation_item_id=(
                journey.active_action.foundation_item_id
                if journey.active_action is not None
                else None
            ),
        ),
    )


def _validate_resume_proof(
    awaiting: GuidanceAwaitingV1,
    proof: GuidanceAwaitingResumeProofV1,
) -> None:
    if awaiting.resume_policy != proof.evidence_kind:
        raise _error(
            "guidance_resume_evidence_missing",
            "Resume evidence does not match the declared Guidance policy.",
        )
    if awaiting.resume_policy == "submit_interaction":
        valid = proof.interaction_id == awaiting.interaction_id
    elif awaiting.resume_policy == "node_terminal":
        valid = proof.node_ids == awaiting.node_ids
    else:
        valid = True
    if not valid:
        raise _error(
            "guidance_resume_evidence_missing",
            "Resume evidence does not match the current Guidance resources.",
        )


def _questionnaire_directives(
    interaction: GuidedInteractionV1,
    request: GuidedQuestionnaireSubmitV1,
    *,
    submission_id: str,
) -> tuple[RequirementDirectiveV1, ...]:
    content = interaction.content
    if not isinstance(content, GuidedQuestionnaireV1):
        raise _error(
            "guided_interaction_action_not_allowed",
            "This guided interaction is not a questionnaire.",
        )
    questions = {question.question_id: question for question in content.questions}
    answers = {answer.question_id: answer for answer in request.answers}
    if len(answers) != len(request.answers) or set(answers) != set(questions):
        raise _error(
            "guided_interaction_incomplete",
            "Questionnaire Submit requires exactly one answer for every question.",
        )
    directives: list[RequirementDirectiveV1] = []
    for question_id, question in questions.items():
        answer = answers[question_id]
        if isinstance(answer, GuidedQuestionAnswerV1):
            option = next(
                (item for item in question.options if item.option_id == answer.option_id),
                None,
            )
            if option is None:
                raise _error(
                    "guided_interaction_option_invalid",
                    "Questionnaire answer is not a current option.",
                )
            source_text = option.title
            normalized_meaning = option.summary
            source_option_id = option.option_id
        elif isinstance(answer, GuidedCustomAnswerV1):
            if not question.allow_custom:
                raise _error(
                    "guided_interaction_action_not_allowed",
                    "This question does not accept a custom answer.",
                )
            source_text = answer.value
            normalized_meaning = answer.value
            source_option_id = None
        elif isinstance(answer, GuidedSkipAnswerV1):
            if not question.allow_skip:
                raise _error(
                    "guided_interaction_action_not_allowed",
                    "This question cannot be skipped.",
                )
            continue
        else:
            raise AssertionError("Questionnaire answer union is exhaustive.")
        digest = sha256(
            f"{submission_id}:{question_id}:{source_text}:{normalized_meaning}".encode("utf-8")
        ).hexdigest()
        directives.append(
            RequirementDirectiveV1(
                directive_id=f"reqdir_{digest[:32]}",
                source_kind="decision_bundle_answer",
                source_bundle_id=interaction.interaction_id,
                source_question_id=question_id,
                source_option_id=source_option_id,
                source_text=source_text,
                normalized_meaning=normalized_meaning,
                scope_kind="global",
                strength="preference",
                created_revision_no=1,
            )
        )
    return tuple(directives)


def _dump(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="guided_interaction_repository")
