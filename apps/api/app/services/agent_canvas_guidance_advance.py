"""Typed, authority-driven advancement for persisted guided production."""

from __future__ import annotations

from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_decision_bundle_repository import (
    AgentCanvasDecisionBundleRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.schemas.agent_canvas_conversation import ChatTurnAcceptedV2, ChatTurnRetryRequestV1
from app.schemas.agent_canvas_creative_session import GuidedSessionStateV2
from app.schemas.agent_canvas_guidance import GuidanceAdvanceRequestV1, GuidanceAdvanceTargetV1
from app.schemas.agent_canvas_requirements import RequirementLedgerRevisionV1
from app.services.chat_turn_retry import ChatTurnRetryService


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

    def __init__(self, conversations: AgentCanvasConversationRepository) -> None:
        self._conversations = conversations

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
        retry_turn_id: str | None = None
        if journey.active_action is not None and journey.active_action.turn_id:
            candidate = self._conversations.get_turn(journey.active_action.turn_id)
            snapshot = self._conversations.get_retry_snapshot(candidate.turn_id)
            if (
                candidate.status == "failed"
                and candidate.retryable
                and snapshot.get("session_revision") == session.revision
                and snapshot.get("journey_stage") == journey.stage
                and snapshot.get("journey_stage_revision") == journey.stage_revision
            ):
                retry_turn_id = candidate.turn_id
            elif candidate.status in {"queued", "running"}:
                raise _not_available("Current journey work is already active.")
        return GuidanceAdvanceTargetV1(
            source_kind=("retry_current_turn" if retry_turn_id else "fresh_next_action"),
            source_id=source_id,
            journey_stage=journey.stage,
            journey_stage_revision=journey.stage_revision,
            retry_turn_id=retry_turn_id,
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
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._requirements = requirements
        self._continuations = continuations
        self._decision_bundles = decision_bundles
        self._retries = retries
        self._events = events
        self._resolver = GuidanceAdvanceTargetResolver(conversations)
        self._consistency = GuidanceAuthorityConsistencyValidator()

    def submit(
        self,
        workflow_id: str,
        request: GuidanceAdvanceRequestV1,
        *,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        replay = self._conversations.get_guidance_advance_replay(
            workflow_id,
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
        )
        if replay is not None:
            return replay
        workflow = self._workflows.get_workflow(workflow_id)
        session = self._conversations.get_guidance_session(workflow_id)
        if (
            workflow.revision != request.expected_workflow_revision
            or session.revision != request.expected_session_revision
            or session.journey.stage != request.expected_journey_stage
            or session.journey.stage_revision != request.expected_journey_stage_revision
        ):
            raise V2PersistenceError(
                "guidance_advance_stale",
                "Guidance Advance no longer matches current authoring state.",
                stage="guidance_advance_service",
            )
        if session.status != "active" or session.journey.stage == "completed":
            raise _not_available("Guidance is not available in the current session state.")
        timeline = self._conversations.list_timeline(workflow_id, limit=1)
        if self._conversations.list_open_proposals(workflow_id):
            raise _not_available("An open Proposal currently owns the next user action.")
        if (
            timeline.conversation_id is not None
            and self._decision_bundles.get_open_for_conversation(timeline.conversation_id)
            is not None
        ):
            raise _not_available("An open Decision Bundle currently owns the next user action.")
        if self._continuations.list_nonterminal_for_workflow(workflow_id):
            raise _not_available("A continuation is already active.")
        requirements = self._requirements.get_current(workflow_id)
        self._consistency.validate(session, requirements)
        target = self._resolver.resolve(session, requirements)
        command_request = {
            **request.model_dump(mode="json"),
            "target": target.model_dump(mode="json"),
        }
        retry_source = None
        retry_snapshot = None
        if target.source_kind == "retry_current_turn":
            assert target.retry_turn_id is not None
            retry_source, retry_snapshot = self._retries.validate(
                workflow_id,
                target.retry_turn_id,
                ChatTurnRetryRequestV1(
                    expected_session_revision=session.revision,
                    expected_workflow_revision=workflow.revision,
                ),
            )
        return self._conversations.create_guidance_advance_delivery(
            workflow_id,
            request=command_request,
            idempotency_key=idempotency_key,
            source_kind=target.source_kind,
            source_id=target.source_id,
            guidance_session_revision=session.revision,
            retry_source=retry_source,
            retry_snapshot=retry_snapshot,
        )


def _not_available(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "guidance_advance_not_available",
        message,
        stage="guidance_advance_service",
    )
