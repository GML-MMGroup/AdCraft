"""Immutable internal contracts for Agent Canvas materialization commits."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.agent_canvas import CanvasBindingV2, CanvasNodeV2
from app.schemas.agent_canvas_conversation import (
    AgentActionReceiptV2,
    ContinuationCommitV2,
)
from app.schemas.agent_canvas_draft_seeds import AcceptedProposalCommitmentV1
from app.schemas.agent_working_documents import AgentDocumentMutationPlanV3
from app.schemas.agent_canvas_production_journey import (
    GuidedProductionJourneyV1,
    JourneyEvidenceKindV1,
    JourneyStageV1,
)


class _MaterializationCommitModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MaterializationAuthoringSnapshotV1(_MaterializationCommitModel):
    workflow_revision: int = Field(ge=1)
    session_revision: int = Field(ge=1)
    proposal_revision: int = Field(ge=1)
    target_node_revision: int | None = Field(default=None, ge=1)
    current_journey: GuidedProductionJourneyV1


class StageMaterializedJourneyEventV1(_MaterializationCommitModel):
    event_type: Literal["stage_materialized"] = "stage_materialized"
    evidence_id: str = Field(min_length=1, max_length=160)
    evidence_kind: JourneyEvidenceKindV1
    source_id: str = Field(min_length=1, max_length=160)
    foundation_item_id: str | None = Field(default=None, max_length=160)
    runnable_storyboard_draft: bool = False
    recorded_at: datetime

    @model_validator(mode="after")
    def validate_storyboard_checkpoint(self) -> "StageMaterializedJourneyEventV1":
        if self.runnable_storyboard_draft and self.evidence_kind != "storyboard_plan_accepted":
            raise ValueError(
                "Runnable Storyboard Draft evidence requires storyboard plan acceptance."
            )
        return self


class TargetedActionCompletedJourneyEventV1(_MaterializationCommitModel):
    event_type: Literal["targeted_action_completed"] = "targeted_action_completed"
    evidence_id: str = Field(min_length=1, max_length=160)
    source_id: str = Field(min_length=1, max_length=160)
    action_id: str = Field(min_length=1, max_length=160)
    recorded_at: datetime


MaterializationJourneyEventV1: TypeAlias = Annotated[
    StageMaterializedJourneyEventV1 | TargetedActionCompletedJourneyEventV1,
    Field(discriminator="event_type"),
]


class NodePromptPreparationIntentV1(_MaterializationCommitModel):
    operation_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    context_snapshot_id: str = Field(min_length=1, max_length=160)


class MaterializationDocumentWriteV1(_MaterializationCommitModel):
    document_type: str = Field(min_length=1, max_length=80)
    document_id: str = Field(min_length=1, max_length=160)
    payload: dict[str, JsonValue] | None = None
    mutation_plan: AgentDocumentMutationPlanV3 | None = None
    relation_metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_write_kind(self) -> "MaterializationDocumentWriteV1":
        if (self.payload is None) == (self.mutation_plan is None):
            raise ValueError("A document write requires exactly one create or mutation payload.")
        if self.mutation_plan is not None and self.mutation_plan.document_id != self.document_id:
            raise ValueError("Document mutation identity does not match its write.")
        return self


class MaterializationDocumentResultV1(_MaterializationCommitModel):
    document_id: str = Field(min_length=1, max_length=160)
    operation: str = Field(min_length=1, max_length=160)
    before_revision: int | None = Field(default=None, ge=1)
    after_revision: int = Field(ge=1)
    before_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    after_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class MaterializationAuthoritySnapshotV1(_MaterializationCommitModel):
    workflow_revision: int = Field(ge=1)
    guidance_revision: int = Field(ge=1)
    requirement_revision_id: str = Field(min_length=1, max_length=160)
    requirement_revision_no: int = Field(ge=1)
    requirement_digest: str = Field(min_length=1, max_length=160)
    anchor_registry_revision: int | None = Field(default=None, ge=1)
    anchor_registry_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    storyboard_plan_revision: int | None = Field(default=None, ge=1)
    storyboard_plan_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )


class MaterializationPlanV1(_MaterializationCommitModel):
    schema_version: Literal["1"] = "1"
    materialization_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    proposal_id: str = Field(min_length=1, max_length=160)
    option_id: str = Field(min_length=1, max_length=160)
    action_turn_id: str = Field(min_length=1, max_length=160)
    proposal_action: Literal["select_option", "delegate_choice", "reuse_direction"]
    selection_actor: Literal["user", "agent"]
    expected_workflow_revision: int = Field(ge=1)
    expected_session_revision: int = Field(ge=1)
    expected_proposal_revision: int = Field(ge=1)
    expected_target_node_revision: int | None = Field(default=None, ge=1)
    nodes: tuple[CanvasNodeV2, ...] = Field(min_length=1, max_length=32)
    bindings: tuple[CanvasBindingV2, ...] = Field(default=(), max_length=128)
    document_writes: tuple[MaterializationDocumentWriteV1, ...] = Field(default=(), max_length=32)
    requirement_commitments: tuple[AcceptedProposalCommitmentV1, ...] = Field(
        default=(), max_length=64
    )
    receipt: AgentActionReceiptV2 | None = None
    continuation: ContinuationCommitV2 | None = None
    prompt_preparations: tuple[NodePromptPreparationIntentV1, ...] = Field(
        default=(), max_length=32
    )
    journey_event: MaterializationJourneyEventV1 | None = None
    payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_plan_integrity(self) -> "MaterializationPlanV1":
        node_ids = tuple(node.node_id for node in self.nodes)
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Node IDs must be unique.")

        binding_ids = tuple(binding.binding_id for binding in self.bindings)
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("Binding IDs must be unique.")
        if any(binding.target_node_id not in node_ids for binding in self.bindings):
            raise ValueError("Every Binding must target a planned Node.")

        document_ids = tuple(document.document_id for document in self.document_writes)
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("Document IDs must be unique.")

        operation_ids = tuple(preparation.operation_id for preparation in self.prompt_preparations)
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("Prompt preparation operation IDs must be unique.")
        if any(preparation.node_id not in node_ids for preparation in self.prompt_preparations):
            raise ValueError("Every prompt preparation Node must be planned.")

        if materialization_plan_digest(self) != self.payload_digest:
            raise ValueError("Materialization plan digest does not match its payload.")
        return self


class MaterializationOutcomeV1(_MaterializationCommitModel):
    schema_version: Literal["1"] = "1"
    materialization_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    proposal_id: str = Field(min_length=1, max_length=160)
    node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    binding_ids: tuple[str, ...] = Field(default=(), max_length=128)
    document_ids: tuple[str, ...] = Field(default=(), max_length=32)
    document_results: tuple[MaterializationDocumentResultV1, ...] = Field(default=(), max_length=32)
    before_authority: MaterializationAuthoritySnapshotV1
    after_authority: MaterializationAuthoritySnapshotV1
    prompt_preparation_ids: tuple[str, ...] = Field(default=(), max_length=32)
    receipt_id: str | None = Field(default=None, max_length=160)
    workflow_revision: int = Field(ge=1)
    session_revision: int = Field(ge=1)
    journey_stage: JourneyStageV1
    replayed: bool = False


def materialization_plan_digest(plan: MaterializationPlanV1) -> str:
    """Return the stable semantic digest for a materialization plan."""

    payload = plan.model_dump(mode="json", exclude={"payload_digest"})
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
