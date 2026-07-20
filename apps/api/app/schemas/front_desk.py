from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.ad_workflow import AdWorkflowGenerateRequest
from app.schemas.asset_library import AssetReference
from app.schemas.assets import WorkflowAssetReference
from app.schemas.workflow_v2_intent import V2FrontDeskPlanningSeed


WorkflowAction = Literal["conversation", "create_workflow", "modify_node", "run_node"]
ConversationMode = Literal[
    "director_discussion",
    "specialist_handoff",
    "node_revision",
    "workflow_creation",
    "workflow_execution",
    "ordinary_conversation",
]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2_000)


class FrontDeskChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    history: list[ChatMessage] = Field(default_factory=list)
    skip_audio_agents: bool = False
    audio_mode: Literal["none", "bgm_only", "full"] | None = None
    selected_assets: list[WorkflowAssetReference] = Field(default_factory=list)
    asset_references: list[AssetReference] = Field(default_factory=list)
    input_asset_locators: list[str] = Field(default_factory=list)
    library_entity_ids: list[str] = Field(default_factory=list)
    reference_mode: Literal["best_effort", "strict"] = "strict"
    workflow_schema_version: int | None = None
    workflow_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class PartialAdWorkflowRequest(BaseModel):
    product_name: str | None = Field(default=None, max_length=120)
    product_description: str | None = Field(default=None, max_length=1_000)
    core_selling_point: str | None = Field(default=None, max_length=500)
    target_audience: str | None = Field(default=None, max_length=500)
    campaign_goal: str | None = Field(default=None, max_length=300)
    desired_emotion: str | None = Field(default=None, max_length=120)
    duration_seconds: int | str | None = None
    visual_style: str | None = Field(default=None, max_length=300)
    references: list[str] | str = Field(default_factory=list)
    channels: list[str] | str = Field(default_factory=list)
    output_resolution: str | None = None
    aspect_ratio: str | None = None
    audio_mode: str | None = None


class FrontDeskChatResponse(BaseModel):
    intent: Literal["conversation", "needs_clarification", "ready_for_workflow"]
    reply: str
    ad_request: AdWorkflowGenerateRequest | None = None
    missing_fields: list[str] = Field(default_factory=list)
    should_start_workflow: bool = False
    workflow_action: WorkflowAction = "conversation"
    target_node_type: str | None = None
    active_speaker: str = "creative_director"
    suggested_agent: str | None = None
    handoff_reason: str | None = None
    target_node_id: str | None = None
    target_asset_id: str | None = None
    conversation_mode: ConversationMode = "ordinary_conversation"
    v2_planning_seed: V2FrontDeskPlanningSeed | None = None

    @model_validator(mode="after")
    def validate_workflow_state(self) -> "FrontDeskChatResponse":
        if self.intent == "ready_for_workflow":
            if self.ad_request is None:
                raise ValueError("ready_for_workflow requires ad_request")
            self.should_start_workflow = True
            self.missing_fields = []
            self.workflow_action = "create_workflow"
            self.target_node_type = None
            self.target_node_id = None
            self.conversation_mode = "workflow_creation"
        else:
            self.ad_request = None
            self.should_start_workflow = False
            if self.workflow_action not in {"modify_node", "run_node"}:
                self.workflow_action = "conversation"
            if self.target_node_id is None:
                self.target_node_id = self.target_node_type
        return self


class FrontDeskIntentOutput(BaseModel):
    intent: Literal["conversation", "needs_clarification", "ready_for_workflow", "ad_request"]
    reply: str
    ad_request: PartialAdWorkflowRequest | None = None
    missing_fields: list[str] = Field(default_factory=list)
    workflow_action: WorkflowAction | None = None
    target_node_type: str | None = None
    active_speaker: str | None = None
    suggested_agent: str | None = None
    handoff_reason: str | None = None
    target_node_id: str | None = None
    target_asset_id: str | None = None
    conversation_mode: ConversationMode | None = None
    v2_planning_seed: V2FrontDeskPlanningSeed | None = None
