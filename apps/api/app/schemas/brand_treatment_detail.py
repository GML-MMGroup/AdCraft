"""Executable creative content beneath concise Brand choice labels."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.brand_treatment_inventory import BrandProductionRequirementsV1


TREATMENT_SECTION_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("hook", ("action_sequence", "product_role")),
    ("story", ("setup", "progression", "resolution", "product_role")),
    ("character", ("identity", "appearance", "performance")),
    ("scene", ("spaces", "boundaries")),
    ("visual", ("color_and_light", "materials", "wardrobe")),
    ("camera", ("people_camera", "product_shots", "prohibited_shots")),
    ("editing", ("opening", "middle", "ending")),
    ("sound", ("ambience", "effects", "music_entry", "progression")),
)


class TreatmentSectionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: Literal[
        "action_sequence",
        "product_role",
        "setup",
        "progression",
        "resolution",
        "identity",
        "appearance",
        "performance",
        "spaces",
        "boundaries",
        "color_and_light",
        "materials",
        "wardrobe",
        "people_camera",
        "product_shots",
        "prohibited_shots",
        "opening",
        "middle",
        "ending",
        "ambience",
        "effects",
        "music_entry",
    ]
    title: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=400)

    @field_validator("title", "text")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Treatment content must not be blank.")
        return value


class TreatmentDetailV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sections: tuple[TreatmentSectionV1, ...] = Field(min_length=2, max_length=4)
    # Omit absent metadata so historical document digests remain stable.
    production_requirements: BrandProductionRequirementsV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def unique_sections(self) -> "TreatmentDetailV1":
        if len({section.key for section in self.sections}) != len(self.sections):
            raise ValueError("Treatment section keys must be unique.")
        return self

    def validate_step(self, step_key: str) -> None:
        required = dict(TREATMENT_SECTION_KEYS).get(step_key)
        if required is None or {section.key for section in self.sections} != set(required):
            raise ValueError(f"Treatment {step_key} requires sections: {required}.")
        inventory = self.production_requirements
        if inventory is None:
            return
        if step_key not in {"character", "scene"}:
            raise ValueError("Production inventory belongs to character or scene details only.")
        if step_key == "character" and (
            inventory.scene_presence != "unspecified"
            or inventory.scenes
            or inventory.scene_sources
            or inventory.prop_presence != "unspecified"
            or inventory.prop_sources
        ):
            raise ValueError("Character details cannot define scene or prop authority.")
        if step_key == "scene" and (
            inventory.character_count is not None
            or inventory.characters
            or inventory.character_sources
        ):
            raise ValueError("Scene details cannot redefine the confirmed cast.")
        references = (
            *inventory.character_sources,
            *inventory.scene_sources,
            *inventory.prop_sources,
            *(
                source
                for element in (*inventory.characters, *inventory.scenes)
                for source in element.sources
            ),
        )
        sections = {section.key: section.text for section in self.sections}
        if any(
            source.step_key != step_key
            or not source.quote.strip()
            or source.quote not in sections.get(source.section_key, "")
            for source in references
        ):
            raise ValueError("Inventory sources must quote this step's authored sections exactly.")

    def render(self) -> str:
        return "\n\n".join(f"{section.title}\n{section.text}" for section in self.sections)
