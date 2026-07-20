from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


CREATIVE_INVENTORY_VERSION = "v2-creative-inventory-1"


class CreativeInventorySourceMapEntry(BaseModel):
    source: str
    source_text: str | None = None


class _CreativeInventoryItem(BaseModel):
    item_id: str
    display_name: str
    source: Literal["explicit", "inferred", "default"] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_text: str | None = None

    @field_validator("item_id", "display_name", mode="after")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be empty")
        return stripped

    @field_validator("source_text", mode="after")
    @classmethod
    def strip_source_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def require_explicit_evidence(self) -> "_CreativeInventoryItem":
        if self.source == "explicit" and not self.source_text:
            raise ValueError("explicit inventory items require source_text")
        return self


class CreativeProductInventoryItem(_CreativeInventoryItem):
    category: str | None = None


class CreativeCharacterInventoryItem(_CreativeInventoryItem):
    gender: str | None = None
    role: str | None = None

    @field_validator("gender", mode="after")
    @classmethod
    def normalize_gender(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None


class CreativeSceneInventoryItem(_CreativeInventoryItem):
    location_type: str
    time_of_day: str | None = None
    setting_type: Literal["interior", "exterior"] | None = None


class CreativeInventorySpec(BaseModel):
    inventory_version: str = CREATIVE_INVENTORY_VERSION
    inventory_id: str
    products: list[CreativeProductInventoryItem] = Field(default_factory=list)
    characters: list[CreativeCharacterInventoryItem] = Field(default_factory=list)
    scenes: list[CreativeSceneInventoryItem] = Field(default_factory=list)
    storyboard_shot_count: int | None = None
    duration_seconds: int | None = None
    aspect_ratio: str | None = None
    source_map: dict[str, dict[str, Any]] = Field(default_factory=dict)
    warnings: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("source_map", mode="before")
    @classmethod
    def normalize_legacy_source_map(
        cls, value: dict[str, dict[str, Any]] | None
    ) -> dict[str, dict[str, Any]]:
        normalized: dict[str, dict[str, Any]] = {}
        for key, entry in (value or {}).items():
            payload = dict(entry)
            source = payload.get("source")
            if source == "explicit_user_prompt":
                payload["source"] = "explicit"
            normalized[str(key)] = payload
        return normalized

    @model_validator(mode="after")
    def require_unique_item_ids(self) -> "CreativeInventorySpec":
        for category in (self.products, self.characters, self.scenes):
            item_ids = [item.item_id for item in category]
            if len(item_ids) != len(set(item_ids)):
                raise ValueError("creative inventory item IDs must be unique per category")
        return self
