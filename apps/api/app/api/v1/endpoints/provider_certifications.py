from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_identity_certification_registry
from app.schemas.provider_identity_certification import ProviderCertificationListResponse
from app.services.provider_identity_certification import IdentityCertificationRegistry


router = APIRouter(tags=["provider-certifications"])


@router.get("/provider-certifications", response_model=ProviderCertificationListResponse)
def list_provider_certifications(
    registry: Annotated[
        IdentityCertificationRegistry,
        Depends(get_identity_certification_registry),
    ],
    provider: str | None = None,
    model_id: str | None = None,
    media_type: str | None = None,
    node_type: str | None = None,
    reference_semantic_type: str | None = None,
    status: str | None = None,
) -> ProviderCertificationListResponse:
    return ProviderCertificationListResponse(
        records=registry.records(
            provider=provider,
            model_id=model_id,
            media_type=media_type,
            node_type=node_type,
            reference_semantic_type=reference_semantic_type,
            status=status,
        )
    )
