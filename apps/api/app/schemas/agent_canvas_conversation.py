"""Durable conversation, proposal, and Video Skill contracts for Agent Canvas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, computed_field, model_validator

from app.schemas.agent_canvas_capability_identity import (
    CAPABILITY_DISPLAY_NAMES,
    CapabilityIdV1,
)
from app.schemas.agent_canvas_commands import AgentPlacementHintV2
from app.schemas.agent_canvas_continuation import ContinuationOperationV2
from app.schemas.agent_canvas_creative_session import (
    CreationModeDecisionV2,
    CreativeAuthorityV2,
    GuidanceSessionActionV2,
    GuidedSessionStateV2,
    ProposedDraftReferenceV2,
)
from app.schemas.agent_runtime import (
    AgentCommandPlanV2,
    AgentOperationResultV2,
)
from app.schemas.agent_canvas_video_skills import VideoSkillPublicDetailV2
from app.schemas.agent_operation_recovery import AgentOperationFailureV2
from app.schemas.agent_canvas_guidance import GuidanceAdvancePreconditionV1


class _ConversationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _compact_option_schema(schema: dict[str, object]) -> None:
    properties = schema.get("properties")
    if isinstance(properties, dict):
        properties.pop("key_decisions", None)
    required = schema.get("required")
    if isinstance(required, list):
        schema["required"] = [item for item in required if item != "key_decisions"]


class ChatMessageRequestV2(_ConversationModel):
    text: str = Field(min_length=1, max_length=32_768)
    mentioned_node_ids: tuple[str, ...] = Field(default=(), max_length=16)
    mentioned_image_asset_ids: tuple[str, ...] = Field(default=(), max_length=16)
    video_skill_run_id: str | None = Field(default=None, max_length=160)


class ChatTurnAcceptedV2(_ConversationModel):
    workflow_id: str
    conversation_id: str
    message_id: str | None
    turn_id: str
    status: Literal["queued"] = "queued"
    events_cursor: int = Field(ge=0)
    retry_of_turn_id: str | None = Field(default=None, min_length=1, max_length=160)
    retry_attempt_no: int = Field(default=1, ge=1)
    replayed: bool = False


class ChatTurnRetryRequestV1(_ConversationModel):
    expected_session_revision: int = Field(ge=0)
    expected_workflow_revision: int = Field(ge=1)


class ContinuationDeliveryV2(_ConversationModel):
    continuation_id: str
    workflow_id: str
    conversation_id: str
    source_turn_id: str
    continuation_turn_id: str
    operation: ContinuationOperationV2
    envelope_id: str = Field(exclude=True)
    payload_digest: str
    status: Literal[
        "queued",
        "leased",
        "retry_wait",
        "completed",
        "failed",
        "superseded",
    ]
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    next_attempt_at: datetime
    lease_owner: str | None = None
    lease_generation: int = Field(ge=0)
    lease_expires_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class ContinuationCommitV2(_ConversationModel):
    continuation_id: str
    continuation_turn_id: str
    source_turn_id: str
    source_action_id: str
    idempotency_key: str
    video_skill_run_id: str | None = None
    max_attempts: int = Field(default=5, ge=1)


class ChatTurnV2(_ConversationModel):
    turn_id: str
    workflow_id: str
    conversation_id: str
    status: Literal["queued", "running", "completed", "failed", "superseded"]
    turn_kind: Literal[
        "message",
        "proposal_action",
        "command_action",
        "guided_action",
        "capability",
        "next_action",
        "guidance_advance",
    ]
    request: dict[str, JsonValue]
    creation_mode: CreationModeDecisionV2 | None = None
    guidance_session_revision: int | None = Field(default=None, ge=1)
    continuation: ContinuationDeliveryV2 | None = None
    retry_of_turn_id: str | None = Field(default=None, min_length=1, max_length=160)
    retry_attempt_no: int = Field(default=1, ge=1)
    retryable: bool = False
    operation_stage: str | None = Field(default=None, min_length=1, max_length=120)
    operation_failure: AgentOperationFailureV2 | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_terminal_retryability(self) -> "ChatTurnV2":
        if self.status == "superseded" and self.retryable:
            raise ValueError("Superseded turns are terminal and non-retryable.")
        return self


class ChatTimelineEntryV2(_ConversationModel):
    entry_id: str
    workflow_id: str
    conversation_id: str
    sequence_no: int = Field(ge=1)
    entry_type: Literal[
        "message",
        "script_artifact",
        "concept_proposal",
        "expert_activity",
        "planning_progress",
        "command_plan",
        "action_receipt",
        "agent_document_reference",
        "decision_bundle",
    ]
    speaker: Literal["user", "adcraft_video_agent"] | None
    content: str
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    command_plan: AgentCommandPlanV2 | None = None
    action_receipt: "AgentActionReceiptV2 | None" = None
    created_at: datetime


class ChatTimelinePresentationItemV2(ChatTimelineEntryV2):
    presentation_key: str = Field(min_length=1, max_length=320)
    presentation_revision: int = Field(ge=1)
    source_entry_ids: tuple[str, ...] = Field(min_length=1, max_length=256)
    message_key: str | None = Field(default=None, min_length=1, max_length=160)
    message_args: dict[str, JsonValue] = Field(default_factory=dict)
    response_locale: str = Field(default="und", min_length=2, max_length=64)


class ChatTimelineListResponseV2(_ConversationModel):
    workflow_id: str
    conversation_id: str | None
    guidance_session: GuidedSessionStateV2 | None = None
    continuations: tuple[ContinuationDeliveryV2, ...] = ()
    current_session_actions: tuple[GuidanceSessionActionV2, ...] = Field(
        default=(),
        max_length=2,
    )
    guidance_advance_precondition: GuidanceAdvancePreconditionV1 | None = None
    items: tuple[ChatTimelineEntryV2, ...] = ()
    presentation_items: tuple[ChatTimelinePresentationItemV2, ...] = ()
    next_cursor: int = Field(ge=0)


class ConceptOptionRecordV2(_ConversationModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra=_compact_option_schema)

    option_id: str
    title: str = Field(min_length=1, max_length=256)
    public_summary: str = Field(min_length=1, max_length=8_192)
    key_decisions: tuple[Annotated[str, Field(min_length=1, max_length=1_024)], ...] = Field(
        default=(), max_length=6, exclude=True
    )


class ProposalMaterializationErrorV2(_ConversationModel):
    code: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=2_048)


class ProposalMaterializationProjectionV2(_ConversationModel):
    materialization_id: str = Field(min_length=1, max_length=160)
    option_id: str = Field(min_length=1, max_length=160)
    turn_id: str = Field(min_length=1, max_length=160)
    status: Literal["queued", "working", "failed", "completed"]
    attempt_no: int = Field(ge=1)
    retryable: bool
    error: ProposalMaterializationErrorV2 | None = None
    created_at: datetime
    updated_at: datetime


class _ConceptProposalBaseV2(_ConversationModel):
    proposal_kind: Literal[
        "world_setting",
        "script",
        "product",
        "prop",
        "character",
        "scene",
        "storyboard",
        "video",
        "bgm",
    ]
    capability_id: CapabilityIdV1
    proposal_card_schema_version: int = Field(default=1, ge=1, exclude=True)
    options: tuple[ConceptOptionRecordV2, ...] = Field(min_length=1, max_length=3)
    proposed_references: tuple[ProposedDraftReferenceV2, ...] = Field(
        default=(),
        max_length=64,
    )
    topic_id: str | None = Field(default=None, max_length=160)
    target_node_id: str | None = Field(default=None, max_length=160)
    target_node_revision: int | None = Field(default=None, ge=1)
    proposal_purpose: str | None = Field(default=None, max_length=4_096)
    preserved_anchor_digest: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
        exclude=True,
    )

    @computed_field
    @property
    def capability_display_name(self) -> str:
        return CAPABILITY_DISPLAY_NAMES[self.capability_id]

    @model_validator(mode="after")
    def validate_proposal_shape(self) -> "_ConceptProposalBaseV2":
        option_ids = tuple(option.option_id for option in self.options)
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("Concept option IDs must be unique within a proposal.")
        if (self.target_node_id is None) != (self.target_node_revision is None):
            raise ValueError("Targeted proposals require both target node ID and revision.")
        return self


class ConceptProposalCreateV2(_ConceptProposalBaseV2):
    @model_validator(mode="after")
    def validate_public_cardinality(self) -> "ConceptProposalCreateV2":
        if len(self.options) != 3:
            raise ValueError("Public concept proposals require exactly three options.")
        return self


ProposalAvailabilityV2 = Literal["open", "applied", "superseded"]


ProposalActionTypeV2 = Literal[
    "select_option",
    "custom_direction",
    "revise_options",
    "defer_topic",
    "exclude_element",
    "delegate_choice",
    "reuse_direction",
    "revise_direction",
]


class ProposalActionDescriptorV2(_ConversationModel):
    action_id: str = Field(min_length=1, max_length=160)
    action: ProposalActionTypeV2
    label: str = Field(min_length=1, max_length=160)
    proposal_id: str = Field(min_length=1, max_length=160)
    expected_session_revision: int = Field(ge=1)
    confirmation_required: bool
    reason: str = Field(min_length=1, max_length=1_024)
    option_id: str | None = Field(default=None, min_length=1, max_length=160)
    enabled: bool = True
    disabled_reason: str | None = Field(default=None, max_length=1_024)


class _ProposalActionBaseV2(_ConversationModel):
    action_id: str = Field(min_length=1, max_length=160)
    expected_session_revision: int = Field(ge=1)


class SelectOptionActionV2(_ProposalActionBaseV2):
    action: Literal["select_option"]
    option_id: str = Field(min_length=1, max_length=160)
    accepted_references: tuple[ProposedDraftReferenceV2, ...] = Field(
        default=(),
        max_length=64,
    )


class CustomDirectionActionV2(_ProposalActionBaseV2):
    action: Literal["custom_direction"]
    custom_text: str = Field(min_length=1, max_length=2_048)


class ReviseOptionsActionV2(_ProposalActionBaseV2):
    action: Literal["revise_options"]
    instruction: str = Field(min_length=1, max_length=8_192)


class DeferTopicActionV2(_ProposalActionBaseV2):
    action: Literal["defer_topic"]


class ExcludeElementActionV2(_ProposalActionBaseV2):
    action: Literal["exclude_element"]


class DelegateChoiceActionV2(_ProposalActionBaseV2):
    action: Literal["delegate_choice"]


class ReuseDirectionActionV2(_ProposalActionBaseV2):
    action: Literal["reuse_direction"]
    option_id: str = Field(min_length=1, max_length=160)


class ReviseDirectionActionV2(_ProposalActionBaseV2):
    action: Literal["revise_direction"]
    option_id: str = Field(min_length=1, max_length=160)
    instruction: str = Field(min_length=1, max_length=8_192)


ProposalActionRequestV2 = Annotated[
    SelectOptionActionV2
    | CustomDirectionActionV2
    | ReviseOptionsActionV2
    | DeferTopicActionV2
    | ExcludeElementActionV2
    | DelegateChoiceActionV2
    | ReuseDirectionActionV2
    | ReviseDirectionActionV2,
    Field(discriminator="action"),
]


class ProposalApplicationSummaryV2(_ConversationModel):
    application_id: str = Field(min_length=1, max_length=160)
    option_id: str = Field(min_length=1, max_length=160)
    action: Literal[
        "select_option",
        "custom_direction",
        "delegate_choice",
        "reuse_direction",
    ]
    receipt_id: str = Field(min_length=1, max_length=160)
    created_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    queued_execution_ids: tuple[str, ...] = Field(default=(), max_length=32)
    created_at: datetime


class ConceptProposalV2(_ConceptProposalBaseV2):
    proposal_id: str
    workflow_id: str
    turn_id: str
    video_skill_run_id: str | None = None
    topic_id: str | None = None
    creative_direction_snapshot_id: str | None = None
    proposal_revision: int = Field(ge=1)
    source_proposal_id: str | None = None
    availability: ProposalAvailabilityV2 = "open"
    application_count: int = Field(default=0, ge=0)
    latest_application: ProposalApplicationSummaryV2 | None = None
    materialization: ProposalMaterializationProjectionV2 | None = None
    guidance_session_id: str = Field(min_length=1, max_length=160)
    guidance_session_revision: int = Field(ge=1)
    actions: tuple[ProposalActionDescriptorV2, ...] = ()
    created_at: datetime
    updated_at: datetime


class AgentCommandPlanActionRequestV2(_ConversationModel):
    action: Literal["confirm", "reject"]


class GuidedActionApplyRequestV2(_ConversationModel):
    confirmed: bool = True
    action: Literal["set_creative_authority"] | None = None
    authority: CreativeAuthorityV2 | None = None
    expected_session_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_authority_action(self) -> "GuidedActionApplyRequestV2":
        authority_values = (self.authority, self.expected_session_revision)
        if self.action == "set_creative_authority":
            if any(value is None for value in authority_values):
                raise ValueError(
                    "Creative-authority actions require authority and session revision."
                )
        elif any(value is not None for value in authority_values):
            raise ValueError("Only creative-authority actions accept authority fields.")
        return self


class AgentActionReceiptV2(_ConversationModel):
    receipt_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    plan_id: str | None = Field(default=None, max_length=160)
    action_id: str | None = Field(default=None, max_length=160)
    proposal_id: str | None = Field(default=None, max_length=160)
    proposal_option_id: str | None = Field(default=None, max_length=160)
    proposal_action: ProposalActionTypeV2 | None = None
    actor_kind: Literal["agent", "user", "system"] = "system"
    idempotency_key: str | None = Field(default=None, max_length=256)
    status: Literal[
        "applied",
        "applied_with_run_error",
        "not_applied",
        "superseded",
        "rejected",
        "failed",
    ]
    summary: str = Field(min_length=1, max_length=4_000)
    created_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    updated_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    deleted_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    created_binding_ids: tuple[str, ...] = Field(default=(), max_length=64)
    deleted_binding_ids: tuple[str, ...] = Field(default=(), max_length=64)
    queued_execution_ids: tuple[str, ...] = Field(default=(), max_length=32)
    run_queue_errors: tuple[str, ...] = Field(default=(), max_length=32)
    operation_results: tuple[AgentOperationResultV2, ...] = Field(
        default=(),
        max_length=8,
    )
    workflow_revision: int = Field(ge=1)
    before_workflow_revision: int | None = Field(default=None, ge=1)
    placement_hints: tuple[AgentPlacementHintV2, ...] = Field(
        default=(),
        max_length=32,
    )
    continuation_turn_id: str | None = Field(default=None, max_length=160)
    superseded_by: str | None = Field(default=None, max_length=160)
    error_code: str | None = Field(default=None, max_length=160)
    error_message: str | None = Field(default=None, max_length=1_024)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentCommandSubmissionV2(_ConversationModel):
    plan: AgentCommandPlanV2
    receipt: AgentActionReceiptV2 | None = None


class VideoSkillRunV2(_ConversationModel):
    skill_run_id: str
    workflow_id: str
    skill_id: str
    skill_version: str
    source_skill_run_id: str | None = None
    status: Literal["active", "superseded"] = "active"
    active_creative_direction_snapshot_id: str | None = None
    public_skill: VideoSkillPublicDetailV2 | None = None
    created_at: datetime
    updated_at: datetime | None = None


class VideoSkillRunCreateRequestV2(_ConversationModel):
    skill_id: str
    skill_version: str
    source_skill_run_id: str | None = None
