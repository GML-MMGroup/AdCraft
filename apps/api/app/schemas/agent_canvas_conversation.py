"""Durable conversation, proposal, and Video Skill contracts for Agent Canvas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.agent_operation_contexts import AgentCanvasSpecialistName
from app.schemas.agent_canvas_commands import AgentPlacementHintV2
from app.schemas.agent_canvas_creative_session import (
    AdaptiveProductionRecipeV2,
    ConceptDraftSpecV2,
    CreationModeDecisionV2,
    CreativeSessionStateV2,
    GuidedDeliveryActionV2,
    ProposedDraftReferenceV2,
)
from app.schemas.agent_runtime import (
    AgentCommandPlanV2,
    AgentOperationResultV2,
)


class _ConversationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatMessageRequestV2(_ConversationModel):
    text: str = Field(min_length=1, max_length=32_768)
    mentioned_node_ids: tuple[str, ...] = Field(default=(), max_length=16)
    mentioned_image_asset_ids: tuple[str, ...] = Field(default=(), max_length=16)
    video_skill_run_id: str | None = Field(default=None, max_length=160)
    auto_continue: bool = False


class ChatTurnAcceptedV2(_ConversationModel):
    workflow_id: str
    conversation_id: str
    message_id: str | None
    turn_id: str
    status: Literal["queued"] = "queued"
    events_cursor: int = Field(ge=0)


class ContinuationDeliveryV2(_ConversationModel):
    continuation_id: str
    workflow_id: str
    conversation_id: str
    source_turn_id: str
    continuation_turn_id: str
    operation: str
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
    status: Literal["queued", "running", "completed", "failed"]
    turn_kind: Literal["message", "proposal_action", "command_action", "guided_action"]
    request: dict[str, JsonValue]
    creation_mode: CreationModeDecisionV2 | None = None
    recipe: AdaptiveProductionRecipeV2 | None = None
    continuation: ContinuationDeliveryV2 | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


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
    ]
    speaker: Literal["user", "adcraft_video_agent"] | None
    content: str
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    command_plan: AgentCommandPlanV2 | None = None
    action_receipt: "AgentActionReceiptV2 | None" = None
    created_at: datetime


class ChatTimelineListResponseV2(_ConversationModel):
    workflow_id: str
    conversation_id: str | None
    creative_session: CreativeSessionStateV2 | None = None
    continuations: tuple[ContinuationDeliveryV2, ...] = ()
    current_session_actions: tuple[GuidedDeliveryActionV2, ...] = Field(
        default=(),
        max_length=2,
    )
    items: tuple[ChatTimelineEntryV2, ...] = ()
    next_cursor: int = Field(ge=0)


class ConceptOptionRecordV2(_ConversationModel):
    option_id: str
    title: str = Field(min_length=1, max_length=256)
    summary_prompt: str = Field(
        min_length=1,
        max_length=8_192,
        validation_alias=AliasChoices("summary_prompt", "description"),
    )
    draft_spec: ConceptDraftSpecV2 | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def canonicalize_draft_spec(self) -> "ConceptOptionRecordV2":
        if self.draft_spec is None:
            object.__setattr__(
                self,
                "draft_spec",
                ConceptDraftSpecV2(prompt=self.summary_prompt),
            )
        return self

    @property
    def description(self) -> str:
        """Compatibility accessor for internal callers during the clean cut."""

        return self.summary_prompt


class ConceptProposalCreateV2(_ConversationModel):
    proposal_kind: Literal[
        "script",
        "product",
        "prop",
        "character",
        "scene",
        "storyboard",
        "video",
        "bgm",
    ]
    specialist_name: AgentCanvasSpecialistName
    options: tuple[ConceptOptionRecordV2, ...] = Field(min_length=1, max_length=4)
    proposed_references: tuple[ProposedDraftReferenceV2, ...] = Field(
        default=(),
        max_length=64,
    )
    recipe_topic_id: str | None = Field(default=None, max_length=160, exclude=True)
    target_node_id: str | None = Field(default=None, max_length=160)
    target_node_revision: int | None = Field(default=None, ge=1)
    proposal_purpose: str | None = Field(default=None, max_length=160)
    preserved_anchor_digest: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
        exclude=True,
    )

    @model_validator(mode="after")
    def validate_unique_option_ids(self) -> "ConceptProposalCreateV2":
        option_ids = tuple(option.option_id for option in self.options)
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("Concept option IDs must be unique within a proposal.")
        if (self.target_node_id is None) != (self.target_node_revision is None):
            raise ValueError("Targeted proposals require both target node ID and revision.")
        return self


ProposalAvailabilityV2 = Literal["open", "archived", "unavailable"]


class ProposalApplicationSummaryV2(_ConversationModel):
    application_id: str = Field(min_length=1, max_length=160)
    option_id: str = Field(min_length=1, max_length=160)
    generation_action: Literal["draft_only", "generate_now"]
    receipt_id: str = Field(min_length=1, max_length=160)
    created_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    queued_execution_ids: tuple[str, ...] = Field(default=(), max_length=32)
    created_at: datetime


class ConceptProposalV2(ConceptProposalCreateV2):
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
    available_actions: tuple[Literal["select", "revise", "archive", "reopen"], ...] = ()
    created_at: datetime
    updated_at: datetime


class ProposalActionRequestV2(_ConversationModel):
    action: Literal["select", "revise", "archive", "reopen"]
    option_id: str | None = None
    generation_action: Literal["draft_only", "generate_now"] | None = None
    instruction: str | None = Field(default=None, max_length=8_192)
    position: dict[str, float] | None = None
    accepted_references: tuple[ProposedDraftReferenceV2, ...] | None = Field(
        default=None,
        max_length=64,
    )
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

    @model_validator(mode="after")
    def validate_action(self) -> "ProposalActionRequestV2":
        if self.action == "select" and (not self.option_id or not self.generation_action):
            raise ValueError("Selection requires option_id and generation_action.")
        if self.action == "revise" and not self.instruction:
            raise ValueError("Revision requires instruction.")
        if self.action in {"archive", "reopen"} and any(
            value is not None
            for value in (
                self.option_id,
                self.generation_action,
                self.instruction,
                self.position,
                self.accepted_references,
                self.mutable_dimensions or None,
                self.replace_whole_concept or None,
            )
        ):
            raise ValueError("Archive and reopen do not accept selection or revision fields.")
        return self


class AgentCommandPlanActionRequestV2(_ConversationModel):
    action: Literal["confirm", "reject"]


class GuidedActionApplyRequestV2(_ConversationModel):
    confirmed: bool = True


class AgentActionReceiptV2(_ConversationModel):
    receipt_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    plan_id: str | None = Field(default=None, max_length=160)
    action_id: str | None = Field(default=None, max_length=160)
    proposal_id: str | None = Field(default=None, max_length=160)
    proposal_option_id: str | None = Field(default=None, max_length=160)
    proposal_generation_action: Literal["draft_only", "generate_now"] | None = None
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
    current_topic_id: str | None = None
    deferred_topic_ids: tuple[str, ...] = ()
    memory_revision: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime | None = None


class VideoSkillRunCreateRequestV2(_ConversationModel):
    skill_id: str
    skill_version: str
    source_skill_run_id: str | None = None


class PlanningTopicStateV2(_ConversationModel):
    skill_run_id: str
    topic_id: str
    topic_kind: str = "generic"
    display_order: int = Field(ge=0)
    required: bool = False
    specialist_name: AgentCanvasSpecialistName = "script_writer"
    status: Literal[
        "pending",
        "in_review",
        "resolved",
        "skipped",
        "not_required",
        "deferred",
    ]
    outcome: str | None = None
    related_node_ids: tuple[str, ...] = ()
