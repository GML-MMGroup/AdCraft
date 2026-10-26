"""Import operator-supplied evidence without running providers or altering defaults."""

from __future__ import annotations

from uuid import uuid4

from app.persistence.provider_model_repository import ProviderModelRecord, ProviderModelRepository
from app.schemas.provider_model_evidence import (
    ConfiguredAgentEvidenceIdentityV1,
    ConfiguredAgentEvidenceReceiptV1,
    ConfiguredAgentEvidenceRequestV1,
    ConfiguredAgentEvidenceTargetV1,
    ConfiguredAgentEvidenceTargetsV1,
)
from app.services.configured_agent_conformance import (
    configured_operation_status,
    operation_policy_digest,
    requires_operation_evidence,
)
from app.services.provider_model_conformance import ProviderModelConformanceService
from app.services.v2_agent_runtime_manifest import V2AgentRuntimeManifestService
from app.services.video_agent_operation_registry import VideoAgentOperationRegistry


class ProviderModelEvidenceService:
    def __init__(self, repository: ProviderModelRepository) -> None:
        self._repository = repository

    def _model(self, provider_id: str, model_ref: str) -> ProviderModelRecord:
        model = self._repository.get_model(model_ref)
        if model.provider_id != provider_id:
            raise ValueError("model_version_provider_mismatch")
        if not requires_operation_evidence(model):
            raise ValueError("model_version_not_configured")
        return model

    @staticmethod
    def _identity(model: ProviderModelRecord, operation: str) -> ConfiguredAgentEvidenceIdentityV1:
        return ConfiguredAgentEvidenceIdentityV1(
            model_ref=model.model_ref,
            expected_catalog_revision=model.catalog_revision,
            operation=operation,
            capability_revision=model.capability_metadata["capability_revision"],
            contract_digest=V2AgentRuntimeManifestService().expected().contract_digest,
            operation_policy_digest=operation_policy_digest(operation),
        )

    def targets(self, provider_id: str, model_ref: str) -> ConfiguredAgentEvidenceTargetsV1:
        model = self._model(provider_id, model_ref)
        records = {r.operation: r for r in self._repository.current_conformances(model_ref)}
        return ConfiguredAgentEvidenceTargetsV1(
            items=tuple(
                ConfiguredAgentEvidenceTargetV1(
                    operation=operation,
                    identity=self._identity(model, operation),
                    status=configured_operation_status(model, operation, records.get(operation)),
                    latest_run_id=(
                        records[operation].conformance_run_id if operation in records else None
                    ),
                )
                for operation in VideoAgentOperationRegistry().names()
            )
        )

    def submit(
        self, provider_id: str, request: ConfiguredAgentEvidenceRequestV1, *, now: str
    ) -> ConfiguredAgentEvidenceReceiptV1:
        model = self._model(provider_id, request.model_ref)
        if model.capability_metadata["version_registration"]["state"] != "approved":
            raise ValueError("model_version_review_required")
        if request.expected_catalog_revision != model.catalog_revision:
            raise ValueError("model_version_conflict")
        if request.operation not in VideoAgentOperationRegistry().names():
            raise ValueError("model_conformance_identity_invalid")
        expected = self._identity(model, request.operation)
        if any(getattr(request, key) != value for key, value in expected.model_dump().items()):
            raise ValueError("model_conformance_identity_invalid")
        service = ProviderModelConformanceService(self._repository)
        run_id = f"conformance_{uuid4().hex}"
        service.record_start(
            run_id=run_id,
            model_ref=model.model_ref,
            operation=request.operation,
            adapter_id=request.adapter_id,
            transport_kind=request.transport_kind,
            adapter_revision=request.adapter_revision,
            capability_revision=request.capability_revision,
            contract_digest=request.contract_digest,
            now=now,
        )
        service.record_result(
            run_id=run_id,
            status=request.status,
            safe_summary={
                "catalog_revision": model.catalog_revision,
                "operation_policy_digest": request.operation_policy_digest,
                "checks": request.checks.model_dump(),
                "evidence_kind": request.evidence_kind,
                "evidence_reference": request.evidence_reference,
                "duration_ms": request.duration_ms,
                "review_kind": "operator_import",
            },
            completed_at=now,
        )
        return ConfiguredAgentEvidenceReceiptV1(
            conformance_run_id=run_id,
            model_ref=model.model_ref,
            operation=request.operation,
            status=request.status,
        )
