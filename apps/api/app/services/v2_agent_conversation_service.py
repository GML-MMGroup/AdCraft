"""Durable public service for workflow-scoped V2 Agent conversations."""

from __future__ import annotations

from hashlib import sha256
from typing import Protocol
from uuid import uuid4

from app.core.config import Settings
from app.schemas.agent_operation_contexts import (
    ConversationSummaryAgentContext,
    InteractionMessageSummary,
    WorkflowConversationAgentContext,
)
from app.persistence.database import create_v2_database
from app.persistence.v2_agent_conversation_repository import (
    V2AgentConversationRepository,
    V2AgentConversationRepositoryError,
)
from app.schemas.v2_agent_conversations import (
    V2AgentActionCreate,
    V2AgentConversation,
    V2AgentConversationCreate,
    V2AgentConversationCreateRequest,
    V2AgentConversationDetail,
    V2AgentConversationMessageRequest,
    V2AgentConversationMessageResponse,
    V2AgentConversationPage,
    V2AgentMessageCreate,
)
from app.schemas.workflow_v2 import (
    WorkflowV2ChatActionRequest,
    WorkflowV2ChatActionResponse,
    WorkflowV2ChatActionTarget,
)
from app.services.v2_event_store import V2EventStore
from app.services.v2_workflow_authoring import create_workflow_authoring_runtime
from app.services.v2_workflow_conversation_agent import (
    V2WorkflowConversationAgent,
    V2WorkflowConversationAgentError,
)
from app.services.workflow_v2 import WorkflowV2Error, WorkflowV2Service


class V2ConversationActionDispatcher(Protocol):
    def dispatch(
        self,
        workflow_id: str,
        request: WorkflowV2ChatActionRequest,
    ) -> WorkflowV2ChatActionResponse: ...


class _WorkflowChatActionDispatcher:
    def __init__(self, settings: Settings) -> None:
        self._service = WorkflowV2Service(settings)

    def dispatch(
        self,
        workflow_id: str,
        request: WorkflowV2ChatActionRequest,
    ) -> WorkflowV2ChatActionResponse:
        return self._service.chat_action(workflow_id, request)


class V2AgentConversationServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class V2AgentConversationService:
    def __init__(
        self,
        settings: Settings,
        *,
        action_dispatcher: V2ConversationActionDispatcher | None = None,
        conversation_agent: V2WorkflowConversationAgent | None = None,
    ) -> None:
        self._database = create_v2_database(settings.media_data_dir)
        self._repository = V2AgentConversationRepository(self._database)
        self._read_model = create_workflow_authoring_runtime(settings.media_data_dir).read_model
        self._events = V2EventStore(settings.media_data_dir)
        self._dispatcher = action_dispatcher or _WorkflowChatActionDispatcher(settings)
        self._conversation_agent = conversation_agent or V2WorkflowConversationAgent(settings)

    def close(self) -> None:
        self._database.dispose()

    def create(
        self,
        workflow_id: str,
        request: V2AgentConversationCreateRequest,
    ) -> V2AgentConversation:
        self._require_workflow(workflow_id)
        conversation = self._repository.create_conversation(
            V2AgentConversationCreate(
                conversation_id=f"conv_{uuid4().hex[:16]}",
                workflow_id=workflow_id,
                title=request.title,
            )
        )
        self._events.append_event(
            workflow_id,
            "agent_conversation_created",
            payload={"conversation_id": conversation.conversation_id},
        )
        return conversation

    def list(
        self,
        workflow_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> V2AgentConversationPage:
        self._require_workflow(workflow_id)
        return self._repository.list_conversations(
            workflow_id,
            after=cursor,
            limit=limit,
        )

    def get(
        self,
        workflow_id: str,
        conversation_id: str,
        *,
        after_sequence: int | None = None,
        limit: int = 50,
    ) -> V2AgentConversationDetail:
        conversation = self._get_owned(workflow_id, conversation_id)
        return V2AgentConversationDetail(
            conversation=conversation,
            messages=self._repository.list_messages(
                conversation_id,
                after_sequence=after_sequence,
                limit=limit,
            ),
            actions=self._repository.list_actions(conversation_id),
        )

    def send_message(
        self,
        workflow_id: str,
        conversation_id: str,
        request: V2AgentConversationMessageRequest,
    ) -> V2AgentConversationMessageResponse:
        self._get_owned(workflow_id, conversation_id)
        action_request = V2AgentActionCreate(
            action_id=_stable_id("action", conversation_id, request.request_id),
            conversation_id=conversation_id,
            request_id=request.request_id,
            action_mode=(
                request.action_mode if request.target is not None else "workflow_conversation"
            ),
            target=request.target,
        )
        action, created = self._repository.create_or_load_action(action_request)
        if not created:
            return self._replay(workflow_id, conversation_id, action)

        user_message = self._repository.append_message(
            V2AgentMessageCreate(
                message_id=_stable_id("message-user", conversation_id, request.request_id),
                conversation_id=conversation_id,
                role="user",
                content=request.message,
                target=request.target,
            )
        )
        self._events.append_event(
            workflow_id,
            "agent_message_created",
            payload={
                "conversation_id": conversation_id,
                "message_id": user_message.message_id,
                "role": "user",
                "sequence_no": user_message.sequence_no,
            },
        )
        action = self._repository.transition_action(action.action_id, status="running")
        try:
            visible_reply = self._visible_reply(
                workflow_id,
                conversation_id,
                request,
            )
            assistant_message = self._repository.append_message(
                V2AgentMessageCreate(
                    message_id=_stable_id(
                        "message-assistant",
                        conversation_id,
                        request.request_id,
                    ),
                    conversation_id=conversation_id,
                    role="assistant",
                    content=visible_reply,
                    target=request.target,
                )
            )
            result = {
                "user_message_id": user_message.message_id,
                "assistant_message_id": assistant_message.message_id,
                "message": visible_reply,
            }
            action = self._repository.transition_action(
                action.action_id,
                status="completed",
                result=result,
            )
        except (
            WorkflowV2Error,
            V2WorkflowConversationAgentError,
            ValueError,
        ) as error:
            code = getattr(error, "code", "agent_conversation_action_failed")
            self._repository.transition_action(
                action.action_id,
                status="failed",
                error_code=code,
                error_message=_safe_error_message(error),
            )
            self._events.append_event(
                workflow_id,
                "agent_action_failed",
                payload={
                    "conversation_id": conversation_id,
                    "action_id": action.action_id,
                    "error_code": code,
                },
            )
            raise V2AgentConversationServiceError(code, _safe_error_message(error)) from error

        self._events.append_event(
            workflow_id,
            "agent_message_created",
            payload={
                "conversation_id": conversation_id,
                "message_id": assistant_message.message_id,
                "role": "assistant",
                "sequence_no": assistant_message.sequence_no,
            },
        )
        self._events.append_event(
            workflow_id,
            "agent_action_completed",
            payload={
                "conversation_id": conversation_id,
                "action_id": action.action_id,
            },
        )
        self._maybe_refresh_summary(workflow_id, conversation_id)
        return V2AgentConversationMessageResponse(
            conversation=self._get_owned(workflow_id, conversation_id),
            user_message=user_message,
            assistant_message=assistant_message,
            action=action,
        )

    def _visible_reply(
        self,
        workflow_id: str,
        conversation_id: str,
        request: V2AgentConversationMessageRequest,
    ) -> str:
        if request.target is None:
            summary, messages = self._conversation_context(conversation_id)
            workflow = self._read_model.assemble(workflow_id)
            return self._conversation_agent.reply(
                WorkflowConversationAgentContext(
                    context_kind="workflow_conversation",
                    user_input=request.message,
                    workflow_id=workflow_id,
                    conversation_id=conversation_id,
                    conversation_summary=summary,
                    recent_messages=tuple(messages),
                    workflow_summary=_workflow_summary(workflow),
                )
            ).message
        target = WorkflowV2ChatActionTarget.model_validate(request.target)
        response = self._dispatcher.dispatch(
            workflow_id,
            WorkflowV2ChatActionRequest(
                message=request.message,
                target=target,
                action_mode=request.action_mode,
                metadata={
                    "conversation_id": conversation_id,
                    "action_id": _stable_id(
                        "action",
                        conversation_id,
                        request.request_id,
                    ),
                },
            ),
        )
        return response.message

    def _maybe_refresh_summary(
        self,
        workflow_id: str,
        conversation_id: str,
    ) -> None:
        conversation = self._get_owned(workflow_id, conversation_id)
        if conversation.last_message_sequence == 0:
            return
        summary, messages = self._conversation_context(conversation_id)
        message_bytes = sum(len(message.content.encode("utf-8")) for message in messages)
        if conversation.last_message_sequence % 12 != 0 and message_bytes < 8_192:
            return
        try:
            result = self._conversation_agent.summarize(
                ConversationSummaryAgentContext(
                    context_kind="conversation_summary",
                    user_input="\n".join(
                        f"{message.role}: {message.content}" for message in messages
                    ),
                    workflow_id=workflow_id,
                    conversation_id=conversation_id,
                    previous_summary=summary,
                    recent_messages=tuple(messages),
                )
            )
        except V2WorkflowConversationAgentError:
            return
        self._repository.update_summary(conversation_id, result.summary)
        self._events.append_event(
            workflow_id,
            "agent_conversation_summary_updated",
            payload={"conversation_id": conversation_id},
        )

    def _conversation_context(
        self,
        conversation_id: str,
    ) -> tuple[str, list[InteractionMessageSummary]]:
        summary, raw_messages = self._repository.load_context(
            conversation_id,
            limit=12,
        )
        messages = [
            InteractionMessageSummary(
                sequence_no=int(message["sequence_no"]),
                role=message["role"],
                content=str(message["content"]),
            )
            for message in raw_messages
            if message.get("role") in {"user", "assistant", "system"}
        ]
        return summary, messages

    def _replay(
        self,
        workflow_id: str,
        conversation_id: str,
        action,
    ) -> V2AgentConversationMessageResponse:
        result = action.result or {}
        user_message_id = result.get("user_message_id")
        assistant_message_id = result.get("assistant_message_id")
        if (
            action.status != "completed"
            or not isinstance(user_message_id, str)
            or not isinstance(assistant_message_id, str)
        ):
            raise V2AgentConversationServiceError(
                "agent_conversation_request_in_progress",
                "The Agent conversation request is not complete.",
            )
        return V2AgentConversationMessageResponse(
            conversation=self._get_owned(workflow_id, conversation_id),
            user_message=self._repository.get_message(user_message_id),
            assistant_message=self._repository.get_message(assistant_message_id),
            action=action,
        )

    def _get_owned(
        self,
        workflow_id: str,
        conversation_id: str,
    ) -> V2AgentConversation:
        try:
            return self._repository.get_conversation(workflow_id, conversation_id)
        except V2AgentConversationRepositoryError as error:
            raise V2AgentConversationServiceError(error.code, error.message) from error

    def _require_workflow(self, workflow_id: str) -> None:
        try:
            self._read_model.assemble(workflow_id)
        except Exception as error:
            raise V2AgentConversationServiceError(
                "workflow_not_found",
                "Workflow was not found.",
            ) from error


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _safe_error_message(error: Exception) -> str:
    return (str(error).strip() or "Agent conversation action failed.")[:512]


def _workflow_summary(workflow) -> str:
    parts = [f"Workflow: {workflow.name}."]
    for node in workflow.nodes:
        active_items = [
            item.display_name for item in node.items if item.lifecycle_state == "active"
        ]
        if active_items:
            parts.append(f"{node.title}: {', '.join(active_items[:12])}.")
    return " ".join(parts)[:16_384]
