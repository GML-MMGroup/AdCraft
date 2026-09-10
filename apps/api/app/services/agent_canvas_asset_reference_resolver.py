"""Canonical immutable AssetVersion resolution for Agent Canvas references."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.v2_asset_library import AssetVersionMetadataV2
from app.services.v2_storage_adapter import StorageAdapter


@dataclass(frozen=True, slots=True)
class ResolvedAssetVersion:
    """One verified immutable version and its canonical local object."""

    metadata: AssetVersionMetadataV2
    path: Path


class AgentCanvasAssetReferenceResolver:
    """Resolve exact Asset/Version pairs without selecting a newer version."""

    def __init__(self, data_dir: Path, assets: V2AssetLibraryRepository) -> None:
        self._assets = assets
        self._storage = StorageAdapter(data_dir)

    def resolve_bound_asset(
        self,
        asset_id: str,
        version_id: str,
        *,
        media_type: str | None = None,
    ) -> ResolvedAssetVersion:
        version = self._assets.find_version(asset_id=asset_id, version_id=version_id)
        return self._validate_bound_asset(
            asset_id,
            version_id,
            version,
            media_type=media_type,
        )

    def resolve_bound_assets(
        self,
        pairs: tuple[tuple[str, str], ...],
    ) -> dict[tuple[str, str], ResolvedAssetVersion]:
        """Resolve exact pairs with one bounded metadata query."""

        unique_pairs = tuple(dict.fromkeys(pairs))
        versions = self._assets.find_versions_by_id(
            tuple(version_id for _, version_id in unique_pairs)
        )
        return {
            pair: self._validate_bound_asset(
                pair[0],
                pair[1],
                versions.get(pair[1]),
            )
            for pair in unique_pairs
        }

    def _validate_bound_asset(
        self,
        asset_id: str,
        version_id: str,
        version: AssetVersionMetadataV2 | None,
        *,
        media_type: str | None = None,
    ) -> ResolvedAssetVersion:
        if version is None or version.asset_id != asset_id or version.version_id != version_id:
            raise _reference_error("canvas_asset_reference_version_required")
        if version.status != "ready":
            raise _reference_error("canvas_asset_reference_version_required")
        if media_type is not None and version.media_type != media_type:
            raise _reference_error("canvas_asset_reference_media_type_invalid")
        try:
            path = self._storage.resolve_local_path(version.storage_key)
        except V2PersistenceError as error:
            raise _reference_error("canvas_asset_reference_version_required") from error
        if not path.is_file() or path.is_symlink():
            raise _reference_error("canvas_asset_reference_version_required")
        if path.stat().st_size != version.size_bytes or _sha256(path) != version.sha256:
            raise _reference_error("canvas_asset_reference_version_required")
        return ResolvedAssetVersion(metadata=version, path=path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reference_error(code: str) -> V2PersistenceError:
    messages = {
        "canvas_asset_reference_version_required": (
            "The bound AssetVersion is missing, unavailable, unreadable, or invalid."
        ),
        "canvas_asset_reference_media_type_invalid": (
            "The bound AssetVersion media type is incompatible with this reference."
        ),
    }
    return V2PersistenceError(
        code,
        messages.get(code, "The bound AssetVersion is invalid."),
        stage="agent_canvas_asset_reference_resolver",
    )
