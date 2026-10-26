"""Executable creative content beneath concise Brand choice labels."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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

    @model_validator(mode="after")
    def unique_sections(self) -> "TreatmentDetailV1":
        if len({section.key for section in self.sections}) != len(self.sections):
            raise ValueError("Treatment section keys must be unique.")
        return self

    def validate_step(self, step_key: str) -> None:
        required = dict(TREATMENT_SECTION_KEYS).get(step_key)
        if required is None or {section.key for section in self.sections} != set(required):
            raise ValueError(f"Treatment {step_key} requires sections: {required}.")

    def render(self) -> str:
        return "\n\n".join(f"{section.title}\n{section.text}" for section in self.sections)
