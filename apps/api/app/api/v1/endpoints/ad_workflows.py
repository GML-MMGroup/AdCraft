from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_ad_workflow_plan_service,
    get_media_task_service,
)
from app.schemas.ad_workflow import AdWorkflowGenerateRequest, AdWorkflowResponse
from app.schemas.media_tasks import MediaPollRequest, MediaStatusResponse
from app.services.asset_library import AssetLibraryError
from app.services.media_tasks import MediaTaskService
from app.services.workflow_plan import AdWorkflowPlanService, WorkflowPlanError

router = APIRouter(prefix="/ad-workflows", tags=["ad-workflows"])


@router.post("/plan", response_model=AdWorkflowResponse)
def plan_ad_workflow(
    request: AdWorkflowGenerateRequest,
    service: Annotated[AdWorkflowPlanService, Depends(get_ad_workflow_plan_service)],
) -> AdWorkflowResponse:
    try:
        return service.plan(request)
    except AssetLibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    except WorkflowPlanError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.get("/{workflow_id}/media-status", response_model=MediaStatusResponse)
def get_ad_workflow_media_status(
    workflow_id: str,
    service: Annotated[MediaTaskService, Depends(get_media_task_service)],
) -> MediaStatusResponse:
    return service.refresh_media_status(workflow_id)


@router.post("/{workflow_id}/media/poll", response_model=MediaStatusResponse)
def poll_ad_workflow_media(
    workflow_id: str,
    request: MediaPollRequest,
    service: Annotated[MediaTaskService, Depends(get_media_task_service)],
) -> MediaStatusResponse:
    try:
        return service.poll_media(
            workflow_id,
            download_media=request.download_media,
            compose_when_ready=request.compose_when_ready,
            wait_until_ready=request.wait_until_ready,
            interval_seconds=request.interval_seconds,
            max_attempts=request.max_attempts,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
