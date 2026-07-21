from __future__ import annotations

from typing import Callable

from app.schemas.agent_conversations import (
    AgentConversation,
    AgentConversationEventsResponse,
    AgentConversationMessageRequest,
)
from app.services.chat_canvas_actions import (
    ChatCanvasActionError,
    ChatCanvasActionResult,
)


class AgentConversationDirectPromptFlowMixin:
    def _direct_node_prompt_update_response(
        self,
        conversation: AgentConversation,
        request: AgentConversationMessageRequest,
        *,
        schedule_execution: Callable[[str, str], None] | None = None,
    ) -> AgentConversationEventsResponse | None:
        if not self._has_node_prompt_target_hint(conversation, request):
            return None
        if not conversation.workflow_id:
            return None
        resolution = self._chat_canvas_actions.resolve_and_classify(
            workflow_id=conversation.workflow_id,
            message=request.message,
            target_references=request.target_references,
            node_references=request.node_references,
            context=request.context,
            focus_node_id=conversation.focus_node_id,
        )
        if resolution is None:
            return None
        if isinstance(resolution, ChatCanvasActionError):
            result = ChatCanvasActionResult(error=resolution)
        else:
            result = self._chat_canvas_actions.execute(
                resolution,
                message=request.message,
                schedule_execution=schedule_execution,
            )
        new_events = self._chat_canvas_events(conversation, result)
        if not new_events:
            return None
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

    def run_chat_canvas_execution(self, workflow_id: str, execution_id: str) -> None:
        self._chat_canvas_actions.run_execution(workflow_id, execution_id)
