from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.canvas_targets import NormalizedCanvasTarget

SpecialistAgentName = Literal[
    "script_writer",
    "character_designer",
    "scene_designer",
    "storyboard_artist",
    "video_director",
    "sound_director",
]
SpecialistResultType = Literal[
    "revised_node_prompt",
    "revised_item_prompt",
    "revision_instruction",
    "quality_notes",
    "reference_requirements",
]


class SpecialistInvocationRequest(BaseModel):
    workflow_id: str
    conversation_id: str
    specialist: SpecialistAgentName
    action: str
    target: NormalizedCanvasTarget
    user_instruction: str
    current_prompt: str | None = None
    director_context_summary: dict[str, Any] = Field(default_factory=dict)
    script_context_summary: dict[str, Any] = Field(default_factory=dict)
    target_item_context: dict[str, Any] = Field(default_factory=dict)
    target_asset_summary: dict[str, Any] = Field(default_factory=dict)
    reference_asset_summary: list[dict[str, Any]] = Field(default_factory=list)
    memory_summary: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)

    @field_validator("workflow_id", "conversation_id", "action", "user_instruction")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("current_prompt")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @property
    def require_real_specialist(self) -> bool:
        return bool(
            self.constraints.get("require_real_specialist")
            or self.constraints.get("requires_real_specialist")
        )


class SpecialistResult(BaseModel):
    specialist: SpecialistAgentName
    target: NormalizedCanvasTarget
    result_type: SpecialistResultType
    revised_prompt: str | None = None
    negative_prompt: str | None = None
    revision_instruction: str | None = None
    quality_notes: list[str] = Field(default_factory=list)
    reference_requirements: list[str] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    mock_mode: bool = False

    @field_validator("revised_prompt", "negative_prompt", "revision_instruction")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("quality_notes", "reference_requirements")
    @classmethod
    def strip_text_list(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @model_validator(mode="after")
    def validate_required_payload(self) -> "SpecialistResult":
        if self.result_type in {"revised_node_prompt", "revised_item_prompt"}:
            if not self.revised_prompt:
                raise ValueError("revised prompt result requires revised_prompt")
        if self.result_type == "revision_instruction" and not self.revision_instruction:
            raise ValueError("revision_instruction result requires revision_instruction")
        if self.result_type == "quality_notes" and not self.quality_notes:
            raise ValueError("quality_notes result requires quality_notes")
        if self.result_type == "reference_requirements" and not self.reference_requirements:
            raise ValueError("reference_requirements result requires reference_requirements")
        return self


class SpecialistAgentOutcome(BaseModel):
    result: SpecialistResult
    used_fallback: bool = False
    model_id: str | None = None
