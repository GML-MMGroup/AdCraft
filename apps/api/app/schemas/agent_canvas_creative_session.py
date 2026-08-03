"""Shared durable contracts for progressive Agent Canvas creative sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.agent_canvas import (
    CanvasBindingKindV2,
    CanvasCreativeRoleV2,
    CanvasInputRoleV2,
    CanvasNodeTypeV2,
)


AgentCanvasSpecialistNameV2 = Literal[
    "script_writer",
    "product_designer",
    "prop_designer",
    "character_designer",
    "scene_designer",
    "storyboard_artist",
    "video_director",
    "bgm_director",
    "quick_media_agent",
]
CreationModeV2 = Literal[
    "ordinary_conversation",
    "targeted_authoring",
    "quick_media",
    "guided_production",
]
AdaptiveProductionTopicKindV2 = Literal[
    "creative_direction",
    "product",
    "prop",
    "character",
    "scene",
    "script",
    "storyboard",
    "video",
    "audio",
]
TopicApplicabilityV2 = Literal["required", "optional", "not_required"]
ProposalModeV2 = Literal["single_plan", "choice_set"]
AdaptiveProductionStageStatusV2 = Literal[
    "pending",
    "working",
    "completed",
    "skipped",
    "not_required",
    "reopened",
]
GuidedDeliveryActionTypeV2 = Literal[
    "add_another_topic_node",
    "skip_topic",
]


class _CreativeSessionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreationModeDecisionV2(_CreativeSessionModel):
    mode: CreationModeV2
    reason: str = Field(min_length=1, max_length=2_048)
    target_node_id: str | None = Field(default=None, max_length=160)
    target_asset_id: str | None = Field(default=None, max_length=160)


class AdaptiveProductionStageV2(_CreativeSessionModel):
    topic_id: str = Field(min_length=1, max_length=160)
    topic_kind: AdaptiveProductionTopicKindV2
    title: str = Field(min_length=1, max_length=256)
    objective: str = Field(min_length=1, max_length=4_096)
    applicability: TopicApplicabilityV2
    applicability_reason: str = Field(min_length=1, max_length=2_048)
    specialist_name: AgentCanvasSpecialistNameV2
    proposal_mode: ProposalModeV2
    candidate_count: int = Field(ge=1, le=4)
    status: AdaptiveProductionStageStatusV2
    related_node_ids: tuple[str, ...] = Field(default=(), max_length=32)


class AdaptiveProductionDeliverableV2(_CreativeSessionModel):
    deliverable_id: str = Field(min_length=1, max_length=160)
    output_kind: Literal["text", "image", "video", "audio", "editing"]
    required: bool = True
    description: str = Field(min_length=1, max_length=4_096)
    related_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    related_asset_ids: tuple[str, ...] = Field(default=(), max_length=32)


class AdaptiveProductionDependencyV2(_CreativeSessionModel):
    source_topic_id: str = Field(min_length=1, max_length=160)
    target_topic_id: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=2_048)


class AdaptiveProductionCompletionCriteriaV2(_CreativeSessionModel):
    required_deliverable_ids: tuple[str, ...] = Field(default=(), max_length=32)
    accepted_omission_deliverable_ids: tuple[str, ...] = Field(default=(), max_length=32)


class AdaptiveProductionRecipeDraftV2(_CreativeSessionModel):
    goal: str = Field(default="", max_length=4_096)
    current_topic_id: str | None = Field(default=None, max_length=160)
    stages: tuple[AdaptiveProductionStageV2, ...] = Field(min_length=1, max_length=16)
    anchor_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    deliverables: tuple[AdaptiveProductionDeliverableV2, ...] = Field(default=(), max_length=32)
    dependencies: tuple[AdaptiveProductionDependencyV2, ...] = Field(default=(), max_length=64)
    recommended_next_topic_ids: tuple[str, ...] = Field(default=(), max_length=16)
    completion_criteria: AdaptiveProductionCompletionCriteriaV2 = Field(
        default_factory=AdaptiveProductionCompletionCriteriaV2
    )


class AdaptiveProductionRecipeV2(_CreativeSessionModel):
    recipe_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    skill_run_id: str | None = Field(default=None, max_length=160)
    revision: int = Field(ge=1)
    creation_mode: CreationModeV2
    goal: str = Field(default="", max_length=4_096)
    current_topic_id: str | None = Field(default=None, max_length=160)
    stages: tuple[AdaptiveProductionStageV2, ...] = Field(min_length=1, max_length=16)
    anchor_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    deliverables: tuple[AdaptiveProductionDeliverableV2, ...] = Field(default=(), max_length=32)
    dependencies: tuple[AdaptiveProductionDependencyV2, ...] = Field(default=(), max_length=64)
    recommended_next_topic_ids: tuple[str, ...] = Field(default=(), max_length=16)
    completion_criteria: AdaptiveProductionCompletionCriteriaV2 = Field(
        default_factory=AdaptiveProductionCompletionCriteriaV2
    )
    created_at: datetime
    updated_at: datetime


class ConceptDraftSpecV2(_CreativeSessionModel):
    """Private bounded prompt authored for one proposal option."""

    prompt: str = Field(min_length=1, max_length=32_768)


class GuidedDeliveryActionV2(_CreativeSessionModel):
    action_id: str = Field(min_length=1, max_length=160)
    logical_key: str = Field(default="", max_length=256)
    action: GuidedDeliveryActionTypeV2
    state: Literal["pending", "applying", "applied", "superseded", "failed"]
    creating_turn_id: str = Field(min_length=1, max_length=160)
    expected_semantic_revision: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    proposal_id: str | None = Field(default=None, max_length=160)
    topic_id: str | None = Field(default=None, max_length=160)
    recipe_id: str | None = Field(default=None, max_length=160)
    recipe_revision: int | None = Field(default=None, ge=1)
    node_id: str | None = Field(default=None, max_length=160)
    ordered_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    manifest_revision: int | None = Field(default=None, ge=1)
    confirmation_required: bool
    reason: str = Field(min_length=1, max_length=1_024)

    @model_validator(mode="after")
    def assign_logical_key(self) -> "GuidedDeliveryActionV2":
        if not self.logical_key:
            source = self.topic_id or self.proposal_id or self.node_id or "session"
            object.__setattr__(self, "logical_key", f"{self.action}:{source}")
        return self


class PlanningTopicProgressV2(_CreativeSessionModel):
    topic_id: str = Field(min_length=1, max_length=160)
    topic_kind: str = Field(min_length=1, max_length=80)
    display_order: int = Field(ge=0)
    required: bool
    specialist_name: AgentCanvasSpecialistNameV2
    status: Literal[
        "pending",
        "in_review",
        "resolved",
        "skipped",
        "not_required",
        "deferred",
    ]
    outcome: str | None = Field(default=None, max_length=160)
    related_node_ids: tuple[str, ...] = Field(default=(), max_length=32)


class ProductionCompletionProjectionV2(_CreativeSessionModel):
    planning: Literal["not_started", "in_progress", "complete"]
    generation: Literal["not_started", "in_progress", "complete", "partial_failed", "failed"]
    delivery: Literal["not_ready", "ready", "partial", "failed"]


class ProductionReadinessProjectionV2(_CreativeSessionModel):
    discussable_topic_ids: tuple[str, ...] = Field(default=(), max_length=32)
    materializable_topic_ids: tuple[str, ...] = Field(default=(), max_length=32)
    runnable_node_ids: tuple[str, ...] = Field(default=(), max_length=128)
    completion: ProductionCompletionProjectionV2


class CreativeSessionStateV2(_CreativeSessionModel):
    skill_run_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    skill_id: str = Field(min_length=1, max_length=160)
    skill_version: str = Field(min_length=1, max_length=80)
    status: Literal["active", "superseded"]
    creation_mode: CreationModeDecisionV2 | None = None
    active_recipe: AdaptiveProductionRecipeV2 | None = None
    readiness: ProductionReadinessProjectionV2 | None = None
    creative_direction_snapshot_id: str | None = Field(default=None, max_length=160)
    current_topic_id: str | None = Field(default=None, max_length=160)
    topics: tuple[PlanningTopicProgressV2, ...] = Field(default=(), max_length=32)
    deferred_topic_ids: tuple[str, ...] = Field(default=(), max_length=32)
    memory_revision: int = Field(ge=0)
    updated_at: datetime


class CreativeDirectionSnapshotV2(_CreativeSessionModel):
    snapshot_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    skill_run_id: str = Field(min_length=1, max_length=160)
    version: int = Field(ge=1)
    source_skill_id: str | None = Field(default=None, max_length=160)
    source_skill_version: str | None = Field(default=None, max_length=80)
    source_skill_digest: str | None = Field(default=None, max_length=160)
    global_direction: dict[str, JsonValue] = Field(default_factory=dict)
    role_projections: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)
    source_message_id: str | None = Field(default=None, max_length=160)
    source_proposal_id: str | None = Field(default=None, max_length=160)
    content_digest: str = Field(min_length=1, max_length=160)
    created_at: datetime


class ProjectCreativeMemoryV2(_CreativeSessionModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    creative_goal: str = Field(default="", max_length=4_000)
    target_audience: str = Field(default="", max_length=2_000)
    duration_format: str = Field(default="", max_length=256)
    approved_style_summary: str = Field(default="", max_length=4_000)
    approved_node_ids: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    open_questions: tuple[str, ...] = Field(default=(), max_length=32)
    deferred_topics: tuple[str, ...] = Field(default=(), max_length=32)
    rejection_notes: tuple[str, ...] = Field(default=(), max_length=32)
    conversation_summary: str = Field(default="", max_length=16_384)
    summary_through_sequence_no: int = Field(default=0, ge=0)
    memory_revision: int = Field(ge=0)
    updated_at: datetime


class DraftReferenceIntentV2(_CreativeSessionModel):
    source_kind: Literal["node", "image_asset"]
    source_id: str = Field(min_length=1, max_length=160)
    binding_kind: CanvasBindingKindV2
    input_role: CanvasInputRoleV2
    required: bool = False
    display_order: int = Field(ge=0, le=127)


class ProposedDraftReferenceV2(DraftReferenceIntentV2):
    display_name: str = Field(min_length=1, max_length=256)
    media_type: Literal["text", "image", "video", "audio"]


class SpecialistDraftV2(_CreativeSessionModel):
    node_type: CanvasNodeTypeV2
    creative_role: CanvasCreativeRoleV2
    title: str = Field(min_length=1, max_length=256)
    summary_prompt: str = Field(min_length=1, max_length=8_192)
    generation_prompt: str | None = Field(default=None, max_length=32_768)
    structured_content: dict[str, JsonValue] = Field(default_factory=dict)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    reference_intents: tuple[DraftReferenceIntentV2, ...] = Field(
        default=(),
        max_length=64,
    )
    warnings: tuple[str, ...] = Field(default=(), max_length=32)


class ExpertActivityV2(_CreativeSessionModel):
    activity_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    turn_id: str = Field(min_length=1, max_length=160)
    specialist_name: AgentCanvasSpecialistNameV2
    display_name: str = Field(min_length=1, max_length=160)
    operation: Literal["propose_concepts", "revise_concepts", "materialize_draft"]
    status: Literal["working", "completed", "failed"]
    error_code: str | None = Field(default=None, max_length=160)
    error_message: str | None = Field(default=None, max_length=1_024)
    created_at: datetime
    updated_at: datetime | None = None


class ResolvedImageTargetV2(_CreativeSessionModel):
    asset_id: str = Field(min_length=1, max_length=160)
    owner_node_id: str | None = Field(default=None, max_length=160)
    owner_semantic_role: str | None = Field(default=None, max_length=160)
    specialist_name: AgentCanvasSpecialistNameV2
    display_name: str = Field(min_length=1, max_length=256)
    checksum: str = Field(min_length=1, max_length=160)
