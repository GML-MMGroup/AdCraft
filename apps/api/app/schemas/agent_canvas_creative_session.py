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
from app.schemas.agent_canvas_ad_media import (
    BgmContentV2,
    DesignAssetContentV2,
    SceneDesignBoardContentV2,
    StoryboardGridContentV2,
    VideoSegmentContentV2,
    SemanticReferenceRoleV2,
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
CreativeOutputKindV2 = Literal["text", "script", "image", "video", "audio"]
CreativeDeliveryScopeV2 = Literal["draft", "generated_media"]
CreativeElementKindV2 = Literal[
    "world_setting",
    "product",
    "character",
    "prop",
    "scene",
    "script",
    "storyboard",
    "video",
    "audio",
]
GuidanceTopicKindV2 = Literal[
    "world_setting",
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


class _CreativeSessionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreationModeDecisionV2(_CreativeSessionModel):
    mode: CreationModeV2
    reason: str = Field(min_length=1, max_length=2_048)
    target_node_id: str | None = Field(default=None, max_length=160)
    target_asset_id: str | None = Field(default=None, max_length=160)


class CreativeGoalV2(_CreativeSessionModel):
    requested_output: CreativeOutputKindV2
    delivery_scope: CreativeDeliveryScopeV2
    summary: str = Field(min_length=1, max_length=4_096)
    explicit_constraints: dict[str, JsonValue] = Field(default_factory=dict)


class CreativeElementDecisionV2(_CreativeSessionModel):
    element_kind: CreativeElementKindV2
    presence: Literal["include", "exclude", "unspecified"]
    authority: Literal["user", "agent"]
    requirements: dict[str, JsonValue] = Field(default_factory=dict)
    source: Literal[
        "explicit_user",
        "accepted_proposal",
        "delegated_to_agent",
    ]


class GuidanceTopicStateV2(_CreativeSessionModel):
    topic_id: str = Field(min_length=1, max_length=160)
    topic_kind: GuidanceTopicKindV2
    title: str = Field(min_length=1, max_length=256)
    status: Literal["proposed", "selected", "deferred", "excluded"]
    specialist_name: AgentCanvasSpecialistNameV2
    related_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    source_proposal_id: str | None = Field(default=None, max_length=160)
    revision: int = Field(ge=1)


class GuidanceCompletionProjectionV2(_CreativeSessionModel):
    authoring: Literal["not_ready", "ready"] = "not_ready"
    delivery: Literal["not_ready", "ready"] = "not_ready"
    editing_preparation: Literal["not_ready", "prepared"] = "not_ready"
    editing_node_id: str | None = Field(default=None, max_length=160)
    matching_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    matching_asset_ids: tuple[str, ...] = Field(default=(), max_length=32)


class GuidedSessionStateV2(_CreativeSessionModel):
    session_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    status: Literal["active", "paused", "completed"]
    guidance_mode: Literal["collaborative", "delegated"]
    goal: CreativeGoalV2
    element_decisions: tuple[CreativeElementDecisionV2, ...] = Field(
        default=(),
        max_length=32,
    )
    current_topic_id: str | None = Field(default=None, max_length=160)
    topics: tuple[GuidanceTopicStateV2, ...] = Field(default=(), max_length=64)
    active_proposal_id: str | None = Field(default=None, max_length=160)
    active_style_skill_run_id: str | None = Field(default=None, max_length=160)
    completion: GuidanceCompletionProjectionV2 = Field(
        default_factory=GuidanceCompletionProjectionV2
    )
    revision: int = Field(ge=1)
    updated_at: datetime


class GuidanceIntentPatchV2(_CreativeSessionModel):
    goal: CreativeGoalV2 | None = None
    element_decisions: tuple[CreativeElementDecisionV2, ...] = Field(
        default=(),
        max_length=32,
    )


class GuidanceCompletionClaimV2(_CreativeSessionModel):
    state: Literal["authoring_ready", "delivery_ready"]
    output_kind: CreativeOutputKindV2
    node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    asset_ids: tuple[str, ...] = Field(default=(), max_length=32)
    reason: str = Field(min_length=1, max_length=2_048)


class NextGuidanceDecisionV2(_CreativeSessionModel):
    action: Literal[
        "ordinary_reply",
        "ask_clarification",
        "propose_topic",
        "finish_guidance",
    ]
    assistant_message: str = Field(min_length=1, max_length=4_000)
    rationale: str = Field(min_length=1, max_length=4_000)
    topic_id: str | None = Field(default=None, max_length=160)
    topic_kind: GuidanceTopicKindV2 | None = None
    topic_title: str | None = Field(default=None, max_length=256)
    topic_objective: str | None = Field(default=None, max_length=4_096)
    specialist_name: AgentCanvasSpecialistNameV2 | None = None
    candidate_count: int | None = Field(default=None, ge=1, le=4)
    suggested_next_topic_kinds: tuple[GuidanceTopicKindV2, ...] = Field(
        default=(),
        max_length=8,
    )
    intent_patch: GuidanceIntentPatchV2 | None = None
    completion_claim: GuidanceCompletionClaimV2 | None = None

    @model_validator(mode="after")
    def validate_action_shape(self) -> "NextGuidanceDecisionV2":
        topic_values = (
            self.topic_id,
            self.topic_kind,
            self.topic_title,
            self.topic_objective,
            self.specialist_name,
            self.candidate_count,
        )
        if self.action == "propose_topic":
            if any(value is None for value in topic_values):
                raise ValueError("A topic proposal requires the complete topic shape.")
        elif any(value is not None for value in topic_values):
            raise ValueError("Only a topic proposal accepts topic fields.")
        if self.action == "finish_guidance":
            if self.completion_claim is None:
                raise ValueError("Finishing guidance requires a completion claim.")
        elif self.completion_claim is not None:
            raise ValueError("Only finish_guidance accepts a completion claim.")
        return self


class DelegatedProposalChoiceV2(_CreativeSessionModel):
    option_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=2_048)


class ConceptDraftSpecV2(_CreativeSessionModel):
    """Private bounded prompt authored for one proposal option."""

    prompt: str = Field(min_length=1, max_length=32_768)


class GuidanceSessionActionV2(_CreativeSessionModel):
    action_id: str = Field(min_length=1, max_length=160)
    logical_key: str = Field(min_length=1, max_length=256)
    action: Literal["stop_guidance", "resume_guidance"]
    state: Literal["pending", "applying", "applied", "superseded", "failed"]
    creating_turn_id: str = Field(min_length=1, max_length=160)
    expected_session_revision: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    confirmation_required: bool
    reason: str = Field(min_length=1, max_length=1_024)


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


class StyleGuidanceContextV2(_CreativeSessionModel):
    skill_run_id: str = Field(min_length=1, max_length=160)
    skill_id: str = Field(min_length=1, max_length=160)
    skill_version: str = Field(min_length=1, max_length=80)
    package_digest: str = Field(min_length=1, max_length=160)
    creative_direction_snapshot_id: str = Field(min_length=1, max_length=160)
    global_guidance: str = Field(min_length=1, max_length=8_192)
    role: str | None = Field(default=None, max_length=160)
    role_guidance: str | None = Field(default=None, max_length=8_192)
    role_guidance_path: str | None = Field(default=None, max_length=512)
    role_guidance_digest: str | None = Field(default=None, max_length=160)
    source: Literal["creative_direction_snapshot"] = "creative_direction_snapshot"
    precedence: Literal["advisory"] = "advisory"


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
    semantic_reference_role: SemanticReferenceRoleV2 | None = None


class ProposedDraftReferenceV2(DraftReferenceIntentV2):
    display_name: str = Field(min_length=1, max_length=256)
    media_type: Literal["text", "image", "video", "audio"]


class ScriptDraftContentV2(_CreativeSessionModel):
    content: str = Field(min_length=1, max_length=32_768)


class _SpecialistDraftBaseV2(_CreativeSessionModel):
    title: str = Field(min_length=1, max_length=256)
    summary_prompt: str = Field(min_length=1, max_length=8_192)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    reference_intents: tuple[DraftReferenceIntentV2, ...] = Field(
        default=(),
        max_length=64,
    )
    warnings: tuple[str, ...] = Field(default=(), max_length=32)


class SpecialistDraftV2(_SpecialistDraftBaseV2):
    node_type: CanvasNodeTypeV2
    creative_role: CanvasCreativeRoleV2
    generation_prompt: str | None = Field(default=None, max_length=32_768)
    structured_content: dict[str, JsonValue] = Field(default_factory=dict)


class ScriptSpecialistDraftV2(_SpecialistDraftBaseV2):
    node_type: Literal["script"]
    creative_role: Literal["script"]
    generation_prompt: None = None
    structured_content: ScriptDraftContentV2


class ProductImageSpecialistDraftV2(_SpecialistDraftBaseV2):
    node_type: Literal["image"]
    creative_role: Literal["product"]
    generation_prompt: str = Field(min_length=1, max_length=32_768)
    structured_content: DesignAssetContentV2


class PropImageSpecialistDraftV2(_SpecialistDraftBaseV2):
    node_type: Literal["image"]
    creative_role: Literal["prop"]
    generation_prompt: str = Field(min_length=1, max_length=32_768)
    structured_content: DesignAssetContentV2


class CharacterImageSpecialistDraftV2(_SpecialistDraftBaseV2):
    node_type: Literal["image"]
    creative_role: Literal["character"]
    generation_prompt: str = Field(min_length=1, max_length=32_768)
    structured_content: DesignAssetContentV2


class SceneImageSpecialistDraftV2(_SpecialistDraftBaseV2):
    node_type: Literal["image"]
    creative_role: Literal["scene"]
    generation_prompt: str = Field(min_length=1, max_length=32_768)
    structured_content: SceneDesignBoardContentV2


class StoryboardImageSpecialistDraftV2(_SpecialistDraftBaseV2):
    node_type: Literal["image"]
    creative_role: Literal["storyboard_sequence"]
    generation_prompt: str = Field(min_length=1, max_length=32_768)
    structured_content: StoryboardGridContentV2


class VideoSpecialistDraftV2(_SpecialistDraftBaseV2):
    node_type: Literal["video"]
    creative_role: Literal["storyboard_video"]
    generation_prompt: str = Field(min_length=1, max_length=32_768)
    structured_content: VideoSegmentContentV2


class BgmAudioSpecialistDraftV2(_SpecialistDraftBaseV2):
    node_type: Literal["audio"]
    creative_role: Literal["bgm"]
    generation_prompt: str = Field(min_length=1, max_length=32_768)
    structured_content: BgmContentV2


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
