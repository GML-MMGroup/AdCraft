"""Repository-backed orchestration for deterministic production journeys."""

from __future__ import annotations

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_guided_interaction_repository import (
    AgentCanvasGuidedInteractionRepository,
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
from app.schemas.agent_canvas_conversation import ChatTurnV2
from app.persistence.errors import V2PersistenceError
from app.services.agent_canvas_guidance_awaiting import GuidanceAwaitingService
from app.services.agent_canvas_guided_duration import GuidedDurationAuthorityPolicy
from app.services.agent_canvas_guided_character import GuidedCharacterAuthorityPolicy
from app.services.agent_canvas_production_journey import (
    GuidedProductionJourneyPolicyService,
    reconcile_character_occurrences,
)
from app.services.agent_canvas_requirements import (
    character_occurrence_authority_for_authoring,
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
        self._character_authority = GuidedCharacterAuthorityPolicy()

    def ensure_character_decision_authority(
        self,
        workflow_id: str,
        *,
        source_turn_id: str,
        expected_session_revision: int,
        idempotency_key: str,
    ) -> ChatTurnV2 | None:
        """Publish the typed Character wait before a mutating caller waits."""

        del idempotency_key
        session = self._conversations.get_guidance_session(workflow_id)
        if session.journey.stage != "character":
            return None
        if (
            session.journey.active_action is not None
            or session.journey.suspended_action is not None
        ):
            return None
        requirements = self._requirements.get_current(workflow_id)
        questionnaire = self._character_authority.questionnaire(
            requirements,
            response_locale=session.response_locale,
        )
        if questionnaire is None:
            return None
        if session.journey.stage_status == "waiting_user" and session.awaiting is not None:
            target = session.journey
        else:
            evidence = JourneyEvidenceV2(
                evidence_id=f"character-count-required:{source_turn_id}",
                evidence_kind="clarification_completed",
                source_id=source_turn_id,
                source_revision=requirements.revision_no,
            )
            target = session.journey.model_copy(
                update={
                    "stage_status": "waiting_user",
                    "stage_revision": session.journey.stage_revision + 1,
                    "transition_evidence": (
                        *session.journey.transition_evidence,
                        evidence.as_transition(
                            stage=session.journey.stage,
                            stage_revision=session.journey.stage_revision,
                        ),
                    ),
                }
            )
        return self._conversations.complete_turn_with_clarification(
            source_turn_id,
            expected_session_revision=expected_session_revision,
            journey=target,
            assistant_message="How many characters should appear in the advertisement?",
            transition_key=(
                f"character-count:{workflow_id}:{session.session_id}:"
                f"{session.journey.stage_revision}:{source_turn_id}"
            ),
            questionnaire=questionnaire,
            checkpoint_id=(
                f"character-count:{workflow_id}:{session.session_id}:"
                f"{session.journey.stage_revision}:{source_turn_id}"
            ),
            interaction_title="Choose the character count",
            interaction_context=(
                "Confirm the number of characters before Character authoring begins."
            ),
            expected_requirement_revision=requirements.revision_no,
        )

    def next_action(
        self,
        workflow_id: str,
        *,
        clarification_required: bool = False,
    ) -> JourneyPolicyResultV2:
        session = self._conversations.get_guidance_session(workflow_id)
        self._require_stage_duration(workflow_id, session.journey.stage)
        return self._policy.evaluate(
            self._context(session, clarification_required=clarification_required)
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
        if session.journey.stage == "product" and session.awaiting is None:
            entered = self._ensure_product_source_stage_entry(
                session,
                turn_id=turn_id,
                expected_session_revision=expected_session_revision,
                idempotency_key=idempotency_key,
            )
            if entered is not None:
                return entered, JourneyPolicyResultV2(
                    action="wait_for_user",
                    expected_stage_revision=entered.journey.stage_revision,
                    requires_model_call=False,
                )
        result = self._policy.evaluate(self._context(session))
        if result.action == "advance_stage":
            evidence_kind = f"{session.journey.stage}_excluded"
            next_journey = self._policy.apply_evidence(
                self._context(session),
                JourneyEvidenceV2.model_validate(
                    {
                        "evidence_id": (
                            f"auto-skip:{session.journey.stage}:{session.journey.stage_revision}"
                        ),
                        "evidence_kind": evidence_kind,
                        "source_id": action_id,
                        "stage": session.journey.stage,
                        "stage_revision": session.journey.stage_revision,
                    }
                ),
            )
            session = self._conversations.replace_guidance_journey(
                session.session_id,
                journey=next_journey,
                expected_session_revision=expected_session_revision,
                idempotency_key=(
                    f"{idempotency_key}:auto-skip:{session.journey.stage}:"
                    f"{session.journey.stage_revision}"
                ),
                event_type="journey_stage_changed",
                event_payload={
                    "previous_stage": session.journey.stage,
                    "next_stage": next_journey.stage,
                    "evidence_kind": evidence_kind,
                    "action_owner": "system",
                },
            )
            expected_session_revision = session.revision
            self._require_stage_duration(workflow_id, session.journey.stage)
            result = self._policy.evaluate(self._context(session))
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
        journey = session.journey.model_copy(
            update={
                "active_action": projection,
                "active_occurrence_id": (
                    result.occurrence_id
                    if result.occurrence_id is not None
                    else session.journey.active_occurrence_id
                ),
            }
        )
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

    def _ensure_product_source_stage_entry(
        self,
        session: GuidedSessionStateV2,
        *,
        turn_id: str,
        expected_session_revision: int,
        idempotency_key: str,
    ) -> GuidedSessionStateV2 | None:
        """Open the existing typed Product source wait at first Product entry."""

        if session.journey.stage != "product":
            return None
        # A resolved source branch leaves the Product stage working while its
        # existing continuation reserves Product Designer.  Only the initial
        # ready Product checkpoint may publish the source question; reopening
        # it during a continuation would create a duplicate interaction.
        if session.journey.stage_status != "ready":
            return None
        if session.interaction is not None or session.awaiting is not None:
            return None
        interactions = AgentCanvasGuidedInteractionRepository(
            self._conversations.database,
            self._conversations.events,
        )
        interactions.open_product_source_with_journey(
            session.workflow_id,
            source_turn_id=turn_id,
            expected_session_revision=expected_session_revision,
            idempotency_key=f"{idempotency_key}:product-source-stage-entry",
            input_kind="main",
        )
        return self._conversations.get_guidance_session(session.workflow_id)

    def _require_stage_duration(self, workflow_id: str, stage) -> None:
        self._duration_authority.require_for_stage(
            self._requirements.get_current(workflow_id),
            stage,
        )

    def _context(
        self,
        session: GuidedSessionStateV2,
        *,
        clarification_required: bool = False,
    ) -> JourneyPolicyContextV2:
        revision = self._requirements.get_current(session.workflow_id)
        authority = character_occurrence_authority_for_authoring(revision)
        return _context(
            session,
            clarification_required=clarification_required,
            included_character_occurrence_ids=(
                tuple(item.occurrence_id for item in authority.occurrences)
                if authority.status != "unresolved"
                else None
            ),
        )

    def sync_character_occurrences(
        self,
        workflow_id: str,
        *,
        expected_session_revision: int,
        idempotency_key: str,
    ) -> GuidedSessionStateV2:
        """Project the latest canonical Ledger roster into the persisted Journey."""

        session = self._conversations.get_guidance_session(workflow_id)
        revision = self._requirements.get_current(workflow_id)
        authority = character_occurrence_authority_for_authoring(revision)
        occurrences = authority.occurrences
        journey = reconcile_character_occurrences(session.journey, occurrences)
        if journey == session.journey:
            return session
        return self._conversations.replace_guidance_journey(
            session.session_id,
            journey=journey,
            expected_session_revision=expected_session_revision,
            idempotency_key=idempotency_key,
            event_type="journey_character_roster_changed",
            event_payload={
                "requirement_revision_id": revision.revision_id,
                "requirement_revision_no": revision.revision_no,
                "character_occurrence_ids": [item.occurrence_id for item in occurrences],
                "included_character_occurrence_count": sum(
                    item.presence == "include" for item in occurrences
                ),
                "action_owner": "system",
            },
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
            self._context(session, clarification_required=clarification_required),
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
    included_character_occurrence_ids: tuple[str, ...] | None = None,
) -> JourneyPolicyContextV2:
    return JourneyPolicyContextV2(
        journey=session.journey,
        clarification_required=clarification_required,
        included_character_occurrence_ids=included_character_occurrence_ids,
    )
