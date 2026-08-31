"""Durable coordination for Product and Character parent-derived Drafts."""

from __future__ import annotations

from hashlib import sha256

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_materialization_repository import (
    AgentCanvasMaterializationRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_materialization import (
    ParentDerivedMaterializationIntentV1,
    ProposalPublicationEnvelopeV1,
    ProposalReferencePlanV1,
)
from app.services.agent_canvas_production_journey_orchestration import (
    GuidedProductionJourneyService,
)
from app.services.agent_canvas_requirements import character_occurrences_for_authoring


class ParentDerivedMaterializationCoordinator:
    """Queue a derived operation after validating the committed parent identity."""

    def __init__(
        self,
        *,
        workflows: AgentCanvasWorkflowRepository,
        conversations: AgentCanvasConversationRepository,
        materializations: AgentCanvasMaterializationRepository,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._materializations = materializations

    def reconcile_after_parent(
        self,
        parent: ProposalPublicationEnvelopeV1,
        *,
        lease_guard,
        source_turn_id: str | None = None,
    ) -> ProposalPublicationEnvelopeV1 | None:
        """Create or replay the one durable derivative queue entry for a parent."""

        if parent.operation_kind != "parent" or parent.derivative_intent is None:
            return None
        intent = parent.derivative_intent
        handoff_source_turn_id = source_turn_id or parent.action_turn_id
        derivative_materialization_id = (
            "materialization_" + sha256(intent.intent_id.encode("utf-8")).hexdigest()[:32]
        )
        derivative_envelope_id = (
            "envelope_" + sha256(derivative_materialization_id.encode("utf-8")).hexdigest()[:32]
        )
        try:
            existing = self._materializations.get_envelope(derivative_envelope_id)
        except V2PersistenceError as error:
            if error.code != "operation_envelope_not_found":
                raise
        else:
            if not isinstance(existing, ProposalPublicationEnvelopeV1):
                raise V2PersistenceError(
                    "derivative_materialization_invalid",
                    "Persisted parent-derived operation has an invalid envelope type.",
                    stage="parent_derived_materialization",
                )
            lease_guard()
            return self._materializations.queue_derivative(
                existing,
                source_turn_id=handoff_source_turn_id,
            )
        lease_guard()
        workflow = self._workflows.get_workflow(parent.workflow_id)
        session = self._conversations.get_guidance_session(parent.workflow_id)
        derivative_turn = self._conversations.create_continuation_turn(
            parent.workflow_id,
            source_action_id=intent.intent_id,
            workflow_revision=workflow.revision,
            video_skill_run_id=parent.style_skill_run_id,
            idempotency_key=f"parent-derived:{intent.intent_id}",
        )
        session = self._conversations.get_guidance_session(parent.workflow_id)
        derivative_requirement_revision_id = parent.requirement_revision_id
        derivative_requirement_revision_no = parent.requirement_revision_no
        if parent.capability_id == "character_design":
            requirement = AgentCanvasRequirementRepository(
                self._conversations.database
            ).get_current(parent.workflow_id)
            if not any(
                occurrence.occurrence_id == intent.occurrence_id
                and occurrence.presence == "include"
                for occurrence in character_occurrences_for_authoring(requirement)
            ):
                raise V2PersistenceError(
                    "character_occurrence_invalid",
                    "Character derivative occurrence is not included in the current Ledger.",
                    stage="parent_derived_materialization",
                )
            derivative_requirement_revision_id = requirement.revision_id
            derivative_requirement_revision_no = requirement.revision_no
            expected_action_id = f"journey-action:{derivative_turn.turn_id}"
            active_action = session.journey.active_action
            if active_action is None:
                session, result = GuidedProductionJourneyService(
                    self._conversations
                ).reserve_next_action(
                    parent.workflow_id,
                    action_id=expected_action_id,
                    turn_id=derivative_turn.turn_id,
                    expected_session_revision=session.revision,
                    idempotency_key=f"reserve-parent-derived:{intent.intent_id}",
                )
                if (
                    result.capability_id != "character_design"
                    or result.occurrence_id != intent.occurrence_id
                    or result.character_phase != "turnaround"
                ):
                    raise V2PersistenceError(
                        "character_authoring_phase_invalid",
                        "Character derivative does not match the current authoring phase.",
                        stage="parent_derived_materialization",
                    )
            elif (
                active_action.action_id != expected_action_id
                or active_action.occurrence_id != intent.occurrence_id
                or active_action.character_phase != "turnaround"
            ):
                raise V2PersistenceError(
                    "character_authoring_phase_invalid",
                    "Another Character authoring action owns the current phase.",
                    stage="parent_derived_materialization",
                )
        envelope = self.build_derivative_envelope(
            parent,
            intent=intent,
            turn_id=derivative_turn.turn_id,
            conversation_id=derivative_turn.conversation_id,
            expected_session_revision=session.revision,
            requirement_revision_id=derivative_requirement_revision_id,
            requirement_revision_no=derivative_requirement_revision_no,
        )
        lease_guard()
        return self._materializations.queue_derivative(
            envelope,
            source_turn_id=handoff_source_turn_id,
        )

    def queue_after_parent(
        self,
        parent: ProposalPublicationEnvelopeV1,
        *,
        lease_guard,
    ) -> ProposalPublicationEnvelopeV1 | None:
        """Backward-compatible alias for parent-derived reconciliation."""

        return self.reconcile_after_parent(parent, lease_guard=lease_guard)

    @staticmethod
    def build_derivative_envelope(
        parent: ProposalPublicationEnvelopeV1,
        *,
        intent: ParentDerivedMaterializationIntentV1,
        turn_id: str,
        conversation_id: str,
        expected_session_revision: int,
        requirement_revision_id: str | None = None,
        requirement_revision_no: int | None = None,
    ) -> ProposalPublicationEnvelopeV1:
        """Compile the deterministic derivative envelope without I/O."""

        if parent.operation_kind != "parent" or parent.derivative_intent != intent:
            raise V2PersistenceError(
                "parent_materialization_invalid",
                "Derivative intent does not match the accepted parent operation.",
                stage="parent_derived_materialization",
            )
        materialization_id = "materialization_" + _digest(intent.intent_id)[:32]
        reference_plan_identity = f"{intent.intent_id}:parent-only-references"
        return ProposalPublicationEnvelopeV1(
            envelope_id="envelope_" + _digest(materialization_id)[:32],
            materialization_id=materialization_id,
            proposal_id=parent.proposal_id,
            proposal_revision=parent.proposal_revision,
            workflow_id=parent.workflow_id,
            conversation_id=conversation_id,
            action_turn_id=turn_id,
            action="select_option",
            selection_actor="agent",
            selection_reason="Continue the accepted identity as its derived reference.",
            capability_id=parent.capability_id,
            occurrence_id=parent.occurrence_id,
            character_phase=("turnaround" if parent.capability_id == "character_design" else None),
            requirement_revision_id=(
                requirement_revision_id
                if requirement_revision_id is not None
                else parent.requirement_revision_id
            ),
            requirement_revision_no=(
                requirement_revision_no
                if requirement_revision_no is not None
                else parent.requirement_revision_no
            ),
            selected_option=parent.selected_option,
            reference_plan=ProposalReferencePlanV1(
                plan_id="reference_plan_" + _digest(reference_plan_identity)[:32],
                references=(),
                source_snapshots=(),
                digest=_digest(reference_plan_identity),
            ),
            expected_session_revision=expected_session_revision,
            stage_revision=intent.stage_revision,
            target_node_id=None,
            target_node_revision=None,
            context_snapshot_id="snapshot_" + _digest(f"{materialization_id}:context")[:32],
            context_snapshot_digest=_digest(f"{materialization_id}:context"),
            style_skill_run_id=parent.style_skill_run_id,
            operation_kind="derivative",
            parent_snapshot=intent.parent,
            derivative_intent=None,
            attempt_no=1,
            idempotency_identity=f"parent-derived:{intent.intent_id}",
            created_at=parent.created_at,
        )


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
