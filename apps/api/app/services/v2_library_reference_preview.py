"""Resolve version-pinned preview renditions for asset-library references."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from collections.abc import Mapping

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import ResolvedMediaInputSnapshotV2
from app.schemas.v2_asset_library import AssetVersionMetadataV2
from app.services.v2_asset_renditions import V2AssetRenditionService
from app.services.v2_data_boundary import V2DataBoundaryError, validate_v2_data_path
from app.services.v2_storage_adapter import StorageAdapter


class LibraryReferencePreviewError(ValueError):
    """A safe, bounded reason for rejecting a library preview rendition."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class ResolvedLibraryPreview:
    """Verified preview bytes and metadata for one exact source version."""

    path: Path
    mime_type: str
    sha256: str
    byte_count: int
    width: int
    height: int
    data_url: str
    data_url_byte_count: int
    kind: Literal["preview"] = "preview"


class V2LibraryReferencePreviewResolver:
    """Resolve previews only for explicitly marked library provenance."""

    _LIBRARY_SCOPES = frozenset({"my", "project", "recommended"})

    def __init__(
        self,
        data_dir: Path,
        *,
        rendition_service: V2AssetRenditionService | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._renditions = rendition_service or V2AssetRenditionService(data_dir)

    def resolve(
        self,
        snapshot: ResolvedMediaInputSnapshotV2,
        version: AssetVersionMetadataV2,
        *,
        max_data_url_bytes: int,
    ) -> ResolvedLibraryPreview | None:
        provenance = snapshot.binding_metadata
        return self.resolve_version(
            asset_id=snapshot.asset_id,
            version_id=snapshot.asset_version_id,
            media_type=snapshot.media_type,
            provenance=provenance,
            version=version,
            max_data_url_bytes=max_data_url_bytes,
        )

    def resolve_version(
        self,
        *,
        asset_id: str,
        version_id: str | None,
        media_type: str,
        provenance: Mapping[str, object],
        version: AssetVersionMetadataV2,
        max_data_url_bytes: int,
    ) -> ResolvedLibraryPreview | None:
        marker = provenance.get("reference_source")
        scope = provenance.get("source_scope")
        if marker != "asset_library":
            if scope in self._LIBRARY_SCOPES:
                raise LibraryReferencePreviewError("library_provenance_ambiguous")
            return None
        if scope not in self._LIBRARY_SCOPES:
            raise LibraryReferencePreviewError("library_provenance_invalid")
        if asset_id != version.asset_id or version_id != version.version_id:
            raise LibraryReferencePreviewError("asset_version_mismatch")
        if media_type != "image" or version.mime_type.split("/", 1)[0] != "image":
            raise LibraryReferencePreviewError("preview_media_type_invalid")

        if scope == "recommended":
            path, expected = self._catalog_preview(version)
        else:
            source_path = self._resolve_source(version.storage_key, "preview_source_invalid")
            if not _is_regular_file(source_path):
                raise LibraryReferencePreviewError("preview_source_missing")
            rendition = self._renditions.ensure(
                source_path,
                asset_id=version.asset_id,
                version_id=version.version_id,
                media_type="image",
                kind="preview",
            )
            if rendition.kind != "preview" or rendition.media_type != "image/jpeg":
                raise LibraryReferencePreviewError("preview_rendition_invalid")
            try:
                path = validate_v2_data_path(
                    self._data_dir,
                    rendition.path,
                    operation="v2-library-reference-preview",
                )
            except V2DataBoundaryError as error:
                raise LibraryReferencePreviewError("preview_storage_key_invalid") from error
            if path == source_path:
                raise LibraryReferencePreviewError("preview_rendition_invalid")
            expected = {}

        return self._verify(
            path,
            asset_id=version.asset_id,
            version_id=version.version_id,
            expected=expected,
            max_data_url_bytes=max_data_url_bytes,
        )

    def _catalog_preview(
        self, version: AssetVersionMetadataV2
    ) -> tuple[Path, dict[str, object]]:
        metadata = version.metadata if isinstance(version.metadata, dict) else {}
        storage_key = metadata.get("preview_storage_key")
        if not isinstance(storage_key, str) or not storage_key.strip():
            raise LibraryReferencePreviewError("preview_rendition_missing")
        path = self._resolve_source(storage_key, "preview_storage_key_invalid")
        return path, {
            "sha256": metadata.get("preview_sha256"),
            "size_bytes": metadata.get("preview_size_bytes"),
            "mime_type": metadata.get("preview_mime_type"),
            "width": metadata.get("preview_width"),
            "height": metadata.get("preview_height"),
        }

    def _resolve_source(self, storage_key: str, missing_reason: str) -> Path:
        try:
            path = StorageAdapter(self._data_dir).resolve_local_path(storage_key)
        except (OSError, ValueError, V2PersistenceError):
            raise LibraryReferencePreviewError(missing_reason) from None
        return path

    def _verify(
        self,
        path: Path,
        *,
        asset_id: str,
        version_id: str,
        expected: dict[str, object],
        max_data_url_bytes: int,
    ) -> ResolvedLibraryPreview:
        del asset_id, version_id
        if not _is_regular_file(path):
            raise LibraryReferencePreviewError("preview_rendition_missing")
        try:
            content = path.read_bytes()
        except OSError as error:
            raise LibraryReferencePreviewError("preview_rendition_unreadable") from error
        sha256 = hashlib.sha256(content).hexdigest()
        byte_count = len(content)
        mime_type, width, height = _image_metadata(content)
        expected_sha256 = expected.get("sha256")
        expected_size = expected.get("size_bytes")
        expected_mime = expected.get("mime_type")
        expected_width = expected.get("width")
        expected_height = expected.get("height")
        if (
            not isinstance(expected_sha256, str)
            or sha256 != expected_sha256
            or not isinstance(expected_size, int)
            or byte_count != expected_size
            or not isinstance(expected_mime, str)
            or mime_type != expected_mime
            or not isinstance(expected_width, int)
            or width != expected_width
            or not isinstance(expected_height, int)
            or height != expected_height
        ) and expected:
            raise LibraryReferencePreviewError("preview_rendition_invalid")
        data_url = f"data:{mime_type};base64,{base64.b64encode(content).decode('ascii')}"
        data_url_byte_count = len(data_url.encode("utf-8"))
        if data_url_byte_count > max_data_url_bytes:
            raise LibraryReferencePreviewError("preview_rendition_over_budget")
        return ResolvedLibraryPreview(
            path=path,
            mime_type=mime_type,
            sha256=sha256,
            byte_count=byte_count,
            width=width,
            height=height,
            data_url=data_url,
            data_url_byte_count=data_url_byte_count,
        )


def _is_regular_file(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink()
    except OSError:
        return False


def _image_metadata(content: bytes) -> tuple[str, int, int]:
    if content[:8] == b"\x89PNG\r\n\x1a\n" and len(content) >= 24 and content[12:16] == b"IHDR":
        return "image/png", int.from_bytes(content[16:20], "big"), int.from_bytes(
            content[20:24], "big"
        )
    if content[:2] == b"\xff\xd8":
        position = 2
        while position + 9 <= len(content):
            if content[position] != 0xFF:
                break
            marker = content[position + 1]
            position += 2
            if marker in {0xD8, 0xD9}:
                continue
            length = int.from_bytes(content[position : position + 2], "big")
            if length < 2 or position + length > len(content):
                break
            if marker in {0xC0, 0xC1, 0xC2}:
                return (
                    "image/jpeg",
                    int.from_bytes(content[position + 5 : position + 7], "big"),
                    int.from_bytes(content[position + 3 : position + 5], "big"),
                )
            position += length
    raise LibraryReferencePreviewError("preview_rendition_invalid")
