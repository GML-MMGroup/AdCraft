"""Typed dry-run and apply contracts for historical Storyboard convergence."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent_canvas_production_journey import JourneyStageV2


class _ReconciliationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StoryboardTerminalReconciliationPlanV1(_ReconciliationModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    source_evidence_workflow_id: str = "adwf_v2_894b22168ba29393"
    expected_workflow_revision: int = Field(ge=1)
    session_id: str = Field(min_length=1, max_length=160)
    expected_session_revision: int = Field(ge=1)
    stage: JourneyStageV2
    stage_revision: int = Field(ge=1)
    canonical_proposal_id: str = Field(min_length=1, max_length=160)
    canonical_interaction_id: str = Field(min_length=1, max_length=160)
    canonical_parent_turn_id: str = Field(min_length=1, max_length=160)
    canonical_materialization_id: str = Field(min_length=1, max_length=160)
    canonical_receipt_id: str = Field(min_length=1, max_length=160)
    canonical_materialization_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    duplicate_proposal_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    duplicate_proposal_revisions: tuple[int, ...] = Field(min_length=1, max_length=32)
    duplicate_interaction_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    duplicate_interaction_revisions: tuple[int, ...] = Field(min_length=1, max_length=32)
    plan_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class StoryboardTerminalReconciliationReceiptV1(_ReconciliationModel):
    reconciliation_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    plan_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    canonical_proposal_id: str = Field(min_length=1, max_length=160)
    superseded_proposal_ids: tuple[str, ...] = Field(max_length=32)
    cleared_interaction_ids: tuple[str, ...] = Field(max_length=32)
    changed: bool
    replayed: bool = False
