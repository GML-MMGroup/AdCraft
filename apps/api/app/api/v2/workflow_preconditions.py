"""Temporary backend-first precondition boundary for Workflow authoring routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.api.v2.etag import (
    V2PreconditionError,
    parse_workflow_if_match,
    semantic_workflow_mutation_id,
)
from app.core.config import Settings, get_settings
from app.persistence.errors import V2PersistenceError
from app.services.v2_workflow_authoring import create_workflow_authoring_runtime


def validate_workflow_if_match(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Validate supplied Workflow ETags while missing-header compatibility is active."""

    workflow_id = semantic_workflow_mutation_id(request.method, request.url.path)
    if workflow_id is None:
        return
    try:
        expected = parse_workflow_if_match(
            request.headers.get("If-Match"),
            workflow_id,
            required=settings.v2_require_authoring_if_match,
        )
    except V2PreconditionError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": str(error)},
        ) from error
    if expected is None:
        return
    runtime = create_workflow_authoring_runtime(settings.media_data_dir)
    try:
        current = runtime.repository.load_current(workflow_id)
    except V2PersistenceError as error:
        if error.code == "workflow_not_found":
            return
        raise HTTPException(
            status_code=503,
            detail={"code": error.code, "message": "V2 persistence is unavailable."},
        ) from error
    finally:
        runtime.database.dispose()
    if current.state_version != expected:
        raise HTTPException(
            status_code=412,
            detail={
                "code": "workflow_state_conflict",
                "message": "Workflow state has changed.",
                "current_state_version": current.state_version,
            },
        )
