"""V2 Project catalog and ownership endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status

from app.api.v2.etag import V2PreconditionError, parse_project_if_match, project_etag, workflow_etag
from app.core.config import Settings, get_settings
from app.persistence.errors import V2PersistenceError
from app.schemas.workflow_v2 import WorkflowV2
from app.schemas.workflow_v2_projects import (
    ProjectV2,
    ProjectV2ListResponse,
    ProjectV2UpdateRequest,
)
from app.services.v2_projects import V2ProjectService


router = APIRouter(prefix="/projects", tags=["v2-projects"])


def get_v2_project_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[V2ProjectService]:
    service = V2ProjectService(settings.media_data_dir)
    try:
        yield service
    finally:
        service.close()


@router.get("", response_model=ProjectV2ListResponse)
def list_projects(
    service: Annotated[V2ProjectService, Depends(get_v2_project_service)],
    project_status: Annotated[
        Literal["active", "archived", "trashed"], Query(alias="status")
    ] = "active",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> ProjectV2ListResponse:
    try:
        return service.list_projects(status=project_status, limit=limit, cursor=cursor)
    except V2PersistenceError as error:
        raise _project_http_error(error) from error


@router.get("/{project_id}", response_model=ProjectV2)
def get_project(
    project_id: str,
    response: Response,
    service: Annotated[V2ProjectService, Depends(get_v2_project_service)],
) -> ProjectV2:
    try:
        project = service.get_project(project_id)
    except V2PersistenceError as error:
        raise _project_http_error(error) from error
    response.headers["ETag"] = project_etag(project_id, project.project_version)
    return project


@router.get("/{project_id}/workflow", response_model=WorkflowV2)
def get_project_workflow(
    project_id: str,
    response: Response,
    service: Annotated[V2ProjectService, Depends(get_v2_project_service)],
) -> WorkflowV2:
    try:
        workflow = service.get_workflow(project_id)
    except V2PersistenceError as error:
        raise _project_http_error(error) from error
    if workflow.state_version is None:
        raise HTTPException(status_code=503, detail={"code": "workflow_state_unavailable"})
    response.headers["ETag"] = workflow_etag(workflow.workflow_id, workflow.state_version)
    return workflow


@router.patch("/{project_id}", response_model=ProjectV2)
def update_project(
    project_id: str,
    request: ProjectV2UpdateRequest,
    response: Response,
    service: Annotated[V2ProjectService, Depends(get_v2_project_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ProjectV2:
    changes = request.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=422,
            detail={"code": "project_update_empty", "message": "Project update is empty."},
        )
    expected_version = _project_precondition(if_match, project_id)
    try:
        project = service.update_project(
            project_id,
            expected_version=expected_version,
            changes=changes,
        )
    except V2PersistenceError as error:
        raise _project_http_error(error) from error
    response.headers["ETag"] = project_etag(project_id, project.project_version)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def trash_project(
    project_id: str,
    response: Response,
    service: Annotated[V2ProjectService, Depends(get_v2_project_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> None:
    try:
        project = service.trash_project(
            project_id,
            expected_version=_project_precondition(if_match, project_id),
        )
    except V2PersistenceError as error:
        raise _project_http_error(error) from error
    response.headers["ETag"] = project_etag(project_id, project.project_version)


@router.post("/{project_id}/restore", response_model=ProjectV2)
def restore_project(
    project_id: str,
    response: Response,
    service: Annotated[V2ProjectService, Depends(get_v2_project_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ProjectV2:
    try:
        project = service.restore_project(
            project_id,
            expected_version=_project_precondition(if_match, project_id),
        )
    except V2PersistenceError as error:
        raise _project_http_error(error) from error
    response.headers["ETag"] = project_etag(project_id, project.project_version)
    return project


def _project_precondition(value: str | None, project_id: str) -> int:
    try:
        return parse_project_if_match(value, project_id)
    except V2PreconditionError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": str(error)},
        ) from error


def _project_http_error(error: V2PersistenceError) -> HTTPException:
    status_code = {
        "project_not_found": 404,
        "project_not_trashed": 409,
        "project_state_conflict": 412,
        "project_cursor_invalid": 422,
        "project_page_invalid": 422,
        "project_update_invalid": 422,
    }.get(error.code, 503)
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": str(error)},
    )
