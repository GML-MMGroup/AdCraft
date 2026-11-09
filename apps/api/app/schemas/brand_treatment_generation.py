"""Private current-step refinements of the unchanged public Treatment contract."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from app.schemas.brand_professional_mode import (
    BrandTreatmentSubstep,
    CreativeTreatmentOutputV1,
    CreativeTreatmentStepOutputV1,
    TreatmentCandidateV1,
    TreatmentSummaryCandidateV1,
    BrandProductionRequirementsV1,
)
from app.schemas.brand_treatment_detail import (
    TREATMENT_SECTION_KEYS,
    TreatmentDetailV1,
    TreatmentSectionV1,
)


class CharacterProductionRequirementsV1(BrandProductionRequirementsV1):
    """Character authoring cannot acquire scene or prop authority."""

    scene_presence: Literal["unspecified"] = "unspecified"
    scenes: tuple[()] = ()
    scene_sources: tuple[()] = ()
    prop_presence: Literal["unspecified"] = "unspecified"
    prop_sources: tuple[()] = ()


class SceneProductionRequirementsV1(BrandProductionRequirementsV1):
    """Scene authoring preserves the confirmed character roster."""

    character_count: None = None
    characters: tuple[()] = ()
    character_sources: tuple[()] = ()


class SelectedTreatmentStepV1(CreativeTreatmentStepOutputV1):
    options: tuple[TreatmentCandidateV1, ...] = Field(min_length=1, max_length=1)


class CreativeTreatmentDetailOutputV1(CreativeTreatmentOutputV1):
    step: SelectedTreatmentStepV1


@lru_cache(maxsize=16)
def treatment_output_model(
    step_key: BrandTreatmentSubstep,
    option_count: int = 3,
) -> type[CreativeTreatmentOutputV1]:
    """Expose current-step keys/counts to the model while retaining all validators."""
    required = dict(TREATMENT_SECTION_KEYS).get(step_key)
    if required is None:
        raise ValueError("A known current Treatment step is required.")
    prefix = f"Treatment{step_key.title()}"
    section_model = create_model(
        f"{prefix}SectionV1",
        __base__=TreatmentSectionV1,
        key=(Literal[required], ...),
    )
    detail_model = create_model(
        f"{prefix}DetailV1",
        __base__=TreatmentDetailV1,
        sections=(
            tuple[section_model, ...],
            Field(
                min_length=len(required),
                max_length=len(required),
                description=f"Include each required key exactly once: {', '.join(required)}.",
            ),
        ),
        **(
            {
                "production_requirements": (
                    CharacterProductionRequirementsV1
                    if step_key == "character"
                    else SceneProductionRequirementsV1,
                    ...,
                )
            }
            if step_key in {"character", "scene"}
            else {"production_requirements": (None, Field(default=None, exclude=True))}
        ),
    )
    candidate_model = create_model(
        f"{prefix}CandidateV1", __base__=TreatmentCandidateV1, detail=(detail_model, ...)
    )
    step_model = create_model(
        f"{prefix}StepV1",
        __base__=SelectedTreatmentStepV1 if option_count == 1 else CreativeTreatmentStepOutputV1,
        step_key=(Literal[step_key], ...),
        options=(
            tuple[candidate_model, ...],
            Field(min_length=option_count, max_length=option_count),
        ),
    )
    return create_model(
        f"{prefix}OutputV1",
        __base__=CreativeTreatmentDetailOutputV1
        if option_count == 1
        else CreativeTreatmentOutputV1,
        step=(step_model, ...),
    )


@lru_cache(maxsize=8)
def treatment_summary_model(step_key: BrandTreatmentSubstep) -> type[CreativeTreatmentOutputV1]:
    """Request only three summaries; detailed candidates remain a legacy read contract."""
    if step_key not in dict(TREATMENT_SECTION_KEYS):
        raise ValueError("A known current Treatment step is required.")
    step_model = create_model(
        f"Treatment{step_key.title()}SummaryStepV1",
        __base__=CreativeTreatmentStepOutputV1,
        step_key=(Literal[step_key], ...),
        options=(tuple[TreatmentSummaryCandidateV1, ...], Field(min_length=3, max_length=3)),
    )
    return create_model(
        f"Treatment{step_key.title()}SummaryOutputV1",
        __base__=CreativeTreatmentOutputV1,
        step=(step_model, ...),
    )


class StoryDirectionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=48)
    hypothesis: str = Field(
        min_length=1,
        max_length=240,
        description="One sentence telling the complete story, including the turn or ending.",
    )


class StoryDirectionsV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: tuple[StoryDirectionV1, ...] = Field(min_length=3, max_length=3)


def hypothesis_output_model() -> type[StoryDirectionsV1]:
    return StoryDirectionsV1
