"""SQLite authority for guided interactions and durable awaiting state."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal, Mapping, cast

from pydantic import TypeAdapter
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.agent_canvas_guided_reference_validation import (
    reference_target_is_current,
)
from app.persistence.agent_canvas_prompt_preparation_dispatch_repository import (
    AgentCanvasPromptPreparationDispatchRepository,
)
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.agent_canvas_guided_media_resume_repository import (
    AgentCanvasGuidedMediaResumeRepository,
)
from app.persistence.agent_canvas_guided_answer_projection import (
    append_guided_answer_message_in_transaction,
)
from app.persistence.models import (
    AgentCanvasActionReceiptRow,
    AgentCanvasChatTurnRow,
    AgentCanvasConceptProposalRow,
    AgentCanvasExecutionResultCommitRow,
    AgentCanvasGuidanceAwaitingRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasGuidanceTopicRow,
    AgentCanvasGuidedInteractionRow,
    AgentCanvasGuidedInteractionSubmissionRow,
    AgentCanvasWorkflowRow,
    AgentCanvasNodeRow,
    AgentWorkingDocumentRow,
    AssetVersionRow,
)
from app.schemas.agent_canvas_conversation import AgentActionReceiptV2, ContinuationCommitV2
from app.schemas.agent_canvas_creative_session import (
    CreativeElementDecisionV2,
    CreativeGoalV2,
    canonical_guidance_topic_kind,
)
from app.schemas.agent_canvas_guided_interactions import (
    GuidanceAwaitingResumeProofV2,
    GuidanceAwaitingV2,
    GuidedConceptChoiceV2,
    GuidedConceptSubmitV2,
    GuidedInteractionSubmissionRecordV1,
    GuidedInteractionSubmitRequestV1,
    GuidedInteractionV1,
    GuidedCustomAnswerV1,
    GuidedQuestionAnswerV1,
    GuidedQuestionnaireSubmitV1,
    GuidedQuestionnaireV1,
    GuidedProductSourceQuestionV1,
    GuidedReferenceKindV1,
    GuidedReferenceSourceQuestionV1,
    GuidedMediaReviewSubmitV1,
    GuidedMediaReviewV1,
    GuidedSkipAnswerV1,
    GuidedInteractionAcceptedV1,
)
from app.schemas.agent_canvas_media_review_authority import (
    CanvasPostReadyEffectDispositionV1,
    GuidedMediaReviewPublicationCommandV1,
)
from app.schemas.agent_canvas_guided_media_resume import (
    GuidedMediaConfirmationResumeDeliveryV1,
)
from app.schemas.agent_canvas_production_journey import (
    GuidedProductionJourneyV2,
    JourneyEvidenceV2,
    JourneyActionProjectionV2,
    JourneyPolicyContextV2,
)
from app.schemas.agent_canvas_requirements import (
    CharacterCountControlV1,
    DurationSecondsControlV1,
    RequirementDirectiveV1,
    RequirementElementPresenceV1,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_production_journey import (
    GuidedProductionJourneyPolicyService,
    parse_production_journey,
)
from app.services.agent_canvas_requirement_directives import (
    canonicalize_requirement_directives,
)
from app.services.agent_canvas_requirements import (
    update_requirement_compatibility_projection_in_transaction,
)
from app.services.agent_canvas_guided_duration import (
    DURATION_QUESTION_ID,
    GuidedDurationAuthorityPolicy,
)
from app.services.agent_canvas_guided_character import (
    CHARACTER_COUNT_QUESTION_ID,
    GuidedCharacterAuthorityPolicy,
)
from app.services.agent_canvas_character_occurrence_authority import (
    CharacterOccurrenceAuthoritySource,
)
from app.services.agent_canvas_requirements import (
    reconcile_character_occurrence_authority_in_transaction,
)
from app.services.agent_canvas_production_journey import reconcile_character_occurrences
from app.services.response_locale_resolver import ResponseLocaleResolverV1


class AgentCanvasGuidedInteractionRepository:
    """Persist one current interaction and awaiting descriptor per workflow."""

    def __init__(
        self,
        database: V2Database,
        events: EventRepository,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._database = database
        self._events = events
        self._fault = fault_injector or (lambda _boundary: None)
        self._media_resume_deliveries = AgentCanvasGuidedMediaResumeRepository(
            database,
            events,
        )

    @property
    def database(self) -> V2Database:
        return self._database

    def open_with_awaiting(
        self,
        interaction: GuidedInteractionV1,
        awaiting: GuidanceAwaitingV2,
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

                    _insert_interaction_and_awaiting_in_transaction(
                        connection,
                        interaction,
                        awaiting,
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

    def open_product_source_with_journey(
        self,
        workflow_id: str,
        *,
        source_turn_id: str,
        expected_session_revision: int,
        idempotency_key: str,
        input_kind: Literal["main", "multiview"] = "main",
        prompt: str | None = None,
    ) -> GuidedInteractionV1:
        """Atomically open the Product source wait and its Journey owner."""

        if not idempotency_key:
            raise _error("guided_interaction_invalid", "Product source idempotency is required.")
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    session = (
                        connection.execute(
                            select(AgentCanvasGuidanceSessionRow).where(
                                AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if session is None:
                        raise _error(
                            "guided_interaction_not_found", "Guidance session was not found."
                        )
                    if int(session["revision"]) != expected_session_revision:
                        raise _error(
                            "guidance_revision_conflict",
                            "Guidance session changed before Product entry.",
                        )
                    journey = _journey(session)
                    if journey.stage != "product":
                        raise _error(
                            "guided_product_stage_invalid",
                            "Product source interaction is only available during the Product stage.",
                        )
                    existing_row = (
                        connection.execute(
                            select(AgentCanvasGuidedInteractionRow).where(
                                AgentCanvasGuidedInteractionRow.workflow_id == workflow_id,
                                AgentCanvasGuidedInteractionRow.session_id == session["session_id"],
                                AgentCanvasGuidedInteractionRow.kind == "product_source",
                                AgentCanvasGuidedInteractionRow.status == "open",
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing_row is not None:
                        existing = guided_interaction_from_row(existing_row)
                        persisted_awaiting = _awaiting_for_workflow(connection, workflow_id)
                        if (
                            persisted_awaiting is None
                            or persisted_awaiting.interaction_id != existing.interaction_id
                        ):
                            raise _error(
                                "guidance_authority_conflict",
                                "Product source interaction is missing matching awaiting authority.",
                            )
                        if (
                            not isinstance(existing.content, GuidedProductSourceQuestionV1)
                            or existing.content.input_kind != input_kind
                        ):
                            raise _error(
                                "guided_interaction_conflict",
                                "Another Product source branch is already open.",
                            )
                        connection.commit()
                        return existing

                    revision = int(session["revision"])
                    identity = sha256(
                        f"product-source:{workflow_id}:{session['session_id']}:{journey.stage_revision}:{input_kind}:v1".encode(
                            "utf-8"
                        )
                    ).hexdigest()[:32]
                    interaction_id = f"interaction_product_source_{identity}"
                    checkpoint_id = f"product_source:{journey.stage_revision}:{input_kind}"
                    now = datetime.now(timezone.utc)
                    question = GuidedProductSourceQuestionV1(
                        input_kind=input_kind,
                        question_id=f"product_{input_kind}_source",
                        prompt=prompt
                        or (
                            "Provide one Product Main image."
                            if input_kind == "main"
                            else "Provide two to eight ordered Product Multiview images."
                        ),
                        expected_guidance_revision=revision + 1,
                        min_asset_count=1 if input_kind == "main" else 2,
                        max_asset_count=1 if input_kind == "main" else 8,
                    )
                    interaction = GuidedInteractionV1(
                        interaction_id=interaction_id,
                        workflow_id=workflow_id,
                        session_id=str(session["session_id"]),
                        checkpoint_id=checkpoint_id,
                        kind="product_source",
                        status="open",
                        response_locale=str(session["response_locale"]),
                        expected_session_revision=revision + 1,
                        revision=1,
                        title="Product image source",
                        context="Choose whether to upload or generate the Product source.",
                        content=question,
                        allowed_actions=("select_source",),
                        submit_path=(
                            f"/api/v2/workflows/{workflow_id}/chat/interactions/{interaction_id}/submit"
                        ),
                        created_at=now,
                        updated_at=now,
                    )
                    awaiting = GuidanceAwaitingV2(
                        awaiting_id=f"awaiting_product_source_{identity}",
                        workflow_id=workflow_id,
                        session_id=str(session["session_id"]),
                        checkpoint_id=checkpoint_id,
                        kind="product_source",
                        requires_user_action=True,
                        resume_policy="submit_interaction",
                        interaction_id=interaction_id,
                        stage="product",
                        stage_revision=journey.stage_revision,
                        created_at=now,
                    )
                    waiting_action = JourneyActionProjectionV2(
                        action_id=f"product-source:{workflow_id}:{journey.stage_revision}",
                        action_kind="wait_for_user:product_source",
                        stage="product",
                        stage_revision=journey.stage_revision,
                        status="waiting_user",
                        turn_id=source_turn_id,
                    )
                    next_journey = journey.model_copy(
                        update={"stage_status": "waiting_user", "active_action": waiting_action}
                    )
                    _insert_interaction_and_awaiting_in_transaction(
                        connection, interaction, awaiting
                    )
                    self._fault("after_product_source_authority")
                    updated = connection.execute(
                        update(AgentCanvasGuidanceSessionRow)
                        .where(
                            AgentCanvasGuidanceSessionRow.session_id == session["session_id"],
                            AgentCanvasGuidanceSessionRow.revision == expected_session_revision,
                        )
                        .values(
                            journey_state_json=next_journey.model_dump_json(),
                            revision=expected_session_revision + 1,
                            updated_at=now.isoformat(),
                        )
                    )
                    if updated.rowcount != 1:
                        raise _error(
                            "guidance_revision_conflict",
                            "Guidance session changed before Product entry.",
                        )
                    self._fault("after_product_source_journey")
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            event_type="journey_stage_waiting_user",
                            transition_key=f"journey:{session['session_id']}:{idempotency_key}",
                            action_id=waiting_action.action_id,
                            created_at=now.isoformat(),
                            payload={
                                "session_id": str(session["session_id"]),
                                "stage": "product",
                                "stage_revision": journey.stage_revision,
                                "action_kind": waiting_action.action_kind,
                                "interaction_id": interaction_id,
                                "awaiting_id": awaiting.awaiting_id,
                            },
                        ),
                    )
                    self._fault("before_product_source_commit")
                    connection.commit()
                    return interaction
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "guided_interaction_persistence_unavailable", "Guided interaction storage failed."
            ) from error

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

    def get_awaiting(self, workflow_id: str) -> GuidanceAwaitingV2 | None:
        with self._database.engine.connect() as connection:
            return _awaiting_for_workflow(connection, workflow_id)

    def open_product_source(
        self,
        workflow_id: str,
        *,
        input_kind: Literal["main", "multiview"],
        prompt: str | None = None,
    ) -> GuidedInteractionV1:
        """Open the typed Product source question at the current Product checkpoint."""

        with self._database.engine.connect() as connection:
            session = (
                connection.execute(
                    select(AgentCanvasGuidanceSessionRow).where(
                        AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if session is None:
            raise _error("guided_interaction_not_found", "Guidance session was not found.")
        return self.open_product_source_with_journey(
            workflow_id,
            source_turn_id="explicit-product-source",
            expected_session_revision=int(session["revision"]),
            idempotency_key=(
                f"open-product-source:{workflow_id}:{input_kind}:{session['revision']}"
            ),
            input_kind=input_kind,
            prompt=prompt,
        )

    def open_reference_source_with_journey(
        self,
        workflow_id: str,
        *,
        source_turn_id: str,
        expected_session_revision: int,
        idempotency_key: str,
        reference_kind: GuidedReferenceKindV1,
        target_node_id: str,
        target_node_revision: int,
        occurrence_id: str | None = None,
        prompt_dispatch: AgentCanvasPromptPreparationDispatchRepository | None = None,
        prompt_operation_id: str | None = None,
    ) -> GuidedInteractionV1:
        """Open one typed reference wait while reserving the current Journey stage."""

        if not idempotency_key:
            raise _error("guided_interaction_invalid", "Reference source idempotency is required.")
        if (prompt_dispatch is None) != (prompt_operation_id is None):
            raise _error(
                "guided_interaction_invalid",
                "Reference prompt dispatch and operation must be supplied together.",
            )
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    session = (
                        connection.execute(
                            select(AgentCanvasGuidanceSessionRow).where(
                                AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if session is None:
                        raise _error(
                            "guided_interaction_not_found", "Guidance session was not found."
                        )
                    if int(session["revision"]) != expected_session_revision:
                        raise _error("guidance_revision_conflict", "Guidance session is stale.")
                    target = (
                        connection.execute(
                            select(AgentCanvasNodeRow).where(
                                AgentCanvasNodeRow.workflow_id == workflow_id,
                                AgentCanvasNodeRow.node_id == target_node_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if not reference_target_is_current(
                        target,
                        reference_kind=reference_kind,
                        target_node_revision=target_node_revision,
                        occurrence_id=occurrence_id,
                    ):
                        raise _error(
                            "guided_reference_source_target_invalid",
                            "Reference source target does not match the selected capability.",
                        )
                    journey = _journey(session)
                    identity = sha256(
                        f"reference-source:{workflow_id}:{journey.stage_revision}:{reference_kind}:"
                        f"{target_node_id}:{target_node_revision}:{occurrence_id or '-'}:v1".encode()
                    ).hexdigest()[:32]
                    interaction_id = f"interaction_reference_source_{identity}"
                    exact_row = (
                        connection.execute(
                            select(AgentCanvasGuidedInteractionRow).where(
                                AgentCanvasGuidedInteractionRow.interaction_id == interaction_id,
                                AgentCanvasGuidedInteractionRow.workflow_id == workflow_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if exact_row is not None:
                        exact = guided_interaction_from_row(exact_row)
                        if (
                            not isinstance(exact.content, GuidedReferenceSourceQuestionV1)
                            or exact.content.reference_kind != reference_kind
                            or exact.content.target_node_id != target_node_id
                            or exact.content.target_node_revision != target_node_revision
                            or exact.content.occurrence_id != occurrence_id
                        ):
                            raise _error(
                                "guided_interaction_conflict",
                                "Reference source interaction identity conflicts with persisted state.",
                            )
                        persisted_awaiting = _awaiting_for_workflow(connection, workflow_id)
                        if exact.status == "open":
                            if (
                                persisted_awaiting is None
                                or persisted_awaiting.interaction_id != exact.interaction_id
                            ):
                                raise _error(
                                    "guidance_authority_conflict",
                                    "Reference source interaction is missing matching awaiting authority.",
                                )
                            if prompt_dispatch is not None:
                                prompt_dispatch.hold_for_waiting_user_in_transaction(
                                    connection,
                                    workflow_id=workflow_id,
                                    node_id=target_node_id,
                                    operation_id=prompt_operation_id or "",
                                    now=datetime.now(timezone.utc),
                                )
                        elif (
                            persisted_awaiting is not None
                            and persisted_awaiting.interaction_id == exact.interaction_id
                        ):
                            raise _error(
                                "guidance_authority_conflict",
                                "Closed reference source interaction still owns awaiting authority.",
                            )
                        connection.commit()
                        return exact
                    existing_row = (
                        connection.execute(
                            select(AgentCanvasGuidedInteractionRow).where(
                                AgentCanvasGuidedInteractionRow.workflow_id == workflow_id,
                                AgentCanvasGuidedInteractionRow.kind == "reference_source",
                                AgentCanvasGuidedInteractionRow.status == "open",
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing_row is not None:
                        existing = guided_interaction_from_row(existing_row)
                        if (
                            not isinstance(existing.content, GuidedReferenceSourceQuestionV1)
                            or existing.content.reference_kind != reference_kind
                            or existing.content.target_node_id != target_node_id
                            or existing.content.target_node_revision != target_node_revision
                            or existing.content.occurrence_id != occurrence_id
                        ):
                            raise _error(
                                "guided_interaction_conflict",
                                "Another reference source interaction is already open.",
                            )
                        persisted_awaiting = _awaiting_for_workflow(connection, workflow_id)
                        if (
                            persisted_awaiting is None
                            or persisted_awaiting.interaction_id != existing.interaction_id
                        ):
                            raise _error(
                                "guidance_authority_conflict",
                                "Reference source interaction is missing matching awaiting authority.",
                            )
                        if prompt_dispatch is not None:
                            prompt_dispatch.hold_for_waiting_user_in_transaction(
                                connection,
                                workflow_id=workflow_id,
                                node_id=target_node_id,
                                operation_id=prompt_operation_id or "",
                                now=datetime.now(timezone.utc),
                            )
                        connection.commit()
                        return existing

                    now = datetime.now(timezone.utc)
                    if prompt_dispatch is not None:
                        prompt_dispatch.hold_for_waiting_user_in_transaction(
                            connection,
                            workflow_id=workflow_id,
                            node_id=target_node_id,
                            operation_id=prompt_operation_id or "",
                            now=now,
                        )
                    interaction = GuidedInteractionV1(
                        interaction_id=interaction_id,
                        workflow_id=workflow_id,
                        session_id=str(session["session_id"]),
                        checkpoint_id=f"reference_source:{journey.stage_revision}:{reference_kind}:{target_node_id}",
                        kind="reference_source",
                        status="open",
                        response_locale=ResponseLocaleResolverV1().resolve(
                            str(session["response_locale"])
                        ),
                        expected_session_revision=int(session["revision"]) + 1,
                        revision=1,
                        title=(
                            "Character reference"
                            if reference_kind == "character_main"
                            else "Scene reference"
                        ),
                        context="Choose an optional reference image for this Main draft.",
                        content=GuidedReferenceSourceQuestionV1(
                            reference_kind=reference_kind,
                            target_node_id=target_node_id,
                            target_node_revision=target_node_revision,
                            occurrence_id=occurrence_id,
                            question="Would you like to use a reference image for this Main draft?",
                            use_reference_label="Use reference",
                            skip_reference_label="Skip reference",
                            expected_guidance_revision=int(session["revision"]) + 1,
                        ),
                        allowed_actions=("use_reference", "skip_reference"),
                        submit_path=(
                            f"/api/v2/workflows/{workflow_id}/chat/interactions/"
                            f"interaction_reference_source_{identity}/submit"
                        ),
                        created_at=now,
                        updated_at=now,
                    )
                    awaiting = GuidanceAwaitingV2(
                        awaiting_id=f"awaiting_reference_source_{identity}",
                        workflow_id=workflow_id,
                        session_id=str(session["session_id"]),
                        checkpoint_id=interaction.checkpoint_id,
                        kind="reference_source",
                        requires_user_action=True,
                        resume_policy="submit_interaction",
                        interaction_id=interaction.interaction_id,
                        stage=journey.stage,
                        stage_revision=journey.stage_revision,
                        created_at=now,
                    )
                    waiting_action = JourneyActionProjectionV2(
                        action_id=f"reference-source:{workflow_id}:{journey.stage_revision}:{reference_kind}:{target_node_id}",
                        action_kind="wait_for_user:reference_source",
                        stage=journey.stage,
                        stage_revision=journey.stage_revision,
                        status="waiting_user",
                        turn_id=source_turn_id,
                        occurrence_id=occurrence_id,
                        character_phase="main" if reference_kind == "character_main" else None,
                    )
                    _insert_interaction_and_awaiting_in_transaction(
                        connection, interaction, awaiting
                    )
                    updated = connection.execute(
                        update(AgentCanvasGuidanceSessionRow)
                        .where(
                            AgentCanvasGuidanceSessionRow.session_id == session["session_id"],
                            AgentCanvasGuidanceSessionRow.revision == expected_session_revision,
                        )
                        .values(
                            journey_state_json=journey.model_copy(
                                update={
                                    "stage_status": "waiting_user",
                                    "active_action": waiting_action,
                                }
                            ).model_dump_json(),
                            revision=expected_session_revision + 1,
                            updated_at=now.isoformat(),
                        )
                    )
                    if updated.rowcount != 1:
                        raise _error(
                            "guidance_revision_conflict",
                            "Guidance session changed before reference entry.",
                        )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            event_type="guided_reference_source_opened",
                            transition_key=f"guided-reference:{interaction.interaction_id}:opened",
                            action_id=waiting_action.action_id,
                            created_at=now.isoformat(),
                            payload={
                                "interaction_id": interaction.interaction_id,
                                "reference_kind": reference_kind,
                                "target_node_id": target_node_id,
                                "target_node_revision": target_node_revision,
                                "occurrence_id": occurrence_id,
                                "stage_revision": journey.stage_revision,
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
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "guided_interaction_persistence_unavailable",
                "Guided interaction storage failed.",
            ) from error

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

    def ensure_media_resume_delivery(
        self,
        submission_id: str,
    ) -> GuidedMediaConfirmationResumeDeliveryV1 | None:
        """Lazily publish one exact accepted media resume delivery on replay."""

        return self._media_resume_deliveries.ensure_for_submission(submission_id)

    def submit_questionnaire(
        self,
        interaction: GuidedInteractionV1,
        request: GuidedQuestionnaireSubmitV1,
        *,
        submission_id: str,
        idempotency_key: str,
        continuation_writer: Callable[..., None] | None = None,
    ) -> GuidedInteractionAcceptedV1:
        if not isinstance(interaction.content, GuidedQuestionnaireV1):
            raise _error(
                "guided_interaction_action_not_allowed",
                "This guided interaction is not a questionnaire.",
            )
        duration_answer = (
            GuidedDurationAuthorityPolicy().resolve_answer(interaction.content, request)
            if _is_duration_questionnaire(interaction.content)
            else None
        )
        character_answer = (
            GuidedCharacterAuthorityPolicy().resolve_answer(interaction.content, request)
            if _is_character_questionnaire(interaction.content)
            else None
        )
        directives = (
            ()
            if duration_answer is not None or character_answer is not None
            else _questionnaire_directives(
                interaction,
                request,
                submission_id=submission_id,
            )
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
                controls = {item.control: item for item in requirement_head.ledger.hard_controls}
                if duration_answer is not None:
                    controls["duration_seconds"] = DurationSecondsControlV1(
                        value=duration_answer.effect.value,
                        source_kind="decision_bundle_answer",
                        source_bundle_id=interaction.interaction_id,
                        source_question_id=DURATION_QUESTION_ID,
                        source_option_id=duration_answer.source_option_id,
                        source_text=duration_answer.source_text,
                        created_revision_no=revision_no,
                    )
                next_ledger = requirement_head.ledger.model_copy(
                    update={
                        "hard_controls": tuple(controls[key] for key in sorted(controls)),
                        "active_directives": canonical.active_directives,
                        "unresolved_conflicts": (),
                    }
                )
                reconciliation = None
                if character_answer is not None:
                    source_turn_id = _character_source_turn_id(interaction)
                    source = CharacterOccurrenceAuthoritySource(
                        source_kind="decision_bundle_answer",
                        source_text=character_answer.source_text,
                        source_turn_id=source_turn_id,
                        source_bundle_id=interaction.interaction_id,
                        source_question_id=CHARACTER_COUNT_QUESTION_ID,
                        source_option_id=character_answer.source_option_id,
                    )
                    count_control = CharacterCountControlV1(
                        value=character_answer.count,
                        source_kind="decision_bundle_answer",
                        source_turn_id=source_turn_id,
                        source_bundle_id=interaction.interaction_id,
                        source_question_id=CHARACTER_COUNT_QUESTION_ID,
                        source_option_id=character_answer.source_option_id,
                        source_text=character_answer.source_text,
                        created_revision_no=revision_no,
                    )
                    presence = RequirementElementPresenceV1(
                        element_kind="character",
                        presence="include" if character_answer.count > 0 else "exclude",
                        source_kind="decision_bundle_answer",
                        source_turn_id=source_turn_id,
                        source_bundle_id=interaction.interaction_id,
                        source_question_id=CHARACTER_COUNT_QUESTION_ID,
                        source_option_id=character_answer.source_option_id,
                        source_text=character_answer.source_text,
                        created_revision_no=revision_no,
                    )
                    next_ledger = next_ledger.model_copy(
                        update={
                            "hard_controls": tuple(
                                item
                                for item in next_ledger.hard_controls
                                if item.control != "character_count"
                            )
                            + (count_control,),
                            "element_presence": tuple(
                                item
                                for item in next_ledger.element_presence
                                if item.element_kind != "character"
                            )
                            + (presence,),
                        }
                    )
                    reconciliation = reconcile_character_occurrence_authority_in_transaction(
                        connection,
                        workflow_id=interaction.workflow_id,
                        current=requirement_head.ledger,
                        candidate=next_ledger,
                        occurrence_patches=None,
                        revision_no=revision_no,
                        source=source,
                        explicit_character_count=True,
                        explicit_character_presence=True,
                    )
                    next_ledger = reconciliation.ledger
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
                if character_answer is not None and character_answer.count > 0:
                    assert reconciliation is not None
                    next_journey = reconcile_character_occurrences(
                        journey,
                        reconciliation.projection.occurrences,
                    ).model_copy(
                        update={
                            "stage_status": "ready",
                            "stage_revision": journey.stage_revision + 1,
                            "active_action": None,
                        }
                    )
                else:
                    next_journey = policy.apply_evidence(
                        JourneyPolicyContextV2(
                            journey=journey,
                            included_character_occurrence_ids=(
                                () if character_answer is not None else None
                            ),
                        ),
                        JourneyEvidenceV2(
                            evidence_id=f"questionnaire-submitted:{submission_id}",
                            evidence_kind=(
                                "character_excluded"
                                if character_answer is not None
                                else "clarification_completed"
                            ),
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
                continuation_id = None
                if duration_answer is not None or character_answer is not None:
                    if continuation_writer is None:
                        raise _error(
                            "guidance_continuation_unavailable",
                            "Questionnaire acceptance cannot publish its continuation.",
                        )
                    source_turn_id = (
                        _duration_source_turn_id(interaction)
                        if duration_answer is not None
                        else _character_source_turn_id(interaction)
                    )
                    source_turn = (
                        connection.execute(
                            select(AgentCanvasChatTurnRow).where(
                                AgentCanvasChatTurnRow.turn_id == source_turn_id,
                                AgentCanvasChatTurnRow.workflow_id == interaction.workflow_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if source_turn is None:
                        raise _error(
                            "guidance_resume_evidence_missing",
                            "Duration acceptance source Turn is unavailable.",
                        )
                    continuation_kind = "duration" if duration_answer is not None else "character"
                    identity = sha256(
                        f"{continuation_kind}-next-action:{submission_id}".encode("utf-8")
                    ).hexdigest()
                    continuation_id = f"continuation_{identity[:24]}"
                    continuation_writer(
                        connection,
                        workflow_id=interaction.workflow_id,
                        conversation_id=str(source_turn["conversation_id"]),
                        continuation=ContinuationCommitV2(
                            continuation_id=continuation_id,
                            continuation_turn_id=f"turn_{identity[24:56]}",
                            source_turn_id=source_turn_id,
                            source_action_id=interaction.interaction_id,
                            idempotency_key=f"{continuation_kind}-next-action:{submission_id}",
                        ),
                        now=now,
                    )
                append_guided_answer_message_in_transaction(
                    connection,
                    workflow_id=interaction.workflow_id,
                    interaction_id=interaction.interaction_id,
                    submission_id=submission_id,
                    questionnaire=interaction.content,
                    request=request,
                    created_at=now,
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
                            "changed_control_names": (
                                ["duration_seconds"]
                                if duration_answer is not None
                                else (["character_count"] if character_answer is not None else [])
                            ),
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
                    continuation_id=continuation_id,
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
                raise

    def submit_concept_state_action(
        self,
        interaction: GuidedInteractionV1,
        request: GuidedConceptSubmitV2,
        *,
        submission_id: str,
        idempotency_key: str,
        action_id: str,
        proposal_action: Literal["defer_topic", "exclude_element"],
    ) -> GuidedInteractionAcceptedV1:
        """Apply a non-materializing concept action without an Agent action Turn."""

        if not isinstance(interaction.content, GuidedConceptChoiceV2):
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
        awaiting: GuidanceAwaitingV2,
        *,
        expected_session_revision: int,
    ) -> GuidanceAwaitingV2:
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

    def reconcile_terminal_member(
        self,
        *,
        workflow_id: str,
        execution_id: str,
        member_id: str,
        node_id: str,
        error_code: str,
        retryable: bool,
    ) -> bool:
        """Close the matching manual wait when its execution member settles."""

        now = datetime.now(timezone.utc).isoformat()
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                awaiting = _awaiting_for_workflow(connection, workflow_id)
                if (
                    awaiting is None
                    or awaiting.kind != "manual_node_run"
                    or node_id not in awaiting.node_ids
                ):
                    connection.rollback()
                    return False
                session = _require_session(
                    connection,
                    workflow_id=workflow_id,
                    session_id=awaiting.session_id,
                    expected_revision=(
                        int(
                            connection.execute(
                                select(AgentCanvasGuidanceSessionRow.revision).where(
                                    AgentCanvasGuidanceSessionRow.session_id == awaiting.session_id
                                )
                            ).scalar_one()
                        )
                    ),
                )
                journey = _journey(session)
                evidence_id = f"execution-member-terminal:{execution_id}:{member_id}"
                if any(item.evidence_id == evidence_id for item in journey.transition_evidence):
                    connection.rollback()
                    return False
                transition = JourneyEvidenceV2(
                    evidence_id=evidence_id,
                    evidence_kind="stage_failed",
                    source_id=member_id,
                    stage=awaiting.stage,
                    stage_revision=awaiting.stage_revision,
                    actor="system",
                ).as_transition(
                    stage=journey.stage,
                    stage_revision=journey.stage_revision,
                )
                next_journey = journey.model_copy(
                    update={
                        "stage_status": "working" if retryable else "failed",
                        "active_action": None,
                        "transition_evidence": (*journey.transition_evidence, transition),
                    }
                )
                deleted = connection.execute(
                    delete(AgentCanvasGuidanceAwaitingRow).where(
                        AgentCanvasGuidanceAwaitingRow.awaiting_id == awaiting.awaiting_id
                    )
                )
                if deleted.rowcount != 1:
                    connection.rollback()
                    return False
                updated = connection.execute(
                    update(AgentCanvasGuidanceSessionRow)
                    .where(
                        AgentCanvasGuidanceSessionRow.session_id == awaiting.session_id,
                    )
                    .values(
                        journey_state_json=next_journey.model_dump_json(),
                        revision=AgentCanvasGuidanceSessionRow.revision + 1,
                        updated_at=now,
                    )
                )
                if updated.rowcount != 1:
                    raise _error(
                        "guidance_revision_conflict",
                        "Guidance session changed during terminal member reconciliation.",
                    )
                payload = {
                    "awaiting_id": awaiting.awaiting_id,
                    "execution_id": execution_id,
                    "member_id": member_id,
                    "node_id": node_id,
                    "session_id": awaiting.session_id,
                    "stage": awaiting.stage,
                    "stage_revision": awaiting.stage_revision,
                    "error_code": error_code,
                    "retryability": "retryable" if retryable else "terminal",
                }
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        event_type="execution_member_terminal_reconciled",
                        transition_key=f"{evidence_id}:execution",
                        created_at=now,
                        payload=payload,
                    ),
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        event_type="manual_node_run_awaiting_reconciled",
                        transition_key=f"{evidence_id}:awaiting",
                        created_at=now,
                        payload=payload,
                    ),
                )
                connection.commit()
                return True
            except BaseException:
                connection.rollback()
                raise

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
        resume_delivery: GuidedMediaConfirmationResumeDeliveryV1 | None = None,
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
                    if request.action == "accept" and resume_delivery is not None:
                        self._media_resume_deliveries.enqueue_in_transaction(
                            connection,
                            resume_delivery,
                        )
                        connection.commit()
                    else:
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
                if request.action == "accept":
                    if resume_delivery is None:
                        raise _error(
                            "guided_media_resume_delivery_unavailable",
                            "Accepted media review requires durable resume delivery.",
                        )
                    self._media_resume_deliveries.enqueue_in_transaction(
                        connection,
                        resume_delivery,
                    )
                connection.commit()
                return accepted
            except BaseException:
                connection.rollback()
                raise

    def publish_media_review_from_result(
        self,
        command: GuidedMediaReviewPublicationCommandV1,
        *,
        now: datetime | None = None,
    ) -> CanvasPostReadyEffectDispositionV1:
        """Replace one exact terminal wait and publish its review atomically."""

        timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        created_at = timestamp.isoformat()
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                awaiting = _awaiting_for_workflow(connection, command.lineage.workflow_id)
                if (
                    awaiting is not None
                    and awaiting.kind == "media_review"
                    and awaiting.interaction_id == command.interaction_id
                ):
                    connection.rollback()
                    return CanvasPostReadyEffectDispositionV1(
                        outcome="already_applied",
                        reason_code="media_review_already_published",
                        interaction_id=command.interaction_id,
                    )
                if awaiting is None or not _awaiting_matches_publication(awaiting, command):
                    connection.rollback()
                    return CanvasPostReadyEffectDispositionV1(
                        outcome="superseded",
                        reason_code="current_wait_replaced",
                    )
                session = _require_session(
                    connection,
                    workflow_id=command.lineage.workflow_id,
                    session_id=awaiting.session_id,
                    expected_revision=command.expected_session_revision,
                )
                self._validate_media_review_authority(connection, command)
                current_journey = _journey(session).model_copy(
                    update={"stage_status": "working", "active_action": None}
                )
                interaction = _publication_interaction(command, timestamp)
                review_awaiting = _publication_awaiting(command, timestamp)
                self._fault("after_old_wait_validation")
                connection.execute(
                    delete(AgentCanvasGuidanceAwaitingRow).where(
                        AgentCanvasGuidanceAwaitingRow.awaiting_id == awaiting.awaiting_id
                    )
                )
                _insert_interaction_and_awaiting_in_transaction(
                    connection,
                    interaction,
                    review_awaiting,
                )
                self._fault("after_review_interaction")
                changed = connection.execute(
                    update(AgentCanvasGuidanceSessionRow)
                    .where(
                        AgentCanvasGuidanceSessionRow.session_id == session["session_id"],
                        AgentCanvasGuidanceSessionRow.revision == command.expected_session_revision,
                    )
                    .values(
                        journey_state_json=current_journey.model_dump_json(),
                        revision=command.expected_session_revision + 1,
                        updated_at=created_at,
                    )
                )
                if changed.rowcount != 1:
                    raise _error(
                        "guidance_revision_conflict",
                        "Guidance session changed before media review publication.",
                    )
                self._fault("after_review_awaiting")
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=command.lineage.workflow_id,
                        node_id=command.lineage.node_id,
                        event_type="guidance_awaiting_resumed",
                        transition_key=f"guidance-awaiting:{awaiting.awaiting_id}:result-replaced",
                        created_at=created_at,
                        payload={
                            "awaiting_id": awaiting.awaiting_id,
                            "checkpoint_id": awaiting.checkpoint_id,
                            "kind": awaiting.kind,
                            "resume_policy": awaiting.resume_policy,
                            "resume_evidence": "result_lineage",
                            "node_ids": list(awaiting.node_ids),
                            "source_commit_id": command.lineage.commit_id,
                        },
                    ),
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=command.lineage.workflow_id,
                        node_id=command.lineage.node_id,
                        event_type="guided_interaction_opened",
                        transition_key=f"guided-interaction:{interaction.interaction_id}:opened",
                        action_id=interaction.interaction_id,
                        created_at=created_at,
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
                        workflow_id=command.lineage.workflow_id,
                        node_id=command.lineage.node_id,
                        event_type="guidance_awaiting_entered",
                        transition_key=f"guidance-awaiting:{review_awaiting.awaiting_id}:entered",
                        action_id=interaction.interaction_id,
                        created_at=created_at,
                        payload={
                            "awaiting_id": review_awaiting.awaiting_id,
                            "session_id": review_awaiting.session_id,
                            "checkpoint_id": review_awaiting.checkpoint_id,
                            "kind": review_awaiting.kind,
                            "resume_policy": review_awaiting.resume_policy,
                            "interaction_id": review_awaiting.interaction_id,
                            "node_ids": list(review_awaiting.node_ids),
                        },
                    ),
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=command.lineage.workflow_id,
                        node_id=command.lineage.node_id,
                        event_type="guided_media_review_required",
                        transition_key=f"guided-media-review-required:{interaction.interaction_id}",
                        action_id=interaction.interaction_id,
                        created_at=created_at,
                        payload={
                            "interaction_id": interaction.interaction_id,
                            "plan_document_id": command.plan_document_id,
                            "plan_revision": command.plan_revision,
                            "node_revision": command.current_node_revision,
                            "asset_id": command.asset_id,
                            "asset_version_id": command.asset_version_id,
                            "allowed_actions": list(command.allowed_actions),
                        },
                    ),
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=command.lineage.workflow_id,
                        node_id=command.lineage.node_id,
                        event_type="guidance_state_updated",
                        transition_key=f"guided-media-review:{interaction.interaction_id}:state",
                        action_id=interaction.interaction_id,
                        created_at=created_at,
                        payload={
                            "session_id": interaction.session_id,
                            "session_revision": command.expected_session_revision + 1,
                            "refresh": ["conversation", "workflow", "runtime", "events"],
                        },
                    ),
                )
                connection.commit()
                return CanvasPostReadyEffectDispositionV1(
                    outcome="applied",
                    reason_code="media_review_published",
                    interaction_id=interaction.interaction_id,
                )
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _validate_media_review_authority(connection, command) -> None:
        commit = (
            connection.execute(
                select(AgentCanvasExecutionResultCommitRow).where(
                    AgentCanvasExecutionResultCommitRow.commit_id == command.lineage.commit_id
                )
            )
            .mappings()
            .one_or_none()
        )
        node = (
            connection.execute(
                select(AgentCanvasNodeRow).where(
                    AgentCanvasNodeRow.workflow_id == command.lineage.workflow_id,
                    AgentCanvasNodeRow.node_id == command.lineage.node_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        version = (
            connection.execute(
                select(AssetVersionRow).where(
                    AssetVersionRow.version_id == command.asset_version_id,
                    AssetVersionRow.asset_id == command.asset_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        plan = (
            connection.execute(
                select(AgentWorkingDocumentRow).where(
                    AgentWorkingDocumentRow.document_id == command.plan_document_id,
                    AgentWorkingDocumentRow.workflow_id == command.lineage.workflow_id,
                    AgentWorkingDocumentRow.revision == command.plan_revision,
                )
            )
            .mappings()
            .one_or_none()
        )
        valid_commit = commit is not None and all(
            (
                str(commit["workflow_id"]) == command.lineage.workflow_id,
                str(commit["execution_id"]) == command.lineage.execution_id,
                str(commit["member_id"]) == command.lineage.member_id,
                str(commit["node_id"]) == command.lineage.node_id,
                str(commit["outcome"]) == "succeeded",
                str(commit["asset_id"]) == command.asset_id,
                str(commit["version_id"]) == command.asset_version_id,
            )
        )
        valid_node = node is not None and all(
            (
                str(node["status"]) == "ready",
                str(node["output_asset_id"]) == command.asset_id,
                int(node["revision"]) == command.current_node_revision,
            )
        )
        valid_version = version is not None and str(version["status"]) == "ready"
        valid_plan = _plan_contains_node(
            plan,
            node_id=command.lineage.node_id,
            node_role=command.planned_node_role,
            sequence_id=command.planned_sequence_id,
            node_revision=command.planned_node_revision,
        )
        if not all((valid_commit, valid_node, valid_version, valid_plan)):
            raise _error(
                "guided_media_result_lineage_invalid",
                "Ready media result lineage does not match current Guidance authority.",
            )

    def resume_awaiting(
        self,
        workflow_id: str,
        proof: GuidanceAwaitingResumeProofV2,
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
        awaiting: GuidanceAwaitingV2,
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
            "product_source": "product_source",
            "reference_source": "reference_source",
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


def _insert_interaction_and_awaiting_in_transaction(
    connection,
    interaction: GuidedInteractionV1,
    awaiting: GuidanceAwaitingV2,
) -> None:
    """Insert one validated interaction/awaiting pair in the caller transaction."""

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


def _awaiting_for_workflow(connection, workflow_id: str) -> GuidanceAwaitingV2 | None:
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


def _awaiting_matches_publication(
    awaiting: GuidanceAwaitingV2,
    command: GuidedMediaReviewPublicationCommandV1,
) -> bool:
    return (
        awaiting.workflow_id == command.lineage.workflow_id
        and awaiting.session_id == command.session_id
        and awaiting.awaiting_id == command.expected_awaiting_id
        and awaiting.kind == command.expected_awaiting_kind
        and awaiting.resume_policy == command.expected_resume_policy
        and awaiting.node_ids == command.expected_awaiting_node_ids
        and awaiting.stage == command.expected_stage
        and awaiting.stage_revision == command.expected_stage_revision
    )


def _publication_interaction(
    command: GuidedMediaReviewPublicationCommandV1,
    timestamp: datetime,
) -> GuidedInteractionV1:
    return GuidedInteractionV1(
        interaction_id=command.interaction_id,
        workflow_id=command.lineage.workflow_id,
        session_id=command.session_id,
        checkpoint_id=command.checkpoint_id,
        kind="media_review",
        status="open",
        response_locale=command.response_locale,
        expected_session_revision=command.expected_session_revision + 1,
        revision=1,
        title=command.title,
        context=command.summary,
        content=GuidedMediaReviewV1(
            node_id=command.lineage.node_id,
            node_revision=command.current_node_revision,
            asset_id=command.asset_id,
            asset_version_id=command.asset_version_id,
            summary=command.summary,
        ),
        allowed_actions=command.allowed_actions,
        submit_path=(
            f"/api/v2/workflows/{command.lineage.workflow_id}/chat/interactions/"
            f"{command.interaction_id}/submit"
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )


def _publication_awaiting(
    command: GuidedMediaReviewPublicationCommandV1,
    timestamp: datetime,
) -> GuidanceAwaitingV2:
    return GuidanceAwaitingV2(
        awaiting_id=command.review_awaiting_id,
        workflow_id=command.lineage.workflow_id,
        session_id=command.session_id,
        checkpoint_id=command.checkpoint_id,
        kind="media_review",
        requires_user_action=True,
        resume_policy="submit_interaction",
        interaction_id=command.interaction_id,
        node_ids=(),
        stage=command.expected_stage,
        stage_revision=command.expected_stage_revision,
        created_at=timestamp,
    )


def _plan_contains_node(
    plan: Mapping[str, object] | None,
    *,
    node_id: str,
    node_role: str,
    sequence_id: str | None,
    node_revision: int,
) -> bool:
    if plan is None:
        return False
    try:
        content = json.loads(str(plan["content_json"]))
    except (KeyError, TypeError, ValueError):
        return False
    records = content.get("planned_nodes") or content.get("node_records") or ()
    return any(
        str(record.get("node_id")) == node_id
        and str(record.get("node_role")) == node_role
        and record.get("sequence_id") == sequence_id
        and int(record.get("node_revision", 0)) == node_revision
        for record in records
        if isinstance(record, dict)
    )


def guidance_awaiting_from_row(row: Mapping[str, object]) -> GuidanceAwaitingV2:
    return GuidanceAwaitingV2.model_validate(
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


def _journey(session: Mapping[str, object]) -> GuidedProductionJourneyV2:
    return parse_production_journey(str(session["journey_state_json"]))


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
    awaiting: GuidanceAwaitingV2,
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
    journey: GuidedProductionJourneyV2,
    element_decisions: tuple[CreativeElementDecisionV2, ...],
    proposal_action: Literal["defer_topic", "exclude_element"],
    *,
    submission_id: str,
) -> GuidedProductionJourneyV2:
    if proposal_action == "defer_topic":
        return journey.model_copy(update={"stage_status": "waiting_user"})
    evidence_kind = {
        "world_view": "world_view_excluded",
        "props": "props_excluded",
        "character": "character_excluded",
        "bgm": "bgm_excluded",
    }.get(journey.stage)
    if evidence_kind is None:
        return journey.model_copy(update={"stage_status": "ready", "active_action": None})
    return policy.apply_evidence(
        JourneyPolicyContextV2(journey=journey),
        JourneyEvidenceV2(
            evidence_id=f"guided-state-action:{submission_id}",
            evidence_kind=cast(str, evidence_kind),
            source_id=submission_id,
            stage=journey.stage,
            stage_revision=journey.stage_revision,
            occurrence_id=(
                journey.active_action.occurrence_id if journey.active_action is not None else None
            ),
        ),
    )


def _validate_resume_proof(
    awaiting: GuidanceAwaitingV2,
    proof: GuidanceAwaitingResumeProofV2,
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


def _is_duration_questionnaire(content: GuidedQuestionnaireV1) -> bool:
    return len(content.questions) == 1 and content.questions[0].question_id == DURATION_QUESTION_ID


def _is_character_questionnaire(content: GuidedQuestionnaireV1) -> bool:
    return (
        len(content.questions) == 1
        and content.questions[0].question_id == CHARACTER_COUNT_QUESTION_ID
    )


def _duration_source_turn_id(interaction: GuidedInteractionV1) -> str:
    prefix = "duration:"
    if not interaction.checkpoint_id.startswith(prefix):
        raise _error(
            "guidance_resume_evidence_missing",
            "Duration interaction does not identify its source Turn.",
        )
    source_turn_id = interaction.checkpoint_id[len(prefix) :]
    if not source_turn_id:
        raise _error(
            "guidance_resume_evidence_missing",
            "Duration interaction does not identify its source Turn.",
        )
    return source_turn_id


def _character_source_turn_id(interaction: GuidedInteractionV1) -> str:
    prefix = "character-count:"
    parts = interaction.checkpoint_id.split(":")
    if not interaction.checkpoint_id.startswith(prefix) or not parts:
        raise _error(
            "guidance_resume_evidence_missing",
            "Character interaction does not identify its source Turn.",
        )
    source_turn_id = parts[-1]
    if not source_turn_id:
        raise _error(
            "guidance_resume_evidence_missing",
            "Character interaction does not identify its source Turn.",
        )
    return source_turn_id


def _dump(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="guided_interaction_repository")
