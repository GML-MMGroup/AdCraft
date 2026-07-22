from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router as api_v1_router
from app.api.v2.persistence import v2_persistence_exception_handler
from app.api.v2.router import api_router as api_v2_router
from app.core.config import Settings, get_settings
from app.persistence.errors import V2PersistenceError
from app.schemas.v2_persistence import PersistenceBootstrapFailure
from app.services.persistence_bootstrap import PersistenceBootstrapService
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.database import create_v2_database
from app.services.v2_asset_catalog import V2AssetCatalogService
from app.services.v2_asset_catalog_coordinator import V2AssetCatalogCoordinator
from app.services.v2_execution_recovery import V2ExecutionRecoveryService
from app.services.v2_final_composition_render_service import V2FinalCompositionRenderService
from app.services.workflow_v2 import WorkflowV2Service

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct the HTTP application without touching persistence or media data."""

    resolved_settings = settings or get_settings()
    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=_lifespan(resolved_settings),
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if settings is not None:
        application.dependency_overrides[get_settings] = lambda: resolved_settings
    application.mount(
        "/media",
        StaticFiles(directory=resolved_settings.media_data_dir, check_dir=False),
        name="media",
    )
    application.add_exception_handler(V2PersistenceError, v2_persistence_exception_handler)
    application.include_router(api_v1_router, prefix="/api/v1")
    application.include_router(api_v2_router, prefix="/api/v2")
    return application


def _lifespan(settings: Settings) -> Callable[[FastAPI], AsyncIterator[None]]:
    """Build a lifespan hook that gates V2 recovery on verified persistence."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            application.state.v2_persistence_state = PersistenceBootstrapService(
                settings
            ).bootstrap()
        except V2PersistenceError as error:
            application.state.v2_persistence_state = PersistenceBootstrapFailure(
                code=error.code,
                message=str(error),
                stage=error.stage,
            )
            logger.error(
                "V2 persistence bootstrap failed: code=%s stage=%s",
                error.code,
                error.stage,
            )
            yield
            return

        coordinator = _create_asset_catalog_coordinator(settings)
        if coordinator is not None:
            application.state.v2_asset_catalog_coordinator = coordinator
        try:
            _recover_v2_interrupted_executions(settings)
            _recover_v2_active_provider_task_polling(settings)
            _recover_v2_final_composition_renders(settings)
            yield
        finally:
            if coordinator is not None:
                coordinator.shutdown()

    return lifespan


def _create_asset_catalog_coordinator(settings: Settings) -> V2AssetCatalogCoordinator | None:
    """Create the optional catalog coordinator once for the application lifespan."""

    if settings.v2_recommended_catalog_manifest_path is None:
        return None
    return V2AssetCatalogCoordinator(
        V2AssetCatalogService(
            data_dir=settings.media_data_dir,
            repository=V2AssetLibraryRepository(create_v2_database(settings.media_data_dir)),
            manifest_path=settings.v2_recommended_catalog_manifest_path,
        )
    )


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
    for workflow_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
        active_pointer = workflow_dir / "executions" / "active.json"
        if active_pointer.is_file():
            recovery.recover_interrupted_execution(workflow_dir.name, trigger="startup")


def _recover_v2_active_provider_task_polling(settings: Settings) -> None:
    """Resume provider polling after interrupted executions have been recovered."""

    runs_dir = settings.media_data_dir / "v2" / "runs"
    if not runs_dir.is_dir():
        return
    workflow_service = WorkflowV2Service(settings)
    for workflow_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
        active_pointer = workflow_dir / "executions" / "active.json"
        if active_pointer.is_file():
            workflow_service.recover_active_provider_task_polling(workflow_dir.name)


app = create_app()
