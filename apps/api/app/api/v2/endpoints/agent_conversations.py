"""Public workflow-scoped V2 Agent conversation endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import Settings, get_settings
from app.schemas.v2_agent_conversations import (
    V2AgentConversation,
    V2AgentConversationCreateRequest,
    V2AgentConversationDetail,
    V2AgentConversationMessageRequest,
    V2AgentConversationMessageResponse,
    V2AgentConversationPage,
)
from app.services.v2_agent_conversation_service import (
    V2AgentConversationService,
    V2AgentConversationServiceError,
)


router = APIRouter(
    prefix="/workflows/{workflow_id}/conversations",
    tags=["v2-agent-conversations"],
)


def get_v2_agent_conversation_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[V2AgentConversationService]:
    service = V2AgentConversationService(settings)
    try:
        yield service
    finally:
        service.close()


@router.post("", response_model=V2AgentConversation, status_code=status.HTTP_201_CREATED)
def create_conversation(
    workflow_id: str,
    request: V2AgentConversationCreateRequest,
    service: Annotated[
        V2AgentConversationService,
        Depends(get_v2_agent_conversation_service),
    ],
) -> V2AgentConversation:
    try:
        return service.create(workflow_id, request)
    except V2AgentConversationServiceError as error:
        raise _http_error(error) from error


@router.get("", response_model=V2AgentConversationPage)
def list_conversations(
    workflow_id: str,
    service: Annotated[
        V2AgentConversationService,
        Depends(get_v2_agent_conversation_service),
    ],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> V2AgentConversationPage:
    try:
        return service.list(workflow_id, cursor=cursor, limit=limit)
    except V2AgentConversationServiceError as error:
        raise _http_error(error) from error


@router.get("/{conversation_id}", response_model=V2AgentConversationDetail)
def get_conversation(
    workflow_id: str,
    conversation_id: str,
    service: Annotated[
        V2AgentConversationService,
        Depends(get_v2_agent_conversation_service),
    ],
    after_sequence: int | None = Query(default=None, ge=0),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> V2AgentConversationDetail:
    try:
        return service.get(
            workflow_id,
            conversation_id,
            after_sequence=after_sequence,
            limit=limit,
        )
    except V2AgentConversationServiceError as error:
        raise _http_error(error) from error


@router.post(
    "/{conversation_id}/messages",
    response_model=V2AgentConversationMessageResponse,
)
def send_message(
    workflow_id: str,
    conversation_id: str,
    request: V2AgentConversationMessageRequest,
    service: Annotated[
        V2AgentConversationService,
        Depends(get_v2_agent_conversation_service),
    ],
) -> V2AgentConversationMessageResponse:
    try:
        return service.send_message(workflow_id, conversation_id, request)
    except V2AgentConversationServiceError as error:
        raise _http_error(error) from error


def _http_error(error: V2AgentConversationServiceError) -> HTTPException:
    status_code = {
        "agent_conversation_not_found": 404,
        "workflow_not_found": 404,
        "agent_conversation_request_in_progress": 409,
        "agent_action_idempotency_conflict": 409,
        "agent_target_clarification_required": 422,
        "agent_target_not_supported": 422,
        "agent_target_not_found": 404,
    }.get(error.code, 503)
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": error.message},
    )
