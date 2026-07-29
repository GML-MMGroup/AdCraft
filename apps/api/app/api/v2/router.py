from fastapi import APIRouter, Depends

from app.api.v2.persistence import require_v2_persistence
from app.api.v2.endpoints import (
    agent_canvas,
    asset_library,
    agent_conversations,
    health,
    input_assets,
    media_toolchain,
    provider_callbacks,
    production_acceptance,
    prompt_evals,
)


api_router = APIRouter(dependencies=[Depends(require_v2_persistence)])
api_router.include_router(health.router)
api_router.include_router(agent_canvas.router)
api_router.include_router(media_toolchain.router)
api_router.include_router(provider_callbacks.router)
api_router.include_router(input_assets.router)
api_router.include_router(asset_library.router)
api_router.include_router(agent_conversations.router)
api_router.include_router(prompt_evals.router)
api_router.include_router(prompt_evals.workflow_router)
api_router.include_router(production_acceptance.router)
