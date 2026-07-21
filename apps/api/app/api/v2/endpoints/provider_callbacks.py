from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from app.core.config import Settings, get_settings
from app.schemas.tianpuyue_pure_music import TianpuyueInstrumentalCallbackRequest
from app.services.tianpuyue_instrumental_callback import TianpuyueInstrumentalCallbackService


router = APIRouter(prefix="/provider-callbacks/tianpuyue", tags=["v2-provider-callbacks"])


def get_tianpuyue_instrumental_callback_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> TianpuyueInstrumentalCallbackService:
    return TianpuyueInstrumentalCallbackService(settings.media_data_dir)


@router.post(
    "/instrumental/{workflow_id}/{callback_id}",
    response_class=PlainTextResponse,
)
def accept_tianpuyue_instrumental_callback(
    workflow_id: str,
    callback_id: str,
    payload: TianpuyueInstrumentalCallbackRequest,
    service: Annotated[
        TianpuyueInstrumentalCallbackService,
        Depends(get_tianpuyue_instrumental_callback_service),
    ],
) -> PlainTextResponse:
    service.accept(workflow_id, callback_id, payload)
    return PlainTextResponse("success")
