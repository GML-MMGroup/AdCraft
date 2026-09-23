"""Operator-only full Agent call inspection, separate from public chat APIs."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_workflow_model_call_store
from app.api.internal.router import require_agent_internal_auth
from app.schemas.workflow_model_calls import (
    WorkflowModelCallDetailV1,
    WorkflowModelCallListV1,
    WorkflowModelCallReceiptV1,
    WorkflowModelCallWriteV1,
)
from app.services.workflow_model_calls import WorkflowModelCallStore


def _private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/internal/v1",
    dependencies=[Depends(require_agent_internal_auth), Depends(_private_response)],
)


@router.post(
    "/agent-model-calls",
    response_model=WorkflowModelCallReceiptV1,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": WorkflowModelCallWriteV1.model_json_schema()}
            },
        }
    },
)
async def record_model_call(
    request: Request,
    store: WorkflowModelCallStore = Depends(get_workflow_model_call_store),
) -> WorkflowModelCallReceiptV1:
    # Parse explicitly so validation errors never echo private prompt/response data.
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 16 * 1024 * 1024:
            raise HTTPException(413, detail={"code": "agent_model_call_too_large"})
        body.extend(chunk)
    try:
        write = WorkflowModelCallWriteV1.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, detail={"code": "agent_model_call_invalid"}) from None
    return await run_in_threadpool(store.record_for_run, write)


@router.get("/workflows/{workflow_id}/agent-model-calls", response_model=WorkflowModelCallListV1)
def list_model_calls(
    workflow_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    store: WorkflowModelCallStore = Depends(get_workflow_model_call_store),
) -> WorkflowModelCallListV1:
    return store.list(workflow_id, offset=offset, limit=limit)


@router.get(
    "/workflows/{workflow_id}/agent-model-calls/{call_id}", response_model=WorkflowModelCallDetailV1
)
def get_model_call(
    workflow_id: str,
    call_id: str,
    store: WorkflowModelCallStore = Depends(get_workflow_model_call_store),
) -> WorkflowModelCallDetailV1:
    return store.detail(workflow_id, call_id)
