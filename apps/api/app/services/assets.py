import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import Settings
from app.schemas.asset_library import (
    SUPPORTED_LIBRARY_ENTITY_TYPES,
    SUPPORTED_LIBRARY_SEMANTIC_TYPES,
)
from app.schemas.assets import (
    AssetUploadBatchResponse,
    AssetPromptTarget,
    AssetRole,
    AssetType,
    AssetUploadResponse,
    default_prompt_targets_for_role,
)
from app.services.asset_library import AssetLibraryError, AssetLibraryService
from app.services.canonical_assets import (
    canonical_media_type,
    canonical_semantic_type,
    semantic_type_matches_media_entity,
)
from app.services.media_paths import public_url_for_path

ALLOWED_MIME_PREFIXES = {
    "image": "image/",
    "video": "video/",
    "audio": "audio/",
}

DEFAULT_REUSE_POLICY = {
    "use_as_prompt": True,
    "lock_identity": False,
    "allow_style_transfer": False,
}

DEFAULT_SEMANTIC_TYPES = {
    ("image", "character"): "character_main",
    ("image", "scene"): "scene_main",
    ("image", "storyboard_shot"): "storyboard_image",
    ("image", "style_reference"): "style_reference",
    ("image", "uploaded_reference"): "uploaded_reference",
    ("image", "product"): "product_reference",
    ("video", "storyboard_shot"): "storyboard_video",
    ("video", "video_clip"): "storyboard_video",
    ("video", "uploaded_reference"): "uploaded_reference",
    ("audio", "bgm"): "bgm",
    ("audio", "uploaded_reference"): "uploaded_reference",
}

SEMANTIC_ASSET_TYPES = {
    "character_main": {"image"},
    "character_face_id": {"image"},
    "character_three_view": {"image"},
    "character_concept": {"image"},
    "scene_main": {"image"},
    "scene_multi_view": {"image"},
    "storyboard_image": {"image"},
    "product_reference": {"image"},
    "product_image": {"image"},
    "style_reference": {"image"},
    "storyboard_video": {"video"},
    "final_video": {"video"},
    "bgm": {"audio"},
    "uploaded_reference": {"image", "video", "audio"},
}

ENTITY_SEMANTIC_TYPES = {
    "character": {
        "character_main",
        "character_face_id",
        "character_three_view",
        "character_concept",
    },
    "scene": {"scene_main", "scene_multi_view"},
    "storyboard_shot": {"storyboard_image", "storyboard_video"},
    "video_clip": {"storyboard_video", "final_video"},
    "bgm": {"bgm"},
    "product": {"product_reference", "product_image", "uploaded_reference"},
    "style_reference": {"style_reference"},
    "uploaded_reference": {"uploaded_reference"},
}


class AssetUploadError(RuntimeError):
    """Raised when an uploaded asset cannot be stored."""


class AssetService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._data_dir = settings.media_data_dir
        self._library = AssetLibraryService(settings)

    def upload_asset(
        self,
        file: UploadFile,
        asset_role: AssetRole,
        use_as_prompt: bool,
        prompt_targets: list[AssetPromptTarget] | None = None,
        *,
        entity_type: str | None = None,
        semantic_type: str | None = None,
        display_name: str | None = None,
        description: str = "",
        tags: list[str] | None = None,
        register_to_library: bool = True,
    ) -> AssetUploadResponse:
        batch = self.upload_assets(
            files=[file],
            asset_role=asset_role,
            use_as_prompt=use_as_prompt,
            prompt_targets=prompt_targets,
            entity_type=entity_type,
            semantic_types=[semantic_type] if semantic_type else None,
            display_name=display_name,
            description=description,
            tags=tags,
            register_to_library=register_to_library,
            group_as_entity=False,
        )
        if not batch.assets:
            raise AssetUploadError("upload_failed")
        return batch.assets[0]

    def upload_assets(
        self,
        *,
        files: list[UploadFile],
        asset_role: AssetRole,
        use_as_prompt: bool,
        prompt_targets: list[AssetPromptTarget] | None = None,
        entity_type: str | None = None,
        semantic_types: list[str | None] | None = None,
        display_name: str | None = None,
        description: str = "",
        tags: list[str] | None = None,
        register_to_library: bool = True,
        group_as_entity: bool = False,
    ) -> AssetUploadBatchResponse:
        if not files:
            raise AssetUploadError("upload_file_required")
        entity_type = _validated_entity_type(entity_type or "uploaded_reference")
        strict_semantic_validation = group_as_entity or len(files) > 1
        file_specs = [
            _validated_file_spec(
                file,
                entity_type,
                _semantic_at(semantic_types, index),
                index=index,
                strict_semantic_validation=strict_semantic_validation,
            )
            for index, file in enumerate(files)
        ]
        created_dirs: list[Path] = []
        uploaded_assets: list[AssetUploadResponse] = []
        try:
            for file, asset_type, semantic_type, warnings in file_specs:
                filename_display_name = display_name or _display_name_from_filename(
                    file.filename or "upload.bin"
                )
                uploaded = self._write_uploaded_asset(
                    file=file,
                    asset_type=asset_type,
                    asset_role=asset_role,
                    use_as_prompt=use_as_prompt,
                    prompt_targets=prompt_targets,
                    display_name=filename_display_name,
                    semantic_type=semantic_type,
                    warnings=warnings,
                )
                created_dirs.append(self._data_dir / Path(uploaded.local_path).parent)
                _enforce_size_limit(uploaded, self._settings)
                uploaded_assets.append(uploaded)
            if register_to_library:
                detail = self._library.create_entity_from_uploaded_assets(
                    uploaded_assets=[asset.model_dump(mode="json") for asset in uploaded_assets],
                    entity_type=entity_type,
                    semantic_types=[semantic_type for _, _, semantic_type, _ in file_specs],
                    display_name=display_name
                    or _display_name_from_filename(uploaded_assets[0].filename),
                    description=description,
                    tags=tags or [],
                    reuse_policy=dict(DEFAULT_REUSE_POLICY),
                )
                uploaded_assets = [
                    _attach_library_detail(asset, detail.entity.model_dump(mode="json"), detail)
                    for asset in uploaded_assets
                ]
                for asset in uploaded_assets:
                    _write_upload_metadata(self._data_dir, asset)
                return AssetUploadBatchResponse(
                    assets=uploaded_assets,
                    library_entity_id=detail.entity.entity_id,
                    library_asset_ids=[asset.asset_id for asset in detail.assets],
                    library_entity=detail.entity.model_dump(mode="json"),
                    library_assets=[asset.model_dump(mode="json") for asset in detail.assets],
                )
            return AssetUploadBatchResponse(assets=uploaded_assets)
        except (AssetUploadError, AssetLibraryError):
            for directory in created_dirs:
                shutil.rmtree(directory, ignore_errors=True)
            raise

    def _write_uploaded_asset(
        self,
        *,
        file: UploadFile,
        asset_type: AssetType,
        asset_role: AssetRole,
        use_as_prompt: bool,
        prompt_targets: list[AssetPromptTarget] | None,
        display_name: str,
        semantic_type: str,
        warnings: list[dict[str, Any]],
    ) -> AssetUploadResponse:
        filename = _safe_filename(file.filename)
        asset_id = f"asset_{uuid4().hex[:12]}"
        relative_path = Path("assets") / _asset_dir_name(asset_type) / asset_id / filename
        output_path = self._data_dir / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("wb") as output_file:
            shutil.copyfileobj(file.file, output_file)

        metadata = AssetUploadResponse(
            asset_id=asset_id,
            asset_type=asset_type,
            media_type=asset_type,
            type=asset_type,
            kind=asset_type,
            asset_role=asset_role,
            filename=filename,
            display_name=display_name,
            semantic_type=semantic_type,
            mime_type=file.content_type or "application/octet-stream",
            local_path=relative_path.as_posix(),
            public_url=public_url_for_path(relative_path.as_posix()),
            use_as_prompt=use_as_prompt,
            prompt_targets=prompt_targets or default_prompt_targets_for_role(asset_role),
            size_bytes=output_path.stat().st_size,
            warnings=warnings,
            metadata={"warnings": warnings} if warnings else {},
        )
        _write_upload_metadata(self._data_dir, metadata)
        return metadata

    def list_assets(self) -> list[AssetUploadResponse]:
        metadata_files = (self._data_dir / "assets").glob("*/*/metadata.json")
        return [
            AssetUploadResponse.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(metadata_files)
        ]


def _asset_type_from_mime(mime_type: str | None) -> AssetType:
    if mime_type is None:
        raise AssetUploadError("Uploaded file must include a content type.")
    asset_type = canonical_media_type({"mime_type": mime_type})
    if asset_type in ALLOWED_MIME_PREFIXES:
        return asset_type  # type: ignore[return-value]
    raise AssetUploadError("Only image, video, and audio uploads are supported.")


def _safe_filename(filename: str | None) -> str:
    if not filename:
        return "upload.bin"
    safe = Path(filename).name.strip().replace("\\", "_").replace("/", "_")
    return safe or "upload.bin"


def _asset_dir_name(asset_type: AssetType) -> str:
    return "audio" if asset_type == "audio" else f"{asset_type}s"


def _write_upload_metadata(data_dir: Path, metadata: AssetUploadResponse) -> None:
    metadata_path = data_dir / Path(metadata.local_path).parent / "metadata.json"
    metadata_path.write_text(
        metadata.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def _validated_entity_type(entity_type: str) -> str:
    if entity_type not in SUPPORTED_LIBRARY_ENTITY_TYPES:
        raise AssetUploadError("invalid_entity_type")
    return entity_type


def _validated_file_spec(
    file: UploadFile,
    entity_type: str,
    semantic_type: str | None,
    *,
    index: int,
    strict_semantic_validation: bool,
) -> tuple[UploadFile, AssetType, str, list[dict[str, Any]]]:
    asset_type = _asset_type_from_mime(file.content_type)
    canonical_default = canonical_semantic_type(
        {"media_type": asset_type},
        entity_type=entity_type,
        media_type=asset_type,
    )
    semantic_type = semantic_type or DEFAULT_SEMANTIC_TYPES.get((asset_type, entity_type))
    if not semantic_type:
        semantic_type = canonical_default
    warnings: list[dict[str, Any]] = []
    if not _semantic_type_allowed_for_upload(
        semantic_type,
        entity_type=entity_type,
        asset_type=asset_type,
    ):
        if strict_semantic_validation or not _semantic_type_allowed_for_upload(
            canonical_default,
            entity_type=entity_type,
            asset_type=asset_type,
        ):
            raise AssetUploadError(
                _invalid_semantic_type_detail(
                    index=index,
                    entity_type=entity_type,
                    semantic_type=semantic_type,
                    media_type=asset_type,
                )
            )
        warnings.append(
            {
                "code": "semantic_type_normalized",
                "from": semantic_type,
                "to": canonical_default,
                "media_type": asset_type,
                "entity_type": entity_type,
            }
        )
        semantic_type = canonical_default
    return file, asset_type, semantic_type, warnings


def _semantic_type_allowed_for_upload(
    semantic_type: str,
    *,
    entity_type: str,
    asset_type: str,
) -> bool:
    if semantic_type not in SUPPORTED_LIBRARY_SEMANTIC_TYPES:
        return False
    allowed_semantic_types = ENTITY_SEMANTIC_TYPES.get(entity_type, set())
    if semantic_type not in allowed_semantic_types:
        return False
    allowed_asset_types = SEMANTIC_ASSET_TYPES.get(semantic_type, set())
    if asset_type not in allowed_asset_types:
        return False
    return semantic_type_matches_media_entity(
        semantic_type,
        media_type=asset_type,
        entity_type=entity_type,
    )


def _invalid_semantic_type_detail(
    *,
    index: int,
    entity_type: str,
    semantic_type: str,
    media_type: str,
) -> str:
    return (
        "invalid_semantic_type"
        f":file_index={index},entity_type={entity_type},"
        f"semantic_type={semantic_type},media_type={media_type}"
    )


def _semantic_at(values: list[str | None] | None, index: int) -> str | None:
    if not values or index >= len(values):
        return None
    return values[index]


def _enforce_size_limit(asset: AssetUploadResponse, settings: Settings) -> None:
    limits = {
        "image": settings.upload_image_max_bytes,
        "audio": settings.upload_audio_max_bytes,
        "video": settings.upload_video_max_bytes,
    }
    limit = limits.get(asset.asset_type)
    if limit is not None and asset.size_bytes > limit:
        raise AssetUploadError("upload_file_too_large")


def _display_name_from_filename(filename: str) -> str:
    stem = Path(filename).stem.strip()
    return stem or filename or "Uploaded Asset"


def _attach_library_detail(
    asset: AssetUploadResponse,
    entity: dict[str, Any],
    detail: Any,
) -> AssetUploadResponse:
    return asset.model_copy(
        update={
            "library_entity_id": entity.get("entity_id"),
            "library_asset_ids": [item.asset_id for item in detail.assets],
            "library_entity": entity,
            "library_assets": [item.model_dump(mode="json") for item in detail.assets],
        }
    )
