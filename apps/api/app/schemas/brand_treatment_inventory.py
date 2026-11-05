"""Source-grounded production facts authored alongside selected Treatment details."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

BrandTreatmentSubstep = Literal[
    "hook",
    "story",
    "character",
    "scene",
    "visual",
    "camera",
    "editing",
    "sound",
]


class BrandTreatmentSourceV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_key: BrandTreatmentSubstep
    section_key: str = Field(min_length=1, max_length=80)
    quote: str = Field(min_length=1, max_length=400)


class BrandProductionElementV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=400)
    sources: tuple[BrandTreatmentSourceV1, ...] = Field(min_length=1, max_length=4)


class BrandProductionRequirementsV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_count: int | None = Field(default=None, ge=0, le=32)
    characters: tuple[BrandProductionElementV1, ...] = Field(default=(), max_length=32)
    character_sources: tuple[BrandTreatmentSourceV1, ...] = Field(default=(), max_length=4)
    prop_presence: Literal["include", "exclude", "unspecified"] = "unspecified"
    prop_sources: tuple[BrandTreatmentSourceV1, ...] = Field(default=(), max_length=4)
    scene_presence: Literal["include", "exclude", "unspecified"] = "unspecified"
    scenes: tuple[BrandProductionElementV1, ...] = Field(default=(), max_length=32)
    scene_sources: tuple[BrandTreatmentSourceV1, ...] = Field(default=(), max_length=4)

    @model_validator(mode="after")
    def grounded_inventory(self) -> "BrandProductionRequirementsV1":
        if self.character_count is not None and (
            self.character_count != len(self.characters) or not self.character_sources
        ):
            raise ValueError("Resolved character count requires matching inventory and sources.")
        if self.prop_presence != "unspecified" and not self.prop_sources:
            raise ValueError("Resolved prop presence requires sources.")
        if self.scene_presence != "unspecified" and not self.scene_sources:
            raise ValueError("Resolved scene presence requires sources.")
        if (self.scene_presence == "include" and not self.scenes) or (
            self.scene_presence == "exclude" and self.scenes
        ):
            raise ValueError("Scene inventory must agree with its presence decision.")
        return self
