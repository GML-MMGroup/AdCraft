from __future__ import annotations


from app.schemas.agent_conversations import (
    AgentConversation,
    AgentConversationEvent,
    AgentConversationMessageRequest,
)
from app.schemas.specialist_agents import (
    SpecialistAgentOutcome,
    SpecialistInvocationRequest,
)
from app.services.chat_canvas_actions import (
    ResolvedChatCanvasAction,
)

from app.services.agent_conversation_common import (
    AgentConversationInputError,
    _dict_payload,
    _specialist_action_name,
    _target_asset_summary,
    _target_current_prompt,
    _target_item_context,
)


class AgentConversationSpecialistFlowMixin:
    def _specialist_invocation_request(
        self,
        *,
        conversation: AgentConversation,
        request: AgentConversationMessageRequest,
        resolution: ResolvedChatCanvasAction,
        specialist: str,
    ) -> SpecialistInvocationRequest:
        target = resolution.target
        if target is None:
            raise AgentConversationInputError("Specialist routing requires a resolved target.")
        item_context = _target_item_context(target)
        asset_summary = _target_asset_summary(target)
        node_context = resolution.node.input_context
        return SpecialistInvocationRequest(
            workflow_id=resolution.workflow_id,
            conversation_id=conversation.conversation_id,
            specialist=specialist,  # type: ignore[arg-type]
            action=_specialist_action_name(resolution),
            target=target,
            user_instruction=request.message,
            current_prompt=_target_current_prompt(resolution),
            director_context_summary=_dict_payload(node_context.get("director_context_summary")),
            script_context_summary=_dict_payload(node_context.get("script_context_summary")),
            target_item_context=item_context,
            target_asset_summary=asset_summary,
            reference_asset_summary=self._asset_reference_payloads(request.asset_references),
            memory_summary=self._conversation_memory.memory_summary_for_request(
                conversation,
                user_message=request.message,
                target=target,
            ),
            constraints={
                "require_real_specialist": bool(
                    request.context.get("require_real_specialist")
                    or request.context.get("specialist_require_real")
                ),
                "source": "agent_conversation",
            },
        )

    def _specialist_result_event(
        self,
        *,
        conversation: AgentConversation,
        resolution: ResolvedChatCanvasAction,
        outcome: SpecialistAgentOutcome,
        applied: bool,
    ) -> AgentConversationEvent:
        result = outcome.result
        return self._event(
            conversation=conversation,
            event_type="specialist_result",
            speaker_agent=result.specialist,
            target_node_id=resolution.node.id,
            text=f"{result.specialist.replace('_', ' ').title()} prepared a structured result.",
            metadata={
                "specialist": result.specialist,
                "result_type": result.result_type,
                "applied": applied,
                "quality_notes_count": len(result.quality_notes),
                "quality_notes": result.quality_notes,
                "reference_requirements": result.reference_requirements,
                "warnings": result.warnings,
                "target": result.target.model_dump(mode="json"),
                "model_id": outcome.model_id,
                "used_fallback": outcome.used_fallback,
                "chat_canvas_action": resolution.action.action_type,
            },
        )

    def _specialist_message(
        self,
        *,
        target_agent: str,
        target_node_id: str | None,
        message: str,
    ) -> str:
        display = target_agent.replace("_", " ").title()
        node_text = f" for `{target_node_id}`" if target_node_id else ""
        return f"{display} reviewed the request{node_text} and prepared a suggested action."

    def _handoff_text(self, target_agent: str) -> str:
        display = target_agent.replace("_", " ").title()
        return f"I will ask the {display} to review this direction."

    def _handoff_reason(self, target_agent: str, message: str) -> str:
        return f"The user request was routed to {target_agent}: {message[:160]}"
