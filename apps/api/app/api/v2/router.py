from fastapi import APIRouter

from app.api.v2.endpoints import (
    health,
    input_assets,
    media_toolchain,
    provider_callbacks,
    production_acceptance,
    prompt_evals,
    workflows,
)


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(media_toolchain.router)
api_router.include_router(provider_callbacks.router)
api_router.include_router(input_assets.router)
api_router.include_router(prompt_evals.router)
api_router.include_router(prompt_evals.workflow_router)
api_router.include_router(production_acceptance.router)
api_router.include_router(workflows.router)
