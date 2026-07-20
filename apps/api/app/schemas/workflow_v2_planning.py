from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class V2ScriptShot(BaseModel):
    shot_id: str
    scene_id: str
    shot_index: int = Field(ge=1)
    product_ids: list[str] = Field(default_factory=list)
    character_ids: list[str] = Field(default_factory=list)
    scene_ids: list[str] = Field(default_factory=list)
    reference_item_ids: list[str] = Field(default_factory=list)
    description: str
    visual_prompt: str
    narration: str | None = None
    duration_seconds: int = Field(ge=1)

    @field_validator("shot_id", "scene_id", "description", "visual_prompt", mode="after")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value

    @field_validator(
        "product_ids", "character_ids", "scene_ids", "reference_item_ids", mode="after"
    )
    @classmethod
    def clean_reference_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item for item in (str(item).strip() for item in value) if item))

    @model_validator(mode="after")
    def normalize_reference_unions(self) -> "V2ScriptShot":
        self.scene_ids = [self.scene_id]
        self.reference_item_ids = list(
            dict.fromkeys([*self.product_ids, *self.character_ids, self.scene_id])
        )
        return self


class V2ScriptScene(BaseModel):
    scene_id: str
    title: str
    description: str
    location_id: str | None = None
    shot_ids: list[str] = Field(default_factory=list)
    duration_seconds: int = Field(ge=1)
    location_type: str | None = None
    time_of_day: str | None = None
    setting_type: Literal["interior", "exterior"] | None = None

    @field_validator("scene_id", "title", "description", mode="after")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value


class V2ScriptCharacter(BaseModel):
    character_id: str
    display_name: str
    description: str
    role: str
    visual_notes: str
    gender: str | None = None

    @field_validator(
        "character_id",
        "display_name",
        "description",
        "role",
        "visual_notes",
        mode="after",
    )
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value


class V2ScriptLocation(BaseModel):
    location_id: str
    display_name: str
    description: str
    visual_notes: str
    location_type: str | None = None
    time_of_day: str | None = None
    setting_type: Literal["interior", "exterior"] | None = None

    @field_validator(
        "location_id",
        "display_name",
        "description",
        "visual_notes",
        mode="after",
    )
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value


class V2ScriptPlan(BaseModel):
    script_plan_version: Literal[1] = 1
    script_brief_id: str
    script_version_id: str
    language: str
    script_title: str
    script_text: str
    scenes: list[V2ScriptScene] = Field(min_length=1)
    shots: list[V2ScriptShot] = Field(min_length=1)
    characters: list[V2ScriptCharacter] = Field(default_factory=list)
    locations: list[V2ScriptLocation] = Field(default_factory=list)
    product_beats: list[str] = Field(default_factory=list)
    tone: str
    visual_style: str
    duration_seconds: int = Field(ge=1)
    aspect_ratio: str
    materializer_mode: Literal["real", "mock"]
    model_id: str | None = None
    selected_skill_ids: list[str] = Field(default_factory=list)
    selected_skill_paths: list[str] = Field(default_factory=list)
    skill_context_warnings: list[dict[str, Any]] = Field(default_factory=list)
    quality_notes: list[str] = Field(default_factory=list)
    materializer_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator(
        "script_brief_id",
        "script_version_id",
        "language",
        "script_title",
        "script_text",
        "tone",
        "visual_style",
        "aspect_ratio",
        mode="after",
    )
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value


class _BaseExpertBrief(BaseModel):
    item_id: str
    display_name: str
    description: str
    item_prompt: str
    slot_prompts: dict[str, str]
    creative_brief: str | None = None
    asset_prompts: dict[str, str] = Field(default_factory=dict)
    specialist_quality_audit: dict[str, Any] = Field(default_factory=dict)
    source_scene_ids: list[str] = Field(default_factory=list)
    source_shot_ids: list[str] = Field(default_factory=list)
    source_skill_ids: list[str] = Field(default_factory=list)
    source_skill_paths: list[str] = Field(default_factory=list)
    brief_builder_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_specialist_prompt_layers(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        creative_brief = payload.get("creative_brief")
        item_prompt = payload.get("item_prompt")
        if not item_prompt and creative_brief:
            payload["item_prompt"] = creative_brief
        if not creative_brief and item_prompt:
            payload["creative_brief"] = item_prompt
        asset_prompts = payload.get("asset_prompts")
        slot_prompts = payload.get("slot_prompts")
        if not slot_prompts and isinstance(asset_prompts, dict):
            payload["slot_prompts"] = asset_prompts
        if not asset_prompts and isinstance(slot_prompts, dict):
            payload["asset_prompts"] = slot_prompts
        return payload

    @field_validator(
        "item_id",
        "display_name",
        "description",
        "item_prompt",
        mode="after",
    )
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value

    @field_validator("slot_prompts", mode="after")
    @classmethod
    def validate_slot_prompts(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for key, prompt in value.items():
            slot_type = str(key).strip()
            slot_prompt = str(prompt).strip()
            if not slot_type or not slot_prompt:
                raise ValueError("slot_prompts must contain non-empty slot prompts")
            cleaned[slot_type] = slot_prompt
        if not cleaned:
            raise ValueError("slot_prompts must not be empty")
        return cleaned

    @field_validator("creative_brief", mode="after")
    @classmethod
    def strip_optional_creative_brief(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("asset_prompts", mode="after")
    @classmethod
    def validate_asset_prompts(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for key, prompt in value.items():
            slot_type = str(key).strip()
            slot_prompt = str(prompt).strip()
            if slot_type and slot_prompt:
                cleaned[slot_type] = slot_prompt
        return cleaned

    @model_validator(mode="after")
    def sync_specialist_prompt_layers(self) -> "_BaseExpertBrief":
        if not self.creative_brief:
            self.creative_brief = self.item_prompt
        if not self.asset_prompts:
            self.asset_prompts = dict(self.slot_prompts)
        return self


class V2ProductBrief(_BaseExpertBrief):
    pass


class V2CharacterBrief(_BaseExpertBrief):
    pass


class V2SceneBrief(_BaseExpertBrief):
    pass


class V2BgmBrief(_BaseExpertBrief):
    duration_seconds: int = Field(ge=1)
    music_mood: str
    pace: str
    audio_mode: Literal["none", "bgm_only", "full"]

    @field_validator("music_mood", "pace", mode="after")
    @classmethod
    def strip_audio_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value


class V2ExpertBriefPlan(BaseModel):
    script_brief_id: str
    script_version_id: str
    product_briefs: list[V2ProductBrief] = Field(default_factory=list)
    character_briefs: list[V2CharacterBrief] = Field(default_factory=list)
    scene_briefs: list[V2SceneBrief] = Field(default_factory=list)
    bgm_brief: V2BgmBrief
    specialist_quality_audit: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("script_brief_id", "script_version_id", mode="after")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value

    @model_validator(mode="after")
    def require_front_stage_briefs(self) -> "V2ExpertBriefPlan":
        if not self.product_briefs:
            raise ValueError("product_briefs must not be empty")
        if not self.scene_briefs:
            raise ValueError("scene_briefs must not be empty")
        return self
