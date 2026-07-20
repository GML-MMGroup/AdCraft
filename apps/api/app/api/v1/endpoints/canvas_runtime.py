from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.dependencies import (
    get_canvas_runtime_event_service,
    get_canvas_runtime_service,
)
from app.schemas.canvas_runtime import (
    CanvasRuntimeEventsResponse,
    CanvasRuntimeSnapshotResponse,
)
from app.services.canvas_runtime_events import (
    CanvasRuntimeError,
    CanvasRuntimeEventService,
    CanvasRuntimeService,
)


router = APIRouter(prefix="/workflows/{workflow_id}/canvas", tags=["canvas-runtime"])


@router.get("/runtime", response_model=CanvasRuntimeSnapshotResponse)
def get_canvas_runtime(
    workflow_id: str,
    service: Annotated[CanvasRuntimeService, Depends(get_canvas_runtime_service)],
) -> CanvasRuntimeSnapshotResponse:
    try:
        return service.snapshot(workflow_id)
    except CanvasRuntimeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/events", response_model=CanvasRuntimeEventsResponse)
def list_canvas_events(
    workflow_id: str,
    service: Annotated[
        CanvasRuntimeEventService,
        Depends(get_canvas_runtime_event_service),
    ],
    after_seq: int = 0,
) -> CanvasRuntimeEventsResponse:
    return service.response(workflow_id, after_seq=after_seq)


@router.get("/events/stream")
def stream_canvas_events(
    workflow_id: str,
    service: Annotated[
        CanvasRuntimeEventService,
        Depends(get_canvas_runtime_event_service),
    ],
    runtime_service: Annotated[
        CanvasRuntimeService,
        Depends(get_canvas_runtime_service),
    ],
    after_seq: int = 0,
) -> StreamingResponse:
    runtime_service.recover(workflow_id)
    return StreamingResponse(
        service.stream_events(workflow_id, after_seq=after_seq),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
