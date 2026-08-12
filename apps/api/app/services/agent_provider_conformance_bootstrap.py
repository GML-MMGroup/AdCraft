"""Durable, product-detached bootstrap for provider conformance diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal
from uuid import uuid4

from app.persistence.agent_run_repository import AgentRunRecord, AgentRunRepository
from app.persistence.database import V2Database
from app.schemas.agent_canvas_capabilities import (
    CompactTurnIntentDecisionV2,
    TurnIntentContextV2,
)
from app.schemas.agent_runtime import (
    AgentProviderConformanceInputV1,
    AgentRunRequest,
    canonical_agent_run_request_digest,
)
from app.services.agent_operation_policy import freeze_agent_run_operation_policy
from app.services.agent_run_envelope import agent_run_envelope_fields
from app.services.agent_run_context_registry import validate_video_agent_operation_context


_MODEL_POLICY_ID = "video_agent.decide_turn_intent.v3"
_LEASE_DURATION_SECONDS = 600
_SYNTHETIC_USER_INPUT = (
    "Create a 30-second 16:9 premium sparkling-tea advertisement for urban young adults."
)


@dataclass(frozen=True, slots=True)
class AgentProviderConformanceRunHandle:
    request: AgentRunRequest
    input_envelope: AgentProviderConformanceInputV1
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
    ) -> None:
        self._repository = AgentRunRepository(database)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._run_id_factory = run_id_factory or _new_run_id
        self._lease_owner_factory = lease_owner_factory or _new_lease_owner_id

    def start(self, *, model_ref: str) -> AgentProviderConformanceRunHandle:
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
        request = AgentRunRequest(
            run_id=run_id,
            request_id=f"request_{run_id}",
            **agent_run_envelope_fields(context),
            agent_name="video_agent",
            operation="decide_turn_intent",
            deadline_at=timestamp + timedelta(seconds=_LEASE_DURATION_SECONDS),
            model_policy_id=_MODEL_POLICY_ID,
            model_ref=model_ref,
            context=context,
            contract_name="CompactTurnIntentDecisionV2",
            contract_schema=CompactTurnIntentDecisionV2.model_json_schema(),
            audit_metadata={
                "run_purpose": "provider_conformance",
                "report_schema_version": 2,
                "model_ref": model_ref,
                "model_policy_id": _MODEL_POLICY_ID,
            },
        )
        frozen_request = freeze_agent_run_operation_policy(request, now=timestamp)
        lease_owner_id = self._lease_owner_factory()
        record, created = self._repository.create_or_load(
            frozen_request,
            lease_owner_id=lease_owner_id,
            lease_duration_seconds=_LEASE_DURATION_SECONDS,
            now=timestamp,
        )
        return AgentProviderConformanceRunHandle(
            request=frozen_request,
            input_envelope=AgentProviderConformanceInputV1(
                frozen_agent_request=frozen_request,
                frozen_agent_request_digest=canonical_agent_run_request_digest(frozen_request),
                diagnostic_case_budget=6,
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
