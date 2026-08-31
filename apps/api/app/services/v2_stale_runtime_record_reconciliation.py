"""Read-only classification for stale V2 runtime records.

This module deliberately stops at an authorization boundary. Existing runtime
repositories remain the only writers for their respective record classes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RuntimeRecordClass = Literal[
    "chat_turn",
    "guided_action",
    "skill_run",
    "presentation_stream",
    "guided_interaction",
]
RuntimeDispositionClass = Literal[
    "live",
    "legal_wait",
    "durable_selection",
    "orphan_candidate",
    "stale_candidate",
    "ineligible",
    "unknown",
]


class RuntimeRecordObservationV1(BaseModel):
    """One read-only observation captured from the authoritative database."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_class: RuntimeRecordClass
    record_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    session_id: str | None = Field(default=None, max_length=160)
    status: str = Field(min_length=1, max_length=80)
    observed_at: datetime
    owner_id: str | None = Field(default=None, max_length=160)
    heartbeat_at: datetime | None = None
    lease_generation: int | None = Field(default=None, ge=1)
    lease_expires_at: datetime | None = None
    process_id: int | None = Field(default=None, ge=1)
    revision: int | None = Field(default=None, ge=1)
    source_workflow_id: str | None = Field(default=None, max_length=160)
    source_session_id: str | None = Field(default=None, max_length=160)
    source_revision: int | None = Field(default=None, ge=1)
    expected_revision: int | None = Field(default=None, ge=1)
    source_status: str | None = Field(default=None, max_length=80)
    continuation_id: str | None = Field(default=None, max_length=160)
    continuation_status: str | None = Field(default=None, max_length=80)
    has_current_awaiting: bool = False
    has_source_proof: bool = False
    has_reliable_terminal_evidence: bool = False
    has_recovery_identity: bool = False
    identity_matches: bool = True


class RuntimeRecordDispositionV1(BaseModel):
    """A classification that never authorizes a database mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_class: RuntimeRecordClass
    record_id: str
    workflow_id: str
    classification: RuntimeDispositionClass
    reason_code: str
    mutation_allowed: bool = False
    recovery_action: str | None = None


class RuntimeDispositionPlanItemV1(BaseModel):
    """One proposed action, still blocked by the explicit mutation boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_class: RuntimeRecordClass
    record_id: str
    workflow_id: str
    classification: RuntimeDispositionClass
    disposition_key: str = Field(min_length=1, max_length=160)
    expected_status: str = Field(min_length=1, max_length=80)
    expected_revision: int | None = Field(default=None, ge=1)
    expected_generation: int | None = Field(default=None, ge=1)
    has_source_proof: bool = False
    mutation_allowed: bool = False
    requires_runtime_owner_authorization: bool = True
    existing_authority: str | None = None


class RuntimeDispositionPlanV1(BaseModel):
    """A deterministic dry-run plan with no implicit live mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mutation_authorized: bool = False
    mutation_boundary: Literal["dry_run", "owner_authorized"] = "dry_run"
    items: tuple[RuntimeDispositionPlanItemV1, ...] = ()


class RuntimeDispositionAuthorizationResultV1(BaseModel):
    """Result of validating an owner request; it still cannot write state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    authorized: bool
    mutation_allowed: bool = False
    disposition_key: str
    reason_code: str


def authorize_disposition(
    record: RuntimeRecordObservationV1,
    *,
    expected_status: str,
    expected_revision: int | None = None,
    expected_generation: int | None = None,
    owner_approval_id: str | None,
) -> RuntimeDispositionAuthorizationResultV1:
    """Validate a bounded request without invoking a repository writer."""

    disposition = classify_runtime_record(record)
    disposition_key = _disposition_key(record, disposition)
    if (
        record.record_class in {"guided_action", "presentation_stream"}
        and not record.has_source_proof
    ):
        return RuntimeDispositionAuthorizationResultV1(
            authorized=False,
            disposition_key=disposition_key,
            reason_code="source_proof_required",
        )
    if disposition.classification not in {"orphan_candidate", "stale_candidate"}:
        return RuntimeDispositionAuthorizationResultV1(
            authorized=False,
            disposition_key=disposition_key,
            reason_code="record_not_reconcilable",
        )
    if owner_approval_id is None:
        return RuntimeDispositionAuthorizationResultV1(
            authorized=False,
            disposition_key=disposition_key,
            reason_code="runtime_owner_authorization_required",
        )
    if record.status != expected_status:
        return RuntimeDispositionAuthorizationResultV1(
            authorized=False,
            disposition_key=disposition_key,
            reason_code="status_conflict",
        )
    if expected_revision is not None and record.revision != expected_revision:
        return RuntimeDispositionAuthorizationResultV1(
            authorized=False,
            disposition_key=disposition_key,
            reason_code="revision_conflict",
        )
    if expected_generation is not None and record.lease_generation != expected_generation:
        return RuntimeDispositionAuthorizationResultV1(
            authorized=False,
            disposition_key=disposition_key,
            reason_code="generation_conflict",
        )
    return RuntimeDispositionAuthorizationResultV1(
        authorized=True,
        disposition_key=disposition_key,
        reason_code="owner_authorization_validated",
    )


class RuntimeDispositionInventoryV1(BaseModel):
    """Read-only inventory projection and its deterministic classifications."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    records: tuple[RuntimeRecordObservationV1, ...] = ()
    dispositions: tuple[RuntimeRecordDispositionV1, ...] = ()
    classification_counts: dict[RuntimeDispositionClass, int] = Field(default_factory=dict)
    mutation_authorized: bool = False


class RuntimeIdleAuditV1(BaseModel):
    """Separate worker queues from legal waits and durable selections."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_queue_count: int = Field(ge=0)
    member_queue_count: int = Field(ge=0)
    continuation_queue_count: int = Field(ge=0)
    agent_run_queue_count: int = Field(ge=0)
    provider_queue_count: int = Field(ge=0)
    editing_export_queue_count: int = Field(ge=0)
    node_lease_count: int = Field(ge=0)
    legal_wait_count: int = Field(ge=0)
    durable_selection_count: int = Field(ge=0)
    blocked_liveness_count: int = Field(ge=0)

    @property
    def worker_queues_idle(self) -> bool:
        return not any(
            (
                self.execution_queue_count,
                self.member_queue_count,
                self.continuation_queue_count,
                self.agent_run_queue_count,
                self.provider_queue_count,
                self.editing_export_queue_count,
                self.node_lease_count,
            )
        )


def build_disposition_inventory(
    records: tuple[RuntimeRecordObservationV1, ...],
) -> RuntimeDispositionInventoryV1:
    """Project records without writing to the source database."""

    dispositions = tuple(classify_runtime_record(record) for record in records)
    counts: dict[RuntimeDispositionClass, int] = {}
    for disposition in dispositions:
        counts[disposition.classification] = counts.get(disposition.classification, 0) + 1
    return RuntimeDispositionInventoryV1(
        records=records,
        dispositions=dispositions,
        classification_counts=counts,
    )


def build_disposition_plan(
    records: tuple[RuntimeRecordObservationV1, ...],
) -> RuntimeDispositionPlanV1:
    """Build a stable dry-run plan without invoking any repository writer."""

    items = tuple(
        RuntimeDispositionPlanItemV1(
            record_class=disposition.record_class,
            record_id=disposition.record_id,
            workflow_id=disposition.workflow_id,
            classification=disposition.classification,
            disposition_key=_disposition_key(record, disposition),
            expected_status=record.status,
            expected_revision=record.revision,
            expected_generation=record.lease_generation,
            has_source_proof=record.has_source_proof,
            existing_authority=_existing_authority(disposition),
        )
        for record in records
        for disposition in (classify_runtime_record(record),)
    )
    return RuntimeDispositionPlanV1(items=items)


def _existing_authority(disposition: RuntimeRecordDispositionV1) -> str | None:
    authorities = {
        "chat_turn": "AgentCanvasConversationRepository",
        "guided_action": "AgentCanvasGuidedInteractionRepository",
        "skill_run": "AgentCanvasConversationRepository.create_skill_run",
        "presentation_stream": "PresentationStreamPublisher",
        "guided_interaction": "AgentCanvasGuidedInteractionRepository",
    }
    return authorities.get(disposition.record_class)


def classify_runtime_record(
    record: RuntimeRecordObservationV1,
) -> RuntimeRecordDispositionV1:
    """Classify one record using explicit liveness and source evidence."""

    if not record.identity_matches or _cross_scope_mismatch(record):
        return _disposition(record, "ineligible", "identity_scope_mismatch")

    if _has_live_owner(record):
        return _disposition(record, "live", "owned_live_record")

    if record.record_class == "chat_turn":
        return _classify_chat_turn(record)
    if record.record_class == "guided_action":
        return _classify_guided_action(record)
    if record.record_class == "skill_run":
        return _classify_skill_run(record)
    if record.record_class == "presentation_stream":
        return _classify_presentation_stream(record)
    if record.record_class == "guided_interaction":
        return _classify_guided_interaction(record)
    return _disposition(record, "unknown", "unsupported_record_class")


def _classify_chat_turn(record: RuntimeRecordObservationV1) -> RuntimeRecordDispositionV1:
    if record.status not in {"queued", "running"}:
        return _disposition(record, "ineligible", "terminal_or_nonrecoverable_status")
    if record.continuation_id and record.continuation_status not in {
        None,
        "completed",
        "failed",
        "superseded",
    }:
        return _disposition(record, "unknown", "continuation_liveness_unproven")
    if record.has_reliable_terminal_evidence and not record.has_recovery_identity:
        return _disposition(record, "orphan_candidate", "terminal_evidence_without_owner")
    return _disposition(record, "stale_candidate", "liveness_unproven")


def _classify_guided_action(record: RuntimeRecordObservationV1) -> RuntimeRecordDispositionV1:
    if record.status != "applying":
        return _disposition(record, "ineligible", "non_applying_action")
    if record.has_source_proof and record.source_status in {
        "completed",
        "failed",
        "cancelled",
        "superseded",
    }:
        return _disposition(record, "stale_candidate", "source_terminal_proof")
    return _disposition(record, "stale_candidate", "source_proof_required")


def _classify_skill_run(record: RuntimeRecordObservationV1) -> RuntimeRecordDispositionV1:
    if record.status != "active":
        return _disposition(record, "ineligible", "non_active_skill_run")
    return _disposition(record, "durable_selection", "durable_style_selection")


def _classify_presentation_stream(
    record: RuntimeRecordObservationV1,
) -> RuntimeRecordDispositionV1:
    if record.status != "open":
        return _disposition(record, "ineligible", "terminal_stream")
    if record.has_source_proof:
        return _disposition(record, "stale_candidate", "source_terminal_proof")
    return _disposition(record, "unknown", "source_proof_required")


def _classify_guided_interaction(
    record: RuntimeRecordObservationV1,
) -> RuntimeRecordDispositionV1:
    if record.status != "open":
        return _disposition(record, "ineligible", "closed_interaction")
    if record.has_current_awaiting:
        return _disposition(record, "legal_wait", "current_user_awaiting")
    return _disposition(record, "unknown", "awaiting_proof_required")


def _has_live_owner(record: RuntimeRecordObservationV1) -> bool:
    if record.process_id is not None:
        return True
    if record.owner_id is None or record.heartbeat_at is None:
        return False
    if record.lease_expires_at is not None and record.lease_expires_at <= record.observed_at:
        return False
    return True


def _cross_scope_mismatch(record: RuntimeRecordObservationV1) -> bool:
    return (
        (record.source_workflow_id is not None and record.source_workflow_id != record.workflow_id)
        or (
            record.session_id is not None
            and record.source_session_id is not None
            and record.session_id != record.source_session_id
        )
        or (
            record.source_revision is not None
            and record.expected_revision is not None
            and record.source_revision != record.expected_revision
        )
    )


def _disposition(
    record: RuntimeRecordObservationV1,
    classification: RuntimeDispositionClass,
    reason_code: str,
) -> RuntimeRecordDispositionV1:
    return RuntimeRecordDispositionV1(
        record_class=record.record_class,
        record_id=record.record_id,
        workflow_id=record.workflow_id,
        classification=classification,
        reason_code=reason_code,
    )


def _disposition_key(
    record: RuntimeRecordObservationV1,
    disposition: RuntimeRecordDispositionV1,
) -> str:
    revision = record.revision if record.revision is not None else "none"
    generation = record.lease_generation if record.lease_generation is not None else "none"
    return (
        f"{disposition.record_class}:{disposition.record_id}:"
        f"{record.status}:{revision}:{generation}:{disposition.classification}:"
        f"{disposition.reason_code}"
    )
