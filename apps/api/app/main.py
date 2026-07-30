import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router as api_v1_router
from app.api.internal.router import router as internal_agent_router
from app.api.v2.persistence import v2_persistence_exception_handler
from app.api.v2.etag import semantic_workflow_mutation_id, workflow_etag
from app.api.v2.router import api_router as api_v2_router
from app.api.v2.endpoints.agent_canvas import create_agent_canvas_runtime
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
from app.services.v2_workflow_authoring import create_workflow_authoring_runtime

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
        expose_headers=["ETag"],
    )

    @application.middleware("http")
    async def add_workflow_etag(request: Request, call_next):
        response = await call_next(request)
        workflow_id = semantic_workflow_mutation_id(request.method, request.url.path)
        if workflow_id is None or response.status_code >= 400:
            return response
        runtime = create_workflow_authoring_runtime(resolved_settings.media_data_dir)
        try:
            current = runtime.repository.load_current(workflow_id)
        except V2PersistenceError:
            return response
        finally:
            runtime.database.dispose()
        response.headers["ETag"] = workflow_etag(workflow_id, current.state_version)
        return response

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
    application.include_router(internal_agent_router)
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
        application.state.v2_asset_catalog_coordinator = coordinator
        coordinator.ensure_indexed()
        try:
            _recover_v2_interrupted_executions(settings)
            _recover_v2_active_provider_task_polling(settings)
            _recover_v2_final_composition_renders(settings)
            _recover_agent_canvas_chat_turns(settings)
            _recover_agent_canvas_executions(settings)
            _recover_agent_canvas_editing_exports(settings)
            provider_poll_stop = asyncio.Event()
            provider_poll_task = asyncio.create_task(
                _poll_agent_canvas_provider_tasks(settings, provider_poll_stop)
            )
            try:
                yield
            finally:
                provider_poll_stop.set()
                await provider_poll_task
        finally:
            coordinator.shutdown()

    return lifespan


def _recover_agent_canvas_chat_turns(settings: Settings) -> None:
    """Resume durable queued Agent Canvas turns after process restart."""

    runtime = create_agent_canvas_runtime(settings)
    try:
        runtime.commands.recover_applying_plans()
        runtime.conversations.recover_pending_turns()
    finally:
        runtime.database.dispose()


def _recover_agent_canvas_executions(settings: Settings) -> None:
    """Resume persisted non-terminal Agent Canvas scheduler memberships."""

    runtime = create_agent_canvas_runtime(settings)
    try:
        runtime.provider_recovery.recover_due_tasks()
        for execution in runtime.runtime_repository.list_active_executions():
            runtime.scheduler.resume(execution.execution_id)
    finally:
        runtime.database.dispose()


async def _poll_agent_canvas_provider_tasks(
    settings: Settings,
    stop: asyncio.Event,
) -> None:
    interval = max(1, settings.v2_provider_task_poll_interval_seconds)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            continue
        except TimeoutError:
            pass
        try:
            await asyncio.to_thread(_recover_agent_canvas_provider_tasks, settings)
        except Exception:  # noqa: BLE001 - later poll cycles must remain available.
            logger.exception("Agent Canvas provider polling cycle failed.")


def _recover_agent_canvas_provider_tasks(settings: Settings) -> None:
    runtime = create_agent_canvas_runtime(settings)
    try:
        runtime.provider_recovery.recover_due_tasks()
    finally:
        runtime.database.dispose()


def _recover_agent_canvas_editing_exports(settings: Settings) -> None:
    """Resume persisted non-terminal Agent Canvas Editing exports."""

    runtime = create_agent_canvas_runtime(settings)
    try:
        runtime.editing_exports.resume_active()
    finally:
        runtime.database.dispose()


def _create_asset_catalog_coordinator(settings: Settings) -> V2AssetCatalogCoordinator:
    """Create the local-catalog coordinator once for the application lifespan."""

    return V2AssetCatalogCoordinator(
        V2AssetCatalogService(
            data_dir=settings.media_data_dir,
            repository=V2AssetLibraryRepository(create_v2_database(settings.media_data_dir)),
            catalog_root=settings.v2_recommended_catalog_root,
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
