"""V2 HTTP readiness and persistence-error boundaries."""

from __future__ import annotations

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.persistence.errors import V2PersistenceError
from app.schemas.v2_persistence import PersistenceBootstrapFailure, PersistenceBootstrapState

_PAYLOAD_ERROR_CODES = {
    "v2_event_payload_embedded_media",
    "v2_event_payload_absolute_path",
    "v2_event_payload_too_large",
}
_SAFE_STAGES = {"event_import", "event_store", "lock", "payload", "schema"}


def require_v2_persistence(request: Request) -> None:
    """Reject every V2 route until the lifespan has verified persistence."""

    state = getattr(request.app.state, "v2_persistence_state", None)
    if isinstance(state, PersistenceBootstrapState):
        return

    detail: dict[str, str] = {
        "code": "v2_persistence_not_ready",
        "message": "V2 persistence is not ready.",
    }
    if isinstance(state, PersistenceBootstrapFailure) and state.stage in _SAFE_STAGES:
        detail["stage"] = state.stage
    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)


async def v2_persistence_exception_handler(
    _request: Request,
    error: V2PersistenceError,
) -> JSONResponse:
    """Map persistence failures without exposing storage internals to HTTP clients."""

    if error.code in _PAYLOAD_ERROR_CODES:
        response_status = status.HTTP_422_UNPROCESSABLE_ENTITY
        message = "V2 event payload is invalid."
    elif error.code == "v2_event_store_busy":
        response_status = status.HTTP_503_SERVICE_UNAVAILABLE
        message = "V2 event storage is busy."
    else:
        response_status = status.HTTP_503_SERVICE_UNAVAILABLE
        message = "V2 persistence is unavailable."

    detail: dict[str, str] = {"code": error.code, "message": message}
    if error.stage in _SAFE_STAGES:
        detail["stage"] = error.stage
    return JSONResponse(status_code=response_status, content={"detail": detail})
