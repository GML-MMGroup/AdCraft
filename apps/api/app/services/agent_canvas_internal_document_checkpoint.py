"""Atomic publication for internal fixed-journey Script checkpoints."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import select, update

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_expert_activity_terminal_publication import (
    publish_expert_activity_terminal_in_transaction,
)
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.agent_working_document_repository import AgentWorkingDocumentRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasChatTurnRow,
    AgentCanvasContinuationOutboxRow,
    AgentCanvasGuidanceSessionRow,
    AgentWorkingDocumentPatchReceiptRow,
)
from app.schemas.agent_canvas_capabilities import CapabilityCommandEnvelopeV2
from app.schemas.agent_canvas_conversation import ContinuationCommitV2
from app.schemas.agent_canvas_materialization import ScriptMaterializationResultV1
from app.schemas.agent_canvas_production_journey import (
    JourneyEvidenceKindV2,
    JourneyEvidenceV2,
    JourneyStageV2,
)
from app.schemas.agent_working_documents import (
    AgentWorkingDocumentV2,
    StoryboardNarrativeSegmentV2,
    StoryboardPlanGlobalParametersV2,
    StoryboardProductionPlanContentV3,
    StoryboardSegmentMaterializationV3,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_production_journey import (
    GuidedProductionJourneyPolicyService,
    parse_production_journey,
)
from app.services.agent_canvas_guided_duration import GuidedDurationAuthorityPolicy
from app.services.response_locale_resolver import ResponseLocaleResolverV1


_EVIDENCE_KIND: dict[JourneyStageV2, JourneyEvidenceKindV2] = {
    "narrative_direction": "narrative_direction_accepted",
    "style_lock": "style_lock_accepted",
    "storyboard_plan": "storyboard_plan_accepted",
}


class AgentCanvasInternalDocumentCheckpointPublisher:
    """Commit a document checkpoint, journey evidence, and continuation once."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Internal checkpoints and events must share one database.")
        self._database = database
        self._events = events
        self._documents = AgentWorkingDocumentRepository(database, events)
        self._requirements = AgentCanvasRequirementRepository(database)
        self._conversations = AgentCanvasConversationRepository(database, events)
        self._journey_policy = GuidedProductionJourneyPolicyService()
        self._duration_authority = GuidedDurationAuthorityPolicy()
        self._locale_resolver = ResponseLocaleResolverV1()

    def publish(self, envelope: CapabilityCommandEnvelopeV2, result: BaseModel) -> str:
        stage = self._validate_envelope(envelope)
        typed_result = ScriptMaterializationResultV1.model_validate(result)
        authored_text = _authored_text(typed_result)
        document_id = _document_id(envelope)
        idempotency_key = f"internal-checkpoint:{envelope.envelope_id}"
        request_digest = _request_digest(envelope, typed_result)
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat()

        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                replay = _receipt(
                    connection,
                    document_id=document_id,
                    idempotency_key=idempotency_key,
                )
                if replay is not None:
                    if str(replay["request_digest"]) != request_digest:
                        raise _error(
                            "agent_document_idempotency_conflict",
                            "The checkpoint key was already used for another result.",
                        )
                    connection.commit()
                    return str(replay["receipt_id"])

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
                    raise _error("guidance_session_not_found", "Guidance session was not found.")
                if envelope.session_id != str(
                    session["session_id"]
                ) or envelope.expected_session_revision != int(session["revision"]):
                    raise _error(
                        "guidance_revision_conflict",
                        "Guidance state changed before the internal checkpoint.",
                    )
                journey = parse_production_journey(str(session["journey_state_json"]))
                if journey.stage != stage or journey.active_action is None:
                    raise _error(
                        "journey_stage_action_mismatch",
                        "The internal checkpoint does not own the current journey action.",
                    )

                current = self._documents.get_by_kind(
                    envelope.workflow_id,
                    str(session["session_id"]),
                    "storyboard_production_plan",
                )
                next_content = self._compile_content(
                    connection,
                    envelope=envelope,
                    stage=stage,
                    authored_text=authored_text,
                    current=current,
                )
                if current is None:
                    self._documents.create_in_transaction(
                        connection,
                        workflow_id=envelope.workflow_id,
                        guidance_session_id=str(session["session_id"]),
                        kind="storyboard_production_plan",
                        title="Storyboard Production Plan",
                        content=next_content,
                        agent_run_id=envelope.capability_turn_id,
                        idempotency_key=idempotency_key,
                        request_digest=request_digest,
                        now=now,
                        document_id=document_id,
                    )
                else:
                    self._documents.apply_content_in_transaction(
                        connection,
                        document_id=current.document_id,
                        expected_revision=current.revision,
                        operation=f"accept_{stage}",
                        content=next_content,
                        agent_run_id=envelope.capability_turn_id,
                        idempotency_key=idempotency_key,
                        now=now,
                        request_digest=request_digest,
                    )

                evidence = JourneyEvidenceV2(
                    evidence_id=f"evidence_{_digest(envelope.envelope_id, stage)[:32]}",
                    evidence_kind=_EVIDENCE_KIND[stage],
                    source_id=document_id,
                    source_revision=(current.revision + 1 if current is not None else 1),
                    stage=stage,
                    stage_revision=journey.stage_revision,
                    action_id=journey.active_action.action_id,
                    actor="system",
                )
                next_journey = self._journey_policy.apply_evidence(
                    journey,
                    evidence,
                    recorded_at=now,
                )
                next_session_revision = int(session["revision"]) + 1
                updated = connection.execute(
                    update(AgentCanvasGuidanceSessionRow)
                    .where(
                        AgentCanvasGuidanceSessionRow.session_id == session["session_id"],
                        AgentCanvasGuidanceSessionRow.revision == int(session["revision"]),
                    )
                    .values(
                        journey_state_json=next_journey.model_dump_json(),
                        revision=next_session_revision,
                        updated_at=timestamp,
                    )
                )
                if updated.rowcount != 1:
                    raise _error(
                        "guidance_revision_conflict",
                        "Guidance state changed before the internal checkpoint.",
                    )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=envelope.workflow_id,
                        conversation_id=envelope.conversation_id,
                        turn_id=envelope.capability_turn_id,
                        event_type="journey_stage_changed",
                        transition_key=f"journey:{session['session_id']}:{evidence.evidence_id}",
                        created_at=timestamp,
                        payload={
                            "session_id": str(session["session_id"]),
                            "session_revision": next_session_revision,
                            "previous_stage": stage,
                            "next_stage": next_journey.stage,
                            "evidence_id": evidence.evidence_id,
                            "evidence_kind": evidence.evidence_kind,
                            "document_id": document_id,
                        },
                    ),
                )
                connection.execute(
                    update(AgentCanvasChatTurnRow)
                    .where(AgentCanvasChatTurnRow.turn_id == envelope.capability_turn_id)
                    .values(
                        status="completed",
                        guidance_session_revision=next_session_revision,
                        error_code=None,
                        error_message=None,
                        updated_at=timestamp,
                    )
                )
                activity = publish_expert_activity_terminal_in_transaction(
                    connection,
                    self._events,
                    turn_id=envelope.capability_turn_id,
                    status="completed",
                    response_locale=self._locale_resolver.resolve(str(session["response_locale"])),
                    now=timestamp,
                    event_details={"document_id": document_id, "journey_stage": stage},
                )
                if not activity.changed:
                    raise _error(
                        "expert_activity_terminal",
                        "Expert activity already reached a terminal state.",
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
                continuation_identity = _digest(envelope.envelope_id, "next-action")
                self._conversations.insert_continuation_in_transaction(
                    connection,
                    workflow_id=envelope.workflow_id,
                    conversation_id=envelope.conversation_id,
                    continuation=ContinuationCommitV2(
                        continuation_id=f"continuation_{continuation_identity[:24]}",
                        continuation_turn_id=f"turn_{continuation_identity[24:56]}",
                        source_turn_id=envelope.capability_turn_id,
                        source_action_id=envelope.envelope_id,
                        idempotency_key=f"internal-checkpoint-next:{envelope.envelope_id}",
                        video_skill_run_id=envelope.style_skill_run_id,
                    ),
                    now=timestamp,
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=envelope.workflow_id,
                        conversation_id=envelope.conversation_id,
                        turn_id=envelope.capability_turn_id,
                        event_type="agent_command_completed",
                        transition_key=(
                            f"conversation:{envelope.capability_turn_id}:agent_command_completed"
                        ),
                        created_at=timestamp,
                        payload={
                            "envelope_id": envelope.envelope_id,
                            "operation": "author_guided_script_checkpoint",
                            "document_id": document_id,
                        },
                    ),
                )
                receipt = _receipt(
                    connection,
                    document_id=document_id,
                    idempotency_key=idempotency_key,
                )
                if receipt is None:
                    raise _error(
                        "agent_document_receipt_missing",
                        "The internal document receipt was not persisted.",
                    )
                connection.commit()
                return str(receipt["receipt_id"])
            except BaseException:
                connection.rollback()
                raise

    def _compile_content(
        self,
        connection,
        *,
        envelope: CapabilityCommandEnvelopeV2,
        stage: JourneyStageV2,
        authored_text: str,
        current: AgentWorkingDocumentV2 | None,
    ) -> StoryboardProductionPlanContentV3:
        if current is not None:
            if not isinstance(current.content, StoryboardProductionPlanContentV3):
                raise _error(
                    "agent_storyboard_plan_invalid",
                    "The internal checkpoint requires the authoritative Storyboard Plan.",
                )
            requirement = self._requirements.get_current_in_transaction(
                connection,
                envelope.workflow_id,
            )
            self._duration_authority.validate_plan(requirement, current.content)
            label = "Style lock" if stage == "style_lock" else "Storyboard plan"
            outline = f"{current.content.narrative_outline}\n{label}: {authored_text}"
            return current.content.model_copy(update={"narrative_outline": outline})
        if stage != "narrative_direction":
            raise _error(
                "agent_document_not_found",
                "Narrative Direction must create the Storyboard Plan first.",
            )
        requirement = self._requirements.get_current_in_transaction(
            connection,
            envelope.workflow_id,
        )
        constraints = dict((envelope.capability_context or {}).get("explicit_constraints", {}))
        constraints.update(
            {control.control: control.value for control in requirement.ledger.hard_controls}
        )
        authority_plan = self._duration_authority.plan_sequences(
            requirement,
            aspect_ratio=constraints.get("aspect_ratio", "16:9"),
            explicit_sequence_count=constraints.get("storyboard_sequence_count"),
        )
        segments = tuple(
            StoryboardNarrativeSegmentV2(
                sequence_id=f"sequence-{window.order}",
                order=window.order,
                start_seconds=window.start_seconds,
                end_seconds=window.end_seconds,
                narrative_goal=(
                    f"Sequence {window.order} local narrative direction "
                    f"({window.start_seconds:g}-{window.end_seconds:g}s)."
                ),
                start_state=("Opening state" if window.order == 1 else "Continue prior sequence."),
                end_state=(
                    "Close the authored direction."
                    if window.order == len(authority_plan.windows)
                    else "Hand off to the next sequence."
                ),
                continuity_from_previous=(
                    None if window.order == 1 else "Continue from the prior sequence."
                ),
                terminal_policy=(
                    "close" if window.order == len(authority_plan.windows) else "continue"
                ),
            )
            for window in authority_plan.windows
        )
        return StoryboardProductionPlanContentV3(
            narrative_outline=authored_text,
            requirement_revision_id=requirement.revision_id,
            requirement_revision_no=requirement.revision_no,
            global_parameters=StoryboardPlanGlobalParametersV2(
                aspect_ratio=authority_plan.aspect_ratio,
                total_duration_seconds=authority_plan.total_duration_seconds,
                segment_count=len(authority_plan.windows),
            ),
            segments=segments,
            rows=(),
            segment_materializations=tuple(
                StoryboardSegmentMaterializationV3(
                    sequence_id=segment.sequence_id,
                    materialization_id=f"storyboard-segment:{segment.sequence_id}",
                )
                for segment in segments
            ),
        )

    @staticmethod
    def _validate_envelope(envelope: CapabilityCommandEnvelopeV2) -> JourneyStageV2:
        if (
            envelope.publication_kind != "internal_document"
            or envelope.capability_id != "script_authoring"
            or envelope.journey_stage not in _EVIDENCE_KIND
        ):
            raise _error(
                "capability_publication_mode_invalid",
                "The command is not an internal Script checkpoint.",
            )
        return envelope.journey_stage


def _authored_text(result: ScriptMaterializationResultV1) -> str:
    text = result.structured_content.content.strip() or result.summary_prompt.strip()
    if not text:
        raise _error(
            "guided_document_content_invalid",
            "Internal document authorship requires non-empty content.",
        )
    return text


def _document_id(envelope: CapabilityCommandEnvelopeV2) -> str:
    return (
        "adoc_"
        + _digest(
            envelope.workflow_id,
            envelope.session_id or "",
            "storyboard-production-plan",
        )[:32]
    )


def _request_digest(
    envelope: CapabilityCommandEnvelopeV2,
    result: ScriptMaterializationResultV1,
) -> str:
    payload = json.dumps(
        {
            "envelope_id": envelope.envelope_id,
            "journey_stage": envelope.journey_stage,
            "result": result.model_dump(mode="json"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _receipt(connection, *, document_id: str, idempotency_key: str):
    return (
        connection.execute(
            select(AgentWorkingDocumentPatchReceiptRow).where(
                AgentWorkingDocumentPatchReceiptRow.document_id == document_id,
                AgentWorkingDocumentPatchReceiptRow.idempotency_key == idempotency_key,
            )
        )
        .mappings()
        .one_or_none()
    )


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="internal_document_checkpoint")
