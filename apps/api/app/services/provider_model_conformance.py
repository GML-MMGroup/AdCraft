"""Transactional conformance evidence for exact provider model identities."""

from __future__ import annotations

from typing import Any, Mapping

from app.persistence.provider_model_repository import (
    ProviderModelConformanceRunRecord,
    ProviderModelRepository,
)


class ProviderModelConformanceService:
    """Keep conformance lifecycle policy above the model repository boundary."""

    def __init__(self, repository: ProviderModelRepository) -> None:
        self._repository = repository

    def record_start(
        self,
        *,
        model_ref: str,
        operation: str,
        adapter_id: str,
        transport_kind: str,
        adapter_revision: str,
        capability_revision: str,
        contract_digest: str,
        routing_policy_id: str | None = None,
        routing_policy_digest: str | None = None,
        now: str,
        run_id: str,
    ) -> ProviderModelConformanceRunRecord:
        return self._repository.record_conformance_start(
            conformance_run_id=run_id,
            model_ref=model_ref,
            operation=operation,
            adapter_id=adapter_id,
            transport_kind=transport_kind,
            adapter_revision=adapter_revision,
            capability_revision=capability_revision,
            contract_digest=contract_digest,
            routing_policy_id=routing_policy_id,
            routing_policy_digest=routing_policy_digest,
            started_at=now,
        )

    def record_result(
        self,
        *,
        run_id: str,
        status: str,
        safe_summary: Mapping[str, Any],
        completed_at: str,
    ) -> ProviderModelConformanceRunRecord:
        return self._repository.record_conformance_result(
            conformance_run_id=run_id,
            status=status,
            safe_summary=safe_summary,
            completed_at=completed_at,
        )

    def current(
        self,
        model_ref: str,
        operation: str,
    ) -> ProviderModelConformanceRunRecord | None:
        return self._repository.current_conformance(model_ref=model_ref, operation=operation)
