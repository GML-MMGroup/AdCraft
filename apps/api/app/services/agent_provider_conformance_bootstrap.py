"""Durable, product-detached bootstrap for provider conformance diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal
from uuid import uuid4

from app.persistence.agent_run_repository import AgentRunRecord, AgentRunRepository
from app.persistence.database import V2Database
from app.schemas.agent_canvas_capabilities import (
    CompactTurnIntentDecisionV3,
    TurnIntentContextV2,
)
from app.schemas.agent_runtime import (
    AgentProviderConformanceBudgetPlanV1,
    AgentProviderConformanceInputV2,
    AgentRunRequest,
    canonical_agent_run_request_digest,
)
from app.schemas.provider_models import ProviderConformanceTargetV1
from app.services.agent_operation_policy import AgentRunRequestFactory
from app.services.agent_provider_conformance_budget import (
    canonical_agent_provider_conformance_budget_digest,
    derive_agent_provider_conformance_budget,
)
from app.services.agent_run_context_registry import validate_video_agent_operation_context


_SYNTHETIC_USER_INPUT = (
    "Create a 30-second 16:9 premium sparkling-tea advertisement for urban young adults."
)


@dataclass(frozen=True, slots=True)
class AgentProviderConformanceRunHandle:
    request: AgentRunRequest
    input_envelope: AgentProviderConformanceInputV2
    record: AgentRunRecord
    lease_owner_id: str
    created: bool


class AgentProviderConformanceBootstrapService:
    """Own exactly one frozen diagnostic Agent Run for one operator command."""

    def __init__(
        self,
        database: V2Database,
        *,
        now: Callable[[], datetime] | None = None,
        run_id_factory: Callable[[], str] | None = None,
        lease_owner_factory: Callable[[], str] | None = None,
        budget_deriver: Callable[
            [AgentRunRequest], AgentProviderConformanceBudgetPlanV1
        ] = derive_agent_provider_conformance_budget,
    ) -> None:
        self._repository = AgentRunRepository(database)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._run_id_factory = run_id_factory or _new_run_id
        self._lease_owner_factory = lease_owner_factory or _new_lease_owner_id
        self._budget_deriver = budget_deriver

    def start(
        self,
        *,
        model_ref: str,
        adapter_id: str | None = None,
        transport_kind: str | None = None,
        capability: str = "text",
        adapter_revision: str | None = None,
        capability_revision: str = "catalog-1",
        contract_digest: str | None = None,
    ) -> AgentProviderConformanceRunHandle:
        timestamp = self._now()
        run_id = self._run_id_factory()
        suffix = _diagnostic_suffix(run_id)
        context = TurnIntentContextV2(
            workflow_id=f"diagnostic_workflow_{suffix}",
            workflow_revision=1,
            conversation_id=f"diagnostic_conversation_{suffix}",
            user_input=_SYNTHETIC_USER_INPUT,
            session_exists=False,
            requirement_revision_id=f"diagnostic_requirement_{suffix}",
            requirement_revision_no=1,
            requirement_digest="0" * 64,
        )
        validate_video_agent_operation_context("decide_turn_intent", context)
        frozen_request = AgentRunRequestFactory().build(
            run_id=run_id,
            request_id=f"request_{run_id}",
            agent_name="video_agent",
            operation="decide_turn_intent",
            now=timestamp,
            model_ref=model_ref,
            context=context,
            contract_name="CompactTurnIntentDecisionV3",
            contract_schema=CompactTurnIntentDecisionV3.model_json_schema(),
            audit_metadata={
                "run_purpose": "provider_conformance",
                "report_schema_version": 3,
                "model_ref": model_ref,
            },
        )
        target = ProviderConformanceTargetV1(
            model_ref=model_ref,
            provider_model_id=_provider_model_id(model_ref),
            adapter_id=adapter_id or "pi-openai-compatible-v1",
            transport_kind=transport_kind or "pi_native_openai_compatible",
            capability=capability,
            operation=frozen_request.operation,
            adapter_revision=adapter_revision or adapter_id or "pi-openai-compatible-v1",
            capability_revision=capability_revision,
            contract_digest=contract_digest or frozen_request.contract_digest,
        )
        frozen_request = frozen_request.model_copy(
            update={
                "audit_metadata": {
                    **frozen_request.audit_metadata,
                    "provider_model_id": target.provider_model_id,
                    "adapter_id": target.adapter_id,
                    "transport_kind": target.transport_kind,
                    "capability": target.capability,
                    "adapter_revision": target.adapter_revision,
                    "capability_revision": target.capability_revision,
                    "contract_digest": target.contract_digest,
                }
            }
        )
        budget_plan = self._budget_deriver(frozen_request)
        audit_metadata = {
            **frozen_request.audit_metadata,
            "conformance_budget_version": budget_plan.budget_version,
            "conformance_budget_digest": canonical_agent_provider_conformance_budget_digest(
                budget_plan
            ),
            "conformance_matrix_timeout_ms": budget_plan.matrix_timeout_ms,
            "conformance_child_timeout_ms": budget_plan.child_timeout_ms,
            "conformance_lease_duration_seconds": budget_plan.lease_duration_seconds,
        }
        frozen_request = frozen_request.model_copy(update={"audit_metadata": audit_metadata})
        lease_owner_id = self._lease_owner_factory()
        record, created = self._repository.create_or_load(
            frozen_request,
            lease_owner_id=lease_owner_id,
            lease_duration_seconds=budget_plan.lease_duration_seconds,
            now=timestamp,
        )
        return AgentProviderConformanceRunHandle(
            request=frozen_request,
            input_envelope=AgentProviderConformanceInputV2(
                frozen_agent_request=frozen_request,
                frozen_agent_request_digest=canonical_agent_run_request_digest(frozen_request),
                target=target,
                budget_plan=budget_plan,
                evidence_destination_id=run_id,
            ),
            record=record,
            lease_owner_id=lease_owner_id,
            created=created,
        )

    def finish(
        self,
        handle: AgentProviderConformanceRunHandle,
        *,
        status: Literal["completed", "failed", "cancelled"],
        terminal_result: dict[str, object],
        safe_error_code: str | None = None,
        now: datetime | None = None,
    ) -> AgentRunRecord:
        return self._repository.finish(
            handle.record.run_id,
            lease_owner_id=handle.lease_owner_id,
            lease_generation=handle.record.lease_generation,
            status=status,
            terminal_result=terminal_result,
            safe_error_code=safe_error_code,
            now=now or self._now(),
        )


def _new_run_id() -> str:
    return f"arun_conformance_{uuid4().hex}"


def _new_lease_owner_id() -> str:
    return f"conformance_operator_{uuid4().hex}"


def _diagnostic_suffix(run_id: str) -> str:
    prefix = "arun_conformance_"
    if not run_id.startswith(prefix) or len(run_id) <= len(prefix):
        raise ValueError("conformance_durable_run_unavailable")
    suffix = run_id[len(prefix) :]
    if not suffix.replace("_", "").isalnum():
        raise ValueError("conformance_durable_run_unavailable")
    return suffix


def _provider_model_id(model_ref: str) -> str:
    _provider_id, separator, provider_model_id = model_ref.partition(":")
    if not separator or not provider_model_id:
        raise ValueError("provider_conformance_model_identity_mismatch")
    return provider_model_id
