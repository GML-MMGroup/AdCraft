"""Replay-safe execution of immutable Agent Canvas capability commands."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from pydantic import BaseModel, ValidationError

from app.persistence.agent_canvas_operation_envelope_repository import (
    AgentCanvasOperationEnvelopeRepository,
)
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_capabilities import (
    CAPABILITY_RESULT_CONTRACTS,
    CapabilityCommandEnvelopeV2,
    CapabilityExecutionResultV1,
)
from app.services.agent_canvas_capability_policy import CapabilityPolicyService
from app.services.pi_agent_runtime_client import PiAgentRuntimeError


class CapabilityGateway(Protocol):
    def run_capability(
        self,
        *,
        request_identity: str,
        capability_id: str,
        operation: str,
        result_contract_name: str,
        candidate_count: int,
        context: Mapping[str, object],
        repair_error: str | None,
    ) -> Mapping[str, object] | BaseModel: ...


def capability_context_from_envelope(
    envelope: CapabilityCommandEnvelopeV2,
) -> Mapping[str, object]:
    """Project only immutable, capability-local context for the Pi boundary."""

    return {
        "context_kind": "capability_operation",
        "workflow_id": envelope.workflow_id,
        "conversation_id": envelope.conversation_id,
        "capability_id": envelope.capability_id,
        "objective": envelope.objective,
        "context_snapshot_id": envelope.context_snapshot_id,
        "context_snapshot_digest": envelope.context_snapshot_digest,
        "requirement_projection": envelope.requirement_projection.model_dump(mode="json"),
        "approved_reference_ids": envelope.reference_allowlist,
        "capability_context": envelope.capability_context or {"objective": envelope.objective},
        "style_projection": envelope.style_projection,
        "response_locale": envelope.response_locale,
    }


class CapabilityExecutionService:
    """Validate frozen command state, invoke or replay Pi, then publish once."""

    def __init__(
        self,
        *,
        database: V2Database,
        gateway: CapabilityGateway,
        context_loader: Callable[[CapabilityCommandEnvelopeV2], Mapping[str, object]],
        current_session_revision: Callable[[CapabilityCommandEnvelopeV2], int | None],
        publisher: Callable[[CapabilityCommandEnvelopeV2, BaseModel], str],
    ) -> None:
        self._envelopes = AgentCanvasOperationEnvelopeRepository(database)
        self._gateway = gateway
        self._context_loader = context_loader
        self._current_session_revision = current_session_revision
        self._publisher = publisher
        self._policy = CapabilityPolicyService()

    def execute(self, envelope_id: str) -> CapabilityExecutionResultV1:
        envelope = self._envelopes.get(envelope_id)
        if not isinstance(envelope, CapabilityCommandEnvelopeV2):
            raise V2PersistenceError(
                "capability_envelope_invalid",
                "Operation envelope does not contain a capability command.",
                stage="capability_execution",
            )
        self._validate_frozen_state(envelope)
        definition = self._policy.definition(envelope.capability_id)
        if definition.result_contract_name != envelope.result_contract_name:
            raise V2PersistenceError(
                "capability_contract_invalid",
                "Capability result contract conflicts with its immutable policy.",
                stage="capability_execution",
            )
        contract = CAPABILITY_RESULT_CONTRACTS[envelope.capability_id]
        context = self._context_loader(envelope)
        repaired = False
        try:
            raw = self._invoke(envelope, definition.operation, context, repair_error=None)
        except V2PersistenceError:
            raise
        except PiAgentRuntimeError as error:
            raise V2PersistenceError(
                error.code,
                error.message,
                stage="capability_execution",
                details={"retryable": error.retryable},
            ) from error
        except Exception as error:  # noqa: BLE001 - gateway boundary normalization.
            raise V2PersistenceError(
                "capability_invocation_failed",
                "Capability execution failed.",
                stage="capability_execution",
            ) from error
        try:
            result = contract.model_validate(raw)
        except ValidationError:
            repaired = True
            try:
                repaired_raw = self._invoke(
                    envelope,
                    definition.operation,
                    context,
                    repair_error="capability_contract_invalid",
                )
                result = contract.model_validate(repaired_raw)
            except (ValidationError, ValueError, TypeError) as error:
                raise V2PersistenceError(
                    "capability_contract_invalid",
                    "Capability result remained invalid after one repair.",
                    stage="capability_execution",
                ) from error
        proposal_id = self._publisher(envelope, result)
        return CapabilityExecutionResultV1(
            envelope_id=envelope.envelope_id,
            capability_id=envelope.capability_id,
            result_contract_name=envelope.result_contract_name,
            proposal_id=proposal_id,
            repaired=repaired,
        )

    def _validate_frozen_state(self, envelope: CapabilityCommandEnvelopeV2) -> None:
        if envelope.expected_session_revision is None:
            return
        current = self._current_session_revision(envelope)
        if current != envelope.expected_session_revision:
            raise V2PersistenceError(
                "guidance_revision_conflict",
                "Guidance state changed before capability execution.",
                stage="capability_execution",
            )

    def _invoke(
        self,
        envelope: CapabilityCommandEnvelopeV2,
        operation: str,
        context: Mapping[str, object],
        *,
        repair_error: str | None,
    ) -> Mapping[str, object] | BaseModel:
        return self._gateway.run_capability(
            request_identity=envelope.agent_request_identity,
            capability_id=envelope.capability_id,
            operation=operation,
            result_contract_name=envelope.result_contract_name,
            candidate_count=envelope.candidate_count,
            context=context,
            repair_error=repair_error,
        )
