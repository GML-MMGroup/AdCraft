"""Operator-only full Agent call inspection, separate from public chat APIs."""

from collections.abc import Iterator
from dataclasses import fields

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.internal.router import require_agent_internal_auth
from app.core.config import Settings, get_settings
from app.schemas.workflow_model_calls import (
    WorkflowModelCallDetailV1,
    WorkflowModelCallListV1,
    WorkflowModelCallReceiptV1,
    WorkflowModelCallWriteV1,
)
from app.services.workflow_model_calls import WorkflowModelCallError, WorkflowModelCallStore


def _private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/internal/v1",
    dependencies=[Depends(require_agent_internal_auth), Depends(_private_response)],
)


def _store(settings: Settings = Depends(get_settings)) -> Iterator[WorkflowModelCallStore]:
    secrets = tuple(
        value
        for field in fields(settings)
        if ("api_key" in field.name or "internal_token" in field.name)
        and isinstance(value := getattr(settings, field.name), str)
        and value
    )
    try:
        yield WorkflowModelCallStore(settings.media_data_dir, secrets=secrets)
    except WorkflowModelCallError as error:
        raise HTTPException(
            error.status_code,
            detail={"code": error.code, "message": "Agent model call record is unavailable."},
        ) from error
    except (OSError, ValueError):
        raise HTTPException(
            503,
            detail={
                "code": "agent_model_call_unavailable",
                "message": "Agent model call storage is unavailable.",
            },
        ) from None


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
    store: WorkflowModelCallStore = Depends(_store),
) -> WorkflowModelCallReceiptV1:
    # Parse explicitly so validation errors never echo private prompt/response data.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16 * 1024 * 1024:
            raise HTTPException(413, detail={"code": "agent_model_call_too_large"})
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
    store: WorkflowModelCallStore = Depends(_store),
) -> WorkflowModelCallListV1:
    return store.list(workflow_id, offset=offset, limit=limit)


@router.get(
    "/workflows/{workflow_id}/agent-model-calls/{call_id}", response_model=WorkflowModelCallDetailV1
)
def get_model_call(
    workflow_id: str,
    call_id: str,
    store: WorkflowModelCallStore = Depends(_store),
) -> WorkflowModelCallDetailV1:
    return store.detail(workflow_id, call_id)
