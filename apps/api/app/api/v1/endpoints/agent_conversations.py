from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query

from app.api.dependencies import get_agent_conversation_service
from app.schemas.agent_conversations import (
    AgentConversation,
    AgentConversationActionResponse,
    AgentConversationCreateRequest,
    AgentConversationEventsResponse,
    AgentConversationListResponse,
    AgentConversationMessageRequest,
    AgentConversationRejectActionRequest,
)
from app.services.agent_conversations import (
    AgentConversationInputError,
    AgentConversationService,
)

router = APIRouter(prefix="/agent-conversations", tags=["agent-conversations"])


@router.post("", response_model=AgentConversation)
def create_agent_conversation(
    request: AgentConversationCreateRequest,
    service: Annotated[AgentConversationService, Depends(get_agent_conversation_service)],
) -> AgentConversation:
    return service.create(request)


@router.get("", response_model=AgentConversationListResponse)
def list_agent_conversations(
    service: Annotated[AgentConversationService, Depends(get_agent_conversation_service)],
    workflow_id: str | None = Query(default=None),
    focus_node_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> AgentConversationListResponse:
    return AgentConversationListResponse(
        items=service.list(
            workflow_id=workflow_id,
            focus_node_id=focus_node_id,
            status=status,
        )
    )


@router.get("/{conversation_id}", response_model=AgentConversation)
def get_agent_conversation(
    conversation_id: str,
    service: Annotated[AgentConversationService, Depends(get_agent_conversation_service)],
) -> AgentConversation:
    try:
        return service.get(conversation_id)
    except AgentConversationInputError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{conversation_id}/messages", response_model=AgentConversationEventsResponse)
def send_agent_conversation_message(
    conversation_id: str,
    request: AgentConversationMessageRequest,
    background_tasks: BackgroundTasks,
    service: Annotated[AgentConversationService, Depends(get_agent_conversation_service)],
) -> AgentConversationEventsResponse:
    try:
        return service.send_message(
            conversation_id,
            request,
            schedule_execution=lambda workflow_id, execution_id: background_tasks.add_task(
                service.run_chat_canvas_execution,
                workflow_id,
                execution_id,
            ),
        )
    except AgentConversationInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/{conversation_id}/actions/{action_id}/apply",
    response_model=AgentConversationActionResponse,
)
def apply_agent_conversation_action(
    conversation_id: str,
    action_id: str,
    service: Annotated[AgentConversationService, Depends(get_agent_conversation_service)],
) -> AgentConversationActionResponse:
    try:
        events, action = service.apply_action(conversation_id, action_id)
    except AgentConversationInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AgentConversationActionResponse(
        conversation_id=conversation_id,
        events=events,
        action=action,
    )


@router.post(
    "/{conversation_id}/actions/{action_id}/reject",
    response_model=AgentConversationActionResponse,
)
def reject_agent_conversation_action(
    conversation_id: str,
    action_id: str,
    service: Annotated[AgentConversationService, Depends(get_agent_conversation_service)],
    request: Annotated[
        AgentConversationRejectActionRequest,
        Body(default_factory=AgentConversationRejectActionRequest),
    ],
) -> AgentConversationActionResponse:
    try:
        events, action = service.reject_action(
            conversation_id,
            action_id,
            request,
        )
    except AgentConversationInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AgentConversationActionResponse(
        conversation_id=conversation_id,
        events=events,
        action=action,
    )
