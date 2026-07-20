from __future__ import annotations

from typing import Any, Callable
from uuid import uuid4

from app.schemas.agent_conversations import (
    AgentConversation,
    AgentConversationEvent,
    AgentConversationEventsResponse,
    AgentConversationMessageRequest,
    SuggestedAction,
)
from app.schemas.director_context import DirectorContext
from app.schemas.director_orchestrator import DirectorDecision
from app.services.agent_trace import utc_now
from app.services.chat_canvas_actions import (
    ChatCanvasActionError,
    ChatCanvasActionResult,
    ResolvedChatCanvasAction,
)
from app.services.director_orchestrator import (
    DirectorOrchestrationPlan,
)
from app.services.specialist_agents import (
    SpecialistAgentError,
    specialist_for_node_type,
)
from app.services.workflow_graph import save_graph

from app.services.agent_conversation_common import (
    AgentConversationInputError,
    _director_node_briefs_from_message,
    _node_is_user_targetable,
    _node_prompt_is_user_owned,
    _resolution_needs_specialist,
    _specialist_action_overrides,
    _specialist_result_was_applied,
    _system_suggestion_for_node,
)


class AgentConversationDirectorFlowMixin:
    def _director_orchestrator_response(
        self,
        conversation: AgentConversation,
        request: AgentConversationMessageRequest,
        *,
        schedule_execution: Callable[[str, str], None] | None = None,
    ) -> AgentConversationEventsResponse | None:
        plan = self._director_orchestrator.plan(
            workflow_id=conversation.workflow_id,
            message=request.message,
            target_references=request.target_references,
            node_references=request.node_references,
            context=request.context,
            focus_node_id=conversation.focus_node_id,
        )
        if plan is None:
            return None
        if plan.route == "clarification":
            event = self._clarification_requested_event(conversation, plan)
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
        if plan.route == "director_context":
            try:
                update = self._apply_director_context_update(
                    conversation=conversation,
                    request=request,
                    decision=plan.decision,
                )
            except Exception as exc:  # noqa: BLE001 - persisted as conversation error.
                event = self._error_event(
                    conversation=conversation,
                    error_code="director_context_update_failed",
                    message=str(exc),
                    target_agent=None,
                    target_node_id=None,
                    recoverable=True,
                )
                self._attach_director_decision(event, plan.decision)
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
            event = self._director_context_updated_event(
                conversation=conversation,
                decision=plan.decision,
                director_context=update["director_context"],
                affected_node_ids=update["affected_node_ids"],
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
        resolution = self._chat_canvas_actions.resolve_and_classify(
            workflow_id=conversation.workflow_id or "",
            message=request.message,
            target_references=plan.target_references,
            node_references=plan.node_references,
            context=plan.context,
            focus_node_id=None,
        )
        if resolution is None:
            return None
        if isinstance(resolution, ChatCanvasActionError):
            result = ChatCanvasActionResult(error=resolution)
            new_events = self._chat_canvas_events(conversation, result)
        else:
            specialist_events, result = self._execute_director_chat_canvas_action(
                conversation=conversation,
                request=request,
                resolution=resolution,
                schedule_execution=schedule_execution,
            )
            new_events = [*specialist_events, *self._chat_canvas_events(conversation, result)]
        if not new_events:
            return None
        for event in new_events:
            self._attach_director_decision(event, plan.decision)
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

    def _execute_director_chat_canvas_action(
        self,
        *,
        conversation: AgentConversation,
        request: AgentConversationMessageRequest,
        resolution: ResolvedChatCanvasAction,
        schedule_execution: Callable[[str, str], None] | None,
    ) -> tuple[list[AgentConversationEvent], ChatCanvasActionResult]:
        if not _resolution_needs_specialist(resolution):
            return [], self._chat_canvas_actions.execute(
                resolution,
                message=request.message,
                schedule_execution=schedule_execution,
            )
        specialist = specialist_for_node_type(resolution.node.node_type)
        if specialist is None:
            error = ChatCanvasActionError(
                error_code="specialist_not_supported",
                message=(
                    f"No specialist agent is available for node_type {resolution.node.node_type}."
                ),
                target_node_id=resolution.node.id,
                target=resolution.target,
            )
            return [], ChatCanvasActionResult(resolved=resolution, error=error)
        handoff = self._event(
            conversation=conversation,
            event_type="agent_handoff",
            speaker_agent="creative_director",
            target_agent=specialist,
            target_node_id=resolution.node.id,
            text=self._handoff_text(specialist),
            metadata={
                "reason": self._handoff_reason(specialist, request.message),
                "target": resolution.target.model_dump(mode="json")
                if resolution.target is not None
                else None,
                "chat_canvas_action": resolution.action.action_type,
            },
        )
        specialist_request = self._specialist_invocation_request(
            conversation=conversation,
            request=request,
            resolution=resolution,
            specialist=specialist,
        )
        try:
            outcome = self._specialist_agents.invoke(specialist_request)
        except SpecialistAgentError as exc:
            error = ChatCanvasActionError(
                error_code=exc.code,
                message=str(exc),
                target_node_id=resolution.node.id,
                target=resolution.target,
                metadata={"target_agent": specialist},
            )
            return [handoff], ChatCanvasActionResult(resolved=resolution, error=error)

        prompt_override, revision_instruction_override = _specialist_action_overrides(
            outcome.result
        )
        result = self._chat_canvas_actions.execute(
            resolution,
            message=request.message,
            schedule_execution=schedule_execution,
            prompt_override=prompt_override,
            revision_instruction_override=revision_instruction_override,
        )
        specialist_event = self._specialist_result_event(
            conversation=conversation,
            resolution=resolution,
            outcome=outcome,
            applied=_specialist_result_was_applied(result),
        )
        return [handoff, specialist_event], result

    def _clarification_requested_event(
        self,
        conversation: AgentConversation,
        plan: DirectorOrchestrationPlan,
    ) -> AgentConversationEvent:
        decision = plan.decision
        target = decision.target if isinstance(decision.target, dict) else {}
        return self._event(
            conversation=conversation,
            event_type="clarification_requested",
            speaker_agent="creative_director",
            text=plan.clarification_text or "请明确你想修改哪个目标。",
            metadata={
                "reason": target.get("reason", "target_ambiguous"),
                "candidate_targets": target.get("candidate_targets", []),
                "director_decision": self._director_decision_payload(decision),
            },
        )

    def _apply_director_context_update(
        self,
        *,
        conversation: AgentConversation,
        request: AgentConversationMessageRequest,
        decision: DirectorDecision,
    ) -> dict[str, Any]:
        workflow_id = conversation.workflow_id
        if not workflow_id:
            raise AgentConversationInputError("Director context update requires workflow_id.")
        now = utc_now().isoformat()
        action = SuggestedAction(
            action_id=f"act_{uuid4().hex[:12]}",
            conversation_id=conversation.conversation_id,
            action_type="update_director_context",
            status="pending",
            speaker_agent="creative_director",
            workflow_id=workflow_id,
            target_node_id=None,
            title="Update director context",
            summary="Update global creative direction.",
            payload={
                "creative_direction": {"user_update": request.message},
                "node_briefs": _director_node_briefs_from_message(request.message),
                "source": {
                    "conversation_id": conversation.conversation_id,
                    "global_update_message": request.message,
                    "director_decision": self._director_decision_payload(decision),
                },
            },
            created_at=now,
            updated_at=now,
        )
        result = self._update_director_context(action)
        context = DirectorContext.model_validate(result["director_context"])
        affected_node_ids = self._refresh_graph_from_director_context(
            workflow_id=workflow_id,
            director_context=context,
        )
        return {
            "director_context": context,
            "affected_node_ids": affected_node_ids,
        }

    def _refresh_graph_from_director_context(
        self,
        *,
        workflow_id: str,
        director_context: DirectorContext,
    ) -> list[str]:
        graph = self._graph_service.get_graph(workflow_id)
        affected_node_ids: list[str] = []
        summary = {
            "version": director_context.version,
            "creative_direction": director_context.creative_direction,
            "art_direction": director_context.art_direction,
            "strategy": director_context.strategy,
        }
        node_briefs = director_context.node_briefs.model_dump(mode="json")
        for node in graph.nodes:
            if not _node_is_user_targetable(node):
                continue
            suggestion = _system_suggestion_for_node(node, node_briefs, director_context)
            node.input_context = {
                **node.input_context,
                "director_context_summary": summary,
                "system_suggested_prompt": suggestion,
            }
            node.metadata = dict(node.metadata or {})
            node.metadata["director_context_version"] = director_context.version
            node.metadata["system_suggested_prompt"] = suggestion
            user_owned = _node_prompt_is_user_owned(node.metadata)
            if user_owned:
                node.metadata["has_new_system_suggestion"] = True
            else:
                node.prompt = suggestion
                node.override_prompt = suggestion
                node.input_context["user_prompt"] = suggestion
                node.metadata["prompt_source"] = "system"
                node.metadata["manual_prompt_dirty"] = False
                node.metadata["has_new_system_suggestion"] = False
            if not node.locked:
                node.status = "stale"
                node.stale = True
                node.stale_reason = "director context updated"
            node.version += 1
            affected_node_ids.append(node.id)
        if affected_node_ids:
            graph.version += 1
            save_graph(self._settings.media_data_dir, graph)
        return affected_node_ids

    def _director_context_updated_event(
        self,
        *,
        conversation: AgentConversation,
        decision: DirectorDecision,
        director_context: DirectorContext,
        affected_node_ids: list[str],
    ) -> AgentConversationEvent:
        return self._event(
            conversation=conversation,
            event_type="director_context_updated",
            speaker_agent="creative_director",
            text="已更新整体创意方向。",
            metadata={
                "director_context_version": director_context.version,
                "refresh": [
                    "director_context",
                    "workflow_graph",
                    "node",
                    "resolved_inputs",
                ],
                "affected_node_ids": affected_node_ids,
                "director_decision": self._director_decision_payload(decision),
            },
        )

    def _attach_director_decision(
        self,
        event: AgentConversationEvent,
        decision: DirectorDecision,
    ) -> None:
        event.metadata["director_decision"] = self._director_decision_payload(decision)

    def _director_decision_payload(self, decision: DirectorDecision) -> dict[str, Any]:
        return decision.model_dump(mode="json")
