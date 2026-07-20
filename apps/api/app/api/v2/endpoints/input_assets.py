from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.core.config import Settings, get_settings
from app.schemas.workflow_v2 import V2InputAssetUploadResponse
from app.services.v2_input_assets import (
    V2InputAssetError,
    V2InputAssetService,
    input_asset_view,
)


router = APIRouter(prefix="/input-assets", tags=["v2-input-assets"])


def get_v2_input_asset_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> V2InputAssetService:
    return V2InputAssetService(settings=settings)


@router.post("/upload", response_model=V2InputAssetUploadResponse)
def upload_input_assets(
    service: Annotated[V2InputAssetService, Depends(get_v2_input_asset_service)],
    intent: Annotated[Literal["product_reference", "style_reference", "generic_reference"], Form()],
    files_bracket: Annotated[list[UploadFile] | None, File(alias="files[]")] = None,
    files_plain: Annotated[list[UploadFile] | None, File(alias="files")] = None,
    display_name: Annotated[str | None, Form()] = None,
    tags_bracket: Annotated[list[str] | None, Form(alias="tags[]")] = None,
    tags_plain: Annotated[list[str] | None, Form(alias="tags")] = None,
) -> V2InputAssetUploadResponse:
    files = [*(files_bracket or []), *(files_plain or [])]
    tags = [*(tags_bracket or []), *(tags_plain or [])]
    try:
        records = service.upload_pre_workflow_assets(
            files=files,
            intent=intent,
            display_name=display_name,
            tags=tags,
        )
    except V2InputAssetError as exc:
        raise _upload_http_error(exc) from exc
    return V2InputAssetUploadResponse(assets=[input_asset_view(record) for record in records])


def _upload_http_error(exc: V2InputAssetError) -> HTTPException:
    if exc.code in {
        "upload_file_required",
        "upload_file_too_large",
        "unsupported_upload_media_type",
        "input_asset_intent_incompatible",
    }:
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        )
    if exc.code == "v2_data_boundary_violation":
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"code": exc.code, "message": str(exc)},
    )
