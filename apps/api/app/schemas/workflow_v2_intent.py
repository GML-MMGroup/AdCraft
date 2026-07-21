from __future__ import annotations

import re
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, Field, field_validator, model_validator


V2_INTENT_CONTRACT_VERSION = "v2-intent-contract-1"
V2_MAX_INTENT_INVENTORY_ITEMS = 12
V2PlanningFieldState: TypeAlias = Literal["explicit", "unspecified", "unknown"]

V2_INTENT_ERROR_CODES = {
    "v2_intent_schema_invalid",
    "v2_intent_validation_failed",
    "v2_intent_repair_failed",
    "v2_intent_fallback_failed",
    "v2_intent_clarification_required",
    "missing_explicit_source_span",
    "explicit_source_span_not_found",
    "character_count_mismatch",
    "character_gender_mismatch",
    "missing_explicit_scene",
    "scene_count_mismatch",
    "shot_count_mismatch",
    "script_intent_count_mismatch",
    "expert_brief_intent_count_mismatch",
    "script_product_id_set_mismatch",
    "script_character_id_set_mismatch",
    "script_scene_id_set_mismatch",
    "script_inventory_usage_missing",
    "script_character_attribute_mismatch",
    "script_scene_attribute_mismatch",
    "expert_brief_product_id_set_mismatch",
    "expert_brief_character_id_set_mismatch",
    "expert_brief_scene_id_set_mismatch",
    "product_count_out_of_bounds",
    "character_count_out_of_bounds",
    "scene_count_out_of_bounds",
    "duplicate_product_id",
    "duplicate_character_id",
    "duplicate_scene_id",
}

_SCENE_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SCENE_KIND_SEPARATOR_PATTERN = re.compile(r"[^a-z0-9]+")


def _normalize_english_scene_kind(value: str) -> str:
    normalized = _SCENE_KIND_SEPARATOR_PATTERN.sub("_", value.strip().lower()).strip("_")
    if not _SCENE_KIND_PATTERN.fullmatch(normalized):
        raise ValueError("scene kind must be an English slug")
    return normalized


class V2IntentSourceInfo(BaseModel):
    source: Literal["explicit", "inferred", "default"]
    source_span: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""

    @field_validator("source_span", "reason", mode="after")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_provenance(self) -> "V2IntentSourceInfo":
        if not self.reason:
            raise ValueError("intent facts require reason")
        if self.source == "explicit" and not self.source_span:
            raise ValueError("explicit intent facts require source_span")
        return self


class V2PlanningSource(BaseModel):
    origin: Literal["user_message", "structured_request", "input_asset"]
    source_span: str | None = Field(default=None, max_length=500)
    message_index: int | None = Field(default=None, ge=0)

    @field_validator("source_span", mode="after")
    @classmethod
    def strip_source_span(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class V2PlanningCountFact(BaseModel):
    state: V2PlanningFieldState
    value: int | None = Field(default=None, ge=0)
    source: V2PlanningSource | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "V2PlanningCountFact":
        if self.state == "explicit" and (self.value is None or self.source is None):
            raise ValueError("explicit planning facts require a value and source")
        if self.state == "unspecified" and (self.value is not None or self.source is not None):
            raise ValueError("unspecified planning facts must not include a value or source")
        return self


class V2PlanningEntitySeed(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    source: V2PlanningSource | None = None

    @field_validator("display_name", "description", mode="after")
    @classmethod
    def strip_entity_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class V2PlanningInventoryFact(BaseModel):
    state: V2PlanningFieldState
    requested_count: int | None = Field(default=None, ge=0)
    items: list[V2PlanningEntitySeed] = Field(
        default_factory=list, max_length=V2_MAX_INTENT_INVENTORY_ITEMS
    )
    source: V2PlanningSource | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "V2PlanningInventoryFact":
        if self.state == "explicit" and (self.requested_count is None or self.source is None):
            raise ValueError("explicit planning facts require a value and source")
        if self.state == "unspecified" and (
            self.requested_count is not None or self.items or self.source is not None
        ):
            raise ValueError("unspecified planning facts must not include values or a source")
        if (
            self.requested_count is not None
            and self.items
            and len(self.items) > self.requested_count
        ):
            raise ValueError("planning inventory items cannot exceed requested_count")
        return self


class V2PlanningProductFact(BaseModel):
    state: V2PlanningFieldState
    identity: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=1_000)
    source: V2PlanningSource | None = None

    @field_validator("identity", "description", mode="after")
    @classmethod
    def strip_product_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_state(self) -> "V2PlanningProductFact":
        if self.state == "explicit" and (self.identity is None or self.source is None):
            raise ValueError("explicit planning facts require a value and source")
        if self.state == "unspecified" and (
            self.identity is not None or self.description is not None or self.source is not None
        ):
            raise ValueError("unspecified planning facts must not include values or a source")
        return self


class V2FrontDeskPlanningSeed(BaseModel):
    product: V2PlanningProductFact
    characters: V2PlanningInventoryFact
    scenes: V2PlanningInventoryFact
    storyboard_shot_count: V2PlanningCountFact


class _IntentFact(BaseModel):
    source: Literal["explicit", "inferred", "default"]
    source_span: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""

    @field_validator("source_span", "reason", mode="after")
    @classmethod
    def strip_fact_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_fact_provenance(self) -> "_IntentFact":
        V2IntentSourceInfo(
            source=self.source,
            source_span=self.source_span,
            confidence=self.confidence,
            reason=self.reason,
        )
        return self

    def source_info(self) -> V2IntentSourceInfo:
        return V2IntentSourceInfo(
            source=self.source,
            source_span=self.source_span,
            confidence=self.confidence,
            reason=self.reason,
        )


class V2IntentProduct(_IntentFact):
    product_id: str = "product-1"
    display_name: str
    category: str | None = None

    @field_validator("product_id", "display_name", mode="after")
    @classmethod
    def strip_product_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be empty")
        return stripped


class V2IntentCharacter(_IntentFact):
    character_id: str
    display_name: str
    gender: str | None = None
    role: str | None = "lead"

    @field_validator("character_id", "display_name", mode="after")
    @classmethod
    def strip_character_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be empty")
        return stripped

    @field_validator("gender", "role", mode="after")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip().lower()
        return stripped or None


class V2IntentScene(_IntentFact):
    scene_id: str
    display_name: str
    kind: str
    time_of_day: str | None = None
    setting_type: Literal["interior", "exterior"] | None = None

    @field_validator("scene_id", "display_name", mode="after")
    @classmethod
    def strip_scene_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be empty")
        return stripped

    @field_validator("kind", mode="after")
    @classmethod
    def normalize_scene_kind(cls, value: str) -> str:
        return _normalize_english_scene_kind(value)

    @field_validator("time_of_day", mode="after")
    @classmethod
    def strip_time_of_day(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip().lower()
        return stripped or None


class V2IntentStoryboard(_IntentFact):
    shot_count: int = Field(ge=1)


class V2IntentAudio(_IntentFact):
    audio_mode: Literal["none", "bgm_only", "full"] = "bgm_only"


class V2IntentPlan(BaseModel):
    intent_contract_version: str = V2_INTENT_CONTRACT_VERSION
    concept_mode: Literal[
        "product_only",
        "spokesperson_demo",
        "lifestyle_narrative",
        "unclassified",
    ] = "unclassified"
    products: list[V2IntentProduct] = Field(default_factory=list)
    characters: list[V2IntentCharacter] = Field(default_factory=list)
    scenes: list[V2IntentScene] = Field(default_factory=list)
    storyboard: V2IntentStoryboard
    audio: V2IntentAudio
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class V2ExplicitCharacterConstraint(BaseModel):
    gender: str | None = None
    source_span: str | None = None

    @field_validator("gender", "source_span", mode="after")
    @classmethod
    def strip_constraint_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip().lower() if value in {"male", "female"} else value.strip()
        return stripped or None


class V2ExplicitSceneConstraint(BaseModel):
    kind: str
    source_span: str
    time_of_day: str | None = None
    setting_type: Literal["interior", "exterior"] | None = None

    @field_validator("kind", mode="after")
    @classmethod
    def normalize_scene_kind(cls, value: str) -> str:
        return _normalize_english_scene_kind(value)

    @field_validator("source_span", mode="after")
    @classmethod
    def strip_source_span(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("source_span must not be empty")
        return stripped


class V2ExplicitConstraints(BaseModel):
    product_name: str | None = None
    product_source_span: str | None = None
    character_count: int | None = None
    characters: list[V2ExplicitCharacterConstraint] = Field(default_factory=list)
    scenes: list[V2ExplicitSceneConstraint] = Field(default_factory=list)
    scene_count: int | None = None
    storyboard_shot_count: int | None = None
    storyboard_shot_count_span: str | None = None
    duration_seconds: int | None = None
    duration_source_span: str | None = None
    aspect_ratio: str | None = None

    @field_validator(
        "product_name",
        "product_source_span",
        "storyboard_shot_count_span",
        "duration_source_span",
        "aspect_ratio",
        mode="after",
    )
    @classmethod
    def strip_optional_constraint_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class V2IntentValidationViolation(BaseModel):
    code: str
    message: str
    expected: Any = None
    actual: Any = None
    expected_kind: str | None = None
    source_span: str | None = None
    field_path: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class V2IntentValidationResult(BaseModel):
    valid: bool
    violations: list[V2IntentValidationViolation] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
