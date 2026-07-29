"""Director-owned Agent Canvas conversation and proposal orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol
from uuid import uuid4

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    CanvasNodeCreateRequestV2,
    CanvasNodeV2,
    CanvasPositionV2,
)
from app.schemas.agent_canvas_conversation import (
    ChatTimelineListResponseV2,
    ChatTurnAcceptedV2,
    ChatTurnV2,
    ConceptOptionRecordV2,
    ConceptProposalCreateV2,
    ProposalActionRequestV2,
)
from app.schemas.agent_operation_contexts import (
    DirectorTurnContextV2,
    SpecialistContextV2,
)
from app.schemas.agent_runtime import (
    AgentActionEnvelopeV2,
    AgentCanvasOperationV2,
    AgentRunPolicy,
    AgentRunRequest,
    AgentRunCompletedPayload,
    ConceptProposalDraftV2,
)
from app.services.pi_agent_runtime_client import (
    PiAgentRuntimeClient,
    PiAgentRuntimeError,
)
from app.services.agent_canvas_nodes import AgentCanvasNodeService
from app.services.agent_canvas_context import AgentLocalContextAssembler
from app.services.agent_canvas_video_skills import VideoSkillRegistry


@dataclass(frozen=True, slots=True)
class DirectorGatewayResult:
    assistant_message: str
    proposal: ConceptProposalCreateV2 | None = None
    operations: tuple[AgentCanvasOperationV2, ...] = ()


class DirectorGateway(Protocol):
    def run_turn(self, context: DirectorTurnContextV2) -> DirectorGatewayResult: ...


class DeterministicDirectorGateway:
    """Test/offline gateway that never performs semantic keyword routing."""

    def run_turn(self, context: DirectorTurnContextV2) -> DirectorGatewayResult:
        return DirectorGatewayResult(
            assistant_message=(f"Your request is recorded for this canvas: {context.user_input}")
        )


class PiDirectorGateway:
    """Boundary for a private Pi runtime-backed Director implementation."""

    def __init__(
        self,
        client: PiAgentRuntimeClient,
        *,
        timeout_seconds: float,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds

    def run_turn(self, context: DirectorTurnContextV2) -> DirectorGatewayResult:
        envelope = AgentActionEnvelopeV2.model_validate(
            self._run(
                agent_name="director",
                operation="conversation_turn",
                context=context,
                contract=AgentActionEnvelopeV2,
                max_handoffs=1,
            )
        )
        if envelope.specialist_handoff is None:
            return DirectorGatewayResult(
                assistant_message=envelope.assistant_message,
                operations=envelope.operations,
            )
        specialist = envelope.specialist_handoff
        specialist_context = SpecialistContextV2(
            context_kind="specialist_handoff",
            specialist_name=specialist,
            operation="propose_concepts",
            workflow_id=context.workflow_id,
            workflow_revision=context.workflow_revision,
            user_instruction=context.user_input,
            script_summary=context.script_summary,
            video_skill_excerpt=context.video_skill_excerpt,
            explicit_input_summaries=context.explicit_input_summaries,
        )
        proposal = ConceptProposalDraftV2.model_validate(
            self._run(
                agent_name=specialist,
                operation="propose_concepts",
                context=specialist_context,
                contract=ConceptProposalDraftV2,
                max_handoffs=0,
            )
        )
        return DirectorGatewayResult(
            assistant_message=envelope.assistant_message,
            proposal=ConceptProposalCreateV2(
                proposal_kind=proposal.proposal_kind,
                specialist_name=proposal.specialist_name,
                options=tuple(
                    ConceptOptionRecordV2(
                        option_id=option.option_id,
                        title=option.title,
                        description=option.description,
                    )
                    for option in proposal.options
                ),
            ),
        )

    def _run(
        self,
        *,
        agent_name: str,
        operation: str,
        context: DirectorTurnContextV2 | SpecialistContextV2,
        contract,
        max_handoffs: int,
    ) -> dict[str, object]:
        run_id = f"arun_{uuid4().hex}"
        request = AgentRunRequest(
            run_id=run_id,
            request_id=f"request_{uuid4().hex}",
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
        outcome = self._client.run(request)
        if outcome.terminal_event.event_type != "run_completed":
            payload = outcome.terminal_event.payload
            raise PiAgentRuntimeError(
                str(payload.get("code") or "agent_runtime_unavailable"),
                str(payload.get("message") or "Agent turn failed."),
                retryable=bool(payload.get("retryable")),
            )
        completed = AgentRunCompletedPayload.model_validate(outcome.terminal_event.payload)
        return completed.value


class AgentOperationValidationService:
    """Validate revision-scoped Agent operations before authoring mutation."""

    def validate(
        self,
        envelope: AgentActionEnvelopeV2,
        *,
        workflow_revision: int,
    ) -> AgentActionEnvelopeV2:
        if any(
            operation.expected_workflow_revision != workflow_revision
            for operation in envelope.operations
        ):
            raise V2PersistenceError(
                "agent_operation_revision_conflict",
                "Agent operation targets a stale workflow revision.",
                stage="agent_operation_validation",
            )
        return envelope


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


class DraftMaterializationService:
    """Materialize one selected text option as one complete editable Draft."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        conversations: AgentCanvasConversationRepository,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations

    def materialize(
        self,
        proposal_id: str,
        *,
        option_id: str,
        next_action: str,
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
        workflow = self._workflows.get_workflow(proposal.workflow_id)
        node_type = _node_type_for_proposal(proposal.proposal_kind)
        now = datetime.now(timezone.utc)
        node = CanvasNodeV2(
            node_id=f"node_{uuid4().hex}",
            workflow_id=proposal.workflow_id,
            node_type=node_type,
            semantic_role=_semantic_role_for_proposal(proposal.proposal_kind),
            title=option.title,
            status="ready" if node_type == "script" else "draft",
            summary_prompt=option.description,
            generation_prompt=option.description if node_type != "script" else None,
            structured_content=_structured_content_for_proposal(
                proposal.proposal_kind,
                option.description,
            ),
            parameters={"requested_run": next_action == "generate_now"},
            video_skill_run_id=None,
            position=CanvasPositionV2(
                x=float((position or {}).get("x", 0)),
                y=float((position or {}).get("y", 0)),
            ),
            revision=1,
            created_at=now,
            updated_at=now,
        )
        self._conversations.select_and_materialize(
            proposal_id,
            option_id=option_id,
            node=node,
            expected_workflow_revision=workflow.revision,
            selection_actor=selection_actor,
            source_turn_id=source_turn_id,
        )
        return node


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
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._nodes = nodes
        self._gateway = gateway
        self._provider_runner = provider_runner
        self._video_skills = video_skills or VideoSkillRegistry()
        self._context_assembler = context_assembler
        self._materialization = DraftMaterializationService(workflows, conversations)

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
            default_skill = self._video_skills.load("platform-default", "1")
            video_skill_run_id = self._conversations.create_skill_run(
                workflow_id,
                skill_id=default_skill.manifest.skill_id,
                skill_version=default_skill.manifest.version,
                recipe_topics=tuple(
                    str(topic["topic_id"]) for topic in default_skill.recipe["planning_topics"]
                ),
                idempotency_key=f"{workflow_id}:platform-default:1",
            ).skill_run_id
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
            return self._process_proposal_action(turn_id, turn)
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
                status="started",
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
                self._materialization.materialize(
                    persisted.proposal_id,
                    option_id=persisted.options[0].option_id,
                    next_action="continue_planning",
                    position=None,
                    selection_actor="agent",
                    source_turn_id=turn_id,
                )
            message = f"Review {len(persisted.options)} {persisted.proposal_kind} option(s)."
        else:
            context = self._director_context(turn)
            result = self._gateway.run_turn(context)
            if result.proposal is not None:
                return self._process_message_turn(turn_id, turn, result.proposal)
            if result.operations:
                self._apply_direct_operations(turn, result.operations)
            message = result.assistant_message
        return self._conversations.complete_turn(turn_id, assistant_message=message)

    def _apply_direct_operations(
        self,
        turn: ChatTurnV2,
        operations: tuple[AgentCanvasOperationV2, ...],
    ) -> None:
        if len(operations) != 1:
            raise V2PersistenceError(
                "agent_operation_batch_unsupported",
                "Direct authoring requires one atomic operation.",
                stage="agent_conversation_service",
            )
        operation = operations[0]
        workflow = self._workflows.get_workflow(turn.workflow_id)
        AgentOperationValidationService().validate(
            AgentActionEnvelopeV2(
                assistant_message="Validated direct operation.",
                operations=operations,
            ),
            workflow_revision=workflow.revision,
        )
        if operation.operation_type not in {"create_node", "materialize_draft"}:
            raise V2PersistenceError(
                "agent_operation_not_allowed",
                "Direct operation is not allowed for this turn.",
                stage="agent_conversation_service",
            )
        try:
            request = CanvasNodeCreateRequestV2.model_validate(operation.payload)
        except ValueError as error:
            raise V2PersistenceError(
                "agent_operation_invalid",
                "Direct node operation payload is invalid.",
                stage="agent_conversation_service",
            ) from error
        self._nodes.create(
            turn.workflow_id,
            request,
            expected_revision=workflow.revision,
        )

    def _process_proposal_action(self, turn_id: str, turn: ChatTurnV2) -> ChatTurnV2:
        proposal_id = str(turn.request["proposal_id"])
        action = ProposalActionRequestV2.model_validate(turn.request["action"])
        proposal = self._conversations.get_proposal(proposal_id)
        if action.action == "select":
            assert action.option_id is not None
            assert action.next_action is not None
            self._materialization.materialize(
                proposal_id,
                option_id=action.option_id,
                next_action=action.next_action,
                position=action.position,
                source_turn_id=turn_id,
            )
            message = "The selected concept is now an editable Draft."
        elif action.action == "revise":
            assert action.instruction is not None
            self._conversations.mark_proposal(proposal_id, status="revised")
            revised = ConceptProposalCreateV2(
                proposal_kind=proposal.proposal_kind,
                specialist_name=proposal.specialist_name,
                options=tuple(
                    ConceptOptionRecordV2(
                        option_id=f"option_{uuid4().hex}",
                        title=option.title,
                        description=f"{option.description}\nRevision: {action.instruction}",
                    )
                    for option in proposal.options
                ),
            )
            self._conversations.create_proposal(turn_id, revised)
            message = "The concept options were revised."
        else:
            self._conversations.mark_proposal(proposal_id, status="skipped")
            message = "The concept was skipped."
        return self._conversations.complete_turn(turn_id, assistant_message=message)

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
        )
        default_skill = self._video_skills.load("platform-default", "1")
        return self._context_assembler.assemble_director_turn(
            turn.workflow_id,
            conversation_id=turn.conversation_id,
            user_input=str(turn.request.get("text") or ""),
            mentioned_node_ids=tuple(turn.request.get("mentioned_node_ids") or ()),
            mentioned_image_asset_ids=tuple(turn.request.get("mentioned_image_asset_ids") or ()),
            recent_messages=recent,
            video_skill_excerpt=default_skill.instructions,
        ).model_copy(update={"workflow_revision": workflow.revision})


def _node_type_for_proposal(proposal_kind: str) -> str:
    if proposal_kind == "script":
        return "script"
    if proposal_kind == "video":
        return "video"
    if proposal_kind == "bgm":
        return "audio"
    return "image"


def _semantic_role_for_proposal(proposal_kind: str) -> str:
    return {
        "script": "advertising_script",
        "product": "product_main",
        "prop": "prop_main",
        "character": "character_main",
        "scene": "scene_design_board",
        "storyboard": "storyboard_grid",
        "video": "storyboard_video_segment",
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
