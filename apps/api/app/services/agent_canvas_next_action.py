"""Lean Next Action execution constrained by deterministic capability policy."""

from __future__ import annotations

from collections.abc import Callable
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
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.agent_canvas_decision_bundle_repository import (
    AgentCanvasDecisionBundleRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import ProjectAssetSummaryV2
from app.schemas.agent_canvas_capabilities import (
    CapabilityCommandEnvelopeV2,
    CapabilityDispatchReceiptV1,
    NextActionCommandV1,
    NextActionContextV1,
    NextActionEnvelopeV1,
    ValidatedNextActionV1,
)
from app.schemas.agent_canvas_decision_bundles import DecisionBundleDraftV1
from app.schemas.agent_canvas_creative_session import GuidanceCompletionProjectionV2
from app.services.agent_canvas_capability_dispatch import CapabilityDispatchService
from app.services.agent_canvas_capability_context import (
    build_capability_context_snapshot,
)
from app.services.agent_canvas_capability_policy import CapabilityPolicyService
from app.services.agent_canvas_capability_reference_planner import CapabilityReferencePlanner
from app.services.agent_canvas_next_action_context import (
    assemble_capability_policy_context,
)
from app.services.agent_canvas_production_journey_orchestration import (
    GuidedProductionJourneyService,
)
from app.services.model_selection import ModelSelectionService
from app.services.agent_canvas_decision_bundles import DecisionBundleAuthoringService


class NextActionGateway(Protocol):
    def choose_next_action(
        self,
        context: NextActionContextV1,
        *,
        turn_id: str,
    ) -> NextActionCommandV1: ...

    def author_decision_bundle(
        self, context: NextActionContextV1, *, turn_id: str
    ) -> DecisionBundleDraftV1: ...


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
        asset_resolver: Callable[[str], ProjectAssetSummaryV2] | None = None,
        model_selection: ModelSelectionService | None = None,
        decision_bundles: AgentCanvasDecisionBundleRepository | None = None,
        editing_preparer: Callable[[str], object] | None = None,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._outbox = outbox
        self._capability_dispatch = capability_dispatch
        self._envelopes = AgentCanvasOperationEnvelopeRepository(workflows.database)
        self._next_action = NextActionExecutionService(gateway)
        self._policy = CapabilityPolicyService()
        self._reference_planner = CapabilityReferencePlanner(
            model_selection=model_selection,
        )
        self._asset_resolver = asset_resolver
        self._requirements = AgentCanvasRequirementRepository(workflows.database)
        self._decision_bundles = (
            DecisionBundleAuthoringService(decision_bundles)
            if decision_bundles is not None
            else None
        )
        self._gateway = gateway
        self._journey = GuidedProductionJourneyService(conversations)
        self._editing_preparer = editing_preparer

    def execute(
        self,
        envelope_id: str,
        lease_guard: Callable[[], None],
    ) -> ValidatedNextActionV1:
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
        lease_guard()
        turn = self._conversations.mark_turn_running(envelope.next_action_turn_id)
        journey_action = None
        if session.journey.stage != "intake":
            session, journey_action = self._journey.reserve_next_action(
                envelope.workflow_id,
                action_id=f"journey-action:{envelope.next_action_turn_id}",
                turn_id=envelope.next_action_turn_id,
                expected_session_revision=session.revision,
                idempotency_key=f"reserve-next-action:{envelope.envelope_id}",
            )
        if journey_action is not None and journey_action.action in {
            "wait_for_user",
            "prepare_editing",
            "complete",
        }:
            lease_guard()
            if journey_action.action == "wait_for_user":
                self._journey.require_current_awaiting(envelope.workflow_id)
            if journey_action.action == "prepare_editing":
                if self._editing_preparer is None:
                    raise V2PersistenceError(
                        "editing_preparation_unavailable",
                        "Editing preparation is unavailable.",
                        stage="next_action_execution",
                    )
                self._editing_preparer(envelope.workflow_id)
                lease_guard()
            if journey_action.action == "complete":
                self._conversations.complete_guidance_session(
                    session.session_id,
                    expected_session_revision=session.revision,
                    completion=GuidanceCompletionProjectionV2(
                        authoring="ready",
                        delivery="ready",
                    ),
                )
                command = NextActionCommandV1(action="finish")
                message = "Guided production is complete."
            else:
                command = NextActionCommandV1(
                    action="reply",
                    message=(
                        "The production journey is ready for Editing preparation."
                        if journey_action.action == "prepare_editing"
                        else "Run the current Drafts before continuing guided production."
                    ),
                )
                message = command.message
            self._conversations.complete_turn(
                envelope.next_action_turn_id,
                assistant_message=message,
            )
            return ValidatedNextActionV1(command=command)
        workflow = self._workflows.get_workflow(envelope.workflow_id)
        policy = self._policy.evaluate(
            assemble_capability_policy_context(
                workflow=workflow,
                session=session,
                journey_capability=(
                    journey_action.capability_id
                    if journey_action is not None and journey_action.action == "invoke_capability"
                    else None
                ),
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
        lease_guard()
        if journey_action is not None and journey_action.action == "invoke_capability":
            assert journey_action.capability_id is not None
            command = self._policy.validate_next_action(
                NextActionCommandV1(
                    action="invoke_capability",
                    capability_id=journey_action.capability_id,
                    objective=envelope.objective,
                ),
                policy,
            )
        else:
            command = self._next_action.execute(
                NextActionContextV1(
                    workflow_id=envelope.workflow_id,
                    conversation_id=envelope.conversation_id,
                    session_revision=session.revision,
                    objective=envelope.objective,
                    policy=policy,
                    shared_summary="",
                    response_locale=session.response_locale,
                ),
                turn_id=envelope.next_action_turn_id,
            )
        lease_guard()
        if command.command.action == "author_decision_bundle":
            if self._decision_bundles is None:
                raise V2PersistenceError(
                    "decision_bundle_authoring_unavailable",
                    "Decision Bundle authoring is unavailable.",
                    stage="next_action_execution",
                )
            context = NextActionContextV1(
                workflow_id=envelope.workflow_id,
                conversation_id=envelope.conversation_id,
                session_revision=session.revision,
                objective=command.command.objective or envelope.objective,
                policy=policy,
                shared_summary="",
                response_locale=session.response_locale,
            )
            lease_guard()
            draft = self._gateway.author_decision_bundle(
                context,
                turn_id=envelope.next_action_turn_id,
            )
            lease_guard()
            bundle = self._decision_bundles.author(
                workflow_id=envelope.workflow_id,
                conversation_id=envelope.conversation_id,
                source_turn_id=envelope.next_action_turn_id,
                draft=draft,
            )
            lease_guard()
            self._conversations.complete_turn(
                envelope.next_action_turn_id,
                assistant_message=f"Decision Bundle ready: {bundle.title}",
            )
            return command
        if command.command.action == "invoke_capability":
            source_turn = self._conversations.get_turn(envelope.source_turn_id)
            reference_plan = self._reference_planner.plan(
                workflow=workflow,
                session=session,
                capability_id=command.command.capability_id,
                objective=command.command.objective or envelope.objective,
                explicit_node_ids=tuple(source_turn.request.get("mentioned_node_ids") or ()),
                explicit_image_asset_ids=tuple(
                    source_turn.request.get("mentioned_image_asset_ids") or ()
                ),
                approved_node_ids=self._conversations.get_creative_memory(
                    envelope.workflow_id
                ).approved_node_ids,
                asset_resolver=self._asset_resolver,
            )
            lease_guard()
            self._capability_dispatch.dispatch_next_action(
                turn,
                command,
                build_capability_context_snapshot(
                    workflow=workflow,
                    session=session,
                    conversations=self._conversations,
                    capability_id=command.command.capability_id,
                    objective=command.command.objective or envelope.objective,
                    reference_plan=reference_plan,
                    requirement_revision=self._requirements.get_current(envelope.workflow_id),
                    asset_resolver=self._asset_resolver,
                ),
                session_id=session.session_id,
                expected_session_revision=session.revision,
            )
            return command
        if command.command.action == "finish":
            lease_guard()
            self._conversations.complete_guidance_session(
                session.session_id,
                expected_session_revision=session.revision,
                completion=GuidanceCompletionProjectionV2(
                    authoring="ready",
                    delivery="ready",
                ),
            )
        lease_guard()
        self._conversations.complete_turn(
            envelope.next_action_turn_id,
            assistant_message=command.command.message,
        )
        return command

    def requeue_superseded_capability(
        self,
        envelope_id: str,
    ) -> CapabilityDispatchReceiptV1 | None:
        """Reproject one still-relevant stale capability against the current Ledger."""

        envelope = self._envelopes.get(envelope_id)
        if not isinstance(envelope, CapabilityCommandEnvelopeV2):
            raise V2PersistenceError(
                "capability_envelope_invalid",
                "Operation envelope does not contain a capability command.",
                stage="next_action_execution",
            )
        session = self._conversations.get_guidance_session(envelope.workflow_id)
        if session.status != "active":
            return None
        if envelope.capability_id in self._outbox.list_nonterminal_capability_ids(
            envelope.workflow_id
        ):
            return None
        if any(
            proposal.capability_id == envelope.capability_id
            for proposal in self._conversations.list_open_proposals(envelope.workflow_id)
        ):
            return None

        workflow = self._workflows.get_workflow(envelope.workflow_id)
        source_turn = self._conversations.get_turn(envelope.source_turn_id)
        requirement_revision = self._requirements.get_current(envelope.workflow_id)
        if requirement_revision.revision_id == envelope.requirement_revision_id:
            return None
        reference_plan = self._reference_planner.plan(
            workflow=workflow,
            session=session,
            capability_id=envelope.capability_id,
            objective=envelope.objective,
            explicit_node_ids=tuple(source_turn.request.get("mentioned_node_ids") or ()),
            explicit_image_asset_ids=tuple(
                source_turn.request.get("mentioned_image_asset_ids") or ()
            ),
            approved_node_ids=self._conversations.get_creative_memory(
                envelope.workflow_id
            ).approved_node_ids,
            asset_resolver=self._asset_resolver,
        )
        command = ValidatedNextActionV1(
            command=NextActionCommandV1(
                action="invoke_capability",
                capability_id=envelope.capability_id,
                objective=envelope.objective,
            ),
            definition=self._policy.definition(envelope.capability_id),
            source_action=envelope.source_action,
        )
        return self._capability_dispatch.dispatch_next_action(
            source_turn,
            command,
            build_capability_context_snapshot(
                workflow=workflow,
                session=session,
                conversations=self._conversations,
                capability_id=envelope.capability_id,
                objective=envelope.objective,
                reference_plan=reference_plan,
                requirement_revision=requirement_revision,
                asset_resolver=self._asset_resolver,
            ),
            session_id=session.session_id,
            expected_session_revision=session.revision,
            allow_completed_source_replacement=True,
        )
