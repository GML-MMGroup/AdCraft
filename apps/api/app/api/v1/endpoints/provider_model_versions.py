"""Protected API SPACE configuration for compatible provider versions."""

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.endpoints.providers import _adapter_response_fields, _ensure_local_access
from app.api.v1.endpoints.provider_settings import ProviderSettingsRoute
from app.core.config import Settings, get_settings
from app.persistence.database import create_v2_database
from app.persistence.provider_model_repository import ProviderModelRecord, ProviderModelRepository
from app.schemas.provider_models import (
    ProviderModelListResponseV2,
    ProviderModelSummaryV2,
    ProviderModelVersionRequestV1,
    ProviderModelVersionReviewRequestV1,
)
from app.services.provider_model_catalog import image_resolution_capabilities
from app.services.provider_model_versions import ProviderModelVersionService
from app.services.provider_model_evidence import ProviderModelEvidenceService
from app.schemas.provider_model_evidence import (
    ConfiguredAgentEvidenceRequestV1,
    ConfiguredAgentEvidenceTargetsV1,
    ConfiguredAgentEvidenceReceiptV1,
)
from app.schemas.provider_settings import (
    ProviderCredentialErrorDetail,
    ProviderCredentialErrorResponse,
)


router = APIRouter(
    tags=["providers"],
    route_class=ProviderSettingsRoute,
    dependencies=[Depends(_ensure_local_access)],
    responses={code: {"model": ProviderCredentialErrorResponse} for code in (403, 404, 409)},
)


def get_version_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[ProviderModelVersionService]:
    database = create_v2_database(settings.media_data_dir)
    try:
        yield ProviderModelVersionService(ProviderModelRepository(database))
    finally:
        database.dispose()


def get_evidence_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[ProviderModelEvidenceService]:
    database = create_v2_database(settings.media_data_dir)
    try:
        yield ProviderModelEvidenceService(ProviderModelRepository(database))
    finally:
        database.dispose()


@router.get(
    "/providers/{provider_id}/models/versions/conformance",
    response_model=ConfiguredAgentEvidenceTargetsV1,
)
def list_operation_evidence_targets(
    provider_id: str,
    model_ref: str,
    service: Annotated[ProviderModelEvidenceService, Depends(get_evidence_service)],
) -> ConfiguredAgentEvidenceTargetsV1:
    try:
        return service.targets(provider_id, model_ref)
    except ValueError as error:
        raise _error(error) from error


@router.post(
    "/providers/{provider_id}/models/versions/conformance",
    response_model=ConfiguredAgentEvidenceReceiptV1,
    status_code=201,
)
def submit_operation_evidence(
    provider_id: str,
    payload: ConfiguredAgentEvidenceRequestV1,
    service: Annotated[ProviderModelEvidenceService, Depends(get_evidence_service)],
) -> ConfiguredAgentEvidenceReceiptV1:
    try:
        return service.submit(provider_id, payload, now=datetime.now(timezone.utc).isoformat())
    except ValueError as error:
        raise _error(error) from error


@router.get("/providers/{provider_id}/models/templates", response_model=ProviderModelListResponseV2)
def list_version_templates(
    provider_id: str,
    service: Annotated[ProviderModelVersionService, Depends(get_version_service)],
) -> ProviderModelListResponseV2:
    return ProviderModelListResponseV2(
        items=tuple(_summary(m) for m in service.templates(provider_id))
    )


@router.post(
    "/providers/{provider_id}/models/versions",
    response_model=ProviderModelSummaryV2,
    status_code=201,
)
def register_version(
    provider_id: str,
    payload: ProviderModelVersionRequestV1,
    service: Annotated[ProviderModelVersionService, Depends(get_version_service)],
) -> ProviderModelSummaryV2:
    try:
        return _summary(
            service.register(provider_id, payload, now=datetime.now(timezone.utc).isoformat())
        )
    except ValueError as error:
        raise _error(error) from error


@router.post(
    "/providers/{provider_id}/models/versions/review", response_model=ProviderModelSummaryV2
)
def review_version(
    provider_id: str,
    payload: ProviderModelVersionReviewRequestV1,
    service: Annotated[ProviderModelVersionService, Depends(get_version_service)],
) -> ProviderModelSummaryV2:
    try:
        return _summary(
            service.review(provider_id, payload, now=datetime.now(timezone.utc).isoformat())
        )
    except ValueError as error:
        raise _error(error) from error


def _error(error: ValueError) -> HTTPException:
    allowed = {
        "provider_model_not_found",
        "model_version_template_unsupported",
        "model_version_provider_mismatch",
        "model_version_exists",
        "model_version_conflict",
        "model_version_not_configured",
        "model_version_review_required",
        "model_conformance_identity_invalid",
    }
    code = str(error) if str(error) in allowed else "model_version_invalid"
    return HTTPException(
        status_code=404 if code == "provider_model_not_found" else 409,
        detail=ProviderCredentialErrorDetail(
            code=code, message="The model version configuration could not be applied."
        ).model_dump(),
    )


def _summary(model: ProviderModelRecord) -> ProviderModelSummaryV2:
    return ProviderModelSummaryV2(
        model_ref=model.model_ref,
        provider_id=model.provider_id,
        provider_model_id=model.provider_model_id,
        display_name=model.display_name,
        capability=model.capability,
        capability_metadata=model.capability_metadata,
        availability=model.availability,
        unavailable_reason=model.unavailable_reason,
        catalog_revision=model.catalog_revision,
        image_resolution_capabilities=(
            image_resolution_capabilities(model.capability_metadata)
            if model.capability == "image"
            else None
        ),
        **_adapter_response_fields(model.capability_metadata),
    )
