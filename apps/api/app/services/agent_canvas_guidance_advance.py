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
from app.schemas.agent_canvas_guidance import (
    GuidanceAdvanceAuthorityPlanV1,
    GuidanceAdvanceRequestV1,
    GuidanceAdvanceTargetV1,
)
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

        workflow = self._workflows.get_workflow(workflow_id)
        session = self._conversations.get_guidance_session(workflow_id)
        timeline = self._conversations.list_timeline(workflow_id, limit=1)
        open_proposals = self._conversations.list_open_proposals(workflow_id)
        open_bundle = (
            self._decision_bundles.get_open_for_conversation(timeline.conversation_id)
            if timeline.conversation_id is not None
            else None
        )
        active_continuations = self._continuations.list_nonterminal_for_workflow(workflow_id)
        requirements = self._requirements.get_current(workflow_id)
        self._consistency.validate(session, requirements)
        target = self._resolver.resolve(session, requirements)
        retry_snapshot_json: str | None = None
        retry_snapshot_digest: str | None = None
        if target.source_kind == "retry_current_turn":
            assert target.retry_turn_id is not None
            _, retry_snapshot = self._retries.validate(
                workflow_id,
                target.retry_turn_id,
                ChatTurnRetryRequestV1(
                    expected_session_revision=session.revision,
                    expected_workflow_revision=workflow.revision,
                ),
            )
            retry_snapshot_json = _canonical_json(retry_snapshot)
            retry_snapshot_digest = _digest(retry_snapshot)
        request_payload = request.model_dump(mode="json")
        request_digest = _digest(request_payload)
        identity = hashlib.sha256(
            f"{workflow_id}:{idempotency_key}:{request_digest}".encode("utf-8")
        ).hexdigest()
        is_fresh = target.source_kind == "fresh_next_action"
        return GuidanceAdvanceAuthorityPlanV1(
            workflow_id=workflow_id,
            request=request_payload,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            session_id=session.session_id,
            session_status=session.status,
            journey_active_action_digest=_digest(
                (
                    session.journey.active_action.model_dump(mode="json")
                    if session.journey.active_action is not None
                    else None
                )
            ),
            requirement_revision_id=requirements.revision_id,
            requirement_digest=requirements.digest,
            conversation_id=timeline.conversation_id,
            open_proposal_id=(open_proposals[0].proposal_id if open_proposals else None),
            open_decision_bundle_id=(open_bundle.bundle_id if open_bundle is not None else None),
            active_continuation_id=(
                active_continuations[0].continuation_id if active_continuations else None
            ),
            target=target,
            retry_snapshot_json=retry_snapshot_json,
            retry_snapshot_digest=retry_snapshot_digest,
            command_turn_id=f"turn_{identity[:32]}",
            executable_turn_id=f"turn_{identity[32:]}",
            continuation_id=(f"continuation_{identity[:24]}" if is_fresh else None),
            continuation_idempotency_key=(f"guidance-next-action:{identity}" if is_fresh else None),
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
