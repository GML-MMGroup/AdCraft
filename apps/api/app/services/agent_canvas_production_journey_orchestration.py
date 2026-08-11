"""Repository-backed orchestration for deterministic production journeys."""

from __future__ import annotations

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.schemas.agent_canvas_creative_session import (
    CreativeElementDecisionV2,
    GuidedSessionStateV2,
)
from app.schemas.agent_canvas_production_journey import (
    JourneyActionProjectionV1,
    JourneyEvidenceV1,
    JourneyPolicyContextV1,
    JourneyPolicyResultV1,
)
from app.services.agent_canvas_production_journey import (
    GuidedProductionJourneyPolicyService,
    build_foundation_queue,
)


class GuidedProductionJourneyService:
    """Persist one evidence transition and project the next deterministic action."""

    def __init__(
        self,
        conversations: AgentCanvasConversationRepository,
        policy: GuidedProductionJourneyPolicyService | None = None,
    ) -> None:
        self._conversations = conversations
        self._policy = policy or GuidedProductionJourneyPolicyService()

    def next_action(
        self,
        workflow_id: str,
        *,
        clarification_required: bool = False,
    ) -> JourneyPolicyResultV1:
        session = self._conversations.get_guidance_session(workflow_id)
        return self._policy.evaluate(
            _context(session, clarification_required=clarification_required)
        )

    def reserve_next_action(
        self,
        workflow_id: str,
        *,
        action_id: str,
        turn_id: str,
        expected_session_revision: int,
        idempotency_key: str,
    ) -> tuple[GuidedSessionStateV2, JourneyPolicyResultV1]:
        session = self._conversations.get_guidance_session(workflow_id)
        result = self._policy.evaluate(_context(session))
        if result.action not in {"invoke_capability", "prepare_editing"}:
            return session, result
        projection = JourneyActionProjectionV1(
            action_id=action_id,
            action_kind=(
                f"invoke_capability:{result.capability_id}"
                if result.capability_id is not None
                else result.action
            ),
            stage=session.journey.stage,
            status="reserved",
            turn_id=turn_id,
            foundation_item_id=result.foundation_item_id,
        )
        journey = session.journey.model_copy(update={"active_action": projection})
        updated = self._conversations.replace_guidance_journey(
            session.session_id,
            journey=journey,
            expected_session_revision=expected_session_revision,
            idempotency_key=idempotency_key,
            event_type="journey_stage_started",
            event_payload={
                "action_id": action_id,
                "action_kind": projection.action_kind,
                "foundation_item_id": result.foundation_item_id,
            },
        )
        return updated, result

    def apply_evidence(
        self,
        workflow_id: str,
        *,
        evidence: JourneyEvidenceV1,
        expected_session_revision: int,
        idempotency_key: str,
        clarification_required: bool = False,
    ) -> GuidedSessionStateV2:
        session = self._conversations.get_guidance_session(workflow_id)
        next_journey = self._policy.apply_evidence(
            _context(session, clarification_required=clarification_required),
            evidence,
        )
        event_type = (
            "journey_stage_failed"
            if next_journey.stage_status == "failed"
            else (
                "journey_stage_changed"
                if next_journey.stage != session.journey.stage
                else "journey_stage_started"
            )
        )
        return self._conversations.replace_guidance_journey(
            session.session_id,
            journey=next_journey,
            expected_session_revision=expected_session_revision,
            idempotency_key=idempotency_key,
            event_type=event_type,
            event_payload={
                "previous_stage": session.journey.stage,
                "next_stage": next_journey.stage,
                "evidence_id": evidence.evidence_id,
                "evidence_kind": evidence.evidence_kind,
                "action_id": evidence.action_id,
                "foundation_item_id": evidence.foundation_item_id,
            },
        )

    def mark_waiting_for_user(
        self,
        workflow_id: str,
        *,
        expected_session_revision: int,
        idempotency_key: str,
    ) -> GuidedSessionStateV2:
        session = self._conversations.get_guidance_session(workflow_id)
        journey = session.journey.model_copy(update={"stage_status": "waiting_user"})
        return self._conversations.replace_guidance_journey(
            session.session_id,
            journey=journey,
            expected_session_revision=expected_session_revision,
            idempotency_key=idempotency_key,
            event_type="journey_stage_waiting_user",
            event_payload={"reason": "user_input_required"},
        )

    def amend_foundation_queue(
        self,
        workflow_id: str,
        *,
        element_decisions: tuple[CreativeElementDecisionV2, ...],
        expected_session_revision: int,
        idempotency_key: str,
    ) -> GuidedSessionStateV2:
        session = self._conversations.get_guidance_session(workflow_id)
        existing = {item.item_id: item for item in session.journey.foundation_queue}
        queue = tuple(
            existing.get(item.item_id, item) for item in build_foundation_queue(element_decisions)
        )
        evidence = JourneyEvidenceV1(
            evidence_id=f"queue-amendment:{idempotency_key}",
            evidence_kind="foundation_queue_amended",
            source_id=idempotency_key,
        )
        journey = session.journey.model_copy(
            update={
                "foundation_queue": queue,
                "transition_evidence": (
                    *session.journey.transition_evidence,
                    evidence.as_transition(),
                ),
            }
        )
        return self._conversations.replace_guidance_journey(
            session.session_id,
            journey=journey,
            expected_session_revision=expected_session_revision,
            idempotency_key=idempotency_key,
            event_type="journey_stage_changed",
            event_payload={
                "evidence_id": evidence.evidence_id,
                "evidence_kind": evidence.evidence_kind,
                "foundation_item_ids": [item.item_id for item in queue],
            },
        )


def _context(
    session: GuidedSessionStateV2,
    *,
    clarification_required: bool = False,
) -> JourneyPolicyContextV1:
    return JourneyPolicyContextV1(
        journey=session.journey,
        element_decisions=session.element_decisions,
        clarification_required=clarification_required,
    )
