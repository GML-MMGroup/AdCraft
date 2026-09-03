"""Lean Next Action execution constrained by deterministic capability policy."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
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
from app.persistence.agent_canvas_editing_action_reconciliation_repository import (
    AgentCanvasEditingActionReconciliationRepository,
)
from app.persistence.agent_canvas_production_closure_repository import (
    AgentCanvasProductionClosureRepository,
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
from app.schemas.agent_canvas_editing import EditingPreparationResultV2
from app.schemas.agent_canvas_guided_interactions import GuidanceAwaitingV2
from app.schemas.agent_canvas_production_closure import (
    EditingActionReconciliationOutcomeV1,
    EditingActionSystemOwnerKindV1,
    GuidedEditingActionReconciliationCommandV1,
)
from app.schemas.agent_canvas_creative_session import (
    GuidanceCompletionProjectionV2,
    GuidedSessionStateV2,
)
from app.schemas.agent_canvas_production_journey import JourneyActionProjectionV2
from app.services.agent_canvas_capability_dispatch import CapabilityDispatchService
from app.services.agent_canvas_capability_context import (
    build_capability_context_snapshot,
)
from app.services.agent_canvas_character_proposal_scope import (
    resolve_character_proposal_target_for_dispatch,
)
from app.services.agent_canvas_capability_policy import CapabilityPolicyService
from app.services.agent_canvas_capability_reference_planner import CapabilityReferencePlanner
from app.services.agent_canvas_next_action_context import (
    assemble_capability_policy_context,
)
from app.services.agent_canvas_production_journey_orchestration import (
    GuidedProductionJourneyService,
)
from app.services.agent_canvas_editing_action_outcomes import (
    GuidedEditingActionOutcomeResolver,
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
        materialization_resumer: Callable[
            [str, str, Callable[[], None]],
            object,
        ]
        | None = None,
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
        self._editing_receipts = AgentCanvasProductionClosureRepository(workflows.database)
        self._editing_reconciliation = AgentCanvasEditingActionReconciliationRepository(
            workflows.database,
            conversations.events,
        )
        self._editing_outcomes = GuidedEditingActionOutcomeResolver(
            workflows=workflows,
            conversations=conversations,
        )
        self._materialization_resumer = materialization_resumer

    def set_materialization_resumer(
        self,
        resumer: Callable[[str, str, Callable[[], None]], object],
    ) -> None:
        """Attach the canonical post-commit materialization recovery boundary."""

        self._materialization_resumer = resumer

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
        if envelope.resume_materialization_envelope_id is not None:
            if self._materialization_resumer is None:
                raise V2PersistenceError(
                    "materialization_resume_unavailable",
                    "Committed materialization recovery is unavailable.",
                    stage="next_action_execution",
                )
            lease_guard()
            recovered = self._materialization_resumer(
                envelope.resume_materialization_envelope_id,
                envelope.next_action_turn_id,
                lease_guard,
            )
            if recovered is None:
                raise V2PersistenceError(
                    "materialization_resume_not_found",
                    "Committed materialization recovery did not resolve its persisted result.",
                    stage="next_action_execution",
                )
            lease_guard()
            message = "The selected reference is applied and authoring has resumed."
            self._conversations.complete_turn(
                envelope.next_action_turn_id,
                assistant_message=message,
            )
            return ValidatedNextActionV1(
                command=NextActionCommandV1(action="reply", message=message)
            )
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
            editing_outcome: EditingActionReconciliationOutcomeV1 | None = None
            if journey_action.action == "wait_for_user":
                if session.journey.stage == "character" and session.awaiting is None:
                    admitted = self._journey.ensure_character_decision_authority(
                        envelope.workflow_id,
                        source_turn_id=envelope.next_action_turn_id,
                        expected_session_revision=session.revision,
                        idempotency_key=f"character-count:{envelope.next_action_turn_id}",
                    )
                    if admitted is not None:
                        lease_guard()
                self._journey.require_current_awaiting(envelope.workflow_id)
            if journey_action.action == "prepare_editing":
                if self._editing_preparer is None:
                    raise V2PersistenceError(
                        "editing_preparation_unavailable",
                        "Editing preparation is unavailable.",
                        stage="next_action_execution",
                    )
                reserved_editing_action = session.journey.active_action
                if reserved_editing_action is None:
                    raise V2PersistenceError(
                        "guided_editing_action_identity_conflict",
                        "Editing preparation has no reserved Journey action.",
                        stage="next_action_execution",
                    )
                try:
                    preparation_result = self._editing_preparer(envelope.workflow_id)
                    if not isinstance(preparation_result, EditingPreparationResultV2):
                        raise V2PersistenceError(
                            "guided_preparation_receipt_unavailable",
                            "Editing preparation did not return persisted receipt authority.",
                            stage="next_action_execution",
                        )
                    preparation = self._editing_receipts.find_preparation_for_editing(
                        envelope.workflow_id,
                        preparation_result.editing_node_id,
                    )
                    if preparation is None:
                        raise V2PersistenceError(
                            "guided_preparation_receipt_unavailable",
                            "Editing preparation receipt authority is unavailable.",
                            stage="next_action_execution",
                        )
                except V2PersistenceError as error:
                    current_session = self._conversations.get_guidance_session(envelope.workflow_id)
                    if not self._editing_action_is_current(
                        current_session,
                        reserved_editing_action,
                    ):
                        self._reconcile_editing_action(
                            current_session,
                            action=reserved_editing_action,
                            outcome="superseded",
                            reason_code="editing_action_superseded",
                        )
                        editing_outcome = "superseded"
                    else:
                        resolution = self._editing_outcomes.resolve(error, current_session)
                        self._reconcile_editing_action(
                            resolution.session,
                            action=reserved_editing_action,
                            outcome=resolution.outcome,
                            reason_code=resolution.reason_code,
                            evidence_ids=resolution.evidence_ids,
                            awaiting=resolution.awaiting,
                            awaiting_id=resolution.awaiting_id,
                            awaiting_kind=resolution.awaiting_kind,
                            system_owner_kind=resolution.system_owner_kind,
                            system_owner_id=resolution.system_owner_id,
                            system_owner_node_id=resolution.system_owner_node_id,
                            error_code=resolution.error_code,
                        )
                        editing_outcome = resolution.outcome
                    if editing_outcome == "failed":
                        raise
                else:
                    lease_guard()
                    current_session = self._conversations.get_guidance_session(envelope.workflow_id)
                    action_is_current = self._editing_action_is_current(
                        current_session,
                        reserved_editing_action,
                    )
                    self._reconcile_editing_action(
                        current_session,
                        action=reserved_editing_action,
                        outcome="prepared" if action_is_current else "superseded",
                        reason_code=(
                            "editing_prepared" if action_is_current else "editing_action_superseded"
                        ),
                        evidence_ids=(preparation.receipt_id,) if action_is_current else (),
                        preparation_receipt_id=(
                            preparation.receipt_id if action_is_current else None
                        ),
                    )
                    editing_outcome = "prepared" if action_is_current else "superseded"
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
                        and editing_outcome == "prepared"
                        else "Background media work will resume Editing when it settles."
                        if journey_action.action == "prepare_editing"
                        and editing_outcome == "system_deferred"
                        else "Run the required Draft media before Editing can continue."
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
                    if journey_action is not None
                    and journey_action.action in {"invoke_capability", "invoke_internal_checkpoint"}
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
        if journey_action is not None and journey_action.action in {
            "invoke_capability",
            "invoke_internal_checkpoint",
        }:
            assert journey_action.capability_id is not None
            command = self._policy.validate_next_action(
                NextActionCommandV1(
                    action="invoke_capability",
                    capability_id=journey_action.capability_id,
                    objective=envelope.objective,
                ),
                policy,
            )
            if journey_action.action == "invoke_internal_checkpoint":
                command = command.model_copy(
                    update={"definition": self._policy.internal_script_checkpoint_definition()}
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
            requirement_revision = self._requirements.get_current(envelope.workflow_id)
            publication_kind = (
                "internal_document"
                if journey_action is not None
                and journey_action.action == "invoke_internal_checkpoint"
                else "proposal"
            )
            character_target = resolve_character_proposal_target_for_dispatch(
                action=session.journey.active_action,
                capability_id=command.command.capability_id,
                publication_kind=publication_kind,
                requirement_revision=requirement_revision,
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
                    requirement_revision=requirement_revision,
                    character_target=character_target,
                    asset_resolver=self._asset_resolver,
                ),
                session_id=session.session_id,
                expected_session_revision=session.revision,
                publication_kind=(
                    "internal_document"
                    if journey_action is not None
                    and journey_action.action == "invoke_internal_checkpoint"
                    else "proposal"
                ),
                journey_stage=(
                    session.journey.stage
                    if journey_action is not None
                    and journey_action.action == "invoke_internal_checkpoint"
                    else None
                ),
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

    @staticmethod
    def _editing_action_is_current(
        session: GuidedSessionStateV2,
        action: JourneyActionProjectionV2,
    ) -> bool:
        current = session.journey.active_action
        return bool(
            session.journey.stage == "editing"
            and current is not None
            and current.action_id == action.action_id
            and current.turn_id == action.turn_id
            and current.stage_revision == action.stage_revision
            and current.action_kind == action.action_kind
            and current.status == action.status
        )

    def _reconcile_editing_action(
        self,
        session: GuidedSessionStateV2,
        *,
        action: JourneyActionProjectionV2 | None = None,
        outcome: EditingActionReconciliationOutcomeV1,
        reason_code: str,
        evidence_ids: tuple[str, ...] = (),
        preparation_receipt_id: str | None = None,
        awaiting: GuidanceAwaitingV2 | None = None,
        awaiting_id: str | None = None,
        awaiting_kind: str | None = None,
        system_owner_kind: EditingActionSystemOwnerKindV1 | None = None,
        system_owner_id: str | None = None,
        system_owner_node_id: str | None = None,
        error_code: str | None = None,
    ) -> None:
        action = action or session.journey.active_action
        if action is None or action.turn_id is None:
            raise V2PersistenceError(
                "guided_editing_action_identity_conflict",
                "Editing preparation has no reserved Journey action.",
                stage="next_action_execution",
            )
        self._editing_reconciliation.reconcile(
            GuidedEditingActionReconciliationCommandV1.model_validate(
                {
                    "logical_identity": (
                        f"{session.workflow_id}:{session.session_id}:"
                        f"{action.action_id}:{action.stage_revision}"
                    ),
                    "workflow_id": session.workflow_id,
                    "session_id": session.session_id,
                    "action_id": action.action_id,
                    "action_turn_id": action.turn_id,
                    "action_stage_revision": action.stage_revision,
                    "expected_session_revision": session.revision,
                    "outcome": outcome,
                    "reason_code": reason_code,
                    "evidence_ids": evidence_ids,
                    "preparation_receipt_id": preparation_receipt_id,
                    "awaiting": awaiting,
                    "awaiting_id": awaiting_id,
                    "awaiting_kind": awaiting_kind,
                    "system_owner_kind": system_owner_kind,
                    "system_owner_id": system_owner_id,
                    "system_owner_node_id": system_owner_node_id,
                    "error_code": error_code,
                    "reconciled_at": datetime.now(timezone.utc),
                }
            )
        )

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
        character_target = resolve_character_proposal_target_for_dispatch(
            action=session.journey.active_action,
            capability_id=envelope.capability_id,
            publication_kind=envelope.publication_kind,
            requirement_revision=requirement_revision,
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
                character_target=character_target,
                asset_resolver=self._asset_resolver,
            ),
            session_id=session.session_id,
            expected_session_revision=session.revision,
            allow_completed_source_replacement=True,
        )
