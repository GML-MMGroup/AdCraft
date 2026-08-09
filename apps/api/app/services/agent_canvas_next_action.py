"""Lean Next Action execution constrained by deterministic capability policy."""

from __future__ import annotations

from typing import Protocol

from pydantic import ValidationError

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.agent_canvas_operation_envelope_repository import (
    AgentCanvasOperationEnvelopeRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_capabilities import (
    NextActionCommandV1,
    NextActionContextV1,
    NextActionEnvelopeV1,
    ValidatedNextActionV1,
)
from app.schemas.agent_canvas_creative_session import GuidanceCompletionProjectionV2
from app.services.agent_canvas_capability_dispatch import CapabilityDispatchService
from app.services.agent_canvas_capability_context import (
    build_capability_context_snapshot,
)
from app.services.agent_canvas_capability_policy import CapabilityPolicyService
from app.services.agent_canvas_next_action_context import (
    assemble_capability_policy_context,
)


class NextActionGateway(Protocol):
    def choose_next_action(
        self,
        context: NextActionContextV1,
        *,
        turn_id: str,
    ) -> NextActionCommandV1: ...


class NextActionExecutionService:
    """Validate one model suggestion against Python-owned current policy."""

    def __init__(self, gateway: NextActionGateway) -> None:
        self._gateway = gateway
        self._policy = CapabilityPolicyService()

    def execute(
        self,
        context: NextActionContextV1,
        *,
        turn_id: str,
    ) -> ValidatedNextActionV1:
        try:
            command = NextActionCommandV1.model_validate(
                self._gateway.choose_next_action(context, turn_id=turn_id)
            )
        except ValidationError as error:
            raise V2PersistenceError(
                "next_action_contract_invalid",
                "Next Action remained invalid after structured repair.",
                stage="next_action_execution",
            ) from error
        return self._policy.validate_next_action(command, context.policy)


class DurableNextActionExecutionService:
    """Execute one immutable post-selection Next Action delivery."""

    def __init__(
        self,
        *,
        workflows: AgentCanvasWorkflowRepository,
        conversations: AgentCanvasConversationRepository,
        outbox: AgentCanvasContinuationOutboxRepository,
        capability_dispatch: CapabilityDispatchService,
        gateway: NextActionGateway,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._outbox = outbox
        self._capability_dispatch = capability_dispatch
        self._envelopes = AgentCanvasOperationEnvelopeRepository(workflows.database)
        self._next_action = NextActionExecutionService(gateway)
        self._policy = CapabilityPolicyService()

    def execute(self, envelope_id: str) -> ValidatedNextActionV1:
        envelope = self._envelopes.get(envelope_id)
        if not isinstance(envelope, NextActionEnvelopeV1):
            raise V2PersistenceError(
                "next_action_envelope_invalid",
                "Operation envelope does not contain a Next Action command.",
                stage="next_action_execution",
            )
        session = self._conversations.get_guidance_session(envelope.workflow_id)
        if session.revision != envelope.expected_session_revision:
            raise V2PersistenceError(
                "guidance_revision_conflict",
                "Guidance state changed before Next Action execution.",
                stage="next_action_execution",
            )
        turn = self._conversations.mark_turn_running(envelope.next_action_turn_id)
        workflow = self._workflows.get_workflow(envelope.workflow_id)
        policy = self._policy.evaluate(
            assemble_capability_policy_context(
                workflow=workflow,
                session=session,
                open_proposal_capabilities=tuple(
                    proposal.capability_id
                    for proposal in self._conversations.list_open_proposals(envelope.workflow_id)
                ),
                active_materialization_capabilities=tuple(
                    dict.fromkeys(
                        (
                            *self._outbox.list_nonterminal_capability_ids(envelope.workflow_id),
                            *self._conversations.list_active_materialization_capability_ids(
                                envelope.workflow_id
                            ),
                        )
                    )
                ),
            )
        )
        command = self._next_action.execute(
            NextActionContextV1(
                workflow_id=envelope.workflow_id,
                conversation_id=envelope.conversation_id,
                session_revision=session.revision,
                objective=envelope.objective,
                policy=policy,
                shared_summary=session.goal.summary,
            ),
            turn_id=envelope.next_action_turn_id,
        )
        if command.command.action == "invoke_capability":
            self._capability_dispatch.dispatch_next_action(
                turn,
                command,
                build_capability_context_snapshot(
                    workflow=workflow,
                    session=session,
                    conversations=self._conversations,
                    capability_id=command.command.capability_id,
                    objective=command.command.objective or envelope.objective,
                    approved_reference_ids=(),
                ),
                session_id=session.session_id,
                expected_session_revision=session.revision,
            )
            return command
        if command.command.action == "finish":
            self._conversations.complete_guidance_session(
                session.session_id,
                expected_session_revision=session.revision,
                completion=GuidanceCompletionProjectionV2(
                    authoring="ready",
                    delivery="ready",
                ),
            )
        self._conversations.complete_turn(
            envelope.next_action_turn_id,
            assistant_message=command.command.message,
        )
        return command
