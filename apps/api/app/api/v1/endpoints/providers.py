"""Canonical local provider connection configuration endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import (
    get_provider_connection_service,
    get_provider_model_catalog_service,
)
from app.api.v1.endpoints.provider_settings import (
    ProviderSettingsRoute,
    _ensure_local_settings_access,
)
from app.core.config import Settings, get_settings
from app.schemas.provider_models import (
    ProviderConnectionStatusV1,
    ProviderCredentialCapabilityStatusV1,
    ProviderCredentialTestRequestV1,
    ProviderCredentialTestResponseV1,
    ProviderCredentialUpdateRequestV1,
    ProviderCredentialUpdateResponseV1,
    ProviderListResponseV1,
    ModelDefaultsPatchRequestV1,
    ModelDefaultsResponseV1,
    ProviderModelListResponseV1,
    ProviderModelSummaryV1,
    ProviderModelSyncResponseV1,
)
from app.schemas.provider_settings import (
    ProviderCredentialErrorDetail,
    ProviderCredentialErrorResponse,
)
from app.services.provider_credentials import (
    CredentialSettingsError,
    ProviderConnectionService,
    ProviderConnectionSnapshot,
)
from app.services.provider_model_catalog import ProviderModelCatalogService


router = APIRouter(tags=["providers"], route_class=ProviderSettingsRoute)


def _ensure_local_access(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    _ensure_local_settings_access(request, settings)


@router.get(
    "/providers",
    response_model=ProviderListResponseV1,
    responses={403: {"model": ProviderCredentialErrorResponse}},
)
def list_providers(
    _: Annotated[None, Depends(_ensure_local_access)],
    service: Annotated[ProviderConnectionService, Depends(get_provider_connection_service)],
) -> ProviderListResponseV1:
    try:
        return ProviderListResponseV1(items=tuple(_response(item) for item in service.list()))
    except CredentialSettingsError as error:
        raise _http_error(error) from error


@router.get(
    "/providers/{provider_id}",
    response_model=ProviderConnectionStatusV1,
    responses={
        403: {"model": ProviderCredentialErrorResponse},
        404: {"model": ProviderCredentialErrorResponse},
    },
)
def get_provider(
    provider_id: str,
    _: Annotated[None, Depends(_ensure_local_access)],
    service: Annotated[ProviderConnectionService, Depends(get_provider_connection_service)],
) -> ProviderConnectionStatusV1:
    try:
        return _response(service.status(provider_id))
    except CredentialSettingsError as error:
        raise _http_error(error) from error
    except ValueError as error:
        if str(error) != "provider_not_supported":
            raise
        raise HTTPException(
            status_code=404,
            detail=ProviderCredentialErrorDetail(
                code="provider_not_supported",
                message="The requested provider is not supported.",
            ).model_dump(),
        ) from error


@router.put(
    "/providers/{provider_id}/credentials",
    response_model=ProviderCredentialUpdateResponseV1,
    responses={
        403: {"model": ProviderCredentialErrorResponse},
        404: {"model": ProviderCredentialErrorResponse},
        409: {"model": ProviderCredentialErrorResponse},
        422: {"model": ProviderCredentialErrorResponse},
        500: {"model": ProviderCredentialErrorResponse},
    },
)
def update_provider_credentials(
    provider_id: str,
    payload: ProviderCredentialUpdateRequestV1,
    _: Annotated[None, Depends(_ensure_local_access)],
    service: Annotated[ProviderConnectionService, Depends(get_provider_connection_service)],
) -> ProviderCredentialUpdateResponseV1:
    try:
        result = service.update(
            provider_id,
            api_keys=payload.secret_values(),
            clear_capabilities=payload.clear_capabilities,
        )
        return ProviderCredentialUpdateResponseV1(
            provider=_response(result.provider),
            updated_capabilities=result.updated_capabilities,
            cleared_capabilities=result.cleared_capabilities,
            applied_at=result.applied_at,
        )
    except CredentialSettingsError as error:
        raise _http_error(error) from error


@router.post(
    "/providers/{provider_id}/credentials/test",
    response_model=ProviderCredentialTestResponseV1,
    responses={
        403: {"model": ProviderCredentialErrorResponse},
        409: {"model": ProviderCredentialErrorResponse},
        422: {"model": ProviderCredentialErrorResponse},
        503: {"model": ProviderCredentialErrorResponse},
    },
)
def test_provider_credentials(
    provider_id: str,
    payload: ProviderCredentialTestRequestV1,
    _: Annotated[None, Depends(_ensure_local_access)],
    service: Annotated[ProviderConnectionService, Depends(get_provider_connection_service)],
) -> ProviderCredentialTestResponseV1:
    try:
        result = service.test(
            provider_id,
            capability=payload.capability,
            candidate=payload.api_key.get_secret_value() if payload.api_key is not None else None,
            model_ref=payload.model_ref,
        )
    except CredentialSettingsError as error:
        raise _http_error(error) from error
    return ProviderCredentialTestResponseV1(
        provider_id=result.provider_id,
        capability=result.capability,  # type: ignore[arg-type]
        model_ref=result.model_ref,
        tested_at=datetime.now(timezone.utc),
    )


@router.post(
    "/providers/{provider_id}/models/sync",
    response_model=ProviderModelSyncResponseV1,
    responses={
        403: {"model": ProviderCredentialErrorResponse},
        404: {"model": ProviderCredentialErrorResponse},
        503: {"model": ProviderCredentialErrorResponse},
    },
)
def sync_provider_models(
    provider_id: str,
    _: Annotated[None, Depends(_ensure_local_access)],
    service: Annotated[ProviderModelCatalogService, Depends(get_provider_model_catalog_service)],
) -> ProviderModelSyncResponseV1:
    try:
        result = service.sync(provider_id, now=datetime.now(timezone.utc).isoformat())
    except ValueError as error:
        code = str(error)
        status_code = 404 if code == "provider_not_supported" else 503
        raise HTTPException(
            status_code=status_code,
            detail=ProviderCredentialErrorDetail(
                code=code,
                message="Provider model synchronization could not be completed.",
            ).model_dump(),
        ) from error
    return ProviderModelSyncResponseV1(
        provider_id=result.provider_id,
        sync_run_id=result.sync_run_id,
        catalog_revision=result.catalog_revision,
    )


@router.get("/models", response_model=ProviderModelListResponseV1)
def list_models(
    provider: str | None = None,
    capability: str | None = None,
    node_type: str | None = None,
    purpose: str | None = None,
    include_unavailable: bool = False,
    service: ProviderModelCatalogService = Depends(get_provider_model_catalog_service),
) -> ProviderModelListResponseV1:
    return ProviderModelListResponseV1(
        items=tuple(
            ProviderModelSummaryV1(
                model_ref=model.model_ref,
                provider_id=model.provider_id,
                provider_model_id=model.provider_model_id,
                display_name=model.display_name,
                capability=model.capability,
                capability_metadata=model.capability_metadata,
                availability=model.availability,
                unavailable_reason=model.unavailable_reason,
                catalog_revision=model.catalog_revision,
            )
            for model in service.list_models(
                provider_id=provider,
                capability=capability,
                node_type=node_type,
                purpose=purpose,
                include_unavailable=include_unavailable,
            )
        )
    )


@router.get("/model-defaults", response_model=ModelDefaultsResponseV1)
def get_model_defaults(
    service: ProviderModelCatalogService = Depends(get_provider_model_catalog_service),
) -> ModelDefaultsResponseV1:
    records = service.get_default_records()
    return ModelDefaultsResponseV1(
        defaults={key: record.model_ref for key, record in records.items()},
        revisions={key: record.revision for key, record in records.items()},
    )


@router.patch(
    "/model-defaults",
    response_model=ModelDefaultsResponseV1,
    responses={409: {"model": ProviderCredentialErrorResponse}},
)
def update_model_defaults(
    payload: ModelDefaultsPatchRequestV1,
    _: Annotated[None, Depends(_ensure_local_access)],
    service: Annotated[ProviderModelCatalogService, Depends(get_provider_model_catalog_service)],
) -> ModelDefaultsResponseV1:
    try:
        service.set_defaults(payload.defaults, now=datetime.now(timezone.utc).isoformat())
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail=ProviderCredentialErrorDetail(
                code=str(error),
                message="The requested model default is not valid.",
            ).model_dump(),
        ) from error
    return get_model_defaults(service)


def _response(snapshot: ProviderConnectionSnapshot) -> ProviderConnectionStatusV1:
    return ProviderConnectionStatusV1(
        provider_id=snapshot.provider_id,
        display_name=snapshot.display_name,
        capabilities=snapshot.capabilities,
        connection_state=snapshot.connection_state,
        credentials={
            capability: ProviderCredentialCapabilityStatusV1(
                configured=status.configured,
                fingerprint=status.fingerprint,
                source=status.source,
                test_capability=status.test_capability,
            )
            for capability, status in snapshot.credentials.items()
        },
        credential_revision=snapshot.credential_revision,
        updated_at=snapshot.updated_at,
    )


def _http_error(error: CredentialSettingsError) -> HTTPException:
    code = (
        "provider_not_supported"
        if error.code == "credential_provider_not_supported"
        else error.code
    )
    return HTTPException(
        status_code=404 if code == "provider_not_supported" else error.status_code,
        detail=ProviderCredentialErrorDetail(code=code, message=str(error)).model_dump(),
    )
