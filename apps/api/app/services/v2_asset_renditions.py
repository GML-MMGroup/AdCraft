"""On-demand, version-pinned media renditions for browser previews."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from app.persistence.errors import V2PersistenceError
from app.services.v2_data_boundary import validate_v2_data_path


@dataclass(frozen=True)
class AssetRendition:
    path: Path
    media_type: str
    kind: str


def read_image_dimensions(path: Path) -> tuple[int, int]:
    """Read dimensions from a rendered PNG or JPEG without a runtime image dependency."""

    content = path.read_bytes()
    if content[:8] == b"\x89PNG\r\n\x1a\n" and len(content) >= 24 and content[12:16] == b"IHDR":
        return int.from_bytes(content[16:20], "big"), int.from_bytes(content[20:24], "big")
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
                    int.from_bytes(content[position + 5 : position + 7], "big"),
                    int.from_bytes(content[position + 3 : position + 5], "big"),
                )
            position += length
    raise V2PersistenceError(
        "asset_rendition_metadata_invalid",
        "Asset rendition image metadata is invalid.",
        stage="v2_asset_rendition_service",
    )


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
        max_dimension: int | None = None,
        min_short_side: int | None = None,
        image_processing: Literal["storyboard_soften_v1", "human_face_blur_sigma7_v1"]
        | None = None,
    ) -> AssetRendition:
        if kind not in {"preview", "poster", "provider_reference"}:
            raise V2PersistenceError(
                "asset_rendition_kind_invalid",
                "Asset rendition kind is invalid.",
                stage="v2_asset_rendition_service",
            )
        if image_processing is not None and (
            image_processing not in {"storyboard_soften_v1", "human_face_blur_sigma7_v1"}
            or kind != "provider_reference"
            or media_type != "image"
        ):
            raise V2PersistenceError(
                "asset_rendition_processing_invalid",
                "Image processing requires an image provider reference rendition.",
                stage="v2_asset_rendition_service",
            )
        if media_type not in {"image", "video"}:
            raise V2PersistenceError(
                "asset_rendition_media_unsupported",
                "Asset rendition media type is unsupported.",
                stage="v2_asset_rendition_service",
            )
        if kind in {"poster", "provider_reference"} and (
            (kind == "poster" and media_type != "video")
            or (kind == "provider_reference" and media_type != "image")
        ):
            raise V2PersistenceError(
                "asset_rendition_media_unsupported",
                (
                    "Poster renditions require video media."
                    if kind == "poster"
                    else "Provider reference renditions require image media."
                ),
                stage="v2_asset_rendition_service",
            )
        if kind == "provider_reference":
            if max_dimension not in {None, 2048, 1536, 1024, 768, 512, 320}:
                raise V2PersistenceError(
                    "asset_rendition_size_invalid",
                    (
                        "Provider reference renditions require a 2048px, 1536px, 1024px, "
                        "768px, 512px, or 320px maximum dimension."
                    ),
                    stage="v2_asset_rendition_service",
                )
            if image_processing != "human_face_blur_sigma7_v1":
                max_dimension = max_dimension or 2048
            if min_short_side is not None and (
                max_dimension not in {1024, 768, 512, 320}
                or not 300 <= min_short_side <= max_dimension
            ):
                raise V2PersistenceError(
                    "asset_rendition_size_invalid",
                    "A minimum short side needs a 1024px, 768px, 512px, or 320px rendition "
                    "and 300px or more.",
                    stage="v2_asset_rendition_service",
                )
        elif min_short_side is not None:
            raise V2PersistenceError(
                "asset_rendition_size_invalid",
                "Only provider reference renditions accept a minimum short side.",
                stage="v2_asset_rendition_service",
            )
        elif max_dimension is not None and max_dimension not in {320, 640}:
            raise V2PersistenceError(
                "asset_rendition_size_invalid",
                "Asset rendition size is invalid.",
                stage="v2_asset_rendition_service",
            )
        extension = "jpg"
        target_name = (
            f"{kind}-{max_dimension}-short{min_short_side}.jpg"
            if min_short_side is not None
            else f"{kind}-{max_dimension}.jpg"
            if max_dimension is not None
            else f"{kind}.{extension}"
        )
        if image_processing is not None:
            target_name = f"{Path(target_name).stem}-{image_processing}.jpg"
        target = validate_v2_data_path(
            self._data_dir,
            self._data_dir / "v2" / "renditions" / asset_id / version_id / target_name,
            operation="v2-asset-rendition-target",
        )
        if target.is_file() and not target.is_symlink():
            return AssetRendition(path=target, media_type="image/jpeg", kind=kind)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.stem}.{uuid4().hex}.{extension}")
        if media_type == "image":
            dimension = max_dimension or 640
            filters = (
                "null"
                if kind == "provider_reference" and max_dimension is None
                # Long side at the target, but never a short side below the
                # provider minimum (Seedance rejects images under 300px).
                else f"scale=w='if(gte(iw\\,ih)\\,min(iw\\,max({dimension}\\,"
                f"ceil({min_short_side}*iw/ih/2)*2))\\,-2)'"
                f":h='if(gte(iw\\,ih)\\,-2\\,min(ih\\,max({dimension}\\,"
                f"ceil({min_short_side}*ih/iw/2)*2)))'"
                if kind == "provider_reference" and min_short_side is not None
                else f"scale='min({dimension},iw)':'min({dimension},ih)':force_original_aspect_ratio=decrease"
                if kind == "provider_reference"
                else f"scale={dimension}:{dimension}:force_original_aspect_ratio=decrease"
            )
            quality = "3" if kind == "provider_reference" else "5"
            if image_processing == "storyboard_soften_v1":
                # Remove fine strokes and facial detail from the provider copy.
                # Scale sigma with delivery size to keep the same visual treatment.
                sigma = 4 * dimension / 320
                filters += f",gblur=sigma={sigma}:steps=3"
            elif image_processing == "human_face_blur_sigma7_v1":
                filters += ",gblur=sigma=7:steps=3"
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
                quality,
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
                f"scale={max_dimension or 640}:{max_dimension or 640}:force_original_aspect_ratio=decrease",
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
