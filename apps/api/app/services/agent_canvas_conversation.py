"""Director-owned Agent Canvas conversation and proposal orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Literal, Protocol, cast
from uuid import uuid4

from pydantic import TypeAdapter

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.agent_canvas_command_repository import (
    AgentCanvasCommandRepository,
)
from app.persistence.event_repository import EventRepository
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
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
    ContinuationCommitV2,
    ProposalActionRequestV2,
)
from app.schemas.agent_canvas_creative_session import (
    CreationModeDecisionV2,
    DraftReferenceIntentV2,
    GuidanceSessionActionV2,
    SpecialistDraftV2,
    DelegatedProposalChoiceV2,
    NextGuidanceDecisionV2,
)
from app.schemas.agent_operation_contexts import (
    AgentCommandReplanContextV2,
    CreativeAnchorSetV2,
    DirectorTurnContextV2,
    DirectorGuidanceContextV2,
    DelegatedProposalChoiceContextV2,
    GuidanceSpecialistContextV2,
    ProposalRevisionContextV2,
    ProposalRevisionOptionV2,
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
from app.services.model_resolution import ModelResolutionService
from app.services.agent_run_envelope import agent_run_envelope_fields
from app.services.pi_agent_runtime_client import PiAgentRuntimeError
from app.services.agent_canvas_nodes import AgentCanvasNodeService
from app.services.agent_canvas_command_compiler import (
    AgentCommandPlanCompiler,
)
from app.services.agent_canvas_commands import AgentCanvasCommandService
from app.services.agent_canvas_context import AgentLocalContextAssembler
from app.services.agent_canvas_connection_policy import AgentCanvasConnectionPolicyService
from app.services.agent_canvas_ad_media import AdMediaDraftValidationService
from app.services.agent_canvas_specialist_labels import specialist_display_name
from app.services.agent_canvas_video_skills import VideoSkillRegistry
from app.services.agent_canvas_guidance_context import GuidanceContextBuilder
from app.services.agent_canvas_guidance_decision import (
    GuidanceCompletionService,
    GuidanceDecisionValidator,
)


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


def _continuation_commit(
    turn: ChatTurnV2,
    *,
    source_action_id: str,
) -> ContinuationCommitV2:
    continuation_turn_id = (
        "turn_" + hashlib.sha256(f"continuation:{source_action_id}".encode()).hexdigest()[:32]
    )
    continuation_id = (
        "continuation_"
        + hashlib.sha256(
            f"{turn.workflow_id}:{continuation_turn_id}:conversation_turn".encode()
        ).hexdigest()[:24]
    )
    return ContinuationCommitV2(
        continuation_id=continuation_id,
        continuation_turn_id=continuation_turn_id,
        source_turn_id=turn.turn_id,
        source_action_id=source_action_id,
        idempotency_key=f"continuation:{source_action_id}",
        video_skill_run_id=(
            str(turn.request.get("video_skill_run_id"))
            if turn.request.get("video_skill_run_id")
            else None
        ),
    )


class DirectorGateway(Protocol):
    def resolve_creation_mode(
        self,
        context: DirectorTurnContextV2,
        *,
        turn_id: str,
    ) -> CreationModeDecisionV2: ...

    def decide_next_guidance_step(
        self,
        context: DirectorGuidanceContextV2,
        *,
        turn_id: str,
        parent_run_id: str | None = None,
    ) -> NextGuidanceDecisionV2: ...

    def choose_delegated_proposal_option(
        self,
        context: DelegatedProposalChoiceContextV2,
        *,
        turn_id: str,
        parent_run_id: str | None = None,
    ) -> DelegatedProposalChoiceV2: ...

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
        context: SpecialistContextV2 | GuidanceSpecialistContextV2,
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

    def resolve_creation_mode(
        self,
        context: DirectorTurnContextV2,
        *,
        turn_id: str,
    ) -> CreationModeDecisionV2:
        return CreationModeDecisionV2(
            mode="ordinary_conversation",
            reason="The deterministic runtime records the message without authoring.",
        )

    def decide_next_guidance_step(
        self,
        context: DirectorGuidanceContextV2,
        *,
        turn_id: str,
        parent_run_id: str | None = None,
    ) -> NextGuidanceDecisionV2:
        return NextGuidanceDecisionV2(
            action="ordinary_reply",
            assistant_message=f"Your request is recorded for this canvas: {context.user_input}",
            rationale="The deterministic test gateway performs no creative inference.",
        )

    def choose_delegated_proposal_option(
        self,
        context: DelegatedProposalChoiceContextV2,
        *,
        turn_id: str,
        parent_run_id: str | None = None,
    ) -> DelegatedProposalChoiceV2:
        raise PiAgentRuntimeError(
            "delegated_proposal_choice_unavailable",
            "Delegated Proposal choice requires a configured Director.",
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
        context: SpecialistContextV2 | GuidanceSpecialistContextV2,
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
        model_resolution: ModelResolutionService,
    ) -> None:
        self._durable_runner = durable_runner
        self._timeout_seconds = timeout_seconds
        self._model_resolution = model_resolution

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

    def resolve_creation_mode(
        self,
        context: DirectorTurnContextV2,
        *,
        turn_id: str,
    ) -> CreationModeDecisionV2:
        value, _ = self._run(
            agent_name="director",
            operation="resolve_creation_mode",
            context=context,
            contract=CreationModeDecisionV2,
            max_handoffs=0,
            identity_fields={
                "workflow_id": context.workflow_id,
                "conversation_id": context.conversation_id,
                "turn_id": turn_id,
                "agent_name": "director",
                "operation": "resolve_creation_mode",
            },
        )
        return CreationModeDecisionV2.model_validate(value)

    def decide_next_guidance_step(
        self,
        context: DirectorGuidanceContextV2,
        *,
        turn_id: str,
        parent_run_id: str | None = None,
    ) -> NextGuidanceDecisionV2:
        value, _ = self._run(
            agent_name="director",
            operation="decide_next_guidance_step",
            context=context,
            contract=NextGuidanceDecisionV2,
            max_handoffs=0,
            parent_run_id=parent_run_id,
            identity_fields={
                "workflow_id": context.workflow_id,
                "conversation_id": context.conversation_id,
                "turn_id": turn_id,
                "agent_name": "director",
                "operation": "decide_next_guidance_step",
            },
        )
        return NextGuidanceDecisionV2.model_validate(value)

    def choose_delegated_proposal_option(
        self,
        context: DelegatedProposalChoiceContextV2,
        *,
        turn_id: str,
        parent_run_id: str | None = None,
    ) -> DelegatedProposalChoiceV2:
        value, _ = self._run(
            agent_name="director",
            operation="proposal_action",
            context=context,
            contract=DelegatedProposalChoiceV2,
            max_handoffs=0,
            parent_run_id=parent_run_id,
            identity_fields={
                "workflow_id": context.workflow_id,
                "proposal_id": context.proposal_id,
                "turn_id": turn_id,
                "agent_name": "director",
                "operation": "proposal_action",
            },
        )
        return DelegatedProposalChoiceV2.model_validate(value)

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
                guidance_session=context.guidance_session,
                creative_memory=context.creative_memory,
                resolved_image_targets=context.resolved_image_targets,
                current_topic_id=None,
                proposal_mode=None,
                candidate_count=None,
                approved_anchor_summaries=_approved_anchor_summaries(context),
            ),
        )

    def run_specialist(
        self,
        context: SpecialistContextV2 | GuidanceSpecialistContextV2,
        *,
        turn_id: str,
        parent_run_id: str | None = None,
    ) -> ConceptProposalCreateV2:
        operation = (
            "propose_concepts"
            if isinstance(context, GuidanceSpecialistContextV2)
            else context.operation
        )
        if operation not in {"propose_concepts", "revise_concepts"}:
            raise PiAgentRuntimeError(
                "agent_specialist_operation_unsupported",
                "The requested Specialist operation is not supported.",
            )
        proposal_value, _ = self._run(
            agent_name=context.specialist_name,
            operation=operation,
            context=context,
            contract=ConceptProposalDraftV2,
            max_handoffs=0,
            parent_run_id=parent_run_id,
            identity_fields={
                "workflow_id": context.workflow_id,
                "turn_id": turn_id,
                "agent_name": context.specialist_name,
                "operation": operation,
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
            topic_id=(
                context.topic_id
                if isinstance(context, GuidanceSpecialistContextV2)
                else context.current_topic_id
            ),
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
        context: (
            DirectorTurnContextV2
            | DirectorGuidanceContextV2
            | DelegatedProposalChoiceContextV2
            | GuidanceSpecialistContextV2
            | AgentCommandReplanContextV2
            | SpecialistContextV2
        ),
        contract,
        max_handoffs: int,
        identity_fields: dict[str, str | int],
        parent_run_id: str | None = None,
    ) -> tuple[dict[str, object], str]:
        resolution = self._model_resolution.resolve_selection(
            node_type="script",
            model_selection_mode="default",
            model_ref=None,
        )
        operation_timeout = _guidance_operation_timeout(operation)
        request = AgentRunRequest(
            run_id="candidate_agent_run",
            request_id="candidate_agent_request",
            **agent_run_envelope_fields(context),
            parent_run_id=parent_run_id,
            agent_name=agent_name,
            operation=operation,
            deadline_at=datetime.now(timezone.utc) + timedelta(seconds=operation_timeout),
            model_policy_id=f"{agent_name}.{operation}.v1",
            model_ref=resolution.model_ref,
            context=context,
            policy=AgentRunPolicy(
                max_handoffs=max_handoffs,
                timeout_seconds=operation_timeout,
            ),
            contract_name=contract.__name__,
            contract_schema=contract.model_json_schema(),
            audit_metadata={
                "tool_mode": "structured_only",
                "model_identity": {
                    "model_ref": resolution.model_ref,
                    "provider_id": resolution.provider_id,
                    "provider_model_id": resolution.provider_model_id,
                    "capability": resolution.capability,
                    "provider_protocol": resolution.provider_protocol,
                    "catalog_revision": resolution.catalog_revision,
                    "provider_revision": resolution.credential_revision,
                },
            },
        )
        result = self._durable_runner.run(
            request,
            identity_fields=identity_fields,
            model_ref=resolution.model_ref,
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


def _guidance_operation_timeout(operation: str) -> float:
    return 180.0 if operation == "resolve_creation_mode" else 300.0


class GuidanceSessionActionService:
    """Project the one action available for the current Guidance session state."""

    def project(
        self,
        session,
        *,
        creating_turn_id: str,
    ) -> tuple[GuidanceSessionActionV2, ...]:
        if session is None or session.status == "completed":
            return ()
        action = "stop_guidance" if session.status == "active" else "resume_guidance"
        logical_key = f"{session.session_id}:{session.revision}:{action}"
        return (
            GuidanceSessionActionV2(
                action_id=(
                    "guided_" + hashlib.sha256(logical_key.encode("utf-8")).hexdigest()[:32]
                ),
                logical_key=logical_key,
                action=action,
                state="pending",
                creating_turn_id=creating_turn_id,
                expected_session_revision=session.revision,
                label="Stop guidance" if action == "stop_guidance" else "Resume guidance",
                workflow_id=session.workflow_id,
                confirmation_required=True,
                reason=(
                    "Pause progressive guidance without changing the Canvas."
                    if action == "stop_guidance"
                    else "Resume progressive guidance from the persisted session state."
                ),
            ),
        )


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


class GuidanceProposalActionService:
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
        expected_session_revision: int,
        proposal_action: Literal["select_option", "delegate_choice"],
        selection_actor: str = "user",
        source_turn_id: str | None = None,
        continuation: ContinuationCommitV2 | None = None,
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
            },
            position=CanvasPositionV2(x=0, y=0),
            revision=1,
            created_at=now,
            updated_at=now,
        )
        allowed_sources = {
            (reference.source_kind, reference.source_id)
            for reference in proposal.proposed_references
        }
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
                proposal_id=proposal.proposal_id,
                proposal_option_id=option_id,
                proposal_action=proposal_action,
                status="applied",
                summary="The selected concept is now an editable Draft.",
                created_node_ids=(node.node_id,),
                created_binding_ids=tuple(binding.binding_id for binding in bindings),
                workflow_revision=workflow.revision + 1,
            )
            if source_turn_id is not None
            else None
        )
        if continuation is not None and receipt is not None:
            if continuation.source_turn_id != source_turn_id:
                raise V2PersistenceError(
                    "continuation_context_invalid",
                    "Continuation source does not match the action turn.",
                    stage="draft_materialization",
                )
            receipt = receipt.model_copy(
                update={"continuation_turn_id": continuation.continuation_turn_id}
            )
        self._conversations.apply_and_materialize(
            proposal_id,
            option_id=option_id,
            node=node,
            bindings=bindings,
            expected_workflow_revision=workflow.revision,
            selection_actor=selection_actor,
            source_turn_id=source_turn_id,
            skill_run_id=proposal.video_skill_run_id,
            topic_id=proposal.topic_id,
            expected_session_revision=expected_session_revision,
            proposal_action=proposal_action,
            receipt=receipt,
            continuation=continuation,
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
                        "proposal_reference_unavailable",
                        "Image asset references require the project asset resolver.",
                        stage="draft_materialization",
                    )
                try:
                    asset = self._asset_resolver(intent.source_id)
                except (KeyError, LookupError) as error:
                    raise V2PersistenceError(
                        "proposal_reference_unavailable",
                        "Draft reference asset was not found.",
                        stage="draft_materialization",
                    ) from error
                if asset.media_type != "image" or asset.status != "ready":
                    raise V2PersistenceError(
                        "proposal_reference_unavailable",
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
        continuation_outbox: AgentCanvasContinuationOutboxRepository | None = None,
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
        self._asset_resolver = asset_resolver
        self._session_actions = GuidanceSessionActionService()
        self._continuation_outbox = continuation_outbox or (
            AgentCanvasContinuationOutboxRepository(
                workflows.database,
                EventRepository(workflows.database),
            )
        )
        self._materialization = GuidanceProposalActionService(
            workflows,
            conversations,
            asset_resolver=asset_resolver,
            connection_policy=connection_policy,
        )
        self._guidance_contexts = GuidanceContextBuilder()
        self._guidance_decisions = GuidanceDecisionValidator()
        self._guidance_completion = GuidanceCompletionService()

    def submit_message(
        self,
        workflow_id: str,
        *,
        text: str,
        idempotency_key: str,
        mentioned_node_ids: tuple[str, ...] = (),
        mentioned_image_asset_ids: tuple[str, ...] = (),
        video_skill_run_id: str | None = None,
    ) -> ChatTurnAcceptedV2:
        self._workflows.get_workflow(workflow_id)
        if video_skill_run_id is None:
            video_skill_run_id = self._conversations.get_active_style_skill_run(
                workflow_id
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
        existing_turn = self._conversations.get_turn_by_idempotency_key(idempotency_key)
        if existing_turn is not None:
            return self._conversations.create_action_turn(
                workflow_id,
                proposal_id=proposal_id,
                action=request,
                idempotency_key=idempotency_key,
            )
        if proposal.availability != "open":
            raise V2PersistenceError(
                "proposal_action_stale",
                "Concept proposal is not available for application.",
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
        workflow = self._workflows.get_workflow(turn.workflow_id)
        session = self._conversations.get_guidance_session_or_none(turn.workflow_id)
        open_proposals = self._conversations.list_open_proposals(turn.workflow_id)
        open_proposal = open_proposals[0] if open_proposals else None
        style_run = self._conversations.get_active_style_skill_run(turn.workflow_id)
        style = self._video_skills.load(style_run.skill_id, style_run.skill_version)
        memory = self._conversations.get_creative_memory(turn.workflow_id)
        mentioned_node_ids = tuple(
            str(item) for item in turn.request.get("mentioned_node_ids") or ()
        )
        mentioned_asset_ids = tuple(
            str(item) for item in turn.request.get("mentioned_image_asset_ids") or ()
        )
        image_assets: tuple[ProjectAssetSummaryV2, ...] = ()
        if mentioned_asset_ids:
            if self._asset_resolver is None:
                raise V2PersistenceError(
                    "specialist_context_invalid",
                    "Guidance image references require the project asset resolver.",
                    stage="agent_conversation_service",
                )
            image_assets = tuple(self._asset_resolver(asset_id) for asset_id in mentioned_asset_ids)
        director_context = self._guidance_contexts.build_director(
            workflow,
            conversation_id=turn.conversation_id,
            user_input=str(turn.request.get("text") or ""),
            conversation_summary=memory.conversation_summary,
            session=session,
            open_proposal=open_proposal,
            style_run=style_run,
            style_summary=memory.approved_style_summary or style.instructions,
            mentioned_node_ids=mentioned_node_ids,
            image_assets=image_assets,
        )
        decision = self._gateway.decide_next_guidance_step(
            director_context,
            turn_id=turn_id,
        )
        decision = self._guidance_decisions.validate(
            decision,
            session=session,
            workflow=workflow,
            resolved_targets=mentioned_node_ids,
            open_proposal=open_proposal,
        )
        completion = None
        if decision.action == "finish_guidance":
            goal = session.goal if session is not None else decision.intent_patch.goal
            completion_assets = workflow.assets
            if decision.completion_claim.asset_ids:
                if self._asset_resolver is None:
                    raise V2PersistenceError(
                        "guidance_completion_invalid",
                        "Generated-media completion requires canonical Asset resolution.",
                        stage="guidance_completion_service",
                    )
                try:
                    completion_assets = tuple(
                        self._asset_resolver(asset_id)
                        for asset_id in decision.completion_claim.asset_ids
                    )
                except (KeyError, LookupError, V2PersistenceError) as error:
                    raise V2PersistenceError(
                        "guidance_completion_invalid",
                        "The completion claim references an unavailable Asset.",
                        stage="guidance_completion_service",
                    ) from error
            completion = self._guidance_completion.validate(
                goal,
                decision.completion_claim,
                workflow,
                completion_assets,
            )
        session = self._conversations.persist_guidance_decision(
            turn_id,
            decision,
            expected_session_revision=session.revision if session is not None else None,
        )
        if decision.action == "finish_guidance":
            assert session is not None and completion is not None
            self._conversations.complete_guidance_session(
                session.session_id,
                expected_session_revision=session.revision,
                completion=completion,
            )
        elif decision.action == "propose_topic":
            assert session is not None
            specialist_context = self._guidance_contexts.build_specialist(
                workflow,
                decision=decision,
                session=session,
                user_instruction=str(turn.request.get("text") or ""),
                style_excerpt=style.instructions,
                accepted_anchors=tuple(
                    node_id
                    for node_ids in memory.approved_node_ids.values()
                    for node_id in node_ids
                ),
                image_assets=image_assets,
                relevant_node_ids=mentioned_node_ids,
                targeted_prompt_baseline=(
                    self._workflows.get_node(
                        turn.workflow_id, mentioned_node_ids[0]
                    ).generation_prompt
                    if len(mentioned_node_ids) == 1
                    else None
                ),
            )
            activity = self._conversations.start_expert_activity(
                turn_id,
                specialist_name=specialist_context.specialist_name,
                operation="propose_concepts",
                display_name=specialist_display_name(specialist_context.specialist_name),
            )
            try:
                created = proposal or self._gateway.run_specialist(
                    specialist_context,
                    turn_id=turn_id,
                )
                if len(created.options) != decision.candidate_count:
                    raise V2PersistenceError(
                        "specialist_proposal_invalid",
                        "Specialist Proposal option count does not match the decision.",
                        stage="agent_conversation_service",
                    )
                created = created.model_copy(update={"topic_id": decision.topic_id})
                self._conversations.create_proposal(turn_id, created)
            except (PiAgentRuntimeError, V2PersistenceError) as error:
                self._conversations.transition_expert_activity(
                    activity.activity_id,
                    status="failed",
                    error_code=error.code,
                    error_message=str(error),
                )
                raise
            self._conversations.transition_expert_activity(
                activity.activity_id,
                status="completed",
            )
        return self._complete_turn(turn_id, turn.workflow_id, decision.assistant_message)

    def _process_proposal_action(self, turn_id: str, turn: ChatTurnV2) -> ChatTurnV2:
        committed_receipt = self._conversations.get_publication_receipt_for_action(turn_id)
        if committed_receipt is not None:
            return self._complete_turn(turn_id, turn.workflow_id, committed_receipt.summary)
        proposal_id = str(turn.request["proposal_id"])
        action = TypeAdapter(ProposalActionRequestV2).validate_python(turn.request["action"])
        proposal = self._conversations.get_proposal(proposal_id)
        descriptor = next(
            (
                item
                for item in proposal.actions
                if item.action_id == action.action_id and item.action == action.action
            ),
            None,
        )
        if proposal.availability != "open" or descriptor is None:
            raise V2PersistenceError(
                "proposal_action_stale",
                "Proposal action is no longer available.",
                stage="agent_conversation_service",
            )
        session = self._conversations.get_guidance_session(turn.workflow_id)
        if (
            action.expected_session_revision != descriptor.expected_session_revision
            or session.revision != action.expected_session_revision
        ):
            raise V2PersistenceError(
                "guidance_revision_conflict",
                "Guidance session revision is stale.",
                stage="agent_conversation_service",
            )
        if action.action == "select_option":
            materialized = self._materialize_specialist_draft(
                turn,
                proposal,
                action.option_id,
            )
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
            continuation = (
                _continuation_commit(turn, source_action_id=turn_id)
                if session.status == "active"
                else None
            )
            try:
                node = self._materialization.materialize(
                    proposal_id,
                    option_id=action.option_id,
                    draft=materialized.draft,
                    expected_session_revision=action.expected_session_revision,
                    proposal_action="select_option",
                    source_turn_id=turn_id,
                    continuation=continuation,
                )
            except V2PersistenceError as error:
                self._fail_draft_materialization(materialized, error)
                raise
            self._complete_draft_materialization(materialized, node)
            receipt = self._conversations.get_publication_receipt_for_action(turn_id)
            message = receipt.summary if receipt is not None else "The Draft is ready to edit."
            return self._complete_turn(turn_id, turn.workflow_id, message)
        if action.action in {"defer_topic", "exclude_element"}:
            continuation = (
                _continuation_commit(turn, source_action_id=turn_id)
                if session.status == "active"
                else None
            )
            receipt = self._conversations.apply_guidance_state_action(
                proposal_id,
                source_turn_id=turn_id,
                action_id=action.action_id,
                action=action.action,
                expected_session_revision=action.expected_session_revision,
                continuation=continuation,
            )
            return self._complete_turn(turn_id, turn.workflow_id, receipt.summary)
        if action.action == "revise_options":
            revised = self._revise_specialist_proposal(turn, proposal, action)
            revised = revised.model_copy(
                update={
                    "topic_id": proposal.topic_id,
                    "target_node_id": proposal.target_node_id,
                    "target_node_revision": proposal.target_node_revision,
                    "proposal_purpose": proposal.proposal_purpose,
                }
            )
            receipt = AgentActionReceiptV2(
                receipt_id=f"receipt_{turn_id}",
                workflow_id=turn.workflow_id,
                action_id=turn_id,
                proposal_id=proposal_id,
                proposal_action="revise_options",
                actor_kind="user",
                idempotency_key=turn_id,
                status="applied",
                summary="The concept options were revised.",
                workflow_revision=self._workflows.get_workflow(turn.workflow_id).revision,
            )
            self._conversations.create_proposal(
                turn_id,
                revised,
                source_proposal_id=proposal_id,
                expected_session_revision=action.expected_session_revision,
                receipt=receipt,
            )
            return self._complete_turn(turn_id, turn.workflow_id, receipt.summary)
        if action.action == "delegate_choice":
            memory = self._conversations.get_creative_memory(turn.workflow_id)
            style_run = self._conversations.get_active_style_skill_run(turn.workflow_id)
            style = self._video_skills.load(style_run.skill_id, style_run.skill_version)
            choice_context = self._guidance_contexts.build_delegated_choice(
                proposal,
                session=session,
                style_summary=memory.approved_style_summary or style.instructions,
            )
            choice = self._gateway.choose_delegated_proposal_option(
                choice_context,
                turn_id=turn_id,
            )
            if choice.option_id not in {option.option_id for option in proposal.options}:
                raise V2PersistenceError(
                    "delegated_proposal_choice_invalid",
                    "The Director selected an option outside the current Proposal.",
                    stage="agent_conversation_service",
                )
            materialized = self._materialize_specialist_draft(
                turn,
                proposal,
                choice.option_id,
            )
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
                for reference in proposal.proposed_references
                if reference.required
            )
            materialized = replace(
                materialized,
                draft=materialized.draft.model_copy(
                    update={"reference_intents": accepted_references}
                ),
            )
            continuation = (
                _continuation_commit(turn, source_action_id=turn_id)
                if session.status == "active"
                else None
            )
            try:
                node = self._materialization.materialize(
                    proposal_id,
                    option_id=choice.option_id,
                    draft=materialized.draft,
                    expected_session_revision=action.expected_session_revision,
                    proposal_action="delegate_choice",
                    selection_actor="agent",
                    source_turn_id=turn_id,
                    continuation=continuation,
                )
            except V2PersistenceError as error:
                self._fail_draft_materialization(materialized, error)
                raise
            self._complete_draft_materialization(materialized, node)
            receipt = self._conversations.get_publication_receipt_for_action(turn_id)
            message = receipt.summary if receipt is not None else "The Draft is ready to edit."
            return self._complete_turn(turn_id, turn.workflow_id, message)
        raise V2PersistenceError(
            "proposal_action_invalid",
            "This Proposal action is not implemented yet.",
            stage="agent_conversation_service",
        )

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
        continuation = (
            _continuation_commit(turn, source_action_id=action_id)
            if action.action == "resume_guidance"
            else None
        )
        receipt = self._conversations.apply_guidance_session_action(
            action_id,
            source_turn_id=turn_id,
            continuation=continuation,
        )
        return self._complete_turn(turn_id, turn.workflow_id, receipt.summary)

    def _complete_turn(
        self,
        turn_id: str,
        workflow_id: str,
        assistant_message: str | None,
    ) -> ChatTurnV2:
        session = self._conversations.get_guidance_session_or_none(workflow_id)
        return self._conversations.complete_turn(
            turn_id,
            assistant_message=assistant_message,
            guided_actions=self._session_actions.project(
                session,
                creating_turn_id=turn_id,
            ),
        )

    def get_turn(self, turn_id: str) -> ChatTurnV2:
        return self._conversations.get_turn(turn_id)

    def recover_pending_turns(self) -> tuple[ChatTurnV2, ...]:
        return tuple(
            self.process_turn(turn_id)
            for turn_id in self._conversations.list_recoverable_turn_ids()
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
            display_name=specialist_display_name(proposal.specialist_name),
            event_details={
                "conversation_id": turn.conversation_id,
                "proposal_id": proposal.proposal_id,
                "option_id": option.option_id,
            },
        )
        try:
            materialize = getattr(self._gateway, "materialize_draft", None)
            if not callable(materialize):
                raise V2PersistenceError(
                    "specialist_materialization_unavailable",
                    "The owning Specialist cannot materialize this Proposal.",
                    stage="agent_conversation_service",
                )
            workflow = self._workflows.get_workflow(turn.workflow_id)
            draft = materialize(
                SpecialistContextV2(
                    context_kind="specialist_handoff",
                    specialist_name=proposal.specialist_name,
                    operation="materialize_draft",
                    workflow_id=turn.workflow_id,
                    workflow_revision=workflow.revision,
                    user_instruction=str(
                        turn.request.get("instruction") or "Apply the selected option."
                    ),
                    selected_option_summary=option.summary_prompt,
                    selected_option_id=option.option_id,
                    reference_allowlist=tuple(
                        reference.source_id for reference in proposal.proposed_references
                    ),
                ),
                turn_id=turn.turn_id,
            )
            SpecialistDraftValidationService().validate(proposal, draft)
        except V2PersistenceError as error:
            self._conversations.transition_expert_activity(
                activity.activity_id,
                status="failed",
                error_code=error.code,
                error_message=str(error),
            )
            raise
        except (TypeError, ValueError) as error:
            self._conversations.transition_expert_activity(
                activity.activity_id,
                status="failed",
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
        error: V2PersistenceError,
    ) -> None:
        self._conversations.transition_expert_activity(
            materialized.activity_id,
            status="failed",
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
        action: ProposalActionRequestV2,
    ) -> ConceptProposalCreateV2:
        assert action.instruction is not None
        workflow = self._workflows.get_workflow(proposal.workflow_id)
        session = self._conversations.get_guidance_session(proposal.workflow_id)
        empty_anchor_values = {
            "subject_product": (),
            "audience": "",
            "campaign_goal": "",
            "duration": "",
            "aspect_ratio": "",
            "approved_facts": (),
        }
        anchor_digest = hashlib.sha256(
            json.dumps(
                empty_anchor_values,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        topic = next(
            (item for item in session.topics if item.topic_id == proposal.topic_id),
            None,
        )
        revision_context = ProposalRevisionContextV2(
            source_proposal_id=proposal.proposal_id,
            source_proposal_revision=proposal.proposal_revision,
            prior_options=tuple(
                ProposalRevisionOptionV2(
                    option_id=option.option_id,
                    title=option.title,
                    summary=option.summary_prompt,
                )
                for option in proposal.options
            ),
            approved_anchors=CreativeAnchorSetV2(
                **empty_anchor_values,
                digest=anchor_digest,
            ),
            topic_objective=topic.title if topic is not None else "",
            user_instruction=action.instruction,
            mutable_dimensions=("other",),
        )
        specialist_context = SpecialistContextV2(
            context_kind="specialist_handoff",
            specialist_name=proposal.specialist_name,
            operation="revise_concepts",
            workflow_id=proposal.workflow_id,
            workflow_revision=workflow.revision,
            user_instruction=action.instruction,
            selected_option_summary="\n".join(option.description for option in proposal.options),
            current_topic_id=proposal.topic_id,
            candidate_count=len(proposal.options),
            proposal_revision=revision_context,
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
            display_name=specialist_display_name(proposal.specialist_name),
        )
        try:
            revised = ConceptProposalCreateV2.model_validate(
                revise(specialist_context, turn_id=turn.turn_id)
            )
        except PiAgentRuntimeError as error:
            self._conversations.transition_expert_activity(
                activity.activity_id,
                status="failed",
                error_code=error.code,
                error_message=error.message,
            )
            raise
        except (TypeError, ValueError) as error:
            self._conversations.transition_expert_activity(
                activity.activity_id,
                status="failed",
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
                error_code="specialist_revision_failed",
                error_message="Specialist revision is incompatible with the proposal.",
            )
            raise V2PersistenceError(
                "specialist_revision_failed",
                "Specialist revision is incompatible with the proposal.",
                stage="agent_conversation_service",
            )
        try:
            _validate_proposal_revision(
                revised,
                revision_context,
            )
        except V2PersistenceError as error:
            self._conversations.transition_expert_activity(
                activity.activity_id,
                status="failed",
                error_code=error.code,
                error_message=str(error),
            )
            raise
        self._conversations.transition_expert_activity(
            activity.activity_id,
            status="completed",
        )
        return revised


def _validate_proposal_revision(
    revised: ConceptProposalCreateV2,
    context: ProposalRevisionContextV2,
) -> None:
    if context.replace_whole_concept or not context.approved_anchors.has_protected_values:
        return
    if revised.preserved_anchor_digest != context.approved_anchors.digest:
        raise V2PersistenceError(
            "proposal_revision_anchor_drift",
            "Specialist revision did not preserve the approved anchor set.",
            stage="agent_conversation_service",
        )
    revised_text = "\n".join(
        f"{option.title}\n{option.summary_prompt}" for option in revised.options
    ).casefold()
    if any(
        subject.casefold() not in revised_text
        for subject in context.approved_anchors.subject_product
    ):
        raise V2PersistenceError(
            "proposal_revision_anchor_drift",
            "Specialist revision changed the protected subject or product.",
            stage="agent_conversation_service",
        )


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


def _approved_anchor_summaries(
    context: DirectorTurnContextV2,
) -> tuple[str, ...]:
    memory = context.creative_memory
    values = [
        f"Current request: {context.user_input}",
        f"Approved script: {context.script_summary}" if context.script_summary else "",
        *(f"Explicit input: {item}" for item in context.explicit_input_summaries),
    ]
    if memory is not None:
        values.extend(
            (
                f"Creative goal: {memory.creative_goal}" if memory.creative_goal else "",
                f"Target audience: {memory.target_audience}" if memory.target_audience else "",
                f"Delivery format: {memory.duration_format}" if memory.duration_format else "",
                (
                    f"Approved style: {memory.approved_style_summary}"
                    if memory.approved_style_summary
                    else ""
                ),
            )
        )
    return tuple(value[:4_096] for value in values if value)[:16]


def _approved_anchor_digest(context: DirectorTurnContextV2) -> str:
    payload = json.dumps(
        _approved_anchor_summaries(context),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
