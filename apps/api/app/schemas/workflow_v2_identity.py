from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


IDENTITY_SPEC_VERSION = "v2-item-identity-spec-1"


class ProductIdentitySpec(BaseModel):
    spec_type: Literal["product"] = "product"
    product_name: str
    product_category: str
    recognizable_features: list[str] = Field(default_factory=list)
    silhouette: str
    material_finish: str | None = None
    brand_or_packaging_cues: list[str] = Field(default_factory=list)
    hero_selling_points: list[str] = Field(default_factory=list)
    forbidden_content: list[str] = Field(default_factory=list)

    @field_validator("product_name", "product_category", "silhouette", mode="after")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value


class CharacterIdentitySpec(BaseModel):
    spec_type: Literal["character"] = "character"
    character_id: str
    display_name: str
    age_impression: str
    body_type: str | None = None
    wardrobe: str
    silhouette: str
    facial_features: str
    hairstyle: str
    performance_role: str
    emotion_arc: str
    forbidden_content: list[str] = Field(default_factory=list)

    @field_validator(
        "character_id",
        "display_name",
        "age_impression",
        "wardrobe",
        "silhouette",
        "facial_features",
        "hairstyle",
        "performance_role",
        "emotion_arc",
        mode="after",
    )
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value


class SceneIdentitySpec(BaseModel):
    spec_type: Literal["scene"] = "scene"
    scene_id: str
    display_name: str
    location_type: str
    spatial_layout: str
    time_of_day: str
    lighting: str
    materials: list[str] = Field(default_factory=list)
    atmosphere: str
    weather_or_surface: str | None = None
    composition_zones: list[str] = Field(default_factory=list)
    forbidden_content: list[str] = Field(default_factory=list)

    @field_validator(
        "scene_id",
        "display_name",
        "location_type",
        "spatial_layout",
        "time_of_day",
        "lighting",
        "atmosphere",
        mode="after",
    )
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value
