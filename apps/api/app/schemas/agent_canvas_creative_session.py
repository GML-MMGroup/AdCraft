"""Shared durable contracts for progressive Agent Canvas creative sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, computed_field, model_validator

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
from app.schemas.agent_canvas_video_parameters import CanvasParameterProvenanceV2
from app.schemas.agent_canvas_capability_identity import (
    CAPABILITY_DISPLAY_NAMES,
    CapabilityIdV1,
)


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


def canonical_guidance_topic_kind(value: str) -> GuidanceTopicKindV2:
    """Normalize retired capability-facing aliases at the persistence boundary."""

    return cast(GuidanceTopicKindV2, "audio" if value == "bgm" else value)


GuidanceStageKindV2 = Literal[
    "world_setting",
    "narrative_direction",
    "product",
    "prop",
    "character",
    "scene",
    "script",
    "storyboard",
    "video",
    "bgm",
    "editing",
]
CreativeAuthorityV2 = Literal["user", "director"]
CreativeAuthoritySourceV2 = Literal[
    "explicit_user",
    "explicit_delegation",
    "director_inference",
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
    capability_id: CapabilityIdV1
    related_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    source_proposal_id: str | None = Field(default=None, max_length=160)
    revision: int = Field(ge=1)

    @computed_field
    @property
    def capability_display_name(self) -> str:
        return CAPABILITY_DISPLAY_NAMES[self.capability_id]


class GuidanceCompletionProjectionV2(_CreativeSessionModel):
    authoring: Literal["not_ready", "ready"] = "not_ready"
    delivery: Literal["not_ready", "ready"] = "not_ready"
    editing_preparation: Literal["not_ready", "prepared"] = "not_ready"
    editing_node_id: str | None = Field(default=None, max_length=160)
    matching_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    matching_asset_ids: tuple[str, ...] = Field(default=(), max_length=32)


class CreativeAuthorityStateV2(_CreativeSessionModel):
    authority: CreativeAuthorityV2
    source: CreativeAuthoritySourceV2
    decided_at_turn_id: str = Field(min_length=1, max_length=160)
    revision: int = Field(ge=1)


class CreativeAuthorityActionV2(_CreativeSessionModel):
    action_id: str = Field(min_length=1, max_length=160)
    action: Literal["set_creative_authority"] = "set_creative_authority"
    authority: CreativeAuthorityV2
    label: str = Field(min_length=1, max_length=160)
    expected_session_revision: int = Field(ge=1)


class CreativeAuthorityResolutionV2(_CreativeSessionModel):
    outcome: Literal["resolved", "ask"]
    authority: CreativeAuthorityV2 | None = None
    source: CreativeAuthoritySourceV2 | None = None
    actions: tuple[CreativeAuthorityActionV2, ...] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def validate_resolution(self) -> "CreativeAuthorityResolutionV2":
        if self.outcome == "resolved":
            if self.authority is None or self.source is None or self.actions:
                raise ValueError("A resolved authority requires authority and source only.")
        elif self.authority is not None or self.source is not None:
            raise ValueError("An authority question cannot claim a resolved authority.")
        return self


class GuidedStepCheckpointV2(_CreativeSessionModel):
    checkpoint_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    session_revision: int = Field(ge=1)
    stage_kind: GuidanceStageKindV2 | None = None
    status: Literal["pending", "waiting_user", "completed", "failed", "superseded"]
    trigger: Literal["user_message", "proposal_action", "continuation", "recovery"]
    action_id: str | None = Field(default=None, max_length=160)


class GuidanceStagePolicyResultV2(_CreativeSessionModel):
    allowed_stage_kinds: tuple[GuidanceStageKindV2, ...]
    recommended_stage_kinds: tuple[GuidanceStageKindV2, ...]
    unresolved_element_kinds: tuple[CreativeElementKindV2, ...] = ()
    blocking_facts: tuple[str, ...] = Field(default=(), max_length=32)
    completion_allowed: bool


class GuidedSessionStateV2(_CreativeSessionModel):
    session_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    status: Literal["active", "paused", "completed"]
    goal: CreativeGoalV2
    creative_authority: CreativeAuthorityStateV2 | None = None
    current_checkpoint: GuidedStepCheckpointV2 | None = None
    narrative_direction: str | None = Field(default=None, max_length=4_096)
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


class DelegatedProposalChoiceV2(_CreativeSessionModel):
    option_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=2_048)


class GuidanceSessionActionV2(_CreativeSessionModel):
    action_id: str = Field(min_length=1, max_length=160)
    logical_key: str = Field(min_length=1, max_length=256)
    action: Literal[
        "stop_guidance",
        "resume_guidance",
        "set_creative_authority",
    ]
    state: Literal["pending", "applying", "applied", "superseded", "failed"]
    creating_turn_id: str = Field(min_length=1, max_length=160)
    expected_session_revision: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    confirmation_required: bool
    reason: str = Field(min_length=1, max_length=1_024)
    authority: CreativeAuthorityV2 | None = None


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
    parameter_provenance: dict[str, CanvasParameterProvenanceV2] = Field(default_factory=dict)
    prompt_context_snapshot_id: str | None = Field(default=None, max_length=160)
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
    capability_id: CapabilityIdV1
    capability_display_name: str = Field(min_length=1, max_length=160)
    operation: str = Field(min_length=1, max_length=160)
    status: Literal["working", "completed", "failed"]
    error_code: str | None = Field(default=None, max_length=160)
    error_message: str | None = Field(default=None, max_length=1_024)
    created_at: datetime
    updated_at: datetime | None = None


class ResolvedImageTargetV2(_CreativeSessionModel):
    asset_id: str = Field(min_length=1, max_length=160)
    owner_node_id: str | None = Field(default=None, max_length=160)
    owner_semantic_role: str | None = Field(default=None, max_length=160)
    capability_id: CapabilityIdV1
    display_name: str = Field(min_length=1, max_length=256)
    checksum: str = Field(min_length=1, max_length=160)
