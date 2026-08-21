"""Atomic accepted-command dispatch for Agent Canvas capabilities."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, insert, select

from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.agent_canvas_conversation_repository import (
    _complete_turn_state_in_transaction,
    _publish_assistant_message_in_transaction,
)
from app.persistence.agent_canvas_operation_envelope_repository import (
    AgentCanvasOperationEnvelopeRepository,
)
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasChatEntryRow,
    AgentCanvasChatTurnRow,
    AgentCanvasExpertActivityRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasNodeRow,
    AgentCanvasWorkflowRow,
)
from app.schemas.agent_canvas_capabilities import (
    CapabilityCommandEnvelopeV2,
    CapabilityContextSnapshotV2,
    CapabilityDispatchReceiptV1,
    ValidatedNextActionV1,
)
from app.services.agent_canvas_guided_interaction_policy import (
    GuidedInteractionPolicyService,
)
from app.services.agent_canvas_requirement_projection import requirement_projection_digest
from app.services.agent_canvas_user_presentation import build_presentation_metadata
from app.schemas.agent_canvas_conversation import ChatTurnV2
from app.schemas.agent_canvas_guidance import ContinuationTurnRetrySnapshotV1
from app.schemas.agent_canvas_production_journey import JourneyStageV2
from app.services.agent_canvas_production_journey import parse_production_journey
from app.schemas.language import BCP47Tag
from app.schemas.v2_persistence import V2EventInsert


logger = logging.getLogger(__name__)
_RETRY_REFERENCE_PROJECTION_VERSION = "capability-retry-reference-kind-partition-v1"


class SourceTurnReplyPublicationV1(BaseModel):
    """Private source-turn reply accepted by atomic capability dispatch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str = Field(min_length=1, max_length=2_000)
    response_locale: BCP47Tag

    @field_validator("content", mode="before")
    @classmethod
    def strip_content(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


@dataclass(frozen=True, slots=True)
class RetryReferenceAuthorityProjection:
    """Store-specific authority derived from typed capability references."""

    node_ids: tuple[str, ...]
    image_asset_ids: tuple[str, ...]


def _stable_unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _project_retry_reference_authority(
    context_snapshot: CapabilityContextSnapshotV2,
) -> RetryReferenceAuthorityProjection:
    planned_ids = context_snapshot.reference_plan.approved_reference_ids
    if tuple(context_snapshot.approved_reference_ids) != tuple(planned_ids):
        raise V2PersistenceError(
            "capability_retry_reference_projection_invalid",
            "Capability retry reference authority is inconsistent.",
            stage="capability_retry_snapshot_construction",
        )

    node_ids: list[str] = []
    image_asset_ids: list[str] = []
    for reference in context_snapshot.reference_plan.references:
        if reference.source_kind == "node":
            node_ids.append(reference.source_id)
        elif reference.source_kind == "image_asset":
            image_asset_ids.append(reference.source_id)
        else:
            raise V2PersistenceError(
                "capability_retry_reference_projection_invalid",
                "Capability retry reference kind is unsupported.",
                stage="capability_retry_snapshot_construction",
            )
    return RetryReferenceAuthorityProjection(
        node_ids=_stable_unique(node_ids),
        image_asset_ids=_stable_unique(image_asset_ids),
    )


class CapabilityDispatchService:
    """Persist one accepted capability command before waking its worker."""

    def __init__(
        self,
        *,
        database: V2Database,
        events: EventRepository,
        wake_worker: Callable[[], object] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._database = database
        self._events = events
        self._envelopes = AgentCanvasOperationEnvelopeRepository(database)
        self._outbox = AgentCanvasContinuationOutboxRepository(database, events)
        self._wake_worker = wake_worker
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def dispatch_next_action(
        self,
        source_turn: ChatTurnV2,
        command: ValidatedNextActionV1,
        context_snapshot: CapabilityContextSnapshotV2,
        *,
        session_id: str | None = None,
        expected_session_revision: int | None = None,
        allow_completed_source_replacement: bool = False,
        source_reply: SourceTurnReplyPublicationV1 | None = None,
        publication_kind: str = "proposal",
        journey_stage: JourneyStageV2 | None = None,
    ) -> CapabilityDispatchReceiptV1:
        if command.definition is None or command.command.capability_id is None:
            raise ValueError("Capability dispatch requires an invoke-capability command.")
        capability_id = command.command.capability_id
        objective = command.command.objective or ""
        identity = _digest(
            source_turn.turn_id,
            capability_id,
            objective,
            context_snapshot.digest,
            str(expected_session_revision or source_turn.guidance_session_revision or ""),
            publication_kind,
            journey_stage or "",
        )
        envelope_id = f"envelope_{identity[:32]}"
        capability_turn_id = f"turn_{identity[32:]}"
        continuation_id = f"continuation_{identity[:24]}"
        activity_id = f"activity_{identity[8:32]}"
        source_reply_entry_id = f"msg_{_digest('source_reply', identity)[:32]}"
        now = self._clock().astimezone(timezone.utc)
        projection = context_snapshot.requirement_projection
        interaction_policy = GuidedInteractionPolicyService().decide_candidate_count(
            projection,
            default_candidate_count=command.definition.default_candidate_count,
        )
        candidate_count = (
            1 if publication_kind == "internal_document" else interaction_policy.candidate_count
        )
        envelope = CapabilityCommandEnvelopeV2(
            envelope_id=envelope_id,
            workflow_id=source_turn.workflow_id,
            conversation_id=source_turn.conversation_id,
            source_turn_id=source_turn.turn_id,
            capability_turn_id=capability_turn_id,
            session_id=session_id,
            expected_session_revision=(
                expected_session_revision or source_turn.guidance_session_revision
            ),
            capability_id=capability_id,
            publication_kind=publication_kind,
            journey_stage=journey_stage,
            source_action=command.source_action,
            objective=objective,
            context_snapshot_id=context_snapshot.snapshot_id,
            context_snapshot_digest=context_snapshot.digest,
            requirement_revision_id=projection.ledger_revision_id,
            requirement_revision_no=projection.ledger_revision_no,
            requirement_digest=projection.ledger_digest,
            requirement_projection_digest=requirement_projection_digest(projection),
            requirement_projection=projection,
            style_skill_run_id=_style_skill_run_id(context_snapshot),
            capability_context=context_snapshot.capability_context,
            style_projection=context_snapshot.style_projection,
            result_contract_name=command.definition.result_contract_name,
            candidate_count=candidate_count,
            reference_allowlist=context_snapshot.approved_reference_ids,
            reference_plan=context_snapshot.reference_plan,
            agent_request_identity=f"capability:{identity}",
            created_at=now,
            response_locale=context_snapshot.response_locale,
        )
        timestamp = now.isoformat()
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                current = (
                    connection.execute(
                        select(AgentCanvasChatTurnRow).where(
                            AgentCanvasChatTurnRow.turn_id == source_turn.turn_id
                        )
                    )
                    .mappings()
                    .one()
                )
                try:
                    existing = self._envelopes.get_in_transaction(connection, envelope_id)
                except V2PersistenceError as error:
                    if error.code != "operation_envelope_not_found":
                        raise
                    existing = None
                if existing is not None:
                    if not isinstance(existing, CapabilityCommandEnvelopeV2):
                        raise ValueError(
                            "Operation envelope type conflicts with capability dispatch."
                        )
                    _validate_existing_source_reply(
                        connection,
                        entry_id=source_reply_entry_id,
                        source_reply=source_reply,
                    )
                    connection.commit()
                    return CapabilityDispatchReceiptV1(
                        envelope_id=existing.envelope_id,
                        continuation_id=continuation_id,
                        capability_turn_id=existing.capability_turn_id,
                        capability_id=existing.capability_id,
                        activity_id=activity_id,
                        queued_at=existing.created_at,
                    )
                if str(current["status"]) == "completed" and not allow_completed_source_replacement:
                    raise V2PersistenceError(
                        "operation_envelope_not_found",
                        "Operation envelope was not found.",
                        stage="capability_dispatch",
                    )
                if str(current["turn_kind"]) == "message" and source_reply is None:
                    raise V2PersistenceError(
                        "capability_source_reply_missing",
                        "Message-source capability dispatch requires a visible reply.",
                        stage="capability_dispatch",
                    )
                if source_reply is not None:
                    _publish_assistant_message_in_transaction(
                        connection,
                        events=self._events,
                        turn=current,
                        assistant_message=source_reply.content,
                        now=timestamp,
                        entry_id=source_reply_entry_id,
                        metadata={
                            "response_locale": source_reply.response_locale,
                            "presentation_key": f"source-reply:{envelope_id}",
                            "dispatch_identity": envelope_id,
                        },
                    )
                connection.execute(
                    insert(AgentCanvasChatTurnRow).values(
                        turn_id=capability_turn_id,
                        conversation_id=source_turn.conversation_id,
                        workflow_id=source_turn.workflow_id,
                        turn_kind="capability",
                        status="queued",
                        request_json=json.dumps(
                            {"schema_version": "1", "envelope_id": envelope_id},
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        creation_mode_json=None,
                        guidance_session_revision=source_turn.guidance_session_revision,
                        idempotency_key=f"capability:{envelope_id}",
                        retry_snapshot_json=_retry_snapshot_json(
                            connection,
                            envelope=envelope,
                            source_turn=source_turn,
                            context_snapshot=context_snapshot,
                        ),
                        error_code=None,
                        error_message=None,
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
                self._envelopes.create_in_transaction(connection, envelope)
                self._outbox.enqueue_in_transaction(
                    connection,
                    continuation_id=continuation_id,
                    workflow_id=source_turn.workflow_id,
                    conversation_id=source_turn.conversation_id,
                    source_turn_id=source_turn.turn_id,
                    continuation_turn_id=capability_turn_id,
                    operation="capability_command",
                    payload={"schema_version": "1", "envelope_id": envelope_id},
                    max_attempts=5,
                    now=now,
                )
                connection.execute(
                    insert(AgentCanvasExpertActivityRow).values(
                        activity_id=activity_id,
                        turn_id=capability_turn_id,
                        workflow_id=source_turn.workflow_id,
                        capability_id=capability_id,
                        operation=command.definition.operation,
                        status="working",
                        display_name=command.definition.display_name,
                        error_code=None,
                        error_message=None,
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
                sequence_no = (
                    int(
                        connection.execute(
                            select(
                                func.coalesce(func.max(AgentCanvasChatEntryRow.sequence_no), 0)
                            ).where(
                                AgentCanvasChatEntryRow.conversation_id
                                == source_turn.conversation_id
                            )
                        ).scalar_one()
                    )
                    + 1
                )
                connection.execute(
                    insert(AgentCanvasChatEntryRow).values(
                        entry_id=f"entry_{identity[:32]}",
                        conversation_id=source_turn.conversation_id,
                        workflow_id=source_turn.workflow_id,
                        sequence_no=sequence_no,
                        entry_type="expert_activity",
                        speaker="adcraft_video_agent",
                        content=f"{command.definition.display_name} is working.",
                        metadata_json=json.dumps(
                            build_presentation_metadata(
                                message_key="expert_activity.working",
                                message_args={
                                    "capability_display_name": command.definition.display_name,
                                },
                                response_locale=context_snapshot.response_locale,
                                presentation_key=f"activity:{activity_id}",
                                base={
                                    "activity_id": activity_id,
                                    "turn_id": capability_turn_id,
                                    "capability_id": capability_id,
                                    "capability_display_name": command.definition.display_name,
                                    "operation": command.definition.operation,
                                    "status": "working",
                                },
                            ),
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        created_at=timestamp,
                    )
                )
                for event_type, turn_id, payload in (
                    (
                        "expert_activity_started",
                        capability_turn_id,
                        {
                            "activity_id": activity_id,
                            "capability_id": capability_id,
                            "capability_display_name": command.definition.display_name,
                            "operation": command.definition.operation,
                            "status": "working",
                        },
                    ),
                    (
                        "agent_command_queued",
                        capability_turn_id,
                        {
                            "envelope_id": envelope_id,
                            "capability_id": capability_id,
                            "source_action": command.source_action,
                            "continuation_id": continuation_id,
                        },
                    ),
                ):
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=source_turn.workflow_id,
                            conversation_id=source_turn.conversation_id,
                            turn_id=turn_id,
                            event_type=event_type,
                            transition_key=f"conversation:{turn_id}:{event_type}",
                            created_at=timestamp,
                            payload=payload,
                        ),
                    )
                _complete_turn_state_in_transaction(
                    connection,
                    events=self._events,
                    turn=current,
                    now=timestamp,
                    owned_events=True,
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        if self._wake_worker is not None:
            self._wake_worker()
        return CapabilityDispatchReceiptV1(
            envelope_id=envelope_id,
            continuation_id=continuation_id,
            capability_turn_id=capability_turn_id,
            capability_id=capability_id,
            activity_id=activity_id,
            queued_at=now,
        )


def _validate_existing_source_reply(
    connection,
    *,
    entry_id: str,
    source_reply: SourceTurnReplyPublicationV1 | None,
) -> None:
    row = (
        connection.execute(
            select(AgentCanvasChatEntryRow).where(AgentCanvasChatEntryRow.entry_id == entry_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return
    metadata = json.loads(str(row["metadata_json"]))
    if (
        source_reply is None
        or str(row["entry_type"]) != "message"
        or str(row["speaker"]) != "adcraft_video_agent"
        or str(row["content"]) != source_reply.content
        or metadata.get("response_locale") != source_reply.response_locale
    ):
        raise V2PersistenceError(
            "capability_source_reply_conflict",
            "Capability source reply conflicts with the immutable dispatch receipt.",
            stage="capability_dispatch_replay",
        )


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _style_skill_run_id(context_snapshot: CapabilityContextSnapshotV2) -> str | None:
    value = context_snapshot.style_projection.get("skill_run_id")
    return value if isinstance(value, str) and value else None


def _retry_snapshot_json(
    connection,
    *,
    envelope: CapabilityCommandEnvelopeV2,
    source_turn: ChatTurnV2,
    context_snapshot: CapabilityContextSnapshotV2,
) -> str:
    workflow_revision = int(
        connection.execute(
            select(AgentCanvasWorkflowRow.revision).where(
                AgentCanvasWorkflowRow.workflow_id == envelope.workflow_id
            )
        ).scalar_one()
    )
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
        # Unguided compatibility dispatches remain executable but are deliberately
        # ineligible for typed explicit retry because no journey authority exists.
        return "{}"
    journey = parse_production_journey(str(session["journey_state_json"]))
    active_action = journey.active_action
    logical_action_id = (
        active_action.action_id
        if active_action is not None and active_action.turn_id == source_turn.turn_id
        else str(source_turn.request.get("source_action_id") or source_turn.turn_id)
    )
    nodes = connection.execute(
        select(AgentCanvasNodeRow.node_id, AgentCanvasNodeRow.revision).where(
            AgentCanvasNodeRow.workflow_id == envelope.workflow_id
        )
    ).all()
    projection = _project_retry_reference_authority(context_snapshot)
    node_revisions = {str(node_id): int(revision) for node_id, revision in nodes}
    if any(node_id not in node_revisions for node_id in projection.node_ids):
        raise V2PersistenceError(
            "capability_retry_reference_projection_invalid",
            "Capability retry references a missing Canvas Node.",
            stage="capability_retry_snapshot_construction",
        )
    logger.info(
        "capability_retry_reference_projection version=%s node_reference_count=%s "
        "image_asset_reference_count=%s",
        _RETRY_REFERENCE_PROJECTION_VERSION,
        len(projection.node_ids),
        len(projection.image_asset_ids),
    )
    skill_run_id = _style_skill_run_id(context_snapshot)
    snapshot = ContinuationTurnRetrySnapshotV1(
        workflow_id=envelope.workflow_id,
        conversation_id=envelope.conversation_id,
        session_id=str(session["session_id"]),
        workflow_revision=workflow_revision,
        session_revision=int(session["revision"]),
        journey_stage=journey.stage,
        journey_stage_revision=journey.stage_revision,
        logical_action_id=logical_action_id,
        root_turn_id=source_turn.turn_id,
        operation="capability_command",
        envelope_id=envelope.envelope_id,
        envelope_digest=hashlib.sha256(envelope.model_dump_json().encode("utf-8")).hexdigest(),
        requirement_revision_id=envelope.requirement_revision_id,
        requirement_digest=envelope.requirement_digest,
        node_revisions=node_revisions,
        asset_ids=projection.image_asset_ids,
        response_locale=envelope.response_locale,
        policy_identity_digest=_capability_policy_identity(envelope),
        skill_identity_digest=(
            hashlib.sha256(skill_run_id.encode("utf-8")).hexdigest()
            if skill_run_id is not None
            else None
        ),
    )
    return snapshot.model_dump_json()


def _capability_policy_identity(envelope: CapabilityCommandEnvelopeV2) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "capability_id": envelope.capability_id,
                "result_contract_name": envelope.result_contract_name,
                "candidate_count": envelope.candidate_count,
                "reference_plan_digest": envelope.reference_plan.digest,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
