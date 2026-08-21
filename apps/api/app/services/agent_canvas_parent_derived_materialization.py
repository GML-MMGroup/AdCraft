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
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_materialization import (
    ParentDerivedMaterializationIntentV1,
    ProposalPublicationEnvelopeV1,
    ProposalReferencePlanV1,
)


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

    def queue_after_parent(
        self,
        parent: ProposalPublicationEnvelopeV1,
        *,
        lease_guard,
    ) -> ProposalPublicationEnvelopeV1 | None:
        """Create or replay the one durable derivative queue entry for a parent."""

        if parent.operation_kind != "parent" or parent.derivative_intent is None:
            return None
        intent = parent.derivative_intent
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
        envelope = self.build_derivative_envelope(
            parent,
            intent=intent,
            turn_id=derivative_turn.turn_id,
            conversation_id=derivative_turn.conversation_id,
            expected_session_revision=session.revision,
        )
        lease_guard()
        return self._materializations.queue_derivative(
            envelope,
            source_turn_id=parent.action_turn_id,
        )

    @staticmethod
    def build_derivative_envelope(
        parent: ProposalPublicationEnvelopeV1,
        *,
        intent: ParentDerivedMaterializationIntentV1,
        turn_id: str,
        conversation_id: str,
        expected_session_revision: int,
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
