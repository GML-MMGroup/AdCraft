"""Atomic publication of concise capability results as public Proposals."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Mapping

from pydantic import BaseModel
from sqlalchemy import func, insert, select, update

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.agent_canvas_expert_activity_terminal_publication import (
    publish_expert_activity_terminal_in_transaction,
)
from app.persistence.models import (
    AgentCanvasChatEntryRow,
    AgentCanvasChatTurnRow,
    AgentCanvasConceptOptionRow,
    AgentCanvasConceptProposalRow,
    AgentCanvasContinuationOutboxRow,
    AgentCanvasGuidanceAwaitingRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasGuidanceTopicRow,
    AgentCanvasGuidedInteractionRow,
    AgentCanvasRequirementLedgerRow,
)
from app.schemas.agent_canvas_capabilities import CapabilityCommandEnvelopeV2
from app.schemas.agent_canvas_capability_identity import CAPABILITY_DISPLAY_NAMES
from app.schemas.agent_canvas_creative_session import (
    ProposedDraftReferenceV2,
    canonical_guidance_topic_kind,
)
from app.schemas.agent_canvas_guided_interactions import (
    GuidanceAwaitingV2,
    GuidedChoiceOptionV1,
    GuidedConceptChoiceV2,
    GuidedInteractionV1,
)
from app.schemas.agent_canvas_production_journey import GuidedProductionJourneyV2
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_production_journey import (
    FIXED_JOURNEY_STAGE_DESCRIPTORS,
    parse_production_journey,
)
from app.services.agent_canvas_proposal_cardinality import (
    proposal_candidate_count_details,
)
from app.services.agent_canvas_public_concept_projection import (
    AgentCanvasPublicConceptProjector,
    public_option_metadata,
)
from app.services.agent_canvas_user_presentation import build_presentation_metadata
from app.services.response_locale_resolver import ResponseLocaleResolverV1


_PROPOSAL_KIND = {
    "world_setting": "world_setting",
    "product_design": "product",
    "prop_design": "prop",
    "character_design": "character",
    "scene_design": "scene",
    "script_authoring": "script",
    "storyboard_design": "storyboard",
    "video_direction": "video",
    "bgm_direction": "bgm",
    "quick_media": "video",
}


class AgentCanvasCapabilityProposalRepository:
    """Commit one replay-safe capability result and its terminal operation state."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Capability Proposal and event repositories must share one database.")
        self._database = database
        self._events = events

    def publish(self, envelope: CapabilityCommandEnvelopeV2, result: BaseModel) -> str:
        if envelope.publication_kind != "proposal":
            raise V2PersistenceError(
                "capability_publication_mode_invalid",
                "Internal document commands cannot publish a public Proposal.",
                stage="capability_publication",
            )
        proposal_id = f"proposal_{_digest(envelope.envelope_id)[:32]}"
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat()
        options = tuple(getattr(result, "options", ()))
        details = proposal_candidate_count_details(envelope.candidate_count, result)
        if details is not None:
            raise V2PersistenceError(
                "proposal_candidate_count_mismatch",
                "Proposal result candidate count conflicts with its immutable envelope.",
                stage="capability_publication",
                details=details,
            )
        option_ids = tuple(
            f"option_{_digest(proposal_id, str(order))[:32]}" for order in range(len(options))
        )
        public_projection = (
            AgentCanvasPublicConceptProjector().project(
                options=options,
                option_ids=option_ids,
                response_locale=envelope.response_locale,
                recommended_option_id=option_ids[0],
            )
            if envelope.candidate_count == 3
            else None
        )
        response_locale = (
            public_projection.response_locale
            if public_projection is not None
            else ResponseLocaleResolverV1().resolve(envelope.response_locale)
        )
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    select(AgentCanvasConceptProposalRow.proposal_id).where(
                        AgentCanvasConceptProposalRow.proposal_id == proposal_id
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    connection.commit()
                    return str(existing)
                requirement_head = (
                    connection.execute(
                        select(AgentCanvasRequirementLedgerRow).where(
                            AgentCanvasRequirementLedgerRow.workflow_id == envelope.workflow_id
                        )
                    )
                    .mappings()
                    .one()
                )
                if (
                    str(requirement_head["current_revision_id"]) != envelope.requirement_revision_id
                    or int(requirement_head["current_revision_no"])
                    != envelope.requirement_revision_no
                ):
                    error = V2PersistenceError(
                        "requirement_revision_superseded",
                        "Requirements changed before capability publication.",
                        stage="capability_publication",
                    )
                    error.details = {
                        "retryable": False,
                        "current_requirement_revision_id": str(
                            requirement_head["current_revision_id"]
                        ),
                        "current_requirement_revision_no": int(
                            requirement_head["current_revision_no"]
                        ),
                    }
                    raise error
                session = (
                    connection.execute(
                        select(AgentCanvasGuidanceSessionRow).where(
                            AgentCanvasGuidanceSessionRow.workflow_id == envelope.workflow_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if session is None:
                    raise V2PersistenceError(
                        "guidance_session_not_found",
                        "Guidance session was not found.",
                        stage="capability_publication",
                    )
                if (
                    envelope.expected_session_revision is not None
                    and int(session["revision"]) != envelope.expected_session_revision
                ):
                    raise V2PersistenceError(
                        "guidance_revision_conflict",
                        "Guidance state changed before capability publication.",
                        stage="capability_publication",
                    )
                session_revision = int(session["revision"]) + 1
                topic_id = f"topic_{envelope.capability_id}"
                proposed_references = _project_references(envelope)
                creative_direction_snapshot_id = _style_snapshot_id(envelope.style_projection)
                topic = (
                    connection.execute(
                        select(AgentCanvasGuidanceTopicRow).where(
                            AgentCanvasGuidanceTopicRow.session_id == session["session_id"],
                            AgentCanvasGuidanceTopicRow.topic_id == topic_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                source_proposal_id = None
                if topic is None:
                    connection.execute(
                        insert(AgentCanvasGuidanceTopicRow).values(
                            session_id=session["session_id"],
                            topic_id=topic_id,
                            topic_kind=canonical_guidance_topic_kind(
                                _PROPOSAL_KIND[envelope.capability_id]
                            ),
                            title=CAPABILITY_DISPLAY_NAMES[envelope.capability_id],
                            status="proposed",
                            capability_id=envelope.capability_id,
                            related_node_ids_json="[]",
                            source_proposal_id=proposal_id,
                            revision=1,
                            created_at=timestamp,
                            updated_at=timestamp,
                        )
                    )
                elif str(topic["status"]) == "deferred":
                    if envelope.source_action not in {
                        "required_deferred_final_review",
                        "user_resumed_deferred_topic",
                    }:
                        raise V2PersistenceError(
                            "guidance_defer_conflict",
                            "Deferred guidance requires an explicit resume action.",
                            stage="capability_publication",
                        )
                    source_proposal_id = (
                        str(topic["source_proposal_id"])
                        if topic["source_proposal_id"] is not None
                        else None
                    )
                    connection.execute(
                        update(AgentCanvasGuidanceTopicRow)
                        .where(
                            AgentCanvasGuidanceTopicRow.session_id == session["session_id"],
                            AgentCanvasGuidanceTopicRow.topic_id == topic_id,
                        )
                        .values(
                            status="proposed",
                            source_proposal_id=proposal_id,
                            revision=int(topic["revision"]) + 1,
                            updated_at=timestamp,
                        )
                    )
                connection.execute(
                    insert(AgentCanvasConceptProposalRow).values(
                        proposal_id=proposal_id,
                        turn_id=envelope.capability_turn_id,
                        workflow_id=envelope.workflow_id,
                        proposal_kind=_PROPOSAL_KIND[envelope.capability_id],
                        capability_id=envelope.capability_id,
                        video_skill_run_id=envelope.style_skill_run_id,
                        topic_id=topic_id,
                        target_node_id=None,
                        target_node_revision=None,
                        proposal_purpose=envelope.objective,
                        creative_direction_snapshot_id=creative_direction_snapshot_id,
                        requirement_revision_id=envelope.requirement_revision_id,
                        requirement_revision_no=envelope.requirement_revision_no,
                        requirement_digest=envelope.requirement_digest,
                        proposal_revision=1,
                        proposed_references_json=json.dumps(
                            [
                                reference.model_dump(mode="json")
                                for reference in proposed_references
                            ],
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        source_proposal_id=source_proposal_id,
                        availability="open",
                        guidance_session_id=session["session_id"],
                        guidance_session_revision=session_revision,
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
                for order, option in enumerate(options):
                    option_id = option_ids[order]
                    public_summary = str(option.public_summary)
                    connection.execute(
                        insert(AgentCanvasConceptOptionRow).values(
                            option_id=option_id,
                            proposal_id=proposal_id,
                            display_order=order,
                            title=str(option.title),
                            description=public_summary,
                            key_decisions_json=json.dumps(
                                list(option.key_decisions),
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                            draft_seed_schema=None,
                            draft_seed_json=None,
                            draft_seed_digest=None,
                        )
                    )
                interaction, awaiting, journey = _concept_interaction(
                    envelope=envelope,
                    proposal_id=proposal_id,
                    session=session,
                    session_revision=session_revision,
                    public_options=(public_projection.options if public_projection else ()),
                    response_locale=response_locale,
                    now=now,
                )
                if interaction is not None and awaiting is not None:
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
                            allowed_actions_json=json.dumps(
                                list(interaction.allowed_actions),
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                            submit_path=interaction.submit_path,
                            created_at=timestamp,
                            updated_at=timestamp,
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
                            created_at=timestamp,
                        )
                    )
                connection.execute(
                    update(AgentCanvasGuidanceSessionRow)
                    .where(AgentCanvasGuidanceSessionRow.session_id == session["session_id"])
                    .values(
                        active_proposal_id=(proposal_id if public_projection is not None else None),
                        current_topic_id=topic_id,
                        journey_state_json=journey.model_dump_json(),
                        revision=session_revision,
                        updated_at=timestamp,
                    )
                )
                connection.execute(
                    update(AgentCanvasChatTurnRow)
                    .where(AgentCanvasChatTurnRow.turn_id == envelope.capability_turn_id)
                    .values(
                        status="completed",
                        guidance_session_revision=session_revision,
                        error_code=None,
                        error_message=None,
                        updated_at=timestamp,
                    )
                )
                activity_publication = publish_expert_activity_terminal_in_transaction(
                    connection,
                    self._events,
                    turn_id=envelope.capability_turn_id,
                    status="completed",
                    response_locale=response_locale,
                    now=timestamp,
                )
                if not activity_publication.changed:
                    raise V2PersistenceError(
                        "expert_activity_terminal",
                        "Expert activity already reached a terminal state.",
                        stage="capability_publication",
                    )
                connection.execute(
                    update(AgentCanvasContinuationOutboxRow)
                    .where(
                        AgentCanvasContinuationOutboxRow.continuation_turn_id
                        == envelope.capability_turn_id
                    )
                    .values(
                        status="completed",
                        lease_owner=None,
                        lease_expires_at=None,
                        last_error_code=None,
                        last_error_message=None,
                        updated_at=timestamp,
                    )
                )
                sequence_no = (
                    int(
                        connection.execute(
                            select(
                                func.coalesce(func.max(AgentCanvasChatEntryRow.sequence_no), 0)
                            ).where(
                                AgentCanvasChatEntryRow.conversation_id == envelope.conversation_id
                            )
                        ).scalar_one()
                    )
                    + 1
                )
                if public_projection is not None:
                    connection.execute(
                        insert(AgentCanvasChatEntryRow).values(
                            entry_id=f"entry_{_digest(proposal_id)[:32]}",
                            conversation_id=envelope.conversation_id,
                            workflow_id=envelope.workflow_id,
                            sequence_no=sequence_no,
                            entry_type="concept_proposal",
                            speaker="adcraft_video_agent",
                            content=f"Review {len(options)} option(s).",
                            metadata_json=json.dumps(
                                build_presentation_metadata(
                                    message_key="concept_proposal.review",
                                    message_args={"option_count": len(options)},
                                    response_locale=response_locale,
                                    presentation_key=f"proposal:{proposal_id}",
                                    base={
                                        "proposal_id": proposal_id,
                                        "capability_id": envelope.capability_id,
                                        "capability_display_name": CAPABILITY_DISPLAY_NAMES[
                                            envelope.capability_id
                                        ],
                                        "proposal_revision": 1,
                                        "options": [
                                            public_option_metadata(option)
                                            for option in public_projection.options
                                        ],
                                    },
                                ),
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                            created_at=timestamp,
                        )
                    )
                publication_events: list[tuple[str, dict[str, object]]] = [
                    (
                        "concept_proposal_created",
                        {
                            "proposal_id": proposal_id,
                            "capability_id": envelope.capability_id,
                            "option_count": len(options),
                            "source_action": envelope.source_action,
                            "source_proposal_id": source_proposal_id,
                            "reference_count": len(proposed_references),
                            "reference_plan_digest": envelope.reference_plan.digest,
                        },
                    ),
                ]
                if interaction is not None:
                    publication_events.append(
                        (
                            "guided_interaction_opened",
                            {
                                "interaction_id": interaction.interaction_id,
                                "session_id": interaction.session_id,
                                "checkpoint_id": interaction.checkpoint_id,
                                "kind": interaction.kind,
                                "interaction_revision": interaction.revision,
                            },
                        )
                    )
                if awaiting is not None:
                    publication_events.append(
                        (
                            "guidance_awaiting_entered",
                            {
                                "awaiting_id": awaiting.awaiting_id,
                                "session_id": awaiting.session_id,
                                "checkpoint_id": awaiting.checkpoint_id,
                                "kind": awaiting.kind,
                                "resume_policy": awaiting.resume_policy,
                                "interaction_id": awaiting.interaction_id,
                                "node_ids": [],
                            },
                        )
                    )
                publication_events.extend(
                    [
                        (
                            "agent_command_completed",
                            {
                                "envelope_id": envelope.envelope_id,
                                "proposal_id": proposal_id,
                            },
                        ),
                    ]
                )
                for event_type, payload in publication_events:
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=envelope.workflow_id,
                            conversation_id=envelope.conversation_id,
                            turn_id=envelope.capability_turn_id,
                            event_type=event_type,
                            transition_key=(
                                f"conversation:{envelope.capability_turn_id}:{event_type}"
                            ),
                            created_at=timestamp,
                            payload=payload,
                        ),
                    )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return proposal_id


def _concept_interaction(
    *,
    envelope: CapabilityCommandEnvelopeV2,
    proposal_id: str,
    session: Mapping[str, object],
    session_revision: int,
    public_options: tuple[GuidedChoiceOptionV1, ...],
    response_locale: str,
    now: datetime,
) -> tuple[
    GuidedInteractionV1 | None,
    GuidanceAwaitingV2 | None,
    GuidedProductionJourneyV2,
]:
    journey = parse_production_journey(str(session["journey_state_json"]))
    if len(public_options) != 3 or journey.active_action is None:
        return None, None, journey

    checkpoint_id = f"checkpoint_{_digest(str(session['session_id']), journey.stage, str(journey.stage_revision))[:32]}"
    interaction_id = f"interaction_{_digest(proposal_id, 'interaction')[:32]}"
    awaiting_id = f"awaiting_{_digest(proposal_id, 'awaiting')[:32]}"
    content = GuidedConceptChoiceV2(
        proposal_id=proposal_id,
        stage=journey.stage,
        stage_revision=journey.stage_revision,
        action_id=journey.active_action.action_id,
        occurrence_id=journey.active_action.occurrence_id,
        capability_id=envelope.capability_id,
        options=public_options,
        allow_exclusion=FIXED_JOURNEY_STAGE_DESCRIPTORS[journey.stage].optional,
    )
    interaction = GuidedInteractionV1(
        interaction_id=interaction_id,
        workflow_id=envelope.workflow_id,
        session_id=str(session["session_id"]),
        checkpoint_id=checkpoint_id,
        kind="concept_choice",
        status="open",
        response_locale=response_locale,
        expected_session_revision=session_revision,
        revision=1,
        title=_bounded_text(
            " / ".join(option.title for option in public_options),
            limit=160,
        ),
        context=_bounded_text(envelope.objective, limit=1_024),
        content=content,
        allowed_actions=(
            ("select", "custom", "defer")
            + (("exclude",) if FIXED_JOURNEY_STAGE_DESCRIPTORS[journey.stage].optional else ())
            + ("delegate",)
        ),
        submit_path=(
            f"/api/v2/workflows/{envelope.workflow_id}/chat/interactions/{interaction_id}/submit"
        ),
        created_at=now,
        updated_at=now,
    )
    awaiting = GuidanceAwaitingV2(
        awaiting_id=awaiting_id,
        workflow_id=envelope.workflow_id,
        session_id=str(session["session_id"]),
        checkpoint_id=checkpoint_id,
        kind="concept_selection",
        requires_user_action=True,
        resume_policy="submit_interaction",
        interaction_id=interaction_id,
        stage=journey.stage,
        stage_revision=journey.stage_revision,
        created_at=now,
    )
    return interaction, awaiting, journey.model_copy(update={"stage_status": "waiting_user"})


def _bounded_text(value: object, *, limit: int) -> str:
    text = str(value).strip()
    return (text or "Option")[:limit]


def _project_references(
    envelope: CapabilityCommandEnvelopeV2,
) -> tuple[ProposedDraftReferenceV2, ...]:
    return tuple(
        ProposedDraftReferenceV2(
            source_kind=reference.source_kind,
            source_id=reference.source_id,
            binding_kind=reference.input_role,
            input_role=reference.input_role,
            required=reference.required,
            display_order=index,
            semantic_reference_role=reference.semantic_reference_role,
            display_name=reference.display_name,
            media_type=reference.media_type,
        )
        for index, reference in enumerate(envelope.reference_plan.references)
    )


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _style_snapshot_id(style_projection: dict[str, object]) -> str | None:
    value = style_projection.get("creative_direction_snapshot_id")
    return value if isinstance(value, str) and value else None
