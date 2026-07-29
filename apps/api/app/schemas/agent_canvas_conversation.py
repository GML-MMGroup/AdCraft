"""Durable conversation, proposal, and Video Skill contracts for Agent Canvas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.agent_operation_contexts import AgentCanvasSpecialistName


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
    turn_kind: Literal["message", "proposal_action"]
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
    entry_type: Literal["message", "script_artifact"]
    speaker: Literal["user", "adcraft_video_agent"] | None
    content: str
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime


class ChatTimelineListResponseV2(_ConversationModel):
    workflow_id: str
    conversation_id: str | None
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


class ConceptProposalV2(ConceptProposalCreateV2):
    proposal_id: str
    workflow_id: str
    turn_id: str
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

    @model_validator(mode="after")
    def validate_action(self) -> "ProposalActionRequestV2":
        if self.action == "select" and (not self.option_id or not self.next_action):
            raise ValueError("Selection requires option_id and next_action.")
        if self.action == "revise" and not self.instruction:
            raise ValueError("Revision requires instruction.")
        if self.action == "skip" and any(
            value is not None
            for value in (self.option_id, self.next_action, self.instruction, self.position)
        ):
            raise ValueError("Skip does not accept selection or revision fields.")
        return self


class VideoSkillRunV2(_ConversationModel):
    skill_run_id: str
    workflow_id: str
    skill_id: str
    skill_version: str
    source_skill_run_id: str | None = None
    created_at: datetime


class VideoSkillRunCreateRequestV2(_ConversationModel):
    skill_id: str
    skill_version: str
    source_skill_run_id: str | None = None


class PlanningTopicStateV2(_ConversationModel):
    skill_run_id: str
    topic_id: str
    display_order: int = Field(ge=0)
    status: Literal["pending", "in_review", "resolved", "skipped", "not_required"]
    related_node_ids: tuple[str, ...] = ()
