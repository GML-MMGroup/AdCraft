"""Bounded rendition prewarming for exact project-cover versions."""

from __future__ import annotations

from pathlib import Path

from app.persistence.errors import V2PersistenceError
from app.schemas.v2_asset_library import AssetVersionMetadataV2
from app.services.v2_asset_renditions import V2AssetRenditionService
from app.services.v2_storage_adapter import StorageAdapter


class ProjectCoverRenditionPrewarmer:
    """Resolve one exact version and delegate to the canonical rendition service."""

    def __init__(self, data_dir: Path, renditions: V2AssetRenditionService) -> None:
        self._storage = StorageAdapter(data_dir)
        self._renditions = renditions

    def ensure(self, version: AssetVersionMetadataV2) -> str:
        media_type = _media_type(version.mime_type)
        if media_type is None:
            raise V2PersistenceError(
                "project_cover_media_invalid",
                "Project cover media is unsupported.",
                stage="project_cover_rendition_prewarm",
            )
        self._renditions.ensure(
            self._storage.resolve_local_path(version.storage_key),
            asset_id=version.asset_id,
            version_id=version.version_id,
            media_type=media_type,
            kind="poster" if media_type == "video" else "preview",
            max_dimension=320,
        )
        return "ready"


def _media_type(mime_type: str) -> str | None:
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("video/"):
        return "video"
    return None
