import asyncio
import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.api.dependencies import get_front_desk_service
from app.core.config import Settings, get_settings
from app.schemas.front_desk import FrontDeskChatRequest
from app.schemas.workflow_v2_screenplay import (
    V2ScriptConfirmResponse,
    V2ScriptReadResponse,
    V2ScriptSelectVersionRequest,
    V2ScriptSelectVersionResponse,
    V2ScriptVersionListResponse,
)
from app.schemas.workflow_v2 import (
    AbsorbAssetRequestV2,
    AbsorbAssetResponseV2,
    AddSlotReferenceRequestV2,
    AddSlotReferenceResponseV2,
    SelectSlotVersionRequestV2,
    SelectSlotVersionResponseV2,
    V2ReferenceAssetMutationResponse,
    V2AssetOwnerResponse,
    V2AssetLocatorResponse,
    V2RegisterLibraryReferenceRequest,
    V2RegisterReferenceRequest,
    V2SlotVersionsResponse,
    WorkflowAssetListResponseV2,
    WorkflowAssetOwnerTypeV2,
    WorkflowAssetSemanticTypeV2,
    WorkflowAssetStateV2,
    WorkflowAssetVersionsResponseV2,
    WorkflowV2,
    WorkflowV2ChatActionRequest,
    WorkflowV2ChatActionResponse,
    WorkflowV2ChatTargetRequest,
    WorkflowV2ChatTargetResponse,
    WorkflowV2ConfirmShotSummaryRequest,
    WorkflowV2Event,
    WorkflowV2EventListResponse,
    WorkflowV2FreeNodeAbsorbRequest,
    WorkflowV2FreeNodeAbsorbResponse,
    WorkflowV2FreeNodeCreateRequest,
    WorkflowV2FreeNodeGenerateRequest,
    WorkflowV2ItemGenerateRequest,
    WorkflowV2ItemPromptUpdateRequest,
    WorkflowV2PlanFromChatResponse,
    WorkflowV2PlanFromPromptRequest,
    WorkflowV2PlanningClarificationResponse,
    WorkflowV2ShotDetailPromptPatchRequest,
    WorkflowV2ShotDetailPromptRefineRequest,
    WorkflowV2ShotPrimarySceneUpdateRequest,
    WorkflowV2ShotPrimarySceneUpdateResponse,
    V2ProviderTask,
    V2ProviderTaskListResponse,
    V2ProviderTaskPollResponse,
    WorkflowV2ReferenceAttachRequest,
    WorkflowV2ReferenceMutationResponse,
    WorkflowV2RuntimeSnapshot,
    WorkflowV2RunRequest,
    WorkflowV2RunStartResponse,
    WorkflowV2RunResponse,
    WorkflowV2SlotPromptUpdateRequest,
    WorkflowV2TimelineClipCreateRequest,
    WorkflowV2TimelineClipDeleteRequest,
    WorkflowV2TimelineClipMutationResponse,
    WorkflowV2TimelineRenderRequest,
    WorkflowV2TimelineRenderStartResponse,
    WorkflowV2TimelineRenderStateResponse,
    WorkflowV2TimelineResponse,
    WorkflowV2TimelineSourceImportRequest,
    WorkflowV2TimelineSourceImportResponse,
    WorkflowV2TimelineUpdateRequest,
    WorkflowV2TimelineUpdateResponse,
)
from app.services.front_desk import FrontDeskService
from app.services.v2_asset_locator import V2AssetLocatorError, V2AssetLocatorResolver
from app.services.v2_final_composition_timeline import (
    V2FinalCompositionTimelineError,
    V2FinalCompositionTimelineService,
)
from app.services.v2_final_composition_render_service import V2FinalCompositionRenderService
from app.services.v2_script_versions import (
    V2ScriptVersionError,
    V2ScriptVersionService,
    parse_confirm_request,
)
from app.services.v2_workflow_assets import V2WorkflowAssetError, V2WorkflowAssetService
from app.services.workflow_v2 import WorkflowV2Error, WorkflowV2Service


router = APIRouter(prefix="/workflows", tags=["v2-workflows"])


def get_workflow_v2_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> WorkflowV2Service:
    return WorkflowV2Service(settings=settings)


def get_v2_workflow_asset_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> V2WorkflowAssetService:
    return V2WorkflowAssetService(settings.media_data_dir, settings=settings)


def get_v2_asset_locator_resolver(
    settings: Annotated[Settings, Depends(get_settings)],
) -> V2AssetLocatorResolver:
    return V2AssetLocatorResolver(settings.media_data_dir)


def get_v2_final_timeline_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> V2FinalCompositionTimelineService:
    return V2FinalCompositionTimelineService(settings)


def get_v2_final_composition_render_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> V2FinalCompositionRenderService:
    return V2FinalCompositionRenderService(settings)


def get_v2_script_version_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> V2ScriptVersionService:
    return V2ScriptVersionService(settings.media_data_dir)


def _sse_event(event: WorkflowV2Event) -> str:
    payload = json.dumps(
        event.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"id: {event.seq}\nevent: {event.event_type}\ndata: {payload}\n\n"


@router.post(
    "/plan-from-prompt", response_model=WorkflowV2 | WorkflowV2PlanningClarificationResponse
)
def plan_from_prompt(
    request: WorkflowV2PlanFromPromptRequest,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2 | WorkflowV2PlanningClarificationResponse:
    try:
        return service.plan_from_prompt(request)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.post("/plan-from-chat", response_model=WorkflowV2PlanFromChatResponse)
def plan_from_chat(
    request: FrontDeskChatRequest,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
    front_desk_service: Annotated[FrontDeskService, Depends(get_front_desk_service)],
) -> WorkflowV2PlanFromChatResponse:
    try:
        return service.plan_from_chat(request, front_desk_service=front_desk_service)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.get("/{workflow_id}/script", response_model=V2ScriptReadResponse)
def read_workflow_script(
    workflow_id: str,
    service: Annotated[V2ScriptVersionService, Depends(get_v2_script_version_service)],
) -> V2ScriptReadResponse:
    try:
        return service.read_selected(workflow_id)
    except V2ScriptVersionError as exc:
        raise _v2_script_http_error(exc) from exc


@router.post("/{workflow_id}/script/confirm", response_model=V2ScriptConfirmResponse)
def confirm_workflow_script(
    workflow_id: str,
    payload: Annotated[Any, Body()],
    service: Annotated[V2ScriptVersionService, Depends(get_v2_script_version_service)],
) -> V2ScriptConfirmResponse:
    try:
        return service.confirm(workflow_id, parse_confirm_request(payload))
    except V2ScriptVersionError as exc:
        raise _v2_script_http_error(exc) from exc


@router.get("/{workflow_id}/script/versions", response_model=V2ScriptVersionListResponse)
def list_workflow_script_versions(
    workflow_id: str,
    service: Annotated[V2ScriptVersionService, Depends(get_v2_script_version_service)],
) -> V2ScriptVersionListResponse:
    try:
        return service.list_versions(workflow_id)
    except V2ScriptVersionError as exc:
        raise _v2_script_http_error(exc) from exc


@router.post(
    "/{workflow_id}/script/versions/{script_version_id}/select",
    response_model=V2ScriptSelectVersionResponse,
)
def select_workflow_script_version(
    workflow_id: str,
    script_version_id: str,
    request: V2ScriptSelectVersionRequest,
    service: Annotated[V2ScriptVersionService, Depends(get_v2_script_version_service)],
) -> V2ScriptSelectVersionResponse:
    try:
        return service.select(
            workflow_id,
            script_version_id,
            base_selected_script_version_id=request.base_selected_script_version_id,
        )
    except V2ScriptVersionError as exc:
        raise _v2_script_http_error(exc) from exc


@router.get("/{workflow_id}", response_model=WorkflowV2)
def get_workflow(
    workflow_id: str,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2:
    try:
        return service.get_workflow(workflow_id)
    except WorkflowV2Error as exc:
        if exc.code == "unsupported_workflow_schema_version":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.get("/{workflow_id}/assets", response_model=WorkflowAssetListResponseV2)
def list_workflow_assets(
    workflow_id: str,
    service: Annotated[V2WorkflowAssetService, Depends(get_v2_workflow_asset_service)],
    media_type: Literal["image", "video", "audio"] | None = None,
    semantic_type: WorkflowAssetSemanticTypeV2 | None = None,
    node_id: str | None = None,
    item_id: str | None = None,
    slot_id: str | None = None,
    state: WorkflowAssetStateV2 | None = None,
    owner_type: WorkflowAssetOwnerTypeV2 | None = None,
) -> WorkflowAssetListResponseV2:
    try:
        return service.list_workflow_assets(
            workflow_id,
            media_type=media_type,
            semantic_type=semantic_type,
            node_id=node_id,
            item_id=item_id,
            slot_id=slot_id,
            state=state,
            owner_type=owner_type,
        )
    except V2WorkflowAssetError as exc:
        raise _workflow_v2_asset_http_error(exc) from exc


@router.get(
    "/{workflow_id}/assets/{asset_id}/versions",
    response_model=WorkflowAssetVersionsResponseV2,
)
def list_workflow_asset_versions(
    workflow_id: str,
    asset_id: str,
    service: Annotated[V2WorkflowAssetService, Depends(get_v2_workflow_asset_service)],
) -> WorkflowAssetVersionsResponseV2:
    try:
        return service.list_asset_versions(workflow_id, asset_id)
    except V2WorkflowAssetError as exc:
        raise _workflow_v2_asset_http_error(exc) from exc


@router.post(
    "/{workflow_id}/slots/{slot_id}/select-version",
    response_model=SelectSlotVersionResponseV2,
)
def select_workflow_asset_version(
    workflow_id: str,
    slot_id: str,
    request: SelectSlotVersionRequestV2,
    service: Annotated[V2WorkflowAssetService, Depends(get_v2_workflow_asset_service)],
) -> SelectSlotVersionResponseV2:
    try:
        return service.select_slot_version(workflow_id, slot_id, request)
    except V2WorkflowAssetError as exc:
        raise _workflow_v2_asset_http_error(exc) from exc


@router.post(
    "/{workflow_id}/slots/{slot_id}/references",
    response_model=AddSlotReferenceResponseV2,
)
def add_workflow_slot_reference(
    workflow_id: str,
    slot_id: str,
    request: AddSlotReferenceRequestV2,
    service: Annotated[V2WorkflowAssetService, Depends(get_v2_workflow_asset_service)],
) -> AddSlotReferenceResponseV2:
    try:
        return service.add_slot_reference(workflow_id, slot_id, request)
    except V2WorkflowAssetError as exc:
        raise _workflow_v2_asset_http_error(exc) from exc


@router.post(
    "/{workflow_id}/slots/{slot_id}/reference-assets/upload",
    response_model=V2ReferenceAssetMutationResponse,
)
def upload_workflow_slot_reference_assets(
    workflow_id: str,
    slot_id: str,
    service: Annotated[V2WorkflowAssetService, Depends(get_v2_workflow_asset_service)],
    files_bracket: Annotated[list[UploadFile] | None, File(alias="files[]")] = None,
    files_plain: Annotated[list[UploadFile] | None, File(alias="files")] = None,
    reference_role: Annotated[
        Literal["product", "character", "scene", "style", "composition", "motion", "audio"] | None,
        Form(),
    ] = None,
    display_name: Annotated[str | None, Form()] = None,
    tags_bracket: Annotated[list[str] | None, Form(alias="tags[]")] = None,
    tags_plain: Annotated[list[str] | None, Form(alias="tags")] = None,
) -> V2ReferenceAssetMutationResponse:
    try:
        return service.upload_slot_reference_assets(
            workflow_id,
            slot_id,
            files=[*(files_bracket or []), *(files_plain or [])],
            reference_role=reference_role,
            display_name=display_name,
            tags=[*(tags_bracket or []), *(tags_plain or [])],
        )
    except V2WorkflowAssetError as exc:
        raise _workflow_v2_asset_http_error(exc) from exc


@router.post(
    "/{workflow_id}/assets/register-reference",
    response_model=V2ReferenceAssetMutationResponse,
)
def register_workflow_reference_asset(
    workflow_id: str,
    request: V2RegisterReferenceRequest,
    service: Annotated[V2WorkflowAssetService, Depends(get_v2_workflow_asset_service)],
) -> V2ReferenceAssetMutationResponse:
    try:
        return service.register_reference(workflow_id, request)
    except V2WorkflowAssetError as exc:
        raise _workflow_v2_asset_http_error(exc) from exc


@router.post(
    "/{workflow_id}/assets/register-library-reference",
    response_model=V2ReferenceAssetMutationResponse,
)
def register_workflow_library_reference_asset(
    workflow_id: str,
    request: V2RegisterLibraryReferenceRequest,
    service: Annotated[V2WorkflowAssetService, Depends(get_v2_workflow_asset_service)],
) -> V2ReferenceAssetMutationResponse:
    try:
        return service.register_library_reference(workflow_id, request)
    except V2WorkflowAssetError as exc:
        raise _workflow_v2_asset_http_error(exc) from exc


@router.post(
    "/{workflow_id}/assets/{asset_id}/absorb",
    response_model=AbsorbAssetResponseV2,
)
def absorb_workflow_asset(
    workflow_id: str,
    asset_id: str,
    request: AbsorbAssetRequestV2,
    service: Annotated[V2WorkflowAssetService, Depends(get_v2_workflow_asset_service)],
) -> AbsorbAssetResponseV2:
    try:
        return service.absorb_asset(workflow_id, asset_id, request)
    except V2WorkflowAssetError as exc:
        raise _workflow_v2_asset_http_error(exc) from exc


@router.get("/{workflow_id}/locators/resolve", response_model=V2AssetLocatorResponse)
def resolve_asset_locator(
    workflow_id: str,
    locator: str,
    resolver: Annotated[V2AssetLocatorResolver, Depends(get_v2_asset_locator_resolver)],
) -> V2AssetLocatorResponse:
    try:
        return resolver.resolve(workflow_id, locator)
    except (V2AssetLocatorError, WorkflowV2Error) as exc:
        raise _workflow_v2_locator_http_error(exc) from exc


@router.post(
    "/{workflow_id}/run", response_model=WorkflowV2RunResponse | WorkflowV2RunStartResponse
)
def run_workflow(
    workflow_id: str,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
    request: WorkflowV2RunRequest | None = None,
    wait: bool = False,
) -> WorkflowV2RunResponse | WorkflowV2RunStartResponse:
    try:
        request = request or WorkflowV2RunRequest()
        return service.run_workflow(
            workflow_id,
            wait=wait,
            mode=request.mode,
            source_action=request.source_action,
        )
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.post("/{workflow_id}/storyboard/shots/{shot_id}/confirm-summary", response_model=WorkflowV2)
def confirm_shot_summary(
    workflow_id: str,
    shot_id: str,
    request: WorkflowV2ConfirmShotSummaryRequest,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2:
    try:
        return service.confirm_shot_summary(
            workflow_id,
            shot_id,
            request.shot_summary_prompt,
        )
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.patch("/{workflow_id}/storyboard/shots/{shot_id}/detail-prompts", response_model=WorkflowV2)
def patch_shot_detail_prompts(
    workflow_id: str,
    shot_id: str,
    request: WorkflowV2ShotDetailPromptPatchRequest,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2:
    try:
        return service.patch_shot_detail_prompts(workflow_id, shot_id, request)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.post(
    "/{workflow_id}/storyboard/shots/{shot_id}/refine-detail-prompts",
    response_model=WorkflowV2,
)
def refine_shot_detail_prompts(
    workflow_id: str,
    shot_id: str,
    request: WorkflowV2ShotDetailPromptRefineRequest,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2:
    try:
        return service.refine_shot_detail_prompts(workflow_id, shot_id, request)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.patch(
    "/{workflow_id}/storyboard/shots/{shot_id}/primary-scene",
    response_model=WorkflowV2ShotPrimarySceneUpdateResponse,
)
def update_shot_primary_scene(
    workflow_id: str,
    shot_id: str,
    request: WorkflowV2ShotPrimarySceneUpdateRequest,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2ShotPrimarySceneUpdateResponse:
    try:
        return service.update_shot_primary_scene(workflow_id, shot_id, request.scene_item_id)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.delete("/{workflow_id}/slots/{slot_id}/selected-asset", response_model=WorkflowV2)
def delete_selected_slot_asset(
    workflow_id: str,
    slot_id: str,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2:
    try:
        return service.delete_selected_slot_asset(workflow_id, slot_id)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.patch("/{workflow_id}/items/{item_id}/prompt", response_model=WorkflowV2)
def update_item_prompt(
    workflow_id: str,
    item_id: str,
    request: WorkflowV2ItemPromptUpdateRequest,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2:
    try:
        return service.update_item_prompt(workflow_id, item_id, request.item_prompt)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.patch("/{workflow_id}/slots/{slot_id}/prompt", response_model=WorkflowV2)
def update_slot_prompt(
    workflow_id: str,
    slot_id: str,
    request: WorkflowV2SlotPromptUpdateRequest,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2:
    try:
        return service.update_slot_prompt(
            workflow_id,
            slot_id,
            slot_prompt=request.slot_prompt,
            negative_prompt=request.negative_prompt,
            detail_prompt_key=request.detail_prompt_key,
            visual_style_override=request.visual_style_override,
        )
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.post("/{workflow_id}/slots/{slot_id}/generate", response_model=WorkflowV2RunResponse)
def generate_slot(
    workflow_id: str,
    slot_id: str,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2RunResponse:
    try:
        return service.generate_slot(workflow_id, slot_id)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.post("/{workflow_id}/slots/{slot_id}/regenerate", response_model=WorkflowV2RunResponse)
def regenerate_slot(
    workflow_id: str,
    slot_id: str,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2RunResponse:
    try:
        return service.regenerate_slot(workflow_id, slot_id)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.post("/{workflow_id}/items/{item_id}/generate", response_model=WorkflowV2RunResponse)
def generate_item(
    workflow_id: str,
    item_id: str,
    request: WorkflowV2ItemGenerateRequest,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2RunResponse:
    try:
        return service.generate_item(workflow_id, item_id, request)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.get("/{workflow_id}/slots/{slot_id}/versions", response_model=V2SlotVersionsResponse)
def list_slot_versions(
    workflow_id: str,
    slot_id: str,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> V2SlotVersionsResponse:
    try:
        return service.list_slot_versions(workflow_id, slot_id)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.post(
    "/{workflow_id}/slots/{slot_id}/versions/{version_id}/select",
    response_model=SelectSlotVersionResponseV2,
)
def select_slot_version(
    workflow_id: str,
    slot_id: str,
    version_id: str,
    asset_service: Annotated[V2WorkflowAssetService, Depends(get_v2_workflow_asset_service)],
) -> SelectSlotVersionResponseV2:
    try:
        response = asset_service.select_slot_version_by_version_id(workflow_id, slot_id, version_id)
        return response.model_copy(
            update={
                "compatibility_only": True,
                "canonical_endpoint": (
                    f"/api/v2/workflows/{workflow_id}/slots/{slot_id}/select-version"
                ),
            }
        )
    except V2WorkflowAssetError as exc:
        raise _workflow_v2_asset_http_error(exc) from exc


@router.post("/{workflow_id}/slots/{slot_id}/working-version/discard", response_model=WorkflowV2)
def discard_working_version(
    workflow_id: str,
    slot_id: str,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2:
    try:
        return service.discard_working_version(workflow_id, slot_id)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.get("/{workflow_id}/assets/{asset_id}/owner", response_model=V2AssetOwnerResponse)
def resolve_asset_owner(
    workflow_id: str,
    asset_id: str,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> V2AssetOwnerResponse:
    try:
        return service.resolve_asset_owner(workflow_id, asset_id)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.post("/{workflow_id}/references", response_model=WorkflowV2ReferenceMutationResponse)
def attach_reference(
    workflow_id: str,
    request: WorkflowV2ReferenceAttachRequest,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2ReferenceMutationResponse:
    try:
        return service.attach_reference(workflow_id, request)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.delete(
    "/{workflow_id}/references/{relation_id}", response_model=WorkflowV2ReferenceMutationResponse
)
def remove_reference(
    workflow_id: str,
    relation_id: str,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2ReferenceMutationResponse:
    try:
        return service.remove_reference(workflow_id, relation_id)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.get("/{workflow_id}/runtime", response_model=WorkflowV2RuntimeSnapshot)
def runtime_snapshot(
    workflow_id: str,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2RuntimeSnapshot:
    try:
        return service.runtime_snapshot(workflow_id)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.get("/{workflow_id}/events/stream")
async def stream_events(
    workflow_id: str,
    request: Request,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
    after_seq: int = 0,
    heartbeat_interval_seconds: float = 15.0,
    once: bool = False,
) -> StreamingResponse:
    try:
        service.get_workflow(workflow_id)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc

    async def event_generator():
        cursor = max(after_seq, 0)
        heartbeat_interval = max(heartbeat_interval_seconds, 0.01)
        while True:
            if await request.is_disconnected():
                break
            events = service.list_events(workflow_id, after_seq=cursor).events
            if events:
                for event in events:
                    cursor = event.seq
                    yield _sse_event(event)
                if once:
                    break
                continue
            yield ": heartbeat\n\n"
            if once:
                break
            await asyncio.sleep(heartbeat_interval)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{workflow_id}/events", response_model=WorkflowV2EventListResponse)
def list_events(
    workflow_id: str,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
    after_seq: int = 0,
) -> WorkflowV2EventListResponse:
    try:
        return service.list_events(workflow_id, after_seq=after_seq)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.post(
    "/{workflow_id}/executions/{execution_id}/resume",
    response_model=WorkflowV2RuntimeSnapshot,
)
def resume_execution(
    workflow_id: str,
    execution_id: str,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2RuntimeSnapshot:
    try:
        return service.resume_execution(workflow_id, execution_id)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.get(
    "/{workflow_id}/provider-tasks",
    response_model=V2ProviderTaskListResponse,
)
def list_provider_tasks(
    workflow_id: str,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
    slot_id: str | None = None,
) -> V2ProviderTaskListResponse:
    try:
        return service.list_provider_tasks(workflow_id, slot_id=slot_id)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.get(
    "/{workflow_id}/provider-tasks/{task_id}",
    response_model=V2ProviderTask,
)
def get_provider_task(
    workflow_id: str,
    task_id: str,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> V2ProviderTask:
    try:
        return service.get_provider_task(workflow_id, task_id)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.post(
    "/{workflow_id}/provider-tasks/{task_id}/poll",
    response_model=V2ProviderTaskPollResponse,
)
def poll_provider_task(
    workflow_id: str,
    task_id: str,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> V2ProviderTaskPollResponse:
    try:
        return service.poll_provider_task(workflow_id, task_id)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.post("/{workflow_id}/chat-target", response_model=WorkflowV2ChatTargetResponse)
def chat_target(
    workflow_id: str,
    request: WorkflowV2ChatTargetRequest,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2ChatTargetResponse:
    try:
        return service.chat_target(workflow_id, request)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.post("/{workflow_id}/chat-actions", response_model=WorkflowV2ChatActionResponse)
def chat_action(
    workflow_id: str,
    request: WorkflowV2ChatActionRequest,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2ChatActionResponse:
    try:
        return service.chat_action(workflow_id, request)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.post("/{workflow_id}/free-nodes", response_model=WorkflowV2)
def create_free_node(
    workflow_id: str,
    request: WorkflowV2FreeNodeCreateRequest,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2:
    try:
        return service.create_free_node(workflow_id, request)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.post("/{workflow_id}/free-nodes/{node_id}/generate", response_model=WorkflowV2RunResponse)
def generate_free_node(
    workflow_id: str,
    node_id: str,
    request: WorkflowV2FreeNodeGenerateRequest,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2RunResponse:
    try:
        return service.generate_free_node(workflow_id, node_id, request)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.post(
    "/{workflow_id}/free-nodes/{node_id}/absorb",
    response_model=WorkflowV2FreeNodeAbsorbResponse,
)
def absorb_free_node(
    workflow_id: str,
    node_id: str,
    request: WorkflowV2FreeNodeAbsorbRequest,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2FreeNodeAbsorbResponse:
    try:
        return service.absorb_free_node(workflow_id, node_id, request)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.delete("/{workflow_id}/free-nodes/{node_id}", response_model=WorkflowV2)
def delete_free_node(
    workflow_id: str,
    node_id: str,
    service: Annotated[WorkflowV2Service, Depends(get_workflow_v2_service)],
) -> WorkflowV2:
    try:
        return service.delete_free_node(workflow_id, node_id)
    except WorkflowV2Error as exc:
        raise _workflow_v2_http_error(exc) from exc


@router.post(
    "/{workflow_id}/final-composition/timeline/clips",
    response_model=WorkflowV2TimelineClipMutationResponse,
)
def create_timeline_clip(
    workflow_id: str,
    request: WorkflowV2TimelineClipCreateRequest,
    service: Annotated[
        V2FinalCompositionTimelineService,
        Depends(get_v2_final_timeline_service),
    ],
) -> WorkflowV2TimelineClipMutationResponse:
    try:
        return service.create_compatibility_clip(workflow_id, request)
    except V2FinalCompositionTimelineError as exc:
        raise _workflow_v2_timeline_http_error(exc) from exc


@router.post(
    "/{workflow_id}/final-composition/timeline/sources",
    response_model=WorkflowV2TimelineSourceImportResponse,
)
def import_final_composition_timeline_source(
    workflow_id: str,
    request: WorkflowV2TimelineSourceImportRequest,
    service: Annotated[
        V2FinalCompositionTimelineService,
        Depends(get_v2_final_timeline_service),
    ],
) -> WorkflowV2TimelineSourceImportResponse:
    try:
        return service.import_library_source(workflow_id, request)
    except V2FinalCompositionTimelineError as exc:
        raise _workflow_v2_timeline_http_error(exc) from exc


@router.delete(
    "/{workflow_id}/final-composition/timeline/clips/{clip_id}",
    response_model=WorkflowV2TimelineClipMutationResponse,
)
def delete_timeline_clip(
    workflow_id: str,
    clip_id: str,
    service: Annotated[
        V2FinalCompositionTimelineService,
        Depends(get_v2_final_timeline_service),
    ],
    request: Annotated[WorkflowV2TimelineClipDeleteRequest | None, Body()] = None,
) -> WorkflowV2TimelineClipMutationResponse:
    try:
        return service.delete_compatibility_clip(
            workflow_id,
            clip_id,
            request or WorkflowV2TimelineClipDeleteRequest(),
        )
    except V2FinalCompositionTimelineError as exc:
        raise _workflow_v2_timeline_http_error(exc) from exc


@router.get(
    "/{workflow_id}/final-composition/timeline",
    response_model=WorkflowV2TimelineResponse,
)
def get_final_composition_timeline(
    workflow_id: str,
    service: Annotated[
        V2FinalCompositionTimelineService,
        Depends(get_v2_final_timeline_service),
    ],
) -> WorkflowV2TimelineResponse:
    try:
        return service.get_timeline(workflow_id)
    except V2FinalCompositionTimelineError as exc:
        raise _workflow_v2_timeline_http_error(exc) from exc


@router.patch(
    "/{workflow_id}/final-composition/timeline",
    response_model=WorkflowV2TimelineUpdateResponse,
)
def update_final_composition_timeline(
    workflow_id: str,
    payload: Annotated[dict[str, Any], Body()],
    service: Annotated[
        V2FinalCompositionTimelineService,
        Depends(get_v2_final_timeline_service),
    ],
) -> WorkflowV2TimelineUpdateResponse:
    try:
        request = WorkflowV2TimelineUpdateRequest.model_validate(payload)
        return service.save_timeline(workflow_id, request)
    except ValidationError as exc:
        message = str(exc)
        raise _workflow_v2_timeline_http_error(
            V2FinalCompositionTimelineError(
                (
                    "v2_timeline_track_overlap"
                    if "cannot overlap" in message
                    else "v2_timeline_invalid_clip"
                ),
                message,
                status_code=400,
            )
        ) from exc
    except V2FinalCompositionTimelineError as exc:
        raise _workflow_v2_timeline_http_error(exc) from exc


@router.post(
    "/{workflow_id}/final-composition/render",
    response_model=WorkflowV2TimelineRenderStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def render_final_composition_timeline(
    workflow_id: str,
    request: WorkflowV2TimelineRenderRequest,
    service: Annotated[
        V2FinalCompositionRenderService,
        Depends(get_v2_final_composition_render_service),
    ],
) -> WorkflowV2TimelineRenderStartResponse:
    try:
        return service.start_render(workflow_id, request)
    except V2FinalCompositionTimelineError as exc:
        raise _workflow_v2_timeline_http_error(exc) from exc


@router.get(
    "/{workflow_id}/final-composition/renders/{render_id}",
    response_model=WorkflowV2TimelineRenderStateResponse,
)
def get_final_composition_render(
    workflow_id: str,
    render_id: str,
    service: Annotated[
        V2FinalCompositionRenderService,
        Depends(get_v2_final_composition_render_service),
    ],
) -> WorkflowV2TimelineRenderStateResponse:
    try:
        return service.load_render_state(workflow_id, render_id)
    except V2FinalCompositionTimelineError as exc:
        raise _workflow_v2_timeline_http_error(exc) from exc


@router.post(
    "/{workflow_id}/final-composition/renders/{render_id}/cancel",
    response_model=WorkflowV2TimelineRenderStateResponse,
)
def cancel_final_composition_render(
    workflow_id: str,
    render_id: str,
    service: Annotated[
        V2FinalCompositionRenderService,
        Depends(get_v2_final_composition_render_service),
    ],
) -> WorkflowV2TimelineRenderStateResponse:
    try:
        return service.cancel_render(workflow_id, render_id)
    except V2FinalCompositionTimelineError as exc:
        raise _workflow_v2_timeline_http_error(exc) from exc


def _workflow_v2_timeline_http_error(exc: V2FinalCompositionTimelineError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc), **exc.details},
    )


def _v2_script_http_error(exc: V2ScriptVersionError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


def _workflow_v2_http_error(exc: WorkflowV2Error) -> HTTPException:
    if exc.code == "unsupported_workflow_schema_version":
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        )
    if exc.code in {
        "slot_dependency_not_satisfied",
        "composition_bgm_missing",
        "composition_input_missing",
        "final_composition_not_ready",
        "asset_file_missing",
        "script_version_conflict",
        "script_plan_unavailable",
        "v2_data_boundary_violation",
        "shot_reference_contract_mismatch",
    }:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_workflow_v2_error_detail(exc),
        )
    if exc.code == "provider_task_already_terminal":
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        )
    if exc.code == "clarification_required":
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        )
    if exc.code in {
        "invalid_free_node_absorb_target",
        "asset_slot_incompatible",
        "reference_role_incompatible",
        "absorb_target_incompatible",
        "target_type_not_supported",
        "invalid_locator",
        "v2_planning_constraints_lost",
        "v2_slot_semantic_boundary_failed",
        "v2_visual_style_contract_failed",
        "v2_duplicate_fallback_item",
        "v2_product_reference_binding_failed",
        "v2_generation_integrity_failed",
        "invalid_script_chat_action",
        "invalid_script_document",
        "unknown_script_reference",
        "explicit_constraint_conflict",
        "shot_primary_scene_invalid_owner",
    }:
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_workflow_v2_error_detail(exc),
        )
    if exc.code in {
        "slot_generation_failed",
        "provider_generation_failed",
        "script_writer_unavailable",
        "script_writer_llm_call_failed",
        "script_writer_output_invalid_json",
        "script_writer_output_schema_invalid",
        "script_writer_output_quality_failed",
        "script_writer_failed",
        "script_edit_normalization_failed",
        "expert_brief_planner_unavailable",
        "expert_brief_llm_call_failed",
        "expert_brief_output_invalid_json",
        "expert_brief_output_schema_invalid",
        "expert_brief_output_quality_failed",
        "expert_brief_repair_failed",
        "expert_brief_fallback_failed",
        "v2_intent_fallback_failed",
        "v2_intent_reconciliation_failed",
        "v2_intent_validation_failed",
        "storyboard_detail_unavailable",
        "storyboard_detail_llm_call_failed",
        "storyboard_detail_output_invalid_json",
        "storyboard_detail_output_schema_invalid",
        "storyboard_detail_output_quality_failed",
        "storyboard_detail_repair_failed",
        "v2_storyboard_materialization_failed",
        "v2_storyboard_fallback_failed",
        "v2_storyboard_namespace_violation",
        "composition_ffmpeg_missing",
        "composition_failed",
        "composition_output_missing",
        "provider_output_missing",
        "quality_gate_failed",
    }:
        detail = _workflow_v2_error_detail(exc)
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        )
    if exc.code in {
        "script_persistence_failed",
        "script_version_corrupt",
    }:
        detail = _workflow_v2_error_detail(exc)
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        )
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": exc.code, "message": str(exc)},
    )


_SCRIPT_WORKFLOW_ERROR_CODES = {
    "script_version_conflict",
    "script_plan_unavailable",
    "invalid_script_chat_action",
    "invalid_script_document",
    "unknown_script_reference",
    "explicit_constraint_conflict",
    "script_edit_normalization_failed",
    "script_persistence_failed",
    "script_version_corrupt",
}


def _workflow_v2_error_detail(exc: WorkflowV2Error) -> dict[str, Any]:
    detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
    if not exc.details:
        return detail
    if exc.code in _SCRIPT_WORKFLOW_ERROR_CODES:
        for key in ("stage", "violations"):
            if key in exc.details:
                detail[key] = exc.details[key]
        return detail
    detail["details"] = exc.details
    return detail


def _workflow_v2_asset_http_error(exc: V2WorkflowAssetError) -> HTTPException:
    if exc.code in {
        "asset_slot_incompatible",
        "reference_role_incompatible",
        "absorb_target_incompatible",
        "upload_file_required",
        "upload_file_too_large",
        "unsupported_upload_media_type",
        "remote_reference_registration_not_supported",
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
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": exc.code, "message": str(exc)},
    )


def _workflow_v2_locator_http_error(exc: Exception) -> HTTPException:
    code = str(getattr(exc, "code", "locator_not_found"))
    if code == "invalid_locator":
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": code, "message": str(exc)},
        )
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": code, "message": str(exc)},
    )
