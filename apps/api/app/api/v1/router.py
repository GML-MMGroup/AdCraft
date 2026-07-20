from fastapi import APIRouter

from app.api.v1.endpoints import (
    ad_workflows,
    agent_conversations,
    asset_library,
    asset_references,
    assets,
    canvas_runtime,
    chat_workflow_stream,
    front_desk,
    health,
    provider_certifications,
    provider_settings,
    video_editing,
    workflow_graph,
    workflow_nodes,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(assets.router)
api_router.include_router(asset_library.router)
api_router.include_router(asset_references.router)
api_router.include_router(canvas_runtime.router)
api_router.include_router(agent_conversations.router)
api_router.include_router(chat_workflow_stream.router)
api_router.include_router(front_desk.router)
api_router.include_router(ad_workflows.router)
api_router.include_router(provider_certifications.router)
api_router.include_router(provider_settings.router)
api_router.include_router(video_editing.router)
api_router.include_router(workflow_graph.router)
api_router.include_router(workflow_nodes.router)
