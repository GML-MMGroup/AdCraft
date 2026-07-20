import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.dependencies import get_asset_service
from app.schemas.assets import (
    AssetListResponse,
    AssetPromptTarget,
    AssetRole,
    AssetUploadBatchResponse,
    AssetUploadResponse,
)
from app.services.asset_library import AssetLibraryError
from app.services.assets import AssetService, AssetUploadError

router = APIRouter(prefix="/assets", tags=["assets"])


@router.post("/upload", response_model=AssetUploadResponse | AssetUploadBatchResponse)
def upload_asset(
    service: Annotated[AssetService, Depends(get_asset_service)],
    file: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None, alias="files[]"),
    asset_role: AssetRole = Form("reference"),
    use_as_prompt: bool = Form(False),
    prompt_targets: str | None = Form(None),
    entity_type: str | None = Form(None),
    semantic_type: str | None = Form(None),
    assets_metadata: str | None = Form(None),
    group_as_entity: bool = Form(False),
    display_name: str | None = Form(None),
    description: str = Form(""),
    tags: str | None = Form(None),
    register_to_library: bool = Form(True),
) -> AssetUploadResponse | AssetUploadBatchResponse:
    try:
        upload_files = list(files or [])
        if file is not None:
            upload_files.insert(0, file)
        if group_as_entity or len(upload_files) > 1:
            return service.upload_assets(
                files=upload_files,
                asset_role=asset_role,
                use_as_prompt=use_as_prompt,
                prompt_targets=_parse_prompt_targets(prompt_targets),
                entity_type=entity_type,
                semantic_types=_parse_assets_metadata(assets_metadata, upload_files),
                display_name=display_name,
                description=description,
                tags=_parse_tags(tags),
                register_to_library=register_to_library,
                group_as_entity=group_as_entity,
            )
        if not upload_files:
            raise AssetUploadError("upload_file_required")
        return service.upload_asset(
            file=upload_files[0],
            asset_role=asset_role,
            use_as_prompt=use_as_prompt,
            prompt_targets=_parse_prompt_targets(prompt_targets),
            entity_type=entity_type,
            semantic_type=semantic_type,
            display_name=display_name,
            description=description,
            tags=_parse_tags(tags),
            register_to_library=register_to_library,
        )
    except AssetUploadError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except AssetLibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


@router.get("", response_model=AssetListResponse)
def list_assets(
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> AssetListResponse:
    return AssetListResponse(assets=service.list_assets())


def _parse_prompt_targets(value: str | None) -> list[AssetPromptTarget] | None:
    if value is None or not value.strip():
        return None
    allowed_targets = {"product_design", "character_design", "scene_design"}
    targets = [target.strip() for target in value.split(",") if target.strip()]
    invalid_targets = sorted(set(targets) - allowed_targets)
    if invalid_targets:
        raise AssetUploadError(f"Invalid prompt targets: {', '.join(invalid_targets)}.")
    return targets  # type: ignore[return-value]


def _parse_tags(value: str | None) -> list[str]:
    if value is None or not value.strip():
        return []
    parsed = _json_or_none(value)
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [tag.strip() for tag in value.split(",") if tag.strip()]


def _parse_assets_metadata(
    value: str | None,
    upload_files: list[UploadFile],
) -> list[str | None] | None:
    if value is None or not value.strip():
        return None
    parsed = _json_or_none(value)
    if not isinstance(parsed, list):
        raise AssetUploadError("assets_metadata_invalid")
    if len(parsed) != len(upload_files):
        raise AssetUploadError("assets_metadata_mismatch")
    semantic_types: list[str | None] = []
    for item, upload_file in zip(parsed, upload_files):
        if not isinstance(item, dict):
            raise AssetUploadError("assets_metadata_invalid")
        filename = item.get("filename")
        if filename:
            expected_filename = Path(str(upload_file.filename or "")).name
            metadata_filename = Path(str(filename)).name
            if metadata_filename != expected_filename:
                raise AssetUploadError("assets_metadata_filename_mismatch")
        semantic_type = item.get("semantic_type")
        semantic_types.append(str(semantic_type).strip() if semantic_type else None)
    return semantic_types


def _json_or_none(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None
