"""Private current-step refinements of the unchanged public Treatment contract."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, create_model

from app.schemas.brand_professional_mode import (
    BrandTreatmentSubstep,
    CreativeTreatmentOutputV1,
    CreativeTreatmentStepOutputV1,
    TreatmentCandidateV1,
)
from app.schemas.brand_treatment_detail import (
    TREATMENT_SECTION_KEYS,
    TreatmentDetailV1,
    TreatmentSectionV1,
)


@lru_cache(maxsize=8)
def treatment_output_model(step_key: BrandTreatmentSubstep) -> type[CreativeTreatmentOutputV1]:
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
    )
    candidate_model = create_model(
        f"{prefix}CandidateV1", __base__=TreatmentCandidateV1, detail=(detail_model, ...)
    )
    step_model = create_model(
        f"{prefix}StepV1",
        __base__=CreativeTreatmentStepOutputV1,
        step_key=(Literal[step_key], ...),
        options=(tuple[candidate_model, ...], Field(min_length=3, max_length=3)),
    )
    return create_model(
        f"{prefix}OutputV1", __base__=CreativeTreatmentOutputV1, step=(step_model, ...)
    )
