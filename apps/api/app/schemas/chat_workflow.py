from pydantic import BaseModel

from app.schemas.ad_workflow import AdWorkflowResponse
from app.schemas.front_desk import FrontDeskChatResponse


class ChatWorkflowResponse(BaseModel):
    front_desk: FrontDeskChatResponse
    workflow: AdWorkflowResponse | None = None
