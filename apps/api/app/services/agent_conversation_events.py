from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.schemas.agent_conversations import (
    AgentConversation,
    AgentConversationEvent,
    SuggestedAction,
)
from app.services.agent_trace import utc_now
from app.services.chat_canvas_actions import (
    ChatCanvasActionError,
    ChatCanvasActionResult,
    ResolvedChatCanvasAction,
)

from app.services.agent_conversation_common import (
    SPECIALIST_BY_NODE,
    SPECIALIST_BY_NODE_TYPE,
)
from app.services.agent_conversation_trace import AgentConversationTraceMixin


class AgentConversationEventsMixin(AgentConversationTraceMixin):
    def _chat_canvas_events(
        self,
        conversation: AgentConversation,
        result: ChatCanvasActionResult,
    ) -> list[AgentConversationEvent]:
        events: list[AgentConversationEvent] = []
        resolved = result.resolved
        if result.prompt_update is not None and resolved is not None:
            events.append(self._node_prompt_updated_event(conversation, resolved, result))
        if result.item_prompt_update is not None and resolved is not None:
            events.append(self._item_prompt_updated_event(conversation, resolved, result))
        if result.execution is not None and resolved is not None:
            events.append(self._execution_started_event(conversation, resolved, result))
        if result.revision is not None and resolved is not None:
            events.append(self._revision_started_event(conversation, resolved, result))
        if result.error is not None:
            events.append(self._chat_canvas_error_event(conversation, result.error))
        return events

    def _node_prompt_updated_event(
        self,
        conversation: AgentConversation,
        resolved: ResolvedChatCanvasAction,
        result: ChatCanvasActionResult,
    ) -> AgentConversationEvent:
        prompt_update = result.prompt_update
        node = resolved.node
        speaker_agent = (
            SPECIALIST_BY_NODE.get(node.id)
            or SPECIALIST_BY_NODE_TYPE.get(node.node_type)
            or "creative_director"
        )
        stale_node_ids = prompt_update.stale_node_ids if prompt_update is not None else [node.id]
        workflow_version = prompt_update.workflow_version if prompt_update is not None else None
        return self._event(
            conversation=conversation,
            event_type="node_prompt_updated",
            speaker_agent=speaker_agent,
            target_node_id=node.id,
            text=f"已更新 {node.title} 的提示词，并标记相关节点为待刷新。",
            metadata={
                "refresh": ["workflow_graph", "node", "resolved_inputs"],
                "prompt_updated": True,
                "stale_node_ids": stale_node_ids,
                "workflow_version": workflow_version,
                "chat_canvas_action": resolved.action.action_type,
                "node_reference": {
                    "node_id": node.id,
                    "node_type": node.node_type,
                    "mention_text": resolved.mention_text,
                    "source": resolved.source,
                },
                "target": resolved.target.model_dump(mode="json")
                if resolved.target is not None
                else None,
            },
        )

    def _item_prompt_updated_event(
        self,
        conversation: AgentConversation,
        resolved: ResolvedChatCanvasAction,
        result: ChatCanvasActionResult,
    ) -> AgentConversationEvent:
        update = result.item_prompt_update
        node = resolved.node
        speaker_agent = (
            SPECIALIST_BY_NODE.get(node.id)
            or SPECIALIST_BY_NODE_TYPE.get(node.node_type)
            or "creative_director"
        )
        target = (
            resolved.target.model_dump(mode="json")
            if resolved.target is not None
            else update.target
            if update is not None and update.target
            else None
        )
        return self._event(
            conversation=conversation,
            event_type="item_prompt_updated",
            speaker_agent=speaker_agent,
            target_node_id=node.id,
            text=f"已更新 {node.title} 中目标 item 的提示词。",
            metadata={
                "refresh": ["workflow_graph", "node", "item", "resolved_inputs"],
                "target": target,
                "prompt_updated": True,
                "stale_item_ids": update.stale_item_ids if update is not None else [],
                "chat_canvas_action": resolved.action.action_type,
            },
        )

    def _execution_started_event(
        self,
        conversation: AgentConversation,
        resolved: ResolvedChatCanvasAction,
        result: ChatCanvasActionResult,
    ) -> AgentConversationEvent:
        execution = result.execution
        node = resolved.node
        speaker_agent = (
            SPECIALIST_BY_NODE.get(node.id)
            or SPECIALIST_BY_NODE_TYPE.get(node.node_type)
            or "creative_director"
        )
        metadata = {
            "execution_id": execution.execution_id if execution is not None else "",
            "run_mode": execution.run_mode if execution is not None else resolved.action.run_mode,
            "frontier_node_id": execution.frontier_node_id if execution is not None else None,
            "refresh": ["execution", "workflow_graph"],
            "chat_canvas_action": resolved.action.action_type,
            "target": resolved.target.model_dump(mode="json")
            if resolved.target is not None
            else None,
        }
        return self._event(
            conversation=conversation,
            event_type="execution_started",
            speaker_agent=speaker_agent,
            target_node_id=node.id,
            text=f"已开始执行 {node.title}。",
            metadata=metadata,
        )

    def _revision_started_event(
        self,
        conversation: AgentConversation,
        resolved: ResolvedChatCanvasAction,
        result: ChatCanvasActionResult,
    ) -> AgentConversationEvent:
        revision = result.revision
        node = resolved.node
        speaker_agent = (
            SPECIALIST_BY_NODE.get(node.id)
            or SPECIALIST_BY_NODE_TYPE.get(node.node_type)
            or "creative_director"
        )
        metadata = {
            "revision_id": revision.revision_id if revision is not None else "",
            "acceptance_policy": "manual_candidate",
            "revision_status": revision.status if revision is not None else "",
            "generation_status": revision.generation_status if revision is not None else None,
            "acceptance_status": revision.acceptance_status if revision is not None else "",
            "target": revision.target
            if revision is not None
            else resolved.target.model_dump(mode="json")
            if resolved.target is not None
            else None,
            "refresh": ["revision", "node", "item"],
            "chat_canvas_action": resolved.action.action_type,
        }
        return self._event(
            conversation=conversation,
            event_type="revision_started",
            speaker_agent=speaker_agent,
            target_node_id=node.id,
            text=f"已开始重新生成 {node.title} 中的目标 item。",
            metadata=metadata,
        )

    def _chat_canvas_error_event(
        self,
        conversation: AgentConversation,
        error: ChatCanvasActionError,
    ) -> AgentConversationEvent:
        event = self._error_event(
            conversation=conversation,
            error_code=error.error_code,
            message=error.message,
            target_agent=None,
            target_node_id=error.target_node_id,
            recoverable=True,
        )
        event.metadata.update(error.metadata_payload())
        return event

    def _append_events(
        self,
        conversation: AgentConversation,
        events: list[AgentConversationEvent],
        asset_references: list[Any],
        *,
        user_message: str | None = None,
    ) -> None:
        conversation.events.extend(events)
        conversation.updated_at = utc_now().isoformat()
        self._conversation_memory.update_from_events(
            conversation,
            events,
            user_message=user_message,
        )
        self._trace_events(conversation, events, asset_references)
        self._save(conversation)

    def _suggested_action_event(
        self, conversation: AgentConversation, action: SuggestedAction
    ) -> AgentConversationEvent:
        return self._event(
            conversation=conversation,
            event_type="suggested_action",
            speaker_agent=action.speaker_agent,
            target_node_id=action.target_node_id,
            text=action.summary,
            metadata={
                "action_id": action.action_id,
                "action_type": action.action_type,
                "action_status": action.status,
            },
        )

    def _event(
        self,
        *,
        conversation: AgentConversation,
        event_type: str,
        speaker_agent: str | None,
        target_agent: str | None = None,
        target_node_id: str | None = None,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> AgentConversationEvent:
        return AgentConversationEvent(
            event_id=f"evt_{uuid4().hex[:12]}",
            conversation_id=conversation.conversation_id,
            event_type=event_type,  # type: ignore[arg-type]
            speaker_agent=speaker_agent,  # type: ignore[arg-type]
            target_agent=target_agent,  # type: ignore[arg-type]
            workflow_id=conversation.workflow_id,
            target_node_id=target_node_id,
            text=text,
            created_at=utc_now().isoformat(),
            metadata={"transport": "http_batch", **(metadata or {})},
        )

    def _error_event(
        self,
        *,
        conversation: AgentConversation,
        error_code: str,
        message: str,
        target_agent: str | None,
        target_node_id: str | None,
        recoverable: bool,
    ) -> AgentConversationEvent:
        return self._event(
            conversation=conversation,
            event_type="error",
            speaker_agent="creative_director",
            target_agent=target_agent,
            target_node_id=target_node_id,
            text=message,
            metadata={
                "error_code": error_code,
                "recoverable": recoverable,
                "target_agent": target_agent,
                "target_node_id": target_node_id,
                "error": message,
            },
        )
