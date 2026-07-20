from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router as api_v1_router
from app.api.v2.router import api_router as api_v2_router
from app.core.config import Settings, get_settings
from app.services.v2_execution_recovery import V2ExecutionRecoveryService
from app.services.v2_final_composition_render_service import V2FinalCompositionRenderService
from app.services.workflow_v2 import WorkflowV2Service


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name, version=settings.app_version)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    settings.media_data_dir.mkdir(parents=True, exist_ok=True)
    _recover_v2_interrupted_executions(settings)
    _recover_v2_final_composition_renders(settings)
    application.mount("/media", StaticFiles(directory=settings.media_data_dir), name="media")
    application.include_router(api_v1_router, prefix="/api/v1")
    application.include_router(api_v2_router, prefix="/api/v2")
    return application


def _recover_v2_final_composition_renders(settings: Settings) -> None:
    """Recover persisted V2 final renders before accepting requests after a restart."""

    runs_dir = settings.media_data_dir / "v2" / "runs"
    if not runs_dir.is_dir():
        return
    service = V2FinalCompositionRenderService(settings)
    for workflow_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
        composition_dir = workflow_dir / "composition"
        if composition_dir.is_dir():
            service.recover_interrupted_renders(workflow_dir.name)


def _recover_v2_interrupted_executions(settings: Settings) -> None:
    """Run the V2 command-owned recovery once for persisted active executions."""

    runs_dir = settings.media_data_dir / "v2" / "runs"
    if not runs_dir.is_dir():
        return
    recovery = V2ExecutionRecoveryService(
        settings.media_data_dir,
        stale_running_timeout_seconds=settings.v2_stale_running_timeout_seconds,
    )
    workflow_service = WorkflowV2Service(settings)
    for workflow_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
        active_pointer = workflow_dir / "executions" / "active.json"
        if active_pointer.is_file():
            recovery.recover_interrupted_execution(workflow_dir.name, trigger="startup")
            workflow_service.recover_active_provider_task_polling(workflow_dir.name)


app = create_app()
