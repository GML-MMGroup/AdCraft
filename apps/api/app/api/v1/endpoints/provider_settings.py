from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.api.dependencies import get_runtime_credential_service
from app.core.config import Settings, get_settings
from app.schemas.provider_settings import (
    ProviderCredentialErrorDetail,
    ProviderCredentialErrorResponse,
    ProviderCredentialStatusResponse,
    ProviderCredentialTestResponse,
    ProviderCredentialUpdateResponse,
    VolcengineCredentialTestRequest,
    VolcengineCredentialUpdateRequest,
)
from app.services.provider_credentials import (
    CredentialSettingsError,
    LocalSettingsAccessPolicy,
    RuntimeCredentialService,
)


class ProviderSettingsRoute(APIRoute):
    """Redact validation input values for secret-bearing settings requests only."""

    def get_route_handler(self):  # type: ignore[no-untyped-def]
        original_handler = super().get_route_handler()

        async def redacting_handler(request: Request) -> JSONResponse:
            try:
                return await original_handler(request)
            except RequestValidationError:
                code = (
                    "credential_test_configuration_invalid"
                    if request.url.path.endswith("/test")
                    else "credential_update_invalid"
                )
                message = (
                    "Credential test request is not valid."
                    if request.url.path.endswith("/test")
                    else "Credential update request is not valid."
                )
                return JSONResponse(
                    status_code=422,
                    content=ProviderCredentialErrorResponse(
                        detail=ProviderCredentialErrorDetail(code=code, message=message)
                    ).model_dump(mode="json"),
                )

        return redacting_handler


router = APIRouter(
    prefix="/settings/providers",
    tags=["provider-settings"],
    route_class=ProviderSettingsRoute,
)


def _ensure_local_settings_access(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    try:
        LocalSettingsAccessPolicy(settings.local_settings_allowed_origins).ensure_allowed(
            client_host=request.client.host if request.client else None,
            origin=request.headers.get("origin"),
        )
    except CredentialSettingsError as error:
        raise _http_error(error) from error


def _http_error(error: CredentialSettingsError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail=ProviderCredentialErrorDetail(code=error.code, message=str(error)).model_dump(),
    )


@router.get(
    "/volcengine",
    response_model=ProviderCredentialStatusResponse,
    responses={
        403: {"model": ProviderCredentialErrorResponse},
        500: {"model": ProviderCredentialErrorResponse},
    },
)
def get_volcengine_credential_status(
    _: Annotated[None, Depends(_ensure_local_settings_access)],
    service: Annotated[RuntimeCredentialService, Depends(get_runtime_credential_service)],
) -> ProviderCredentialStatusResponse:
    try:
        return ProviderCredentialStatusResponse(credentials=service.status("volcengine_ark"))
    except CredentialSettingsError as error:
        raise _http_error(error) from error


@router.put(
    "/volcengine",
    response_model=ProviderCredentialUpdateResponse,
    responses={
        403: {"model": ProviderCredentialErrorResponse},
        409: {"model": ProviderCredentialErrorResponse},
        422: {"model": ProviderCredentialErrorResponse},
        500: {"model": ProviderCredentialErrorResponse},
    },
)
def update_volcengine_credentials(
    payload: VolcengineCredentialUpdateRequest,
    _: Annotated[None, Depends(_ensure_local_settings_access)],
    service: Annotated[RuntimeCredentialService, Depends(get_runtime_credential_service)],
) -> ProviderCredentialUpdateResponse:
    try:
        result = service.update("volcengine_ark", payload.supplied_values())
        return ProviderCredentialUpdateResponse(
            credentials=result.credentials,
            updated_consumers=list(result.updated_consumers),
            applied_at=result.applied_at,
        )
    except CredentialSettingsError as error:
        raise _http_error(error) from error


@router.post(
    "/volcengine/test",
    response_model=ProviderCredentialTestResponse,
    responses={
        403: {"model": ProviderCredentialErrorResponse},
        409: {"model": ProviderCredentialErrorResponse},
        422: {"model": ProviderCredentialErrorResponse},
        503: {"model": ProviderCredentialErrorResponse},
    },
)
def test_volcengine_credential(
    payload: VolcengineCredentialTestRequest,
    _: Annotated[None, Depends(_ensure_local_settings_access)],
    service: Annotated[RuntimeCredentialService, Depends(get_runtime_credential_service)],
) -> ProviderCredentialTestResponse:
    try:
        result = service.test(
            "volcengine_ark",
            payload.consumer,
            payload.api_key.get_secret_value() if payload.api_key is not None else None,
        )
        return ProviderCredentialTestResponse(
            tested_consumer=payload.consumer,
            model_id=result.model_id,
            tested_at=datetime.now(timezone.utc),
        )
    except CredentialSettingsError as error:
        raise _http_error(error) from error
