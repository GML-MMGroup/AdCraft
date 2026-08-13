"""Atomic publication of concise capability results as public Proposals."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import func, insert, select, update

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasChatEntryRow,
    AgentCanvasChatTurnRow,
    AgentCanvasConceptOptionRow,
    AgentCanvasConceptProposalRow,
    AgentCanvasContinuationOutboxRow,
    AgentCanvasExpertActivityRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasGuidanceTopicRow,
    AgentCanvasRequirementLedgerRow,
)
from app.schemas.agent_canvas_capabilities import CapabilityCommandEnvelopeV2
from app.schemas.agent_canvas_capability_identity import CAPABILITY_DISPLAY_NAMES
from app.schemas.agent_canvas_creative_session import (
    ProposedDraftReferenceV2,
    canonical_guidance_topic_kind,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_user_presentation import build_presentation_metadata


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
        proposal_id = f"proposal_{_digest(envelope.envelope_id)[:32]}"
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat()
        options = tuple(getattr(result, "options", ()))
        if not options:
            raise V2PersistenceError(
                "capability_contract_invalid",
                "Capability result contains no Proposal options.",
                stage="capability_publication",
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
                public_options: list[dict[str, object]] = []
                for order, option in enumerate(options):
                    option_id = f"option_{_digest(proposal_id, str(order))[:32]}"
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
                    public_options.append(
                        {
                            "option_id": option_id,
                            "title": str(option.title),
                            "public_summary": public_summary,
                            "key_decisions": list(option.key_decisions),
                        }
                    )
                connection.execute(
                    update(AgentCanvasGuidanceSessionRow)
                    .where(AgentCanvasGuidanceSessionRow.session_id == session["session_id"])
                    .values(
                        active_proposal_id=proposal_id,
                        current_topic_id=topic_id,
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
                connection.execute(
                    update(AgentCanvasExpertActivityRow)
                    .where(AgentCanvasExpertActivityRow.turn_id == envelope.capability_turn_id)
                    .values(status="completed", updated_at=timestamp)
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
                                response_locale=envelope.response_locale,
                                presentation_key=f"proposal:{proposal_id}",
                                base={
                                    "proposal_id": proposal_id,
                                    "capability_id": envelope.capability_id,
                                    "capability_display_name": CAPABILITY_DISPLAY_NAMES[
                                        envelope.capability_id
                                    ],
                                    "proposal_revision": 1,
                                    "options": public_options,
                                },
                            ),
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        created_at=timestamp,
                    )
                )
                for event_type, payload in (
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
                    (
                        "expert_activity_completed",
                        {
                            "capability_id": envelope.capability_id,
                            "status": "completed",
                        },
                    ),
                    (
                        "agent_command_completed",
                        {
                            "envelope_id": envelope.envelope_id,
                            "proposal_id": proposal_id,
                        },
                    ),
                ):
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
