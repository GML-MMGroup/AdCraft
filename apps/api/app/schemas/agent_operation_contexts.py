"""Strict, operation-specific contexts for V2 Pi planning calls."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.agent_canvas_creative_session import (
    CreationModeDecisionV2,
    GuidedSessionStateV2,
    ProjectCreativeMemoryV2,
    ResolvedImageTargetV2,
    StyleGuidanceContextV2,
)
from app.schemas.language import BCP47Tag
from app.schemas.agent_working_documents import AgentDocumentContextExcerptV2


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


class AssetRevisionAgentContext(_PlanningContextModel):
    context_kind: Literal["asset_revision"]
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


class _WorkflowContextModel(_PlanningContextModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkflowWorkItemSummaryV1(_WorkflowContextModel):
    node_id: str = Field(min_length=1, max_length=160)
    node_type: Literal["text", "script", "image", "video", "audio", "editing"]
    title: str = Field(min_length=1, max_length=256)
    node_revision: int = Field(ge=1)
    node_status: Literal["draft", "working", "ready", "failed"]
    execution_id: str | None = Field(default=None, min_length=1, max_length=160)
    execution_state: str | None = Field(default=None, min_length=1, max_length=80)
    prompt_preparation_state: str | None = Field(default=None, min_length=1, max_length=80)
    output_available: bool = False
    failure_code: str | None = Field(default=None, min_length=1, max_length=160)


class WorkflowActionSummaryV1(_WorkflowContextModel):
    action_id: str = Field(min_length=1, max_length=160)
    action_kind: str = Field(min_length=1, max_length=80)
    stage: str = Field(min_length=1, max_length=80)
    stage_revision: int = Field(ge=1)
    status: str = Field(min_length=1, max_length=80)
    objective: str = Field(default="", max_length=2_048)
    ownership_status: Literal["owned", "awaiting", "orphaned", "inconsistent"]
    owner_kind: (
        Literal[
            "continuation",
            "runtime_execution",
            "post_ready_effect",
            "guided_media_resume",
            "typed_awaiting",
        ]
        | None
    ) = None
    owner_id: str | None = Field(default=None, min_length=1, max_length=160)
    owner_state: str | None = Field(default=None, min_length=1, max_length=80)
    turn_id: str | None = Field(default=None, min_length=1, max_length=160)
    turn_status: str | None = Field(default=None, min_length=1, max_length=80)
    continuation_id: str | None = Field(default=None, min_length=1, max_length=160)
    continuation_status: str | None = Field(default=None, min_length=1, max_length=80)
    error_code: str | None = Field(default=None, min_length=1, max_length=160)
    leaf_error_code: str | None = Field(default=None, min_length=1, max_length=160)
    awaiting_id: str | None = Field(default=None, min_length=1, max_length=160)
    blocker_class: (
        Literal[
            "unrecoverable",
            "user_action_required",
            "automatic_work_in_progress",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_ownership(self) -> "WorkflowActionSummaryV1":
        has_owner = self.owner_kind is not None or self.owner_id is not None
        if self.ownership_status == "owned":
            if self.owner_kind is None or self.owner_id is None:
                raise ValueError("Owned action requires an exact owner kind and owner identity.")
            if self.owner_kind == "typed_awaiting":
                raise ValueError("Owned automatic action cannot use typed_awaiting as its owner.")
        elif self.ownership_status == "awaiting":
            if self.owner_kind != "typed_awaiting" or self.owner_id is None:
                raise ValueError("Awaiting action requires a typed_awaiting owner identity.")
            if self.awaiting_id is None:
                raise ValueError("Awaiting action requires its typed awaiting identity.")
        elif has_owner:
            raise ValueError("Orphaned or inconsistent action cannot claim an owner.")
        return self


class WorkflowDocumentReferenceV1(_WorkflowContextModel):
    document_id: str = Field(min_length=1, max_length=160)
    document_kind: Literal["anchor_registry", "storyboard_production_plan"]
    revision: int = Field(ge=1)
    content_digest: str = Field(pattern=r"^(sha256:)?[a-f0-9]{64}$")


class WorkflowContextTruncationV1(_WorkflowContextModel):
    omitted_active_work: int = Field(default=0, ge=0)
    omitted_blockers: int = Field(default=0, ge=0)
    omitted_documents: int = Field(default=0, ge=0)


class WorkflowStateCapsuleV1(_WorkflowContextModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    workflow_revision: int = Field(ge=1)
    response_locale: BCP47Tag = "und"
    guidance_session_id: str | None = Field(default=None, min_length=1, max_length=160)
    guidance_session_revision: int | None = Field(default=None, ge=1)
    journey_stage: str | None = Field(default=None, min_length=1, max_length=80)
    journey_status: str | None = Field(default=None, min_length=1, max_length=80)
    requirement_revision_id: str | None = Field(default=None, min_length=1, max_length=160)
    requirement_revision_no: int | None = Field(default=None, ge=1)
    requirement_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    node_status_counts: dict[Literal["draft", "working", "ready", "failed"], int] = Field(
        default_factory=dict
    )
    active_work: tuple[WorkflowWorkItemSummaryV1, ...] = Field(default=(), max_length=64)
    blockers: tuple[WorkflowActionSummaryV1, ...] = Field(default=(), max_length=32)
    current_action: WorkflowActionSummaryV1 | None = None
    awaiting_action: WorkflowActionSummaryV1 | None = None
    next_valid_action: WorkflowActionSummaryV1 | None = None
    documents: tuple[WorkflowDocumentReferenceV1, ...] = Field(default=(), max_length=2)
    projection_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    truncation: WorkflowContextTruncationV1 = Field(default_factory=WorkflowContextTruncationV1)

    @model_validator(mode="after")
    def validate_capsule(self) -> "WorkflowStateCapsuleV1":
        if len(self.model_dump_json().encode("utf-8")) > 8_192:
            raise ValueError("Workflow state capsule exceeds the 8 KiB limit.")
        if self.awaiting_action is not None and self.awaiting_action.ownership_status != "awaiting":
            raise ValueError("Awaiting action projection must have awaiting ownership.")
        if self.next_valid_action is not None and self.current_action is not None:
            if self.current_action.ownership_status in {"orphaned", "inconsistent"}:
                raise ValueError("Unsafe current action suppresses the next valid action.")
        document_kinds = tuple(item.document_kind for item in self.documents)
        if len(document_kinds) != len(set(document_kinds)):
            raise ValueError("Workflow document references must have unique kinds.")
        return self


from app.schemas.agent_canvas_capabilities import NextActionContextV1  # noqa: E402


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
    workflow_revision: int | None = Field(default=None, ge=0)
    response_locale: BCP47Tag = "und"
    journey_stage: str | None = Field(default=None, max_length=80)
    journey_status: str | None = Field(default=None, max_length=80)
    awaiting_action: NextActionContextV1 | None = None
    next_action: NextActionContextV1 | None = None
    source_revision: int | None = Field(default=None, ge=0)
    workflow_context: WorkflowStateCapsuleV1 | None = None
    document_excerpt: AgentDocumentContextExcerptV2 | None = None


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


class VideoParameterTextSourceV2(_PlanningContextModel):
    source_kind: Literal["node_prompt", "binding"]
    source_node_id: str = Field(min_length=1, max_length=160)
    source_revision: int = Field(ge=1)
    binding_id: str | None = Field(default=None, min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=32_768)

    @model_validator(mode="after")
    def validate_binding_identity(self) -> "VideoParameterTextSourceV2":
        if self.source_kind == "binding" and self.binding_id is None:
            raise ValueError("Binding parameter sources require a Binding ID.")
        if self.source_kind == "node_prompt" and self.binding_id is not None:
            raise ValueError("Node prompt parameter sources cannot claim a Binding ID.")
        return self


class VideoParameterCapabilityContextV2(_PlanningContextModel):
    supported_parameters: tuple[str, ...]
    duration_seconds_min: float | None = Field(default=None, gt=0)
    duration_seconds_max: float | None = Field(default=None, gt=0)
    supported_resolutions: tuple[str, ...] = ()
    supported_aspect_ratios: tuple[str, ...] = ()
    supports_native_audio: bool
    default_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    capability_revision: int = Field(ge=1)


class VideoParameterIntentContextV2(_PlanningContextModel):
    context_kind: Literal["video_parameter_intent"]
    workflow_id: str = Field(min_length=1, max_length=160)
    target_node_id: str = Field(min_length=1, max_length=160)
    target_node_revision: int = Field(ge=1)
    selected_model_ref: str = Field(min_length=3, max_length=320)
    sources: tuple[VideoParameterTextSourceV2, ...] = Field(default=(), max_length=129)
    capability: VideoParameterCapabilityContextV2


class VideoParameterTextSourceV3(_PlanningContextModel):
    source_ref: str = Field(min_length=1, max_length=80, pattern=r"^source_[1-9][0-9]*$")
    text: str = Field(min_length=1, max_length=32_768)


class VideoParameterIntentContextV3(_PlanningContextModel):
    context_kind: Literal["video_parameter_intent_v3"]
    workflow_id: str = Field(min_length=1, max_length=160)
    unresolved_fields: tuple[
        Literal["duration_seconds", "resolution", "aspect_ratio", "generate_audio"], ...
    ] = Field(min_length=1, max_length=4)
    sources: tuple[VideoParameterTextSourceV3, ...] = Field(min_length=1, max_length=129)
    capability: VideoParameterCapabilityContextV2

    @model_validator(mode="after")
    def validate_scope(self) -> "VideoParameterIntentContextV3":
        if len(self.unresolved_fields) != len(set(self.unresolved_fields)):
            raise ValueError("Unresolved Video parameter fields must be unique.")
        if not set(self.unresolved_fields).issubset(set(self.capability.supported_parameters)):
            raise ValueError("Unresolved fields must be supported by the selected capability.")
        refs = tuple(source.source_ref for source in self.sources)
        if len(refs) != len(set(refs)):
            raise ValueError("Video parameter source refs must be unique.")
        return self


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
    style_guidance: StyleGuidanceContextV2 | None = None
    explicit_input_summaries: tuple[str, ...] = Field(default=(), max_length=64)
    candidate_summaries: tuple[str, ...] = Field(default=(), max_length=32)
    guidance_session: GuidedSessionStateV2 | None = None
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


PlanningAgentContext = Annotated[
    Union[
        FrontDeskIntentAgentContext,
        IntentContractAgentContext,
        ScriptWriterAgentContext,
        ProductExpertAgentContext,
        CharacterExpertAgentContext,
        SceneExpertAgentContext,
        BgmExpertAgentContext,
        AssetRevisionAgentContext,
        QuickMediaAgentContext,
        WorkflowConversationAgentContext,
        ConversationSummaryAgentContext,
        DirectorTurnContextV2,
        AgentCommandReplanContextV2,
        VideoParameterIntentContextV3,
    ],
    Field(discriminator="context_kind"),
]
