from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.schemas.workflow_v2 import V2MediaToolchainCapabilities
from app.services.v2_media_toolchain_capabilities import (
    V2MediaToolchainCapabilityService,
)


router = APIRouter(prefix="/system/media-toolchain", tags=["v2-system"])


def get_v2_media_toolchain_capability_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> V2MediaToolchainCapabilityService:
    return V2MediaToolchainCapabilityService(settings)


@router.get("/capabilities", response_model=V2MediaToolchainCapabilities)
def get_media_toolchain_capabilities(
    service: Annotated[
        V2MediaToolchainCapabilityService,
        Depends(get_v2_media_toolchain_capability_service),
    ],
) -> V2MediaToolchainCapabilities:
    return service.snapshot()
