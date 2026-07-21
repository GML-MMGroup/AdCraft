from fastapi import APIRouter, Depends

from app.api.v2.persistence import require_v2_persistence
from app.api.v2.endpoints import (
    health,
    input_assets,
    media_toolchain,
    provider_callbacks,
    workflows,
)


api_router = APIRouter(dependencies=[Depends(require_v2_persistence)])
api_router.include_router(health.router)
api_router.include_router(media_toolchain.router)
api_router.include_router(provider_callbacks.router)
api_router.include_router(input_assets.router)
api_router.include_router(workflows.router)
