"""Contracts for proposal-authorized guided authoring and published results."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _GuidedAuthoringPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GuidedAuthoringPolicyV1(_GuidedAuthoringPolicyModel):
    """Installation-owned policy for the new proposal-submit journey."""

    policy_id: Literal["proposal_submit_auto_result_v1"] = "proposal_submit_auto_result_v1"
    policy_revision: int = Field(default=1, ge=1, le=32)
    media_review_required: Literal[False] = False
    proposal_submit_required: Literal[True] = True


class PlanningWaveIdentityV1(_GuidedAuthoringPolicyModel):
    """Immutable identity of one accepted Proposal planning wave."""

    planning_wave_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    proposal_id: str = Field(min_length=1, max_length=160)
    plan_document_id: str = Field(min_length=1, max_length=160)
    plan_revision: int = Field(ge=1)
    source_revision: int = Field(ge=1)
    source_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class GuidedMediaResultEvidenceV2(_GuidedAuthoringPolicyModel):
    """Durable publication evidence; it is not a synthetic user acceptance."""

    evidence_id: str = Field(min_length=1, max_length=160)
    planning_wave_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    node_revision: int = Field(ge=1)
    operation_id: str = Field(min_length=1, max_length=160)
    asset_id: str = Field(min_length=1, max_length=160)
    asset_version_id: str = Field(min_length=1, max_length=160)
    publication_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    outcome: Literal["published"] = "published"
    recorded_at: datetime
