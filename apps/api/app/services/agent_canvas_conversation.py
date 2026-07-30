"""Director-owned Agent Canvas conversation and proposal orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Literal, Protocol, cast
from uuid import uuid4

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_command_repository import (
    AgentCanvasCommandRepository,
)
from app.persistence.event_repository import EventRepository
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    AgentCanvasWorkflowV2,
    CanvasBindingSourceImageAssetV2,
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    CanvasConnectionDecisionV2,
    CanvasInputRoleV2,
    CanvasNodeTypeV2,
    CanvasNodeV2,
    CanvasPositionV2,
    ProjectAssetSummaryV2,
)
from app.schemas.agent_canvas_conversation import (
    AgentActionReceiptV2,
    ChatTimelineListResponseV2,
    ChatTurnAcceptedV2,
    ChatTurnV2,
    ConceptOptionRecordV2,
    ConceptProposalCreateV2,
    ProposalActionRequestV2,
)
from app.schemas.agent_canvas_creative_session import (
    DraftReferenceIntentV2,
    GuidedDeliveryActionV2,
    SpecialistDraftV2,
)
from app.schemas.agent_operation_contexts import (
    AgentCommandReplanContextV2,
    DirectorTurnContextV2,
    SpecialistContextV2,
)
from app.schemas.agent_runtime import (
    AgentActionEnvelopeV2,
    AgentCommandPlanDraftV2,
    AgentRunPolicy,
    AgentRunRequest,
    AgentRunCompletedPayload,
    ConceptProposalDraftV2,
)
from app.services.durable_pi_run import DurablePiRunService
from app.services.agent_run_envelope import agent_run_envelope_fields
from app.services.pi_agent_runtime_client import PiAgentRuntimeError
from app.services.agent_canvas_nodes import AgentCanvasNodeService
from app.services.agent_canvas_command_compiler import (
    AgentCommandPlanCompiler,
    ResolvedAgentMentionsV2,
)
from app.services.agent_canvas_commands import AgentCanvasCommandService
from app.services.agent_canvas_context import AgentLocalContextAssembler
from app.services.agent_canvas_connection_policy import AgentCanvasConnectionPolicyService
from app.services.agent_canvas_ad_media import AdMediaDraftValidationService
from app.services.agent_canvas_video_skills import VideoSkillRegistry


@dataclass(frozen=True, slots=True)
class DirectorGatewayResult:
    assistant_message: str
    proposal: ConceptProposalCreateV2 | None = None
    command_plan: AgentCommandPlanDraftV2 | None = None


@dataclass(frozen=True, slots=True)
class DirectorRouteResult:
    """A Director decision before Python invokes one bounded Specialist."""

    assistant_message: str
    director_run_id: str
    specialist_context: SpecialistContextV2 | None = None
    command_plan: AgentCommandPlanDraftV2 | None = None


@dataclass(frozen=True, slots=True)
class SpecialistDraftMaterialization:
    """Validated Specialist Draft plus its still-open activity identity."""

    draft: SpecialistDraftV2
    activity_id: str
    proposal_id: str
    option_id: str
    conversation_id: str


class DirectorGateway(Protocol):
    def run_turn(
        self,
        context: DirectorTurnContextV2,
        *,
        turn_id: str,
    ) -> DirectorGatewayResult: ...

    def route_turn(
        self,
        context: DirectorTurnContextV2,
        *,
        turn_id: str,
    ) -> DirectorRouteResult: ...

    def run_specialist(
        self,
        context: SpecialistContextV2,
        *,
        turn_id: str,
        parent_run_id: str | None = None,
    ) -> ConceptProposalCreateV2: ...


class DeterministicDirectorGateway:
    """Test/offline gateway that never performs semantic keyword routing."""

    def run_turn(
        self,
        context: DirectorTurnContextV2,
        *,
        turn_id: str,
    ) -> DirectorGatewayResult:
        return DirectorGatewayResult(
            assistant_message=(f"Your request is recorded for this canvas: {context.user_input}")
        )

    def route_turn(
        self,
        context: DirectorTurnContextV2,
        *,
        turn_id: str,
    ) -> DirectorRouteResult:
        return DirectorRouteResult(
            assistant_message=f"Your request is recorded for this canvas: {context.user_input}",
            director_run_id=f"deterministic:{turn_id}",
        )

    def run_specialist(
        self,
        context: SpecialistContextV2,
        *,
        turn_id: str,
        parent_run_id: str | None = None,
    ) -> ConceptProposalCreateV2:
        raise PiAgentRuntimeError(
            "agent_specialist_unavailable",
            "A Specialist was not configured for this deterministic gateway.",
        )

    def materialize_draft(
        self,
        context: SpecialistContextV2,
        *,
        turn_id: str,
        parent_run_id: str | None = None,
    ) -> SpecialistDraftV2:
        """Provide a complete deterministic Draft only for explicit fake-mode runtimes."""

        proposal_kind = _proposal_kind_for_specialist(context.specialist_name)
        node_type = _node_type_for_proposal(proposal_kind)
        summary = context.selected_option_summary or context.user_instruction
        return SpecialistDraftV2(
            node_type=node_type,
            creative_role=_semantic_role_for_proposal(proposal_kind),
            title=f"{proposal_kind.title()} Draft",
            summary_prompt=summary,
            generation_prompt=(
                None if node_type == "script" else f"Deterministic test Draft: {summary}"
            ),
            structured_content=_structured_content_for_proposal(proposal_kind, summary),
            parameters={},
        )


class PiDirectorGateway:
    """Boundary for a private Pi runtime-backed Director implementation."""

    def __init__(
        self,
        durable_runner: DurablePiRunService,
        *,
        timeout_seconds: float,
    ) -> None:
        self._durable_runner = durable_runner
        self._timeout_seconds = timeout_seconds

    def run_turn(
        self,
        context: DirectorTurnContextV2,
        *,
        turn_id: str,
    ) -> DirectorGatewayResult:
        route = self.route_turn(context, turn_id=turn_id)
        if route.specialist_context is None:
            return DirectorGatewayResult(
                assistant_message=route.assistant_message,
                command_plan=route.command_plan,
            )
        return DirectorGatewayResult(
            assistant_message=route.assistant_message,
            proposal=self.run_specialist(
                route.specialist_context,
                turn_id=turn_id,
                parent_run_id=route.director_run_id,
            ),
        )

    def route_turn(
        self,
        context: DirectorTurnContextV2,
        *,
        turn_id: str,
    ) -> DirectorRouteResult:
        director_value, director_run_id = self._run(
            agent_name="director",
            operation="conversation_turn",
            context=context,
            contract=AgentActionEnvelopeV2,
            max_handoffs=1,
            identity_fields={
                "workflow_id": context.workflow_id,
                "conversation_id": context.conversation_id,
                "turn_id": turn_id,
                "agent_name": "director",
                "operation": "conversation_turn",
            },
        )
        envelope = AgentActionEnvelopeV2.model_validate(director_value)
        if envelope.specialist_handoff is None:
            return DirectorRouteResult(
                assistant_message=envelope.assistant_message,
                director_run_id=director_run_id,
                command_plan=envelope.command_plan,
            )
        specialist = envelope.specialist_handoff
        return DirectorRouteResult(
            assistant_message=envelope.assistant_message,
            director_run_id=director_run_id,
            specialist_context=SpecialistContextV2(
                context_kind="specialist_handoff",
                specialist_name=specialist,
                operation="propose_concepts",
                workflow_id=context.workflow_id,
                workflow_revision=context.workflow_revision,
                user_instruction=context.user_input,
                script_summary=context.script_summary,
                video_skill_excerpt=context.video_skill_excerpt,
                explicit_input_summaries=context.explicit_input_summaries,
                creative_session=context.creative_session,
                creative_memory=context.creative_memory,
                resolved_image_targets=context.resolved_image_targets,
            ),
        )

    def run_specialist(
        self,
        context: SpecialistContextV2,
        *,
        turn_id: str,
        parent_run_id: str | None = None,
    ) -> ConceptProposalCreateV2:
        if context.operation not in {"propose_concepts", "revise_concepts"}:
            raise PiAgentRuntimeError(
                "agent_specialist_operation_unsupported",
                "The requested Specialist operation is not supported.",
            )
        proposal_value, _ = self._run(
            agent_name=context.specialist_name,
            operation=context.operation,
            context=context,
            contract=ConceptProposalDraftV2,
            max_handoffs=0,
            parent_run_id=parent_run_id,
            identity_fields={
                "workflow_id": context.workflow_id,
                "turn_id": turn_id,
                "agent_name": context.specialist_name,
                "operation": context.operation,
            },
        )
        proposal = ConceptProposalDraftV2.model_validate(proposal_value)
        return ConceptProposalCreateV2(
            proposal_kind=proposal.proposal_kind,
            specialist_name=proposal.specialist_name,
            options=tuple(
                ConceptOptionRecordV2(
                    option_id=option.option_id,
                    title=option.title,
                    summary_prompt=option.summary_prompt,
                    draft_spec=option.draft_spec,
                )
                for option in proposal.options
            ),
            proposed_references=proposal.proposed_references,
        )

    def materialize_draft(
        self,
        context: SpecialistContextV2,
        *,
        turn_id: str,
        parent_run_id: str | None = None,
    ) -> SpecialistDraftV2:
        if context.operation != "materialize_draft":
            raise PiAgentRuntimeError(
                "agent_specialist_operation_unsupported",
                "The requested Specialist operation is not supported.",
            )
        value, _ = self._run(
            agent_name=context.specialist_name,
            operation=context.operation,
            context=context,
            contract=SpecialistDraftV2,
            max_handoffs=0,
            parent_run_id=parent_run_id,
            identity_fields={
                "workflow_id": context.workflow_id,
                "turn_id": turn_id,
                "agent_name": context.specialist_name,
                "operation": context.operation,
                "selected_option_id": context.selected_option_id or "",
            },
        )
        return SpecialistDraftV2.model_validate(value)

    def replan(
        self,
        context: AgentCommandReplanContextV2,
    ) -> AgentCommandPlanDraftV2:
        value, _ = self._run(
            agent_name="director",
            operation="command_replan",
            context=context,
            contract=AgentCommandPlanDraftV2,
            max_handoffs=0,
            identity_fields={
                "workflow_id": context.workflow_id,
                "conversation_id": context.conversation_id,
                "workflow_revision": context.workflow_revision,
                "conflict_code": context.conflict_code,
                "agent_name": "director",
                "operation": "command_replan",
            },
        )
        return AgentCommandPlanDraftV2.model_validate(value)

    def _run(
        self,
        *,
        agent_name: str,
        operation: str,
        context: (DirectorTurnContextV2 | AgentCommandReplanContextV2 | SpecialistContextV2),
        contract,
        max_handoffs: int,
        identity_fields: dict[str, str | int],
        parent_run_id: str | None = None,
    ) -> tuple[dict[str, object], str]:
        request = AgentRunRequest(
            run_id="candidate_agent_run",
            request_id="candidate_agent_request",
            **agent_run_envelope_fields(context),
            parent_run_id=parent_run_id,
            agent_name=agent_name,
            operation=operation,
            deadline_at=datetime.now(timezone.utc) + timedelta(seconds=self._timeout_seconds),
            model_policy_id=f"{agent_name}.{operation}.v1",
            context=context,
            policy=AgentRunPolicy(
                max_handoffs=max_handoffs,
                timeout_seconds=self._timeout_seconds,
            ),
            contract_name=contract.__name__,
            contract_schema=contract.model_json_schema(),
            audit_metadata={"tool_mode": "structured_only"},
        )
        result = self._durable_runner.run(
            request,
            identity_fields=identity_fields,
        )
        completed = AgentRunCompletedPayload.model_validate(result.terminal_payload)
        return completed.value, result.run_id


class ConceptProposalService:
    """Small proposal facade retained for explicit service ownership."""

    def __init__(self, repository: AgentCanvasConversationRepository) -> None:
        self._repository = repository

    def persist(
        self,
        turn_id: str,
        proposal: ConceptProposalCreateV2,
    ):
        return self._repository.create_proposal(turn_id, proposal)


class PlanningProgressService:
    """Read recipe-derived planning state without creating runtime dependencies."""

    def __init__(self, repository: AgentCanvasConversationRepository) -> None:
        self._repository = repository

    def list(self, skill_run_id: str):
        return self._repository.list_planning_topics(skill_run_id)

    def begin(self, skill_run_id: str, topic_id: str):
        return self._repository.begin_planning_topic(skill_run_id, topic_id)

    def complete(
        self,
        skill_run_id: str,
        topic_id: str,
        *,
        outcome: str,
        related_node_ids: tuple[str, ...] = (),
    ):
        return self._repository.complete_planning_topic(
            skill_run_id,
            topic_id,
            outcome=outcome,
            related_node_ids=related_node_ids,
        )

    def skip(self, skill_run_id: str, topic_id: str):
        return self._repository.update_planning_topic(
            skill_run_id,
            topic_id,
            status="skipped",
            outcome="skipped_by_user",
        )

    def defer(self, skill_run_id: str, topic_id: str):
        return self._repository.update_planning_topic(
            skill_run_id,
            topic_id,
            status="deferred",
            outcome="deferred_by_user",
        )

    def reopen(self, skill_run_id: str, topic_id: str):
        return self._repository.update_planning_topic(
            skill_run_id,
            topic_id,
            status="in_review",
            outcome="reopened_by_user",
        )


class GuidedDeliveryActionProjectionService:
    """Project bounded UI actions from persisted Canvas state without mutation."""

    def project(
        self,
        workflow: AgentCanvasWorkflowV2,
        *,
        creating_turn_id: str,
        topic_id: str | None,
    ) -> tuple[GuidedDeliveryActionV2, ...]:
        actions: list[GuidedDeliveryActionV2] = []
        if topic_id:
            actions.extend(
                (
                    GuidedDeliveryActionV2(
                        action_id=f"guided_{uuid4().hex}",
                        action="add_another_topic_node",
                        state="pending",
                        creating_turn_id=creating_turn_id,
                        expected_semantic_revision=workflow.revision,
                        label="Add another",
                        workflow_id=workflow.workflow_id,
                        topic_id=topic_id,
                        confirmation_required=False,
                        reason="Create another independent option for the current topic.",
                    ),
                    GuidedDeliveryActionV2(
                        action_id=f"guided_{uuid4().hex}",
                        action="skip_topic",
                        state="pending",
                        creating_turn_id=creating_turn_id,
                        expected_semantic_revision=workflow.revision,
                        label="Skip",
                        workflow_id=workflow.workflow_id,
                        topic_id=topic_id,
                        confirmation_required=True,
                        reason="Mark this planning topic as skipped without changing the graph.",
                    ),
                )
            )
        runnable = tuple(
            node
            for node in workflow.nodes
            if node.status == "draft" and node.node_type in {"script", "image", "video", "audio"}
        )
        if runnable:
            actions.append(
                GuidedDeliveryActionV2(
                    action_id=f"guided_{uuid4().hex}",
                    action="run_all_drafts",
                    state="pending",
                    creating_turn_id=creating_turn_id,
                    expected_semantic_revision=workflow.revision,
                    label="Generate existing drafts",
                    workflow_id=workflow.workflow_id,
                    ordered_node_ids=tuple(node.node_id for node in runnable),
                    confirmation_required=True,
                    reason="Run only the runnable Draft nodes already present on the canvas.",
                )
            )
        for node in runnable:
            actions.append(
                GuidedDeliveryActionV2(
                    action_id=f"guided_{uuid4().hex}",
                    action="generate_node",
                    state="pending",
                    creating_turn_id=creating_turn_id,
                    expected_semantic_revision=workflow.revision,
                    label="Generate node",
                    workflow_id=workflow.workflow_id,
                    node_id=node.node_id,
                    confirmation_required=True,
                    reason="Run this existing Draft node.",
                )
            )
        return tuple(actions)


class ProjectCreativeMemoryService:
    """Maintain bounded, non-authoritative creative memory references."""

    def __init__(
        self,
        repository: AgentCanvasConversationRepository,
        workflows: AgentCanvasWorkflowRepository,
    ) -> None:
        self._repository = repository
        self._workflows = workflows

    def get(self, workflow_id: str):
        self._workflows.get_workflow(workflow_id)
        return self._repository.get_creative_memory(workflow_id)

    def update(self, memory):
        self._workflows.get_workflow(memory.workflow_id)
        return self._repository.upsert_creative_memory(memory)

    def reconcile_deleted_nodes(self, workflow_id: str):
        self._workflows.get_workflow(workflow_id)
        return self._repository.reconcile_deleted_memory_nodes(workflow_id)

    def compact_non_authoritative(
        self,
        workflow_id: str,
        *,
        through_sequence_no: int,
        summarize: Callable[[], str],
    ):
        """Persist an optional conversation summary without changing approved facts.

        The caller owns Pi invocation. A summary failure must never invalidate
        authoritative memory or interrupt the conversation that triggered it.
        """

        memory = self.get(workflow_id)
        if through_sequence_no <= memory.summary_through_sequence_no:
            return memory
        try:
            summary = summarize().strip()
        except Exception:  # noqa: BLE001 - compaction is intentionally non-authoritative.
            return memory
        if not summary:
            return memory
        return self.update(
            memory.model_copy(
                update={
                    "conversation_summary": summary,
                    "summary_through_sequence_no": through_sequence_no,
                }
            )
        )


class AgentCanvasDraftPublicationService:
    """Prevalidate and atomically publish one Specialist Draft."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        conversations: AgentCanvasConversationRepository,
        *,
        asset_resolver: Callable[[str], ProjectAssetSummaryV2] | None = None,
        connection_policy: AgentCanvasConnectionPolicyService | None = None,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._asset_resolver = asset_resolver
        self._connection_policy = connection_policy or AgentCanvasConnectionPolicyService()

    def materialize(
        self,
        proposal_id: str,
        *,
        option_id: str,
        draft: SpecialistDraftV2,
        generation_action: str,
        position: dict[str, float] | None,
        selection_actor: str = "user",
        source_turn_id: str | None = None,
    ) -> CanvasNodeV2:
        proposal = self._conversations.get_proposal(proposal_id)
        option = next(
            (item for item in proposal.options if item.option_id == option_id),
            None,
        )
        if option is None:
            raise V2PersistenceError(
                "proposal_option_not_found",
                "Concept option was not found.",
                stage="draft_materialization",
            )
        SpecialistDraftValidationService().validate(proposal, draft)
        workflow = self._workflows.get_workflow(proposal.workflow_id)
        source_turn = self._conversations.get_turn(proposal.turn_id)
        video_skill_run_id = source_turn.request.get("video_skill_run_id")
        now = datetime.now(timezone.utc)
        node = CanvasNodeV2(
            node_id=f"node_{uuid4().hex}",
            workflow_id=proposal.workflow_id,
            node_type=draft.node_type,
            creative_role=draft.creative_role,
            title=draft.title,
            status="ready" if draft.node_type == "script" else "draft",
            summary_prompt=draft.summary_prompt,
            generation_prompt=draft.generation_prompt,
            structured_content=draft.structured_content,
            parameters={
                **draft.parameters,
                "requested_run": generation_action == "generate_now",
            },
            position=CanvasPositionV2(
                x=float((position or {}).get("x", 0)),
                y=float((position or {}).get("y", 0)),
            ),
            revision=1,
            created_at=now,
            updated_at=now,
        )
        allowed_sources = {
            ("node", str(node_id))
            for node_id in source_turn.request.get("mentioned_node_ids") or ()
        }
        allowed_sources.update(
            ("image_asset", str(asset_id))
            for asset_id in source_turn.request.get("mentioned_image_asset_ids") or ()
        )
        bindings = self._validated_bindings(
            node,
            draft.reference_intents,
            allowed_sources=allowed_sources,
        )
        receipt = (
            AgentActionReceiptV2(
                receipt_id=f"receipt_{source_turn_id}",
                workflow_id=node.workflow_id,
                action_id=source_turn_id,
                status="applied",
                summary="The selected concept is now an editable Draft.",
                created_node_ids=(node.node_id,),
                created_binding_ids=tuple(binding.binding_id for binding in bindings),
                workflow_revision=workflow.revision + 1,
            )
            if source_turn_id is not None
            else None
        )
        publication_identity = (
            f"{proposal.workflow_id}:{proposal.proposal_id}:{proposal.proposal_revision}:"
            f"{proposal.specialist_name}:materialize_draft:{option_id}:{generation_action}:"
            f"{source_turn_id or proposal.turn_id}"
        )
        self._conversations.select_and_materialize(
            proposal_id,
            option_id=option_id,
            node=node,
            bindings=bindings,
            expected_workflow_revision=workflow.revision,
            selection_actor=selection_actor,
            source_turn_id=source_turn_id,
            publication_identity=publication_identity,
            skill_run_id=(str(video_skill_run_id) if isinstance(video_skill_run_id, str) else None),
            topic_id=_planning_topic_for_proposal(proposal.proposal_kind),
            receipt=receipt,
        )
        return node

    def _validated_bindings(
        self,
        node: CanvasNodeV2,
        intents: tuple[DraftReferenceIntentV2, ...],
        *,
        allowed_sources: set[tuple[str, str]],
    ) -> tuple[CanvasBindingV2, ...]:
        bindings: list[CanvasBindingV2] = []
        seen_sources: set[tuple[str, str]] = set()
        seen_orders: set[int] = set()
        for intent in sorted(intents, key=lambda item: item.display_order):
            source_key = (intent.source_kind, intent.source_id)
            if source_key not in allowed_sources:
                raise V2PersistenceError(
                    "draft_reference_not_allowed",
                    "Draft reference was not included in the Specialist allowlist.",
                    stage="draft_materialization",
                )
            if source_key in seen_sources or intent.display_order in seen_orders:
                raise V2PersistenceError(
                    "draft_binding_invalid",
                    "Draft references must have unique sources and display order.",
                    stage="draft_materialization",
                )
            seen_sources.add(source_key)
            seen_orders.add(intent.display_order)
            if intent.source_kind == "node":
                source = self._workflows.get_node(node.workflow_id, intent.source_id)
                decision = self._require_draft_connection(
                    source_node_type=source.node_type,
                    target_node_type=node.node_type,
                    input_role=intent.input_role,
                )
                binding_source = CanvasBindingSourceNodeV2(source_node_id=source.node_id)
            else:
                if self._asset_resolver is None:
                    raise V2PersistenceError(
                        "draft_reference_not_allowed",
                        "Image asset references require the project asset resolver.",
                        stage="draft_materialization",
                    )
                try:
                    asset = self._asset_resolver(intent.source_id)
                except (KeyError, LookupError) as error:
                    raise V2PersistenceError(
                        "draft_reference_not_allowed",
                        "Draft reference asset was not found.",
                        stage="draft_materialization",
                    ) from error
                if asset.media_type != "image" or asset.status != "ready":
                    raise V2PersistenceError(
                        "draft_reference_not_allowed",
                        "Draft references must be Ready image assets.",
                        stage="draft_materialization",
                    )
                decision = self._require_draft_connection(
                    source_node_type="image",
                    target_node_type=node.node_type,
                    input_role=intent.input_role,
                    is_image_asset=True,
                )
                binding_source = CanvasBindingSourceImageAssetV2(source_asset_id=asset.asset_id)
            input_role = intent.input_role
            if decision.input_role != input_role:
                raise V2PersistenceError(
                    "draft_binding_invalid",
                    "Draft reference binding kind conflicts with the connection policy.",
                    stage="draft_materialization",
                )
            bindings.append(
                CanvasBindingV2(
                    binding_id=f"binding_{uuid4().hex}",
                    workflow_id=node.workflow_id,
                    source=binding_source,
                    target_node_id=node.node_id,
                    input_role=decision.input_role or input_role,
                    required=intent.required,
                    enabled=True,
                    order=intent.display_order,
                    created_at=node.created_at,
                    updated_at=node.created_at,
                )
            )
        return tuple(bindings)

    def _require_draft_connection(
        self,
        *,
        source_node_type: CanvasNodeTypeV2,
        target_node_type: CanvasNodeTypeV2,
        input_role: CanvasInputRoleV2,
        is_image_asset: bool = False,
    ) -> CanvasConnectionDecisionV2:
        try:
            return self._connection_policy.require(
                source_node_type=source_node_type,
                target_node_type=target_node_type,
                input_role=input_role,
                is_image_asset=is_image_asset,
            )
        except V2PersistenceError as error:
            raise V2PersistenceError(
                "draft_binding_invalid",
                "Draft reference is incompatible with the connection policy.",
                stage="draft_materialization",
            ) from error


DraftMaterializationService = AgentCanvasDraftPublicationService


class SpecialistDraftValidationService:
    """Reject incompatible Specialist Drafts without creatively repairing them."""

    def validate(
        self,
        proposal,
        draft: SpecialistDraftV2,
    ) -> None:
        expected_node_type = _node_type_for_proposal(proposal.proposal_kind)
        expected_role = _semantic_role_for_proposal(proposal.proposal_kind)
        if draft.node_type != expected_node_type or draft.creative_role != expected_role:
            raise V2PersistenceError(
                "specialist_draft_invalid",
                "Specialist Draft is incompatible with the selected concept.",
                stage="draft_materialization",
            )
        try:
            AdMediaDraftValidationService().validate(
                node_type=draft.node_type,
                semantic_role=draft.creative_role,
                structured_content=draft.structured_content,
            )
        except V2PersistenceError as error:
            raise V2PersistenceError(
                "specialist_draft_invalid",
                "Specialist Draft structured content is invalid.",
                stage="draft_materialization",
            ) from error
        if draft.node_type != "script" and not draft.generation_prompt:
            raise V2PersistenceError(
                "specialist_draft_invalid",
                "Media Draft requires a generation prompt.",
                stage="draft_materialization",
            )
        if (
            draft.node_type == "script"
            and not str(draft.structured_content.get("content") or "").strip()
        ):
            raise V2PersistenceError(
                "specialist_draft_invalid",
                "Script Draft requires structured content.",
                stage="draft_materialization",
            )


class AgentConversationService:
    """Persist asynchronous Director turns and apply validated proposal actions."""

    def __init__(
        self,
        *,
        workflows: AgentCanvasWorkflowRepository,
        conversations: AgentCanvasConversationRepository,
        nodes: AgentCanvasNodeService,
        gateway: DirectorGateway,
        provider_runner: Callable[..., object] | None = None,
        video_skills: VideoSkillRegistry | None = None,
        context_assembler: AgentLocalContextAssembler | None = None,
        command_compiler: AgentCommandPlanCompiler | None = None,
        command_service: AgentCanvasCommandService | None = None,
        run_nodes: Callable[
            [str, tuple[str, ...], str],
            tuple[str, ...],
        ]
        | None = None,
        asset_resolver: Callable[[str], ProjectAssetSummaryV2] | None = None,
        connection_policy: AgentCanvasConnectionPolicyService | None = None,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._nodes = nodes
        self._gateway = gateway
        self._provider_runner = provider_runner
        self._video_skills = video_skills or VideoSkillRegistry()
        self._context_assembler = context_assembler
        self._command_compiler = command_compiler or AgentCommandPlanCompiler()
        self._command_service = command_service or AgentCanvasCommandService(
            AgentCanvasCommandRepository(
                workflows.database,
                EventRepository(workflows.database),
            ),
        )
        self._run_nodes = run_nodes
        self._planning_progress = PlanningProgressService(conversations)
        self._guided_actions = GuidedDeliveryActionProjectionService()
        self._materialization = AgentCanvasDraftPublicationService(
            workflows,
            conversations,
            asset_resolver=asset_resolver,
            connection_policy=connection_policy,
        )

    def submit_message(
        self,
        workflow_id: str,
        *,
        text: str,
        idempotency_key: str,
        mentioned_node_ids: tuple[str, ...] = (),
        mentioned_image_asset_ids: tuple[str, ...] = (),
        video_skill_run_id: str | None = None,
        auto_continue: bool = False,
    ) -> ChatTurnAcceptedV2:
        self._workflows.get_workflow(workflow_id)
        if video_skill_run_id is None:
            try:
                video_skill_run_id = self._conversations.get_creative_session(
                    workflow_id
                ).skill_run_id
            except V2PersistenceError as error:
                if error.code != "creative_session_not_found":
                    raise
                default_skill = self._video_skills.load("platform-default", "1")
                video_skill_run_id = self._conversations.create_skill_run(
                    workflow_id,
                    skill_id=default_skill.manifest.skill_id,
                    skill_version=default_skill.manifest.version,
                    recipe_topics=tuple(default_skill.recipe["planning_topics"]),
                    idempotency_key=f"{workflow_id}:platform-default:1",
                ).skill_run_id
        else:
            skill_run = self._conversations.get_skill_run(video_skill_run_id)
            if skill_run.workflow_id != workflow_id or skill_run.status != "active":
                raise V2PersistenceError(
                    "creative_session_conflict",
                    "Creative session does not belong to this Workflow.",
                    stage="agent_conversation_service",
                )
        if self._context_assembler is not None:
            self._context_assembler.assemble_director_turn(
                workflow_id,
                conversation_id=f"pending:{idempotency_key}",
                user_input=text,
                mentioned_node_ids=mentioned_node_ids,
                mentioned_image_asset_ids=mentioned_image_asset_ids,
            )
        return self._conversations.create_user_turn(
            workflow_id,
            text=text,
            mentioned_node_ids=mentioned_node_ids,
            mentioned_image_asset_ids=mentioned_image_asset_ids,
            video_skill_run_id=video_skill_run_id,
            auto_continue=auto_continue,
            idempotency_key=idempotency_key,
        )

    def act_on_proposal(
        self,
        workflow_id: str,
        proposal_id: str,
        request: ProposalActionRequestV2,
        *,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        proposal = self._conversations.get_proposal(proposal_id)
        if proposal.workflow_id != workflow_id:
            raise V2PersistenceError(
                "proposal_not_found",
                "Concept proposal was not found.",
                stage="agent_conversation_service",
            )
        if proposal.status != "pending":
            raise V2PersistenceError(
                "proposal_not_pending",
                "Concept proposal is no longer pending.",
                stage="agent_conversation_service",
            )
        return self._conversations.create_action_turn(
            workflow_id,
            proposal_id=proposal_id,
            action=request,
            idempotency_key=idempotency_key,
        )

    def act_on_command_plan(
        self,
        workflow_id: str,
        plan_id: str,
        *,
        action: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        plan = self._command_service.get_plan(plan_id)
        if plan.workflow_id != workflow_id:
            raise V2PersistenceError(
                "agent_command_plan_not_found",
                "Agent command plan was not found.",
                stage="agent_conversation_service",
            )
        return self._conversations.create_command_action_turn(
            workflow_id,
            plan_id=plan_id,
            action=action,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )

    def act_on_guided_action(
        self,
        workflow_id: str,
        action_id: str,
        *,
        confirmed: bool,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        action = self._conversations.get_guided_action(action_id)
        if action.workflow_id != workflow_id:
            raise V2PersistenceError(
                "guided_action_not_found",
                "Guided action was not found.",
                stage="agent_conversation_service",
            )
        if action.confirmation_required and not confirmed:
            raise V2PersistenceError(
                "confirmation_required",
                "Guided action requires explicit confirmation.",
                stage="agent_conversation_service",
            )
        return self._conversations.create_guided_action_turn(
            workflow_id,
            action_id=action_id,
            idempotency_key=idempotency_key,
        )

    def process_turn(
        self,
        turn_id: str,
        *,
        proposal: ConceptProposalCreateV2 | None = None,
    ) -> ChatTurnV2:
        turn = self._conversations.get_turn(turn_id)
        if turn.status == "completed":
            return turn
        self._conversations.mark_turn_running(turn_id)
        try:
            if turn.turn_kind == "message":
                return self._process_message_turn(turn_id, turn, proposal)
            if turn.turn_kind == "proposal_action":
                return self._process_proposal_action(turn_id, turn)
            if turn.turn_kind == "command_action":
                return self._process_command_action(turn_id, turn)
            return self._process_guided_action(turn_id, turn)
        except PiAgentRuntimeError as error:
            if error.code == "agent_run_in_progress":
                return self._conversations.get_turn(turn_id)
            return self._conversations.fail_turn(
                turn_id,
                code=error.code,
                message=error.message,
            )
        except V2PersistenceError as error:
            return self._conversations.fail_turn(
                turn_id,
                code=error.code,
                message=str(error),
            )
        except Exception:
            return self._conversations.fail_turn(
                turn_id,
                code="agent_runtime_unavailable",
                message="Agent turn could not be completed.",
            )

    def _process_message_turn(
        self,
        turn_id: str,
        turn: ChatTurnV2,
        proposal: ConceptProposalCreateV2 | None,
    ) -> ChatTurnV2:
        if proposal is not None:
            self._conversations.record_expert_activity(
                turn_id,
                specialist_name=proposal.specialist_name,
                operation="propose_concepts",
                status="working",
                label=f"{proposal.specialist_name} is working",
            )
            persisted = self._conversations.create_proposal(turn_id, proposal)
            self._conversations.record_expert_activity(
                turn_id,
                specialist_name=proposal.specialist_name,
                operation="propose_concepts",
                status="completed",
                label=f"{proposal.specialist_name} completed",
            )
            if bool(turn.request.get("auto_continue")):
                materialized = self._materialize_specialist_draft(
                    turn,
                    persisted,
                    persisted.options[0].option_id,
                )
                try:
                    node = self._materialization.materialize(
                        persisted.proposal_id,
                        option_id=persisted.options[0].option_id,
                        draft=materialized.draft,
                        generation_action="draft_only",
                        position=None,
                        selection_actor="agent",
                        source_turn_id=turn_id,
                    )
                except V2PersistenceError as error:
                    self._fail_draft_materialization(
                        materialized,
                        persisted.specialist_name,
                        error,
                    )
                    raise
                self._complete_draft_materialization(materialized, persisted.specialist_name, node)
                try:
                    continuation = self._queue_continuation(
                        turn,
                        source_action_id=turn_id,
                    )
                except Exception:  # noqa: BLE001 - receipt drives restart recovery.
                    continuation = None
                self._store_proposal_receipt(
                    turn,
                    node=node,
                    continuation_turn_id=(
                        continuation.turn_id if continuation is not None else None
                    ),
                    queued_execution_ids=(),
                    run_errors=(),
                )
            message = f"Review {len(persisted.options)} {persisted.proposal_kind} option(s)."
        else:
            context = self._director_context(turn)
            route_turn = getattr(self._gateway, "route_turn", None)
            run_specialist = getattr(self._gateway, "run_specialist", None)
            if callable(route_turn) and callable(run_specialist):
                route = route_turn(context, turn_id=turn_id)
                if route.specialist_context is not None:
                    specialist_context = SpecialistContextV2.model_validate(
                        route.specialist_context
                    )
                    activity = self._conversations.start_expert_activity(
                        turn_id,
                        specialist_name=specialist_context.specialist_name,
                        operation=specialist_context.operation,
                        label=f"{specialist_context.specialist_name} is working",
                    )
                    try:
                        routed_proposal = run_specialist(
                            specialist_context,
                            turn_id=turn_id,
                            parent_run_id=route.director_run_id,
                        )
                    except PiAgentRuntimeError as error:
                        self._conversations.transition_expert_activity(
                            activity.activity_id,
                            status="failed",
                            label=f"{specialist_context.specialist_name} failed",
                            error_code=error.code,
                            error_message=error.message,
                        )
                        raise
                    self._conversations.transition_expert_activity(
                        activity.activity_id,
                        status="completed",
                        label=f"{specialist_context.specialist_name} completed",
                    )
                    return self._process_message_turn(turn_id, turn, routed_proposal)
                result = DirectorGatewayResult(
                    assistant_message=route.assistant_message,
                    command_plan=route.command_plan,
                )
            else:
                result = self._gateway.run_turn(context, turn_id=turn_id)
            if result.proposal is not None:
                return self._process_message_turn(turn_id, turn, result.proposal)
            if result.command_plan is not None:
                workflow = self._workflows.get_workflow(turn.workflow_id)
                mentioned_node_ids = tuple(
                    str(item) for item in turn.request.get("mentioned_node_ids") or ()
                )
                mentioned_asset_ids = tuple(
                    str(item) for item in turn.request.get("mentioned_image_asset_ids") or ()
                )
                compiled = self._command_compiler.compile(
                    workflow=workflow,
                    turn=turn,
                    envelope=AgentActionEnvelopeV2(
                        assistant_message=result.assistant_message,
                        command_plan=result.command_plan,
                    ),
                    resolved_mentions=ResolvedAgentMentionsV2(
                        explicit_node_ids=mentioned_node_ids,
                        explicit_image_asset_ids=mentioned_asset_ids,
                        candidate_node_ids=(
                            ()
                            if mentioned_node_ids
                            else tuple(node.node_id for node in workflow.nodes[:32])
                        ),
                    ),
                )
                submission = self._command_service.submit(
                    plan=compiled,
                    idempotency_key=f"turn-command:{turn.turn_id}",
                )
                message = (
                    submission.receipt.summary
                    if submission.receipt is not None
                    else "Review and confirm the proposed canvas changes."
                )
            else:
                message = result.assistant_message
        return self._complete_turn(turn_id, turn.workflow_id, message)

    def _process_proposal_action(self, turn_id: str, turn: ChatTurnV2) -> ChatTurnV2:
        proposal_id = str(turn.request["proposal_id"])
        action = ProposalActionRequestV2.model_validate(turn.request["action"])
        proposal = self._conversations.get_proposal(proposal_id)
        if action.action == "select":
            assert action.option_id is not None
            assert action.generation_action is not None
            materialized = self._materialize_specialist_draft(
                turn,
                proposal,
                action.option_id,
            )
            if action.accepted_references is not None:
                accepted_references = tuple(
                    DraftReferenceIntentV2.model_validate(
                        reference.model_dump(
                            include={
                                "source_kind",
                                "source_id",
                                "binding_kind",
                                "input_role",
                                "required",
                                "display_order",
                            }
                        )
                    )
                    for reference in action.accepted_references
                )
                materialized = replace(
                    materialized,
                    draft=materialized.draft.model_copy(
                        update={"reference_intents": accepted_references}
                    ),
                )
            try:
                node = self._materialization.materialize(
                    proposal_id,
                    option_id=action.option_id,
                    draft=materialized.draft,
                    generation_action=action.generation_action,
                    position=action.position,
                    source_turn_id=turn_id,
                )
            except V2PersistenceError as error:
                self._fail_draft_materialization(
                    materialized,
                    proposal.specialist_name,
                    error,
                )
                raise
            self._complete_draft_materialization(materialized, proposal.specialist_name, node)
            continuation: ChatTurnAcceptedV2 | None = None
            try:
                continuation = self._queue_continuation(
                    turn,
                    source_action_id=turn_id,
                )
            except Exception:
                # The committed receipt remains the durable recovery identity.
                continuation = None
            queued_execution_ids: tuple[str, ...] = ()
            run_errors: tuple[str, ...] = ()
            if action.generation_action == "generate_now" and self._run_nodes is not None:
                try:
                    queued_execution_ids = self._run_nodes(
                        turn.workflow_id,
                        (node.node_id,),
                        f"proposal-action:{turn_id}",
                    )
                except Exception:
                    run_errors = ("node_run_queue_failed",)
            receipt = self._store_proposal_receipt(
                turn,
                node=node,
                continuation_turn_id=(continuation.turn_id if continuation is not None else None),
                queued_execution_ids=queued_execution_ids,
                run_errors=run_errors,
            )
            message = receipt.summary
        elif action.action == "revise":
            assert action.instruction is not None
            revised = self._revise_specialist_proposal(turn, proposal, action.instruction)
            self._conversations.mark_proposal(proposal_id, status="revised")
            self._conversations.create_proposal(turn_id, revised)
            message = "The concept options were revised."
        else:
            self._conversations.mark_proposal(proposal_id, status="skipped")
            source_turn = self._conversations.get_turn(proposal.turn_id)
            skill_run_id = source_turn.request.get("video_skill_run_id")
            if isinstance(skill_run_id, str) and skill_run_id:
                self._planning_progress.skip(
                    skill_run_id,
                    _planning_topic_for_proposal(proposal.proposal_kind),
                )
            try:
                continuation = self._queue_continuation(
                    turn,
                    source_action_id=turn_id,
                )
            except Exception:  # noqa: BLE001 - receipt drives restart recovery.
                continuation = None
            receipt = self._store_proposal_receipt(
                turn,
                node=None,
                continuation_turn_id=(continuation.turn_id if continuation is not None else None),
                queued_execution_ids=(),
                run_errors=(),
            )
            message = receipt.summary
        return self._complete_turn(turn_id, turn.workflow_id, message)

    def _process_command_action(self, turn_id: str, turn: ChatTurnV2) -> ChatTurnV2:
        receipt = self._command_service.act(
            plan_id=str(turn.request["plan_id"]),
            action=cast(
                Literal["confirm", "reject"],
                str(turn.request["action"]),
            ),
            expected_revision=int(turn.request["expected_revision"]),
            idempotency_key=turn_id,
        )
        return self._complete_turn(turn_id, turn.workflow_id, receipt.summary)

    def _process_guided_action(self, turn_id: str, turn: ChatTurnV2) -> ChatTurnV2:
        action_id = str(turn.request.get("action_id") or "")
        action = self._conversations.get_guided_action(action_id)
        workflow = self._workflows.get_workflow(turn.workflow_id)
        if workflow.revision != action.expected_semantic_revision:
            raise V2PersistenceError(
                "workflow_revision_conflict",
                "Guided action was authored for an older workflow revision.",
                stage="agent_conversation_service",
            )
        if action.action == "skip_topic":
            if action.topic_id is None:
                raise V2PersistenceError(
                    "guided_action_invalid",
                    "Skip-topic action is missing its topic.",
                    stage="agent_conversation_service",
                )
            session = self._conversations.get_creative_session(turn.workflow_id)
            self._planning_progress.skip(session.skill_run_id, action.topic_id)

        receipt = self._command_service.store_action_receipt(
            AgentActionReceiptV2(
                receipt_id=f"receipt_{uuid4().hex}",
                workflow_id=turn.workflow_id,
                action_id=action.action_id,
                actor_kind="user",
                idempotency_key=turn_id,
                status="applied",
                summary=f"Applied guided action {action.action}.",
                workflow_revision=workflow.revision,
                before_workflow_revision=workflow.revision,
            )
        )
        self._conversations.complete_guided_action(
            action.action_id,
            receipt_id=receipt.receipt_id,
        )

        if action.action in {"generate_node", "run_all_drafts"}:
            node_ids = (
                (action.node_id,)
                if action.action == "generate_node" and action.node_id is not None
                else action.ordered_node_ids
            )
            if not node_ids:
                raise V2PersistenceError(
                    "guided_action_invalid",
                    "Generate action does not contain runnable nodes.",
                    stage="agent_conversation_service",
                )
            if self._run_nodes is not None:
                self._run_nodes(
                    turn.workflow_id,
                    tuple(node_ids),
                    f"guided-action:{action.action_id}",
                )
        elif action.action == "add_another_topic_node":
            self._queue_continuation(
                turn,
                source_action_id=action.action_id,
            )

        return self._complete_turn(
            turn_id,
            turn.workflow_id,
            f"Applied {action.label}.",
        )

    def _complete_turn(
        self,
        turn_id: str,
        workflow_id: str,
        assistant_message: str,
    ) -> ChatTurnV2:
        workflow = self._workflows.get_workflow(workflow_id)
        try:
            topic_id = self._conversations.get_creative_session(workflow_id).current_topic_id
        except V2PersistenceError as error:
            if error.code != "creative_session_not_found":
                raise
            topic_id = None
        return self._conversations.complete_turn(
            turn_id,
            assistant_message=assistant_message,
            guided_actions=self._guided_actions.project(
                workflow,
                creating_turn_id=turn_id,
                topic_id=topic_id,
            ),
        )

    def get_turn(self, turn_id: str) -> ChatTurnV2:
        return self._conversations.get_turn(turn_id)

    def recover_pending_turns(self) -> tuple[ChatTurnV2, ...]:
        recovered_turns = tuple(
            self.process_turn(turn_id)
            for turn_id in self._conversations.list_recoverable_turn_ids()
        )
        self._recover_publication_queue_phases()
        return recovered_turns

    def _recover_publication_queue_phases(self) -> None:
        """Resume only incomplete post-commit work identified by persisted receipts."""

        for receipt, turn in self._conversations.list_publication_receipts_requiring_recovery():
            if turn.turn_kind == "message":
                try:
                    continuation = self._queue_continuation(
                        turn,
                        source_action_id=turn.turn_id,
                    )
                except Exception:  # noqa: BLE001 - receipt remains recoverable after restart.
                    continue
                self._conversations.update_publication_receipt(
                    receipt.model_copy(update={"continuation_turn_id": continuation.turn_id})
                )
                continue
            action = ProposalActionRequestV2.model_validate(turn.request["action"])
            if action.action in {"skip", "select"} and receipt.continuation_turn_id is None:
                try:
                    continuation = self._queue_continuation(
                        turn,
                        source_action_id=turn.turn_id,
                    )
                except Exception:  # noqa: BLE001 - receipt remains recoverable after restart.
                    continue
                receipt = receipt.model_copy(update={"continuation_turn_id": continuation.turn_id})
                self._conversations.update_publication_receipt(receipt)
                if action.action == "skip":
                    continue
            if action.generation_action != "generate_now" or self._run_nodes is None:
                continue
            if len(receipt.created_node_ids) != 1:
                continue
            try:
                queued_execution_ids = self._run_nodes(
                    turn.workflow_id,
                    receipt.created_node_ids,
                    f"proposal-action:{turn.turn_id}",
                )
            except Exception:  # noqa: BLE001 - receipt remains recoverable after restart.
                continue
            self._conversations.update_publication_receipt(
                receipt.model_copy(
                    update={
                        "status": "applied",
                        "queued_execution_ids": queued_execution_ids,
                        "run_queue_errors": (),
                    }
                )
            )

    def get_timeline(
        self,
        workflow_id: str,
        *,
        after_seq: int = 0,
        limit: int = 100,
    ) -> ChatTimelineListResponseV2:
        self._workflows.get_workflow(workflow_id)
        return self._conversations.list_timeline(
            workflow_id,
            after_seq=after_seq,
            limit=limit,
        )

    def get_proposal(self, workflow_id: str, proposal_id: str):
        self._workflows.get_workflow(workflow_id)
        proposal = self._conversations.get_proposal(proposal_id)
        if proposal.workflow_id != workflow_id:
            raise V2PersistenceError(
                "proposal_not_found",
                "Concept proposal was not found.",
                stage="agent_conversation_service",
            )
        return proposal

    def _director_context(self, turn: ChatTurnV2) -> DirectorTurnContextV2:
        if self._context_assembler is None:
            raise V2PersistenceError(
                "agent_context_unavailable",
                "Agent local context assembler is unavailable.",
                stage="agent_conversation_service",
            )
        workflow = self._workflows.get_workflow(turn.workflow_id)
        timeline = self._conversations.list_timeline(turn.workflow_id)
        recent = tuple(
            {
                "sequence_no": item.sequence_no,
                "role": "user" if item.speaker == "user" else "assistant",
                "content": item.content,
            }
            for item in timeline.items
            if item.entry_type == "message" and item.speaker is not None
        )[-16:]
        video_skill_run_id = turn.request.get("video_skill_run_id")
        skill_run = (
            self._conversations.get_skill_run(video_skill_run_id)
            if isinstance(video_skill_run_id, str)
            else self._active_or_default_session(turn.workflow_id)
        )
        if skill_run.workflow_id != turn.workflow_id or skill_run.status != "active":
            raise V2PersistenceError(
                "creative_session_conflict",
                "Creative session does not belong to this Workflow.",
                stage="agent_conversation_service",
            )
        selected_skill = self._video_skills.load(skill_run.skill_id, skill_run.skill_version)
        return self._context_assembler.assemble_director_turn(
            turn.workflow_id,
            conversation_id=turn.conversation_id,
            user_input=str(turn.request.get("text") or ""),
            mentioned_node_ids=tuple(turn.request.get("mentioned_node_ids") or ()),
            mentioned_image_asset_ids=tuple(turn.request.get("mentioned_image_asset_ids") or ()),
            recent_messages=recent,
            video_skill_excerpt=selected_skill.instructions,
            creative_session=self._conversations.get_creative_session(turn.workflow_id),
            creative_memory=self._conversations.get_creative_memory(turn.workflow_id),
        ).model_copy(update={"workflow_revision": workflow.revision})

    def _active_or_default_session(self, workflow_id: str):
        try:
            return self._conversations.get_skill_run(
                self._conversations.get_creative_session(workflow_id).skill_run_id
            )
        except V2PersistenceError as error:
            if error.code != "creative_session_not_found":
                raise
        skill = self._video_skills.load("platform-default", "1")
        return self._conversations.create_skill_run(
            workflow_id,
            skill_id=skill.manifest.skill_id,
            skill_version=skill.manifest.version,
            recipe_topics=tuple(skill.recipe["planning_topics"]),
            idempotency_key=f"recovery-session:{workflow_id}",
        )

    def _queue_continuation(
        self,
        turn: ChatTurnV2,
        *,
        source_action_id: str,
    ) -> ChatTurnAcceptedV2:
        return self._conversations.create_continuation_turn(
            turn.workflow_id,
            source_action_id=source_action_id,
            workflow_revision=self._workflows.get_workflow(turn.workflow_id).revision,
            video_skill_run_id=(
                str(turn.request.get("video_skill_run_id"))
                if turn.request.get("video_skill_run_id")
                else None
            ),
            idempotency_key=f"continuation:{source_action_id}",
        )

    def _materialize_specialist_draft(
        self,
        turn: ChatTurnV2,
        proposal,
        option_id: str,
    ) -> SpecialistDraftMaterialization:
        option = next(
            (item for item in proposal.options if item.option_id == option_id),
            None,
        )
        if option is None:
            raise V2PersistenceError(
                "proposal_option_not_found",
                "Concept option was not found.",
                stage="agent_conversation_service",
            )
        activity = self._conversations.start_expert_activity(
            turn.turn_id,
            specialist_name=proposal.specialist_name,
            operation="materialize_draft",
            label=f"{proposal.specialist_name} is materializing a Draft",
            event_details={
                "conversation_id": turn.conversation_id,
                "proposal_id": proposal.proposal_id,
                "option_id": option.option_id,
            },
        )
        try:
            prompt = (
                option.draft_spec.prompt if option.draft_spec is not None else option.summary_prompt
            )
            node_type = _node_type_for_proposal(proposal.proposal_kind)
            draft = SpecialistDraftV2(
                node_type=node_type,
                creative_role=_semantic_role_for_proposal(proposal.proposal_kind),
                title=f"{option.title} Draft",
                summary_prompt=option.summary_prompt,
                generation_prompt=None if node_type == "script" else prompt,
                structured_content=_structured_content_for_proposal(
                    proposal.proposal_kind,
                    prompt,
                ),
                parameters={},
            )
            SpecialistDraftValidationService().validate(proposal, draft)
        except V2PersistenceError as error:
            self._conversations.transition_expert_activity(
                activity.activity_id,
                status="failed",
                label=f"{proposal.specialist_name} returned an incompatible Draft",
                error_code=error.code,
                error_message=str(error),
            )
            raise
        except (TypeError, ValueError) as error:
            self._conversations.transition_expert_activity(
                activity.activity_id,
                status="failed",
                label=f"{proposal.specialist_name} returned an invalid Draft",
                error_code="specialist_draft_invalid",
                error_message="Specialist Draft is invalid.",
            )
            raise V2PersistenceError(
                "specialist_draft_invalid",
                "Specialist Draft is invalid.",
                stage="agent_conversation_service",
            ) from error
        return SpecialistDraftMaterialization(
            draft=draft,
            activity_id=activity.activity_id,
            proposal_id=proposal.proposal_id,
            option_id=option.option_id,
            conversation_id=turn.conversation_id,
        )

    def _complete_draft_materialization(
        self,
        materialized: SpecialistDraftMaterialization,
        specialist_name: str,
        node: CanvasNodeV2,
    ) -> None:
        bindings = tuple(
            binding.binding_id
            for binding in self._workflows.get_workflow(node.workflow_id).bindings
            if binding.target_node_id == node.node_id
        )
        self._conversations.transition_expert_activity(
            materialized.activity_id,
            status="completed",
            label=f"{specialist_name} materialized a Draft",
            event_details={
                "node_id": node.node_id,
                "creative_role": node.creative_role,
                "binding_ids": list(bindings),
                "conversation_id": materialized.conversation_id,
                "proposal_id": materialized.proposal_id,
                "option_id": materialized.option_id,
            },
        )

    def _fail_draft_materialization(
        self,
        materialized: SpecialistDraftMaterialization,
        specialist_name: str,
        error: V2PersistenceError,
    ) -> None:
        self._conversations.transition_expert_activity(
            materialized.activity_id,
            status="failed",
            label=f"{specialist_name} failed to publish a Draft",
            error_code=error.code,
            error_message=str(error),
            event_details={
                "conversation_id": materialized.conversation_id,
                "proposal_id": materialized.proposal_id,
                "option_id": materialized.option_id,
            },
        )

    def _revise_specialist_proposal(
        self,
        turn: ChatTurnV2,
        proposal,
        instruction: str,
    ) -> ConceptProposalCreateV2:
        source_turn = self._conversations.get_turn(proposal.turn_id)
        context = self._director_context(source_turn)
        specialist_context = SpecialistContextV2(
            context_kind="specialist_handoff",
            specialist_name=proposal.specialist_name,
            operation="revise_concepts",
            workflow_id=proposal.workflow_id,
            workflow_revision=self._workflows.get_workflow(proposal.workflow_id).revision,
            user_instruction=instruction,
            selected_option_summary="\n".join(option.description for option in proposal.options),
            script_summary=context.script_summary,
            video_skill_excerpt=context.video_skill_excerpt,
            explicit_input_summaries=context.explicit_input_summaries,
            creative_session=context.creative_session,
            creative_memory=context.creative_memory,
            resolved_image_targets=context.resolved_image_targets,
        )
        revise = getattr(self._gateway, "run_specialist", None)
        if not callable(revise):
            raise V2PersistenceError(
                "specialist_revision_failed",
                "The selected Specialist cannot revise concepts.",
                stage="agent_conversation_service",
            )
        activity = self._conversations.start_expert_activity(
            turn.turn_id,
            specialist_name=proposal.specialist_name,
            operation="revise_concepts",
            label=f"{proposal.specialist_name} is revising concepts",
        )
        try:
            revised = ConceptProposalCreateV2.model_validate(
                revise(specialist_context, turn_id=turn.turn_id)
            )
        except PiAgentRuntimeError as error:
            self._conversations.transition_expert_activity(
                activity.activity_id,
                status="failed",
                label=f"{proposal.specialist_name} failed to revise concepts",
                error_code=error.code,
                error_message=error.message,
            )
            raise
        except (TypeError, ValueError) as error:
            self._conversations.transition_expert_activity(
                activity.activity_id,
                status="failed",
                label=f"{proposal.specialist_name} returned invalid revised concepts",
                error_code="specialist_revision_failed",
                error_message="Specialist revision is invalid.",
            )
            raise V2PersistenceError(
                "specialist_revision_failed",
                "Specialist revision is invalid.",
                stage="agent_conversation_service",
            ) from error
        if (
            revised.proposal_kind != proposal.proposal_kind
            or revised.specialist_name != proposal.specialist_name
        ):
            self._conversations.transition_expert_activity(
                activity.activity_id,
                status="failed",
                label=f"{proposal.specialist_name} returned incompatible revised concepts",
                error_code="specialist_revision_failed",
                error_message="Specialist revision is incompatible with the proposal.",
            )
            raise V2PersistenceError(
                "specialist_revision_failed",
                "Specialist revision is incompatible with the proposal.",
                stage="agent_conversation_service",
            )
        self._conversations.transition_expert_activity(
            activity.activity_id,
            status="completed",
            label=f"{proposal.specialist_name} revised concepts",
        )
        return revised

    def _store_proposal_receipt(
        self,
        turn: ChatTurnV2,
        *,
        node: CanvasNodeV2 | None,
        continuation_turn_id: str | None,
        queued_execution_ids: tuple[str, ...],
        run_errors: tuple[str, ...],
    ):
        from app.schemas.agent_canvas_conversation import AgentActionReceiptV2

        receipt = AgentActionReceiptV2(
            receipt_id=f"receipt_{turn.turn_id}",
            workflow_id=turn.workflow_id,
            action_id=turn.turn_id,
            status="applied_with_run_error" if run_errors else "applied",
            summary=(
                "The selected concept is now an editable Draft."
                if node is not None
                else "The concept was skipped."
            ),
            created_node_ids=(node.node_id,) if node is not None else (),
            queued_execution_ids=queued_execution_ids,
            run_queue_errors=run_errors,
            workflow_revision=self._workflows.get_workflow(turn.workflow_id).revision,
            continuation_turn_id=continuation_turn_id,
        )
        stored = self._conversations.update_publication_receipt(receipt)
        if stored is not None:
            return stored
        return AgentCanvasCommandRepository(
            self._workflows.database,
            EventRepository(self._workflows.database),
        ).store_receipt(receipt)


def _node_type_for_proposal(proposal_kind: str) -> str:
    if proposal_kind == "script":
        return "script"
    if proposal_kind == "video":
        return "video"
    if proposal_kind == "bgm":
        return "audio"
    return "image"


def _proposal_kind_for_specialist(specialist_name: str) -> str:
    return {
        "script_writer": "script",
        "product_designer": "product",
        "prop_designer": "prop",
        "character_designer": "character",
        "scene_designer": "scene",
        "storyboard_artist": "storyboard",
        "video_director": "video",
        "bgm_director": "bgm",
    }[specialist_name]


def _semantic_role_for_proposal(proposal_kind: str) -> str:
    return {
        "script": "script",
        "product": "product",
        "prop": "prop",
        "character": "character",
        "scene": "scene",
        "storyboard": "storyboard_sequence",
        "video": "storyboard_video",
        "bgm": "bgm",
    }[proposal_kind]


def _planning_topic_for_proposal(proposal_kind: str) -> str:
    return {
        "script": "script",
        "product": "product",
        "prop": "props",
        "character": "characters",
        "scene": "scenes",
        "storyboard": "storyboard",
        "video": "videos",
        "bgm": "bgm",
    }[proposal_kind]


def _structured_content_for_proposal(
    proposal_kind: str,
    description: str,
) -> dict[str, object]:
    style = {
        "style_prompt": "Detailed semi-realistic advertising illustration",
        "source": "platform_default",
        "negative_style_constraints": [],
    }
    if proposal_kind == "script":
        return {"content": description}
    if proposal_kind in {"product", "prop", "character"}:
        return {
            "subject_identity": description,
            "design_summary": description,
            "style": style,
            "explicit_inclusions": [],
            "negative_constraints": [],
        }
    if proposal_kind == "scene":
        return {
            "scene_identity": description,
            "environment_summary": description,
            "layout": "One coherent advertising environment",
            "lighting": "Consistent commercial lighting",
            "materials": "Consistent materials across every panel",
            "time_of_day": "Day",
            "style": style,
            "panels": [
                {
                    "panel_index": index,
                    "view_or_zone": f"Spatial view {index}",
                    "spatial_description": description,
                    "lighting_material_detail": "Preserve the same lighting and materials.",
                }
                for index in range(1, 10)
            ],
            "explicit_entity_reference_ids": [],
            "exclude_unreferenced_entities": True,
            "no_narrative_progression": True,
        }
    if proposal_kind == "storyboard":
        return {
            "sequence_summary": description,
            "narrative_goal": description,
            "style": style,
            "panels": [
                {
                    "panel_index": index,
                    "beat": f"Beat {index}: {description}",
                    "composition": "Advertising composition",
                    "camera": "Intentional cinematic framing",
                    "subject_action": description,
                    "continuity_from_previous": (
                        "Opening frame" if index == 1 else "Continue from the previous panel"
                    ),
                }
                for index in range(1, 10)
            ],
            "no_generated_text": True,
        }
    if proposal_kind == "video":
        return {
            "segment_summary": description,
            "duration_seconds": 8,
            "storyboard_content": description,
            "dialogue": "",
            "voice_style": "",
            "environment_sound": "",
            "action_effects": "",
            "negative_constraints": "",
            "background_music": False,
        }
    if proposal_kind == "bgm":
        return {
            "music_summary": description,
            "duration_seconds": 30,
            "pace": "Medium",
            "energy_curve": "Build and resolve",
            "instrumentation": "Instrumental ensemble",
            "mood": "Confident",
            "instrumental_only": True,
            "no_vocals": True,
        }
    raise ValueError(f"Unsupported proposal kind: {proposal_kind}")
