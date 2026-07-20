from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.asset_library import AssetReference
from app.schemas.canvas_targets import CanvasTargetReference

VisibleAgent = Literal[
    "creative_director",
    "script_writer",
    "character_designer",
    "scene_designer",
    "storyboard_artist",
    "video_director",
    "sound_director",
    "final_composition_assistant",
]
ConversationStatus = Literal["active", "archived"]
ConversationEventType = Literal[
    "agent_message",
    "agent_handoff",
    "node_prompt_updated",
    "item_prompt_updated",
    "execution_started",
    "revision_started",
    "revision_waiting",
    "revision_completed",
    "revision_failed",
    "clarification_requested",
    "conversation_memory_updated",
    "director_context_updated",
    "specialist_result",
    "suggested_action",
    "action_applied",
    "action_rejected",
    "error",
]
SuggestedActionType = Literal[
    "apply_prompt_to_node",
    "optimize_node_prompt",
    "run_node",
    "revise_node_asset",
    "update_director_context",
    "create_workflow",
]
SuggestedActionStatus = Literal["pending", "applied", "rejected", "failed"]

VISIBLE_AGENTS: set[str] = set(VisibleAgent.__args__)  # type: ignore[attr-defined]
HIDDEN_AGENT_ALIASES = {"hidden_director", "director", "director_agent"}


class NodeReference(BaseModel):
    node_id: str
    node_type: str | None = None
    mention_text: str | None = None
    source: Literal["mention", "selected_node", "inferred"] = "mention"

    @field_validator("node_id")
    @classmethod
    def strip_node_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("node_id must not be blank")
        return value

    @field_validator("node_type", "mention_text")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class AgentConversationEvent(BaseModel):
    event_id: str
    conversation_id: str
    event_type: ConversationEventType
    speaker_agent: VisibleAgent | None = None
    target_agent: VisibleAgent | None = None
    workflow_id: str | None = None
    target_node_id: str | None = None
    text: str
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SuggestedAction(BaseModel):
    action_id: str
    conversation_id: str
    action_type: SuggestedActionType
    status: SuggestedActionStatus = "pending"
    speaker_agent: VisibleAgent
    workflow_id: str | None = None
    target_node_id: str | None = None
    title: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationMemory(BaseModel):
    workflow_id: str | None = None
    conversation_id: str
    focus_target: dict[str, Any] | None = None
    recent_targets: list[dict[str, Any]] = Field(default_factory=list)
    recent_actions: list[dict[str, Any]] = Field(default_factory=list)
    recent_user_preferences: dict[str, Any] = Field(default_factory=dict)
    last_director_decision: dict[str, Any] | None = None
    last_specialist_result_summary: dict[str, Any] | None = None
    open_revisions: list[dict[str, Any]] = Field(default_factory=list)
    active_executions: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: str


class AgentConversation(BaseModel):
    conversation_id: str
    workflow_id: str | None = None
    focus_node_id: str | None = None
    topic: str
    status: ConversationStatus = "active"
    created_at: str
    updated_at: str
    memory: ConversationMemory | None = None
    events: list[AgentConversationEvent] = Field(default_factory=list)
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)


class AgentConversationCreateRequest(BaseModel):
    workflow_id: str | None = None
    focus_node_id: str | None = None
    topic: str = Field(default="Creative conversation", min_length=1, max_length=200)

    @field_validator("topic")
    @classmethod
    def strip_topic(cls, value: str) -> str:
        return value.strip()


class AgentConversationListResponse(BaseModel):
    items: list[AgentConversation]


class AgentConversationMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    agent_mentions: list[str] = Field(default_factory=list)
    node_references: list[NodeReference] = Field(default_factory=list)
    target_references: list[CanvasTargetReference] = Field(default_factory=list)
    asset_references: list[AssetReference] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class AgentConversationEventsResponse(BaseModel):
    conversation_id: str
    events: list[AgentConversationEvent] = Field(default_factory=list)
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)


class AgentConversationActionResponse(BaseModel):
    conversation_id: str
    events: list[AgentConversationEvent] = Field(default_factory=list)
    action: SuggestedAction


class AgentConversationRejectActionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1_000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None
