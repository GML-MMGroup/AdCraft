"""Trusted local read-only Agent model-call history endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.api.dependencies import get_workflow_model_call_store
from app.core.config import Settings, get_settings
from app.schemas.workflow_model_calls import (
    WorkflowModelCallDetailV1,
    WorkflowModelCallListV1,
)
from app.services.provider_credentials import CredentialSettingsError, LocalSettingsAccessPolicy
from app.services.workflow_model_calls import WorkflowModelCallError, WorkflowModelCallStore


router = APIRouter(tags=["v2-agent-model-calls"])


def _private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _ensure_local_read_access(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    try:
        LocalSettingsAccessPolicy(settings.local_settings_allowed_origins).ensure_allowed(
            client_host=request.client.host if request.client else None,
            origin=request.headers.get("origin"),
        )
    except CredentialSettingsError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": str(error)},
        ) from error


def _read_error(error: WorkflowModelCallError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": "Agent model call record is unavailable."},
    )


@router.get(
    "/workflows/{workflow_id}/agent-model-calls",
    response_model=WorkflowModelCallListV1,
    dependencies=[Depends(_ensure_local_read_access), Depends(_private_response)],
)
def list_model_calls(
    workflow_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    store: WorkflowModelCallStore = Depends(get_workflow_model_call_store),
) -> WorkflowModelCallListV1:
    try:
        return store.list(workflow_id, offset=offset, limit=limit)
    except WorkflowModelCallError as error:
        raise _read_error(error) from error


@router.get(
    "/workflows/{workflow_id}/agent-model-calls/{call_id}",
    response_model=WorkflowModelCallDetailV1,
    dependencies=[Depends(_ensure_local_read_access), Depends(_private_response)],
)
def get_model_call(
    workflow_id: str,
    call_id: str,
    store: WorkflowModelCallStore = Depends(get_workflow_model_call_store),
) -> WorkflowModelCallDetailV1:
    try:
        return store.detail(workflow_id, call_id)
    except WorkflowModelCallError as error:
        raise _read_error(error) from error
