from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_chat_workflow_stream_service
from app.schemas.chat_workflow_stream import (
    ChatWorkflowRunCreateRequest,
    ChatWorkflowRunCreateResponse,
)
from app.services.chat_workflow_stream import ChatWorkflowRunError, ChatWorkflowStreamService

router = APIRouter(prefix="/chat", tags=["chat-workflow-stream"])


@router.post("/workflow-runs", response_model=ChatWorkflowRunCreateResponse)
def create_chat_workflow_run(
    request: ChatWorkflowRunCreateRequest,
    service: Annotated[ChatWorkflowStreamService, Depends(get_chat_workflow_stream_service)],
) -> ChatWorkflowRunCreateResponse:
    return service.create_run(request)


@router.get("/workflow-runs/{run_id}/stream")
def stream_chat_workflow_run(
    run_id: str,
    service: Annotated[ChatWorkflowStreamService, Depends(get_chat_workflow_stream_service)],
) -> StreamingResponse:
    try:
        return StreamingResponse(
            service.stream_run(run_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except ChatWorkflowRunError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
