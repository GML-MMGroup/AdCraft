from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.workflow_v2_style import V2VisualStyleAudit, V2VisualStyleContract

PromptContractMaterializerMode = Literal["real", "fallback", "mock"]
WorkflowMediaType = Literal["image", "video", "audio"]


class _PromptContractBase(BaseModel):
    summary_prompt: str
    provider_prompt: str
    negative_prompt: str | None = None
    negative_constraints: str | None = None
    reference_asset_ids: list[str] = Field(default_factory=list)
    quality_notes: list[str] = Field(default_factory=list)
    warnings: list[dict[str, str]] = Field(default_factory=list)

    @field_validator("summary_prompt", "provider_prompt", mode="after")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value

    @field_validator("negative_prompt", "negative_constraints", mode="after")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("reference_asset_ids", "quality_notes", mode="after")
    @classmethod
    def clean_string_list(cls, value: list[str]) -> list[str]:
        return [item for item in [str(item).strip() for item in value] if item]


class _SpecialistPromptContract(_PromptContractBase):
    specialist_prompt: str

    @field_validator("specialist_prompt", mode="after")
    @classmethod
    def strip_specialist_prompt(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value


class V2ProductMainPromptPlan(_SpecialistPromptContract):
    layout_intent: Literal["single_product"]
    forbidden_layouts: list[Literal["multi_view", "grid", "contact_sheet", "collage"]] = Field(
        default_factory=list
    )


class V2ProductMultiViewPromptPlan(_SpecialistPromptContract):
    layout_intent: Literal["product_grid_2x2"]
    grid_layout: Literal["2x2"]
    view_count: Literal[4]
    same_product_required: Literal[True]
    must_use_reference_slot_type: Literal["product_main_image"]


class V2CharacterMainPromptPlan(_SpecialistPromptContract):
    layout_intent: Literal["single_character"]
    forbidden_layouts: list[
        Literal[
            "three_view",
            "turnaround",
            "multi_view",
            "grid",
            "sheet",
            "contact_sheet",
            "collage",
        ]
    ] = Field(default_factory=list)


class V2CharacterThreeViewPromptPlan(_SpecialistPromptContract):
    layout_intent: Literal["character_three_view"]
    required_views: list[Literal["front", "side", "back"]]
    same_identity_required: Literal[True]
    must_use_reference_slot_type: Literal["character_main_image"]

    @model_validator(mode="after")
    def require_front_side_back(self) -> "V2CharacterThreeViewPromptPlan":
        if set(self.required_views) != {"front", "side", "back"} or len(self.required_views) != 3:
            raise ValueError("required_views must contain exactly front, side, and back")
        return self


class V2SceneMainPromptPlan(_SpecialistPromptContract):
    layout_intent: Literal["single_scene"]
    forbidden_layouts: list[
        Literal["multi_view", "grid", "collage", "storyboard_sheet", "split_screen"]
    ] = Field(default_factory=list)


class V2SceneMultiViewPromptPlan(_SpecialistPromptContract):
    layout_intent: Literal["scene_grid_2x2"]
    grid_layout: Literal["2x2"]
    view_count: Literal[4]
    same_location_required: Literal[True]
    must_use_reference_slot_type: Literal["scene_main_image"]


class V2ShotCellPromptPlan(_SpecialistPromptContract):
    layout_intent: Literal["single_keyframe"]
    cell_role: Literal["establishing", "action", "detail", "payoff"]
    shot_id: str
    cell_index: Literal[1, 2, 3, 4]
    same_shot_continuity_required: Literal[True]
    forbidden_layouts: list[
        Literal["storyboard_sheet", "collage", "split_screen", "multi_panel", "text_labels"]
    ] = Field(default_factory=list)

    @field_validator("cell_role", mode="before")
    @classmethod
    def normalize_cell_role(cls, value: Any) -> Any:
        return {
            "opening": "establishing",
            "action_buildup": "action",
            "action_peak": "detail",
        }.get(value, value)

    @field_validator("shot_id", mode="after")
    @classmethod
    def strip_shot_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("shot_id must not be empty")
        return value


class V2ShotVideoTimeSegment(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    content: str

    @field_validator("content", mode="after")
    @classmethod
    def strip_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content must not be empty")
        return value


class V2ShotVideoPromptPlan(_PromptContractBase):
    storyboard_content: str
    dialogue: str
    audio_description: str
    voice_style: str
    video_negative_constraints: str
    time_segments: list[V2ShotVideoTimeSegment] = Field(min_length=1)
    desired_duration_seconds: int = Field(ge=1)
    provider_duration_seconds: Literal[5, 10]
    shot_cell_asset_ids: list[str] = Field(default_factory=list)

    @field_validator(
        "storyboard_content",
        "dialogue",
        "audio_description",
        "voice_style",
        "video_negative_constraints",
        mode="after",
    )
    @classmethod
    def strip_video_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value

    @field_validator("shot_cell_asset_ids", mode="after")
    @classmethod
    def clean_shot_cell_ids(cls, value: list[str]) -> list[str]:
        return [item for item in [str(item).strip() for item in value] if item]


V2PromptContractModel = (
    V2ProductMainPromptPlan
    | V2ProductMultiViewPromptPlan
    | V2CharacterMainPromptPlan
    | V2CharacterThreeViewPromptPlan
    | V2SceneMainPromptPlan
    | V2SceneMultiViewPromptPlan
    | V2ShotCellPromptPlan
    | V2ShotVideoPromptPlan
)


class V2CanonicalProviderPayload(BaseModel):
    workflow_id: str
    node_id: str
    item_id: str
    slot_id: str
    slot_type: str
    media_type: WorkflowMediaType
    provider_prompt: str
    negative_prompt: str | None = None
    negative_constraints: str | None = None
    reference_asset_ids: list[str] = Field(default_factory=list)
    provider_params: dict[str, Any] = Field(default_factory=dict)
    quality_contract: dict[str, Any]
    prompt_contract_name: str
    prompt_contract_version: str
    materializer_mode: PromptContractMaterializerMode
    model_id: str | None = None
    selected_skill_ids: list[str] = Field(default_factory=list)
    visual_style_contract: V2VisualStyleContract | None = None
    visual_style_audit: V2VisualStyleAudit | None = None

    @field_validator(
        "workflow_id",
        "node_id",
        "item_id",
        "slot_id",
        "slot_type",
        "provider_prompt",
        "prompt_contract_name",
        "prompt_contract_version",
        mode="after",
    )
    @classmethod
    def strip_required_payload_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value

    @field_validator("quality_contract", mode="after")
    @classmethod
    def require_quality_contract(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("quality_contract must not be empty")
        return value

    @model_validator(mode="after")
    def require_visual_style_for_visual_media(self) -> "V2CanonicalProviderPayload":
        is_visual = self.media_type in {"image", "video"}
        if is_visual and (self.visual_style_contract is None or self.visual_style_audit is None):
            raise ValueError("visual style contract and audit are required for visual media")
        if not is_visual and (
            self.visual_style_contract is not None or self.visual_style_audit is not None
        ):
            raise ValueError("visual style contract and audit must be absent for audio media")
        return self


class V2PromptContractRepairContext(BaseModel):
    contract_name: str
    slot_type: str
    validation_error_paths: list[str] = Field(default_factory=list)
    quality_error_code: str | None = None
    quality_error_message: str | None = None


class V2PromptContractValidationResult(BaseModel):
    status: Literal["passed", "failed"]
    contract_name: str
    error_code: str | None = None
    error_message: str | None = None
    warnings: list[dict[str, str]] = Field(default_factory=list)


_PROMPT_CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    "product_main_image": V2ProductMainPromptPlan,
    "product_multi_view_grid": V2ProductMultiViewPromptPlan,
    "character_main_image": V2CharacterMainPromptPlan,
    "character_three_view": V2CharacterThreeViewPromptPlan,
    "scene_main_image": V2SceneMainPromptPlan,
    "scene_multi_view_grid": V2SceneMultiViewPromptPlan,
    "shot_cell_1": V2ShotCellPromptPlan,
    "shot_cell_2": V2ShotCellPromptPlan,
    "shot_cell_3": V2ShotCellPromptPlan,
    "shot_cell_4": V2ShotCellPromptPlan,
    "shot_video_segment": V2ShotVideoPromptPlan,
}


def prompt_contract_model_for_slot(slot_type: str) -> type[BaseModel]:
    try:
        return _PROMPT_CONTRACT_MODELS[slot_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported V2 prompt contract slot_type: {slot_type}") from exc


def prompt_contract_name_for_slot(slot_type: str) -> str:
    return prompt_contract_model_for_slot(slot_type).__name__


def prompt_contract_version() -> str:
    return "v2-slot-prompt-contracts-16"
