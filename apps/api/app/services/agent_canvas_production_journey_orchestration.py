"""Repository-backed orchestration for deterministic production journeys."""

from __future__ import annotations

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.schemas.agent_canvas_creative_session import GuidedSessionStateV2
from app.schemas.agent_canvas_production_journey import (
    GuidedProductionJourneyV2,
    JourneyActionProjectionV2,
    JourneyEvidenceV2,
    JourneyPolicyContextV2,
    JourneyPolicyResultV2,
)
from app.schemas.agent_canvas_guided_interactions import GuidanceAwaitingResumeProofV2
from app.persistence.errors import V2PersistenceError
from app.services.agent_canvas_guidance_awaiting import GuidanceAwaitingService
from app.services.agent_canvas_guided_duration import GuidedDurationAuthorityPolicy
from app.services.agent_canvas_production_journey import (
    GuidedProductionJourneyPolicyService,
)


class GuidedProductionJourneyService:
    """Persist one evidence transition and project the next deterministic action."""

    def __init__(
        self,
        conversations: AgentCanvasConversationRepository,
        policy: GuidedProductionJourneyPolicyService | None = None,
        awaiting: GuidanceAwaitingService | None = None,
    ) -> None:
        self._conversations = conversations
        self._policy = policy or GuidedProductionJourneyPolicyService()
        self._awaiting = awaiting
        self._requirements = AgentCanvasRequirementRepository(conversations.database)
        self._duration_authority = GuidedDurationAuthorityPolicy()

    def next_action(
        self,
        workflow_id: str,
        *,
        clarification_required: bool = False,
    ) -> JourneyPolicyResultV2:
        session = self._conversations.get_guidance_session(workflow_id)
        self._require_stage_duration(workflow_id, session.journey.stage)
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
    ) -> tuple[GuidedSessionStateV2, JourneyPolicyResultV2]:
        session = self._conversations.get_guidance_session(workflow_id)
        self._require_stage_duration(workflow_id, session.journey.stage)
        result = self._policy.evaluate(_context(session))
        if result.action not in {
            "invoke_capability",
            "invoke_internal_checkpoint",
            "prepare_editing",
        }:
            return session, result
        projection = JourneyActionProjectionV2(
            action_id=action_id,
            action_kind=(
                f"{result.action}:{result.capability_id}"
                if result.capability_id is not None
                else result.action
            ),
            stage=session.journey.stage,
            stage_revision=session.journey.stage_revision,
            status="reserved",
            turn_id=turn_id,
            occurrence_id=result.occurrence_id,
            character_phase=result.character_phase,
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
                "occurrence_id": result.occurrence_id,
                "character_phase": result.character_phase,
            },
        )
        return updated, result

    def _require_stage_duration(self, workflow_id: str, stage) -> None:
        self._duration_authority.require_for_stage(
            self._requirements.get_current(workflow_id),
            stage,
        )

    def require_current_awaiting(self, workflow_id: str) -> None:
        """Require typed waiting authority for the current Journey revision."""

        session = self._conversations.get_guidance_session(workflow_id)
        awaiting = session.awaiting
        if (
            awaiting is None
            or awaiting.stage != session.journey.stage
            or awaiting.stage_revision != session.journey.stage_revision
        ):
            raise V2PersistenceError(
                "guidance_orphaned_stall",
                "Guidance cannot wait without current typed awaiting authority.",
                stage="guided_production_journey_service",
                details={
                    "journey_stage": session.journey.stage,
                    "stage_revision": session.journey.stage_revision,
                },
            )

    def apply_evidence(
        self,
        workflow_id: str,
        *,
        evidence: JourneyEvidenceV2,
        expected_session_revision: int,
        idempotency_key: str,
        clarification_required: bool = False,
    ) -> GuidedSessionStateV2:
        session = self._conversations.get_guidance_session(workflow_id)
        next_journey = self.project_evidence(
            session,
            evidence=evidence,
            clarification_required=clarification_required,
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
                "occurrence_id": evidence.occurrence_id,
                "character_phase": evidence.character_phase,
            },
        )

    def project_evidence(
        self,
        session: GuidedSessionStateV2,
        *,
        evidence: JourneyEvidenceV2,
        clarification_required: bool = False,
    ) -> GuidedProductionJourneyV2:
        """Project deterministic journey evidence without persisting it."""

        if evidence.stage is None or evidence.stage_revision is None:
            evidence = evidence.model_copy(
                update={
                    "stage": session.journey.stage,
                    "stage_revision": session.journey.stage_revision,
                }
            )
        return self._policy.apply_evidence(
            _context(session, clarification_required=clarification_required),
            evidence,
        )

    def record_storyboard_pipeline_prepared(
        self,
        workflow_id: str,
        *,
        source_id: str,
    ) -> GuidedSessionStateV2 | None:
        """Advance runtime-owned storyboard stages after the complete Draft fan-out."""

        session = self._conversations.get_guidance_session_or_none(workflow_id)
        if session is None:
            return None
        current_awaiting = session.awaiting
        if current_awaiting is not None and current_awaiting.kind == "manual_node_run":
            if self._awaiting is None:
                raise ValueError("Guidance awaiting authority is required to resume Node work.")
            self._awaiting.resume(
                workflow_id,
                GuidanceAwaitingResumeProofV2(
                    awaiting_id=current_awaiting.awaiting_id,
                    expected_session_revision=session.revision,
                    evidence_kind="node_terminal",
                    node_ids=current_awaiting.node_ids,
                ),
            )
            session = self._conversations.get_guidance_session(workflow_id)
        evidence_by_stage = {
            "storyboard_grids": "storyboard_grids_prepared",
            "videos": "videos_prepared",
        }
        while session.journey.stage in evidence_by_stage:
            evidence_kind = evidence_by_stage[session.journey.stage]
            session = self.apply_evidence(
                workflow_id,
                evidence=JourneyEvidenceV2(
                    evidence_id=f"{evidence_kind}:{source_id}",
                    evidence_kind=evidence_kind,
                    source_id=source_id,
                ),
                expected_session_revision=session.revision,
                idempotency_key=f"{evidence_kind}:{source_id}",
            )
        return session


def _context(
    session: GuidedSessionStateV2,
    *,
    clarification_required: bool = False,
) -> JourneyPolicyContextV2:
    return JourneyPolicyContextV2(
        journey=session.journey,
        clarification_required=clarification_required,
    )
