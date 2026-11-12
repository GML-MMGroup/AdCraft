"""Request-scoped media reads independent of Agent execution initialization."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.database import create_v2_database
from app.persistence.event_repository import EventRepository
from app.persistence.project_repository import ProjectRepository
from app.services.agent_canvas_assets import AgentCanvasAssetService
from app.services.v2_asset_renditions import V2AssetRenditionService


def get_agent_canvas_asset_reads(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[AgentCanvasAssetService]:
    """Reuse canonical asset validation without constructing the Agent runtime."""
    database = create_v2_database(settings.media_data_dir)
    try:
        yield AgentCanvasAssetService(
            settings.media_data_dir,
            V2AssetLibraryRepository(database),
            AgentCanvasWorkflowRepository(
                database, ProjectRepository(database), EventRepository(database)
            ),
            rendition_service=V2AssetRenditionService(
                settings.media_data_dir, ffmpeg_path=settings.ffmpeg_path
            ),
        )
    finally:
        database.dispose()
