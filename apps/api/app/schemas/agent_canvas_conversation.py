"""Durable conversation, proposal, and Video Skill contracts for Agent Canvas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.agent_operation_contexts import AgentCanvasSpecialistName
from app.schemas.agent_canvas_commands import AgentPlacementHintV2
from app.schemas.agent_canvas_creative_session import (
    CreativeSessionStateV2,
    GuidedDeliveryActionV2,
    ProposedDraftReferenceV2,
)
from app.schemas.agent_runtime import (
    AgentCommandPlanV2,
    AgentOperationResultV2,
    AgentPrepareCompositionResultV2,
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


class ChatTurnV2(_ConversationModel):
    turn_id: str
    workflow_id: str
    conversation_id: str
    status: Literal["queued", "running", "completed", "failed"]
    turn_kind: Literal["message", "proposal_action", "command_action"]
    request: dict[str, JsonValue]
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
    guided_actions: tuple[GuidedDeliveryActionV2, ...] = Field(
        default=(),
        max_length=8,
    )
    created_at: datetime


class ChatTimelineListResponseV2(_ConversationModel):
    workflow_id: str
    conversation_id: str | None
    creative_session: CreativeSessionStateV2 | None = None
    items: tuple[ChatTimelineEntryV2, ...] = ()
    next_cursor: int = Field(ge=0)


class ConceptOptionRecordV2(_ConversationModel):
    option_id: str
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(min_length=1, max_length=8_192)


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

    @model_validator(mode="after")
    def validate_unique_option_ids(self) -> "ConceptProposalCreateV2":
        option_ids = tuple(option.option_id for option in self.options)
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("Concept option IDs must be unique within a proposal.")
        return self


class ConceptProposalV2(ConceptProposalCreateV2):
    proposal_id: str
    workflow_id: str
    turn_id: str
    video_skill_run_id: str | None = None
    proposal_revision: int = Field(ge=1)
    source_proposal_id: str | None = None
    status: Literal["pending", "selected", "revised", "skipped"]
    selected_option_id: str | None = None
    selection_actor: Literal["user", "agent"] | None = None
    created_at: datetime
    updated_at: datetime


class ProposalActionRequestV2(_ConversationModel):
    action: Literal["select", "revise", "skip"]
    option_id: str | None = None
    next_action: Literal["generate_now", "continue_planning"] | None = None
    instruction: str | None = Field(default=None, max_length=8_192)
    position: dict[str, float] | None = None
    accepted_references: tuple[ProposedDraftReferenceV2, ...] | None = Field(
        default=None,
        max_length=64,
    )

    @model_validator(mode="after")
    def validate_action(self) -> "ProposalActionRequestV2":
        if self.action == "select" and (not self.option_id or not self.next_action):
            raise ValueError("Selection requires option_id and next_action.")
        if self.action == "revise" and not self.instruction:
            raise ValueError("Revision requires instruction.")
        if self.action == "skip" and any(
            value is not None
            for value in (
                self.option_id,
                self.next_action,
                self.instruction,
                self.position,
                self.accepted_references,
            )
        ):
            raise ValueError("Skip does not accept selection or revision fields.")
        return self


class AgentCommandPlanActionRequestV2(_ConversationModel):
    action: Literal["confirm", "reject"]


class AgentActionReceiptV2(_ConversationModel):
    receipt_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    plan_id: str | None = Field(default=None, max_length=160)
    action_id: str | None = Field(default=None, max_length=160)
    status: Literal[
        "applied",
        "applied_with_run_error",
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
    composition_preparation: AgentPrepareCompositionResultV2 | None = None
    workflow_revision: int = Field(ge=1)
    placement_hints: tuple[AgentPlacementHintV2, ...] = Field(
        default=(),
        max_length=32,
    )
    continuation_turn_id: str | None = Field(default=None, max_length=160)
    error_code: str | None = Field(default=None, max_length=160)
    error_message: str | None = Field(default=None, max_length=1_024)


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
        "working",
        "completed",
        "skipped",
        "deferred",
        "reopened",
    ]
    outcome: str | None = None
    related_node_ids: tuple[str, ...] = ()
