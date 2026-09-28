"""Operator-reviewed, template-derived provider versions in the canonical catalog."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

from app.persistence.provider_model_repository import ProviderModelRecord, ProviderModelRepository
from app.schemas.provider_models import (
    ProviderModelVersionRequestV1,
    ProviderModelVersionReviewRequestV1,
)
from app.services.provider_model_catalog import (
    compatible_version_manifests,
    is_reserved_model_identity,
)
from app.services.configured_agent_conformance import NATIVE_AGENT_ADAPTER


class ProviderModelVersionService:
    def __init__(self, repository: ProviderModelRepository) -> None:
        self._repository = repository

    def templates(self, provider_id: str) -> tuple[ProviderModelRecord, ...]:
        allowed = {manifest.model_ref for manifest in compatible_version_manifests(provider_id)}
        return tuple(
            model
            for model in self._repository.list_models(provider_id=provider_id)
            if model.model_ref in allowed and model.source == "built_in"
        )

    def register(
        self, provider_id: str, request: ProviderModelVersionRequestV1, *, now: str
    ) -> ProviderModelRecord:
        if not request.template_model_ref.startswith(f"{provider_id}:"):
            raise ValueError("model_version_provider_mismatch")
        manifests = {m.model_ref: m for m in compatible_version_manifests(provider_id)}
        manifest = manifests.get(request.template_model_ref)
        if manifest is None:
            raise ValueError("model_version_template_unsupported")
        parent = self._repository.get_model(manifest.model_ref)
        if parent.source != "built_in" or parent.availability in {"deprecated", "unsupported"}:
            raise ValueError("model_version_template_unsupported")
        model_ref = f"{provider_id}:{request.provider_model_id}"
        if is_reserved_model_identity(model_ref):
            raise ValueError("model_version_exists")
        metadata = deepcopy(dict(manifest.capability_metadata))
        if manifest.adapter_profile is not None:
            metadata["adapter_profile"] = deepcopy(dict(manifest.adapter_profile))
        revision = f"configured-{sha256(model_ref.encode()).hexdigest()[:32]}-v1"
        metadata["capability_revision"] = revision
        if manifest.capability == "text":
            metadata.update(
                adapter_id=NATIVE_AGENT_ADAPTER,
                adapter_revision=NATIVE_AGENT_ADAPTER,
                transport_kind="pi_native_openai_compatible",
            )
        metadata["version_registration"] = {
            "template_model_ref": manifest.model_ref,
            "template_catalog_revision": parent.catalog_revision,
            "registered_at": now,
            "state": "pending",
            "review_kind": "operator_attestation",
            "reviews": [],
        }
        profile = metadata.get("adapter_profile")
        if isinstance(profile, dict):
            profile.update(
                model_ref=model_ref,
                capability_revision=revision,
                conformance_status="unverified",
                release_tier="compatible",
            )
        return self._repository.insert_configured_model(
            provider_id=provider_id,
            model={
                "model_ref": model_ref,
                "provider_model_id": request.provider_model_id,
                "display_name": request.display_name,
                "capability": manifest.capability,
                "capability_metadata": metadata,
                "source": "configured",
                "availability": "unavailable",
                "unavailable_reason": "model_version_review_required",
            },
            updated_at=now,
        )

    def review(
        self, provider_id: str, request: ProviderModelVersionReviewRequestV1, *, now: str
    ) -> ProviderModelRecord:
        model = self._repository.get_model(request.model_ref)
        if model.provider_id != provider_id:
            raise ValueError("model_version_provider_mismatch")
        if model.source != "configured":
            raise ValueError("model_version_not_configured")
        metadata = deepcopy(model.capability_metadata)
        registration = metadata["version_registration"]
        if request.approved and registration["template_model_ref"] not in {
            m.model_ref for m in compatible_version_manifests(provider_id)
        }:
            raise ValueError("model_version_template_unsupported")
        registration["state"] = "approved" if request.approved else "rejected"
        registration["reviews"].append(
            {
                "approved": request.approved,
                "evidence_reference": request.evidence_reference,
                "reviewed_at": now,
                "previous_catalog_revision": request.expected_catalog_revision,
            }
        )
        profile = metadata.get("adapter_profile")
        if isinstance(profile, dict):
            profile["conformance_status"] = "compatible" if request.approved else "revoked"
        return self._repository.review_configured_model(
            model_ref=model.model_ref,
            expected_revision=request.expected_catalog_revision,
            metadata=metadata,
            approved=request.approved,
            updated_at=now,
        )
