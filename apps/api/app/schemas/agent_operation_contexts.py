"""Strict, operation-specific contexts for V2 Pi planning calls."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_canvas_creative_session import (
    CreationModeDecisionV2,
    CreativeSessionStateV2,
    ProjectCreativeMemoryV2,
    ResolvedImageTargetV2,
)


_MAX_CONTEXT_TEXT = 65_536
_MAX_COLLECTION_ITEMS = 128
_MAX_SAFE_PAYLOAD_BYTES = 65_536
_FORBIDDEN_KEY_PARTS = (
    "api_key",
    "authorization",
    "complete_workflow",
    "credential",
    "media_bytes",
    "provider_payload",
    "secret",
    "sibling_provider_prompt",
    "token",
    "workflow_json",
)
_FORBIDDEN_TEXT_MARKERS = (
    "api_key=",
    "authorization:",
    "bearer ",
    "credential=",
    "secret=",
    "token=",
    "data:",
)


class _PlanningContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def reject_unsafe_context(cls, value: Any) -> Any:
        _validate_planning_value(value)
        return value


def _validate_planning_value(value: Any) -> None:
    if len(str(value).encode("utf-8")) > _MAX_SAFE_PAYLOAD_BYTES:
        raise ValueError("planning context exceeds the internal payload limit")

    def visit(current: Any, key: str | None = None) -> None:
        normalized_key = key.casefold() if key else ""
        if normalized_key and any(part in normalized_key for part in _FORBIDDEN_KEY_PARTS):
            raise ValueError("planning context contains a forbidden field")
        if isinstance(current, dict):
            for child_key, child_value in current.items():
                visit(child_value, str(child_key))
            return
        if isinstance(current, (list, tuple)):
            for child in current:
                visit(child)
            return
        if isinstance(current, (bytes, bytearray, memoryview)):
            raise ValueError("planning context cannot contain media bytes")
        if isinstance(current, str):
            folded = current.casefold()
            if current.startswith(("/", "\\\\")):
                raise ValueError("planning context cannot contain an absolute path")
            if any(marker in folded for marker in _FORBIDDEN_TEXT_MARKERS):
                raise ValueError("planning context cannot contain credentials")

    visit(value)


class FrozenPlanningFacts(_PlanningContextModel):
    product_name: str | None = Field(default=None, max_length=256)
    user_language: str | None = Field(default=None, max_length=32)
    duration_seconds: float | None = Field(default=None, gt=0, le=3_600)
    aspect_ratio: str | None = Field(default=None, max_length=32)
    character_count: int | None = Field(default=None, ge=0, le=128)
    scene_count: int | None = Field(default=None, ge=0, le=128)
    shot_count: int | None = Field(default=None, ge=0, le=256)
    explicit_requirements: tuple[str, ...] = Field(
        default=(),
        max_length=_MAX_COLLECTION_ITEMS,
    )


class PlanningReferenceSummary(_PlanningContextModel):
    asset_id: str = Field(min_length=1, max_length=160)
    version_id: str | None = Field(default=None, max_length=160)
    semantic_type: str = Field(min_length=1, max_length=80)
    display_name: str = Field(default="", max_length=256)
    media_type: Literal["image", "video", "audio", "text"] | None = None
    description: str = Field(default="", max_length=2_048)


class PlanningItemSummary(_PlanningContextModel):
    item_id: str = Field(min_length=1, max_length=160)
    item_type: str = Field(min_length=1, max_length=80)
    display_name: str = Field(default="", max_length=256)
    description: str = Field(default="", max_length=4_096)


class PlanningSlotSummary(_PlanningContextModel):
    slot_id: str = Field(min_length=1, max_length=160)
    slot_type: str = Field(min_length=1, max_length=80)
    required: bool = True


class _PlanningAgentContext(_PlanningContextModel):
    user_input: str = Field(min_length=1, max_length=_MAX_CONTEXT_TEXT)
    user_language: str | None = Field(default=None, max_length=32)
    workflow_id: str | None = Field(default=None, max_length=160)
    frozen_facts: FrozenPlanningFacts
    reference_summaries: tuple[PlanningReferenceSummary, ...] = Field(
        default=(),
        max_length=_MAX_COLLECTION_ITEMS,
    )


class FrontDeskIntentAgentContext(_PlanningAgentContext):
    context_kind: Literal["front_desk_intent"]
    conversation_summary: str | None = Field(default=None, max_length=16_384)


class IntentContractAgentContext(_PlanningAgentContext):
    context_kind: Literal["intent_contract"]
    ad_request_summary: str = Field(min_length=1, max_length=16_384)


class ScriptWriterAgentContext(_PlanningAgentContext):
    context_kind: Literal["script_writer"]
    ad_request_summary: str = Field(min_length=1, max_length=16_384)
    item_inventory: tuple[PlanningItemSummary, ...] = Field(
        default=(),
        max_length=_MAX_COLLECTION_ITEMS,
    )


class _ExpertAgentContext(_PlanningAgentContext):
    screenplay_slice: str = Field(default="", max_length=32_768)
    item_inventory: tuple[PlanningItemSummary, ...] = Field(
        default=(),
        max_length=_MAX_COLLECTION_ITEMS,
    )
    slot_contracts: tuple[PlanningSlotSummary, ...] = Field(
        default=(),
        max_length=_MAX_COLLECTION_ITEMS,
    )
    style_scope: str = Field(default="", max_length=8_192)


class ProductExpertAgentContext(_ExpertAgentContext):
    context_kind: Literal["product_expert"]


class CharacterExpertAgentContext(_ExpertAgentContext):
    context_kind: Literal["character_expert"]


class SceneExpertAgentContext(_ExpertAgentContext):
    context_kind: Literal["scene_expert"]


class BgmExpertAgentContext(_ExpertAgentContext):
    context_kind: Literal["bgm_expert"]
    music_constraints: tuple[str, ...] = Field(
        default=(),
        max_length=_MAX_COLLECTION_ITEMS,
    )


class InteractionMessageSummary(_PlanningContextModel):
    sequence_no: int = Field(ge=1)
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=4_096)


class InteractionTargetSummary(_PlanningContextModel):
    target_locator: str = Field(min_length=1, max_length=320)
    node_id: Literal["character-generation", "scene-generation"]
    item_id: str = Field(min_length=1, max_length=160)
    slot_id: str = Field(min_length=1, max_length=240)
    slot_type: str = Field(min_length=1, max_length=80)
    owner_type: Literal["character", "scene"]
    owner_display_name: str = Field(min_length=1, max_length=256)
    current_prompt: str | None = Field(default=None, max_length=16_384)
    expected_revision: int = Field(ge=1)
    related_multiview_slot_id: str | None = Field(default=None, max_length=240)
    selected_version: PlanningReferenceSummary | None = None
    working_version: PlanningReferenceSummary | None = None


class TargetedRevisionAgentContext(_PlanningContextModel):
    context_kind: Literal["targeted_revision"]
    user_input: str = Field(min_length=1, max_length=_MAX_CONTEXT_TEXT)
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str | None = Field(default=None, max_length=160)
    target: InteractionTargetSummary
    conversation_summary: str = Field(default="", max_length=16_384)
    recent_messages: tuple[InteractionMessageSummary, ...] = Field(
        default=(),
        max_length=32,
    )
    screenplay_slice: str = Field(default="", max_length=16_384)
    style_scope: str = Field(default="", max_length=8_192)
    continuity_slice: str = Field(default="", max_length=8_192)
    reference_summaries: tuple[PlanningReferenceSummary, ...] = Field(
        default=(),
        max_length=_MAX_COLLECTION_ITEMS,
    )


class QuickMediaAgentContext(_PlanningContextModel):
    context_kind: Literal["quick_media"]
    user_input: str = Field(min_length=1, max_length=_MAX_CONTEXT_TEXT)
    workflow_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    item_id: str = Field(min_length=1, max_length=160)
    slot_id: str = Field(min_length=1, max_length=240)
    output_media_type: Literal["image", "video", "audio"]
    negative_prompt: str | None = Field(default=None, max_length=8_192)
    style_scope: str = Field(default="", max_length=8_192)
    reference_summaries: tuple[PlanningReferenceSummary, ...] = Field(
        default=(),
        max_length=_MAX_COLLECTION_ITEMS,
    )


class WorkflowConversationAgentContext(_PlanningContextModel):
    context_kind: Literal["workflow_conversation"]
    user_input: str = Field(min_length=1, max_length=_MAX_CONTEXT_TEXT)
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    conversation_summary: str = Field(default="", max_length=16_384)
    recent_messages: tuple[InteractionMessageSummary, ...] = Field(
        default=(),
        max_length=32,
    )
    workflow_summary: str = Field(default="", max_length=16_384)


class ConversationSummaryAgentContext(_PlanningContextModel):
    context_kind: Literal["conversation_summary"]
    user_input: str = Field(min_length=1, max_length=_MAX_CONTEXT_TEXT)
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    previous_summary: str = Field(default="", max_length=16_384)
    recent_messages: tuple[InteractionMessageSummary, ...] = Field(
        default=(),
        max_length=32,
    )


AgentCanvasSpecialistName = Literal[
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


class DirectorTurnContextV2(_PlanningContextModel):
    context_kind: Literal["director_turn"]
    workflow_id: str = Field(min_length=1, max_length=160)
    workflow_revision: int = Field(ge=1)
    conversation_id: str = Field(min_length=1, max_length=160)
    user_input: str = Field(min_length=1, max_length=_MAX_CONTEXT_TEXT)
    mentioned_node_ids: tuple[str, ...] = Field(default=(), max_length=16)
    mentioned_image_asset_ids: tuple[str, ...] = Field(default=(), max_length=16)
    recent_messages: tuple[InteractionMessageSummary, ...] = Field(
        default=(),
        max_length=16,
    )
    script_summary: str = Field(default="", max_length=8_192)
    video_skill_excerpt: str = Field(default="", max_length=8_192)
    explicit_input_summaries: tuple[str, ...] = Field(default=(), max_length=64)
    candidate_summaries: tuple[str, ...] = Field(default=(), max_length=32)
    creative_session: CreativeSessionStateV2 | None = None
    creative_memory: ProjectCreativeMemoryV2 | None = None
    resolved_image_targets: tuple[ResolvedImageTargetV2, ...] = Field(default=(), max_length=16)
    creation_mode_decision: CreationModeDecisionV2 | None = None
    approved_anchor_digest: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )


class AgentCommandReplanContextV2(_PlanningContextModel):
    context_kind: Literal["agent_command_replan"]
    workflow_id: str = Field(min_length=1, max_length=160)
    workflow_revision: int = Field(ge=1)
    conversation_id: str = Field(min_length=1, max_length=160)
    original_user_intent: str = Field(min_length=1, max_length=_MAX_CONTEXT_TEXT)
    original_plan_summary: str = Field(min_length=1, max_length=8_192)
    current_target_summaries: tuple[str, ...] = Field(default=(), max_length=16)
    conflict_code: Literal["workflow_revision_conflict"]
    replan_attempt: Literal[1] = 1


class CreativeAnchorSetV2(_PlanningContextModel):
    subject_product: tuple[str, ...] = Field(default=(), max_length=16)
    audience: str = Field(default="", max_length=2_000)
    campaign_goal: str = Field(default="", max_length=4_000)
    duration: str = Field(default="", max_length=256)
    aspect_ratio: str = Field(default="", max_length=32)
    approved_facts: tuple[str, ...] = Field(default=(), max_length=32)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @property
    def has_protected_values(self) -> bool:
        return bool(
            self.subject_product
            or self.audience
            or self.campaign_goal
            or self.duration
            or self.aspect_ratio
            or self.approved_facts
        )


class ProposalRevisionOptionV2(_PlanningContextModel):
    option_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=256)
    summary: str = Field(min_length=1, max_length=8_192)


class ProposalRevisionContextV2(_PlanningContextModel):
    source_proposal_id: str = Field(min_length=1, max_length=160)
    source_proposal_revision: int = Field(ge=1)
    prior_options: tuple[ProposalRevisionOptionV2, ...] = Field(
        min_length=1,
        max_length=4,
    )
    approved_anchors: CreativeAnchorSetV2
    topic_objective: str = Field(default="", max_length=4_000)
    user_instruction: str = Field(min_length=1, max_length=_MAX_CONTEXT_TEXT)
    mutable_dimensions: tuple[
        Literal[
            "style",
            "lighting",
            "composition",
            "camera",
            "copy",
            "pacing",
            "audio",
            "other",
        ],
        ...,
    ] = Field(default=(), max_length=8)
    replace_whole_concept: bool = False
    relevant_target_summaries: tuple[str, ...] = Field(default=(), max_length=16)


class SpecialistContextV2(_PlanningContextModel):
    context_kind: Literal["specialist_handoff"]
    specialist_name: AgentCanvasSpecialistName
    operation: Literal[
        "propose_concepts",
        "revise_concepts",
        "materialize_draft",
        "direct_response",
    ]
    workflow_id: str = Field(min_length=1, max_length=160)
    workflow_revision: int = Field(ge=1)
    user_instruction: str = Field(min_length=1, max_length=_MAX_CONTEXT_TEXT)
    target_node_id: str | None = Field(default=None, max_length=160)
    selected_option_summary: str = Field(default="", max_length=8_192)
    selected_option_id: str | None = Field(default=None, max_length=160)
    script_summary: str = Field(default="", max_length=8_192)
    video_skill_excerpt: str = Field(default="", max_length=8_192)
    explicit_input_summaries: tuple[str, ...] = Field(default=(), max_length=64)
    creative_session: CreativeSessionStateV2 | None = None
    creative_memory: ProjectCreativeMemoryV2 | None = None
    resolved_image_targets: tuple[ResolvedImageTargetV2, ...] = Field(default=(), max_length=16)
    reference_allowlist: tuple[str, ...] = Field(default=(), max_length=64)
    current_topic_id: str | None = Field(default=None, max_length=160)
    proposal_mode: Literal["single_plan", "choice_set"] | None = None
    candidate_count: int | None = Field(default=None, ge=1, le=4)
    approved_anchor_summaries: tuple[str, ...] = Field(default=(), max_length=16)
    proposal_revision: ProposalRevisionContextV2 | None = None


PlanningAgentContext = Annotated[
    Union[
        FrontDeskIntentAgentContext,
        IntentContractAgentContext,
        ScriptWriterAgentContext,
        ProductExpertAgentContext,
        CharacterExpertAgentContext,
        SceneExpertAgentContext,
        BgmExpertAgentContext,
        TargetedRevisionAgentContext,
        QuickMediaAgentContext,
        WorkflowConversationAgentContext,
        ConversationSummaryAgentContext,
        DirectorTurnContextV2,
        AgentCommandReplanContextV2,
        SpecialistContextV2,
    ],
    Field(discriminator="context_kind"),
]
