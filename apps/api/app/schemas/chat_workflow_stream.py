from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.front_desk import FrontDeskChatRequest


class ChatWorkflowRunCreateRequest(FrontDeskChatRequest):
    """Request to create a chat-visible workflow planning run."""


class ChatWorkflowRunCreateResponse(BaseModel):
    run_id: str
    status: Literal["queued"] = "queued"


class ChatWorkflowStreamEvent(BaseModel):
    event: str
    data: dict[str, Any] = Field(default_factory=dict)
