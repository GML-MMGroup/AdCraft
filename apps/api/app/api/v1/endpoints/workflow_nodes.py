import json
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.api.dependencies import (
    get_canvas_runtime_event_service,
    get_final_composition_timeline_service,
    get_workflow_canvas_execution_service,
    get_workflow_item_prompt_service,
    get_workflow_local_revision_service,
    get_workflow_node_input_resolver,
    get_workflow_node_execution_service,
    get_workflow_quality_review_service,
    get_workflow_working_version_service,
)
from app.core.config import Settings, get_settings
from app.schemas.final_composition import (
    FinalCompositionRenderRequest,
    FinalCompositionRenderResponse,
    FinalCompositionTimelineResponse,
    FinalCompositionTimelineSaveRequest,
)
from app.schemas.quality_review import WorkflowQualityReviewResponse
from app.schemas.workflow_nodes import (
    ResolvedNodeInputsResponse,
    WorkflowNodeCatalogResponse,
    WorkflowNodeListResponse,
    WorkflowNodeRunRequest,
    WorkflowNodeRunResponse,
    WorkflowRunRequest,
    WorkflowRunResponse,
)
from app.schemas.workflow_item_prompts import (
    WorkflowItemPromptUpdateRequest,
    WorkflowItemPromptUpdateResponse,
)
from app.schemas.workflow_revisions import (
    WorkflowAssetHistoryResponse,
    WorkflowRevisionAcceptRequest,
    WorkflowRevisionListResponse,
    WorkflowRevisionRejectRequest,
    WorkflowRevisionRequest,
    WorkflowRevisionState,
)
from app.schemas.workflow_working_versions import (
    WorkflowAddItemRequest,
    WorkflowAssetMutationResponse,
    WorkflowAssetPromptUpdateRequest,
    WorkflowAssetRegenerateRequest,
    WorkflowAssetSlotHistoryResponse,
    WorkflowAssetUseCurrentVersionRequest,
    WorkflowBatchUseCurrentVersionsRequest,
    WorkflowBatchUseCurrentVersionsResponse,
    WorkflowItemMutationResponse,
    WorkflowItemRegenerateRequest,
    WorkflowShotVideoBatchResponse,
    WorkflowShotVideoGenerateRequest,
    WorkflowUseCurrentVersionRequest,
    WorkflowUseShotVideosForCompositionRequest,
)
from app.schemas.workflow_executions import (
    WorkflowExecutionEventsResponse,
    WorkflowExecutionStateResponse,
)
from app.services.workflow_executions import WorkflowExecutionError
from app.services.asset_library import AssetLibraryError
from app.services.final_composition_timeline import (
    FinalCompositionTimelineError,
    FinalCompositionTimelineService,
)
from app.services.workflow_input_resolver import (
    WorkflowInputResolutionError,
    WorkflowNodeInputResolver,
)
from app.services.workflow_item_prompts import WorkflowItemPromptError, WorkflowItemPromptService
from app.services.workflow_nodes import (
    WorkflowNodeExecutionError,
    WorkflowNodeExecutionService,
    WorkflowNodeInputError,
)
from app.services.workflow_local_revisions import (
    WorkflowLocalRevisionError,
    WorkflowLocalRevisionService,
)
from app.services.workflow_node_identity import WorkflowNodeIdentityError
from app.services.workflow_quality_review import (
    WorkflowQualityReviewError,
    WorkflowQualityReviewService,
)
from app.services.workflow_working_versions import (
    WorkflowWorkingVersionError,
    WorkflowWorkingVersionService,
)
from app.services.workflow_run import WorkflowCanvasExecutionService
from app.services.workflow_run_response_builder import build_workflow_run_response
from app.services.canvas_runtime_events import CanvasRuntimeEventService
from app.services.workflow_v2 import workflow_v2_path

router = APIRouter(tags=["workflow-nodes"])


def _node_run_output_status(result: WorkflowNodeRunResponse) -> str | None:
    output_status = result.output.get("status")
    return str(output_status) if output_status not in (None, "") else result.status


def _node_run_waiting_reason(result: WorkflowNodeRunResponse) -> str | None:
    if result.status != "waiting":
        return None
    output_status = _node_run_output_status(result)
    if output_status not in (None, ""):
        return str(output_status)
    return "node_run_waiting"


def _is_v2_workflow_id(settings: Settings, workflow_id: str | None) -> bool:
    if not workflow_id:
        return False
    path = workflow_v2_path(settings.media_data_dir, workflow_id)
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return payload.get("workflow_schema_version") == 2


def _output_dict(result: WorkflowNodeRunResponse, key: str) -> dict[str, Any]:
    value = result.output.get(key)
    return value if isinstance(value, dict) else {}


def _append_node_run_debug_events(
    canvas_events: CanvasRuntimeEventService,
    workflow_id: str,
    result: WorkflowNodeRunResponse,
) -> None:
    provider_strategy = _output_dict(result, "provider_strategy")
    if provider_strategy:
        canvas_events.append_provider_strategy_updated(
            workflow_id,
            execution_id=None,
            node_id=result.node_id,
            node_type=result.node_type,
            node_run_id=result.node_run_id,
            provider_strategy=provider_strategy,
        )
    reference_policy = _output_dict(result, "reference_policy")
    if reference_policy:
        canvas_events.append_reference_policy_updated(
            workflow_id,
            execution_id=None,
            node_id=result.node_id,
            node_type=result.node_type,
            node_run_id=result.node_run_id,
            reference_policy=reference_policy,
        )
    asset_flow_debug = _output_dict(result, "asset_flow_debug")
    if asset_flow_debug:
        canvas_events.append_asset_flow_debug_updated(
            workflow_id,
            execution_id=None,
            node_id=result.node_id,
            node_type=result.node_type,
            node_run_id=result.node_run_id,
            asset_flow_debug=asset_flow_debug,
        )


def _append_failed_node_run_event(
    canvas_events: CanvasRuntimeEventService,
    workflow_id: str | None,
    node_id: str | None,
    node_type: str | None,
    error: str,
) -> None:
    if not workflow_id or not node_id or not node_type:
        return
    canvas_events.append_node_status_changed(
        workflow_id,
        execution_id=None,
        node_id=node_id,
        node_type=node_type,
        status="failed",
        previous_status="running",
        error=error,
    )


@router.get("/workflow-nodes/catalog", response_model=WorkflowNodeCatalogResponse)
def workflow_node_catalog(
    service: Annotated[WorkflowNodeExecutionService, Depends(get_workflow_node_execution_service)],
) -> WorkflowNodeCatalogResponse:
    return service.catalog()


@router.post("/workflow-nodes/run", response_model=WorkflowNodeRunResponse)
def run_workflow_node(
    request: WorkflowNodeRunRequest,
    service: Annotated[WorkflowNodeExecutionService, Depends(get_workflow_node_execution_service)],
    canvas_events: Annotated[
        CanvasRuntimeEventService,
        Depends(get_canvas_runtime_event_service),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> WorkflowNodeRunResponse:
    if _is_v2_workflow_id(settings, request.workflow_id):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "unsupported_workflow_schema_version",
                "message": "Use /api/v2 for workflow_schema_version=2 workflows.",
            },
        )
    event_workflow_id = request.workflow_id
    event_node_id = request.node_id or request.node_type
    event_node_type = request.node_type or request.node_id
    if event_workflow_id and event_node_id and event_node_type:
        canvas_events.append_node_status_changed(
            event_workflow_id,
            execution_id=None,
            node_id=event_node_id,
            node_type=event_node_type,
            status="running",
        )
    try:
        result = service.run(request)
        if event_workflow_id:
            canvas_events.append_node_status_changed(
                event_workflow_id,
                execution_id=None,
                node_id=result.node_id,
                node_type=result.node_type,
                status=result.status,
                previous_status="running",
                error=result.error,
                waiting_reason=_node_run_waiting_reason(result),
                node_run_id=result.node_run_id,
                output_status=_node_run_output_status(result),
                has_active_output=result.has_active_output,
                failure_stage=result.output.get("failure_stage"),
                user_explainable_reason=result.output.get("user_explainable_reason"),
                asset_flow_debug=_output_dict(result, "asset_flow_debug"),
            )
            canvas_events.append_node_output_updated(
                event_workflow_id,
                execution_id=None,
                node_id=result.node_id,
                node_type=result.node_type,
                node_run_id=result.node_run_id,
                output_status=_node_run_output_status(result),
            )
            if result.output_assets:
                canvas_events.append_node_assets_updated(
                    event_workflow_id,
                    execution_id=None,
                    node_id=result.node_id,
                    node_type=result.node_type,
                    node_run_id=result.node_run_id,
                )
            _append_node_run_debug_events(canvas_events, event_workflow_id, result)
            if result.affected_downstream_nodes:
                canvas_events.append_event(
                    event_workflow_id,
                    "resolved_inputs_updated",
                    node_id=result.node_id,
                    node_type=result.node_type,
                    resource_type="resolved_inputs",
                    resource_id=result.node_id,
                    payload={
                        "source_node_id": result.node_id,
                        "affected_node_ids": result.affected_downstream_nodes,
                        "refresh": ["resolved_inputs"],
                    },
                )
        return result
    except AssetLibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    except WorkflowNodeIdentityError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except WorkflowNodeInputError as exc:
        _append_failed_node_run_event(
            canvas_events,
            event_workflow_id,
            event_node_id,
            event_node_type,
            str(exc),
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except WorkflowNodeExecutionError as exc:
        _append_failed_node_run_event(
            canvas_events,
            event_workflow_id,
            event_node_id,
            event_node_type,
            str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.post("/workflows/{workflow_id}/run", response_model=WorkflowRunResponse)
def run_workflow_canvas(
    workflow_id: str,
    request: WorkflowRunRequest,
    background_tasks: BackgroundTasks,
    service: Annotated[
        WorkflowCanvasExecutionService,
        Depends(get_workflow_canvas_execution_service),
    ],
) -> WorkflowRunResponse:
    try:
        execution = service.start_execution(workflow_id, request)
        background_tasks.add_task(service.run_execution, workflow_id, execution.execution_id)
        return build_workflow_run_response(
            workflow_id=workflow_id,
            execution_id=execution.execution_id,
            mode=execution.mode,
            status=execution.status,
            frontier_node_id=execution.frontier_node_id,
            selected_node_ids=execution.selected_node_ids,
            queued_node_ids=execution.queued_node_ids,
            running_node_ids=execution.running_node_ids,
            waiting_node_ids=execution.waiting_node_ids,
            completed_node_ids=execution.completed_node_ids,
            skipped_node_ids=execution.skipped_node_ids,
            failed_node_ids=execution.failed_node_ids,
            executed_node_ids=[],
            execution=execution,
        )
    except AssetLibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    except WorkflowExecutionError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except WorkflowNodeInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.get(
    "/workflows/{workflow_id}/final-composition/timeline",
    response_model=FinalCompositionTimelineResponse,
)
def get_final_composition_timeline(
    workflow_id: str,
    service: Annotated[
        FinalCompositionTimelineService,
        Depends(get_final_composition_timeline_service),
    ],
) -> FinalCompositionTimelineResponse:
    try:
        return service.get_timeline(workflow_id)
    except FinalCompositionTimelineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.put(
    "/workflows/{workflow_id}/final-composition/timeline",
    response_model=FinalCompositionTimelineResponse,
)
def save_final_composition_timeline(
    workflow_id: str,
    request: FinalCompositionTimelineSaveRequest,
    service: Annotated[
        FinalCompositionTimelineService,
        Depends(get_final_composition_timeline_service),
    ],
) -> FinalCompositionTimelineResponse:
    try:
        return service.save_timeline(workflow_id, request)
    except FinalCompositionTimelineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/workflows/{workflow_id}/final-composition/render",
    response_model=FinalCompositionRenderResponse,
)
def render_final_composition_timeline(
    workflow_id: str,
    request: FinalCompositionRenderRequest,
    service: Annotated[
        FinalCompositionTimelineService,
        Depends(get_final_composition_timeline_service),
    ],
) -> FinalCompositionRenderResponse:
    try:
        return service.render_timeline(workflow_id, request)
    except FinalCompositionTimelineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get(
    "/workflows/{workflow_id}/executions/{execution_id}",
    response_model=WorkflowExecutionStateResponse,
)
def get_workflow_execution(
    workflow_id: str,
    execution_id: str,
    service: Annotated[
        WorkflowCanvasExecutionService,
        Depends(get_workflow_canvas_execution_service),
    ],
) -> WorkflowExecutionStateResponse:
    try:
        execution = service.get_execution(workflow_id, execution_id)
    except WorkflowExecutionError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return WorkflowExecutionStateResponse(
        workflow_id=workflow_id,
        execution_id=execution_id,
        status=execution.status,
        mode=execution.mode,
        execution=execution,
    )


@router.get(
    "/workflows/{workflow_id}/executions/{execution_id}/events",
    response_model=WorkflowExecutionEventsResponse,
)
def list_workflow_execution_events(
    workflow_id: str,
    execution_id: str,
    service: Annotated[
        WorkflowCanvasExecutionService,
        Depends(get_workflow_canvas_execution_service),
    ],
    after_seq: int = 0,
) -> WorkflowExecutionEventsResponse:
    try:
        events = service.list_execution_events(
            workflow_id,
            execution_id,
            after_seq=after_seq,
        )
    except WorkflowExecutionError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return WorkflowExecutionEventsResponse(
        workflow_id=workflow_id,
        execution_id=execution_id,
        events=events,
    )


@router.get("/workflows/{workflow_id}/nodes", response_model=WorkflowNodeListResponse)
def list_workflow_node_runs(
    workflow_id: str,
    service: Annotated[WorkflowNodeExecutionService, Depends(get_workflow_node_execution_service)],
) -> WorkflowNodeListResponse:
    return service.list_nodes(workflow_id)


@router.post(
    "/workflows/{workflow_id}/nodes/{node_id}/revisions",
    response_model=WorkflowRevisionState,
)
def create_workflow_node_revision(
    workflow_id: str,
    node_id: str,
    request: WorkflowRevisionRequest,
    service: Annotated[
        WorkflowLocalRevisionService,
        Depends(get_workflow_local_revision_service),
    ],
) -> WorkflowRevisionState:
    try:
        return service.create_revision(workflow_id, node_id, request)
    except WorkflowNodeIdentityError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except WorkflowLocalRevisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get(
    "/workflows/{workflow_id}/nodes/{node_id}/revisions",
    response_model=WorkflowRevisionListResponse,
)
def list_workflow_node_revisions(
    workflow_id: str,
    node_id: str,
    service: Annotated[
        WorkflowLocalRevisionService,
        Depends(get_workflow_local_revision_service),
    ],
) -> WorkflowRevisionListResponse:
    return service.list_revisions(workflow_id, node_id)


@router.get(
    "/workflows/{workflow_id}/nodes/{node_id}/revisions/{revision_id}",
    response_model=WorkflowRevisionState,
)
def get_workflow_node_revision(
    workflow_id: str,
    node_id: str,
    revision_id: str,
    service: Annotated[
        WorkflowLocalRevisionService,
        Depends(get_workflow_local_revision_service),
    ],
) -> WorkflowRevisionState:
    try:
        return service.get_revision(workflow_id, node_id, revision_id)
    except WorkflowLocalRevisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/workflows/{workflow_id}/nodes/{node_id}/revisions/{revision_id}/accept",
    response_model=WorkflowRevisionState,
)
def accept_workflow_node_revision(
    workflow_id: str,
    node_id: str,
    revision_id: str,
    request: WorkflowRevisionAcceptRequest,
    service: Annotated[
        WorkflowLocalRevisionService,
        Depends(get_workflow_local_revision_service),
    ],
) -> WorkflowRevisionState:
    try:
        return service.accept_revision(workflow_id, node_id, revision_id, request)
    except WorkflowNodeIdentityError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except WorkflowLocalRevisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/workflows/{workflow_id}/nodes/{node_id}/revisions/{revision_id}/reject",
    response_model=WorkflowRevisionState,
)
def reject_workflow_node_revision(
    workflow_id: str,
    node_id: str,
    revision_id: str,
    request: WorkflowRevisionRejectRequest,
    service: Annotated[
        WorkflowLocalRevisionService,
        Depends(get_workflow_local_revision_service),
    ],
) -> WorkflowRevisionState:
    try:
        return service.reject_revision(workflow_id, node_id, revision_id, request)
    except WorkflowNodeIdentityError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except WorkflowLocalRevisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get(
    "/workflows/{workflow_id}/nodes/{node_id}/assets/history",
    response_model=WorkflowAssetHistoryResponse,
)
def get_workflow_node_asset_history(
    workflow_id: str,
    node_id: str,
    entity_id: str,
    semantic_type: str,
    service: Annotated[
        WorkflowLocalRevisionService,
        Depends(get_workflow_local_revision_service),
    ],
) -> WorkflowAssetHistoryResponse:
    try:
        return service.asset_history(
            workflow_id,
            node_id,
            entity_id=entity_id,
            semantic_type=semantic_type,
        )
    except WorkflowLocalRevisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/workflows/{workflow_id}/nodes/{node_id}/quality-review",
    response_model=WorkflowQualityReviewResponse,
)
def review_workflow_node_quality(
    workflow_id: str,
    node_id: str,
    service: Annotated[
        WorkflowQualityReviewService,
        Depends(get_workflow_quality_review_service),
    ],
) -> WorkflowQualityReviewResponse:
    try:
        return service.review_existing_node(workflow_id, node_id)
    except WorkflowNodeIdentityError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except WorkflowQualityReviewError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/workflows/{workflow_id}/nodes/{node_id}/resolved-inputs",
    response_model=ResolvedNodeInputsResponse,
)
def resolve_workflow_node_inputs(
    workflow_id: str,
    node_id: str,
    service: Annotated[
        WorkflowNodeInputResolver,
        Depends(get_workflow_node_input_resolver),
    ],
) -> ResolvedNodeInputsResponse:
    try:
        return service.resolve_node_inputs(workflow_id, node_id)
    except WorkflowInputResolutionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch(
    "/workflows/{workflow_id}/nodes/{node_id}/items/{item_id}/prompt",
    response_model=WorkflowItemPromptUpdateResponse,
)
def update_workflow_node_item_prompt(
    workflow_id: str,
    node_id: str,
    item_id: str,
    request: WorkflowItemPromptUpdateRequest,
    service: Annotated[
        WorkflowItemPromptService,
        Depends(get_workflow_item_prompt_service),
    ],
) -> WorkflowItemPromptUpdateResponse:
    try:
        return service.update_item_prompt(
            workflow_id=workflow_id,
            node_id=node_id,
            item_id=item_id,
            request=request,
        )
    except WorkflowItemPromptError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/workflows/{workflow_id}/nodes/{node_id}/items",
    response_model=WorkflowItemMutationResponse,
)
def add_workflow_node_item(
    workflow_id: str,
    node_id: str,
    request: WorkflowAddItemRequest,
    service: Annotated[
        WorkflowWorkingVersionService,
        Depends(get_workflow_working_version_service),
    ],
) -> WorkflowItemMutationResponse:
    try:
        return service.add_item(workflow_id, node_id, request)
    except WorkflowWorkingVersionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.patch(
    "/workflows/{workflow_id}/nodes/{node_id}/items/{item_id}/assets/{asset_id}/prompt",
    response_model=WorkflowAssetMutationResponse,
)
def update_workflow_node_item_asset_prompt(
    workflow_id: str,
    node_id: str,
    item_id: str,
    asset_id: str,
    request: WorkflowAssetPromptUpdateRequest,
    service: Annotated[
        WorkflowWorkingVersionService,
        Depends(get_workflow_working_version_service),
    ],
) -> WorkflowAssetMutationResponse:
    try:
        return service.update_asset_prompt(workflow_id, node_id, item_id, asset_id, request)
    except WorkflowWorkingVersionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/workflows/{workflow_id}/nodes/{node_id}/items/{item_id}/assets/{asset_id}/regenerate",
    response_model=WorkflowAssetMutationResponse,
)
def regenerate_workflow_node_item_asset(
    workflow_id: str,
    node_id: str,
    item_id: str,
    asset_id: str,
    request: WorkflowAssetRegenerateRequest,
    service: Annotated[
        WorkflowWorkingVersionService,
        Depends(get_workflow_working_version_service),
    ],
) -> WorkflowAssetMutationResponse:
    try:
        return service.regenerate_asset(workflow_id, node_id, item_id, asset_id, request)
    except WorkflowWorkingVersionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/workflows/{workflow_id}/nodes/{node_id}/items/{item_id}/assets/{asset_id}/use-current-version",
    response_model=WorkflowAssetMutationResponse,
)
def use_workflow_node_item_asset_current_version(
    workflow_id: str,
    node_id: str,
    item_id: str,
    asset_id: str,
    request: WorkflowAssetUseCurrentVersionRequest,
    service: Annotated[
        WorkflowWorkingVersionService,
        Depends(get_workflow_working_version_service),
    ],
) -> WorkflowAssetMutationResponse:
    try:
        return service.use_current_asset_version(workflow_id, node_id, item_id, asset_id, request)
    except WorkflowWorkingVersionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get(
    "/workflows/{workflow_id}/nodes/{node_id}/items/{item_id}/assets/{asset_id}/history",
    response_model=WorkflowAssetSlotHistoryResponse,
)
def get_workflow_node_item_asset_history(
    workflow_id: str,
    node_id: str,
    item_id: str,
    asset_id: str,
    service: Annotated[
        WorkflowWorkingVersionService,
        Depends(get_workflow_working_version_service),
    ],
) -> WorkflowAssetSlotHistoryResponse:
    try:
        return service.asset_slot_history(workflow_id, node_id, item_id, asset_id)
    except WorkflowWorkingVersionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/workflows/{workflow_id}/nodes/{node_id}/items/{item_id}/regenerate",
    response_model=WorkflowItemMutationResponse,
)
def regenerate_workflow_node_item(
    workflow_id: str,
    node_id: str,
    item_id: str,
    request: WorkflowItemRegenerateRequest,
    service: Annotated[
        WorkflowWorkingVersionService,
        Depends(get_workflow_working_version_service),
    ],
) -> WorkflowItemMutationResponse:
    try:
        return service.regenerate_item(workflow_id, node_id, item_id, request)
    except WorkflowWorkingVersionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.delete(
    "/workflows/{workflow_id}/nodes/{node_id}/items/{item_id}",
    response_model=WorkflowItemMutationResponse,
)
def remove_workflow_node_item(
    workflow_id: str,
    node_id: str,
    item_id: str,
    service: Annotated[
        WorkflowWorkingVersionService,
        Depends(get_workflow_working_version_service),
    ],
) -> WorkflowItemMutationResponse:
    try:
        return service.remove_item(workflow_id, node_id, item_id)
    except WorkflowWorkingVersionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/workflows/{workflow_id}/nodes/{node_id}/items/{item_id}/use-current-version",
    response_model=WorkflowItemMutationResponse,
)
def use_workflow_node_item_current_version(
    workflow_id: str,
    node_id: str,
    item_id: str,
    request: WorkflowUseCurrentVersionRequest,
    service: Annotated[
        WorkflowWorkingVersionService,
        Depends(get_workflow_working_version_service),
    ],
) -> WorkflowItemMutationResponse:
    try:
        return service.use_current_version(workflow_id, node_id, item_id, request)
    except WorkflowWorkingVersionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/workflows/{workflow_id}/nodes/{node_id}/items/batch-use-current-versions",
    response_model=WorkflowBatchUseCurrentVersionsResponse,
)
def batch_use_workflow_node_item_current_versions(
    workflow_id: str,
    node_id: str,
    request: WorkflowBatchUseCurrentVersionsRequest,
    service: Annotated[
        WorkflowWorkingVersionService,
        Depends(get_workflow_working_version_service),
    ],
) -> WorkflowBatchUseCurrentVersionsResponse:
    try:
        return service.batch_use_current_versions(workflow_id, node_id, request)
    except WorkflowWorkingVersionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/workflows/{workflow_id}/storyboard/shots/{shot_id}/videos/generate",
    response_model=WorkflowItemMutationResponse,
)
def generate_storyboard_shot_video(
    workflow_id: str,
    shot_id: str,
    request: WorkflowShotVideoGenerateRequest,
    service: Annotated[
        WorkflowWorkingVersionService,
        Depends(get_workflow_working_version_service),
    ],
) -> WorkflowItemMutationResponse:
    try:
        return service.generate_shot_video(workflow_id, shot_id, request)
    except WorkflowWorkingVersionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/workflows/{workflow_id}/storyboard/videos/generate-missing-stale",
    response_model=WorkflowShotVideoBatchResponse,
)
def generate_missing_stale_storyboard_shot_videos(
    workflow_id: str,
    service: Annotated[
        WorkflowWorkingVersionService,
        Depends(get_workflow_working_version_service),
    ],
) -> WorkflowShotVideoBatchResponse:
    try:
        return service.generate_missing_stale_shot_videos(workflow_id)
    except WorkflowWorkingVersionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/workflows/{workflow_id}/storyboard/videos/regenerate-all-selected",
    response_model=WorkflowShotVideoBatchResponse,
)
def regenerate_all_selected_storyboard_shot_videos(
    workflow_id: str,
    service: Annotated[
        WorkflowWorkingVersionService,
        Depends(get_workflow_working_version_service),
    ],
) -> WorkflowShotVideoBatchResponse:
    try:
        return service.regenerate_all_selected_shot_videos(workflow_id)
    except WorkflowWorkingVersionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/workflows/{workflow_id}/storyboard/videos/use-current-for-composition",
    response_model=WorkflowBatchUseCurrentVersionsResponse,
)
def use_storyboard_shot_videos_for_composition(
    workflow_id: str,
    request: WorkflowUseShotVideosForCompositionRequest,
    service: Annotated[
        WorkflowWorkingVersionService,
        Depends(get_workflow_working_version_service),
    ],
) -> WorkflowBatchUseCurrentVersionsResponse:
    try:
        return service.use_current_shot_videos_for_composition(workflow_id, request)
    except WorkflowWorkingVersionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/workflows/{workflow_id}/nodes/{node_id}", response_model=WorkflowNodeRunResponse)
def get_latest_workflow_node_run(
    workflow_id: str,
    node_id: str,
    service: Annotated[WorkflowNodeExecutionService, Depends(get_workflow_node_execution_service)],
) -> WorkflowNodeRunResponse:
    try:
        return service.get_latest_node(workflow_id, node_id)
    except WorkflowNodeInputError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
