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
from app.schemas.agent_canvas_materialization import GuidedScriptCheckpointDraftV1
from app.services.agent_canvas_script_checkpoint_contract import (
    CapabilityContractBindingRegistry,
    CapabilityContractBindingRegistryError,
    GuidedScriptCheckpointCanonicalizationError,
)
from app.services.agent_canvas_capability_policy import CapabilityPolicyService
from app.services.agent_canvas_proposal_cardinality import (
    proposal_candidate_count_details,
)
from app.services.agent_canvas_capability_supersession import (
    CapabilitySupersessionClassifier,
)
from app.services.agent_run_context_registry import AgentRunContextRegistryError
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

    def run_materialization(
        self,
        *,
        request_identity: str,
        capability_id: str,
        operation: str,
        result_contract_name: str,
        context: Mapping[str, object],
        repair_error: str | None,
    ) -> Mapping[str, object] | BaseModel: ...


class _CapabilityResultValidationError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def capability_context_from_envelope(
    envelope: CapabilityCommandEnvelopeV2,
) -> Mapping[str, object]:
    """Project only immutable, capability-local context for the Pi boundary."""

    capability_context = dict(envelope.capability_context)
    if envelope.character_target is not None:
        capability_context["character_target"] = envelope.character_target.model_dump(mode="json")
    if envelope.publication_kind == "internal_document":
        capability_context["journey_stage"] = envelope.journey_stage
    existing_constraints = capability_context.get("explicit_constraints")
    explicit_constraints = (
        dict(existing_constraints) if isinstance(existing_constraints, dict) else {}
    )
    explicit_constraints.update(
        {
            control.control: control.value
            for control in envelope.requirement_projection.hard_controls
        }
    )
    if envelope.requirement_projection.identity_safety_decision is not None:
        explicit_constraints["identity_safety_decision"] = (
            envelope.requirement_projection.identity_safety_decision.model_dump(mode="json")
        )
    if explicit_constraints:
        capability_context["explicit_constraints"] = explicit_constraints
    projected_context: dict[str, object] = {
        "context_kind": "capability_operation",
        "workflow_id": envelope.workflow_id,
        "conversation_id": envelope.conversation_id,
        "capability_id": envelope.capability_id,
        "candidate_count": envelope.candidate_count,
        "objective": envelope.objective,
        "context_snapshot_id": envelope.context_snapshot_id,
        "context_snapshot_digest": envelope.context_snapshot_digest,
        "requirement_projection": envelope.requirement_projection.model_dump(mode="json"),
        "approved_reference_ids": envelope.reference_allowlist,
        "capability_context": capability_context or {"objective": envelope.objective},
        "style_projection": envelope.style_projection,
        "response_locale": envelope.response_locale,
    }
    if envelope.character_target is not None:
        projected_context["character_target"] = envelope.character_target
    return projected_context


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
        internal_document_publisher: (
            Callable[[CapabilityCommandEnvelopeV2, BaseModel], str] | None
        ) = None,
    ) -> None:
        self._envelopes = AgentCanvasOperationEnvelopeRepository(database)
        self._gateway = gateway
        self._context_loader = context_loader
        self._current_session_revision = current_session_revision
        self._publisher = publisher
        self._internal_document_publisher = internal_document_publisher
        self._policy = CapabilityPolicyService()
        self._supersession = CapabilitySupersessionClassifier(database)
        self._contract_bindings = CapabilityContractBindingRegistry()

    def execute(
        self,
        envelope_id: str,
        lease_guard: Callable[[], None],
    ) -> CapabilityExecutionResultV1:
        envelope = self._envelopes.get(envelope_id)
        if not isinstance(envelope, CapabilityCommandEnvelopeV2):
            raise V2PersistenceError(
                "capability_envelope_invalid",
                "Operation envelope does not contain a capability command.",
                stage="capability_execution",
            )
        self._validate_frozen_state(envelope)
        definition = (
            self._policy.internal_script_checkpoint_definition()
            if envelope.publication_kind == "internal_document"
            else self._policy.definition(envelope.capability_id)
        )
        if (
            envelope.publication_kind == "internal_document"
            and envelope.capability_id == "script_authoring"
            and envelope.result_contract_name == "ScriptMaterializationResultV1"
        ):
            raise V2PersistenceError(
                "agent_script_checkpoint_contract_retired",
                "The retired direct Script checkpoint contract cannot be dispatched.",
                stage="capability_execution",
                details={
                    "retryable": False,
                    "replacement_contract_name": "GuidedScriptCheckpointDraftV1",
                },
            )
        if definition.result_contract_name != envelope.result_contract_name:
            raise V2PersistenceError(
                "capability_contract_invalid",
                "Capability result contract conflicts with its immutable policy.",
                stage="capability_execution",
            )
        try:
            binding = (
                self._contract_bindings.resolve(definition.operation, envelope.publication_kind)
                if envelope.publication_kind == "internal_document"
                else None
            )
        except CapabilityContractBindingRegistryError as error:
            raise V2PersistenceError(
                error.code,
                str(error),
                stage="capability_execution",
            ) from error
        contract = (
            GuidedScriptCheckpointDraftV1
            if binding is not None
            else CAPABILITY_RESULT_CONTRACTS[envelope.capability_id]
        )
        canonical_script_duration = self._canonical_script_duration(envelope)
        context = self._context_loader(envelope)
        repaired = False
        lease_guard()
        try:
            raw = self._invoke(envelope, definition.operation, context, repair_error=None)
        except V2PersistenceError:
            raise
        except AgentRunContextRegistryError as error:
            raise V2PersistenceError(
                error.code,
                error.message,
                stage="capability_execution",
                details=error.details,
            ) from error
        except PiAgentRuntimeError as error:
            details: dict[str, object] = {"retryable": error.retryable}
            if (
                envelope.publication_kind == "proposal"
                and error.code == "agent_structured_output_invalid"
            ):
                details["proposal_retryable"] = True
            raise V2PersistenceError(
                error.code,
                error.message,
                stage="capability_execution",
                details=details,
            ) from error
        except Exception as error:  # noqa: BLE001 - gateway boundary normalization.
            raise V2PersistenceError(
                "capability_invocation_failed",
                "Capability execution failed.",
                stage="capability_execution",
            ) from error
        lease_guard()
        try:
            result = self._validate_result(
                envelope,
                contract,
                raw,
                canonical_script_duration=(
                    None if binding is not None else canonical_script_duration
                ),
            )
        except _CapabilityResultValidationError as initial_error:
            repaired = True
            lease_guard()
            try:
                repaired_raw = self._invoke(
                    envelope,
                    definition.operation,
                    context,
                    repair_error=initial_error.code,
                )
                lease_guard()
                result = self._validate_result(
                    envelope,
                    contract,
                    repaired_raw,
                    canonical_script_duration=(
                        None if binding is not None else canonical_script_duration
                    ),
                )
            except _CapabilityResultValidationError as error:
                details = {**error.details, "repair_attempted": True}
                if envelope.publication_kind == "proposal":
                    details.update(retryable=True, proposal_retryable=True)
                raise V2PersistenceError(
                    error.code,
                    error.message,
                    stage="capability_execution",
                    details=details,
                ) from error
        if binding is not None:
            try:
                result = binding.normalizer(
                    result,
                    duration_seconds=canonical_script_duration,
                )
            except GuidedScriptCheckpointCanonicalizationError as error:
                raise V2PersistenceError(
                    error.code,
                    str(error),
                    stage="capability_execution",
                ) from error
        lease_guard()
        proposal_id: str | None = None
        document_receipt_id: str | None = None
        if envelope.publication_kind == "internal_document":
            if self._internal_document_publisher is None:
                raise V2PersistenceError(
                    "capability_publication_mode_invalid",
                    "Internal document publication is not configured.",
                    stage="capability_execution",
                )
            document_receipt_id = self._internal_document_publisher(envelope, result)
        else:
            self._validate_candidate_count(envelope, result)
            try:
                proposal_id = self._publisher(envelope, result)
            except V2PersistenceError as error:
                if error.code == "guidance_revision_conflict":
                    self._raise_if_superseded(envelope)
                raise
        return CapabilityExecutionResultV1(
            envelope_id=envelope.envelope_id,
            capability_id=envelope.capability_id,
            result_contract_name=envelope.result_contract_name,
            publication_kind=envelope.publication_kind,
            proposal_id=proposal_id,
            document_receipt_id=document_receipt_id,
            repaired=repaired,
        )

    @staticmethod
    def _validate_candidate_count(
        envelope: CapabilityCommandEnvelopeV2,
        result: BaseModel,
    ) -> None:
        details = proposal_candidate_count_details(envelope.candidate_count, result)
        if details is not None:
            raise V2PersistenceError(
                "proposal_candidate_count_mismatch",
                "Proposal result candidate count conflicts with its immutable envelope.",
                stage="capability_execution",
                details=details,
            )

    @staticmethod
    def _canonical_script_duration(
        envelope: CapabilityCommandEnvelopeV2,
    ) -> float | None:
        if not (
            envelope.publication_kind == "internal_document"
            and envelope.capability_id == "script_authoring"
        ):
            return None
        for control in envelope.requirement_projection.hard_controls:
            if control.control == "duration_seconds":
                return float(control.value)
        raise V2PersistenceError(
            "production_duration_required",
            "Canonical production duration is required before Script authoring.",
            stage="capability_execution",
        )

    @staticmethod
    def _validate_result(
        envelope: CapabilityCommandEnvelopeV2,
        contract: type[BaseModel],
        raw: Mapping[str, object] | BaseModel,
        *,
        canonical_script_duration: float | None,
    ) -> BaseModel:
        try:
            result = contract.model_validate(raw)
        except (ValidationError, ValueError, TypeError) as error:
            raise _CapabilityResultValidationError(
                "capability_contract_invalid",
                "Capability result remained invalid after one repair.",
            ) from error
        if envelope.publication_kind == "proposal":
            details = proposal_candidate_count_details(envelope.candidate_count, result)
            if details is not None:
                raise _CapabilityResultValidationError(
                    "proposal_candidate_count_mismatch",
                    "Capability result candidate count does not match its immutable envelope.",
                    details=details,
                )
        if canonical_script_duration is None:
            return result
        structured_content = getattr(result, "structured_content", None)
        result_duration = getattr(structured_content, "total_duration_seconds", None)
        if result_duration is None or float(result_duration) != canonical_script_duration:
            raise _CapabilityResultValidationError(
                "script_duration_contract_invalid",
                "Script result remained inconsistent with canonical duration after one repair.",
            )
        return result

    def _validate_frozen_state(self, envelope: CapabilityCommandEnvelopeV2) -> None:
        if envelope.expected_session_revision is None:
            return
        current = self._current_session_revision(envelope)
        if current != envelope.expected_session_revision:
            self._raise_if_superseded(envelope)
            raise V2PersistenceError(
                "guidance_revision_conflict",
                "Guidance state changed before capability execution.",
                stage="capability_execution",
            )

    def _raise_if_superseded(self, envelope: CapabilityCommandEnvelopeV2) -> None:
        decision = self._supersession.classify(envelope)
        if decision.outcome != "superseded":
            return
        raise V2PersistenceError(
            "guided_capability_superseded",
            "Guided capability work was superseded by later Journey authority.",
            stage="capability_execution",
            details={
                "capability_id": envelope.capability_id,
                "envelope_stage": decision.envelope_stage,
                "current_stage": decision.current_stage,
                "expected_session_revision": envelope.expected_session_revision,
                "current_session_revision": decision.current_session_revision,
                "retryable": False,
            },
        )

    def _invoke(
        self,
        envelope: CapabilityCommandEnvelopeV2,
        operation: str,
        context: Mapping[str, object],
        *,
        repair_error: str | None,
    ) -> Mapping[str, object] | BaseModel:
        if envelope.publication_kind == "internal_document":
            return self._gateway.run_materialization(
                request_identity=envelope.agent_request_identity,
                capability_id=envelope.capability_id,
                operation=operation,
                result_contract_name=envelope.result_contract_name,
                context=context,
                repair_error=repair_error,
            )
        return self._gateway.run_capability(
            request_identity=envelope.agent_request_identity,
            capability_id=envelope.capability_id,
            operation=operation,
            result_contract_name=envelope.result_contract_name,
            candidate_count=envelope.candidate_count,
            context=context,
            repair_error=repair_error,
        )
