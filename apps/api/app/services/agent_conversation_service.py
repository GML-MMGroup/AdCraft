from __future__ import annotations

from typing import Any, Callable

from app.core.config import Settings
from app.schemas.agent_conversations import (
    AgentConversation,
    AgentConversationEvent,
    AgentConversationEventsResponse,
    AgentConversationMessageRequest,
    SuggestedAction,
)
from app.services.chat_canvas_actions import (
    ChatCanvasActionProtocolService,
)
from app.services.conversation_memory import (
    ConversationMemoryRepair,
    ConversationMemoryService,
    compact_target_reference,
    has_explicit_target,
    message_has_memory_reference,
    message_is_memory_focus_only,
    targets_conflict,
)
from app.services.director_orchestrator import (
    DirectorOrchestratorService,
)
from app.services.front_desk import FrontDeskService
from app.services.specialist_agents import (
    SpecialistAgentService,
)
from app.services.workflow_graph import WorkflowGraphService
from app.services.workflow_nodes import WorkflowNodeExecutionService
from app.services.workflow_plan import AdWorkflowPlanService


from app.services.agent_conversation_actions import AgentConversationActionsMixin
from app.services.agent_conversation_direct_prompt_flow import (
    AgentConversationDirectPromptFlowMixin,
)
from app.services.agent_conversation_director_flow import AgentConversationDirectorFlowMixin
from app.services.agent_conversation_events import AgentConversationEventsMixin
from app.services.agent_conversation_specialist_flow import AgentConversationSpecialistFlowMixin
from app.services.agent_conversation_store import AgentConversationStoreMixin
from app.services.agent_conversation_targets import AgentConversationTargetsMixin


class AgentConversationService(
    AgentConversationStoreMixin,
    AgentConversationEventsMixin,
    AgentConversationDirectorFlowMixin,
    AgentConversationSpecialistFlowMixin,
    AgentConversationTargetsMixin,
    AgentConversationDirectPromptFlowMixin,
    AgentConversationActionsMixin,
):
    def __init__(
        self,
        settings: Settings,
        *,
        front_desk_service: FrontDeskService | None = None,
        workflow_node_service: WorkflowNodeExecutionService | None = None,
        workflow_plan_service: AdWorkflowPlanService | None = None,
        workflow_graph_service: WorkflowGraphService | None = None,
        chat_canvas_action_service: ChatCanvasActionProtocolService | None = None,
        director_orchestrator_service: DirectorOrchestratorService | None = None,
        specialist_agent_service: SpecialistAgentService | None = None,
    ) -> None:
        self._settings = settings
        self._front_desk = front_desk_service or FrontDeskService(settings=settings)
        self._node_service = workflow_node_service or WorkflowNodeExecutionService(
            settings=settings
        )
        self._plan_service = workflow_plan_service or AdWorkflowPlanService(settings=settings)
        self._graph_service = workflow_graph_service or WorkflowGraphService(
            data_dir=settings.media_data_dir
        )
        self._chat_canvas_actions = chat_canvas_action_service or ChatCanvasActionProtocolService(
            settings=settings,
            workflow_graph_service=self._graph_service,
        )
        self._director_orchestrator = director_orchestrator_service or DirectorOrchestratorService(
            settings=settings,
            workflow_graph_service=self._graph_service,
            chat_canvas_action_service=self._chat_canvas_actions,
        )
        self._specialist_agents = specialist_agent_service or SpecialistAgentService(settings)
        self._conversation_memory = ConversationMemoryService(
            settings=settings,
            workflow_graph_service=self._graph_service,
        )

    def send_message(
        self,
        conversation_id: str,
        request: AgentConversationMessageRequest,
        *,
        schedule_execution: Callable[[str, str], None] | None = None,
    ) -> AgentConversationEventsResponse:
        conversation = self._load(conversation_id)
        self._conversation_memory.ensure_memory(conversation)
        self._conversation_memory.reconcile_active_work(conversation)
        memory_repair = self._conversation_memory.repair_focus_target(conversation)
        if memory_repair is not None:
            self._trace_memory_warning(conversation, memory_repair)
        memory_response = self._conversation_memory_response(
            conversation,
            request,
            memory_repair=memory_repair,
        )
        if memory_response is not None:
            return memory_response
        request = self._request_with_memory_focus(
            conversation,
            request,
            memory_repair=memory_repair,
        )
        request = self._request_with_memory_summary(conversation, request)
        director_response = self._director_orchestrator_response(
            conversation,
            request,
            schedule_execution=schedule_execution,
        )
        if director_response is not None:
            return director_response
        direct_update_response = self._direct_node_prompt_update_response(
            conversation,
            request,
            schedule_execution=schedule_execution,
        )
        if direct_update_response is not None:
            return direct_update_response
        front_desk = self._front_desk_response(request)
        target_agent = self._target_agent(conversation, request, front_desk)
        target_node_id = self._target_node_id(
            conversation,
            request,
            target_agent,
            front_desk,
        )
        new_events: list[AgentConversationEvent] = [
            self._event(
                conversation=conversation,
                event_type="agent_message",
                speaker_agent="creative_director",
                target_agent=target_agent if target_agent != "creative_director" else None,
                target_node_id=target_node_id,
                text=front_desk.reply,
                metadata={
                    "conversation_mode": front_desk.conversation_mode,
                    "workflow_action": front_desk.workflow_action,
                    "suggested_agent": target_agent,
                },
            )
        ]

        action: SuggestedAction | None = None
        if target_agent and target_agent != "creative_director":
            new_events.append(
                self._event(
                    conversation=conversation,
                    event_type="agent_handoff",
                    speaker_agent="creative_director",
                    target_agent=target_agent,
                    target_node_id=target_node_id,
                    text=self._handoff_text(target_agent),
                    metadata={
                        "reason": self._handoff_reason(target_agent, request.message),
                    },
                )
            )
            try:
                specialist_text = self._specialist_message(
                    target_agent=target_agent,
                    target_node_id=target_node_id,
                    message=request.message,
                )
            except Exception as exc:  # noqa: BLE001 - failure is persisted as an event.
                error_event = self._error_event(
                    conversation=conversation,
                    error_code="agent_failed",
                    message=str(exc),
                    target_agent=target_agent,
                    target_node_id=target_node_id,
                    recoverable=True,
                )
                new_events.append(error_event)
                self._append_events(
                    conversation,
                    new_events,
                    request.asset_references,
                    user_message=request.message,
                )
                return AgentConversationEventsResponse(
                    conversation_id=conversation.conversation_id,
                    events=new_events,
                    suggested_actions=[],
                )
            new_events.append(
                self._event(
                    conversation=conversation,
                    event_type="agent_message",
                    speaker_agent=target_agent,
                    target_node_id=target_node_id,
                    text=specialist_text,
                    metadata={
                        "agent_role": target_agent,
                        "asset_references": self._asset_reference_payloads(
                            request.asset_references
                        ),
                    },
                )
            )

        action = self._suggested_action(
            conversation=conversation,
            request=request,
            front_desk=front_desk,
            speaker_agent=target_agent or "creative_director",
            target_node_id=target_node_id,
        )
        if action is not None:
            conversation.suggested_actions.append(action)
            new_events.append(self._suggested_action_event(conversation, action))

        self._append_events(
            conversation,
            new_events,
            request.asset_references,
            user_message=request.message,
        )
        return AgentConversationEventsResponse(
            conversation_id=conversation.conversation_id,
            events=new_events,
            suggested_actions=[action] if action is not None else [],
        )

    def _conversation_memory_response(
        self,
        conversation: AgentConversation,
        request: AgentConversationMessageRequest,
        *,
        memory_repair: ConversationMemoryRepair | None,
    ) -> AgentConversationEventsResponse | None:
        selected = self._conversation_memory.selected_reference(request.context)
        if (
            bool(request.context.get("emit_memory_event"))
            and selected is not None
            and message_is_memory_focus_only(request.message)
        ):
            focus_target = compact_target_reference(selected)
            event = self._event(
                conversation=conversation,
                event_type="conversation_memory_updated",
                speaker_agent="creative_director",
                text="已更新当前对话记忆目标。",
                metadata={
                    "debug_only": True,
                    "focus_target": focus_target,
                    "target": focus_target,
                    "refresh": [],
                },
            )
            self._append_events(
                conversation,
                [event],
                request.asset_references,
                user_message=request.message,
            )
            return AgentConversationEventsResponse(
                conversation_id=conversation.conversation_id,
                events=[event],
                suggested_actions=[],
            )

        if not self._should_apply_memory_focus(request):
            return None
        selected_reference = self._conversation_memory.selected_reference(request.context)
        if memory_repair is not None and selected_reference is None:
            return self._memory_clarification_response(
                conversation,
                request,
                reason="memory_focus_target_not_found",
                text="刚才记住的目标已经不可用，请重新选择或 @ 一个具体目标。",
                candidate_targets=[],
            )
        focus_reference = self._conversation_memory.focus_reference(conversation)
        if focus_reference is None or selected_reference is None:
            return None
        if targets_conflict(focus_reference, selected_reference):
            return self._memory_clarification_response(
                conversation,
                request,
                reason="memory_focus_conflict",
                text="你当前选中的目标和刚才记住的目标不一致，请确认要修改哪一个。",
                candidate_targets=[
                    focus_reference.model_dump(mode="json"),
                    selected_reference.model_dump(mode="json"),
                ],
            )
        return None

    def _request_with_memory_focus(
        self,
        conversation: AgentConversation,
        request: AgentConversationMessageRequest,
        *,
        memory_repair: ConversationMemoryRepair | None,
    ) -> AgentConversationMessageRequest:
        if not self._should_apply_memory_focus(request):
            return request
        if memory_repair is not None:
            return request
        if self._conversation_memory.selected_reference(request.context) is not None:
            return request
        focus_reference = self._conversation_memory.focus_reference(conversation)
        if focus_reference is None:
            return request
        return self._conversation_memory.with_memory_target(request, focus_reference)

    def _request_with_memory_summary(
        self,
        conversation: AgentConversation,
        request: AgentConversationMessageRequest,
    ) -> AgentConversationMessageRequest:
        context = {
            **request.context,
            "memory_summary": self._conversation_memory.memory_summary_for_request(
                conversation,
                user_message=request.message,
            ),
        }
        return request.model_copy(update={"context": context})

    def _should_apply_memory_focus(self, request: AgentConversationMessageRequest) -> bool:
        return message_has_memory_reference(request.message) and not has_explicit_target(request)

    def _memory_clarification_response(
        self,
        conversation: AgentConversation,
        request: AgentConversationMessageRequest,
        *,
        reason: str,
        text: str,
        candidate_targets: list[dict[str, Any]],
    ) -> AgentConversationEventsResponse:
        event = self._event(
            conversation=conversation,
            event_type="clarification_requested",
            speaker_agent="creative_director",
            text=text,
            metadata={
                "reason": reason,
                "candidate_targets": candidate_targets,
            },
        )
        self._append_events(
            conversation,
            [event],
            request.asset_references,
            user_message=request.message,
        )
        return AgentConversationEventsResponse(
            conversation_id=conversation.conversation_id,
            events=[event],
            suggested_actions=[],
        )
