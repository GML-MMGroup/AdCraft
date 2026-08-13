import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router as api_v1_router
from app.api.internal.router import router as internal_agent_router
from app.api.v2.persistence import v2_persistence_exception_handler
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
from app.services.agent_canvas_execution_state import AgentCanvasExecutionStateMachine

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
            _recover_agent_canvas_chat_turns(settings)
            _recover_agent_canvas_continuations(settings)
            _recover_agent_canvas_executions(settings)
            _recover_agent_canvas_editing_exports(settings)
            provider_poll_stop = asyncio.Event()
            provider_poll_task = asyncio.create_task(
                _poll_agent_canvas_provider_tasks(settings, provider_poll_stop)
            )
            continuation_poll_stop = asyncio.Event()
            continuation_poll_task = asyncio.create_task(
                _poll_agent_canvas_continuations(settings, continuation_poll_stop)
            )
            try:
                yield
            finally:
                provider_poll_stop.set()
                continuation_poll_stop.set()
                await provider_poll_task
                await continuation_poll_task
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
        runtime.post_ready_effects.run_once()
        state_machine = AgentCanvasExecutionStateMachine()
        for execution in runtime.runtime_repository.list_executions():
            state_machine.reconcile(
                runtime.runtime_repository,
                execution.execution_id,
                now=execution.updated_at,
                workflows=runtime.workflows,
            )
        for execution in runtime.runtime_repository.list_active_executions():
            runtime.scheduler.resume(execution.execution_id)
    finally:
        runtime.database.dispose()


async def _poll_agent_canvas_continuations(
    settings: Settings,
    stop: asyncio.Event,
) -> None:
    interval = max(1, settings.v2_provider_task_poll_interval_seconds)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            continue
        except asyncio.TimeoutError:
            pass
        try:
            await asyncio.to_thread(_recover_agent_canvas_continuations, settings)
        except Exception:  # noqa: BLE001 - later poll cycles must remain available.
            logger.exception("Agent Canvas continuation polling cycle failed.")


def _recover_agent_canvas_continuations(settings: Settings) -> None:
    runtime = create_agent_canvas_runtime(settings)
    try:
        runtime.continuation_worker.run_once()
        runtime.auto_run_dispatcher.run_once()
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
        except asyncio.TimeoutError:
            pass
        try:
            await asyncio.to_thread(_recover_agent_canvas_provider_tasks, settings)
        except Exception:  # noqa: BLE001 - later poll cycles must remain available.
            logger.exception("Agent Canvas provider polling cycle failed.")


def _recover_agent_canvas_provider_tasks(settings: Settings) -> None:
    runtime = create_agent_canvas_runtime(settings)
    try:
        runtime.provider_recovery.recover_due_tasks()
        runtime.post_ready_effects.run_once()
        for execution in runtime.runtime_repository.list_active_executions():
            runtime.scheduler.resume(execution.execution_id)
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


app = create_app()
