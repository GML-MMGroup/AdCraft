from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_video_editing_service
from app.schemas.video_editing import VideoEditingExportRequest, VideoEditingExportResult
from app.services.video_editing import VideoEditingError, VideoEditingService

router = APIRouter(prefix="/video-editing", tags=["video-editing"])


@router.post("/export", response_model=VideoEditingExportResult)
def export_video_timeline(
    request: VideoEditingExportRequest,
    service: Annotated[VideoEditingService, Depends(get_video_editing_service)],
) -> VideoEditingExportResult:
    try:
        return service.export(request)
    except VideoEditingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/exports/{export_id}", response_model=VideoEditingExportResult)
def get_video_export(
    export_id: str,
    service: Annotated[VideoEditingService, Depends(get_video_editing_service)],
) -> VideoEditingExportResult:
    try:
        return service.get_export(export_id)
    except VideoEditingError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
