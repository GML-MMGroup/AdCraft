from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_front_desk_service
from app.schemas.front_desk import FrontDeskChatRequest, FrontDeskChatResponse
from app.services.front_desk import FrontDeskError, FrontDeskService

router = APIRouter(prefix="/front-desk", tags=["front-desk"])


@router.post("/chat", response_model=FrontDeskChatResponse)
def chat_with_front_desk(
    request: FrontDeskChatRequest,
    service: Annotated[FrontDeskService, Depends(get_front_desk_service)],
) -> FrontDeskChatResponse:
    try:
        return service.chat(request)
    except FrontDeskError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
