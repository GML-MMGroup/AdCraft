from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings
from app.schemas.workflow_v2_production_acceptance import (
    V2ProductionAcceptanceReport,
    V2ProductionAcceptanceRunRequest,
    V2ProductionAcceptanceRunView,
)
from app.services.v2_production_acceptance import (
    TERMINAL_ACCEPTANCE_STATUSES,
    V2ProductionAcceptanceService,
    V2ProductionAcceptanceServiceError,
)


router = APIRouter(
    prefix="/production-acceptance-runs",
    tags=["v2-production-acceptance"],
)


def get_v2_production_acceptance_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> V2ProductionAcceptanceService:
    return V2ProductionAcceptanceService(settings=settings)


@router.post("", response_model=V2ProductionAcceptanceRunView)
def start_production_acceptance_run(
    request: V2ProductionAcceptanceRunRequest,
    service: Annotated[
        V2ProductionAcceptanceService,
        Depends(get_v2_production_acceptance_service),
    ],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    if not idempotency_key or not idempotency_key.strip():
        raise _http_error(
            V2ProductionAcceptanceServiceError(
                "production_acceptance_idempotency_key_required",
                "Idempotency-Key is required.",
            )
        )
    try:
        result = service.start_run(request, idempotency_key)
    except V2ProductionAcceptanceServiceError as exc:
        raise _http_error(exc) from exc
    response_status = (
        status.HTTP_200_OK
        if result.idempotent_replay and result.lifecycle_status in TERMINAL_ACCEPTANCE_STATUSES
        else status.HTTP_202_ACCEPTED
    )
    return JSONResponse(
        status_code=response_status,
        content=result.model_dump(mode="json"),
    )


@router.get("/{acceptance_run_id}", response_model=V2ProductionAcceptanceRunView)
def get_production_acceptance_run(
    acceptance_run_id: str,
    service: Annotated[
        V2ProductionAcceptanceService,
        Depends(get_v2_production_acceptance_service),
    ],
) -> V2ProductionAcceptanceRunView:
    try:
        return service.get_run(acceptance_run_id)
    except V2ProductionAcceptanceServiceError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{acceptance_run_id}/report",
    response_model=V2ProductionAcceptanceReport,
)
def get_production_acceptance_report(
    acceptance_run_id: str,
    service: Annotated[
        V2ProductionAcceptanceService,
        Depends(get_v2_production_acceptance_service),
    ],
) -> V2ProductionAcceptanceReport:
    try:
        return service.get_report(acceptance_run_id)
    except V2ProductionAcceptanceServiceError as exc:
        raise _http_error(exc) from exc


def _http_error(error: V2ProductionAcceptanceServiceError) -> HTTPException:
    status_by_code = {
        "production_acceptance_idempotency_key_required": status.HTTP_400_BAD_REQUEST,
        "production_acceptance_fixture_not_found": status.HTTP_404_NOT_FOUND,
        "production_acceptance_run_not_found": status.HTTP_404_NOT_FOUND,
        "production_acceptance_idempotency_conflict": status.HTTP_409_CONFLICT,
        "production_acceptance_active_run_exists": status.HTTP_409_CONFLICT,
        "production_acceptance_report_not_ready": status.HTTP_409_CONFLICT,
        "production_acceptance_disabled": status.HTTP_503_SERVICE_UNAVAILABLE,
        "production_acceptance_fixture_invalid": status.HTTP_500_INTERNAL_SERVER_ERROR,
        "production_acceptance_store_failed": status.HTTP_500_INTERNAL_SERVER_ERROR,
        "production_acceptance_report_failed": status.HTTP_500_INTERNAL_SERVER_ERROR,
    }
    detail: dict[str, str] = {"code": error.code, "message": str(error)}
    if error.acceptance_run_id:
        detail["acceptance_run_id"] = error.acceptance_run_id
    return HTTPException(
        status_code=status_by_code.get(error.code, status.HTTP_500_INTERNAL_SERVER_ERROR),
        detail=detail,
    )
