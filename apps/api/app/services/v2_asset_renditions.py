"""On-demand, version-pinned media renditions for browser previews."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.persistence.errors import V2PersistenceError
from app.services.v2_data_boundary import validate_v2_data_path


@dataclass(frozen=True)
class AssetRendition:
    path: Path
    media_type: str
    kind: str


class V2AssetRenditionService:
    """Create deterministic preview files without mutating AssetVersion content."""

    def __init__(self, data_dir: Path, *, ffmpeg_path: str = "ffmpeg") -> None:
        self._data_dir = data_dir
        self._ffmpeg_path = ffmpeg_path

    def ensure(
        self,
        source_path: Path,
        *,
        asset_id: str,
        version_id: str,
        media_type: str,
        kind: str,
    ) -> AssetRendition:
        if kind not in {"preview", "poster"}:
            raise V2PersistenceError(
                "asset_rendition_kind_invalid",
                "Asset rendition kind is invalid.",
                stage="v2_asset_rendition_service",
            )
        if media_type not in {"image", "video"}:
            raise V2PersistenceError(
                "asset_rendition_media_unsupported",
                "Asset rendition media type is unsupported.",
                stage="v2_asset_rendition_service",
            )
        if kind == "poster" and media_type != "video":
            raise V2PersistenceError(
                "asset_rendition_media_unsupported",
                "Poster renditions require video media.",
                stage="v2_asset_rendition_service",
            )
        extension = "jpg"
        target = validate_v2_data_path(
            self._data_dir,
            self._data_dir / "v2" / "renditions" / asset_id / version_id / f"{kind}.{extension}",
            operation="v2-asset-rendition-target",
        )
        if target.is_file() and not target.is_symlink():
            return AssetRendition(path=target, media_type="image/jpeg", kind=kind)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.stem}.{uuid4().hex}.{extension}")
        if media_type == "image":
            filters = "scale=640:640:force_original_aspect_ratio=decrease"
            command = [
                self._ffmpeg_path,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                source_path.as_posix(),
                "-vf",
                filters,
                "-frames:v",
                "1",
                "-q:v",
                "5",
                temporary.as_posix(),
            ]
        else:
            command = [
                self._ffmpeg_path,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                "0",
                "-i",
                source_path.as_posix(),
                "-frames:v",
                "1",
                "-vf",
                "scale=640:640:force_original_aspect_ratio=decrease",
                "-q:v",
                "5",
                temporary.as_posix(),
            ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise V2PersistenceError(
                "asset_rendition_generation_failed",
                "Asset preview generation failed.",
                stage="v2_asset_rendition_service",
            ) from error
        if completed.returncode != 0 or not temporary.is_file():
            temporary.unlink(missing_ok=True)
            raise V2PersistenceError(
                "asset_rendition_generation_failed",
                "Asset preview generation failed.",
                stage="v2_asset_rendition_service",
            )
        os.replace(temporary, target)
        return AssetRendition(path=target, media_type="image/jpeg", kind=kind)
