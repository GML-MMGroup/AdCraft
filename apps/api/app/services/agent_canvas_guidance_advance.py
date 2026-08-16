"""Typed, authority-driven advancement for persisted guided production."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_guidance_authority_repository import (
    GuidanceAdvanceAuthoritySnapshotRepository,
    guidance_advance_stale_error,
    require_guidance_advance_eligible,
)
from app.persistence.agent_canvas_decision_bundle_repository import (
    AgentCanvasDecisionBundleRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.agent_canvas_operation_envelope_repository import (
    AgentCanvasOperationEnvelopeRepository,
)
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.schemas.agent_canvas_conversation import ChatTurnAcceptedV2
from app.schemas.agent_canvas_creative_session import GuidedSessionStateV2
from app.schemas.agent_canvas_guidance import (
    GuidanceAdvanceAuthorityPlanV1,
    GuidanceAdvanceRequestV1,
    GuidanceAdvanceTargetV1,
)
from app.schemas.agent_canvas_requirements import RequirementLedgerRevisionV1
from app.services.chat_turn_retry import ChatTurnRetryService
from app.services.agent_canvas_guided_action_lineage import (
    GuidedActionExecutionLeafResolver,
)
from app.services.agent_canvas_guidance_post_ready import GuidancePostReadyGate


_TOPIC_ELEMENTS = {
    "world_setting": "world_setting",
    "product": "product",
    "prop": "prop",
    "character": "character",
    "scene": "scene",
    "script": "script",
    "storyboard": "storyboard",
    "video": "video",
    "audio": "audio",
}


class GuidanceAuthorityConsistencyValidator:
    """Reject selected creative authority contradicted by current requirements."""

    def validate(
        self,
        session: GuidedSessionStateV2,
        requirements: RequirementLedgerRevisionV1,
    ) -> None:
        requirement_presence = {
            item.element_kind: item.presence for item in requirements.ledger.element_presence
        }
        session_presence = {item.element_kind: item.presence for item in session.element_decisions}
        selected: set[str] = {
            element
            for topic in session.topics
            if topic.status == "selected"
            for element in (_TOPIC_ELEMENTS.get(topic.topic_kind),)
            if element is not None
        }
        selected.update(
            item.kind for item in session.journey.foundation_queue if item.status == "selected"
        )
        conflicts = tuple(
            sorted(
                element
                for element in selected
                if requirement_presence.get(element) == "exclude"
                or session_presence.get(element) == "exclude"
            )
        )
        if conflicts:
            raise V2PersistenceError(
                "guidance_state_inconsistent",
                "Selected guidance elements conflict with current requirement authority: "
                + ", ".join(conflicts),
                stage="guidance_authority_consistency",
            )


class GuidanceAdvanceTargetResolver:
    """Resolve one current target without consulting timeline order."""

    def __init__(
        self,
        conversations: AgentCanvasConversationRepository,
        continuations: AgentCanvasContinuationOutboxRepository | None = None,
    ) -> None:
        self._conversations = conversations
        self._lineage = (
            GuidedActionExecutionLeafResolver(
                conversations,
                continuations,
                AgentCanvasOperationEnvelopeRepository(conversations.database),
            )
            if continuations is not None
            else None
        )

    def resolve(
        self,
        session: GuidedSessionStateV2,
        requirements: RequirementLedgerRevisionV1,
    ) -> GuidanceAdvanceTargetV1:
        journey = session.journey
        source_id = (
            journey.active_action.action_id
            if journey.active_action is not None
            else f"stage:{journey.stage}:{journey.stage_revision}"
        )
        leaf = (
            self._lineage.resolve(requirements.workflow_id, session)
            if self._lineage is not None and journey.active_action is not None
            else None
        )
        if leaf is not None and (
            leaf.leaf_status in {"queued", "running"}
            or leaf.continuation_status in {"queued", "leased", "retry_wait"}
        ):
            raise _not_available("Current journey work is already active.")
        if leaf is not None and leaf.leaf_status == "failed":
            raise V2PersistenceError(
                "guidance_advance_blocked_by_failed_turn",
                "Current guided work must be resolved before continuing.",
                stage="guidance_advance_service",
                details={
                    "turn_id": leaf.leaf_turn_id,
                    "error_code": leaf.error_code or "agent_operation_failed",
                    "retryable": leaf.retryable,
                },
            )
        return GuidanceAdvanceTargetV1(
            source_kind="fresh_next_action",
            source_id=source_id,
            journey_stage=journey.stage,
            journey_stage_revision=journey.stage_revision,
            requirement_revision_id=requirements.revision_id,
            guidance_session_revision=session.revision,
        )


class GuidanceAdvanceService:
    """Validate and durably submit one typed guidance control command."""

    def __init__(
        self,
        *,
        workflows: AgentCanvasWorkflowRepository,
        conversations: AgentCanvasConversationRepository,
        requirements: AgentCanvasRequirementRepository,
        continuations: AgentCanvasContinuationOutboxRepository,
        decision_bundles: AgentCanvasDecisionBundleRepository,
        retries: ChatTurnRetryService,
        events: EventRepository,
        post_ready_gate: GuidancePostReadyGate,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._requirements = requirements
        self._continuations = continuations
        self._decision_bundles = decision_bundles
        self._retries = retries
        self._events = events
        self._post_ready_gate = post_ready_gate
        self._authority = GuidanceAdvanceAuthoritySnapshotRepository(requirements)
        self._resolver = GuidanceAdvanceTargetResolver(conversations, continuations)
        self._consistency = GuidanceAuthorityConsistencyValidator()

    def submit(
        self,
        workflow_id: str,
        request: GuidanceAdvanceRequestV1,
        *,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        request_digest = _digest(request.model_dump(mode="json"))
        replay = self._conversations.replay_guidance_advance(
            workflow_id=workflow_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            return replay
        plan = self.plan(
            workflow_id,
            request,
            idempotency_key=idempotency_key,
        )
        return self._conversations.create_guidance_advance_delivery(plan)

    def plan(
        self,
        workflow_id: str,
        request: GuidanceAdvanceRequestV1,
        *,
        idempotency_key: str,
    ) -> GuidanceAdvanceAuthorityPlanV1:
        """Build an immutable read-only plan for one authoritative commit."""

        with self._conversations.database.engine.connect() as connection:
            snapshot = self._authority.read_in_transaction(connection, workflow_id)
        require_guidance_advance_eligible(snapshot)
        session = snapshot.session
        requirements = snapshot.requirements
        if session is None or requirements is None:
            raise _not_available("Guidance authority is incomplete.")
        self._consistency.validate(session, requirements)
        if snapshot.precondition != request.precondition:
            raise guidance_advance_stale_error(
                request.precondition,
                snapshot,
                stage="guidance_advance_service",
            )
        target = GuidanceAdvanceTargetV1(
            source_kind="fresh_next_action",
            source_id=request.precondition.source_id,
            journey_stage=request.precondition.journey_stage,
            journey_stage_revision=request.precondition.journey_stage_revision,
            requirement_revision_id=request.precondition.requirement_revision_id,
            guidance_session_revision=request.precondition.session_revision,
        )
        request_payload = request.model_dump(mode="json")
        request_digest = _digest(request_payload)
        identity = hashlib.sha256(
            f"{workflow_id}:{idempotency_key}:{request_digest}".encode("utf-8")
        ).hexdigest()
        return GuidanceAdvanceAuthorityPlanV1(
            workflow_id=workflow_id,
            request=request_payload,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            session_id=session.session_id,
            session_status=session.status,
            journey_active_action_digest=snapshot.active_action_digest,
            requirement_revision_id=requirements.revision_id,
            requirement_digest=requirements.digest,
            conversation_id=snapshot.conversation_id,
            open_proposal_id=snapshot.open_proposal_id,
            open_decision_bundle_id=snapshot.open_decision_bundle_id,
            active_continuation_id=snapshot.active_continuation_id,
            target=target,
            command_turn_id=f"turn_{identity[:32]}",
            executable_turn_id=f"turn_{identity[32:]}",
            continuation_id=f"continuation_{identity[:24]}",
            continuation_idempotency_key=f"guidance-next-action:{identity}",
            created_at=datetime.now(timezone.utc),
        )


def _not_available(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "guidance_advance_not_available",
        message,
        stage="guidance_advance_service",
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
