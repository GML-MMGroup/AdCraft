"""A complete user-readable ad screenplay and its grounded production inventory."""

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.agent_canvas_requirements import DurationSecondsValueV1

from app.schemas.brand_treatment_inventory import (
    BrandProductionRequirementsV1,
    BrandProductionObjectV1,
)
from app.schemas.brand_treatment_detail import TreatmentMusicRequirementV1


class BrandScreenplayTimingV1(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    total_duration_seconds: DurationSecondsValueV1
    source_quote: str = Field(min_length=1, max_length=1000)


class BrandScreenplayV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    screenplay: str = Field(min_length=1, max_length=12000)
    production_requirements: BrandProductionRequirementsV1
    music_requirement: TreatmentMusicRequirementV1
    timing: BrandScreenplayTimingV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def grounded_screenplay(self) -> "BrandScreenplayV1":
        if not self.title.strip() or not self.screenplay.strip():
            raise ValueError("A complete nonblank screenplay is required.")
        if self.timing is not None and (
            not self.timing.source_quote.strip() or self.timing.source_quote not in self.screenplay
        ):
            raise ValueError("The timing source must quote the screenplay verbatim.")
        inventory = self.production_requirements
        if inventory.character_count is None or inventory.scene_presence == "unspecified":
            raise ValueError("The screenplay must establish its cast and locations.")
        sources = (
            *inventory.character_sources,
            *inventory.scene_sources,
            *inventory.prop_sources,
            *(
                source
                for item in (*inventory.characters, *inventory.scenes, *(inventory.objects or ()))
                for source in item.sources
            ),
        )
        if any(
            source.step_key != "story"
            or source.section_key != "screenplay"
            or not source.quote.strip()
            or source.quote not in self.screenplay
            for source in sources
        ):
            raise ValueError("Inventory sources must quote story.screenplay verbatim.")
        if self.music_requirement.source_quote not in self.screenplay:
            raise ValueError("Music intent must quote the screenplay verbatim.")
        return self

    def render(self) -> str:
        return f"# {self.title}\n\n{self.screenplay}"


class ScreenplayProductionRequirementsV1(BrandProductionRequirementsV1):
    objects: tuple[BrandProductionObjectV1, ...] = Field(max_length=32)


class BrandScreenplayGenerationV1(BrandScreenplayV1):
    """New authoring requires timing and inventory; stored screenplays remain readable."""

    production_requirements: ScreenplayProductionRequirementsV1
    timing: BrandScreenplayTimingV1
