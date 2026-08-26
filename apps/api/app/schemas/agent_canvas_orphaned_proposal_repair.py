"""Contracts for one allowlisted orphaned Guided Proposal correction."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OrphanedProposalRepairQueueCountsV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    executions: int = Field(ge=0)
    continuations: int = Field(ge=0)
    agent_runs: int = Field(ge=0)
    provider_tasks: int = Field(ge=0)
    editing_exports: int = Field(ge=0)


class OrphanedProposalProtectedDigestsV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow: str = Field(pattern=r"^[0-9a-f]{64}$")
    session: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirements: str = Field(pattern=r"^[0-9a-f]{64}$")
    nodes: str = Field(pattern=r"^[0-9a-f]{64}$")
    bindings: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal_options: str = Field(pattern=r"^[0-9a-f]{64}$")
    assets: str = Field(pattern=r"^[0-9a-f]{64}$")
    media: str = Field(pattern=r"^[0-9a-f]{64}$")


class OrphanedGuidedProposalRepairAuditV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: str
    proposal_id: str
    turn_id: str
    activity_id: str
    continuation_id: str
    envelope_id: str
    session_id: str
    workflow_revision: int = Field(ge=1)
    session_revision: int = Field(ge=1)
    journey_stage: str
    journey_stage_revision: int = Field(ge=1)
    proposal_card_schema_version: int = Field(ge=1)
    option_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    product_node_count: int = Field(ge=0)
    active_queue_counts: OrphanedProposalRepairQueueCountsV1
    protected_digests: OrphanedProposalProtectedDigestsV1
    audited_at: str
    audit_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class OrphanedGuidedProposalRepairReceiptV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    correction_receipt_id: str
    workflow_id: str
    proposal_id: str
    turn_id: str
    activity_id: str
    continuation_id: str
    evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    transition_key: str
    event_id: str
    replacement_status: str
    protected_digests: OrphanedProposalProtectedDigestsV1
    applied_at: str
    replayed: bool
