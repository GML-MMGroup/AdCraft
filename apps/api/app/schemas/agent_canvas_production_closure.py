"""Strict authority contracts for guided storyboard production closure."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


MediaRoleV1 = Literal["image", "video", "audio"]
ConfirmationActorV1 = Literal["user", "agent"]
ClosureBlockerKindV1 = Literal[
    "missing",
    "not_ready",
    "failed",
    "unreadable",
    "unconfirmed",
    "stale",
    "nonterminal_work",
]
ClosureActionV1 = Literal["accept", "retry", "replace", "exclude", "wait"]


class _ClosureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StoryboardFanoutNodePlanV1(_ClosureModel):
    sequence_id: str = Field(min_length=1, max_length=160)
    order: int = Field(ge=1, le=100)
    node_role: Literal["storyboard_grid", "video_segment"]
    node_id: str = Field(min_length=1, max_length=160)


class StoryboardFanoutBindingPlanV1(_ClosureModel):
    binding_id: str = Field(min_length=1, max_length=160)
    source_node_id: str = Field(min_length=1, max_length=160)
    target_node_id: str = Field(min_length=1, max_length=160)
    input_role: Literal["image_reference", "text_context"]
    required: bool
    order: int = Field(ge=0)
    storyboard_reference_purpose: Literal["sequence_visual_anchor"] | None = None


class StoryboardFanoutPlanV1(_ClosureModel):
    fanout_plan_id: str = Field(min_length=1, max_length=160)
    logical_identity: str = Field(min_length=1, max_length=640)
    workflow_id: str = Field(min_length=1, max_length=160)
    plan_document_id: str = Field(min_length=1, max_length=160)
    plan_revision: int = Field(ge=1)
    visual_anchor_node_id: str = Field(min_length=1, max_length=160)
    visual_anchor_node_revision: int = Field(ge=1)
    visual_anchor_asset_id: str = Field(min_length=1, max_length=160)
    visual_anchor_asset_version_id: str = Field(min_length=1, max_length=160)
    visual_anchor_asset_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    visual_anchor_confirmation_id: str = Field(min_length=1, max_length=160)
    nodes: tuple[StoryboardFanoutNodePlanV1, ...]
    bindings: tuple[StoryboardFanoutBindingPlanV1, ...]
    prompt_preparation_keys: tuple[str, ...] = ()
    automatic_run_keys: tuple[str, ...] = ()
    created_at: datetime

    @model_validator(mode="after")
    def validate_fanout(self) -> "StoryboardFanoutPlanV1":
        node_ids = [item.node_id for item in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Fan-out Node plans must be unique.")
        binding_ids = [item.binding_id for item in self.bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("Fan-out Binding plans must be unique.")
        later_grid_ids = {
            item.node_id for item in self.nodes if item.node_role == "storyboard_grid"
        }
        for binding in self.bindings:
            if binding.storyboard_reference_purpose != "sequence_visual_anchor":
                continue
            if (
                binding.source_node_id != self.visual_anchor_node_id
                or binding.target_node_id not in later_grid_ids
            ):
                raise ValueError("Every storyboard visual anchor must form a Grid1 star.")
        return self


class GuidedMediaConfirmationV1(_ClosureModel):
    confirmation_id: str = Field(min_length=1, max_length=160)
    logical_identity: str = Field(min_length=1, max_length=640)
    workflow_id: str = Field(min_length=1, max_length=160)
    plan_document_id: str = Field(min_length=1, max_length=160)
    plan_revision: int = Field(ge=1)
    media_role: MediaRoleV1
    sequence_id: str | None = Field(default=None, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    node_revision: int = Field(ge=1)
    asset_id: str = Field(min_length=1, max_length=160)
    asset_version_id: str = Field(min_length=1, max_length=160)
    asset_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_by: ConfirmationActorV1
    action_id: str = Field(min_length=1, max_length=160)
    decision_id: str = Field(min_length=1, max_length=160)
    confirmed_at: datetime


class GuidedClosureBlockerV1(_ClosureModel):
    kind: ClosureBlockerKindV1
    sequence_id: str | None = Field(default=None, max_length=160)
    media_role: MediaRoleV1
    node_id: str | None = Field(default=None, max_length=160)
    status: str = Field(min_length=1, max_length=40)
    error_code: str = Field(min_length=1, max_length=120)
    allowed_actions: tuple[ClosureActionV1, ...] = ()


class GuidedClosureInputV1(_ClosureModel):
    sequence_id: str | None = Field(default=None, max_length=160)
    order: int = Field(ge=0)
    media_role: MediaRoleV1
    node_id: str = Field(min_length=1, max_length=160)
    node_revision: int = Field(ge=1)
    asset_id: str = Field(min_length=1, max_length=160)
    asset_version_id: str = Field(min_length=1, max_length=160)
    asset_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation_id: str = Field(min_length=1, max_length=160)


class GuidedClosurePlanV1(_ClosureModel):
    closure_plan_id: str = Field(min_length=1, max_length=160)
    logical_identity: str = Field(min_length=1, max_length=640)
    workflow_id: str = Field(min_length=1, max_length=160)
    guidance_session_id: str = Field(min_length=1, max_length=160)
    plan_document_id: str = Field(min_length=1, max_length=160)
    plan_revision: int = Field(ge=1)
    confirmation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    ordered_inputs: tuple[GuidedClosureInputV1, ...]
    no_active_work: Literal[True]
    created_at: datetime

    @model_validator(mode="after")
    def validate_ordered_inputs(self) -> "GuidedClosurePlanV1":
        orders = [item.order for item in self.ordered_inputs]
        if orders != sorted(orders) or len(orders) != len(set(orders)):
            raise ValueError("Closure inputs must have unique ascending order.")
        confirmation_ids = [item.confirmation_id for item in self.ordered_inputs]
        if len(confirmation_ids) != len(set(confirmation_ids)):
            raise ValueError("Closure confirmations must be unique.")
        return self


class GuidedEditingPreparationReceiptV1(_ClosureModel):
    receipt_id: str = Field(min_length=1, max_length=160)
    logical_identity: str = Field(min_length=1, max_length=640)
    workflow_id: str = Field(min_length=1, max_length=160)
    closure_plan_id: str = Field(min_length=1, max_length=160)
    plan_document_id: str = Field(min_length=1, max_length=160)
    plan_revision: int = Field(ge=1)
    confirmation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    editing_node_id: str = Field(min_length=1, max_length=160)
    editing_node_revision: int = Field(ge=1)
    binding_ids: tuple[str, ...]
    manifest_revision: int = Field(ge=1)
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    committed_at: datetime


EditingActionReconciliationOutcomeV1 = Literal[
    "prepared",
    "waiting_user",
    "system_deferred",
    "failed",
    "superseded",
]
EditingActionSystemOwnerKindV1 = Literal[
    "execution_member",
    "automatic_run",
    "post_ready_effect",
    "guided_media_resume",
]


class GuidedEditingActionReconciliationCommandV1(_ClosureModel):
    logical_identity: str = Field(min_length=1, max_length=640)
    workflow_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    action_id: str = Field(min_length=1, max_length=160)
    action_turn_id: str = Field(min_length=1, max_length=160)
    action_stage_revision: int = Field(ge=1)
    expected_session_revision: int = Field(ge=1)
    outcome: EditingActionReconciliationOutcomeV1
    reason_code: str = Field(min_length=1, max_length=120)
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=16)
    preparation_receipt_id: str | None = Field(default=None, max_length=160)
    awaiting_id: str | None = Field(default=None, max_length=160)
    awaiting_kind: Literal["media_review", "manual_node_run"] | None = None
    system_owner_kind: EditingActionSystemOwnerKindV1 | None = None
    system_owner_id: str | None = Field(default=None, max_length=160)
    system_owner_node_id: str | None = Field(default=None, max_length=160)
    error_code: str | None = Field(default=None, max_length=120)
    reconciled_at: datetime

    @model_validator(mode="after")
    def validate_outcome_evidence(self) -> "GuidedEditingActionReconciliationCommandV1":
        has_preparation = self.preparation_receipt_id is not None
        has_wait = self.awaiting_id is not None or self.awaiting_kind is not None
        has_system_owner = any(
            value is not None
            for value in (
                self.system_owner_kind,
                self.system_owner_id,
                self.system_owner_node_id,
            )
        )
        has_error = self.error_code is not None
        if self.outcome == "prepared":
            if not has_preparation or has_wait or has_system_owner or has_error:
                raise ValueError("prepared requires only a preparation receipt")
        elif self.outcome == "waiting_user":
            if (
                self.awaiting_id is None
                or self.awaiting_kind is None
                or has_preparation
                or has_system_owner
                or has_error
            ):
                raise ValueError("waiting_user requires only typed awaiting authority")
        elif self.outcome == "system_deferred":
            if (
                self.system_owner_kind is None
                or self.system_owner_id is None
                or self.system_owner_node_id is None
                or has_preparation
                or has_wait
                or has_error
            ):
                raise ValueError("system_deferred requires only exact system ownership")
        elif self.outcome == "failed":
            if not has_error or has_preparation or has_wait or has_system_owner:
                raise ValueError("failed requires only a stable error code")
        elif has_preparation or has_wait or has_system_owner or has_error:
            raise ValueError("superseded cannot claim current outcome authority")
        return self


class GuidedEditingActionReconciliationReceiptV1(GuidedEditingActionReconciliationCommandV1):
    receipt_id: str = Field(min_length=1, max_length=160)
    resulting_session_revision: int = Field(ge=1)


class GuidedFinalCompletionReceiptV1(_ClosureModel):
    receipt_id: str = Field(min_length=1, max_length=160)
    logical_identity: str = Field(min_length=1, max_length=640)
    workflow_id: str = Field(min_length=1, max_length=160)
    preparation_receipt_id: str = Field(min_length=1, max_length=160)
    export_id: str = Field(min_length=1, max_length=160)
    export_generation: int = Field(ge=1)
    final_asset_id: str = Field(min_length=1, max_length=160)
    final_asset_version_id: str = Field(min_length=1, max_length=160)
    final_asset_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    completion_revision: int = Field(ge=1)
    completed_at: datetime
