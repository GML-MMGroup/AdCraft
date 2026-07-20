from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_ad_workflow_service,
    get_ad_workflow_plan_service,
    get_chat_workflow_service,
    get_media_task_service,
)
from app.schemas.ad_workflow import AdWorkflowGenerateRequest, AdWorkflowResponse
from app.schemas.chat_workflow import ChatWorkflowResponse
from app.schemas.front_desk import FrontDeskChatRequest
from app.schemas.media_tasks import MediaPollRequest, MediaStatusResponse
from app.services.ad_workflow import AdWorkflowService, WorkflowGenerationError
from app.services.asset_library import AssetLibraryError
from app.services.chat_workflow import ChatWorkflowError, ChatWorkflowService
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


@router.post("/plan-from-chat", response_model=ChatWorkflowResponse)
def plan_ad_workflow_from_chat(
    request: FrontDeskChatRequest,
    service: Annotated[AdWorkflowPlanService, Depends(get_ad_workflow_plan_service)],
) -> ChatWorkflowResponse:
    if _requests_v2_workflow(request):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "unsupported_workflow_schema_version",
                "message": "Use /api/v2/workflows/plan-from-chat for v2 workflows.",
            },
        )
    try:
        return service.plan_from_chat(request)
    except AssetLibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    except WorkflowPlanError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.post("/generate", response_model=AdWorkflowResponse)
def generate_ad_workflow(
    request: AdWorkflowGenerateRequest,
    service: Annotated[AdWorkflowService, Depends(get_ad_workflow_service)],
) -> AdWorkflowResponse:
    try:
        return service.generate(request)
    except AssetLibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    except WorkflowGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.post("/from-chat", response_model=ChatWorkflowResponse)
def generate_ad_workflow_from_chat(
    request: FrontDeskChatRequest,
    service: Annotated[ChatWorkflowService, Depends(get_chat_workflow_service)],
) -> ChatWorkflowResponse:
    try:
        return service.generate_from_chat(request)
    except ChatWorkflowError as exc:
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


def _requests_v2_workflow(request: FrontDeskChatRequest) -> bool:
    if request.workflow_schema_version == 2:
        return True
    if isinstance(request.workflow_version, str) and request.workflow_version.lower() == "v2":
        return True
    metadata = request.metadata
    return metadata.get("workflow_schema_version") == 2 or metadata.get("workflow_version") == "v2"
