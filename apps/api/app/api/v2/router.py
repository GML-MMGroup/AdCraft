from fastapi import APIRouter, Depends

from app.api.v2.persistence import require_v2_persistence
from app.api.v2.endpoints import (
    agent_canvas,
    brand_mode,
    health,
    media_toolchain,
    model_calls,
    provider_callbacks,
)


api_router = APIRouter(dependencies=[Depends(require_v2_persistence)])
api_router.include_router(health.router)
api_router.include_router(agent_canvas.router)
api_router.include_router(brand_mode.router)
api_router.include_router(media_toolchain.router)
api_router.include_router(model_calls.router)
api_router.include_router(provider_callbacks.router)
