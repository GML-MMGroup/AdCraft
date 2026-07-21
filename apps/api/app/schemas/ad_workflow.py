from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.schemas.asset_library import AssetReference
from app.schemas.assets import WorkflowAssetReference
from app.schemas.workflow_handles import (
    WorkflowNodeHandles,
    get_node_handles,
    normalize_edge_handles,
)

SUPPORTED_VIDEO_RESOLUTIONS = {"480p", "720p", "1080p"}
SUPPORTED_VIDEO_ASPECT_RATIOS = {"16:9", "9:16", "4:3", "3:4", "1:1", "21:9"}


class AdWorkflowGenerateRequest(BaseModel):
    product_name: str = Field(min_length=1, max_length=120)
    product_description: str = Field(min_length=1, max_length=1_000)
    core_selling_point: str | None = Field(default=None, max_length=500)
    target_audience: str = Field(min_length=1, max_length=500)
    campaign_goal: str = Field(default="Increase qualified interest", min_length=1, max_length=300)
    desired_emotion: str = Field(default="confident", min_length=1, max_length=120)
    duration_seconds: int = Field(default=30, ge=15, le=60)
    visual_style: str | None = Field(default=None, max_length=300)
    references: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=lambda: ["social"])
    selected_assets: list[WorkflowAssetReference] = Field(default_factory=list)
    asset_references: list[AssetReference] = Field(default_factory=list)
    library_entity_ids: list[str] = Field(default_factory=list)
    reference_mode: Literal["best_effort", "strict"] = "strict"
    skip_audio_agents: bool = False
    audio_mode: Literal["none", "bgm_only", "full"] = "bgm_only"
    output_resolution: str | None = None
    aspect_ratio: str | None = None

    @field_validator(
        "product_name",
        "product_description",
        "target_audience",
        "campaign_goal",
        "desired_emotion",
    )
    @classmethod
    def strip_non_empty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, channels: list[str]) -> list[str]:
        normalized = [channel.strip() for channel in channels if channel.strip()]
        if not normalized:
            raise ValueError("must contain at least one non-blank channel")
        return normalized

    @field_validator("core_selling_point", "visual_style")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("output_resolution")
    @classmethod
    def validate_output_resolution(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_VIDEO_RESOLUTIONS:
            raise ValueError(
                "output_resolution must be one of: "
                f"{', '.join(sorted(SUPPORTED_VIDEO_RESOLUTIONS))}"
            )
        return normalized

    @field_validator("aspect_ratio")
    @classmethod
    def validate_aspect_ratio(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().replace("：", ":")
        if normalized not in SUPPORTED_VIDEO_ASPECT_RATIOS:
            raise ValueError(
                f"aspect_ratio must be one of: {', '.join(sorted(SUPPORTED_VIDEO_ASPECT_RATIOS))}"
            )
        return normalized

    @field_validator("references")
    @classmethod
    def normalize_references(cls, references: list[str]) -> list[str]:
        return [reference.strip() for reference in references if reference.strip()]

    @field_validator("library_entity_ids")
    @classmethod
    def normalize_library_entity_ids(cls, entity_ids: list[str]) -> list[str]:
        return [
            entity_id
            for entity_id in dict.fromkeys(str(item).strip() for item in entity_ids)
            if entity_id
        ]


class WorkflowNode(BaseModel):
    id: str
    type: str
    title: str
    description: str
    content: dict[str, Any]
    output: dict[str, Any] = Field(default_factory=dict)
    status: Literal["completed", "pending", "waiting", "failed"]
    prompt: str | None = None
    override_prompt: str | None = None
    input_context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    input_assets: list[dict[str, Any]] = Field(default_factory=list)
    output_assets: list[dict[str, Any]] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    can_run_standalone: bool = True
    supports_override_prompt: bool = False
    handles: WorkflowNodeHandles = Field(default_factory=WorkflowNodeHandles)

    @model_validator(mode="after")
    def populate_handles(self) -> "WorkflowNode":
        if not self.handles.inputs and not self.handles.outputs:
            self.handles = get_node_handles(self.id)
        if not self.output and self.content:
            self.output = self.content
        return self


class WorkflowEdge(BaseModel):
    source: str
    target: str
    label: str | None = None
    source_handle: str = Field(
        default="",
        validation_alias=AliasChoices("source_handle", "sourceHandle"),
    )
    target_handle: str = Field(
        default="",
        validation_alias=AliasChoices("target_handle", "targetHandle"),
    )

    @model_validator(mode="after")
    def populate_handles(self) -> "WorkflowEdge":
        self.source_handle, self.target_handle = normalize_edge_handles(
            self.source,
            self.target,
            self.source_handle,
            self.target_handle,
            self.label,
        )
        return self

    @computed_field(return_type=str)
    @property
    def sourceHandle(self) -> str:
        return self.source_handle

    @computed_field(return_type=str)
    @property
    def targetHandle(self) -> str:
        return self.target_handle


class AdWorkflowResponse(BaseModel):
    workflow_id: str
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
